"""IngestResult -> Relate store.

Two properties this file exists to guarantee:

1. **Re-ingest is idempotent.** Ingesting the same export twice must leave the
   store byte-comparable (§8 stage 2: "Ingest twice -> identical counts"). Every
   write is a MERGE on a stable key, never a CREATE.

2. **A spool file is deletable only after verification.** Stage 10.1 prunes the
   spool at 3 days, but a job that exited 0 is not proof that the rows landed.
   `verify_present` re-reads the store and compares the key set it should hold
   against the key set it does hold. Only then may the caller delete.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

import relate

from .schema import Chat, IngestResult, Message, to_utc_string

_SCHEMA = (
    "CREATE INDEX msg_key IF NOT EXISTS FOR (m:Message) ON (m.key)",
    "CREATE INDEX thread_key IF NOT EXISTS FOR (t:Thread) ON (t.key)",
    "CREATE INDEX attachment_key IF NOT EXISTS FOR (a:Attachment) ON (a.key)",
    "CREATE INDEX correspondent_key IF NOT EXISTS FOR (c:Correspondent) ON (c.key)",
)

_MSG_CYPHER = (
    "UNWIND $rows AS row "
    "MERGE (m:Message {key: row.key}) "
    "SET m.platform = row.platform, m.chat_id = row.chat_id, "
    "    m.message_id = row.message_id, m.ts_utc = row.ts_utc, m.body = row.body, "
    "    m.has_attachments = row.has_attachments, m.is_self = row.is_self, "
    "    m.raw_kind = row.raw_kind, m.sender_name = row.sender_name, "
    "    m.sender_id = row.sender_id "
    "WITH m, row "
    "MERGE (t:Thread {key: row.thread_key}) "
    "SET t.platform = row.platform, t.title = row.thread_title, t.is_group = row.is_group "
    "MERGE (m)-[:IN]->(t)"
)

_REPLY_CYPHER = (
    "UNWIND $rows AS row "
    "MATCH (m:Message {key: row.key}) "
    "MATCH (r:Message {key: row.reply_to}) "
    "MERGE (m)-[:REPLY_TO]->(r)"
)

_ATTACH_CYPHER = (
    "UNWIND $rows AS row "
    "MATCH (m:Message {key: row.msg_key}) "
    "MERGE (a:Attachment {key: row.key}) "
    "SET a.filename_scrubbed = row.path, a.mime = row.mime, a.size = row.size "
    "MERGE (m)-[:HAS_ATTACHMENT]->(a)"
)

# Rows per statement. Large enough to amortise the round trip, small enough that
# one bad row does not discard an entire ingest.
BATCH_SIZE = 500

# Confidence at or above this is treated as a fact, and written as MATCHED_BY.
# Below it, the edge is POSSIBLY. §3.1: two edge types, never one — a wrong guess
# must look different from a known identity at a glance.
MATCH_THRESHOLD = 0.95

_CORRESPONDENT_CYPHER = (
    "UNWIND $rows AS row "
    "MERGE (c:Correspondent {key: row.key}) "
    "SET c.display_name = row.display_name, c.platform = row.platform, "
    "    c.handle = row.handle, c.email = row.email, c.phone_e164 = row.phone_e164 "
    "WITH c, row "
    "MATCH (t:Thread {key: row.thread_key}) "
    "MERGE (t)-[:WITH]->(c)"
)


# The label the UI shows, mirroring `PLATFORM_LABELS` in
# `app/ui/src/config/nodeTypes.js`. Duplicated deliberately: the title is built in
# Python at write time, and importing the UI's JS is not an option. If one changes,
# both change — the same duplication `paths.PLATFORM_FOLDERS` already carries.
PLATFORM_TITLE_LABELS = {
    "messenger": "Fcbk Mssgr",
    "telegram": "Telegram",
    "whatsapp": "WhatsApp",
    "linkedin": "LinkedIn",
    "email": "Email",
    "gmail": "Email",
    "imap": "Email",
    "outlook": "Outlook",
    "sms": "SMS",
}


def platform_title_label(platform: str) -> str:
    return PLATFORM_TITLE_LABELS.get((platform or "").lower(), platform or "")


def correspondent_key(platform: str, name: str) -> str:
    """Stable per (platform, person), on the **canonical** name.

    **Not scoped to the thread.** Keying by thread gave `David Sartori` four separate
    nodes — one per thread he appeared in — because Messenger's placeholder account
    shows up in 31 different threads. The row is still attached with `WITH` per
    thread; only the identity is shared, so a person who appears in ten threads is
    one node with ten `WITH` edges.

    The name is flattened first, so `Dave Sartori` and `david sartori` are one node
    rather than two. That fan-in is the whole point: fifteen threads with one person
    must read as fifteen edges into one node, not fifteen disconnected pairs.
    """
    from .canon import canonical

    record = canonical(name, kind="person")
    return f"{platform}:{record.key or name.strip()}"


def write_correspondents(
    conn: Any,
    result: IngestResult,
    *,
    owner: str | None = None,
    owner_forms: Iterable[str] | None = None,
) -> dict[str, int]:
    """Write one `Correspondent` per non-owner participant, attached with `WITH`.

    Called **after** `write()`, because `WITH` needs the Thread row to exist.

    `participant_names` is already populated by every adapter and was previously
    dropped. A placeholder or the Owner is skipped: a thread you sent messages into
    alone has correspondents, not a self-edge.

    **The Owner guard needs every form the Owner is known by on this platform.**
    `owner` alone was the bug: a run resolves the Owner once from Telegram and puts a
    user id in `self_id`, which matches no display name anywhere else, so the guard
    was inert on Messenger, LinkedIn, Email and WhatsApp — and the Owner was written
    as a Correspondent in 236 threads. `owner_forms` carries the display name, the
    id, the address and the phone; `canon.canonical` compares against all of them.

    Names are flattened through `canon` before they become keys, so `Dave Sartori`
    and `david sartori` are one node with two `WITH` edges rather than two nodes.
    """
    from .canon import canonical

    forms = [form for form in (owner_forms or ()) if form]
    if owner:
        forms.append(owner)

    rows: list[dict[str, Any]] = []
    for chat in result.chats:
        tkey = thread_key_for(chat)
        for name in chat.participant_names:
            clean = (name or "").strip()
            if not clean:
                continue

            record = canonical(clean, kind="person", owner=forms)
            # The Owner is never a Correspondent, on any platform, ever.
            if record.is_owner:
                continue
            # A placeholder is not a person. It is attached to a per-platform
            # pseudo-node so those threads cluster instead of floating unconnected.
            if record.is_placeholder:
                rows.append({
                    "key": f"{chat.platform}:{record.key}",
                    "display_name": record.display,
                    "platform": chat.platform,
                    "handle": record.display,
                    "email": None,
                    "phone_e164": None,
                    "thread_key": tkey,
                })
                continue

            # One row per (thread, person): the MERGE is on `key`, so a repeat across
            # threads attaches a second `WITH` edge to the same node rather than
            # minting a duplicate.
            rows.append({
                "key": f"{chat.platform}:{record.key}",
                "display_name": record.display,
                "platform": chat.platform,
                "handle": record.display,
                "email": record.key if record.evidence == "email" else None,
                "phone_e164": record.key if record.evidence == "phone" else None,
                "thread_key": tkey,
            })

    cur = conn.cursor()
    for batch in _chunks(rows):
        cur.execute(_CORRESPONDENT_CYPHER, {"rows": batch})
    conn.commit()
    return {"correspondents": len(rows)}


def thread_key_for(chat: Chat) -> str:
    return f"{chat.platform}:{chat.chat_id}"


def _thread_spans(result: IngestResult) -> dict[str, tuple[Any, Any]]:
    """`chat_id -> (first_ts, last_ts)`, from the messages themselves."""
    spans: dict[str, tuple[Any, Any]] = {}
    for message in result.messages:
        current = spans.get(message.chat_id)
        if current is None:
            spans[message.chat_id] = (message.ts_utc, message.ts_utc)
            continue
        first, last = current
        spans[message.chat_id] = (
            message.ts_utc if message.ts_utc < first else first,
            message.ts_utc if message.ts_utc > last else last,
        )
    return spans


def _title_ordinals(
    result: IngestResult,
    owner: str | None,
    spans: dict[str, tuple[Any, Any]],
) -> dict[str, int]:
    """`chat_id -> n`, for threads that share a person and a start date.

    `#n` exists so two threads with the same person starting the same day stay
    distinguishable. It is assigned by `chat_id`, never by ingest order, or the same
    store built twice would get different titles.

    A thread with no collision gets no ordinal, so the common case stays clean.
    """
    from .canon import canonical

    groups: dict[tuple[str, str, str], list[str]] = {}
    for chat in result.chats:
        start = _as_date(spans.get(chat.chat_id, (None, None))[0])
        if start is None:
            continue
        name = _thread_name(chat, owner, canonical)
        groups.setdefault((chat.platform, name, start.strftime("%m-%d-%Y")), []).append(
            chat.chat_id)

    ordinals: dict[str, int] = {}
    for chat_ids in groups.values():
        if len(chat_ids) < 2:
            continue
        for index, chat_id in enumerate(sorted(chat_ids), start=1):
            ordinals[chat_id] = index
    return ordinals


def _title_for(
    message: Message,
    chat: Chat | None,
    owner: str | None,
    spans: dict[str, tuple[Any, Any]],
    ordinals: dict[str, int],
) -> str:
    """The title for one message's thread. Same string for every message in it."""
    if chat is None:
        label = platform_title_label(message.platform)
        return f"{label}; {message.chat_id[-6:]}"
    first, last = spans.get(chat.chat_id, (None, None))
    return thread_display_title(
        chat, owner, first_ts=first, last_ts=last,
        ordinal=ordinals.get(chat.chat_id),
    )


