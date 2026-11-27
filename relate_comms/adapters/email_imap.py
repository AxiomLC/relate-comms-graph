"""Email over IMAP -> canonical `Message` rows.

THE ONE PLATFORM WITH REAL MESSAGE IDS
--------------------------------------
Every other adapter fingerprints a message from its content because the export
offered nothing better. Email states `Message-ID` outright, so this adapter uses it:

    Message.key = email:<chat_id>:<Message-ID>

That means re-ingest is *exactly* idempotent, with no same-second-ordinal tricks and
no collision heuristics.

READ-ONLY BY CONSTRUCTION
-------------------------
Only `SELECT ... (READONLY)`, `SEARCH`, `FETCH BODY.PEEK[]` and `UID` commands are used.
`BODY.PEEK` matters: `BODY[]` sets the `\\Seen` flag, so a read-only tool that used it
would silently mark a decade of the user's mail as read. `EXAMINE` is used instead of
`SELECT` for the same reason.

WHAT REAL MAILBOXES TAUGHT US
-----------------------------
1. **The inbox is not the conversation.** Your own replies live in Sent; Gmail's
   "All Mail" holds both. Reading INBOX alone gives you half of every exchange.
2. **Folder names are not standard.** Hostinger uses `INBOX.Sent`; Gmail uses
   `[Gmail]/All Mail`. Folders are discovered with `LIST` and matched case-insensitively,
   never hardcoded.
3. **Old accounts are large.** 7,680 messages in one Gmail "All Mail" — so the date
   window is a first-class argument (`since`/`until`), not an afterthought. A decade
   of mail should be asked for deliberately.
4. **Headings and quoting are noise.** A reply body carries the whole previous message
   below `On ... wrote:`. That text is kept as-is: trimming it is a heuristic that
   silently loses content, and dedupe already prevents the graph from double-counting.
5. **HTML-only mail is common.** `get_body` prefers `text/plain`, falls back to a
   tag-stripped `text/html`, and never assumes either exists.

DEGRADED ENCODINGS
------------------
`UID FETCH` with `BODY.PEEK[]` returns the raw message. `email.message_from_bytes`
parses it without a network call. An unparseable message is counted, never dropped
silently (§3.2's "never a silent drop").
"""
from __future__ import annotations

import email
import hashlib
import imaplib
import re
import ssl
from datetime import datetime, timezone
from email.header import decode_header, make_header
from email.message import Message as EmailMessage
from email.utils import parsedate_to_datetime, getaddresses
from pathlib import Path
from typing import Any, Iterable, Iterator

from ..schema import Chat, IngestResult, Message

PLATFORM = "email"

# A saved mailbox: one RFC 5322 message per file. `sample_writer` writes these, and
# so does any mail client's "Save As". The suffix is the only signal needed.
_EML_SUFFIX = ".eml"

# Folders we look for, by intent. Matched against the LAST path segment, because
# servers namespace them differently: Gmail uses `[Gmail]/Sent Mail`, Hostinger
# uses `INBOX.Sent`. Comparing whole names silently missed every sent message.
_INBOX_HINTS = ("inbox",)
_SENT_HINTS = ("sent", "sent items", "sent messages", "sent mail")
# Gmail's All Mail already contains Inbox and Sent; importing both would double up.
_ALL_MAIL_HINTS = ("all mail",)
# Never imported: not conversations, and huge.
_SKIP_HINTS = ("trash", "deleted", "junk", "spam", "drafts", "bounces",
               "draft", "bin", "quarantine")

_HTML_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"[ \t]+")


def _decode(value: str | None) -> str:
    """RFC 2047 header decoding; `=?utf-8?b?...?=` is common in real mail."""
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except (UnicodeDecodeError, LookupError):
        return value


