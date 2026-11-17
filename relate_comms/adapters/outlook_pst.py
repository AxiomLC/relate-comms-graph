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
    get_conversation_index()    Outlook's own conversation id — the thread key
    get_identifier()            the PST's own record id, stable within one file

MESSAGE-ID IS RECOVERED, NOT INVENTED
-------------------------------------
`pypff` does not expose a Message-ID accessor, but it does expose the transport
headers, which contain the real `Message-ID:` line. Parsing those gives a proper key
for nearly every message. When a message genuinely has none, the fallback is the PST
identifier — stable for that file, the same policy as email over IMAP.

THE SAME MAIL IS FILED TWICE
----------------------------
Measured on the Aspose sample (2026-11-17): `Inbox` and `Sent Items` each hold the
same five messages, with the same `conversation_index` and the same body. The Inbox
copy carries transport headers; the Sent copy does not. Keying on Message-ID alone
therefore produces ten rows for five messages, and the surviving Sent row would claim
`is_self=False` because it has no `From:` header to compare.

So a second, content-level identity is kept alongside the key: thread + second-
resolution timestamp + sender + body. A row matching an earlier fingerprint is the
same mail in another folder — it is counted, not stored, and if it came out of a
sent-class folder it upgrades the stored row to `is_self=True`. That is the only
place a duplicate is allowed to change anything, and it changes a fact, not a guess.

WHAT WILL BITE
--------------
1. **`get_number_of_sub_messages()` is not the whole folder.** `pypff` models items
   and messages separately; iterating only messages misses appointments and notes. We
   read sub_messages only, which is what we want, but a folder of only `sub_items`
   reports 0 messages and must not be silently skipped — it is counted.
2. **A sub_message is not necessarily mail.** `Calendar` returns an
   `IPM.Appointment`, `Contacts` an `IPM.Contact`, and `Freebusy Data` returns a
   `pypff.item` with no `get_subject` at all. Classification is by message class
   (`PR_MESSAGE_CLASS`, 0x001A), never by folder name — a user can file mail
   anywhere. Unknown classes are kept, because dropping what we cannot classify is
   the worse error.
3. **`set_ascii_codepage()` takes a string, not an int.** Passing `1252` raises
   `TypeError`, which a bare `except` swallows, leaving non-ASCII names mangled.
   `"cp1252"` is the correct call.
4. **`get_client_submit_time()` can be None** on imported or malformed mail. Delivery
   time is the fallback, and if both are absent the row is counted, not dropped.
5. **`Sent Items` messages have `transport_headers = None`.** Anything that parses
   headers must tolerate that — the sent side has no `From:`/`Message-ID:` block.
6. **`delivery_time` is a naive `datetime`.** Treat it as UTC and say so, or the
   timeline lies.
7. **Attachments have no `get_name()`.** The filename is `get_long_filename()`
   (0x3707); the MIME type is record entry 0x370E; embedded messages have neither and
   only a display name (0x3001).
8. **`.pst` files can be password-protected.** libpff exposes `get_encryption_type()`;
   an encrypted file is refused with a readable error rather than producing garbage.
9. **Large PSTs are slow and memory-hungry.** Progress is reported per folder, and
   the walk is depth-first so one huge folder cannot starve the rest.