def _is_owner_name(name: str, owner: str | None) -> bool:
    """Is this participant the Owner? Compared on the canonical form.

    `canon.canonical` resolves nicknames on both sides, so a profile saying
    `David Sartori` matches an export saying `Dave Sartori`.
    """
    from .canon import canonical

    if not owner:
        return False
    return canonical(name, owner=[owner]).is_owner


def thread_display_title(
    chat: Chat,
    owner: str | None = None,
    *,
    first_ts: Any = None,
    last_ts: Any = None,
    ordinal: int | None = None,
) -> str:
    """A human-readable title, always non-empty. **Display only.**

    The schema is two separators, so a group name or email subject that itself
    contains a date, `-`, `->` or `#2` is harmless — the date block is delimited,
    never merely trailing:

        <Platform>; <Name>; <MM-DD-YYYY>[-][>][ #n]

        SMS; Bryan Rodgers; 06-02-2026
        Facebook; Ryan Phillip; 02-13-2025->
        WhatsApp; +27 84 518 9029; 04-21-2026->
        LinkedIn; n8n Hackathon today - log in!🪐; 08-16-2025
        LinkedIn; Invoice due 08-16-2025; 08-16-2025

    Parse from the outside in — platform before the **first** `;`, date block after
    the **last** `;`, name between them. Never parse it for the platform key: the
    token is the display label, and the node's `platform` property is authoritative.

    **Why `->` and not an end date.** An end date changes on every ingest, because
    `max(ts)` moves. `->` changes at most once, ever: the first time a thread spans
    more than one day it becomes true and stays true. Stable label, still accurate.

    **Why the name is canonical.** The title is what makes the fan-in legible: three
    threads all reading `with Mary Olver` are obviously one conversation split across
    three chat ids. Raw spellings would hide that.

    A title is a label, not evidence. Inventing one from the counterparty is safe
    because §5.6 already treats that person as a fact of the export.
    """
    from .canon import canonical

    label = platform_title_label(chat.platform)
    name = _thread_name(chat, owner, canonical)
    block = _date_block(first_ts, last_ts)

    parts = [label, name]
    if block:
        parts.append(block)
    title = "; ".join(part for part in parts if part)
    if ordinal and ordinal > 1:
        title = f"{title} #{ordinal}"
    return title


