"""Where user data lives, and where fixtures live.

Two different trust levels, deliberately kept in different places:

  fixtures/   tests/fixtures/  — scrubbed, committed, shipped with the repo
  user data   RELATE_DATA_ROOT — real exports and the graph store, never committed

Anything that touches real messages goes through `data_root()`. Anything that runs
on every clone goes through `fixtures_root()`. Keeping the two separate is what
stops a real export from ever being committed by accident.
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_ENV = "RELATE_DATA_ROOT"
_DEFAULT = Path.home() / "relate-comms"


def data_root() -> Path:
    """Real exports and the store. Outside the repo by default."""
    return Path(os.environ.get(_ENV, _DEFAULT)).expanduser()


def spool_dir() -> Path:
    """Daily exports land here; pruned at 3 days after verification."""
    return data_root() / "spool"


def store_path() -> Path:
    return data_root() / "store" / "graph.rl"


def profile_dir() -> Path:
    """Owner identity / alias maps. Re-identification material: never committed."""
    return data_root() / "profile"


def fixtures_root() -> Path:
    return ROOT / "tests" / "fixtures"


def fixture(platform: str, shape: str = "bulk") -> Path:
    """Path to a committed fixture, e.g. fixture('telegram', 'single')."""
    return fixtures_root() / f"{platform}_{shape}" / "result.json"
