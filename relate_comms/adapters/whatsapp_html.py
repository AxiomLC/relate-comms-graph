"""WhatsApp HTML export -> canonical `Message` rows.

WHICH FORMAT THIS IS
--------------------
Not WhatsApp's own exporter. A browser extension (WASendly and similar) bulk-downloads
chats as standalone HTML pages, which is the only way to get *many* chats at once — the
native route is one chat at a time.

    whatsapp-chats-20261117.zip
        chats/Thad_Zurawski_Chicago.html
        chats/Michael_Metzler.html
        groups/AOAF_B-DAY_GAME_CHAT___.html
        index.html

**This is a second dialect of the same conversation, not a second platform.** The
`chat_id` is derived from the chat *title*, exactly as `whatsapp.py` does, so a chat
downloaded both ways lands in the same Thread. `message_key()` is shared for the same
reason — see its docstring on why the timestamp is truncated to the minute.

WHAT THE HTML KNOWS THAT `chat.txt` DOES NOT
--------------------------------------------
1. **Group-ness is stated.** `<small>Group · 307 messages</small>` vs `Chat · 11
   messages`. `chat.txt` has to infer it from membership system rows, which fails for a
   group with one sender and no system rows.
2. **Owner-ness is structural.** `class="row out"` is the Owner; there is no sender div
   on those rows. `chat.txt` writes a literal `You:` prefix.
3. **Placeholders are readable.** `🎤 Voice / Audio message`, `🎥 Video`,
   `👤 Contact card`, `🚫 This message was deleted`. `chat.txt` writes
   `<voice message omitted>` and leaks a raw `BEGIN:VCARD…` for a contact.

WHAT IT LOSES
-------------
**Seconds.** The row carries only `<div class="time">23:09</div>`; the date comes from
the preceding `<div class="daysep">16 Nov 2026</div>`. So every timestamp is
minute-resolution. That is why `message_key()` truncates to the minute — otherwise the
same chat in both formats would produce two key sets.

TRAPS
-----
1. **`<div class="daysep">` is positional.** A row's date is the most recent separator
   *before* it. Walking the document in order is the only correct way to read it.
2. **A row ends where the next begins.** Media rows nest deeper than text rows, so
   matching a fixed number of closing `</div>`s silently truncates them.
3. **`<div class="cap">` is the caption on a media row**, not a separate message.
4. **Base64 in `href`/`src` is never decoded.** The 307-row group is 336 KB of mostly
   base64; decoding it would cost gigabytes for data the app does not store.
5. **`<div class="ph">` is a placeholder**, not text a person wrote. It is kinded, not
   treated as a body.
6. **`index.html` is the table of contents**, not a chat.
"""
from __future__ import annotations

import hashlib
import html as html_module
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from ..schema import AttachmentRef, Chat, IngestResult, Message
from .whatsapp import PLATFORM, SELF_NAME, _chat_id, _clean_name, message_key

# --- selectors ---------------------------------------------------------------------
_HEADER = re.compile(
    r'<div class="hd">(?P<title>.*?)<small>(?P<meta>.*?)</small>', re.S)
_DAYSEP = re.compile(r'<div class="daysep"><span>(?P<day>[^<]+)</span></div>')
# A row ends where the next row, the next day separator, or the footer begins.
_ROW = re.compile(
    r'<div class="row (?P<dir>in|out)">(?P<body>.*?)'
    r'(?=<div class="row |<div class="daysep"|<div class="ftr")',
    re.S,
)
_SENDER = re.compile(r'<div class="sender">(?P<name>.*?)</div>', re.S)
_TXT = re.compile(r'<div class="txt">(?P<body>.*?)</div>(?=<div class="time">)', re.S)
_TIME = re.compile(r'<div class="time">(?P<time>[^<]+)</div>')
_PH = re.compile(r'<div class="ph[^"]*">(?P<text>.*?)</div>', re.S)
_CAP = re.compile(r'<div class="cap">(?P<text>.*?)</div>', re.S)
_IMG = re.compile(r'<img class="media"')
_TAG = re.compile(r"<[^>]+>")
_BR = re.compile(r"<br\s*/?>")

_MONTHS = {name: index for index, name in enumerate(
    ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), start=1)}

