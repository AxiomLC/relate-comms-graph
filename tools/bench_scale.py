"""How fast is ingest, really? Measured through the real writer, not raw Cypher.

Stage 2b replaced per-row MERGE with UNWIND batching. These are the numbers that
matter for a daily ingest, so they are measured by calling writer.write() rather
than re-implementing the Cypher here.

Measured 2026-11-14 on this box (i5-12500H, CPU only):

      msgs   per-row MERGE     UNWIND batched
     1,000    7.5 s (133/s)    0.13 s (7,971/s)
    10,000    156 s  (64/s)    1.33 s (7,520/s)

Per-row degraded superlinearly; batched is linear. Entry size ~740-800 bytes/msg.

    python tools/bench_scale.py --n 10000
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Run as a script from the repo, without requiring `pip install -e`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from relate_comms import writer  # noqa: E402
from relate_comms.schema import Chat, IngestResult, Message  # noqa: E402

BODY = (
    "Lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod tempor "
    "incididunt ut labore et dolore magna aliqua ut enim ad minim veniam quis."
)


def build(n: int, chats: int = 500) -> IngestResult:
    base = datetime(2025, 1, 1, tzinfo=timezone.utc)
    seen: dict[str, Chat] = {}
    messages: list[Message] = []
    for i in range(n):
        cid, mid = str(i % chats), str(i)
        messages.append(Message(
            key=f"bench:{cid}:{mid}",
            platform="bench",
            chat_id=cid,
            message_id=mid,
            ts_utc=base + timedelta(minutes=i),
            sender_name="Person A",
            sender_id="user900000",
            body=BODY,
            reply_to=None,
            has_attachments=False,
            is_self=(i % 2 == 0),
            raw_kind="text",
        ))
        seen[cid] = Chat(platform="bench", chat_id=cid, title="Bench",
                         kind="personal_chat", is_group=False)
    return IngestResult(platform="bench", export_path="bench",
                        chats=list(seen.values()), messages=messages)


def run(n: int) -> None:
    store = os.path.join(tempfile.gettempdir(), f"rel_bench_{n}.rl")
    if os.path.exists(store):
        os.remove(store)

    result = build(n)
    conn = writer.connect(store)
    cur = conn.cursor()

    started = time.perf_counter()
    counts = writer.write(conn, result)
    first = time.perf_counter() - started

    started = time.perf_counter()
    writer.write(conn, result)
    second = time.perf_counter() - started

    cur.execute("MATCH (m:Message) RETURN count(m) AS n")
    rows = cur.fetchall()[0]["n"]
    size_mb = os.path.getsize(store) / 1_000_000

    def timed(label: str, cypher: str, params: dict | None = None) -> None:
        t = time.perf_counter()
        cur.execute(cypher, params or {})
        got = cur.fetchall()
        print(f"  {label:24} {(time.perf_counter() - t) * 1000:7.1f} ms  ({len(got):,} rows)")

    print(f"\nmessages   : {n:,} (written {counts['messages']:,})")
    print(f"first write: {first:.2f}s ({n / first:,.0f} msg/s)")
    print(f"re-write   : {second:.2f}s (idempotent, adds nothing)")
    print(f"store rows : {rows:,}")
    print(f"file       : {size_mb:.1f} MB ({size_mb * 1e6 / max(n, 1):,.0f} bytes/msg)")
    print("\nquery latency:")
    timed("count all", "MATCH (m:Message) RETURN count(m) AS n")
    timed("point lookup", "MATCH (m:Message {key:$k}) RETURN m.body", {"k": "bench:1:1"})
    timed("thread traversal", "MATCH (m:Message)-[:IN]->(t:Thread {key:$tk}) "
                              "RETURN m.key LIMIT 100", {"tk": "bench:1"})
    timed("time window", "MATCH (m:Message) WHERE m.ts_utc >= $s RETURN count(m) AS n",
          {"s": "2025-06-01T00:00:00Z"})

    conn.close()
    os.remove(store)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=2000)
    run(parser.parse_args().n)
