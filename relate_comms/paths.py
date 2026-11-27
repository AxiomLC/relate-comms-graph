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


# **The spool scaffold mirrors `sample_writer/out/`.**
#
# Two levels: platform, then the one artifact folder a real export arrives in. The shape
# is fixed rather than derived from what happens to be present, so an empty spool looks
# the same on every clone and after every wipe — and a user can see where a file is
# supposed to go.
#
# `email` is here even though a live mailbox has no file to drop: a saved mailbox (a
# folder of `.eml`) is a real export shape, and it is the one the sample world writes.
#
# `imap` and `gmail` are gone. They were folders nothing ever wrote to — a live mailbox
# is fetched, not staged — and they made the scaffold claim a shape the app does not use.
SPOOL_SCAFFOLD: dict[str, tuple[str, ...]] = {
    "email": ("email_eml",),
    "linkedin": ("linkedin_zip",),
    "messenger": ("messenger_zip",),
    "outlook": ("outlook_copy",),
    "sms": ("sms_xml",),
    "telegram": ("Telegram Desktop",),
    "whatsapp": ("whatsapp_html",),
}

# Every platform folder, in scaffold order. Kept as a flat tuple for callers that only
# need the names.
PLATFORM_FOLDERS: tuple[str, ...] = tuple(SPOOL_SCAFFOLD)


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
    ensure_spool_scaffold()
    store_dir().mkdir(parents=True, exist_ok=True)


def ensure_spool_scaffold(root: str | Path | None = None) -> list[Path]:
    """Create the empty spool shape: `real/<platform>/<artifact>/`.

    **The one definition of "an empty spool".** `ensure_layout()` calls it on a fresh
    clone and `delete_spool()` calls it after a wipe, so the two cannot drift — which is
    what happened before: a wipe removed files and left behind every directory any
    previous ingest had created, so the spool became a skeleton of empty folders that
    looked like data.

    Returns the directories it created or confirmed, deepest last.
    """
    top = Path(root) if root else real_dir()
    made: list[Path] = []
    for platform, artifacts in SPOOL_SCAFFOLD.items():
        for artifact in artifacts:
            folder = top / platform / artifact
            folder.mkdir(parents=True, exist_ok=True)
            made.append(folder)
    return made