# Placeholder text -> (`raw_kind`, canonical body).
#
# The two dialects write the same event differently: the HTML says
# `🎤 Voice / Audio message`, `chat.txt` says `<voice message omitted>`. Both are
# placeholders, not something a person typed, so the **body is normalised to the
# `chat.txt` wording** — that is what makes the message key identical and lets a chat
# downloaded both ways collapse instead of storing every media row twice.
#
# A contact card is the one case where the two cannot agree: `chat.txt` embeds the raw
# vCard, which is personal data the app should not carry. The HTML's `👤 Contact card`
# is kept, so that row stays a duplicate if both formats are ingested. That is the
# correct trade — a vCard in a message body is worse than one duplicated row.
_PLACEHOLDER_KINDS = (
    ("voice", "voice_message", "<voice message omitted>"),
    ("audio", "audio", "<audio omitted>"),
    ("video", "video", "<video omitted>"),
    ("photo", "image", "<image omitted>"),
    ("image", "image", "<image omitted>"),
    ("sticker", "sticker", "<sticker omitted>"),
    ("gif", "gif", "<gif omitted>"),
    ("document", "document", "<document omitted>"),
    ("location", "location", "<location omitted>"),
    ("deleted", "deleted", "You deleted this message"),
    ("pinned", "pinned_message", "[pinned_message]"),
    ("album", "album", "<album message>"),
    ("poll", "poll", "<poll omitted>"),
    ("product", "product", "<product omitted>"),
    ("contact", "contact", "👤 Contact card"),
)


def _text(fragment: str) -> str:
    """HTML -> text. `<br>` becomes a newline; tags stripped; entities decoded."""
    with_breaks = _BR.sub("\n", fragment)
    stripped = html_module.unescape(_TAG.sub("", with_breaks))
    return "\n".join(line.strip() for line in stripped.split("\n") if line.strip())


def _day(text: str) -> datetime | None:
    """`26 Sep 2026` -> midnight UTC on that day."""
    parts = text.strip().split()
    if len(parts) != 3:
        return None
    try:
        day, year = int(parts[0]), int(parts[2])
    except ValueError:
        return None
    month = _MONTHS.get(parts[1])
    if month is None:
        return None
    try:
        return datetime(year, month, day, tzinfo=timezone.utc)
    except ValueError:
        return None


def _stamp(day: datetime | None, clock: str) -> datetime | None:
    """Combine the day separator with the row's `HH:MM`."""
    if day is None:
        return None
    try:
        hour, minute = (int(part) for part in clock.strip().split(":")[:2])
    except (ValueError, TypeError):
        return None
    if not (0 <= hour < 24 and 0 <= minute < 60):
        return None
    return day.replace(hour=hour, minute=minute)


def _placeholder(text: str) -> tuple[str, str]:
    """(raw_kind, canonical body) for a placeholder label.

    The body is normalised to the `chat.txt` wording so the message key matches — see
    `_PLACEHOLDER_KINDS`.
    """
    lowered = text.lower()
    for marker, kind, canonical in _PLACEHOLDER_KINDS:
        if marker in lowered:
            return kind, canonical
    return "placeholder", text


def detect(path: Path) -> bool:
    """A zip holding WhatsApp chat pages, by content. Never by filename.

    The marker is a chat page: a `chats/` or `groups/` folder holding `.html`, plus the
    `class="row in"` / `class="row out"` structure the parser reads. A zip of arbitrary
    HTML does not qualify.
    """
    try:
        if path.suffix.lower() == ".zip":
            with zipfile.ZipFile(path) as archive:
                names = archive.namelist()
                pages = [n for n in names
                         if n.lower().endswith(".html")
                         and Path(n).name != "index.html"
                         and ("chats/" in n or "groups/" in n)]
                if not pages:
                    return False
                head = archive.read(pages[0])[:8192].decode("utf-8", errors="replace")
        elif path.suffix.lower() == ".html":
            head = path.read_text(encoding="utf-8", errors="replace")[:8192]
        else:
            return False
    except (OSError, zipfile.BadZipFile):
        return False

    return 'class="row in"' in head or 'class="row out"' in head


def _pages(path: Path) -> list[tuple[str, str]]:
    """(member name, document text) for every chat page, in archive order."""
    if path.is_dir():
        return [(str(entry.relative_to(path)),
                 entry.read_text(encoding="utf-8", errors="replace"))
                for entry in sorted(path.rglob("*.html"))
                if entry.name != "index.html"]

    if path.suffix.lower() == ".html":
        return [(path.name, path.read_text(encoding="utf-8", errors="replace"))]

    with zipfile.ZipFile(path) as archive:
        return [(name, archive.read(name).decode("utf-8", errors="replace"))
                for name in archive.namelist()
                if name.lower().endswith(".html") and Path(name).name != "index.html"]


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
    """Parse a WhatsApp HTML export (zip, folder, or one page) into Messages.

    `tz_offset_hours` is accepted for signature parity with `whatsapp.parse` but is
    **ignored**: the HTML export states no offset either, and the day separator plus a
    bare `HH:MM` gives no way to place it. Times are read as UTC, and the warning says
    so — the same policy the `.txt` adapter applies at offset 0.

    `exclude_silent_groups` drops group chats the Owner never sent a message in. The
    HTML states group-ness in the header, so this gate is more reliable here than in
    the `.txt` adapter, which has to infer it.
    """
    for bound, label in ((since, "since"), (until, "until")):
        if bound is not None and bound.tzinfo is None:
            raise ValueError(f"{label} must be timezone-aware")

    path = Path(export_path)
    result = IngestResult(platform=PLATFORM, export_path=str(path))

    pages = _pages(path)
    if not pages:
        result.warnings.append("no chat pages found; is this a WhatsApp HTML export?")
        return result

    if tz_offset_hours == 0:
        result.warnings.append(
            "timestamps read as UTC: the HTML export states no offset")

    for member, document in pages:
        _parse_page(member, document, result, since, until,
                    include_service, exclude_silent_groups)

    return result


