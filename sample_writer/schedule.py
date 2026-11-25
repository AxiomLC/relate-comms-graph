"""The world's clock, saved to disk so a later run can extend it instead of re-rolling it.

WHY THIS EXISTS
---------------
`build` is deterministic in content but not in time. `message_times` draws burst days
from a window sized by the world's `END`, so moving `END` re-rolls every timestamp. Two
runs of the same seed therefore share no timestamps at all, and an incremental ingest
sees nothing to skip — every message looks new.

The fix is not to make the generator stateless. It is to **write the clock down**. The
first run saves the times it drew; `append` reads them back, keeps them verbatim, and
only draws new ones after the last recorded moment. The old week is then byte-identical
between runs, so its message keys match and the delta drops it.

WHAT IS STORED
--------------
One entry per thread, keyed by `thread.key` (stable across runs — it is derived from the
platform and the person's slug, never from a hash):

    {"seed": 8, "start": "2024-01-01", "end": "2026-11-18",
     "threads": {"telegram:valentina-newton-1": ["2024-03-07T19:06:42", ...]}}

Only the times. Bodies are regenerated from the seed and are already stable, so storing
them would be a second copy of data the seed already determines.

WHY NOT READ `out/`
-------------------
The exports are one big file per platform (Telegram's `result.json`, WhatsApp's zips,
LinkedIn's CSV, a `.pst`), so extending them means parsing and re-emitting six formats
and rezipping three archives — and `.pst` has no writer at all. The schedule is a few
kilobytes of JSON and needs none of that.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

# **Beside `out/`, never inside it.** `out/` is what a user drags into Ingest, and a
# stray `.json` there is an artifact the app must then classify — measured: it showed up
# as an unrecognised export in `test_every_artifact_is_either_detected_or_documented`.
# A sibling file is invisible to staging and to `discover()`.
FILENAME = ".schedule.json"

# ISO without microseconds: the writers render to the second anyway, and a shorter
# string is easier to read when a human opens the file to see what happened.
_FMT = "%Y-%m-%dT%H:%M:%S"


def path_for(out_dir: str | Path) -> Path:
    """`out/.schedule.json` -> `<parent>/.schedule.json`.

    The clock describes `out/`; it is not part of it. Keeping it beside the folder means
    a `clean` of `out/` leaves it alone (so `append` still works) and a stage of `out/`
    never picks it up.
    """
    target = Path(out_dir)
    return target.parent / FILENAME


def save(out_dir: str | Path, *, seed: int, start: datetime, end: datetime,
         threads: dict[str, list[datetime]]) -> Path:
    """Write the clock. Called once per build, after the plans exist."""
    target = path_for(out_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "seed": seed,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "threads": {
            key: [moment.strftime(_FMT) for moment in times]
            for key, times in threads.items()
        },
    }
    target.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    return target


def load(out_dir: str | Path) -> dict[str, Any] | None:
    """The saved clock, or None when there is none (a first run, or a cleaned `out/`)."""
    target = path_for(out_dir)
    if not target.exists():
        return None
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def times_for(saved: dict[str, Any] | None, key: str) -> list[datetime]:
    """The recorded times for one thread, parsed. Empty when there is no record."""
    if not saved:
        return []
    raw = (saved.get("threads") or {}).get(key)
    if not isinstance(raw, list):
        return []
    parsed: list[datetime] = []
    for value in raw:
        try:
            parsed.append(datetime.strptime(str(value), _FMT))
        except ValueError:
            return []
    return parsed


def last_moment(saved: dict[str, Any] | None) -> datetime | None:
    """The newest moment anywhere in the saved clock — where `append` starts drawing."""
    if not saved:
        return None
    newest: datetime | None = None
    for raw in (saved.get("threads") or {}).values():
        if not isinstance(raw, list) or not raw:
            continue
        try:
            moment = datetime.strptime(str(raw[-1]), _FMT)
        except ValueError:
            continue
        if newest is None or moment > newest:
            newest = moment
    return newest