def _folders(conn: imaplib.IMAP4_SSL) -> list[tuple[str, str]]:
    """(raw_name, display_name) for every folder the server lists.

    `LIST` returns `(\\Flags) "." "INBOX.Sent"` — the quoted name is what IMAP
    commands need verbatim, including Gmail's `[Gmail]/All Mail`.
    """
    typed, data = conn.list()
    if typed != "OK":
        return []
    found: list[tuple[str, str]] = []
    for raw in data:
        if raw is None:
            continue
        line = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
        match = re.search(r'"([^"]*)"\s*$', line)
        name = match.group(1) if match else line.split()[-1].strip('"')
        found.append((name, name.strip('"')))
    return found


def _special_use(conn: imaplib.IMAP4_SSL) -> dict[str, str]:
    """Folder per RFC 6154 attribute: `{'\\Sent': 'INBOX.Sent', '\\All': ...}`.

    This is the primary folder mechanism, not a nicety. Gmail localises its folder
    names — a Spanish account returns `[Gmail]/Todos`, so a hardcoded
    `[Gmail]/All Mail` matches nothing and the import reports success with zero
    messages. Asking the server removes that whole class of bug.

    Falls back to the plain `LIST` flags (which many servers return without needing
    `RETURN (SPECIAL-USE)`) and never raises on a server that implements neither.
    """
    found: dict[str, str] = {}
    try:
        # RFC 6154's extension form. Unsupported servers reply BAD; imaplib raises
        # IMAP4.error, which is expected and handled below.
        typed, data = conn.list('""', "*", "RETURN (SPECIAL-USE)")
    except Exception:  # noqa: BLE001 - extension is optional
        try:
            typed, data = conn.list()
        except Exception:  # noqa: BLE001
            return {}

    if typed != "OK" or not data:
        return {}

    for raw in data:
        if raw is None:
            continue
        line = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
        flags = re.search(r"\(([^)]*)\)", line)
        name_match = re.search(r'"([^"]*)"\s*$', line)
        if not flags or not name_match:
            continue
        name = name_match.group(1)
        for token in flags.group(1).split():
            upper = token.upper()
            if upper in _WANTED_SPECIAL_USE:
                found.setdefault(upper, name)
    return found


# RFC 6154 attributes worth resolving, most useful first.
_WANTED_SPECIAL_USE = ("\\ALL", "\\SENT", "\\INBOX", "\\JUNK", "\\TRASH", "\\DRAFTS")


def _segments(display: str) -> list[str]:
    """`[Gmail]/All Mail` -> [gmail, all mail]; `INBOX.Sent` -> [inbox, sent]."""
    return [part.strip().lower().strip('"')
            for part in re.split(r"[/.]", display) if part.strip()]


def choose_folders(available: Iterable[tuple[str, str]],
                   special: dict[str, str] | None = None) -> list[str]:
    """Pick which folders hold both sides of a conversation.

    Tier 1 — RFC 6154 special-use: `\\All` if the server has one, else `\\Inbox`
    plus `\\Sent`. This is what makes the choice locale-proof, and it is why Gmail's
    `[Gmail]/Todos` (Spanish) works without a hardcoded string.
    Tier 2 — name hints, for servers that publish no flags (Yandex, GMX, cPanel).
    """
    names = list(available)
    special = special or {}

    if "\\ALL" in special:
        return [special["\\ALL"]]        # already contains inbox and sent

    from_flags = [special[attribute] for attribute in ("\\INBOX", "\\SENT")
                  if attribute in special]
    if len(from_flags) >= 2:
        return from_flags

    picked: list[str] = []
    for raw, display in names:
        segments = _segments(display)
        if not segments:
            continue
        if any(hint in segments for hint in _ALL_MAIL_HINTS):
            return [raw]          # All Mail is the whole mailbox
        if any(hint in segments for hint in _SKIP_HINTS):
            continue
        if any(hint in segments for hint in _INBOX_HINTS + _SENT_HINTS):
            picked.append(raw)

    for attribute in from_flags:                      # flags beat guesses
        if attribute not in picked:
            picked.append(attribute)

    if not picked:
        picked = [raw for raw, display in names
                  if not any(h in _segments(display) for h in _SKIP_HINTS)][:1]
    return picked


