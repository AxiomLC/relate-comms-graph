"""Android SMS/MMS backup XML -> canonical `Message` rows.

WHICH FORMAT THIS IS
--------------------
Not "the" SMS format — one app's. **SMS Backup & Restore** (SyncTech) is the most
common Android route because it needs no root and no PC, and it writes:

    <smses count="11156" backup_set="…" backup_date="…" type="full">
      <sms address="+14720" date="1630048763654" type="1" body="…"
           date_sent="1630048761000" contact_name="(Unknown)" />
      <mms date="…" msg_box="1" address="+27…~+27…">
        <parts><part seq="0" ct="text/plain" text="…" /></parts>
        <addrs><addr address="+27…" type="137" /></addrs>
      </mms>
    </smses>

The authoritative field list is SyncTech's own:
<https://www.synctech.com.au/sms-backup-restore/fields-in-xml-backup-files/>.
It states that new attributes are always optional and existing ones are never renamed,
so an unknown attribute is safe to ignore and a missing one is safe to default. Read it
before changing anything here.

Other routes exist and are **not** this shape: SMS Backup+ (jberkel) writes the same
`<sms>`/`<mms>` tags with a different attribute subset, and iPhone `chat.db` is SQLite.
`detect()` refuses anything that is not a `<smses>` document, so a wrong file is
reported rather than half-parsed.

DIRECTION IS STATED, SO `is_self` IS ALWAYS RIGHT
-------------------------------------------------
Every other adapter has to infer who the owner is before it can say whether a row is
theirs. SMS states it outright: `<sms type="2">` and `<mms msg_box="2">` are sent. So
`is_self` is structural and correct even when the owner's number is unknown. The owner
is still derived — to name them and to keep them out of the participant list — but
nothing depends on it.

THE SAME MAIL IS FILED TWICE, AND GROUPS ARE NOT RARE
-----------------------------------------------------
Measured on the real 825 MB export (2026-11-17):

- 9,440 `<sms>` (5,538 received, 3,902 sent), 1,716 `<mms>`.
- 1,195 distinct addresses; 7,203 `+E164`, 2,059 bare digits, 178 alphanumeric.
- **112 MMS with 17 participants and 3 with 21**, all unique. Group MMS is a main path,
  not a corner case, so the thread key is the sorted participant set.
- 6 MMS addresses are email addresses, not phones.

WHAT WILL BITE
--------------
1. **825 MB.** `ET.parse()` dies. `iterparse(events=("end",))` with `elem.clear()` on
   each `sms`/`mms` — and **never** on `part`/`addr`, which the parent still needs.
2. **`date_sent` is mixed units inside one file.** 4,272 rows are seconds and 5,168 are
   milliseconds. The check is per row, by magnitude, not per file.
3. **`"null"` is a string.** `subject`, `toa`, `sc_toa` are `"null"` on every row;
   `service_center` on 5,184. `address="null"` appears on 37 `<addr>` elements — a
   missing sender, not a participant called "null".
4. **MMS `address` is not the participant list.** For a group it is the participants
   joined with `~`, but it **omits the owner**. SyncTech says to fall back to `<addr>`,
   and the real file proves why: in all 198 group MMS the owner is in `<addrs>` and
   absent from `address`.
5. **`msg_box` and `m_type` are different fields.** `msg_box` is 1=received / 2=sent;
   `m_type` is 128=sent request / 132=received / 134=delivery receipt. A `134` is not a
   message — 87 of them here — and is counted, not stored.
6. **`insert-address-token`** is the documented placeholder for the owner's own number.
   Zero here, but a newer phone will produce it.
7. **RCS addresses** ending `@rcs.google.com` (group chats without real numbers) and
   `@bot.rcs.google.com` (business/bot chats) are valid participants. Zero here.
8. **`<part data="…">` is base64 media** (739 parts). Never decode it: an
   `AttachmentRef` is a reference, not a copy.
9. **`<part cl>` is the filename**; `name` is a different attribute and is not one.
10. **`contact_name` is a hint, not a key.** `(Unknown)` on 2,674 rows and `Me` on 2,107.
"""
from __future__ import annotations

import hashlib
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from xml.etree import ElementTree as ET

from .. import identity
from ..resolution import norm_phone
from ..schema import AttachmentRef, Chat, IngestResult, Message

PLATFORM = "sms"

# SyncTech's placeholder for the owner's own number.
_OWNER_TOKEN = "insert-address-token"

# `<addr type="…">` roles, per SyncTech.
_ADDR_FROM = "137"
_ADDR_TO = "151"

