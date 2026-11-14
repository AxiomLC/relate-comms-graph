"""How does Relate scale on this box? Measured, not assumed.

Writes N synthetic messages and reports wall time, file size, and query latency.
Run with a small N first — this is the same shape the daily ingest produces.

    python tools/bench_scale.py --n 5000
"""
from __future__ import annotations

import argparse
import os
import shutil
import tempfile
import time

import relate

BODY = (
    "Lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod tempor "
    "incididunt ut labore et dolore magna aliqua ut enim ad minim veniam quis."
)


def run(n: int) -> None:
    path = os.path.join(tempfile.gettempdir(), f"rel_scale_{n}.rl")
    if os.path.exists(path):
        os.remove(path)

    conn = relate.connect(path)
    cur = conn.cursor()

    t0 = time.time()
    for i in range(n):
        cur.execute(
            "MERGE (m:Message {key:$k}) SET m.platform='telegram', m.body=$b, "
            "m.ts_utc=$t, m.raw_kind='text' "
            "WITH m MERGE (t:Thread {key:$tk}) MERGE (m)-[:IN]->(t)",
            {
                "k": f"telegram:{i % 500}:{i}",
                "b": BODY,
                "t": f"2025-{(i % 12) + 1:02d}-01T00:00:00Z",
                "tk": f"telegram:{i % 500}",
            },
        )
        if i and i % 500 == 0:
            conn.commit()
            print(f"  {i:,} written, {time.time() - t0:.1f}s", flush=True)
    conn.commit()
    write_s = time.time() - t0
    size_mb = os.path.getsize(path) / 1_000_000

    print(f"\nmessages  : {n:,}")
    print(f"write     : {write_s:.1f}s ({n / write_s:,.0f} msg/s)")
    print(f"file      : {size_mb:.1f} MB ({size_mb * 1e6 / n:,.0f} bytes/msg)")

    def timed(label: str, cypher: str, params: dict | None = None) -> None:
        t = time.time()
        cur.execute(cypher, params or {})
        rows = cur.fetchall()
        print(f"{label:26} {(time.time() - t) * 1000:7.1f} ms  ({len(rows):,} rows)")

    timed("count all", "MATCH (m:Message) RETURN count(m) AS n")
    timed("point lookup", "MATCH (m:Message {key:$k}) RETURN m.body",
          {"k": "telegram:1:1"})
    timed("thread traversal", "MATCH (m:Message)-[:IN]->(t:Thread {key:$tk}) "
                              "RETURN m.key LIMIT 100", {"tk": "telegram:1"})
    timed("time window", "MATCH (m:Message) WHERE m.ts_utc >= $s RETURN count(m) AS n",
          {"s": "2025-06-01T00:00:00Z"})
    timed("group by raw_kind", "MATCH (m:Message) RETURN m.raw_kind, count(m)")

    conn.close()
    shutil.rmtree(path, ignore_errors=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=2000)
    run(ap.parse_args().n)