def _uidvalidity(conn: imaplib.IMAP4_SSL) -> str:
    """The mailbox's UIDVALIDITY, which `SELECT`/`EXAMINE` returns in its response.

    RFC 3501 §2.3.1.1: `(mailbox name, UIDVALIDITY, UID)` refers to one immutable
    message forever. If the server ever regenerates UIDs it MUST change this value,
    so it belongs in the key — that is what makes a UID-keyed row stable.
    """
    typed, data = conn.response("UIDVALIDITY")
    if typed == "UIDVALIDITY" and data and data[0] is not None:
        value = data[0]
        return value.decode() if isinstance(value, bytes) else str(value)
    return "0"


def choose_folders(available: Iterable[tuple[str, str]],
                   special: dict[str, str] | None = None) -> list[str]:
    """Pick which folders hold both sides of a conversation.

    Tier 1 — RFC 6154 special-use: `\\All` if the server has one, else `\\Sent`
    plus the inbox. This is what makes the choice locale-proof.
    Tier 2 — name hints, for servers that publish no flags (Yandex, GMX, cPanel).
    """
    names = list(available)
    special = special or {}

    if "\\ALL" in special:
        return [special["\\ALL"]]        # already contains inbox and sent

    from_flags: list[str] = []
    for attribute in ("\\INBOX", "\\SENT"):
        if attribute in special:
            from_flags.append(special[attribute])
    if len(from_flags) >= 2:
        return from_flags

    raw_by_display = {display.lower(): raw for raw, display in names}
    for attribute in from_flags:                     # e.g. only \\Sent resolved
        if attribute.lower() not in raw_by_display:
            pass

    picked: list[str] = []
    for raw, display in names:
        segments = _segments(display)
        if not segments:
            continue
        if any(hint in segments for hint in _ALL_MAIL_HINTS):
            return [raw]          # All Mail is the whole mailbox
        if any(hint in segments for hint in _SKIP_HINTS):
            continue
        if any(hint in segments for hint in _INBOX_HINTS + _SENT_HINTS):
            picked.append(raw)

    for attribute in from_flags:                      # flags beat guesses
        if attribute not in picked:
            picked.append(attribute)

    if not picked:
        picked = [raw for raw, display in names
                  if not any(h in _segments(display) for h in _SKIP_HINTS)][:1]
    return picked


def _body_and_attachments(message: EmailMessage) -> tuple[str, list[tuple[str, str | None]]]:
    """Best-effort plain text plus (filename, mime) for each attachment."""
    text_parts: list[str] = []
    html_parts: list[str] = []
    attachments: list[tuple[str, str | None]] = []

    for part in message.walk():
        disposition = (part.get("Content-Disposition") or "").lower()
        filename = part.get_filename()
        if filename or "attachment" in disposition:
            attachments.append((_decode(filename) or "attachment",
                                part.get_content_type()))
            continue
        if part.get_content_maintype() != "text":
            continue
        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        charset = part.get_content_charset() or "utf-8"
        try:
            decoded = payload.decode(charset, errors="replace")
        except LookupError:
            decoded = payload.decode("utf-8", errors="replace")
        if part.get_content_subtype() == "plain":
            text_parts.append(decoded)
        elif part.get_content_subtype() == "html":
            html_parts.append(decoded)

    if text_parts:
        body = "\n".join(text_parts)
    elif html_parts:
        body = "\n".join(_HTML_TAG.sub(" ", chunk) for chunk in html_parts)
    else:
        body = ""
    body = "\n".join(_WS.sub(" ", line).rstrip() for line in body.split("\n")).strip()
    return body, attachments


def _ts(message: EmailMessage) -> datetime | None:
    raw = message.get("Date")
    if not raw:
        return None
    try:
        parsed = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _addresses(raw: str | None) -> list[tuple[str, str]]:
    """[(display_name, address)] from a header. Never raises on malformed mail."""
    if not raw:
        return []
    try:
        return [(name.strip(), addr.strip().lower())
                for name, addr in getaddresses([_decode(raw)]) if addr]
    except (TypeError, ValueError):
        return []


