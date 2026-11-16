"""Messenger (Facebook) HTML export -> canonical `Message` rows.

Validated against a real export from this machine (2026-11-14, Meta "Download your
information" → Messages → HTML).

SHAPE OF THE ARCHIVE
--------------------
    your_facebook_activity/messages/
        inbox/<thread>/message_1.html
        filtered_threads/<thread>/message_1.html
        message_requests/<thread>/message_1.html
        e2ee_cutover/<thread>/message_1.html
        photos/...            (shared media)

Every thread is HTML. Each message is a `<section class="_a6-g">` whose `<h2>` IS the
sender and whose `<footer>` holds the timestamp:

    <section class="_a6-g">
      <h2>David Sartori</h2>                      <- the sender, by name
      <div class="_2ph_ _a6-p">...body...</div>
      <footer><div class="_a72d">Jan 06, 2026 8:09:48 pm</div></footer>
    </section>

WHAT THE REAL FILE TAUGHT US:

1. **Sender is stated, unlike Instagram.** The same `<h2>` tag means different things
   in the two exports: here it is the sender, in Instagram it is the thread title.
   Do not share parsing code between them.
2. **Metadata sections have an `<h2>` and NO `<footer>`.** `Participants: A, B, C`
   and `Group Invite Link: Off` appear as sections in every group thread. The
   `<footer>` is the only reliable divider between a message and metadata.
3. **The owner is named, not "You".** The export says `David Sartori` in full. We
   still resolve it through `identity.py` so Messenger and Telegram agree on who "me"
   is, rather than hardcoding a display name into every row.
4. **Order is newest-first.** Rows must be reversed at the end, or the thread looks
   like it ran backwards.
5. **Media are real relative paths** (`.../photos/25442071255477526.jpg`), unlike
   WhatsApp's placeholders. They are kept as `AttachmentRef.path`, never stat'd — a
   text-only or partial archive has no such folders.
6. **`You missed a call from Kenny.`** is a call event with the *other* person in the
   `<h2>`. It is kinded `call:missed`, not treated as a text row the sender wrote.
7. **Timestamps are local, no offset.** Same policy as WhatsApp: `tz_offset_hours`
   is declared by the caller, default 0 is flagged in `warnings`.

NO MESSAGE IDS
--------------
Like WhatsApp, the HTML exposes no stable message id. The key is a content
fingerprint plus the ordinal within the same (thread, second, sender, body), so a
photo album of identical rows does not collapse.
"""
from __future__ import annotations

import hashlib
import html
import re
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Iterator

from ..schema import AttachmentRef, Chat, IngestResult, Message

PLATFORM = "messenger"

# Folders inside `your_facebook_activity/messages/` that hold threads. `e2ee_cutover`
# holds legacy encrypted threads; they are still messages and are included.
THREAD_DIRS = ("inbox", "filtered_threads", "message_requests", "e2ee_cutover")

_SECTION = re.compile(r"<section\b[^>]*>(?P<body>.*?)</section>", re.S)
_H2 = re.compile(r"<h2\b[^>]*>(?P<text>.*?)</h2>", re.S)
_FOOTER = re.compile(r"<footer\b[^>]*>(?P<body>.*?)</footer>", re.S)
_IMG_SRC = re.compile(r'<img\b[^>]*\bsrc="(?P<src>[^"]+)"', re.S)
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"[ \t\r\f\v]+")

# `Jan 06, 2026 8:09:48 pm`
_TS = re.compile(
    r"(?P<mon>[A-Z][a-z]{2})\s+(?P<day>\d{1,2}),\s+(?P<year>\d{4})\s+"
    r"(?P<hour>\d{1,2}):(?P<minute>\d{2})(?::(?P<second>\d{2}))?\s*(?P<ampm>[AaPp][Mm])?"
)
_MONTHS = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}

# Sections that carry an `<h2>` but are thread metadata, not messages.
_METADATA_PREFIXES = ("participants:", "group invite link:", "you are", "nickname")

_CALL = re.compile(r"^(?:You (?:missed|placed|answered) a (?:video )?call|"
                   r".{1,80}? (?:called you|missed your call))", re.I)

