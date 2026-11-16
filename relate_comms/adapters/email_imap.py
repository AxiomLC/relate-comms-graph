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

    `export_path` is a provider name here (`"gmail"`, `"zoho"`, …), resolved from
    `.env` by `account_from_env`. It is never a file path — email is the one platform
    with no export file to read. For a provider not in the table, call `fetch()`
    directly with `account_from_parts()`.
    """
    account = account_from_env(str(export_path))
    return fetch(
        account["host"], account["user"], account["password"],
        port=int(account.get("port", 993)),
        since=since, until=until, limit=limit, folders=folders,
    )


# Known IMAP providers. This is a CONVENIENCE TABLE, not a whitelist: a provider
# that is not here works by passing host/port/user/password directly. Nothing in the
# adapter branches on a provider name — folder selection is by RFC 6154 special-use
# flags first and name hints second, so a new provider needs no code at all.
#
# `host` may be a template: `{domain}` is filled from the mailbox address, which is
# how the cPanel-style providers work (the mail host is the domain itself).
ENV_ACCOUNTS: dict[str, tuple[str, str, str, int]] = {
    "gmail": ("imap.gmail.com", "GOOGLE_EMAIL", "GOOGLE_APP_PASSWORD", 993),
    "hostinger": ("imap.hostinger.com", "HOSTINGER_EMAIL", "HOSTINGER_PASSWORD", 993),
    "outlook": ("outlook.office365.com", "OUTLOOK_EMAIL", "OUTLOOK_PASSWORD", 993),
    "yahoo": ("imap.mail.yahoo.com", "YAHOO_EMAIL", "YAHOO_APP_PASSWORD", 993),
    "icloud": ("imap.mail.me.com", "ICLOUD_EMAIL", "ICLOUD_APP_PASSWORD", 993),
    "zoho": ("imap.zoho.com", "ZOHO_EMAIL", "ZOHO_PASSWORD", 993),
    "fastmail": ("imap.fastmail.com", "FASTMAIL_EMAIL", "FASTMAIL_APP_PASSWORD", 993),
    "gmx": ("imap.gmx.com", "GMX_EMAIL", "GMX_PASSWORD", 993),
    "yandex": ("imap.yandex.com", "YANDEX_EMAIL", "YANDEX_APP_PASSWORD", 993),
    "aol": ("imap.aol.com", "AOL_EMAIL", "AOL_APP_PASSWORD", 993),
    # cPanel / generic hosting: the mail host is the domain in the address.
    "cpanel": ("mail.{domain}", "CPANEL_EMAIL", "CPANEL_PASSWORD", 993),
}

# Providers that display app passwords with spaces that are not part of the secret.
_SPACED_APP_PASSWORDS = {"gmail", "yahoo", "aol", "icloud"}

# Hostinger's mailbox address is not in `.env` yet; the skill records this one.
_FALLBACK_USERS = {"hostinger": "dev@w57th.agency"}


def account_from_env(name: str, *, environ: dict[str, str] | None = None) -> dict[str, str]:
    """Resolve a provider name to host, user, password, port.

    Secrets are read from the environment or the repo `.env` (gitignored), never from
    code and never logged. A missing key raises with the *name* of the key, not its
    value.

    A provider in `ENV_ACCOUNTS` is a shortcut for "look these keys up in `.env`".
    Anything else must be supplied explicitly — see `account_from_parts()`.
    """
    import os

    key = name.strip().lower()
    if key not in ENV_ACCOUNTS:
        raise ValueError(
            f"unknown email provider {name!r}; known: {', '.join(sorted(ENV_ACCOUNTS))}. "
            "For any other IMAP server, pass host/port/user/password directly."
        )
    host, user_var, pass_var, port = ENV_ACCOUNTS[key]

    env = dict(_dotenv(environ) if environ is None else environ)
    env.update(os.environ)

    user = env.get(user_var) or _FALLBACK_USERS.get(key)
    password = env.get(pass_var)
    if not user:
        raise ValueError(f"{user_var} is not set (needed to log in to {key})")
    if not password:
        raise ValueError(f"{pass_var} is not set (needed to log in to {key})")
    if key in _SPACED_APP_PASSWORDS:
        # These providers display app passwords with spaces; the spaces are not part
        # of the secret.
        password = password.replace(" ", "")

    # `mail.{domain}` — the cPanel shape, where the host is the mailbox's own domain.
    if "{domain}" in host:
        domain = user.rsplit("@", 1)[-1] if "@" in user else ""
        if not domain:
            raise ValueError(
                f"{key} needs a full mailbox address to derive its host; got {user!r}"
            )
        host = host.replace("{domain}", domain)

    return {"host": host, "user": user, "password": password, "port": str(port)}


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
    """Email is not a file. It is never auto-discovered from the spool."""
    return False