def thread_key(message: EmailMessage, fallback: str) -> str:
    """Gmail/Outlook thread ids when present; otherwise the subject.

    `References` and `In-Reply-To` are standards-defined, unlike a vendor header, so
    they are tried first.
    """
    references = message.get("References") or ""
    first = references.split()[0] if references.split() else ""
    if first:
        return _stable(first)
    in_reply_to = (message.get("In-Reply-To") or "").strip()
    if in_reply_to:
        return _stable(in_reply_to)
    subject = _normalise_subject(message.get("Subject") or "")
    return _stable(subject) if subject else fallback


def _normalise_subject(raw: str) -> str:
    text = _decode(raw)
    while True:
        stripped = re.sub(r"^\s*(re|fw|fwd|aw|sv)\s*:\s*", "", text, flags=re.I)
        if stripped == text:
            break
        text = stripped
    return " ".join(text.split())


def _stable(value: str) -> str:
    return "m_" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def fetch(
    host: str,
    user: str,
    password: str,
    *,
    port: int = 993,
    since: datetime | None = None,
    until: datetime | None = None,
    folders: list[str] | None = None,
    limit: int | None = None,
    timeout: int = 30,
) -> IngestResult:
    """Read both sides of the mailbox over IMAP. Nothing is written or flagged."""
    conn = imaplib.IMAP4_SSL(host, port, ssl_context=ssl.create_default_context(),
                             timeout=timeout)
    conn.login(user, password)
    result = IngestResult(platform=PLATFORM, export_path=f"imap://{host}")

    try:
        available = _folders(conn)
        special = _special_use(conn)
        if special:
            result.warnings.append(
                "special-use flags: " + ", ".join(f"{k}={v}" for k, v in special.items()))
        selected = folders or choose_folders(available, special)
        if not selected:
            result.warnings.append(f"no readable folders on {host}")
            return result
        result.warnings.append("folders read: " + ", ".join(selected))

        seen_keys: set[str] = set()
        chats: dict[str, Chat] = {}

        for folder in selected:
            # EXAMINE = read-only: SELECT would clear the user's unread flags.
            typed, _ = conn.select(f'"{folder}"', readonly=True)
            if typed != "OK":
                result.note_skip(f"folder unreadable ({folder})")
                continue
            uidvalidity = _uidvalidity(conn)

            criteria = _criteria(since, until)
            typed, data = conn.uid("SEARCH", None, *criteria)
            if typed != "OK":
                result.note_skip(f"search failed ({folder})")
                continue
            uids = (data[0] or b"").split()
            if limit:
                uids = uids[-limit:]

            for uid in uids:
                typed, payload = conn.uid("FETCH", uid, "(BODY.PEEK[])")
                if typed != "OK" or not payload or not isinstance(payload[0], tuple):
                    result.note_skip("fetch failed")
                    continue
                raw = payload[0][1]
                _parse_raw(raw, folder, uid.decode(), uidvalidity, result,
                           seen_keys, chats,
                           special_use=special, account_address=user)

        result.chats.extend(chats.values())
        # Never report success when nothing matched: a localised or unusual folder
        # layout must be visible, not a silent zero (§10 research).
        if not result.messages:
            result.warnings.append(
                "no messages matched in " + ", ".join(selected) +
                "; check the folder names or widen the date window")
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001 - closing a broken socket must not mask the read
            pass
        conn.logout()
    return result


def _criteria(since: datetime | None, until: datetime | None) -> list[str]:
    """IMAP SEARCH bounds. `SINCE` is inclusive and date-granular, which is why the
    exact datetimes are re-checked after parsing."""
    parts: list[str] = []
    parts += ["SINCE", since.strftime("%d-%b-%Y")] if since else []
    parts += ["BEFORE", until.strftime("%d-%b-%Y")] if until else []
    return parts or ["ALL"]


def folder_is_sent(folder: str, special_use: dict[str, str] | None = None) -> bool:
    """Was this mail read out of a sent-mail folder?

    Tier 1 is the RFC 6154 `\\Sent` flag, which survives localised folder names.
    Hostinger publishes no flags at all (verified 2026-11-14), so tier 2 is the
    name, compared **per path segment** — `INBOX.Sent` splits to `[inbox, sent]` —
    because comparing whole names missed every sent message.
    """
    if special_use:
        sent_folder = special_use.get("\\Sent")
        if sent_folder and folder == sent_folder:
            return True
    return "sent" in _segments(folder)