# Rows that are group *housekeeping*, not conversation. A spam group is almost
# entirely these: someone adds strangers, the strangers post a link, someone leaves.
# Measured on the real archive: the six largest group threads are 60-70% "sent a
# link" and 30-45% "added ... to the group".
_GROUP_NOISE = (
    re.compile(r"\bsent a link\b", re.I),
    re.compile(r"\badded .{0,80} to the group\b", re.I),
    re.compile(r"\bleft the group\b", re.I),
    re.compile(r"\bjoined the group\b", re.I),
    re.compile(r"\bchanged the group (?:name|photo)\b", re.I),
    re.compile(r"\bnamed the group\b", re.I),
    re.compile(r"\bcreated a poll\b", re.I),
)

# A group thread is spam when at least this share of its rows is housekeeping.
# 0.5 separates the six spam giants (0.60-0.70) from real group chats, which sit
# far below it — a real conversation has actual sentences in it.
SPAM_NOISE_RATIO = 0.5


def is_noise_row(body: str) -> bool:
    """True when a row is group housekeeping rather than something a person said."""
    return any(pattern.search(body or "") for pattern in _GROUP_NOISE)


def _text(fragment: str) -> str:
    """HTML -> text. Block-level `<div>`s become newlines; tags are stripped."""
    with_breaks = re.sub(r"</div>\s*<div[^>]*>", "\n", fragment)
    with_breaks = re.sub(r"<br\s*/?>", "\n", with_breaks)
    stripped = html.unescape(_TAG.sub("", with_breaks))
    lines = [_WS.sub(" ", line).strip() for line in stripped.split("\n")]
    return "\n".join(line for line in lines if line)


def _parse_ts(footer: str, tz_offset_hours: float) -> datetime | None:
    """`Jan 06, 2026 8:09:48 pm` -> aware UTC, anchored by the declared offset."""
    match = _TS.search(_text(footer))
    if not match:
        return None
    month = _MONTHS.get(match.group("mon"))
    if month is None:
        return None

    hour = int(match.group("hour"))
    ampm = (match.group("ampm") or "").lower()
    if ampm == "pm" and hour != 12:
        hour += 12
    elif ampm == "am" and hour == 12:
        hour = 0

    try:
        naive = datetime(int(match.group("year")), month, int(match.group("day")),
                         hour, int(match.group("minute")),
                         int(match.group("second") or 0))
    except ValueError:
        return None
    return (naive - timedelta(hours=tz_offset_hours)).replace(tzinfo=timezone.utc)


def thread_key_from_path(member: str) -> str:
    """`.../inbox/kennysettens_1016.../message_1.html` -> a stable thread id.

    The folder name is `username_numericid`. The numeric id is stable for the life
    of the account; the username is not (people rename). Split on the last `_`.
    """
    folder = member.rsplit("/", 2)[-2]
    return folder.rsplit("_", 1)[-1] if "_" in folder else hashlib.sha256(
        folder.encode("utf-8")).hexdigest()[:16]


def message_key(thread_id: str, ts: datetime, sender: str, body: str, ordinal: int = 0) -> str:
    material = "\x1f".join((
        thread_id, ts.strftime("%Y-%m-%dT%H:%M:%SZ"), sender, body, str(ordinal),
    ))
    return f"{PLATFORM}:{thread_id}:{hashlib.sha256(material.encode('utf-8')).hexdigest()[:24]}"


def _iter_sections(document: str) -> Iterator[str]:
    for match in _SECTION.finditer(document):
        yield match.group("body")


def _section_parts(section: str) -> tuple[str | None, str, str | None]:
    """(sender, body-html, footer-html). Footer is None for metadata sections."""
    heading = _H2.search(section)
    footer = _FOOTER.search(section)

    sender = _text(heading.group("text")) if heading else None

    start = heading.end() if heading else 0
    end = footer.start() if footer else len(section)
    # A footer always follows its own body, so `end` is never before `start` in a
    # real export; clamp anyway rather than produce a negative slice.
    body_html = section[start:end] if end > start else ""
    return sender, body_html, (footer.group("body") if footer else None)


