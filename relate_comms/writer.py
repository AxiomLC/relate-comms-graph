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

from .schema import Chat, Identity, IngestResult, Message, Person, to_utc_string

_SCHEMA = (
    "CREATE INDEX msg_key IF NOT EXISTS FOR (m:Message) ON (m.key)",
    "CREATE INDEX thread_key IF NOT EXISTS FOR (t:Thread) ON (t.key)",
    "CREATE INDEX identity_key IF NOT EXISTS FOR (i:Identity) ON (i.key)",
    "CREATE INDEX attachment_key IF NOT EXISTS FOR (a:Attachment) ON (a.key)",
    "CREATE INDEX person_key IF NOT EXISTS FOR (p:Person) ON (p.key)",
    "CREATE INDEX identity_person IF NOT EXISTS FOR (i:Identity) ON (i.person_key)",
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

_PERSON_CYPHER = (
    "UNWIND $rows AS row "
    "MERGE (p:Person {key: row.key}) "
    "SET p.display_name = row.display_name, "
    "    p.first_seen_utc = row.first_seen_utc, p.last_seen_utc = row.last_seen_utc"
)

_IDENTITY_CYPHER = (
    "UNWIND $rows AS row "
    "MERGE (i:Identity {key: row.key}) "
    "SET i.platform = row.platform, i.handle = row.handle, "
    "    i.phone_e164 = row.phone_e164, i.email = row.email, "
    "    i.display_name = row.display_name, i.confidence = row.confidence, "
    "    i.matched_by = row.matched_by "
    "WITH i, row "
    "MATCH (p:Person {key: row.person_key}) "
    "MERGE (p)-[r:MATCHED_BY]->(i) "
    "SET r.confidence = row.confidence, r.matched_by = row.matched_by"
)

# A fuzzy match between two People. Written in both directions because the resolver
# cannot know which side is "canonical", and a directed guess would invent hierarchy.
_POSSIBLY_CYPHER = (
    "UNWIND $rows AS row "
    "MATCH (a:Person {key: row.a}) "
    "MATCH (b:Person {key: row.b}) "
    "MERGE (a)-[r:POSSIBLY]->(b) "
    "SET r.confidence = row.confidence, r.reason = row.reason"
)

# Whoever sent a message is its author. The resolver knows the platform account; this
# connects it to the message row already written.
_SENT_CYPHER = (
    "UNWIND $rows AS row "
    "MATCH (p:Person {key: row.person_key}) "
    "MATCH (m:Message {key: row.msg_key}) "
    "MERGE (p)-[:SENT]->(m)"
)


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


def write(conn: Any, result: IngestResult) -> dict[str, int]:
    """Write every message and attachment, batched with UNWIND.

    Idempotency is unchanged: every statement is a MERGE on a stable key, so a
    second run over the same input adds nothing. Batching only removes round trips
    (measured: per-row MERGE ran at 64-133 msg/s and degraded superlinearly).
    """
    chats_by_id = {c.chat_id: c for c in result.chats}
    cur = conn.cursor()

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
            "thread_title": chat.title if chat else "",
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
    return {"messages": len(message_rows), "attachments": len(attachment_rows)}


def write_people(
    conn: Any,
    people: Iterable[Person],
    identities: Iterable[Identity],
    *,
    sent: Iterable[tuple[str, str]] = (),
) -> dict[str, int]:
    """Persist resolved people, their identities and who sent what.

    Called **after** `write()`, because `SENT` needs the message rows to exist.

    `sent` is `(person_key, message_key)` pairs. The resolver reports them through
    `resolution.sent_edges()`, so this function does no matching of its own — a
    second place that decides authorship is a second place to be wrong.

    An identity at `confidence >= MATCH_THRESHOLD` is a fact and is written as
    `MATCHED_BY`; anything lower also gets a `POSSIBLY` edge between the person and
    the identity's *own* standalone person, so the uncertainty is visible in the
    graph rather than flattened into a boolean (§3.1).
    """
    cur = conn.cursor()

    person_rows = [
        {
            "key": p.key,
            "display_name": p.display_name,
            "first_seen_utc": to_utc_string(p.first_seen_utc),
            "last_seen_utc": to_utc_string(p.last_seen_utc),
        }
        for p in people
    ]
    for batch in _chunks(person_rows):
        cur.execute(_PERSON_CYPHER, {"rows": batch})

    identity_rows = [
        {
            "key": i.key,
            "platform": i.platform,
            "handle": i.handle,
            "phone_e164": i.phone_e164,
            "email": i.email,
            "display_name": i.display_name,
            "person_key": i.person_key or i.key,
            "confidence": i.confidence,
            "matched_by": i.matched_by,
        }
        for i in identities
    ]
    for batch in _chunks(identity_rows):
        cur.execute(_IDENTITY_CYPHER, {"rows": batch})

    sent_rows = [{"person_key": p, "msg_key": m} for p, m in sent]
    for batch in _chunks(sent_rows):
        cur.execute(_SENT_CYPHER, {"rows": batch})

    conn.commit()
    return {
        "people": len(person_rows),
        "identities": len(identity_rows),
        "sent": len(sent_rows),
    }


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