def _parse_raw(
    raw: bytes,
    folder: str,
    uid: str,
    uidvalidity: str,
    result: IngestResult,
    seen_keys: set[str],
    chats: dict[str, Chat],
    *,
    special_use: dict[str, str] | None = None,
    account_address: str = "",
) -> None:
    message = email.message_from_bytes(raw)
    ts = _ts(message)
    if ts is None:
        result.note_skip("no parseable Date")
        return

    message_id = (message.get("Message-ID") or "").strip()
    if not message_id:
        # Hostinger sends 134 of 165 messages with no Message-ID (measured
        # 2026-11-14). RFC 3501 gives a stronger standard alternative: the tuple
        # (mailbox, UIDVALIDITY, UID) is immutable for the life of the message.
        result.note_kind("missing message-id")
        message_id = f"uid:{uidvalidity}:{uid}"

    thread = thread_key(message, _stable(folder))
    sender_pairs = _addresses(message.get("From"))
    sender_name, sender_addr = sender_pairs[0] if sender_pairs else ("", "")
    recipients = _addresses(message.get("To")) + _addresses(message.get("Cc"))

    body, attachments = _body_and_attachments(message)
    subject = _normalise_subject(message.get("Subject") or "")

    key = f"{PLATFORM}:{thread}:{message_id}"
    if key in seen_keys:
        # All Mail plus a specific folder can return the same mail twice.
        result.note_skip("duplicate within run")
        return
    seen_keys.add(key)

    raw_kind = "attachment" if attachments and not body else (
        "text" if body else "empty")
    if raw_kind != "text":
        result.note_kind(raw_kind)

    from ..schema import AttachmentRef

    # Ownership is structural, not guessed from a name. A message sitting in a
    # `\Sent`-class folder was sent by the account, and mail whose From address is
    # the account's own address is also ours (some servers file it in INBOX).
    # Matching display names like `David` vs `Dave` would be an inference; this is
    # a fact (§3.1: don't guess when the data says).
    is_self = (folder_is_sent(folder, special_use)
               or (sender_addr and sender_addr.lower() == account_address.lower()))

    result.messages.append(Message(
        key=key, platform=PLATFORM, chat_id=thread,
        message_id=message_id, ts_utc=ts,
        sender_name=sender_name or sender_addr,
        sender_id=sender_addr or None,
        body=body, reply_to=None,
        has_attachments=bool(attachments),
        is_self=is_self,
        raw_kind=raw_kind,
        saved_from=subject or None,
    ))
    for name, mime in attachments:
        result.attachments.append(AttachmentRef(
            platform=PLATFORM, chat_id=thread, message_id=message_id,
            path=name, mime=mime, size=None))

    if thread not in chats:
        others = [addr for _, addr in recipients]
        chats[thread] = Chat(
            platform=PLATFORM, chat_id=thread,
            title=subject or ", ".join(others) or thread,
            kind="group_chat" if len(others) > 1 else "personal_chat",
            is_group=len(others) > 1,
            participant_names=tuple(sorted(
                {sender_name or sender_addr} | {n or a for n, a in recipients} - {""})),
        )


def parse(
    export_path: str | Path,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
    self_id: str | None = None,
    include_service: bool = True,
    profile_dir: str | Path | None = None,
    limit: int | None = None,
    folders: list[str] | None = None,
) -> IngestResult:
    """Adapter entry point, so `ingest.ingest()` can treat email like the others.

    Two shapes reach here, and the path decides which:

    * **A saved mailbox** — a folder of `.eml` files, or one `.eml`. Read from disk,
      no network. This is what `discover()` hands over when the spool holds a
      `sample_writer` email export.
    * **A slot name** (`"email"` or `"gmail"`) — resolved from `.env` by
      `account_from_slot` and read over IMAP. Both slots land on the same `email`
      platform; the slot only decides which four `.env` keys hold the credentials.

    The test is `Path.exists()`, not a suffix check: a slot name is not a path, so it
    cannot exist on disk, and a real folder always does.
    """
    path = Path(str(export_path))
    if path.exists() and (path.is_dir() or path.suffix.lower() == _EML_SUFFIX):
        return parse_eml(path, since=since, until=until, limit=limit)

    account = account_from_slot(str(export_path))
    return fetch(
        account["host"], account["user"], account["password"],
        port=int(account.get("port", 993)),
        since=since, until=until, limit=limit, folders=folders,
    )


