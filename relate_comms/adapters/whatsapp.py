"""WhatsApp chat export (`chat.txt`) -> canonical `Message` rows.

Validated against two real exports from this machine (2026-11-14), both produced by
WhatsApp Web/Desktop "Export chat — without media":

    [5/22/26, 8:45:50 AM] +1 (917) 400-4025: Hi
    [4/19/26, 2:32:33 PM] +27 84 518 9029: line one
    line two, a continuation
    [4/19/26, 2:32:35 PM] - Messages and calls are end-to-end encrypted. ...
    [10/27/26, 9:34:12 PM] You: <video omitted>

WHAT THE REAL FILES TAUGHT US:

1. **No line looks like a header by accident.** One body line in the US export is a
   bare `[` (part of a pasted JSON block). A naive `line.startswith("[")` parser
   splits that message and orphans the rest of the JSON into the *previous* message.
   The header test therefore requires the whole `[date, time] ` prefix to match.
2. **Bodies are multi-line.** 213 of 373 lines in one file were continuations, joined
   with `\\n`. Blank lines inside a body are preserved; trailing ones are trimmed.
3. **System rows are prefixed `- `** where a sender would be. They are kept and kinded
   (`system:...`), never dropped — §3.2.
4. **`You` is the owner.** No ID, no `personal_information`; the literal `You` is the
   only marker. Everything else is a display name (a phone number, usually).
5. **Media is a placeholder, not a path.** `<image omitted>`, `<video omitted>`,
   `<document omitted> FILENAME.docx`, `<album message>`, `[Forwarded]` prefix.
   There is no file on disk, so an attachment has no path — only a kind and, for
   documents, a filename we can keep as a scrubbed hint.
6. **`<Media omitted>`** is the Android spelling of the same thing; accepted too.
7. **Date is `M/D/YY`** — month first. Proven, not assumed: 125 header lines in the
   US export have a first field >12, which can only be a day if the format were D/M.
   Detection still handles D/M exports (EU handsets) by looking for a first field >12.

MESSAGE IDS DO NOT EXIST
------------------------
`chat.txt` carries no message id, so `Message.key` is derived from content:
`sha256(chat_id, timestamp, sender, body)`. Re-exporting the same chat is therefore
idempotent. The cost is that two byte-identical messages from the same sender in the
same second are indistinguishable; that is counted and reported as
`key collisions` rather than allowed to vanish (§9.1.2, "delta, not re-parse").

The chat id is the export filename, which WhatsApp sets to the contact/group name.
"""
from __future__ import annotations

import hashlib
import io
import re
import unicodedata
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from .. import identity
from ..schema import AttachmentRef, Chat, IngestResult, Message

PLATFORM = "whatsapp"

# Owner marker in the text. The only statement of identity WhatsApp makes.
SELF_NAME = "You"

# Group evidence in `chat.txt`. WhatsApp writes no participant list, so group-ness has
# to be inferred from what the file actually contains:
#
#   `- Alice added Bob`            a membership change — only a group has these
#   `- Alice changed the group name to 'X'`
#   `- Alice removed Bob`
#   `- Alice turned off disappearing messages`
#
# A 1:1 chat has no such rows. This is the signal that makes the silent-group gate work
# for a group the Owner never spoke in — `SELF_NAME` alone cannot, because a group the
# Owner never wrote in has no `You:` line at all.
_GROUP_SYSTEM = re.compile(
    r"\b(?:added|removed|changed the group|created group|turned (?:on|off) "
    r"disappearing|joined using this group's invite)\b",
    re.I,
)

# `[9/4/26, 10:29:35 AM] - Alice changed the group name to 'X'` — the `- ` form is a
# system row, and its text is the evidence.
_SYSTEM_ROW = re.compile(r"^\[([^\]]+)\]\s*-\s*(?P<text>.+)$")

# `[5/22/26, 8:45:50 AM] ` — must match the whole prefix, see gotcha #1.
_HEADER = re.compile(
    r"^\[(?P<a>\d{1,2})/(?P<b>\d{1,2})/(?P<year>\d{2,4}),\s*"
    r"(?P<hour>\d{1,2}):(?P<minute>\d{2})(?::(?P<second>\d{2}))?"
    r"\s*(?P<ampm>[APap][Mm])?\]\s?"
)