def _thread_name(chat: Chat, owner: str | None, canonical) -> str:
    """The name half of the title: the group's own name, else the counterparty.

    A group's stated name wins outright — it is what the export says the group is
    called, and a participant's name standing in for it is indistinguishable from a
    1:1 thread.

    A 1:1 thread is named after its counterparty, canonicalised so that the same
    person's threads read alike. When there is no counterparty at all — the Telegram
    strangers with a `sender_id` and no name — the short id is the only true thing
    left to say.
    """
    stated = (chat.title or "").strip()
    if stated:
        return stated

    others = [n for n in chat.participant_names
              if n.strip() and not _is_owner_name(n, owner)]
    if not others:
        return chat.chat_id[-6:]

    names = [canonical(name, kind="person").display for name in others]
    if len(names) == 1:
        return names[0]
    if len(names) <= 3:
        return ", ".join(names)
    return f"{names[0]}, {names[1]} +{len(names) - 2}"


def _date_block(first_ts: Any, last_ts: Any) -> str:
    """`MM-DD-YYYY`, plus `->` when the thread spans more than one calendar day."""
    start = _as_date(first_ts)
    if start is None:
        return ""
    block = start.strftime("%m-%d-%Y")
    end = _as_date(last_ts)
    if end is not None and end.date() > start.date():
        block += "->"
    return block


def _as_date(value: Any):
    """Accept a datetime, a date, or the ISO string the store holds."""
    from datetime import date, datetime, timezone

    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def connect(store: str | Path) -> Any:
    path = Path(store)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = relate.connect(str(path))
    cur = conn.cursor()
    for statement in _SCHEMA:
        cur.execute(statement)
    return conn


