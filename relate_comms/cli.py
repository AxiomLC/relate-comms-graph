"""`python -m relate_comms` — the shipped command line.

    python -m relate_comms sample build            # generate sample downloads
    python -m relate_comms ingest --source sample  # ingest them
    python -m relate_comms ingest --source real    # ingest ~/relate-comms/spool/

`prune` is not implicit. Deleting a spool file requires both `--prune` and
`--confirm`, matching `tools.require(Access.DESTRUCTIVE)` so the CLI and a model
cannot diverge on what is safe to delete.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone


def _utc(value: str) -> datetime:
    """Parse an ISO-8601 boundary. A naive value is read as UTC, never local."""
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"not an ISO date: {value!r}") from exc
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


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
    ingest.add_argument("paths", nargs="*",
                        help="export files to copy into the spool before ingesting")
    ingest.add_argument("--root", help="directory to read instead of the default spool")
    ingest.add_argument("--tz-offset", type=float, default=0,
                        help="hours the export's local times were written in, e.g. -5")
    ingest.add_argument("--store", help="override the .rl store path")
    ingest.add_argument("--since", type=_utc, help="ISO-8601, inclusive")
    ingest.add_argument("--until", type=_utc, help="ISO-8601, inclusive")
    ingest.add_argument("--no-service", action="store_true",
                        help="drop Telegram service rows instead of counting them")
    ingest.add_argument("--workers", type=int, help="parse processes (default: half the cores)")
    ingest.add_argument("--self-id", help="pin the owner id instead of inferring it")
    ingest.add_argument("--prune", action="store_true",
                        help="delete spool files older than 3 days once verified")
    ingest.add_argument("--confirm", action="store_true",
                        help="required alongside --prune; a model never passes this alone")
    ingest.add_argument("--json", action="store_true", help="machine-readable report")

    args = parser.parse_args(argv)

    if args.command == "sample" and args.sample_command == "build":
        from .sample_data.build import main as build_main
        forwarded = ["--dest", args.dest, "--seed", str(args.seed)]
        if args.check:
            forwarded.append("--check")
        return build_main(forwarded)

    if args.command == "ingest":
        if args.prune and not args.confirm:
            print("refusing to prune without --confirm: deleting spool files is destructive",
                  file=sys.stderr)
            return 2

        from . import ingest as ingest_module

        if args.paths:
            # Stage into the same root the run will read, or the copy lands somewhere
            # the ingest never looks.
            staged = ingest_module.stage(args.paths, root=args.root)
            for path in staged:
                print(f"staged: {path}", file=sys.stderr)

        report = ingest_module.ingest(
            source=args.source,
            root=args.root,
            store=args.store,
            since=args.since,
            until=args.until,
            include_service=not args.no_service,
            prune=args.prune,
            workers=args.workers,
            self_id=args.self_id,
            tz_offset_hours=args.tz_offset,
        )

        if args.json:
            print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
        else:
            print(ingest_module.format_report(report))
        return 0 if report.ok else 1

    return 1


if __name__ == "__main__":
    sys.exit(main())