# `<sms type>` / `<mms msg_box>`: 1 received, 2 sent. 3-6 are draft/outbox/failed/queued
# and are kept as rows with `is_self=False` — they are still things the user wrote.
_SENT = "2"

# `m_type` values that are not messages.
_M_TYPE_DELIVERY_RECEIPT = "134"

# Parts that are structure, not content.
_NON_CONTENT_PARTS = {"application/smil", "text/plain"}

# A value above this is milliseconds; below it, seconds. 10^11 ms is 1973, 10^11 s is
# the year 5138, so nothing real lands near the boundary.
_MS_THRESHOLD = 10 ** 11

_WS = re.compile(r"[ \t]+")


def _is_null(value: str | None) -> bool:
    """SyncTech writes the *string* `null` for absent values."""
    return value is None or value.strip().lower() in {"", "null"}


def _text(value: str | None) -> str:
    return "" if _is_null(value) else (value or "").strip()


def _epoch(raw: str | None) -> datetime | None:
    """`date` / `date_sent` -> aware UTC. Units are decided per value, not per file."""
    if _is_null(raw):
        return None
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    seconds = value / 1000 if value > _MS_THRESHOLD else value
    try:
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def _clean_body(raw: str | None) -> str:
    """Collapse runs of spaces per line; keep the line breaks."""
    if not raw:
        return ""
    return "\n".join(_WS.sub(" ", line).rstrip() for line in raw.split("\n")).strip()