def parse(
    export_path: str | Path,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
    self_id: str | None = None,
    include_service: bool = True,
    profile_dir: str | Path | None = None,
    tz_offset_hours: float = 0,
    include_filtered: bool = True,
    exclude_spam_groups: bool = False,
) -> IngestResult:
    """Parse a Messenger archive directory or `.zip` into Messages.

    `include_filtered=False` drops `message_requests/` and `filtered_threads/`, which
    are usually spam. They are included by default: the store is whole, and a
    hidden toggle must not narrow an agent's view (§5.2).

    `exclude_spam_groups=True` drops group threads whose rows are mostly
    housekeeping (`sent a link`, `added X to the group`, `left the group`) — see
    `is_noise_row` and `SPAM_NOISE_RATIO`. Off by default for the same reason: the
    store is whole unless the user asks otherwise. A dropped thread is counted in
    `skipped`, never silently lost.

    `self_id` is the owner's **display name** for Messenger (the export names senders,
    it does not give ids). `profile_dir` keeps it stable across platforms.
    """
    for bound, label in ((since, "since"), (until, "until")):
        if bound is not None and bound.tzinfo is None:
            raise ValueError(f"{label} must be timezone-aware")

    path = Path(export_path)
    result = IngestResult(platform=PLATFORM, export_path=str(path))
    if tz_offset_hours == 0:
        result.warnings.append(
            "timestamps read as UTC: the export states no offset (pass tz_offset_hours=)")

    members = _thread_members(path, include_filtered)
    if not members:
        result.warnings.append("no messenger message_*.html found")
        return result

    owner = _resolve_owner(path, members, self_id, profile_dir, result)

    seen: dict[tuple[str, datetime, str, str], int] = {}
    chats: dict[str, Chat] = {}
    repeats = 0

    for member in members:
        thread_id = thread_key_from_path(member)
        document = _read_member(path, member)

        rows: list[Message] = []
        senders: set[str] = set()
        title = ""

        for section in _iter_sections(document):
            sender, body_html, footer = _section_parts(section)
            if footer is None:
                # Metadata section: `Participants: ...`, `Group Invite Link: Off`.
                if not title and sender:
                    title = sender
                result.note_skip("metadata section")
                continue

            ts = _parse_ts(footer, tz_offset_hours)
            if ts is None:
                result.note_skip("unparseable date")
                continue
            if since is not None and ts < since:
                result.note_skip("before window")
                continue
            if until is not None and ts > until:
                result.note_skip("after window")
                continue

            body = _text(body_html)
            images = _IMG_SRC.findall(body_html)
            sender_text = sender or ""
            if sender_text:
                senders.add(sender_text)

            is_call = bool(_CALL.match(body)) and not images
            if is_call:
                kind = "call"
            elif images:
                kind = "attachment"
            elif body:
                kind = "text"
            else:
                kind = "empty"

            if kind != "text":
                result.note_kind(kind)

            if not include_service and is_call:
                result.note_skip("service excluded by request")
                continue

            ordinal = seen.get((thread_id, ts, sender_text, body), 0)
            seen[(thread_id, ts, sender_text, body)] = ordinal + 1
            if ordinal:
                repeats += 1

            key = message_key(thread_id, ts, sender_text, body, ordinal)
            rows.append(Message(
                key=key, platform=PLATFORM, chat_id=thread_id,
                message_id=key.rsplit(":", 1)[1], ts_utc=ts,
                sender_name=sender_text,
                sender_id=None,
                body=body,
                reply_to=None,
                has_attachments=bool(images),
                is_self=bool(owner) and sender_text == owner,
                raw_kind=kind,
            ))

            for src in images:
                result.attachments.append(AttachmentRef(
                    platform=PLATFORM, chat_id=thread_id,
                    message_id=key.rsplit(":", 1)[1], path=src,
                    mime=None, size=None))

        if not rows:
            result.note_skip("empty thread")
            continue

        others = sorted(s for s in senders if s != owner and not s.lower().startswith("participants:"))
        is_group = len(others) > 1

        # Spam-group gate. Decided BEFORE the rows are committed, so a dropped
        # thread leaves no orphan messages behind — the same ordering that fixed
        # Telegram's service-only chats.
        if exclude_spam_groups and is_group:
            noise = sum(1 for row in rows if is_noise_row(row.body))
            if noise / len(rows) >= SPAM_NOISE_RATIO:
                result.note_skip("spam group thread")
                continue

        # The export writes newest-first; a thread must read forward in time.
        rows.reverse()
        result.messages.extend(rows)

        display = next((s for s in others if s), title or thread_id)
        chats[thread_id] = Chat(
            platform=PLATFORM, chat_id=thread_id, title=display,
            kind="group_chat" if is_group else "personal_chat",
            is_group=is_group,
            participant_names=tuple(sorted(senders)),
        )

    result.chats.extend(chats.values())
    if repeats:
        result.note_kind("same-second repeats")
    if not owner:
        result.warnings.append(
            "owner unresolved: is_self=False for every row (pass self_id= or profile_dir=)")
    return result


