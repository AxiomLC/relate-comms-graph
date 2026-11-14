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


def load_owner(profile_dir: str | Path) -> str | None:
    path = Path(profile_dir) / _IDENTITY_FILE
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    owner = data.get("owner_id")
    return owner if isinstance(owner, str) and owner else None


def save_owner(profile_dir: str | Path, owner_id: str, *, evidence: str) -> None:
    path = Path(profile_dir) / _IDENTITY_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = load_owner(profile_dir)
    if existing and existing != owner_id:
        # Never overwrite a known owner silently.
        raise ValueError(
            f"owner already recorded as {existing!r} ({evidence}); "
            "refusing to overwrite with a different id"
        )
    path.write_text(
        json.dumps({"owner_id": owner_id, "evidence": evidence}, indent=2),
        encoding="utf-8",
    )


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
    (best, count), = per_person.most_common(1)
    return best, count