# `[Forwarded] ` is a prefix on the body, not part of the message.
_FORWARDED = re.compile(r"^\[Forwarded\]\s*")

# `<image omitted>`, `<Media omitted>`, `<document omitted> name.docx`, `<album message>`
_MEDIA = re.compile(r"^<([A-Za-z ]+?)(?: omitted| message)?>(?:\s+(?P<name>.+))?$")

_MEDIA_KINDS = {
    "image": "image",
    "photo": "image",
    "video": "video",
    "audio": "audio",
    "ptt": "voice_message",
    "gif": "gif",
    "sticker": "sticker",
    "document": "document",
    "media": "attachment",
    "album": "album",
    "location": "location",
    "contact card": "contact",
}


def _decode(data: bytes) -> str:
    """`chat.txt` is UTF-8 in both real exports; tolerate BOM and CRLF."""
    text = data.decode("utf-8-sig", errors="replace")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def read_export(export_path: str | Path) -> tuple[str, str]:
    """Return (text, chat_title) for a `.zip` export or a bare `.txt`/`.md`.

    The zip holds `chat.txt` plus a markdown twin; the txt is the one we parse. The
    filename is the chat title: WhatsApp names the archive after the contact/group.
    """
    path = Path(export_path)
    if path.is_dir():
        for name in ("chat.txt", "_chat.txt"):
            candidate = path / name
            if candidate.exists():
                path = candidate
                break
        else:
            raise FileNotFoundError(f"no chat.txt in {path}")

    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as archive:
            members = [n for n in archive.namelist()
                       if Path(n).name in {"chat.txt", "_chat.txt"}]
            if not members:
                raise FileNotFoundError(f"no chat.txt inside {path}")
            data = archive.read(members[0])
        title_source = path.stem
    else:
        data = path.read_bytes()
        title_source = path.parent.name if path.name in {"chat.txt", "_chat.txt"} else path.stem

    return _decode(data), title_source


def _detect_month_first(lines: list[str]) -> bool:
    """True when dates are M/D/YY. A first field >12 can only be a day.

    Defaults to month-first: both real exports on this machine are US-locale, and
    there is no other signal in the file.
    """
    for line in lines:
        match = _HEADER.match(line)
        if match and int(match.group("a")) > 12:
            return False
    return True


def _to_utc(
    match: re.Match[str], *, month_first: bool, tz_offset_hours: float
) -> datetime | None:
    a, b = int(match.group("a")), int(match.group("b"))
    month, day = (a, b) if month_first else (b, a)
    year = int(match.group("year"))
    if year < 100:
        year += 2000

    hour = int(match.group("hour"))
    ampm = (match.group("ampm") or "").upper()
    if ampm == "PM" and hour != 12:
        hour += 12
    elif ampm == "AM" and hour == 12:
        hour = 0

    try:
        naive = datetime(year, month, day, hour,
                         int(match.group("minute")), int(match.group("second") or 0))
    except ValueError:
        return None

    # The export carries local wall-clock with no offset. We anchor it with a
    # declared offset rather than reading it as UTC, so a window filter is honest.
    return (naive - timedelta(hours=tz_offset_hours)).replace(tzinfo=timezone.utc)


def split_lines(text: str) -> list[tuple[re.Match[str], str, list[str]]]:
    """Group into (header match, first line remainder, continuation lines).

    A line only starts a message when the full `[date, time] ` prefix matches
    (gotcha #1). Anything before the first header is a preamble; the caller counts
    it as a skip so the row count never silently disagrees with the file.
    """
    groups: list[tuple[re.Match[str], str, list[str]]] = []
    current: tuple[re.Match[str], list[str]] | None = None

    for line in text.split("\n"):
        match = _HEADER.match(line)
        if match:
            remainder = line[match.end():]
            if current is not None:
                head, body = current
                groups.append((head, body[0], body[1:]))
            current = (match, [remainder])
        elif current is not None:
            current[1].append(line)

    if current is not None:
        head, body = current
        groups.append((head, body[0], body[1:]))
    return groups


