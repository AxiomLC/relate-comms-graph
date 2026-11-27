"""`python -m app.mcp` — the stdio entry point.

Kept separate from `server.py` so importing the module never starts a transport.
"""
from __future__ import annotations

from .server import main

raise SystemExit(main())
