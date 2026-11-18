"""The canonical record every adapter produces and every writer consumes.

One shape, six platforms. If a platform cannot fill a field, the field is empty —
the row is never dropped. Media-only messages, service events and polls all become
rows; `raw_kind` is how "what was this actually" survives the normalisation.

Two rules that are not negotiable (TECHREADME.md §5):

1. `key` is built once, from stable parts, and never mutated. It is what makes
   re-ingest idempotent — the daily job re-reads the same archive and must not
   create a second copy of a message it already has.
2. `ts_utc` is always timezone-aware UTC. Telegram and WhatsApp export local time
   with no offset; converting at parse time is the only place the information is
   still available.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone


def make_key(platform: str, chat_id: str, message_id: str) -> str:
    """`platform:chat_id:message_id` — the only stable identity a message has.

    Message ids are only unique *within* a chat, so neither part can be dropped.
    """
    return f"{platform}:{chat_id}:{message_id}"


@dataclass(frozen=True)
class Message:
    key: str
    platform: str
    chat_id: str
    message_id: str
    ts_utc: datetime
    sender_name: str
    sender_id: str | None
    body: str
    reply_to: str | None
    has_attachments: bool
    is_self: bool
    raw_kind: str
    # Provenance edges. Kept on the record rather than dropped, because a forward
    # says something a plain message does not (who introduced you).
    forwarded_from: str | None = None
    saved_from: str | None = None

    def __post_init__(self) -> None:
        if self.ts_utc.tzinfo is None:
            raise ValueError(
                f"{self.key}: ts_utc must be timezone-aware UTC; "
                "a naive datetime means the offset was lost at parse time"
            )
        expected = make_key(self.platform, self.chat_id, self.message_id)
        if self.key != expected:
            raise ValueError(f"key {self.key!r} does not match {expected!r}")


@dataclass
class AttachmentRef:
    """Pre-scrub reference to a file the export mentions.

    `path` is the archive-relative path as written by the platform. `sha256` is
    only filled when we actually read bytes; text-only exports never do.
    """

    platform: str
    chat_id: str
    message_id: str
    path: str
    mime: str | None = None
    size: int | None = None
    sha256: str | None = None

    @property
    def key(self) -> str:
        digest = hashlib.sha256(self.path.encode("utf-8")).hexdigest()[:16]
        return f"{self.platform}:{self.chat_id}:{self.message_id}:{digest}"


@dataclass
class Chat:
    platform: str
    chat_id: str
    title: str
    kind: str          # platform's own chat type, verbatim
    is_group: bool
    participant_names: tuple[str, ...] = ()


# `Person` and `Identity` were removed deliberately. `Person` is a **future extraction
# node type** — a person named in a message body, alongside `Place`, `Organization` and
# `Thing` — and is never the Owner. The Owner is the person using the app, resolved per
# platform and frozen in `store/profile/identity.json`; no leg may emit a node for them.
# The old `Person`/`Identity` dataclasses existed only to carry the output of an
# identity resolver whose result was discarded, and they encoded the wrong term.


@dataclass
class IngestResult:
    """What one file yielded. Counts exist so nothing is silently skipped."""

    platform: str
    # The file or directory this result was parsed from. NOT the platform (that is
    # `platform`) and NOT the user's original download (that is theirs, untouched).
    # `export_path` is the copy inside the spool, or the IMAP URL for live email.
    export_path: str
    chats: list[Chat] = field(default_factory=list)
    messages: list[Message] = field(default_factory=list)
    attachments: list[AttachmentRef] = field(default_factory=list)
    # raw_kind -> count, for every row that is not a plain text message.
    # Build notes §3.2: counted and reported, never dropped.
    unknown_kinds: dict[str, int] = field(default_factory=dict)
    # Rows skipped on purpose (e.g. outside the requested window), with a reason.
    skipped: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def note_kind(self, kind: str) -> None:
        self.unknown_kinds[kind] = self.unknown_kinds.get(kind, 0) + 1

    def note_skip(self, reason: str) -> None:
        self.skipped[reason] = self.skipped.get(reason, 0) + 1


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def to_utc_string(dt: datetime) -> str:
    """Store as ISO-8601 with `Z`. Relate keeps strings; sortable and unambiguous."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
