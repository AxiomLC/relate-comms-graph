"""Which mailbox does the graph actually hold?

IMAP is the one leg with **no spool**. Every other platform leaves a file in
`spool/real/`, and `ingested.json` records what that file contributed. A mailbox leaves
nothing, so after a truncate there is no evidence anywhere that an email leg ever ran —
`.env` holds credentials, which is configuration, not a statement about the graph.

That gap has a visible cost. `_run_ingest` decides whether to wipe the `email` rows by
comparing the typed address against **`.env`**. `.env` is whatever the user last saved,
including by hand, so it can disagree with the store: delete the graph, leave `.env`
alone, and the next run thinks it is continuing a mailbox that is gone. This file is the
graph's own answer.

**Written only on success**, the same rule and the same reason as `.env` — a mailbox that
cannot be read must leave nothing behind, and the only proof a run worked is a run that
worked. **Deleted by `truncate_store()`**, because a wipe that left it behind would make
the next ingest believe it had a mailbox to continue.

Not part of `identity.json`. That file answers "who is me in this export" and holds the
owner and tz offsets; this answers "what is in the store". Two questions, two files, and
one of them is wiped with the graph.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_STATE_FILE = "imap.json"


def path_for(profile_dir: str | Path) -> Path:
    return Path(profile_dir) / _STATE_FILE


def load(profile_dir: str | Path) -> dict[str, Any] | None:
    """The recorded mailbox state, or `None` when the graph holds no email leg.

    A corrupt or unreadable file reads as `None` rather than raising: this is a
    bookkeeping file, and refusing to ingest because it cannot be parsed would turn a
    lost convenience into a dead app. The caller reports the absence instead.
    """
    try:
        raw = path_for(profile_dir).read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def save(
    profile_dir: str | Path,
    *,
    email: str,
    host: str,
    port: int,
    folders: list[str] | None = None,
    since: str | None = None,
    until: str | None = None,
    messages: int = 0,
    first_ts: str | None = None,
    last_ts: str | None = None,
    ingested_at: str | None = None,
) -> dict[str, Any]:
    """Record what this run put in the graph. Called only after a verified write."""
    record = {
        "email": (email or "").strip(),
        "host": (host or "").strip(),
        "port": int(port or 993),
        "folders": list(folders or []),
        "window": {"since": since, "until": until},
        "messages": int(messages or 0),
        "first_ts": first_ts,
        "last_ts": last_ts,
        "ingested_at": ingested_at,
    }
    target = path_for(profile_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


def clear(profile_dir: str | Path) -> bool:
    """Remove the record. Returns whether a file was there. Used by `truncate_store`."""
    target = path_for(profile_dir)
    if target.exists():
        target.unlink()
        return True
    return False


def compare(record: dict[str, Any] | None, *, email: str, host: str | None = None,
            since: str | None = None, until: str | None = None,
            store_has_email: bool = False) -> str:
    """What this request means relative to what the graph holds.

    One of:

        first      nothing recorded and nothing stored — a clean ingest
        same       the same mailbox and the same window: a delta
        window     the same mailbox, a different window — the graph grows, it does not
                   shrink, so this is a union rather than a mirror
        different  another mailbox: its rows share the key namespace, so they must go
        stale      nothing recorded but the store holds email rows — the state file was
                   lost or deleted by hand; the caller must not guess

    `stale` exists because the alternative is silence. If the file is missing while the
    store holds `email` rows, the honest answer is "I cannot tell", not "first" — and
    guessing either way is destructive: wiping loses rows the user did not ask to
    lose, and continuing merges two mailboxes into one key namespace.
    """
    if record is None:
        return "stale" if store_has_email else "first"

    recorded = (record.get("email") or "").strip().casefold()
    wanted = (email or "").strip().casefold()
    if recorded and wanted and recorded != wanted:
        return "different"

    window = record.get("window") or {}
    if (window.get("since"), window.get("until")) != (since, until):
        return "window"
    return "same"