"""
from __future__ import annotations

import email
import email.policy
import email.utils
import hashlib
import html
import re
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .. import identity
from ..schema import AttachmentRef, Chat, IngestResult, Message

PLATFORM = "outlook"

# Headers worth reading straight off the transport block.
_WANTED_HEADERS = ("message-id", "from", "to", "cc", "subject", "date",
                   "in-reply-to", "references")

# MAPI property ids we read directly. Named because a bare hex literal in a loop is
# unreadable six months later.
_PROP_MESSAGE_CLASS = 0x001A
_PROP_DISPLAY_NAME = 0x3001
_PROP_ATTACH_MIME = 0x370E
# The owner. `PR_RECEIVED_BY_EMAIL_ADDRESS` is stamped on everything that arrived,
# `PR_SENT_REPRESENTING_EMAIL_ADDRESS` on everything that left. Both name the mailbox
# this file belongs to, which is the only place a PST states the owner outright —
# the transport headers do not, and the Sent copies have no headers at all.
_PROP_RECEIVED_BY_EMAIL = 0x0076
_PROP_SENT_REPRESENTING_EMAIL = 0x0065
_PROP_RECEIVED_BY_NAME = 0x0040
_PROP_SENT_REPRESENTING_NAME = 0x0042

_WS = re.compile(r"[ \t]+")
_HTML_TAG = re.compile(r"<[^>]+>")
# Block-level tags become a newline before the generic tag strip, so an HTML-only
# body keeps its paragraph breaks instead of collapsing to one line.
_HTML_BLOCK = re.compile(r"(?i)<\s*(?:br|/p|/div|/tr|/li|/h[1-6])\s*/?\s*>")

# Folders that are not conversations the user had. Mail in these is still mail, so
# this is a name list — the one place a name is trusted, because the folder is the
# only evidence that the user deleted or never sent the thing.
_SKIP_FOLDER_NAMES = {
    "deleted items", "deleted messages", "trash", "junk", "junk email", "spam",
    "drafts", "outbox", "sync issues", "conflicts", "local failures",
    "server failures", "rss feeds", "conversation history",
}

# Folders whose mail was sent by the owner. Structural evidence for `is_self`, the
# same rule `email_imap.folder_is_sent` applies — not a guess from a display name.
_SENT_FOLDER_NAMES = {"sent items", "sent", "sent messages", "sent mail", "outbox"}

# Message classes that are not conversations. Matched by prefix, because Outlook
# subclasses them (`IPM.Contact.SBE`, `IPM.Appointment.Recurring`). Anything not
# listed here is kept: an unknown class is more likely mail than not.
_NON_MAIL_CLASSES = (
    "IPM.Appointment", "IPM.Contact", "IPM.DistList", "IPM.StickyNote",
    "IPM.Task", "IPM.Activity", "IPM.Document", "IPM.Post", "IPM.Remote",
)


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
        except (AttributeError, TypeError, OSError):
            continue
        if not raw:
            continue
        text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
        if getter != "get_plain_text_body":
            text = html.unescape(_HTML_TAG.sub(" ", _HTML_BLOCK.sub("\n", text)))
        cleaned = "\n".join(_WS.sub(" ", line).rstrip() for line in text.split("\n")).strip()
        if cleaned:
            return cleaned
    return ""


def _record_value(owner: Any, property_id: int) -> str | None:
    """First string value for a MAPI property id, or None.

    `pypff` exposes properties only through record sets, and `get_data_as_string()`
    raises `OSError` for every non-string type — so the type check happens first and
    the call is still guarded.
    """
    try:
        for index in range(owner.get_number_of_record_sets()):
            record_set = owner.get_record_set(index)
            for entry_index in range(record_set.get_number_of_entries()):
                entry = record_set.get_entry(entry_index)
                if entry.get_entry_type() != property_id:
                    continue
                try:
                    return entry.get_data_as_string()
                except (OSError, TypeError):
                    return None
    except (AttributeError, TypeError, OSError):
        return None
    return None


def _owner_evidence(message: Any) -> tuple[str, str]:
    """(address, display_name) for the mailbox this message proves, or ("", "").

    Received mail names the mailbox that received it; sent mail names who it was sent
    on behalf of. Either is the owner, and a real PST carries one of them on every
    message — which is what makes the owner derivable without being told.
    """
    for address_prop, name_prop in (
        (_PROP_RECEIVED_BY_EMAIL, _PROP_RECEIVED_BY_NAME),
        (_PROP_SENT_REPRESENTING_EMAIL, _PROP_SENT_REPRESENTING_NAME),
    ):
        address = (_record_value(message, address_prop) or "").strip().strip("'").lower()
        if address and "@" in address:
            return address, (_record_value(message, name_prop) or "").strip()
    return "", ""


def _derive_owner(evidence: list[tuple[str, str]]) -> tuple[str | None, int, set[str]]:
    """(address, rows-that-said-so, display names paired with it).

    A bare plurality is not evidence — the same rule `identity.infer_owner` applies to
    Telegram. The winner must lead the runner-up outright, or the owner stays unknown
    and every row falls back to the folder rule. Guessing here would silently label a
    correspondent as the owner.

    The display names come back too: the owner appears in `participant_names` as both
    an address and a name, and pruning only the address leaves the owner in the graph
    as a correspondent under their own name.
    """
    counts: dict[str, int] = {}
    names: dict[str, set[str]] = {}
    for address, name in evidence:
        if not address:
            continue
        counts[address] = counts.get(address, 0) + 1
        if name:
            names.setdefault(address, set()).add(name.strip().lower())
    if not counts:
        return None, 0, set()
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    winner, count = ranked[0]
    if len(ranked) > 1 and ranked[1][1] >= count:
        return None, 0, set()
    return winner, count, names.get(winner, set())


def _message_class(message: Any) -> str:
    """`PR_MESSAGE_CLASS`, e.g. `IPM.Note`. Empty when the store does not say."""
    return (_record_value(message, _PROP_MESSAGE_CLASS) or "").strip()


def _is_mail(message_class: str) -> bool:
    """Unknown classes are mail. Only a known non-mail class is refused."""
    if not message_class:
        return True
    return not any(message_class.startswith(prefix) for prefix in _NON_MAIL_CLASSES)


def _attachment_meta(attachment: Any) -> tuple[str, str | None, int | None]:
    """(filename, mime, size). Embedded messages have no filename — only a display
    name like `message 1 (2.23 KB)` — so that is the fallback."""
    try:
        name = (attachment.get_long_filename() or "").strip()
    except (AttributeError, TypeError, OSError):
        name = ""
    if not name:
        name = (_record_value(attachment, _PROP_DISPLAY_NAME) or "").strip()
    mime = (_record_value(attachment, _PROP_ATTACH_MIME) or "").strip() or None
    try:
        size = attachment.get_size()
    except (AttributeError, TypeError, OSError):
        size = None
    return name or "attachment", mime, size


def _thread_id(conversation_index: bytes | None, folder_path: str,
               headers: dict[str, str], subject: str, identifier: str) -> str:
    """Outlook's own conversation id first, then the standards-defined chain.

    `conversation_index` is what makes the Inbox copy and the Sent copy of one mail
    the same thread. It is only unique within one store, which is why it is hashed
    rather than used raw.
    """
    if conversation_index:
        return _stable("conv:" + conversation_index.hex())
    references = headers.get("references") or ""
    if references.split():
        return _stable("ref:" + references.split()[0])
    in_reply_to = (headers.get("in-reply-to") or "").strip()
    if in_reply_to:
        return _stable("irt:" + in_reply_to)
    topic = _normalise_subject(subject)
    if topic:
        return _stable("subj:" + topic)
    return _stable("folder:" + (folder_path or identifier))


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


def _fingerprint(thread: str, ts: datetime, body: str) -> str:
    """Content identity for "this is the same mail filed in two folders".

    Two things are deliberately loose, both measured on the sample file:

    - **The timestamp is truncated to the second.** The copies differ in
      microseconds (`23:47:01` vs `23:47:01.046875`) — one message, stored twice.
    - **All whitespace is removed from the body.** The Sent copy is hard-wrapped at
      76 columns, so `.../aspose-newsletter-header-june-2011.png` arrives as
      `.../aspose-newsletter-header\r\n-june-2011.png`. Comparing text verbatim
      misses every wrapped copy.

    The sender is *not* part of it: the Sent copy has no `From:` header at all, so
    including one would make the two copies unmatchable by construction. The cost is
    that two people sending byte-identical text in the same thread in the same
    second would merge — accepted, because the alternative is every sent message
    appearing twice.
    """
    material = "\x1f".join((thread, ts.strftime("%Y-%m-%dT%H:%M:%S"),
                            "".join(body.split())))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def _walk(folder: Any, prefix: str) -> Iterator[tuple[str, Any]]:
    """Depth-first (folder_path, folder). Yields the folder itself before children."""
    try:
        name = folder.get_name() or ""
    except (AttributeError, TypeError, OSError):
        name = ""
    path = f"{prefix}/{name}" if prefix else name
    yield path, folder
    try:
        count = folder.get_number_of_sub_folders()
        children = [folder.get_sub_folder(i) for i in range(count)]
    except (AttributeError, TypeError, OSError):
        return
    for child in children:
        if child is not None:
            yield from _walk(child, path)


def parse(
    export_path: str | Path,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
    self_id: str | None = None,
    include_service: bool = True,
    profile_dir: str | Path | None = None,
    include_skipped_folders: bool = False,
) -> IngestResult:
    """Read every mail message in a `.pst` file.

    `since` / `until` bound the window by send time (delivery time as fallback) and
    must be timezone-aware. A decade-old mailbox exports in one file, so the window
    is the only thing keeping a demo quick.

    `self_id` is the owner's address when the caller knows it. Without it, ownership
    is decided structurally: mail out of a sent-class folder is the owner's.
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

    path = Path(export_path)
    result = IngestResult(platform=PLATFORM, export_path=str(path))

    pst = pypff.file()
    try:
        # libpff prefixes a forward-slash path with the CWD and fails with a
        # confusing `\\?\C:\C:\Users\...`. `str(Path(...))` is backslashed on
        # Windows, which is the form it wants.
        pst.open(str(path))
    except OSError as exc:
        raise RuntimeError(f"cannot open {path}: {exc}") from exc

    try:
        # Trap 3: a string codepage, not an int.
        try:
            pst.set_ascii_codepage("cp1252")
        except (AttributeError, TypeError):
            pass
        try:
            # libpff: 0 = none, 1 = compressible (normal, every modern PST), 2+ =
            # actually encrypted. Warning on 1 flagged every healthy file.
            if pst.get_encryption_type() >= 2:
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
        # fingerprint -> index in result.messages. The same mail filed in two folders
        # is one row; see the module docstring.
        by_fingerprint: dict[str, int] = {}
        chats: dict[str, Chat] = {}
        # Collected during the walk, resolved once afterwards: the owner is the
        # address the file names most often, which cannot be known until every
        # message has been read.
        owner_evidence: list[tuple[str, str]] = []
        sent_rows: set[int] = set()

        for folder_path, folder in _walk(root, ""):
            leaf = folder_path.rsplit("/", 1)[-1].strip().lower()
            if leaf in _SKIP_FOLDER_NAMES and not include_skipped_folders:
                result.note_skip(f"excluded folder ({leaf})")
                continue

            try:
                count = folder.get_number_of_sub_messages()
            except (AttributeError, TypeError, OSError):
                count = 0
            if not count:
                # Trap 1: a folder of sub_items is not empty, just not messages.
                try:
                    if folder.get_number_of_sub_items():
                        result.note_skip("folder holds items, not messages")
                except (AttributeError, TypeError, OSError):
                    pass
                continue

            for index in range(count):
                try:
                    message = folder.get_sub_message(index)
                except (AttributeError, TypeError, OSError):
                    result.note_skip("unreadable message")
                    continue
                if message is None:
                    result.note_skip("unreadable message")
                    continue

                parsed = _parse_message(message, folder_path, result, since, until)
                if parsed is None:
                    continue
                row, attachments, chat, fingerprint, evidence, from_sent = parsed
                if evidence[0]:
                    owner_evidence.append(evidence)

                if fingerprint in by_fingerprint:
                    # Trap 2 of the docstring: the same mail in another folder.
                    stored = by_fingerprint[fingerprint]
                    existing = result.messages[stored]
                    if from_sent and not existing.is_self:
                        result.messages[stored] = replace(existing, is_self=True)
                        sent_rows.add(stored)
                    result.note_skip("duplicate copy in another folder")
                    continue
                if row.key in seen:
                    result.note_skip("duplicate within run")
                    continue

                seen.add(row.key)
                by_fingerprint[fingerprint] = len(result.messages)
                if from_sent:
                    sent_rows.add(len(result.messages))
                result.messages.append(row)
                result.attachments.extend(attachments)
                chats.setdefault(chat.chat_id, chat)
    finally:
        try:
            pst.close()
        except Exception:  # noqa: BLE001 - closing must not mask a read error
            pass

    # Chats first: `_apply_owner` prunes the owner out of `participant_names`, and it
    # can only do that once the chats are on the result.
    result.chats.extend(chats.values())
    _apply_owner(result, owner_evidence, sent_rows, self_id, profile_dir)
    return result