def parse_eml(
    path: str | Path,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int | None = None,
) -> IngestResult:
    """Read a saved mailbox: every `.eml` under `path`, as one platform `email`.

    **The owner is inferred by breadth, not volume.** A saved mailbox states no
    account, so `is_self` has nothing structural to read — unlike IMAP, where a
    `\\Sent` folder says it outright. The rule is the one `messenger._resolve_owner`
    already uses: the address that appears in the most *distinct messages* is the
    account, because a mailing list can outnumber the owner in raw rows but never in
    breadth. The inference is reported in `warnings`, never silent.

    `folder` is the containing directory's name and `uid` is the file stem, so a
    message with no `Message-ID` still gets a stable `uid:<uidvalidity>:<uid>` key —
    the same fallback IMAP uses, and unique per file.
    """
    root = Path(path)
    files = sorted(
        [root] if root.is_file() else
        [entry for entry in root.rglob(f"*{_EML_SUFFIX}") if entry.is_file()]
    )
    result = IngestResult(platform=PLATFORM, export_path=str(root))
    if not files:
        result.warnings.append(f"no {_EML_SUFFIX} files under {root}")
        return result

    raws: list[tuple[Path, bytes]] = []
    for entry in files:
        try:
            raws.append((entry, entry.read_bytes()))
        except OSError as exc:
            result.note_skip(f"unreadable file ({type(exc).__name__})")

    # Window first, so the owner vote is not skewed by mail the caller excluded.
    kept: list[tuple[Path, bytes]] = []
    for entry, raw in raws:
        ts = _ts(email.message_from_bytes(raw))
        if ts is not None and since is not None and ts < since:
            result.note_skip("before window")
            continue
        if ts is not None and until is not None and ts > until:
            result.note_skip("after window")
            continue
        kept.append((entry, raw))
    if limit:
        kept = kept[-limit:]

    breadth: dict[str, int] = {}
    for _entry, raw in kept:
        pairs = _addresses(email.message_from_bytes(raw).get("From"))
        if pairs and pairs[0][1]:
            breadth[pairs[0][1]] = breadth.get(pairs[0][1], 0) + 1
    account = max(breadth, key=breadth.get) if breadth else ""
    if account:
        result.warnings.append(
            f"owner inferred as {account!r} (sender of {breadth[account]} of "
            f"{len(kept)} messages); a saved mailbox states no account")

    seen_keys: set[str] = set()
    chats: dict[str, Chat] = {}
    for entry, raw in kept:
        _parse_raw(raw, entry.parent.name, entry.stem, "eml", result,
                   seen_keys, chats, account_address=account)

    result.chats.extend(chats.values())
    if not result.messages:
        result.warnings.append(
            f"no messages matched in {root}; check the date window")
    return result


# **One mailbox, four keys, no provider table.**
#
# There used to be an `ENV_ACCOUNTS` table of 11 providers, each with a hardcoded host
# and its own pair of `.env` key names. It was a convenience that became a trap: a
# mailbox on a domain nobody listed (`w57th.agency`) resolved to the pseudo-provider
# `custom`, which `account_from_env` then refused — and the refusal was printed to
# stderr and swallowed, so the ingest reported success with zero messages.
#
# What replaces it is one block. Gmail is not a special case: it is an address whose
# host happens to be `imap.gmail.com`. Nothing in the adapter branches on a provider
# name — folder selection is RFC 6154 special-use flags first and name hints second, so
# Gmail and a cPanel mailbox take the same code path.
#
# **One mailbox at a time, and that is a store constraint, not a UI choice.** The key is
# `email:<chat_id>:<message_id>` and `chat_id` carries no mailbox, so two mailboxes would
# share a namespace, share the delta watermark, and silently merge on any `Message-ID`
# both happen to hold. Switching mailboxes therefore wipes the `email` rows first — see
# `app/routers/ingest.py::_run_ingest`.
IMAP_KEYS: tuple[str, str, str, str] = (
    "IMAP_EMAIL", "IMAP_PASSWORD", "IMAP_HOST", "IMAP_PORT",
)


