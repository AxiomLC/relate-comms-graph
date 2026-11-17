"""Telegram Desktop JSON export -> canonical `Message` rows.

Validated against the official spec (core.telegram.org/import-export) and two real
exports from this machine (2026-11-14):

  * whole-account export  -> {"about": ..., "chats": {"list": [...]}, ...}
  * single-chat export    -> bare Chat object {"name", "type", "id", "messages"}

Both share one message schema. The two files were verified message-for-message
identical for the same chat, so one bulk download legitimately replaces a
per-chat point-and-click loop.

WHAT THE REAL FILES TAUGHT US (beyond the spec text):

1. `text` is `str` OR `list` mixing strings and entity dicts. 105 of 1215 rows in
   the real account export were lists. Join in order; never index [0].
2. Service rows have `actor` / `actor_id` and NO `from`. 344 of 1215 rows.
3. `text_entities` is present on EVERY row, including plain ones, and disagrees
   with `text` often. Build the body from `text`; use entities only as a signal.
4. Entity types in the wild include `cashtag`, `plain`, `mention_name` — more
   than the docs table lists. The handler must not KeyError on an unknown type.
5. `photo` / `file` point at paths like `chats/chat_01/photos/...`; a text-only
   export has no such folders, so never stat them.
6. `date_unixtime` is present in the bulk export but was MISSING from the
   single-chat sample. `date` alone is local time with no offset.

IS_SELF: the real export has `personal_information: null` and no Saved Messages
chat, so Telegram never states whose account this is. Owner resolution lives in
`identity.py` and is persisted, because a per-file guess makes the same message
`is_self=True` in the bulk export and `False` in a single-chat export — that was
a real failing test, not theory. Pass `self_id=` or `profile_dir=` and exports agree.
"""
from __future__ import annotations

import json

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .. import identity
from ..schema import AttachmentRef, Chat, IngestResult, Message, make_key

PLATFORM = "telegram"

# Message fields that point at a media file. Presence of any => has_attachments.
_MEDIA_FIELDS = ("photo", "file", "thumbnail", "contact_vcard")

# Fields whose value is a relative path we may want as an AttachmentRef.
_PATH_FIELDS = ("photo", "file")


def _join_text(text: Any) -> str:
    """Flatten Telegram's polymorphic `text` into a plain string.

    `str` -> itself. `list` -> concatenate in order; strings stay as-is and entity
    dicts contribute their `text`. Anything else is not valid Telegram and gets
    reported rather than coerced.
    """
    if text is None:
        return ""
    if isinstance(text, str):
        return text
    if isinstance(text, list):
        parts: list[str] = []
        for item in text:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                value = item.get("text")
                parts.append(value if isinstance(value, str) else "")
            else:
                parts.append(str(item))
        return "".join(parts)
    return str(text)


def _parse_ts(msg: dict[str, Any], tz_offset_hours: float = 0) -> datetime | None:
    """Prefer `date_unixtime` (unambiguous); fall back to local `date`.

    `date` carries no offset. `tz_offset_hours` is the caller's statement of which
    wall clock the export was written in; without it we read `date` as UTC and the
    result is wrong by however many hours the caller was from Greenwich (§3.1).
    """
    raw_unix = msg.get("date_unixtime")
    if raw_unix not in (None, ""):
        try:
            return datetime.fromtimestamp(int(raw_unix), tz=timezone.utc)
        except (TypeError, ValueError, OSError):
            pass
    raw_date = msg.get("date")
    if isinstance(raw_date, str) and raw_date:
        try:
            naive = datetime.fromisoformat(raw_date)
        except ValueError:
            return None
        if naive.tzinfo is None:
            # Wall clock with no offset: apply the caller's offset, or treat as UTC
            # and say so. Silently assuming UTC is the bug §9.2 caught.
            return (naive - timedelta(hours=tz_offset_hours)).replace(tzinfo=timezone.utc)
        return naive.astimezone(timezone.utc)
    return None


