"""`python -m app` — serve the UI on loopback.

    python -m app                 # http://127.0.0.1:8000
    python -m app --port 8100
    RELATE_STORE=other.rl python -m app

Loopback only. There is no `--host` flag on purpose: remote access is the user's own
private tunnel, not something this server arranges (buildUI.md §2).
"""
from __future__ import annotations

import argparse

import uvicorn


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true", help="restart on file change")
    args = parser.parse_args(argv)

    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=args.port,
        reload=args.reload,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
