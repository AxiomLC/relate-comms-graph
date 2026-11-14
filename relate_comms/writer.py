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
    "CREATE INDEX identity_key IF NOT EXISTS FOR (i:Identity) ON (i.key)",
    "CREATE INDEX attachment_key IF NOT EXISTS FOR (a:Attachment) ON (a.key)",
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