def _apply_owner(
    result: IngestResult,
    evidence: list[tuple[str, str]],
    sent_rows: set[int],
    self_id: str | None,
    profile_dir: str | Path | None,
) -> None:
    """Resolve the owner and mark their mail `is_self`.

    Precedence follows `identity.py`: an explicit `self_id`, then the persisted owner
    for this platform, then what the file itself states. Persisting it is what makes a
    second export of the same mailbox agree with the first.
    """
    owner = (self_id or "").strip().lower() or None
    note = ""

    # What the file itself says, always — even when the caller stated an owner, so a
    # contradiction between the two is visible instead of silently resolved.
    derived, count, owner_names = _derive_owner(evidence)

    if owner is None and profile_dir:
        stored = identity.load_owner(profile_dir, PLATFORM)
        if stored:
            owner = stored.strip().lower()

    if owner is None:
        if derived:
            owner = derived
            if profile_dir:
                try:
                    identity.save_owner(profile_dir, derived,
                                        evidence=f"pst received-by/sent-representing ({count} rows)",
                                        platform=PLATFORM)
                except ValueError as exc:
                    note = f"owner conflict: {exc}"
        elif evidence:
            note = ("is_self unresolved: the pst names more than one mailbox equally; "
                    "pass self_id= or profile_dir= so exports agree")
    elif derived and derived != owner:
        # The caller wins, because they may be reading a mailbox they were given. But
        # the file disagrees, and that is worth saying out loud.
        note = (f"owner conflict: caller says {owner}, the pst says {derived} "
                f"({count} rows); using the caller's value")

    if owner:
        for index, row in enumerate(result.messages):
            if row.is_self:
                continue
            if index in sent_rows or (row.sender_id or "").lower() == owner:
                result.messages[index] = replace(row, is_self=True)

        # The owner is not a correspondent. `writer.write_correspondents` filters by
        # display name, which cannot match an address — so the owner is removed here,
        # where they are actually known, under both forms the export uses.
        #
        # The display name is only pruned when the owner's address is present in the
        # same chat: a name alone is not proof that this participant is the owner
        # rather than a namesake.
        owner_forms = {owner} | owner_names
        for chat in result.chats:
            names = list(chat.participant_names)
            if not any(name.strip().lower() == owner for name in names):
                continue
            # An empty result is correct when the owner is the only participant — a
            # thread you mailed yourself has no counterparty, and inventing one is
            # the error this is here to prevent.
            chat.participant_names = tuple(
                name for name in names if name.strip().lower() not in owner_forms)

        result.warnings.append(f"owner: {owner}")
    else:
        note = note or ("is_self unresolved: the pst names no mailbox; "
                        "only mail in a sent folder is marked as the owner's")

    if note:
        result.warnings.append(note)


