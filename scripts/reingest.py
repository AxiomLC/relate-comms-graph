"""Rebuild the store from `spool/real/` and report entity balance.

Run: python scripts/reingest.py [--delta]

Exists because `ingest()` uses multiprocessing, which cannot re-import `__main__` from a
stdin heredoc on Windows (`OSError: Invalid argument: '<stdin>'`). A real file is the
only way to run it from a shell.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from relate_comms import ingest, tools  # noqa: E402

KINDS = ("Place", "Organization", "Product")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--delta", action="store_true",
                        help="keep stored rows (default is a full re-process)")
    args = parser.parse_args()

    started = time.perf_counter()
    report = ingest.ingest(delta=args.delta)
    elapsed = time.perf_counter() - started

    print(f"ingest: {elapsed:.1f}s  written={report.written}  "
          f"delta={args.delta}")
    for batch in report.batches:
        state = "error" if batch.error else ("ok" if batch.verified else "unverified")
        print(f"  {batch.platform:10} {batch.messages:6} msgs  "
              f"places={batch.places:4} orgs={batch.organizations:4} "
              f"products={batch.products:4}  {state}")

    print()
    for kind in KINDS:
        total = tools.run_cypher(f"MATCH (n:{kind}) RETURN count(n) AS n")["rows"][0]["n"]
        merged = tools.run_cypher(
            f"MATCH (n:{kind}:Merged) RETURN count(n) AS n")["rows"][0]["n"]
        repeated = tools.run_cypher(
            f"MATCH (n:{kind}) WHERE n.mention_count >= 2 RETURN count(n) AS n"
        )["rows"][0]["n"]
        print(f"{kind:14} total={total:5}  merged={merged:4}  "
              f"mention_count>=2={repeated:4}")

    print("\ntop products by mention_count:")
    rows = tools.run_cypher(
        "MATCH (p:Product) RETURN p.display_name AS name, p.mention_count AS n "
        "ORDER BY n DESC LIMIT 15")["rows"]
    for row in rows:
        print(f"  {row['n']:4}  {row['name']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