def _split_sender(remainder: str) -> tuple[str | None, str]:
    """`Name: body` -> (name, body). System rows are `- text` and have no sender.

    The separator is searched within the first 64 characters, because a body may
    legitimately contain `: ` and must not be mistaken for a sender.
    """
    if remainder.startswith("- "):
        return None, remainder

    colon = remainder.find(": ")
    if 0 < colon <= 64:
        candidate = remainder[:colon]
        # A sender never contains a newline, and never looks like a URL scheme.
        if "\n" not in candidate and "://" not in candidate:
            return candidate.strip(), remainder[colon + 2:]
    return None, remainder


def _media_kind(body: str) -> tuple[str | None, str | None]:
    """Return (kind, filename) when the body is a media placeholder."""
    stripped = body.strip()
    match = _MEDIA.match(stripped)
    if not match:
        return None, None
    label = match.group(1).strip().lower()
    name = match.group("name")
    if label == "album" and not name:
        return "album", None
    kind = _MEDIA_KINDS.get(label)
    if kind is None:
        return None, None
    return kind, (name.strip() if name else None)


def _system_kind(body: str) -> str:
    """A stable, queryable label for a `- ` row."""
    text = body.strip().lower()
    for marker, label in (
        ("end-to-end encrypted", "encryption_notice"),
        ("messages and calls are end-to-end", "encryption_notice"),
        ("doesn't support it", "unsupported_message"),
        ("changed the subject", "subject_change"),
        ("changed this group's icon", "icon_change"),
        ("created group", "group_create"),
        ("added", "member_add"),
        ("removed", "member_remove"),
        ("left", "member_leave"),
        ("joined", "member_join"),
        ("deleted this message", "message_deleted"),
    ):
        if marker in text:
            return f"system:{label}"
    return "system:other"


def message_key(chat_id: str, ts: datetime, sender: str, body: str, ordinal: int = 0) -> str:
    """Content fingerprint — the only stable id a `.txt` export allows.

    Includes chat, **minute**-resolution timestamp, sender, exact body **and the
    ordinal within that minute**. The ordinal is not decoration: a photo album exports
    seven bullet-identical `<image omitted>` rows in one second, and without it six
    real messages would collapse into one row.

    **Why the minute, not the second.** WhatsApp has two export routes and they do not
    agree on precision: the native `chat.txt` writes `[11/16/26, 11:09:15 PM]`, while
    the HTML exporter writes a day separator plus `23:09`. Hashing the second meant the
    same message got two different keys depending on which route produced it, so a user
    who downloaded a chat both ways got every message twice inside one thread — the
    thread key already matches, because `_chat_id()` hashes the chat *title*.

    Truncating to the minute makes both routes agree, and `MERGE` collapses them for
    free. `ts_utc` on the stored row keeps its full precision; only the identity hash is
    coarser.

    Why the ordinal is safe: WhatsApp writes the file in chronological order, so a
    re-export reproduces the same position for the same message. It would only drift
    if someone deleted one of a set of same-minute duplicates upstream — in which case
    the surviving rows still merge correctly and the deleted one becomes an orphan,
    which is the correct outcome.
    """
    # Whitespace is collapsed for the KEY only; the stored body keeps its formatting.
    # The two export routes disagree on trailing spaces (`'Thad here \n'` vs
    # `'Thad here\n'`), which is not a difference in what was said.
    material = "\x1f".join((
        chat_id, ts.strftime("%Y-%m-%dT%H:%MZ"),
        " ".join(sender.split()), " ".join(body.split()), str(ordinal),
    ))
    return f"{PLATFORM}:{chat_id}:{hashlib.sha256(material.encode('utf-8')).hexdigest()[:24]}"


def _clean_name(name: str) -> str:
    """Normalise the sender label. Strips the invisible marks some exports carry."""
    return unicodedata.normalize("NFC", name).strip().lstrip("\u200e\u200f")