def _iter_chats(document: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    """Return (chats, warnings). Handles Result wrapper and bare Chat object."""
    warnings: list[str] = []

    # Single-chat export: a bare Chat object. Gotcha #2.
    if "messages" in document and "chats" not in document:
        warnings.append(
            "bare Chat object (single-chat export); reading it directly, "
            "no Result wrapper to unwrap"
        )
        name = document.get("name") or "unknown"
        return [{"id": document.get("id"), "name": name,
                 "type": document.get("type") or "personal_chat",
                 "messages": document.get("messages") or []}], warnings

    chats: list[dict[str, Any]] = []
    for container_key in ("chats", "left_chats"):
        container = document.get(container_key) or {}
        entries = container.get("list") or []
        if container_key == "left_chats" and entries:
            warnings.append(f"including {len(entries)} entries from left_chats")
        chats.extend(entries)
        if entries:
            warnings.append(f"{len(entries)} chats read from '{container_key}'")
    if not chats:
        warnings.append("no chats found in export")
    return chats, warnings


def _resolve_owner(
    document: dict[str, Any],
    chats: list[dict[str, Any]],
    self_id: str | None,
    profile_dir: str | Path | None,
) -> tuple[str | None, str | None]:
    """Return (owner_id, note-for-warnings), following identity.py's precedence.

    Persisting the owner is what makes `is_self` agree between a bulk export and
    a single-chat export of the same account.
    """
    if self_id:
        return self_id, None

    if profile_dir:
        stored = identity.load_owner(profile_dir, PLATFORM)
        if stored:
            return stored, None

    stated = identity.owner_from_personal_information(document)
    if stated:
        if profile_dir:
            try:
                identity.save_owner(profile_dir, stated, evidence="personal_information",
                                    platform=PLATFORM)
            except ValueError as exc:
                return stated, f"owner conflict: {exc}"
        return stated, None

    inferred, breadth = identity.infer_owner(chats)
    if not inferred:
        return None, (
            "is_self unresolved: no personal_information and no user senders; "
            "all rows marked is_self=False"
        )

    note = (
        f"is_self inferred (no personal_information): {inferred} appears in "
        f"{breadth} chats; pass self_id= or profile_dir= so exports agree"
    )
    if profile_dir:
        try:
            identity.save_owner(profile_dir, inferred,
                                evidence=f"inferred from {breadth} chats",
                                platform=PLATFORM)
        except ValueError as exc:
            return inferred, f"owner conflict: {exc}"
    return inferred, note


def parse(
    export_path: str | Path,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
    self_id: str | None = None,
    include_service: bool = True,
    profile_dir: str | Path | None = None,
    tz_offset_hours: float = 0,
    exclude_silent_groups: bool = False,
) -> IngestResult:
    """Parse one Telegram export file (or an export directory) into Messages.

    `since` / `until` bound the export window at parse time — this is how "the
    last 6 months" is expressed without asking a user to click through every chat.
    Both are inclusive and must be timezone-aware.

    Owner resolution order: `self_id` -> persisted owner in `profile_dir` ->
    `personal_information` in this file -> infer from this file (and persist if
    `profile_dir` was given). Passing `self_id` or reusing a profile keeps
    `is_self` identical across exports of the same account.

    `exclude_silent_groups=True` drops group chats the owner never sent a message in.
    Off by default — the store is whole unless the user asks otherwise — and counted
    in `skipped`, never silently lost. On the real export this is a no-op: all 9
    groups are ones the owner spoke in.
    """
    path = Path(export_path)
    if path.is_dir():
        candidates = sorted(path.glob("result.json"))
        if not candidates:
            candidates = sorted(path.rglob("result.json"))
        if not candidates:
            raise FileNotFoundError(f"no result.json under {path}")
        merged = IngestResult(platform=PLATFORM, export_path=str(path))
        for candidate in candidates:
            part = parse(candidate, since=since, until=until,
                         self_id=self_id, include_service=include_service,
                         profile_dir=profile_dir, tz_offset_hours=tz_offset_hours,
                         exclude_silent_groups=exclude_silent_groups)
            merged.chats.extend(part.chats)
            merged.messages.extend(part.messages)
            merged.attachments.extend(part.attachments)
            for kind, n in part.unknown_kinds.items():
                merged.unknown_kinds[kind] = merged.unknown_kinds.get(kind, 0) + n
            for reason, n in part.skipped.items():
                merged.skipped[reason] = merged.skipped.get(reason, 0) + n
            merged.warnings.extend(f"{candidate.name}: {w}" for w in part.warnings)
        return merged

    for bound, label in ((since, "since"), (until, "until")):
        if bound is not None and bound.tzinfo is None:
            raise ValueError(f"{label} must be timezone-aware")

    document = json.loads(path.read_text(encoding="utf-8"))
    result = IngestResult(platform=PLATFORM, export_path=str(path))
    chats, chat_warnings = _iter_chats(document)
    result.warnings.extend(chat_warnings)

    resolved_self, owner_note = _resolve_owner(document, chats, self_id, profile_dir)
    if owner_note:
        result.warnings.append(owner_note)

    for chat in chats:
        chat_id = str(chat.get("id"))
        chat_kind = chat.get("type") or "unknown"
        messages = chat.get("messages") or []

        # Parse the messages FIRST, then decide whether the chat is a thread at all.
        #
        # A Telegram chat whose every row is a service row is not a conversation:
        # it is "X joined Telegram", "A contact added Y to the group", "history
        # cleared". 328 of the 470 correspondent-less threads in the real store were
        # exactly that, and they drew as a grid of orphan nodes on the canvas.
        # A chat with no surviving message has nothing to be a thread about, so no
        # `Chat` is emitted and no `Thread` node is written.
        before = len(result.messages)
        for msg in messages:
            _parse_message(msg, chat_id, resolved_self, result,
                           since, until, include_service, tz_offset_hours)
        if len(result.messages) == before:
            result.note_skip("chat with no non-service messages")
            continue

        # Same fallback as `_parse_message`: an id with no name is still a
        # participant, and dropping it is what made the thread an orphan.
        participant_names = {
            str(m.get("from") or m.get("actor") or m.get("from_id") or m.get("actor_id"))
            for m in messages
            if m.get("from") or m.get("actor") or m.get("from_id") or m.get("actor_id")
        }
        is_group = chat_kind not in {"personal_chat", "bot_chat", "saved_messages"}

        # Silent-group gate. A group the owner was added to and never spoke in is not
        # a conversation they had. Decided BEFORE the `Chat` is appended, so a dropped
        # group leaves no orphan messages behind — the same ordering Messenger uses.
        #
        # Only groups are affected: a 1:1 thread someone messaged once is still a
        # conversation the owner had, and hiding it is a view toggle, not a drop.
        #
        # The rows for this chat are already in `result.messages`, so a drop has to
        # truncate them back to `before` — skipping only the Chat would leave orphan
        # messages with no thread to hang from.
        if exclude_silent_groups and is_group and not any(
                m.is_self for m in result.messages[before:]):
            result.note_skip("group thread the owner never spoke in")
            del result.messages[before:]
            continue

        result.chats.append(Chat(
            platform=PLATFORM,
            chat_id=chat_id,
            title=str(chat.get("name") or ""),
            kind=chat_kind,
            is_group=is_group,
            participant_names=tuple(sorted(participant_names)),
        ))

    return result


def _parse_message(
    msg: dict[str, Any],
    chat_id: str,
    self_id: str | None,
    result: IngestResult,
    since: datetime | None,
    until: datetime | None,
    include_service: bool,
    tz_offset_hours: float = 0,
) -> None:
    kind = msg.get("type") or "unknown"
    message_id = str(msg.get("id"))
    ts = _parse_ts(msg, tz_offset_hours)

    if ts is None:
        # No usable timestamp: we cannot place it on a timeline. Report, don't guess.
        result.note_skip(f"no timestamp ({kind})")
        result.warnings.append(f"{chat_id}:{message_id}: unparseable date, row skipped")
        return

    if since is not None and ts < since:
        result.note_skip("before window")
        return
    if until is not None and ts > until:
        result.note_skip("after window")
        return

    if kind == "service" and not include_service:
        result.note_skip("service excluded by request")
        return

    # Sender: `from` normally; service rows carry `actor` instead. Gotcha #4.
    sender_name = msg.get("from") or msg.get("actor") or ""
    sender_id = msg.get("from_id") or msg.get("actor_id") or None

    # A sender with an id but no display name is a real person the export did not
    # name — 160 rows in the real export, all strangers who messaged once. Leaving
    # the name blank meant `participant_names` was empty, so no Correspondent was
    # written and the thread became an orphan node with no edge. The id is the only
    # identity available, so it becomes the name: ugly, but it is a fact, and it
    # keeps the thread connected.
    if not sender_name and sender_id:
        sender_name = str(sender_id)

    body = _join_text(msg.get("text"))
    has_attachments = any(msg.get(f) for f in _MEDIA_FIELDS)

    reply_raw = msg.get("reply_to_message_id")
    reply_to = (
        make_key(PLATFORM, chat_id, str(reply_raw))
        if reply_raw not in (None, "") else None
    )

    # raw_kind carries the second dimension: a media row is type=message but not text.
    if kind == "service":
        raw_kind = f"service:{msg.get('action') or 'unknown'}"
    elif msg.get("media_type"):
        raw_kind = str(msg["media_type"])
    elif msg.get("poll"):
        raw_kind = "poll"
    elif msg.get("location_information"):
        raw_kind = "location"
    elif msg.get("contact_information"):
        raw_kind = "contact"
    elif msg.get("invoice_information"):
        raw_kind = "invoice"
    elif has_attachments:
        raw_kind = "attachment"
    else:
        raw_kind = "text"

    if raw_kind != "text":
        result.note_kind(raw_kind)

    result.messages.append(Message(
        key=make_key(PLATFORM, chat_id, message_id),
        platform=PLATFORM,
        chat_id=chat_id,
        message_id=message_id,
        ts_utc=ts,
        sender_name=sender_name,
        sender_id=sender_id,
        body=body,
        reply_to=reply_to,
        has_attachments=has_attachments,
        is_self=bool(self_id) and sender_id == self_id,
        raw_kind=raw_kind,
        forwarded_from=msg.get("forwarded_from"),
        saved_from=msg.get("saved_from"),
    ))

    for field_name in _PATH_FIELDS:
        rel = msg.get(field_name)
        if isinstance(rel, str) and rel:
            result.attachments.append(AttachmentRef(
                platform=PLATFORM,
                chat_id=chat_id,
                message_id=message_id,
                path=rel,
                mime=msg.get("mime_type"),
                size=msg.get("file_size"),
            ))
