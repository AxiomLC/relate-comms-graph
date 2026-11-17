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
    """The queue ingest drains. **One queue.**

    There used to be `spool/real/` and `spool/sample/`, on the theory that a demo must
    never mix with the user's own exports. That was answered better by the Truncate
    button: test with samples, wipe, ingest the real thing. A sample is just a file
    dropped in the spool — `ingest` cannot tell it from a real export and does not need
    to. One queue means one discovery path and one set of docs.
    """
    return data_root() / "spool"


def real_dir() -> Path:
    """The one queue. Named `real/` for continuity with existing spools."""
    return spool_dir() / "real"


# One folder per platform. The list is fixed rather than derived from what happens to
# be present, so the shape of the spool is the same on every clone — including
# platforms that have no file to drop (email is read over IMAP).
PLATFORM_FOLDERS = (
    "telegram",
    "whatsapp",
    "messenger",
    "linkedin",
    "outlook",
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
    """
    for platform in PLATFORM_FOLDERS:
        (real_dir() / platform).mkdir(parents=True, exist_ok=True)
    store_dir().mkdir(parents=True, exist_ok=True)