def parse(
    export_path: str | Path,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
    self_id: str | None = None,
    include_service: bool = True,
    profile_dir: str | Path | None = None,
    tz_offset_hours: float = 0,
    month_first: bool | None = None,
    exclude_silent_groups: bool = False,
) -> IngestResult:
    """Parse one WhatsApp export (`.zip`, `chat.txt`, or the folder holding it).

    `since` / `until` bound the window at parse time and must be timezone-aware.

    `tz_offset_hours` is the offset the export's timestamps were written in, e.g.
    `-5` for US Eastern. The file never states it, so callers declare it; the
    default treats wall clock as UTC and is flagged in `warnings`.

    `self_id` / `profile_dir` follow `identity.py`: who is "me" must not change
    between exports. For WhatsApp the owner is the literal `You`, so `self_id` is
    only used to *name* that identity, not to find it.

    `exclude_silent_groups=True` drops group chats the owner never sent a message in.
    Off by default, counted in `skipped` when on. **Untested against a real group
    export** — the current store holds no WhatsApp group threads, so this gate has
    only fixture coverage.
    """
    for bound, label in ((since, "since"), (until, "until")):
        if bound is not None and bound.tzinfo is None:
            raise ValueError(f"{label} must be timezone-aware")

    path = Path(export_path)
    text, title = read_export(path)

    result = IngestResult(platform=PLATFORM, export_path=str(path))
    chat_id = _chat_id(title)
    lines = text.split("\n")

    if month_first is None:
        month_first = _detect_month_first(lines)
    else:
        result.warnings.append(
            f"date order forced to {'M/D' if month_first else 'D/M'} by the caller")

    if tz_offset_hours == 0:
        result.warnings.append(
            "timestamps read as UTC: the export states no offset (pass tz_offset_hours=)")

    groups = split_lines(text)
    if not groups:
        result.warnings.append("no message headers found; is this a chat export?")
        return result

    if lines and lines[0].strip() and not _HEADER.match(lines[0]):
        result.note_skip("preamble before first message")

    senders: set[str] = set()
    # The ordinal slot is keyed on the **minute**, matching `message_key()`. Keying it on
    # the full timestamp while the fingerprint used minutes meant two rows in the same
    # minute both got ordinal 0, produced identical keys, and the second was dropped —
    # the same class of bug that cost 31 rows in the SMS adapter.
    seen_keys: dict[tuple[datetime, str, str], int] = {}
    collisions = 0
    # Group evidence, collected while walking. See `_GROUP_SYSTEM`.
    group_evidence = False

    for match, remainder, continuation in groups:
        ts = _to_utc(match, month_first=month_first, tz_offset_hours=tz_offset_hours)
        if ts is None:
            result.note_skip("unparseable date")
            result.warnings.append(f"unparseable header: {match.group(0)!r}")
            continue

        if since is not None and ts < since:
            result.note_skip("before window")
            continue
        if until is not None and ts > until:
            result.note_skip("after window")
            continue

        body_lines = [remainder] + continuation
        while body_lines and not body_lines[-1].strip():
            body_lines.pop()
        raw_body = "\n".join(body_lines)

        sender, body = _split_sender(raw_body)
        forwarded = False
        if body:
            stripped = _FORWARDED.match(body)
            if stripped:
                forwarded = True
                body = body[stripped.end():]

        if sender is None:
            # A system row is the only group evidence `chat.txt` carries. Checked
            # before the `include_service` gate, because the evidence is a fact about
            # the chat, not a message we are choosing to keep.
            if _GROUP_SYSTEM.search(body or ""):
                group_evidence = True
            if not include_service:
                result.note_skip("service excluded by request")
                continue
            kind = _system_kind(body)
            result.note_kind(kind)
            slot = ts.replace(second=0, microsecond=0)
            ordinal = seen_keys.get((slot, "", body), 0)
            seen_keys[(slot, "", body)] = ordinal + 1
            key = message_key(chat_id, ts, "", body, ordinal)
            message = Message(
                key=key, platform=PLATFORM, chat_id=chat_id,
                message_id=key.rsplit(":", 1)[1],
                ts_utc=ts, sender_name="", sender_id=None, body="",
                reply_to=None, has_attachments=False, is_self=False,
                raw_kind=kind,
            )
            result.messages.append(message)
            continue

        sender = _clean_name(sender)
        senders.add(sender)
        media, filename = _media_kind(body)
        if media is None and forwarded:
            # `[Forwarded] <album message>`: the prefix hid the placeholder from the
            # check above, which ran on the raw body.
            prefix = _FORWARDED.match(body)
            media, filename = _media_kind(body[prefix.end():] if prefix else body)

        if media is not None:
            raw_kind = media
            has_attachments = True
            if filename:
                result.attachments.append(AttachmentRef(
                    platform=PLATFORM, chat_id=chat_id,
                    message_id="", path=filename, mime=None, size=None))
        else:
            raw_kind = "text"
            has_attachments = False

        if raw_kind != "text":
            result.note_kind(raw_kind)

        slot = ts.replace(second=0, microsecond=0)
        ordinal = seen_keys.get((slot, sender, body), 0)
        seen_keys[(slot, sender, body)] = ordinal + 1
        if ordinal:
            # A same-minute repeat is normal for media albums, not an error. Count
            # it so the number is visible without treating it as data loss.
            collisions += 1

        key = message_key(chat_id, ts, sender, body, ordinal)

        message = Message(
            key=key, platform=PLATFORM, chat_id=chat_id,
            message_id=key.rsplit(":", 1)[1],
            ts_utc=ts, sender_name=sender, sender_id=None, body=body,
            reply_to=None, has_attachments=has_attachments,
            is_self=sender == SELF_NAME, raw_kind=raw_kind,
        )
        result.messages.append(message)

    # Group-ness. **`SELF_NAME` alone is not enough**, and requiring it was a bug: a
    # group the Owner never wrote in has no `You:` line at all, so it was classified
    # `personal_chat` and the silent-group gate could never fire on it — exactly the
    # case the gate exists to catch. Verified against a real native export
    # (`Local Community Events (OSA).zip`): 6 senders, 21 membership system rows, no
    # `You:` line, and the old rule called it a 1:1.
    #
    # Two independent signals, either of which is enough:
    #   1. a membership system row (`added`, `removed`, `changed the group name`, …)
    #      — a 1:1 chat has none, because there is nobody to add
    #   2. the Owner plus more than three senders — the old rule, kept because it is
    #      the only signal when a group has no system rows at all
    is_group = group_evidence or (
        any(s == SELF_NAME for s in senders) and len(senders) > 3)

    # Silent-group gate. Decided BEFORE the `Chat` is appended, so a dropped group
    # leaves no orphan messages behind. `is_self` is `sender == SELF_NAME`, so the
    # check is the same fact the Chat would carry.
    #
    # The rows are already parsed at this point, so a drop has to clear them as well
    # as skip the Chat — otherwise the messages land with no thread to hang from.
    # Falling through rather than returning keeps the collision warning below.
    if exclude_silent_groups and is_group and not any(
            m.is_self for m in result.messages):
        result.note_skip("group thread the owner never spoke in")
        result.messages.clear()
        result.attachments.clear()
    else:
        result.chats.append(Chat(
            platform=PLATFORM, chat_id=chat_id, title=title,
            kind="group_chat" if is_group else "personal_chat",
            is_group=is_group,
            participant_names=tuple(sorted(senders)),
        ))

    if collisions:
        result.note_kind("same-second repeats")
        result.warnings.append(
            f"{collisions} message(s) share a timestamp with an identical body "
            "(media albums); each kept as its own row via its position")

    return result


def _chat_id(title: str) -> str:
    """Stable chat id from the export name.

    The filename is the contact/group name, which is *personal data*. It is hashed
    so the same chat keeps one id across re-exports without printing a phone number
    into every message key.
    """
    digest = hashlib.sha256(_clean_name(title).encode("utf-8")).hexdigest()[:16]
    return f"wa_{digest}"
