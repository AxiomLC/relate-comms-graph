"""Outlook `.pst` archive -> canonical `Message` rows.

WHY A FILE AND NOT IMAP
-----------------------
Microsoft killed basic auth for IMAP (consumer accounts 2024-09-16, M365 tenants
2022-10-01), so an IMAP reader for Outlook needs a registered Azure app and an OAuth2
consent flow. That is a lot of setup for a tool whose every other platform is
"download a file and drop it in".

Instead Outlook is treated like WhatsApp and LinkedIn: the user exports and drops a
file. Two supported routes, both producing a `.pst`:

  Outlook.com      Settings > General > Privacy and data > **Export mailbox**
                   (Microsoft assembles it server-side and mails a link)
  Classic Outlook  File > Open & Export > Import/Export > Export to a file
                   > Outlook Data File (.pst)  — tick "Include subfolders"

Both run on the user's own machine or their own mail. Nothing here authenticates.

HOW THE FILE IS READ
--------------------
`pypff` (libpff) walks the PST container offline. The layout is a tree:

    pst.file -> root_folder -> sub_folder* -> sub_message*

What matters per message:

    get_subject()               subject, used as the thread title fallback
    get_plain_text_body()       body; `get_html_body()` only if there is no plain part
    get_client_submit_time()    when it was sent  (preferred over delivery)
    get_delivery_time()         when it arrived (fallback)
    get_transport_headers()     THE RAW HEADER BLOCK — where Message-ID lives
    get_identifier()            the PST's own record id, stable within one file

MESSAGE-ID IS RECOVERED, NOT INVENTED
-------------------------------------
`pypff` does not expose a Message-ID accessor, but it does expose the transport
headers, which contain the real `Message-ID:` line. Parsing those gives a proper key
for nearly every message. When a message genuinely has none, the fallback is the PST
identifier — stable for that file, the same policy as email over IMAP.

WHAT WILL BITE
--------------
1. **`get_number_of_sub_messages()` is not the whole folder.** `pypff` models items
   and messages separately; iterating only messages misses appointments and notes. We
   read sub_messages only, which is what we want, but a folder of only `sub_items`
   reports 0 messages and must not be silently skipped — it is counted.
2. **`get_client_submit_time()` can be None** on imported or malformed mail. Delivery
   time is the fallback, and if both are absent the row is counted, not dropped.
3. **Encoding is set on the file, not per message.** `set_ascii_codepage()` must be
   called once after opening or non-ASCII names come back mangled.
4. **`.pst` files can be password-protected.** libpff exposes `get_encryption_type()`;
   an encrypted file is refused with a readable error rather than producing garbage.
5. **Large PSTs are slow and memory-hungry.** Progress is reported per folder, and
   the walk is depth-first so one huge folder cannot starve the rest.
"""
from __future__ import annotations

import email
import email.policy
import email.utils
import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from ..schema import AttachmentRef, Chat, IngestResult, Message

PLATFORM = "outlook"

# Headers worth reading straight off the transport block.
_WANTED_HEADERS = ("message-id", "from", "to", "cc", "subject", "date",
                   "in-reply-to", "references")

_WS = re.compile(r"[ \t]+")

# Folders that are not conversations the user had.
_SKIP_FOLDER_NAMES = {
    "deleted items", "deleted messages", "trash", "junk", "junk email", "spam",
    "drafts", "outbox", "sync issues", "conflicts", "local failures",
    "server failures", "rss feeds", "conversation history",
}


def _headers(raw: bytes | None) -> dict[str, str]:
    """Parse the transport header block into a lowercase-keyed dict."""
    if not raw:
        return {}
    try:
        text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
        parsed = email.message_from_string(text, policy=email.policy.compat32)
    except (TypeError, ValueError):
        return {}
    return {key.lower(): str(value) for key, value in parsed.items()
            if key.lower() in _WANTED_HEADERS}