def thread_key(message: Message) -> str:
    return f"{message.platform}:{message.chat_id}"


def _chunks(items: list[Any], size: int = BATCH_SIZE):
    for start in range(0, len(items), size):
        yield items[start:start + size]


def write(conn: Any, result: IngestResult, *, owner: str | None = None) -> dict[str, int]:
    """Write every message and attachment, batched with UNWIND.

    Idempotency is unchanged: every statement is a MERGE on a stable key, so a
    second run over the same input adds nothing. Batching only removes round trips
    (measured: per-row MERGE ran at 64-133 msg/s and degraded superlinearly).
    """
    chats_by_id = {c.chat_id: c for c in result.chats}
    cur = conn.cursor()

    # The title needs each thread's span, which is a property of its messages rather
    # than of the Chat record. Computed once here, before the row loop.
    spans = _thread_spans(result)
    ordinals = _title_ordinals(result, owner, spans)

    message_rows: list[dict[str, Any]] = []
    for message in result.messages:
        chat: Chat | None = chats_by_id.get(message.chat_id)
        message_rows.append({
            "key": message.key,
            "platform": message.platform,
            "chat_id": message.chat_id,
            "message_id": message.message_id,
            "ts_utc": to_utc_string(message.ts_utc),
            "body": message.body,
            "has_attachments": message.has_attachments,
            "is_self": message.is_self,
            "raw_kind": message.raw_kind,
            "sender_name": message.sender_name,
            "sender_id": message.sender_id,
            "thread_key": thread_key(message),
            "thread_title": _title_for(message, chat, owner, spans, ordinals),
            "is_group": chat.is_group if chat else False,
        })

    for batch in _chunks(message_rows):
        cur.execute(_MSG_CYPHER, {"rows": batch})

    # Replies second pass: the target message must exist before the edge can land.
    # A reply to a message outside the export window simply matches nothing, which
    # is why this is a separate statement rather than part of the message write.
    reply_rows = [
        {"key": m.key, "reply_to": m.reply_to}
        for m in result.messages if m.reply_to
    ]
    for batch in _chunks(reply_rows):
        cur.execute(_REPLY_CYPHER, {"rows": batch})

    attachment_rows = [
        {
            "msg_key": f"{a.platform}:{a.chat_id}:{a.message_id}",
            "key": a.key,
            "path": a.path,
            "mime": a.mime,
            "size": a.size,
        }
        for a in result.attachments
    ]
    for batch in _chunks(attachment_rows):
        cur.execute(_ATTACH_CYPHER, {"rows": batch})

    conn.commit()
    return {"messages": len(message_rows), "attachments": len(attachment_rows),
            "keys": {m.key for m in result.messages}}


def stored_keys(conn: Any, platform: str) -> set[str]:
    cur = conn.cursor()
    cur.execute("MATCH (m:Message) WHERE m.platform = $platform RETURN m.key", {"platform": platform})
    return {row["m.key"] for row in cur.fetchall()}


def verify_present(conn: Any, result: IngestResult) -> tuple[bool, dict[str, Any]]:
    """Is every key from this ingest actually in the store?

    This is the gate before pruning a spool file. A missing key means the ingest
    did not fully land, so the file must be kept and the failure reported.
    """
    expected = {m.key for m in result.messages}
    observed = stored_keys(conn, result.platform)
    missing = sorted(expected - observed)
    ok = not missing
    return ok, {
        "expected": len(expected),
        "present": len(expected & observed),
        "missing": len(missing),
        "missing_sample": missing[:10],
    }


def counts_by_kind(conn: Any, platform: str) -> dict[str, int]:
    """Non-text rows in the store, by raw_kind. Feeds the evidence/refusal panel."""
    cur = conn.cursor()
    cur.execute(
        "MATCH (m:Message) WHERE m.platform = $platform "
        "RETURN m.raw_kind AS kind, count(m) AS n",
        {"platform": platform},
    )
    return {row["kind"]: row["n"] for row in cur.fetchall()}


def ingest_file(
    store: str | Path,
    source: str | Path,
    *,
    parser,
    **parse_kwargs: Any,
) -> tuple[IngestResult, dict[str, int], dict[str, Any]]:
    """Parse -> write -> verify, in one call. Returns (result, written, verification)."""
    result = parser(source, **parse_kwargs)
    conn = connect(store)
    try:
        written = write(conn, result)
        ok, verification = verify_present(conn, result)
    finally:
        conn.close()
    verification["ok"] = ok
    return result, written, verification
