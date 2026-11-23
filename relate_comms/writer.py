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

from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

import relate

from .schema import Chat, IngestResult, Message, to_utc_string

_SCHEMA = (
    "CREATE INDEX msg_key IF NOT EXISTS FOR (m:Message) ON (m.key)",
    "CREATE INDEX thread_key IF NOT EXISTS FOR (t:Thread) ON (t.key)",
    "CREATE INDEX attachment_key IF NOT EXISTS FOR (a:Attachment) ON (a.key)",
    "CREATE INDEX correspondent_key IF NOT EXISTS FOR (c:Correspondent) ON (c.key)",
    # Named, not iterated over `canon.KINDS`, because this tuple is imported lazily at
    # connect time and an entity written unindexed is a silent per-ingest scan.
    "CREATE INDEX place_key IF NOT EXISTS FOR (p:Place) ON (p.key)",
    "CREATE INDEX organization_key IF NOT EXISTS FOR (o:Organization) ON (o.key)",
    "CREATE INDEX product_key IF NOT EXISTS FOR (p:Product) ON (p.key)",
    # The delta watermark: `max(ts_utc)` for one platform. Without this index that
    # query is a full scan of every message, which defeats the point of a delta run —
    # measured at 63 ms for 910 messages, i.e. linear and growing with the store.
    "CREATE INDEX msg_ts IF NOT EXISTS FOR (m:Message) ON (m.ts_utc)",
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
# Everything below it folds on a weaker rung in `link`, never on a drawn edge — the
# `POSSIBLY` edge was removed 2026-11-23 (see `link.py`'s header).
MATCH_THRESHOLD = 0.95

# One `Correspondent` per canonical name, **not** per (platform, name). The key is
# `person:<canonical>`, so the same person spelled the same way on Telegram and on
# Messenger is one node with two `WITH` edges. Placeholders are the exception and keep
# their platform prefix — see `write_correspondents`.
#
# **This statement writes only per-platform facts.** `handle_<p>` and `seen_<p>` are
# that platform's spelling and its first sighting; `email`/`phone_e164` are the first
# non-null. Everything *derived* from those — `platform`, `display_name`,
# `first_seen_utc`, `platforms`, `platform_label`, `:Merged` — is recomputed by
# `_reconcile` after the rows land.
#
# The split is not stylistic. Relate evaluates every row of an `UNWIND` against the
# node as it stood **before** the statement, so two rows for one key both read the old
# value and the last row wins. Accumulating in Cypher therefore cannot work; the
# derived properties have to be computed from the finished flat facts.
_CORRESPONDENT_CYPHER = (
    "UNWIND $rows AS row "
    "MERGE (c:Correspondent {key: row.key}) "
    # `c[row.seen_prop] IS NULL` is the "never written" test for this platform, not
    # `first_seen_utc IS NULL`: a participant in a thread with no messages has no
    # timestamp, and keying on the timestamp would let every batch overwrite them.
    "SET c[row.handle_prop] = CASE WHEN c[row.seen_prop] IS NULL "
    "        OR (row.first_seen_utc IS NOT NULL AND row.first_seen_utc < c[row.seen_prop]) "
    "    THEN row.handle ELSE c[row.handle_prop] END "
    "SET c[row.seen_prop] = CASE WHEN c[row.seen_prop] IS NULL "
    "        OR (row.first_seen_utc IS NOT NULL AND row.first_seen_utc < c[row.seen_prop]) "
    "    THEN coalesce(row.first_seen_utc, c[row.seen_prop]) ELSE c[row.seen_prop] END "
    "SET c.email = coalesce(c.email, row.email) "
    "SET c.phone_e164 = coalesce(c.phone_e164, row.phone_e164) "
    "SET c.merged_by = coalesce(c.merged_by, row.merged_by) "
    "WITH c, row "
    "MATCH (t:Thread {key: row.thread_key}) "
    "MERGE (t)-[:WITH]->(c)"
)

# `canon` evidence -> the `merged_by` value the audit query reads. Anything that is
# not a phone, an address or a nickname is a name match, which is what `exact_name`
# means here: the canonical forms were already identical.
_MERGED_BY = {"phone": "phone", "email": "email", "nickname": "nickname"}

# Per-platform spellings and first sightings are stored **flat**, not as a map:
# Relate rejects a map property (`DataError: InvalidPropertyType`). The plan's
# `handles: {telegram: "…"}` shape is assembled by `handles_from()` at the API
# boundary, where a dict is free.
HANDLE_PREFIX = "handle_"
SEEN_PREFIX = "seen_"


def handles_from(properties: dict[str, Any]) -> dict[str, str]:
    """`{handle_telegram: "Axiom", handle_messenger: "David"}` -> `{telegram: …, messenger: …}`.

    The API layer calls this so a caller sees the map the schema promises without the
    store having to hold one.
    """
    return {
        name[len(HANDLE_PREFIX):]: value
        for name, value in (properties or {}).items()
        if name.startswith(HANDLE_PREFIX) and value
    }


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

    **The key is `person:<canonical>`, not `<platform>:<canonical>`.** Dropping the
    platform prefix is what lets one person be one node across sources. It does not
    merge a phone-only contact with a named one — those keys differ and stay apart
    until `link.py` (edit 4) folds them.

    **Placeholders keep the platform prefix.** `canon` returns
    `placeholder:facebook user`; under a bare `person:` key Messenger's `Facebook
    user` and LinkedIn's `LinkedIn Member` would become one node standing for two
    different platforms' placeholder accounts.

    `first_seen_utc` is the earliest message timestamp per (platform, canonical),
    built from `result.messages` — the participant list carries no time at all.
    """
    from .canon import canonical

    forms = [form for form in (owner_forms or ()) if form]
    if owner:
        forms.append(owner)

    first_seen = _first_seen_by_person(result, forms)
    contacts = _contact_ids(result, forms)

    # One row per (thread, person), but the *per-platform* facts are decided once per
    # (key, platform). Relate evaluates every row of an `UNWIND` against the node as
    # it stood **before** the statement, so two rows for one key both see the old
    # value and the last row wins. Aggregating here means every row for a key carries
    # the same answer, and the statement is order-independent.
    #
    # The cache is keyed by `(key, platform)`, not by `key`: a person on two platforms
    # needs a row for each, carrying that platform's own `handle_<p>` / `seen_<p>`.
    rows: list[dict[str, Any]] = []
    facts: dict[tuple[str, str], dict[str, Any]] = {}
    keys: set[str] = set()
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
                key = f"{chat.platform}:{record.key}"
            else:
                key = f"person:{record.key or clean}"
            keys.add(key)

            slot = (key, chat.platform)
            fact = facts.get(slot)
            if fact is None:
                # A phone-only contact's key IS its digits, so the evidence is enough.
                # A *named* contact has no address in its key at all — the export's
                # `sender_id` is the only place a phone or an address ever appears, and
                # without it `link.py` could never fold `person:david sartori` onto
                # `person:+27845189029`.
                contact = contacts.get((chat.platform, record.key), {})
                fact = facts[slot] = {
                    "key": key,
                    "platform": chat.platform,
                    "handle": record.display,
                    "handle_prop": f"{HANDLE_PREFIX}{chat.platform}",
                    "seen_prop": f"{SEEN_PREFIX}{chat.platform}",
                    "first_seen_utc": first_seen.get((chat.platform, record.key)),
                    "merged_by": _MERGED_BY.get(record.evidence, "exact_name"),
                    "email": (record.key if record.evidence == "email"
                              else contact.get("email")),
                    "phone_e164": (record.key if record.evidence == "phone"
                                   else contact.get("phone")),
                }
            rows.append({**fact, "thread_key": tkey})

    cur = conn.cursor()
    for batch in _chunks(rows):
        cur.execute(_CORRESPONDENT_CYPHER, {"rows": batch})
    _reconcile(cur, keys)
    conn.commit()
    return {"correspondents": len(keys)}


def _contact_ids(
    result: IngestResult, owner_forms: Iterable[str],
) -> dict[tuple[str, str], dict[str, str]]:
    """`(platform, canonical) -> {"phone": …, "email": …}` from the export's ids.

    A sender field is a *name*; the address a platform actually knows the person by
    lives in `sender_id` (SMS writes the phone, email writes the address, Telegram
    writes a user id). Without this the store holds no phone for a named contact, so
    a phone fold has nothing to compare and `link.py` can only ever match on names —
    which edit 1 already did at write time.

    Only a value that *is* a phone or an address is kept. A Telegram user id
    (`user1426445212`) is neither, and storing it as a phone would be a lie.
    """
    from .canon import canonical, is_email, is_phone, phone_digits

    forms = list(owner_forms)
    found: dict[tuple[str, str], dict[str, str]] = {}
    for message in result.messages:
        raw_id = (message.sender_id or "").strip()
        name = (message.sender_name or "").strip()
        if not raw_id or not name:
            continue
        record = canonical(name, kind="person", owner=forms)
        if record.is_owner or not record.key or record.is_placeholder:
            continue

        slot = found.setdefault((message.platform, record.key), {})
        if is_phone(raw_id):
            digits = phone_digits(raw_id)
            if digits:
                slot.setdefault("phone", digits)
        elif is_email(raw_id):
            slot.setdefault("email", raw_id.strip().strip(".,;:").casefold())
    return found


def _first_seen_by_person(
    result: IngestResult, owner_forms: Iterable[str],
) -> dict[tuple[str, str], str]:
    """`(platform, canonical) -> earliest `ts_utc`, as the store's ISO string.

    The participant list says who was in a thread, never when. The only timestamp
    the writer has is on the messages, so this walks them once and keeps the
    minimum per sender. A sender who is the Owner is skipped for the same reason
    the Owner is skipped above.
    """
    from .canon import canonical

    forms = list(owner_forms)
    earliest: dict[tuple[str, str], Any] = {}
    for message in result.messages:
        name = (message.sender_name or "").strip()
        if not name:
            continue
        record = canonical(name, kind="person", owner=forms)
        if record.is_owner or not record.key:
            continue
        slot = (message.platform, record.key)
        current = earliest.get(slot)
        if current is None or message.ts_utc < current:
            earliest[slot] = message.ts_utc
    return {slot: to_utc_string(ts) for slot, ts in earliest.items()}


# The order the label lists platforms in when two first sightings tie. A tie is
# possible (a thread with no messages has no timestamp at all), and a stable order
# keeps the label from flickering between ingests.
_PLATFORM_ORDER = tuple(PLATFORM_TITLE_LABELS)


def _reconcile(cur: Any, keys: Iterable[str], *, label: str = "Correspondent") -> None:
    """Recompute every derived property from the flat per-platform facts.

    Runs after the rows have landed, because a node's `platforms` list depends on
    stamps written by *other* batches and a batch cannot see them. It is idempotent:
    it reads only `seen_<p>` and `handle_<p>`, which the row statement owns.

    **The rules are the same for every entity label**, which is why this takes a label
    rather than a query: a `Place` seen on Telegram and on WhatsApp carries exactly the
    properties a `Correspondent` does (`handle_<p>`, `seen_<p>`), and `:Merged` has to
    mean the same thing on both. The `WHERE` is spelled out per label rather than
    built from a parameter because Relate cannot parameterise a label in `MATCH`.

    What it decides, and why each rule is what it is:

      platforms      every platform with a `seen_<p>` stamp, in date order.
      platform       the first of those. The platform filter reads this single
                     string, so it must never be a joined label.
      display_name   the spelling from the earliest platform, so the label does not
                     depend on which export was ingested first.
      first_seen_utc the minimum stamp across platforms.
      platform_label `Telegram-WhatsApp-Fcbk Mssgr`, in the same date order.
      :Merged        set when more than one platform is present, removed when not.
                     Additive, so `MATCH (c:Correspondent)` still finds it.
    """
    keys = sorted(set(keys))
    if not keys:
        return

    rows = []
    cur.execute(
        f"MATCH (n:{label}) WHERE n.key IN $keys RETURN properties(n) AS p",
        {"keys": keys},
    )
    for record in cur.fetchall():
        props = record["p"]
        seen = {
            platform: props[f"{SEEN_PREFIX}{platform}"]
            for platform in _PLATFORM_ORDER
            if props.get(f"{SEEN_PREFIX}{platform}")
        }
        # A platform with no timestamp still counts as present — it is in the list,
        # it just sorts last. `platforms` is therefore the union of the stamps and
        # the handles, not the stamps alone.
        present = [
            platform for platform in _PLATFORM_ORDER
            if props.get(f"{SEEN_PREFIX}{platform}") or props.get(f"{HANDLE_PREFIX}{platform}")
        ]
        present.sort(key=lambda p: (seen.get(p) is None, seen.get(p) or "",
                                    _PLATFORM_ORDER.index(p)))
        if not present:
            continue

        first = present[0]
        rows.append({
            "key": props["key"],
            "platform": first,
            "platforms": present,
            "display_name": props.get(f"{HANDLE_PREFIX}{first}") or props.get("display_name"),
            "first_seen_utc": min(seen.values()) if seen else None,
            "platform_label": "-".join(PLATFORM_TITLE_LABELS[p] for p in present),
            "merged": len(present) > 1,
        })

    cur.execute(
        f"UNWIND $rows AS row MATCH (n:{label} {{key: row.key}}) "
        "SET n.platform = row.platform, n.platforms = row.platforms, "
        "    n.display_name = row.display_name, "
        "    n.first_seen_utc = row.first_seen_utc, "
        "    n.platform_label = row.platform_label "
        "FOREACH (_ IN CASE WHEN row.merged THEN [1] ELSE [] END | SET n:Merged) "
        "FOREACH (_ IN CASE WHEN row.merged THEN [] ELSE [1] END | REMOVE n:Merged) ",
        {"rows": rows},
    )


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


def watermark(conn: Any, platform: str) -> str | None:
    """The newest `ts_utc` this platform already holds, or None for an empty platform.

    This is the delta cutoff: a message at or below it is already in the store, so it
    needs neither a write nor an extraction. It is a *timestamp*, not a set of keys,
    because the point is to answer "what is new?" without shipping every key back.

    Indexed by `_SCHEMA`'s `msg_ts`. The string comparison is safe because every
    `ts_utc` is written by `schema.to_utc_string` — ISO-8601 with `Z`, fixed width, so
    lexical order equals chronological order.
    """
    cur = conn.cursor()
    cur.execute(
        "MATCH (m:Message) WHERE m.platform = $platform "
        "RETURN max(m.ts_utc) AS newest",
        {"platform": platform},
    )
    rows = cur.fetchall()
    if not rows:
        return None
    value = rows[0]["newest"]
    return str(value) if value else None


def watermarks(conn: Any, platforms: Iterable[str]) -> dict[str, str]:
    """`platform -> newest ts_utc` for every platform that holds messages.

    A platform with no rows is simply absent, which the caller reads as "nothing is
    already ingested, keep everything".
    """
    out: dict[str, str] = {}
    for platform in sorted({p for p in platforms if p}):
        newest = watermark(conn, platform)
        if newest:
            out[platform] = newest
    return out


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


# ------------------------------------------------------------ entity extraction

# One statement for the entity kinds, shaped exactly like `_CORRESPONDENT_CYPHER`.
#
# The label cannot be a parameter (Relate will not accept a dynamic label in `MATCH`
# or `MERGE`), so the writer builds the statement once per kind at import time; the
# kind set is `canon.KINDS`, which is the same source `tools.ENTITY_KINDS` reads.
#
# The split is the Correspondent split and for the same reason: `handle_<p>` / `seen_<p>`
# are flat per-platform facts, and everything derived (`platforms`, `platform_label`,
# `:Merged`) is recomputed by `_reconcile` afterwards, because an incremental ingest only
# ever sees part of the picture.
#
# The entity kinds this writer can land. Each maps to its store label; the key prefix and
# the `canon` kind are the dict key itself. `person` is deliberately absent — it competes
# with `Correspondent` and stays last, per the extraction design.
#
# **Adding a kind is a table entry, not an implementation.** The fold, the `mention_count`
# accumulation, the `MENTIONS` edge and `_reconcile` are identical for every entity kind;
# only the label differs. `product` is listed here ahead of its extractor existing, which
# is deliberate: it is the store's capability, and `extract.PRODUCT_ENABLED` is what
# decides whether anything claims it.
_ENTITY_WRITE_KINDS: dict[str, str] = {
    "place": "Place",
    "organization": "Organization",
    "product": "Product",
}

# Cypher cannot parameterise a label, so the statement is built once per kind rather
# than formatted per row.
def _entity_cypher(label: str) -> str:
    return (
        "UNWIND $rows AS row "
        f"MERGE (e:{label} {{key: row.key}}) "
        "SET e[row.handle_prop] = CASE WHEN e[row.seen_prop] IS NULL "
        "        OR (row.first_seen_utc IS NOT NULL AND row.first_seen_utc < e[row.seen_prop]) "
        "    THEN row.handle ELSE e[row.handle_prop] END "
        "SET e[row.seen_prop] = CASE WHEN e[row.seen_prop] IS NULL "
        "        OR (row.first_seen_utc IS NOT NULL AND row.first_seen_utc < e[row.seen_prop]) "
        "    THEN coalesce(row.first_seen_utc, e[row.seen_prop]) ELSE e[row.seen_prop] END "
        "SET e.mention_count = CASE WHEN e.mention_count IS NULL OR row.mentions > e.mention_count "
        "    THEN row.mentions ELSE e.mention_count END "
        "WITH e, row "
        "MATCH (m:Message {key: row.message_key}) "
        "MERGE (m)-[:MENTIONS]->(e)"
    )
#
# **`mention_count` accumulates over MESSAGES, and the edge hangs off the Message.**
#
# The anchor was a `Thread` until 2026-11-23, which made `(thread)-[:MENTIONS]->(entity)`
# a denormalisation: true and useful, but not a fact about the world, and not portable to
# another graph engine. `(message)-[:MENTIONS]->(entity)` is the fact; "this conversation
# is about X" is a projection over it (`tools._EDGE_QUERIES`).
#
# Two ingests of the same export both see an entity, and the second must not double the
# count, so the node keeps the larger of the two — an entity seen in three messages stays
# three when re-ingested.
#
# This replaced a fixed `_PLACE_CYPHER`; the statement is generated per label because
# Relate cannot parameterise a label, and two hand-written copies would drift.

# Evidence for a name-only fold -> the `merged_by` value the audit query reads.
_ENTITY_MERGED_BY = {"suffix": "exact_name", "case": "exact_name",
                     "diacritic": "exact_name", "camel": "exact_name"}


def write_places(
    conn: Any,
    mentions: Iterable[Any],
    *,
    message_meta: dict[str, tuple[str, str]],
) -> dict[str, int]:
    """Write one `Place` per canonical name, attached to threads with `MENTIONS`.

    `mentions` are `extract.Mention` records; `message_meta` maps `message_key ->
    (thread_key, ts_utc)` so a mention knows which thread to hang from and what its
    first sighting is. Both are passed in rather than looked up, so this runs after
    `write()` without a query per message.

    **Folding happens here, inside one platform.** `canon.canonical(kind="place")`
    drops the postal code and the trailing region code, so `Kensington`,
    `kensington` and `Kensington, London` converge to one key on one platform. That is
    `canon` doing its real work; this function only asks it and groups the answer.

    Cross-platform merging is **not** done here. `link.py` does it afterwards, over the
    whole store, exactly as it does for Correspondents.

    Returns `{"places": n, "mentions": n}` where `places` counts distinct keys.
    """
    return write_entities(conn, mentions, message_meta=message_meta, kinds=("place",))


def write_entities(
    conn: Any,
    mentions: Iterable[Any],
    *,
    message_meta: dict[str, tuple[str, str]],
    kinds: Iterable[str] = ("place", "organization"),
) -> dict[str, int]:
    """Write entity nodes for every `kind` present in `mentions`.

    **One function for every kind.** The fold, the `mention_count` accumulation, the
    `MENTIONS` edge and `_reconcile` are identical for a Place and an Organization —
    only the label, the key prefix and the `canon` kind differ, and all three come from
    `_ENTITY_WRITE_KINDS`. A second kind is therefore a table entry, not a second
    implementation. `write_places` is kept as the one-kind entry point callers already use.

    Returns `{"places": n, "organizations": n, "mentions": n}`, with a key for every
    kind requested (`0` when that kind had no mentions).
    """
    wanted = tuple(k for k in kinds if k in _ENTITY_WRITE_KINDS)
    counted = {f"{kind}s": 0 for kind in wanted}
    mentions = list(mentions)
    if not wanted or not mentions:
        return {**counted, "mentions": 0}

    per_kind: dict[str, list[Any]] = {kind: [] for kind in wanted}
    for mention in mentions:
        # A mention from the old single-kind path has no `kind`; it was a Place.
        kind = getattr(mention, "kind", "place")
        if kind in per_kind:
            per_kind[kind].append(mention)

    rows_written = 0
    for kind, rows_mentions in per_kind.items():
        if not rows_mentions:
            continue
        keys, rows = _write_one_kind(
            conn, rows_mentions, message_meta=message_meta, kind=kind,
        )
        counted[f"{kind}s"] = keys
        rows_written += rows
    # `mentions` is the number of (thread, entity, platform) rows written, not the
    # number of distinct keys — that is the contract callers already rely on.
    return {**counted, "mentions": rows_written}


def _write_one_kind(
    conn: Any,
    mentions: list[Any],
    *,
    message_meta: dict[str, tuple[str, str]],
    kind: str,
) -> tuple[int, int]:
    """The fold-and-write pass for ONE kind. Returns `(distinct keys, rows written)`."""
    from .canon import canonical

    label = _ENTITY_WRITE_KINDS[kind]

    # task (key, platform) -> the facts a single `MERGE` row needs.
    facts: dict[tuple[str, str], dict[str, Any]] = {}
    mention_rows: list[dict[str, Any]] = []
    seen_messages: dict[str, set[str]] = defaultdict(set)

    for mention in mentions:
        meta = message_meta.get(mention.message_key)
        if meta is None:
            continue
        _thread_key, ts_utc = meta
        platform = mention.platform or ""
        record = canonical(mention.text, kind=kind)
        if not record.key:
            continue
        key = f"{kind}:{record.key}"
        seen_messages[key].add(mention.message_key)

        slot = (key, platform)
        fact = facts.get(slot)
        if fact is None:
            fact = facts[slot] = {
                "key": key,
                "handle": record.display,
                "handle_prop": f"{HANDLE_PREFIX}{platform}",
                "seen_prop": f"{SEEN_PREFIX}{platform}",
                "first_seen_utc": ts_utc,
            }
        elif ts_utc and (fact["first_seen_utc"] is None
                         or ts_utc < fact["first_seen_utc"]):
            fact["first_seen_utc"] = ts_utc
        # The edge hangs off the **message**, not the thread. The same message naming
        # the same entity twice is one edge, which is why this is a list of rows later
        # deduped on `(message_key, key)` rather than appended blindly.
        mention_rows.append({**fact, "message_key": mention.message_key})

    if not facts:
        return (0, 0)

    # One row per (message, entity, platform); `mentions` carries the count for the whole
    # key so every row agrees on it — the same order-independence the Correspondent
    # statement relies on.
    rows: list[dict[str, Any]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for row in mention_rows:
        dedupe = (row["message_key"], row["key"])
        if dedupe in seen_pairs:
            continue
        seen_pairs.add(dedupe)
        rows.append({**row, "mentions": len(seen_messages[row["key"]])})

    cur = conn.cursor()
    statement = _entity_cypher(label)
    for batch in _chunks(rows):
        cur.execute(statement, {"rows": batch})
    _reconcile(cur, set(seen_messages), label=label)
    conn.commit()
    return (len(seen_messages), len(rows))


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