def slot_keys(slot: str | None = None) -> tuple[str, str, str, str]:
    """The four `.env` keys. There is one mailbox, so `slot` is accepted and ignored.

    Kept as a parameter so callers that still pass `"email"` do not break; it is not a
    choice any more.
    """
    return IMAP_KEYS


def account_from_slot(slot: str | None = None, *, environ: dict[str, str] | None = None) -> dict[str, str]:
    """Resolve the mailbox to host, user, password, port.

    Secrets are read from the environment or the repo `.env` (gitignored), never from
    code and never logged. A missing key raises with the *name* of the key, not its
    value.
    """
    import os

    user_var, pass_var, host_var, port_var = slot_keys(slot)

    env = dict(_dotenv(environ) if environ is None else environ)
    env.update(os.environ)

    user = (env.get(user_var) or "").strip()
    password = env.get(pass_var) or ""
    host = (env.get(host_var) or "").strip()
    port = (env.get(port_var) or "993").strip()

    missing = [
        name for name, value in (
            (user_var, user), (pass_var, password), (host_var, host),
        ) if not value
    ]
    if missing:
        raise ValueError(
            f"no mailbox is configured: {', '.join(missing)} not set. "
            "Enter the four values in the Ingest modal."
        )

    # Gmail and several others display app passwords with spaces that are not part of
    # the secret. Stripping them is harmless for a password that has none.
    password = password.replace(" ", "")

    return {"host": host, "user": user, "password": password, "port": str(int(port))}


def account_from_parts(
    host: str,
    user: str,
    password: str,
    *,
    port: int = 993,
) -> dict[str, str]:
    """An account for any IMAP server, with no provider table involved.

    This is the escape hatch that keeps the adapter from being hung up on a vendor
    name: if a server speaks IMAP over TLS, these four values are all it takes.
    """
    if not host or not user or not password:
        raise ValueError("host, user and password are all required for a custom IMAP account")
    return {
        "host": host.strip(),
        "user": user.strip(),
        "password": password,
        "port": str(int(port)),
    }


def _dotenv(environ: dict[str, str] | None = None) -> dict[str, str]:
    """Minimal `.env` reader. No dependency, no interpolation, no inheritance."""
    path = Path(__file__).resolve().parent.parent.parent / ".env"
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'").strip()
    return values


def detect(path: Path) -> bool:
    """A folder of `.eml` files, or one `.eml`.

    A live mailbox is not a file and is never discovered from the spool — that is
    still true, and it is why this used to return `False` unconditionally. But a
    **saved** mailbox is a folder of RFC 5322 files, which is exactly what a
    `sample_writer` email export and a Thunderbird "Save As" both produce. Those
    are discoverable, and refusing them meant the email leg could only ever be
    reached from a test.

    Detection is by content shape, never by the folder's name: one `.eml` is
    enough, and a folder holding none is not email.

    **Recursive on purpose.** `parse_eml` reads with `rglob`, and the folders that
    actually hold saved mail nest one level (`INBOX/Sent/`, `<thread>/NNN.eml`).
    A non-recursive `iterdir()` here reported `False` for a tree the parser could read
    perfectly well, so the export was filed as unrecognised and never ingested —
    exactly the shape `sample_writer` writes.
    """
    if path.is_dir():
        try:
            return any(entry.is_file() and entry.suffix.lower() == _EML_SUFFIX
                       for entry in path.rglob(f"*{_EML_SUFFIX}"))
        except OSError:
            return False
    return path.suffix.lower() == _EML_SUFFIX