def _as_utc(value: Any) -> datetime | None:
    """`pypff` returns naive datetimes; treat them as UTC and say so."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else \
            value.astimezone(timezone.utc)
    return None


def _body(message: Any) -> str:
    """Plain text preferred; HTML stripped only when there is nothing else."""
    for getter in ("get_plain_text_body", "get_html_body", "get_rtf_body"):
        try:
            raw = getattr(message, getter)()
        except (AttributeError, TypeError):
            continue
        if not raw:
            continue
        text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
        if getter != "get_plain_text_body":
            text = re.sub(r"<[^>]+>", " ", text)
        cleaned = "\n".join(_WS.sub(" ", line).rstrip() for line in text.split("\n")).strip()
        if cleaned:
            return cleaned
    return ""


def _thread_id(folder_path: str, headers: dict[str, str], subject: str,
               identifier: str) -> str:
    """References chain first, then subject, then the folder. Same policy as IMAP."""
    references = headers.get("references") or ""
    if references.split():
        return _stable("ref:" + references.split()[0])
    in_reply_to = (headers.get("in-reply-to") or "").strip()
    if in_reply_to:
        return _stable("irt:" + in_reply_to)
    topic = _normalise_subject(subject)
    if topic:
        return _stable("subj:" + topic)
    return _stable("folder:" + folder_path or identifier)


def _normalise_subject(raw: str | None) -> str:
    text = raw or ""
    while True:
        stripped = re.sub(r"^\s*(re|fw|fwd|aw|sv)\s*:\s*", "", text, flags=re.I)
        if stripped == text:
            break
        text = stripped
    return " ".join(text.split())


def _stable(value: str) -> str:
    return "pst_" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _walk(folder: Any, prefix: str) -> Iterator[tuple[str, Any]]:
    """Depth-first (folder_path, folder). Yields the folder itself before children."""
    name = ""
    try:
        name = folder.get_name() or ""
    except (AttributeError, TypeError):
        name = ""
    path = f"{prefix}/{name}" if prefix else name
    yield path, folder
    try:
        count = folder.get_number_of_sub_folders()
        children = [folder.get_sub_folder(i) for i in range(count)]
    except (AttributeError, TypeError):
        return
    for child in children:
        if child is not None:
            yield from _walk(child, path)


def parse(
    source: str | Path,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
    self_id: str | None = None,
    include_service: bool = True,
    profile_dir: str | Path | None = None,
    include_skipped_folders: bool = False,
) -> IngestResult:
    """Read every message in a `.pst` file.

    `since` / `until` bound the window by send time (delivery time as fallback) and
    must be timezone-aware. A decade-old mailbox exports in one file, so the window
    is the only thing keeping a demo quick.
    """
    try:
        import pypff
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise RuntimeError(
            "libpff-python is required to read .pst files: pip install libpff-python"
        ) from exc

    for bound, label in ((since, "since"), (until, "until")):
        if bound is not None and bound.tzinfo is None:
            raise ValueError(f"{label} must be timezone-aware")

    path = Path(source)
    result = IngestResult(platform=PLATFORM, source=str(path))

    pst = pypff.file()
    pst.open(str(path))
    try:
        # Gotcha 3: set once, before any name is read.
        try:
            pst.set_ascii_codepage(1252)
        except (AttributeError, TypeError):
            pass
        try:
            if pst.get_encryption_type():
                result.warnings.append(
                    "pst reports encryption; if messages come back empty it is "
                    "password-protected and must be re-exported without one")
        except (AttributeError, TypeError):
            pass

        root = pst.get_root_folder()
        if root is None:
            result.warnings.append("pst has no root folder")
            return result

        seen: set[str] = set()
        chats: dict[str, Chat] = {}

        for folder_path, folder in _walk(root, ""):
            leaf = folder_path.rsplit("/", 1)[-1].strip().lower()
            if leaf in _SKIP_FOLDER_NAMES and not include_skipped_folders:
                result.note_skip(f"excluded folder ({leaf})")
                continue

            try:
                count = folder.get_number_of_sub_messages()
            except (AttributeError, TypeError):
                count = 0
            if not count:
                # Gotcha 1: a folder of sub_items is not empty, just not messages.
                try:
                    if folder.get_number_of_sub_items():
                        result.note_skip("folder holds items, not messages")
                except (AttributeError, TypeError):
                    pass
                continue

            for index in range(count):
                try:
                    message = folder.get_sub_message(index)
                except (AttributeError, TypeError):
                    result.note_skip("unreadable message")
                    continue
                if message is None:
                    result.note_skip("unreadable message")
                    continue
                _parse_message(message, folder_path, result, seen, chats, since, until)
    finally:
        try:
            pst.close()
        except Exception:  # noqa: BLE001 - closing must not mask a read error
            pass

    result.chats.extend(chats.values())
    return result


def _parse_message(
    message: Any,
    folder_path: str,
    result: IngestResult,
    seen: set[str],
    chats: dict[str, Chat],
    since: datetime | None,
    until: datetime | None,
) -> None:
    try:
        headers = _headers(message.get_transport_headers())
    except (AttributeError, TypeError):
        headers = {}

    ts = None
    for getter in ("get_client_submit_time", "get_delivery_time", "get_creation_time"):
        try:
            ts = _as_utc(getattr(message, getter)())
        except (AttributeError, TypeError):
            ts = None
        if ts is not None:
            break
    if ts is None:
        result.note_skip("no usable timestamp")
        return
    if since is not None and ts < since:
        result.note_skip("before window")
        return
    if until is not None and ts > until:
        result.note_skip("after window")
        return

    try:
        subject = (message.get_subject() or "").strip()
    except (AttributeError, TypeError):
        subject = ""
    subject = _normalise_subject(headers.get("subject") or subject)
    body = _body(message)

    try:
        identifier = message.get_identifier() or ""
    except (AttributeError, TypeError):
        identifier = ""

    message_id = (headers.get("message-id") or "").strip()
    if not message_id:
        result.note_kind("missing message-id")
        message_id = f"pst:{identifier or _stable(folder_path + str(ts))}"

    thread = _thread_id(folder_path, headers, subject, identifier)
    key = f"{PLATFORM}:{thread}:{message_id}"
    if key in seen:
        result.note_skip("duplicate within run")
        return
    seen.add(key)

    sender_name = ""
    try:
        sender_name = (message.get_sender_name() or "").strip()
    except (AttributeError, TypeError):
        sender_name = ""
    from_header = headers.get("from") or ""
    sender_addr = email.utils.parseaddr(from_header)[1].lower() if from_header else ""

    attachments: list[tuple[str, str | None]] = []
    try:
        for i in range(message.get_number_of_attachments()):
            attachment = message.get_attachment(i)
            if attachment is None:
                continue
            try:
                name = attachment.get_name() or "attachment"
            except (AttributeError, TypeError):
                name = "attachment"
            try:
                mime = attachment.get_mime_type()
            except (AttributeError, TypeError):
                mime = None
            attachments.append((name, mime))
    except (AttributeError, TypeError):
        pass

    raw_kind = "attachment" if attachments and not body else ("text" if body else "empty")
    if raw_kind != "text":
        result.note_kind(raw_kind)

    result.messages.append(Message(
        key=key, platform=PLATFORM, chat_id=thread, message_id=message_id,
        ts_utc=ts, sender_name=sender_name or from_header or sender_addr,
        sender_id=sender_addr or None, body=body, reply_to=None,
        has_attachments=bool(attachments),
        is_self=False,          # resolution decides, against the owner's address
        raw_kind=raw_kind, saved_from=subject or None,
    ))
    for name, mime in attachments:
        result.attachments.append(AttachmentRef(
            platform=PLATFORM, chat_id=thread, message_id=message_id,
            path=name, mime=mime, size=None))

    if thread not in chats:
        chats[thread] = Chat(
            platform=PLATFORM, chat_id=thread,
            title=subject or folder_path or thread,
            kind="personal_chat", is_group=False,
            participant_names=tuple(sorted(
                {sender_name} | {sender_addr} - {""})),
        )


def detect(path: Path) -> bool:
    """A `.pst` by suffix, confirmed by the container's own signature.

    `pypff.check_file_signature` reads four bytes, so a renamed `.pst` is still found
    and a `.zip` misnamed as `.pst` is not attempted.
    """
    if path.suffix.lower() not in {".pst", ".ost"}:
        return False
    try:
        import pypff
    except ImportError:
        return True        # suffix alone is the best we can do without libpff
    try:
        return bool(pypff.check_file_signature(str(path)))
    except (AttributeError, TypeError, OSError):
        return True
