"""Where user data lives, and where fixtures live.

Two different trust levels, kept in different places:

  spool/    raw downloads the user dropped. Rebuildable, gitignored.
  store/    graph.rl, the built graph. Gitignored. Only unrecoverable if the
            spool is lost too, which is why the app offers a Backup button.

Fixtures are a third level again: scrubbed, committed, shipped with the repo.

  tests/fixtures/   scrubbed, committed, present on every clone
  spool/ store/     real messages, never committed
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def data_root() -> Path:
    """The app's data folder. Inside the repo, never committed."""
    return ROOT


def spool_dir() -> Path:
    """The queue ingest drains. Two sub-folders, never mixed."""
    return data_root() / "spool"


def real_dir() -> Path:
    """The user's own exports. Real messages: never committed, pruned on verify."""
    return spool_dir() / "real"


def sample_dir() -> Path:
    """Generated demo exports. Regenerable, so they may be wiped freely."""
    return spool_dir() / "sample"


# One folder per platform, in both `real/` and `sample/`. The list is fixed rather
# than derived from what happens to be present, so the shape of the spool is the same
# on every clone — including platforms that have no file to drop (email is read over
# IMAP; SMS has no adapter yet).
PLATFORM_FOLDERS = (
    "telegram",
    "whatsapp",
    "messenger",
    "linkedin",
    "sms",
    "imap",
    "gmail",
)


def store_dir() -> Path:
    return data_root() / "store"


def store_path() -> Path:
    """The graph. One file, every message and every person."""
    return store_dir() / "graph.rl"


def profile_dir() -> Path:
    """Owner identity per platform. Re-identification material: never committed."""
    return store_dir() / "profile"


def fixtures_root() -> Path:
    return ROOT / "tests" / "fixtures"


def fixture(platform: str, shape: str = "bulk") -> Path:
    """Path to a committed fixture, e.g. fixture('telegram', 'single')."""
    return fixtures_root() / f"{platform}_{shape}" / "result.json"


def ensure_layout() -> None:
    """Create the folder shape so a fresh clone has somewhere to drop files.

    `spool/` and `store/` are gitignored; each ship a `.gitkeep` so the shape exists
    after a clone while the contents never reach version control.

    Every platform folder is created in **both** `real/` and `sample/`, so the spool
    looks the same on day one regardless of what the user has downloaded.
    """
    for root in (real_dir(), sample_dir()):
        for platform in PLATFORM_FOLDERS:
            (root / platform).mkdir(parents=True, exist_ok=True)
    store_dir().mkdir(parents=True, exist_ok=True)
