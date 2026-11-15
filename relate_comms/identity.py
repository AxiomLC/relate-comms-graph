"""Who is "me" in an export?

`is_self` decides whether a message came from the account owner. It must be
**stable across files**: the same message parsed from the bulk export and from a
single-chat export has to agree, or the daily ingest and a one-off export will
disagree about who said what.

Telegram does not always tell us. Real exports from this account (2026-11-14) had
`personal_information: null` and no Saved Messages chat. So:

1. If `personal_information.user_id` is present, trust it. That is a fact.
2. Otherwise, remember whichever owner we inferred before (persisted), so later
   files reuse it instead of guessing again.
3. Only if we have never seen an owner do we infer, and then we say so loudly.

The identity is stored outside the graph because it is account metadata, not a
message property.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

_IDENTITY_FILE = "identity.json"

# Wall-clock platforms whose export states no offset. Kept in the same profile file
# as the owner, because both are "how to read this account's exports" and both must
# survive a restart for the keys to stay stable.
_TZ_KEY = "tz_offsets"


def load_owner(profile_dir: str | Path, platform: str | None = None) -> str | None:
    """The persisted owner id, for one platform.

    **Owners are per platform, not global.** A Telegram export names the owner
    `user1426445212`; Messenger and LinkedIn name them `David Sartori`. They are the
    same human, but the *identifier* is not interchangeable — comparing a Messenger
    display name against a Telegram user id matches nothing, so every row lands
    `is_self=False` while the profile silently claims the owner is known.

    Files written before this was per-platform hold a single `owner_id` string. That
    value is returned only when no platform is asked for, so old profiles keep
    working for Telegram and stop leaking into other adapters.
    """
    path = Path(profile_dir) / _IDENTITY_FILE
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    owners = data.get("owners")
    if isinstance(owners, dict):
        if platform is None:
            return None
        value = owners.get(platform)
        return value if isinstance(value, str) and value else None

    if platform is not None:
        # Legacy single-owner file: only trustworthy for the platform that wrote it.
        writer = data.get("platform")
        if writer not in (None, platform):
            return None
    owner = data.get("owner_id")
    return owner if isinstance(owner, str) and owner else None


def save_owner(
    profile_dir: str | Path,
    owner_id: str,
    *,
    evidence: str,
    platform: str | None = None,
) -> None:
    """Record one platform's owner id without disturbing the others."""
    path = Path(profile_dir) / _IDENTITY_FILE
    path.parent.mkdir(parents=True, exist_ok=True)

    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, json.JSONDecodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}

    owners = data.get("owners")
    if not isinstance(owners, dict):
        owners = {}
        # Carry a legacy single value forward under the platform that wrote it, so
        # upgrading does not lose the owner Telegram already established.
        legacy = data.get("owner_id")
        legacy_platform = data.get("platform")
        if isinstance(legacy, str) and legacy and isinstance(legacy_platform, str):
            owners[legacy_platform] = legacy

    if platform is None:
        platform = "default"
    existing = owners.get(platform)
    if existing and existing != owner_id:
        # Never overwrite a known owner silently — the §9.2 rule, now per platform.
        raise ValueError(
            f"owner for {platform} already recorded as {existing!r} ({evidence}); "
            "refusing to overwrite with a different id"
        )

    owners[platform] = owner_id
    # Update in place. Writing a fresh `{"owners", "evidence"}` dict silently
    # dropped every other key in the file — including `tz_offsets`, which is part
    # of the message key. Adapters call this during parse, so the offsets vanished
    # on the next run and verification reported the whole store as missing.
    data["owners"] = owners
    data["evidence"] = evidence
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_tz_offset(profile_dir: str | Path, platform: str) -> float | None:
    """The offset this account's exports were last parsed with, per platform.

    **This is not a preference — it is part of the message key.** Telegram, WhatsApp
    and Messenger export wall-clock times with no offset, so `ts_utc` (and therefore
    `Message.key`, which hashes the timestamp) depends on the offset the caller
    declared. A run that parses with `-5` and a later run that verifies with `0`
    produce two disjoint key sets for the same file: the store holds 10,605 Messenger
    rows and verification reports all 10,605 missing.

    Persisting it is what makes `verify_ingest` and `prune_spool` able to re-derive
    the keys the store was built with, without the caller repeating the flag.
    """
    path = Path(profile_dir) / _IDENTITY_FILE
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    offsets = data.get(_TZ_KEY)
    if not isinstance(offsets, dict):
        return None
    value = offsets.get(platform)
    return float(value) if isinstance(value, (int, float)) else None


def save_tz_offset(
    profile_dir: str | Path, platform: str, hours: float, *, allow_change: bool = False,
) -> None:
    """Record the offset for a platform.

    Changing it re-keys every message from that platform. On a store that already
    holds rows that means a second copy of everything rather than a replacement, so
    the change is refused unless the caller says the store is empty
    (`allow_change=True`).

    A fresh store is the normal case while the app is being built: wipe
    `store/graph.rl`, re-ingest with whatever offset you like, and nothing is
    duplicated because there was nothing there to duplicate.
    """
    path = Path(profile_dir) / _IDENTITY_FILE
    path.parent.mkdir(parents=True, exist_ok=True)

    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, json.JSONDecodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}

    offsets = data.get(_TZ_KEY)
    if not isinstance(offsets, dict):
        offsets = {}

    existing = offsets.get(platform)
    if (
        not allow_change
        and isinstance(existing, (int, float))
        and float(existing) != float(hours)
    ):
        raise ValueError(
            f"{platform} is already stored at tz offset {existing:g}. Using {hours:g} "
            "would duplicate every message instead of replacing it. "
            "Delete store/graph.rl and re-ingest to change it."
        )

    offsets[platform] = float(hours)
    data[_TZ_KEY] = offsets
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def owner_from_personal_information(document: dict[str, Any]) -> str | None:
    """The one place Telegram states the owner outright."""
    personal = document.get("personal_information")
    if isinstance(personal, dict):
        user_id = personal.get("user_id")
        if user_id not in (None, ""):
            return f"user{user_id}"
    return None


def infer_owner(chats: Iterable[dict[str, Any]]) -> tuple[str | None, int]:
    """Fallback: the person appearing in the most distinct chats.

    Breadth, not message count — a loud group channel would win on volume while
    the owner is spread thinly across many chats. Bots are excluded.

    **A bare plurality is not evidence.** In one real single-chat export two ids
    appeared once each and tie-breaking fell to dict order, electing the
    *correspondent* as the owner — which then silently labelled every Telegram row
    `is_self=False`. So the winner must lead the runner-up outright, and must
    appear in more than one chat. Ambiguity returns None and the caller reports it
    rather than guessing (§3.1: a wrong guess must not look like a fact).
    """
    per_person: Counter[str] = Counter()
    for chat in chats:
        seen_here: set[str] = set()
        for msg in chat.get("messages") or []:
            from_id = msg.get("from_id")
            if isinstance(from_id, str) and from_id.startswith("user"):
                seen_here.add(from_id)
        per_person.update(seen_here)
    if not per_person:
        return None, 0

    ranked = per_person.most_common(2)
    best, count = ranked[0]
    if count < 2:
        # Everyone appears in exactly one chat: this file cannot identify anyone.
        return None, count
    if len(ranked) > 1 and ranked[1][1] == count:
        # A tie is an answer we do not have.
        return None, count
    return best, count
