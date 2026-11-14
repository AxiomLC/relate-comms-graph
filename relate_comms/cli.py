"""`python -m relate_comms` — the shipped command line.

    python -m relate_comms sample build            # generate sample downloads
    python -m relate_comms ingest --source sample  # ingest them
    python -m relate_comms ingest --source real    # ingest ~/relate-comms/spool/

`sample` is implemented. `ingest` is not — it arrives with stage 4/5, once
resolution and the scrub gate exist, so ingest does not ship a graph shape that
will change under it.
"""
from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="relate-comms")
    sub = parser.add_subparsers(dest="command", required=True)

    sample = sub.add_parser("sample", help="generate sample downloads")
    sample_sub = sample.add_subparsers(dest="sample_command", required=True)
    build = sample_sub.add_parser("build", help="write sample result.json files")
    build.add_argument("--dest", choices=("generated", "fixtures"), default="generated")
    build.add_argument("--check", action="store_true")
    build.add_argument("--seed", type=int, default=20261114)

    ingest = sub.add_parser("ingest", help="parse exports into the store")
    ingest.add_argument("--source", choices=("sample", "real"), default="real")

    args = parser.parse_args(argv)

    if args.command == "sample" and args.sample_command == "build":
        from .sample_data.build import main as build_main
        forwarded = ["--dest", args.dest, "--seed", str(args.seed)]
        if args.check:
            forwarded.append("--check")
        return build_main(forwarded)

    if args.command == "ingest":
        print("ingest is not implemented yet — see buildNOTES §10, stage 4/5",
              file=sys.stderr)
        return 2

    return 1


if __name__ == "__main__":
    sys.exit(main())
