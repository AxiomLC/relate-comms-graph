"""LinkedIn `messages.csv` -> canonical `Message` rows.

Verified against a real archive (2026-11-14, "Basic" LinkedIn data export).

THE BASIC EXPORT *DOES* CONTAIN MESSAGES
----------------------------------------
§9.1.3 of buildNOTES said the larger archive was required. That is wrong: the
**Basic** export (23 files, 216 KB) carries `messages.csv` with the full DM history.
The modal guidance is corrected accordingly — one less 24-hour wait for the user.

COLUMNS
-------
    CONVERSATION ID, CONVERSATION TITLE, FROM, SENDER PROFILE URL, TO,
    RECIPIENT PROFILE URLS, DATE, SUBJECT, CONTENT, FOLDER, ATTACHMENTS

WHAT THE REAL FILE TAUGHT US:

1. **Sender and recipient are named outright**, so `is_self` is a fact, not a guess —
   the same luck as Messenger, unlike WhatsApp.
2. **`DATE` is already UTC** (`2026-11-13 13:01:58 UTC`). No offset guessing, and no
   `tz_offset_hours` argument: unlike Telegram/WhatsApp, this adapter must not accept
   one, because accepting it would mean silently corrupting correct timestamps.
3. **`TO` may contain commas inside a person's name.** Real value:
   `"Steve Mikano CIA, AIC-M, AINS, SSBB"`. Splitting on `,` invents three recipients.
   csv handles the quoting; we then split only on `;`, which LinkedIn uses for real
   multi-recipient sends.
4. **`FOLDER` is `INBOX` or `ARCHIVE`.** Archived threads are still your messages and
   are included; a `folder` filter is exposed rather than applied.
5. **`CONVERSATION TITLE` is usually empty** for 1:1 DMs and set for InMail/ads.
   The chat title therefore falls back to the other participant's name.
6. **`LinkedIn Member`** appears as a sender (35 rows) — a member whose profile is
   unavailable. It is not one person, so it must never be treated as a chat title
   when a real name exists.
7. **No message id.** Key is a content fingerprint plus a same-second ordinal, as with
   WhatsApp and Messenger.
8. **`CONTENT` keeps real newlines and non-breaking spaces** (`\\xa0`). Both are
   normalised to ordinary spaces/wraps so stored bodies are searchable.
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from ..schema import AttachmentRef, Chat, IngestResult, Message

PLATFORM = "linkedin"

MESSAGES_MEMBER = "messages.csv"

# A sender placeholder, not a person. Must not become a chat title.
_UNKNOWN_SENDER = "linkedin member"

_NBSP = "\xa0"
_WS = re.compile(r"[ \t]+")


def _clean(text: str | None) -> str:
    """Normalise a CSV cell: NBSP to space, collapse horizontal whitespace."""
    if not text:
        return ""
    return "\n".join(_WS.sub(" ", line).rstrip() for line in text.replace(_NBSP, " ").split("\n")).strip()


def _split_recipients(raw: str) -> list[str]:
    """LinkedIn separates real multi-recipient sends with `;`. Commas are unsafe."""
    if not raw:
        return []
    return [part.strip() for part in raw.split(";") if part.strip()]


def _parse_ts(raw: str) -> datetime | None:
    """`2026-11-13 13:01:58 UTC` -> aware UTC. Non-UTC rows are converted, never assumed."""
    value = _clean(raw)
    if not value:
        return None
    match = re.match(
        r"^(?P<date>\d{4}-\d{2}-\d{2})[ T](?P<time>\d{2}:\d{2}(?::\d{2})?)\s*(?P<tz>UTC|Z|[+-]\d{2}:?\d{2})?$",
        value,
    )
    if not match:
        return None
    stamp = f"{match.group('date')}T{match.group('time')}"
    if len(match.group("time")) == 5:
        stamp += ":00"
    tz = match.group("tz") or "UTC"
    if tz in {"UTC", "Z"}:
        stamp += "+00:00"
    else:
        stamp += tz if ":" in tz else f"{tz[:3]}:{tz[3:]}"
    try:
        return datetime.fromisoformat(stamp).astimezone(timezone.utc)
    except ValueError:
        return None


def _thread_id(conversation_id: str) -> str:
    """Keep the conversation id readable but short and filename-safe.

    The raw id is base64 (`2-ZGI2YTNiODY...`) with `+`, `/` and `=` in it. Hashing
    it produces a stable id we can use in keys and paths without escaping.
    """
    digest = hashlib.sha256(conversation_id.encode("utf-8")).hexdigest()[:16]
    return f"li_{digest}"


def message_key(thread_id: str, ts: datetime, sender: str, body: str, ordinal: int = 0) -> str:
    material = "\x1f".join((
        thread_id, ts.strftime("%Y-%m-%dT%H:%M:%SZ"), sender, body, str(ordinal),
    ))
    return f"{PLATFORM}:{thread_id}:{hashlib.sha256(material.encode('utf-8')).hexdigest()[:24]}"


def read_rows(source: str | Path, member: str = MESSAGES_MEMBER) -> list[dict[str, str]]:
    """Read `messages.csv` from a zip archive or a directory holding the export."""
    path = Path(source)
    if path.is_dir():
        candidate = path / member
        if not candidate.exists():
            candidate = next(iter(path.rglob(member)), None)
        if candidate is None:
            raise FileNotFoundError(f"no {member} under {path}")
        raw = candidate.read_bytes()
    elif path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as archive:
            names = [n for n in archive.namelist() if Path(n).name == member]
            if not names:
                raise FileNotFoundError(f"no {member} inside {path}")
            raw = archive.read(names[0])
    else:
        raw = path.read_bytes()

    text = raw.decode("utf-8-sig", errors="replace")
    return list(csv.DictReader(io.StringIO(text)))


def parse(
    source: str | Path,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
    self_id: str | None = None,
    include_service: bool = True,
    profile_dir: str | Path | None = None,
    include_archived: bool = True,
) -> IngestResult:
    """Parse a LinkedIn export into Messages.

    `self_id` is the owner's **display name** (the export names senders, it exposes no
    stable person id in `messages.csv`). `profile_dir` keeps it stable across
    platforms and adapters.

    `include_archived=False` drops `FOLDER == "ARCHIVE"` threads. Default includes
    them: an archived thread is still a message you sent or received (§5.2).
    """
    for bound, label in ((since, "since"), (until, "until")):
        if bound is not None and bound.tzinfo is None:
            raise ValueError(f"{label} must be timezone-aware")

    path = Path(source)
    result = IngestResult(platform=PLATFORM, source=str(path))
    rows = read_rows(path)
    if not rows:
        result.warnings.append("messages.csv had no rows")
        return result

    owner = _resolve_owner(rows, self_id, profile_dir, result)

    seen: dict[tuple[str, datetime, str, str], int] = {}
    repeats = 0
    chats: dict[str, Chat] = {}
    subjects: set[str] = set()

    for row in rows:
        conversation = _clean(row.get("CONVERSATION ID"))
        if not conversation:
            result.note_skip("no conversation id")
            continue
        thread_id = _thread_id(conversation)

        folder = _clean(row.get("FOLDER")).upper()
        if not include_archived and folder == "ARCHIVE":
            result.note_skip("archived excluded by request")
            continue

        ts = _parse_ts(row.get("DATE", ""))
        if ts is None:
            result.note_skip("unparseable date")
            result.warnings.append(f"bad DATE in {conversation}: {row.get('DATE')!r}")
            continue
        if since is not None and ts < since:
            result.note_skip("before window")
            continue
        if until is not None and ts > until:
            result.note_skip("after window")
            continue

        sender = _clean(row.get("FROM"))
        recipients = _split_recipients(_clean(row.get("TO")))
        subject = _clean(row.get("SUBJECT"))
        body = _clean(row.get("CONTENT"))
        attachments_raw = _clean(row.get("ATTACHMENTS"))

        if not include_service and not body:
            result.note_skip("service excluded by request")
            continue

        if attachments_raw:
            raw_kind = "attachment"
        elif body:
            raw_kind = "text"
        else:
            raw_kind = "empty"
        if raw_kind != "text":
            result.note_kind(raw_kind)

        ordinal = seen.get((thread_id, ts, sender, body), 0)
        seen[(thread_id, ts, sender, body)] = ordinal + 1
        if ordinal:
            repeats += 1

        key = message_key(thread_id, ts, sender, body, ordinal)
        result.messages.append(Message(
            key=key, platform=PLATFORM, chat_id=thread_id,
            message_id=key.rsplit(":", 1)[1], ts_utc=ts,
            sender_name=sender, sender_id=None, body=body,
            reply_to=None, has_attachments=bool(attachments_raw),
            is_self=bool(owner) and sender == owner,
            raw_kind=raw_kind,
            forwarded_from=None,
            saved_from=subject or None,
        ))

        for attachment in _split_recipients(attachments_raw):
            result.attachments.append(AttachmentRef(
                platform=PLATFORM, chat_id=thread_id,
                message_id=key.rsplit(":", 1)[1], path=attachment,
                mime=None, size=None))

        if subject:
            subjects.add(subject)

        existing = chats.get(thread_id)
        if existing is None:
            title = _clean(row.get("CONVERSATION TITLE"))
            others = [p for p in recipients if p and p != owner]
            if not others and sender and sender != owner:
                others = [sender]
            people = tuple(sorted({p for p in (sender, *recipients) if p}))
            chats[thread_id] = Chat(
                platform=PLATFORM, chat_id=thread_id,
                title=title or _chat_title(sender, recipients, owner, thread_id),
                kind="group_chat" if len(others) > 1 else "personal_chat",
                is_group=len(others) > 1,
                participant_names=people,
            )
        else:
            merged = set(existing.participant_names) | {
                p for p in (sender, *recipients) if p}
            existing.participant_names = tuple(sorted(merged))
            if len(merged) - (1 if owner in merged else 0) > 1:
                existing.is_group = True
                existing.kind = "group_chat"

    result.chats.extend(chats.values())
    if repeats:
        result.note_kind("same-second repeats")
    if not owner:
        result.warnings.append(
            "owner unresolved: is_self=False for every row (pass self_id= or profile_dir=)")
    return result


def _chat_title(sender: str, recipients: list[str], owner: str | None, fallback: str) -> str:
    """The other person's name, skipping `LinkedIn Member` placeholders."""
    candidates = [p for p in (sender, *recipients)
                  if p and p != owner and p.strip().lower() != _UNKNOWN_SENDER]
    return candidates[0] if candidates else fallback


