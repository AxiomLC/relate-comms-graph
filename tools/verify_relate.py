"""Stage 0: prove Relate works on this machine before anything depends on it.

Run: python tools/verify_relate.py
Leaves a persistent .rl file behind so durability across process restarts is tested,
not assumed.
"""
import os
import sys

import relate

STORE = os.path.join(os.path.dirname(__file__), "..", "store", "stage0.rl")


from typing import Any

def _exec(conn: Any, cypher: str, params: dict[str, Any] | None = None) -> Any:
    """Run one statement and hand back the cursor (kept small so the body reads linearly)."""
    cur = conn.cursor()
    _ = cur.execute(cypher, params or {})
    return cur


def main() -> int:
    store = os.path.abspath(STORE)
    os.makedirs(os.path.dirname(store), exist_ok=True)

    print(f"relate-db {getattr(relate, '__version__', 'unknown')}")
    print(f"store: {store}")

    conn = relate.connect(store)
    cur = conn.cursor()

    cur = _exec(conn, (
        "MERGE (p:Person {key: $key}) "
        "SET p.display_name = $name, p.platforms = $platforms "
        "RETURN p.key, p.display_name"
    ), {"key": "person:demo", "name": "Dave Sartori", "platforms": ["whatsapp", "telegram"]})
    print("wrote:", cur.fetchall())

    cur = _exec(conn, (
        "MERGE (m:Message {key: $mkey}) "
        "SET m.platform = $platform, m.ts_utc = $ts, m.body = $body "
        "WITH m "
        "MATCH (p:Person {key: $pkey}) "
        "MERGE (p)-[:SENT]->(m) "
        "RETURN m.key"
    ), {
        "mkey": "whatsapp:chat1:msg1",
        "platform": "whatsapp",
        "ts": "2024-01-05T09:12:00Z",
        "body": "see you thursday",
        "pkey": "person:demo",
    })
    print("wrote:", cur.fetchall())

    cur = _exec(conn, (
        "MATCH (p:Person)-[:SENT]->(m:Message) "
        "RETURN p.display_name AS who, m.body AS body, m.ts_utc AS ts"
    ))
    rows = cur.fetchall()
    print("read back:", rows)
    conn.close()

    size = os.path.getsize(store)
    print(f".rl on disk: {size:,} bytes")
    assert size > 0, "store file is empty"
    assert len(rows) == 1, f"expected 1 row, got {len(rows)}"
    return 0


if __name__ == "__main__":
    sys.exit(main())