def _resolve_owner(
    path: Path,
    members: list[str],
    self_id: str | None,
    profile_dir: str | Path | None,
    result: IngestResult,
) -> str | None:
    """Who is 'me'? Same precedence as every other adapter (§9.2)."""
    from .. import identity

    if self_id:
        if profile_dir:
            try:
                identity.save_owner(profile_dir, self_id, evidence="caller self_id",
                                    platform=PLATFORM)
            except ValueError:
                pass
        return self_id

    if profile_dir:
        stored = identity.load_owner(profile_dir, PLATFORM)
        if stored:
            return stored

    # Breadth, not volume — the rule identity.py already states. A spam thread can
    # contain thousands of rows from one automated account (`Facebook user`, 8171
    # messages in this archive), so counting messages would elect the spammer as the
    # owner. The real owner is whoever appears in the most *distinct* threads.
    breadth: dict[str, int] = {}
    for member in members:
        here: set[str] = set()
        for section in _iter_sections(_read_member(path, member)):
            sender, _, footer = _section_parts(section)
            if footer is None or not sender:
                continue
            if sender.lower() in {"facebook user", "facebook"}:
                continue
            here.add(sender)
        for name in here:
            breadth[name] = breadth.get(name, 0) + 1

    if not breadth:
        return None
    winner, threads = max(breadth.items(), key=lambda kv: kv[1])
    note = (f"owner inferred as {winner!r} (present in {threads} threads); "
            "pass self_id= or profile_dir= to pin it")
    result.warnings.append(note)
    if profile_dir:
        try:
            identity.save_owner(profile_dir, winner, evidence=note, platform=PLATFORM)
        except ValueError:
            pass
    return winner


def _thread_members(path: Path, include_filtered: bool) -> list[str]:
    """Archive-relative `message_*.html` paths, sorted."""
    wanted = set(THREAD_DIRS if include_filtered else ("inbox", "e2ee_cutover"))
    found: list[str] = []

    if path.is_dir():
        for entry in sorted(path.rglob("message_*.html")):
            parts = entry.relative_to(path).parts
            rel = "/".join(parts)
            if any(f"/{w}/" in f"/{rel}" for w in wanted):
                found.append(rel)
    else:
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                if not re.search(r"message_\d+\.html$", name):
                    continue
                if any(f"/{w}/" in name for w in wanted):
                    found.append(name)
    return sorted(found)


def _read_member(path: Path, member: str) -> str:
    if path.is_dir():
        return (path / member).read_text(encoding="utf-8", errors="replace")
    with zipfile.ZipFile(path) as archive:
        return archive.read(member).decode("utf-8", errors="replace")


def detect(path: Path) -> bool:
    """Cheap shape check used by `ingest.detect_platform`."""
    try:
        if path.suffix.lower() == ".zip":
            with zipfile.ZipFile(path) as archive:
                names = archive.namelist()
                return any("facebook_activity" in n and re.search(r"message_\d+\.html$", n)
                           for n in names[:4000])
        return False
    except (OSError, zipfile.BadZipFile):
        return False