def _resolve_owner(
    rows: list[dict[str, str]],
    self_id: str | None,
    profile_dir: str | Path | None,
    result: IngestResult,
) -> str | None:
    """Same precedence as every adapter (§9.2): caller, persisted, then infer."""
    from .. import identity

    if self_id:
        if profile_dir:
            try:
                identity.save_owner(profile_dir, self_id, evidence="caller self_id")
            except ValueError:
                pass
        return self_id

    if profile_dir:
        stored = identity.load_owner(profile_dir)
        if stored:
            return stored

    # Breadth across conversations, never raw volume: one long thread must not be
    # able to elect its own author as the owner (the Messenger lesson).
    per_thread: dict[str, set[str]] = {}
    for row in rows:
        conversation = _clean(row.get("CONVERSATION ID"))
        sender = _clean(row.get("FROM"))
        if conversation and sender:
            per_thread.setdefault(conversation, set()).add(sender)

    breadth: dict[str, int] = {}
    for senders in per_thread.values():
        for name in senders:
            breadth[name] = breadth.get(name, 0) + 1

    if not breadth:
        return None
    winner, threads = max(breadth.items(), key=lambda kv: kv[1])
    note = (f"owner inferred as {winner!r} (present in {threads} conversations); "
            "pass self_id= or profile_dir= to pin it")
    result.warnings.append(note)
    if profile_dir:
        try:
            identity.save_owner(profile_dir, winner, evidence=note)
        except ValueError:
            pass
    return winner


def detect(path: Path) -> bool:
    """A zip or directory whose `messages.csv` has the LinkedIn column set."""
    try:
        if path.is_dir():
            candidates = list(path.rglob(MESSAGES_MEMBER))
            if not candidates:
                return False
            head = candidates[0].read_bytes()[:400]
        elif path.suffix.lower() == ".zip":
            with zipfile.ZipFile(path) as archive:
                names = [n for n in archive.namelist() if Path(n).name == MESSAGES_MEMBER]
                if not names:
                    return False
                with archive.open(names[0]) as handle:
                    head = handle.read(400)
        else:
            return False
    except (OSError, zipfile.BadZipFile):
        return False
    return b"CONVERSATION ID" in head and b"CONTENT" in head