def _parse_page(
    member: str,
    document: str,
    result: IngestResult,
    since: datetime | None,
    until: datetime | None,
    include_service: bool,
    exclude_silent_groups: bool,
) -> None:
    header = _HEADER.search(document)
    if header is None:
        result.note_skip("page with no chat header")
        return

    title = _text(header.group("title"))
    meta = _text(header.group("meta"))
    is_group = meta.lower().startswith("group")
    chat_id = _chat_id(title)

    rows: list[Message] = []
    senders: set[str] = set()
    seen: dict[tuple[datetime, str, str], int] = {}
    collisions = 0
    day: datetime | None = None

    # One ordered walk: a row's date is the most recent separator before it.
    events = sorted(
        [(m.start(), "day", m) for m in _DAYSEP.finditer(document)]
        + [(m.start(), "row", m) for m in _ROW.finditer(document)],
        key=lambda item: item[0],
    )

    for _, kind, match in events:
        if kind == "day":
            day = _day(match.group("day"))
            continue

        body = match.group("body")
        is_self = match.group("dir") == "out"

        sender_match = _SENDER.search(body)
        # **Owner rows carry no sender div; `in` rows in a 1:1 carry none either.** The
        # row class is the only signal, so it decides. Using `SELF_NAME` as a blanket
        # fallback named every correspondent "You" in a 1:1 — which then matched the
        # Owner's own key and would have merged two different people's messages.
        #
        # In a group, `in` rows DO carry a sender div, so the name is read from there.
        # The literal `SELF_NAME` is used for owner rows so the key matches what
        # `chat.txt` produces for the same message.
        if sender_match:
            sender = _clean_name(_text(sender_match.group("name")))
            senders.add(sender)
        elif is_self:
            sender = SELF_NAME
        else:
            # A 1:1 correspondent with no sender div: the chat title names them.
            sender = _clean_name(title)

        time_match = _TIME.search(body)
        ts = _stamp(day, time_match.group("time") if time_match else "")
        if ts is None:
            result.note_skip("no usable timestamp")
            continue

        if since is not None and ts < since:
            result.note_skip("before window")
            continue
        if until is not None and ts > until:
            result.note_skip("after window")
            continue

        ph_match = _PH.search(body)
        cap_match = _CAP.search(body)
        txt_match = _TXT.search(body)
        has_media = bool(_IMG.search(body))

        if ph_match:
            raw_kind, text = _placeholder(_text(ph_match.group("text")))
        elif cap_match:
            # A caption belongs to the media above it, not to a separate message.
            raw_kind = "text"
            text = _text(cap_match.group("text"))
        elif txt_match:
            raw_kind = "text"
            text = _text(txt_match.group("body"))
        else:
            raw_kind = "empty"
            text = ""

        if raw_kind != "text":
            result.note_kind(raw_kind)

        if has_media:
            result.attachments.append(AttachmentRef(
                platform=PLATFORM, chat_id=chat_id,
                message_id="", path=f"{member}#media", mime=None, size=None))

        slot = ts.replace(second=0, microsecond=0)
        ordinal = seen.get((slot, sender, text), 0)
        seen[(slot, sender, text)] = ordinal + 1
        if ordinal:
            collisions += 1

        key = message_key(chat_id, ts, sender, text, ordinal)
        rows.append(Message(
            key=key, platform=PLATFORM, chat_id=chat_id,
            message_id=key.rsplit(":", 1)[1], ts_utc=ts,
            sender_name=sender, sender_id=None, body=text,
            reply_to=None, has_attachments=has_media,
            is_self=is_self, raw_kind=raw_kind,
        ))

    if not rows:
        result.note_skip("chat with no usable messages")
        return

    # Silent-group gate, before the Chat is appended so a drop leaves no orphan rows.
    if exclude_silent_groups and is_group and not any(m.is_self for m in rows):
        result.note_skip("group thread the owner never spoke in")
        return

    result.messages.extend(rows)
    result.chats.append(Chat(
        platform=PLATFORM, chat_id=chat_id, title=title,
        kind="group_chat" if is_group else "personal_chat",
        is_group=is_group,
        participant_names=tuple(sorted(senders)),
    ))

    if collisions:
        result.note_kind("same-minute repeats")
        result.warnings.append(
            f"{title}: {collisions} message(s) share a minute with an identical body; "
            "each kept as its own row via its position")