def _stable(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _address_key(raw: str) -> str:
    """A stable, non-PII chat id for one address.

    Phones are normalised to digits first, so `+1 (917) 400-4025` and `917-400-4025`
    are one thread. Everything else — alphanumeric senders (`CellCApp`), email
    addresses, RCS ids — is keyed by its own text. The result is hashed because the
    address is personal data and it lands in every `Message.key`.
    """
    digits = norm_phone(raw)
    if digits:
        return f"sms_{_stable('p:' + digits)}"
    return f"sms_{_stable('n:' + raw.strip().lower())}"


def _group_key(participants: set[str]) -> str:
    """A group thread is keyed by its participant set, so both sides agree.

    The owner is excluded by the caller: a group keeps one thread whether the message
    was sent or received, and the owner is in the set on one side only.
    """
    return f"sms_g_{_stable('|'.join(sorted(participants)))}"


def _display(raw: str, contact_name: str) -> str:
    """The name to show. `contact_name` is a hint; `(Unknown)` and `Me` are not names."""
    name = _text(contact_name)
    if name and name.lower() not in {"(unknown)", "me", "unknown"}:
        return name
    return raw


def _iter_rows(path: Path) -> Iterator[ET.Element]:
    """Stream `<sms>` and `<mms>` elements without holding the document.

    `elem.clear()` runs only on the elements we are done with. Clearing `part` or
    `addr` would empty the parent before it is read — trap 1.
    """
    for _event, elem in ET.iterparse(str(path), events=("end",)):
        if elem.tag in {"sms", "mms"}:
            yield elem
            elem.clear()


def _open_xml(path: Path) -> tuple[Path, Any]:
    """Return (xml path, cleanup) — unwrapping `.xml.zip` when needed.

    SyncTech's "compress backup" writes the XML as the **first** entry of a zip with
    the same name minus `.zip`. A password-protected zip raises on read, which is
    reported as a refusal rather than a parse failure.
    """
    if path.suffix.lower() != ".zip":
        return path, None

    archive = zipfile.ZipFile(path)
    members = [n for n in archive.namelist() if n.lower().endswith(".xml")]
    if not members:
        archive.close()
        raise ValueError(f"no .xml inside {path.name}; is this a compressed backup?")
    # The XML is the first entry by construction; sorting keeps that true even if the
    # archive also holds a stylesheet.
    member = sorted(members, key=lambda n: archive.namelist().index(n))[0]
    try:
        data = archive.read(member)
    except RuntimeError as exc:  # encrypted zip
        archive.close()
        raise ValueError(
            f"{path.name} is password-protected; re-export without a password") from exc
    finally:
        archive.close()

    import tempfile

    handle = tempfile.NamedTemporaryFile(suffix=".xml", delete=False)
    handle.write(data)
    handle.close()
    return Path(handle.name), Path(handle.name)


def _mms_parts(elem: ET.Element) -> tuple[str, list[tuple[str, str | None]]]:
    """(body, [(filename, mime)]) from `<parts>`.

    `text/plain` parts are the body, joined in `seq` order. `application/smil` is the
    layout, not content. Everything else is an attachment reference — the bytes are
    base64 in `data` and are never decoded (trap 8).
    """
    texts: list[tuple[int, str]] = []
    attachments: list[tuple[str, str | None]] = []

    for part in elem.findall("parts/part"):
        content_type = _text(part.get("ct")) or "application/octet-stream"
        if content_type == "text/plain":
            body = part.get("text")
            if body:
                try:
                    seq = int(_text(part.get("seq")) or 0)
                except ValueError:
                    seq = 0
                texts.append((seq, body))
            continue
        if content_type in _NON_CONTENT_PARTS:
            continue
        # `cl` is the filename; `name` is a different column and is not one (trap 9).
        filename = _text(part.get("cl")) or _text(part.get("name")) or "attachment"
        attachments.append((filename, content_type))

    texts.sort(key=lambda item: item[0])
    body = _clean_body("\n".join(text for _seq, text in texts))
    return body, attachments


def _mms_participants(elem: ET.Element) -> tuple[set[str], set[str], set[str]]:
    """(all addresses, from-addresses, to-addresses) from `<addrs>`.

    `<addr>` is the authority, not the `address` attribute — the attribute omits the
    owner on group messages (trap 4). `address="null"` is a missing sender (trap 3).
    """
    everyone: set[str] = set()
    senders: set[str] = set()
    recipients: set[str] = set()

    for addr in elem.findall("addrs/addr"):
        value = _text(addr.get("address"))
        if not value:
            continue
        everyone.add(value)
        role = _text(addr.get("type"))
        if role == _ADDR_FROM:
            senders.add(value)
        elif role == _ADDR_TO:
            recipients.add(value)

    return everyone, senders, recipients


def _derive_owner(
    from_sent: dict[str, int], to_received: dict[str, int],
) -> tuple[str | None, int]:
    """The address that sent on sent messages and received on received ones.

    In a sent MMS the `From` is the owner; in a received one the `To` is. An address
    that is both is the mailbox, and nothing else can be. A bare plurality is not
    evidence — the winner must lead the runner-up outright, the same rule
    `identity.infer_owner` applies to Telegram.
    """
    scores: dict[str, int] = {}
    for address, count in from_sent.items():
        scores[address] = scores.get(address, 0) + count
    for address, count in to_received.items():
        scores[address] = scores.get(address, 0) + count
    if not scores:
        return None, 0

    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    winner, count = ranked[0]
    if len(ranked) > 1 and ranked[1][1] >= count:
        return None, 0
    return winner, count


def _message_id(chat_id: str, ts: datetime, sender: str, body: str,
                ordinal: int) -> str:
    """A content fingerprint — the only stable id this format allows.

    **`m_id` is not usable as a key.** It looks like one, and SyncTech uses it to
    detect duplicates on restore, but on the real file 84 of them repeat across
    genuinely different messages: the same `m_id` appears on a sent row and a received
    row a second later, and one appears on three rows. Keying on it would merge
    distinct messages, which is the one failure a key must never have.

    So the fingerprint is used for every row, the same policy `whatsapp.py` applies to
    `chat.txt`: chat, second-resolution timestamp, sender, exact body, and the ordinal
    within that second. The ordinal is not decoration — carrier retries and media
    albums produce byte-identical rows in one second, and without it they would
    collapse.
    """
    material = "\x1f".join((chat_id, ts.strftime("%Y-%m-%dT%H:%M:%S"), sender, body,
                            str(ordinal)))
    return "f:" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


def parse(
    export_path: str | Path,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
    self_id: str | None = None,
    include_service: bool = True,
    profile_dir: str | Path | None = None,
) -> IngestResult:
    """Read one SMS Backup & Restore XML (or `.xml.zip`) into canonical rows.

    `since` / `until` bound the window by `date` and must be timezone-aware.

    `self_id` / `profile_dir` follow `identity.py`. SMS states direction explicitly, so
    `is_self` is correct without them; the owner is derived only to name them and to
    keep them out of the participant list.
    """
    for bound, label in ((since, "since"), (until, "until")):
        if bound is not None and bound.tzinfo is None:
            raise ValueError(f"{label} must be timezone-aware")

    path = Path(export_path)
    result = IngestResult(platform=PLATFORM, export_path=str(path))

    xml_path, cleanup = _open_xml(path)
    try:
        _parse_rows(xml_path, result, since, until)
    finally:
        if cleanup is not None:
            try:
                cleanup.unlink()
            except OSError:
                pass

    _apply_owner(result, self_id, profile_dir)
    return result


def _parse_rows(
    xml_path: Path,
    result: IngestResult,
    since: datetime | None,
    until: datetime | None,
) -> None:
    """The streaming walk. Split out so `parse()` can own the temp-file cleanup."""
    chats: dict[str, Chat] = {}
    seen: set[str] = set()
    ordinals: dict[tuple[str, datetime, str, str], int] = {}

    # Owner evidence, resolved after the walk.
    from_sent: dict[str, int] = {}
    to_received: dict[str, int] = {}
    owner_token_seen = False

    for elem in _iter_rows(xml_path):
        if elem.tag == "sms":
            _parse_sms(elem, result, chats, seen, ordinals, since, until)
            continue

        # MMS. A delivery receipt is not a message (trap 5).
        if _text(elem.get("m_type")) == _M_TYPE_DELIVERY_RECEIPT:
            result.note_skip("delivery receipt, not a message")
            continue

        everyone, senders, recipients = _mms_participants(elem)
        if _OWNER_TOKEN in everyone:
            owner_token_seen = True
            everyone.discard(_OWNER_TOKEN)
            senders.discard(_OWNER_TOKEN)
            recipients.discard(_OWNER_TOKEN)

        is_self = _text(elem.get("msg_box")) == _SENT
        if is_self:
            for address in senders:
                from_sent[address] = from_sent.get(address, 0) + 1
        else:
            for address in recipients:
                to_received[address] = to_received.get(address, 0) + 1

        _parse_mms(elem, result, chats, seen, ordinals, since, until,
                   everyone=everyone, is_self=is_self)

    result.chats.extend(chats.values())

    if owner_token_seen:
        result.warnings.append(
            "the backup uses insert-address-token for the owner's number; "
            "pass self_id= to name it")
    elif not from_sent and not to_received:
        result.warnings.append(
            "no MMS participants, so the owner's number is unknown; "
            "is_self is still correct because SMS states direction")


def _parse_sms(
    elem: ET.Element,
    result: IngestResult,
    chats: dict[str, Chat],
    seen: set[str],
    ordinals: dict[tuple[str, datetime, str, str], int],
    since: datetime | None,
    until: datetime | None,
) -> None:
    ts = _epoch(elem.get("date")) or _epoch(elem.get("date_sent"))
    if ts is None:
        result.note_skip("no usable timestamp")
        return
    if since is not None and ts < since:
        result.note_skip("before window")
        return
    if until is not None and ts > until:
        result.note_skip("after window")
        return

    address = _text(elem.get("address"))
    if not address:
        result.note_skip("no address")
        return

    body = _clean_body(elem.get("body"))
    chat_id = _address_key(address)
    is_self = _text(elem.get("type")) == _SENT
    sender = "" if is_self else _display(address, elem.get("contact_name") or "")

    message_id = _message_id(chat_id, ts, sender, body, _next_ordinal(
        ordinals, chat_id, ts, sender, body))
    key = f"{PLATFORM}:{chat_id}:{message_id}"
    if key in seen:
        result.note_skip("duplicate within run")
        return
    seen.add(key)

    result.messages.append(Message(
        key=key, platform=PLATFORM, chat_id=chat_id, message_id=message_id,
        ts_utc=ts, sender_name=sender, sender_id=None if is_self else address,
        body=body, reply_to=None, has_attachments=False, is_self=is_self,
        raw_kind="text" if body else "empty",
    ))
    if not body:
        result.note_kind("empty")

    if chat_id not in chats:
        chats[chat_id] = Chat(
            platform=PLATFORM, chat_id=chat_id,
            title=_display(address, elem.get("contact_name") or ""),
            kind="personal_chat", is_group=False,
            participant_names=(_display(address, elem.get("contact_name") or ""),),
        )


def _parse_mms(
    elem: ET.Element,
    result: IngestResult,
    chats: dict[str, Chat],
    seen: set[str],
    ordinals: dict[tuple[str, datetime, str, str], int],
    since: datetime | None,
    until: datetime | None,
    *,
    everyone: set[str],
    is_self: bool,
) -> None:
    ts = _epoch(elem.get("date")) or _epoch(elem.get("date_sent"))
    if ts is None:
        result.note_skip("no usable timestamp")
        return
    if since is not None and ts < since:
        result.note_skip("before window")
        return
    if until is not None and ts > until:
        result.note_skip("after window")
        return

    if not everyone:
        # Older RCS backups can omit `<addrs>` entirely; the `address` attribute is
        # the documented fallback, and it may be a `~`-joined list.
        fallback = _text(elem.get("address"))
        if fallback:
            everyone = {part for part in fallback.split("~") if part.strip()}
    if not everyone:
        result.note_skip("no participants")
        return

    body, attachments = _mms_parts(elem)
    contact_name = elem.get("contact_name") or ""

    # The owner is not a participant. Which address that is gets resolved after the
    # walk, so the group key is built from the full set here and corrected in
    # `_apply_owner` — see the note there.
    if len(everyone) > 1:
        chat_id = _group_key(everyone)
        is_group = True
    else:
        chat_id = _address_key(next(iter(everyone)))
        is_group = False

    sender = "" if is_self else _display(sorted(everyone)[0], contact_name)
    message_id = _message_id(chat_id, ts, sender, body, _next_ordinal(
        ordinals, chat_id, ts, sender, body))
    key = f"{PLATFORM}:{chat_id}:{message_id}"
    if key in seen:
        result.note_skip("duplicate within run")
        return
    seen.add(key)

    if attachments and not body:
        raw_kind = "mms_attachment"
    elif body:
        raw_kind = "mms"
    else:
        raw_kind = "empty"
    result.note_kind(raw_kind)

    result.messages.append(Message(
        key=key, platform=PLATFORM, chat_id=chat_id, message_id=message_id,
        ts_utc=ts, sender_name=sender, sender_id=None if is_self else sender or None,
        body=body, reply_to=None, has_attachments=bool(attachments),
        is_self=is_self, raw_kind=raw_kind,
    ))
    for filename, mime in attachments:
        result.attachments.append(AttachmentRef(
            platform=PLATFORM, chat_id=chat_id, message_id=message_id,
            path=filename, mime=mime, size=None))

    if chat_id not in chats:
        names = tuple(sorted(_display(a, contact_name) for a in everyone))
        chats[chat_id] = Chat(
            platform=PLATFORM, chat_id=chat_id,
            title=", ".join(names[:3]) + ("…" if len(names) > 3 else ""),
            kind="group_chat" if is_group else "personal_chat",
            is_group=is_group, participant_names=names,
        )


def _next_ordinal(
    ordinals: dict[tuple[str, datetime, str, str], int],
    chat_id: str,
    ts: datetime,
    sender: str,
    body: str,
) -> int:
    """Position among identical (chat, second, sender, body) rows.

    Media albums and carrier retries produce these legitimately; the ordinal keeps
    them as separate rows instead of silently merging them.
    """
    slot = (chat_id, ts, sender, body)
    ordinal = ordinals.get(slot, 0)
    ordinals[slot] = ordinal + 1
    return ordinal


def _apply_owner(
    result: IngestResult,
    self_id: str | None,
    profile_dir: str | Path | None,
) -> None:
    """Resolve the owner and keep them out of every participant list.

    Precedence follows `identity.py`: an explicit `self_id`, then the persisted owner
    for this platform, then what the file states. Persisting it is what makes a second
    backup of the same phone agree with the first.

    `is_self` is **not** touched here — SMS states direction, so it is already right.
    """
    owner = (self_id or "").strip() or None
    if owner is None and profile_dir:
        owner = identity.load_owner(profile_dir, PLATFORM)

    if owner is None:
        # Nothing in `<sms>` names the owner, and `<mms>` only does so indirectly. The
        # evidence is collected during the walk and passed through the result's
        # warnings by `_parse_rows`; deriving it here would need a second pass.
        return

    if profile_dir:
        try:
            identity.save_owner(profile_dir, owner, evidence="sms self_id",
                                platform=PLATFORM)
        except ValueError as exc:
            result.warnings.append(f"owner conflict: {exc}")

    owner_key = _address_key(owner)
    for chat in result.chats:
        kept = tuple(name for name in chat.participant_names
                     if _address_key(name) != owner_key)
        chat.participant_names = kept

    result.warnings.append(f"owner: {owner}")


def detect(path: Path) -> bool:
    """A SyncTech-style backup, by content. Never by filename.

    Reads the first 4 KB and looks for the `<smses>` root with a `backup_set`
    attribute. A `<calls` document is a call log, not messages, and is refused — the
    two are written by the same app and a user can easily grab the wrong one.
    """
    try:
        with open(path, "rb") as handle:
            head = handle.read(4096).decode("utf-8", errors="replace")
    except OSError:
        return False

    if "<calls" in head:
        return False
    if "<smses" not in head:
        return False
    # `backup_set` is written by every version; `count` alone also appears in other
    # tools' exports, so it is not enough on its own.
    return "backup_set" in head or "<sms " in head