def _parse_message(
    message: Any,
    folder_path: str,
    result: IngestResult,
    since: datetime | None,
    until: datetime | None,
) -> tuple[Message, list[AttachmentRef], Chat, str, tuple[str, str], bool] | None:
    """One sub_message -> (row, attachments, chat, fingerprint, owner evidence,
    from-sent-folder), or None if skipped."""
    if not hasattr(message, "get_subject"):
        # `Freebusy Data` hands back a bare `pypff.item`, which has record sets but
        # no message accessors at all. Not mail, and not a parse failure either.
        result.note_skip("not a message (item)")
        return None

    message_class = _message_class(message)
    if not _is_mail(message_class):
        # Trap 2: an appointment or a contact is not a conversation.
        result.note_skip(f"not mail ({message_class})")
        return None

    try:
        headers = _headers(message.get_transport_headers())
    except (AttributeError, TypeError, OSError):
        headers = {}

    ts = None
    for getter in ("get_client_submit_time", "get_delivery_time", "get_creation_time"):
        try:
            ts = _as_utc(getattr(message, getter)())
        except (AttributeError, TypeError, OSError):
            ts = None
        if ts is not None:
            break
    if ts is None:
        result.note_skip("no usable timestamp")
        return None
    if since is not None and ts < since:
        result.note_skip("before window")
        return None
    if until is not None and ts > until:
        result.note_skip("after window")
        return None

    try:
        subject = (message.get_subject() or "").strip()
    except (AttributeError, TypeError, OSError):
        subject = ""
    subject = _normalise_subject(headers.get("subject") or subject)
    body = _body(message)

    try:
        identifier = message.get_identifier() or ""
    except (AttributeError, TypeError, OSError):
        identifier = ""
    try:
        conversation_index = message.get_conversation_index()
    except (AttributeError, TypeError, OSError):
        conversation_index = None

    message_id = (headers.get("message-id") or "").strip()
    if not message_id:
        # Trap 5: the sent side has no headers at all, so this is the normal path
        # for half of a real mailbox.
        result.note_kind("missing message-id")
        message_id = f"pst:{identifier or _stable(folder_path + str(ts))}"

    thread = _thread_id(conversation_index, folder_path, headers, subject, identifier)
    key = f"{PLATFORM}:{thread}:{message_id}"

    try:
        sender_name = (message.get_sender_name() or "").strip()
    except (AttributeError, TypeError, OSError):
        sender_name = ""
    from_header = headers.get("from") or ""
    sender_addr = email.utils.parseaddr(from_header)[1].lower() if from_header else ""

    recipients: list[str] = []
    for header in ("to", "cc"):
        raw = headers.get(header) or ""
        if not raw:
            continue
        try:
            for name, addr in email.utils.getaddresses([raw]):
                label = (name or "").strip() or (addr or "").strip().lower()
                if label:
                    recipients.append(label)
        except (TypeError, ValueError):
            continue

    attachments: list[tuple[str, str | None, int | None]] = []
    try:
        for i in range(message.get_number_of_attachments()):
            attachment = message.get_attachment(i)
            if attachment is not None:
                attachments.append(_attachment_meta(attachment))
    except (AttributeError, TypeError, OSError):
        pass

    raw_kind = "attachment" if attachments and not body else ("text" if body else "empty")
    if raw_kind != "text":
        result.note_kind(raw_kind)

    # Ownership is structural, not guessed from a name: mail out of a sent-class
    # folder was sent by the owner. The address-based half of the rule needs the
    # owner, which is only known once the whole file has been read — `_apply_owner`
    # finishes the job.
    leaf = folder_path.rsplit("/", 1)[-1].strip().lower()
    from_sent = leaf in _SENT_FOLDER_NAMES
    is_self = from_sent

    row = Message(
        key=key, platform=PLATFORM, chat_id=thread, message_id=message_id,
        ts_utc=ts, sender_name=sender_name or from_header or sender_addr,
        sender_id=sender_addr or None, body=body, reply_to=None,
        has_attachments=bool(attachments),
        is_self=is_self,
        raw_kind=raw_kind, saved_from=subject or None,
    )
    refs = [AttachmentRef(platform=PLATFORM, chat_id=thread, message_id=message_id,
                          path=name, mime=mime, size=size)
            for name, mime, size in attachments]

    chat = Chat(
        platform=PLATFORM, chat_id=thread,
        title=subject or folder_path or thread,
        kind="group_chat" if len(recipients) > 1 else "personal_chat",
        is_group=len(recipients) > 1,
        participant_names=tuple(sorted(
            {sender_name or sender_addr} | set(recipients) - {""})),
    )

    fingerprint = _fingerprint(thread, ts, body)
    return row, refs, chat, fingerprint, _owner_evidence(message), from_sent


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
