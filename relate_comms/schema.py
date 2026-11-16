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


@dataclass
class Person:
    """One human, across every platform (§3.1).

    A Person is not created by an adapter — adapters produce `Identity` evidence. Only
    `resolution` may mint a Person, which is what keeps a mis-merge from being written
    by a parser.
    """

    key: str
    display_name: str
    first_seen_utc: datetime
    last_seen_utc: datetime

    def __post_init__(self) -> None:
        for field_name in ("first_seen_utc", "last_seen_utc"):
            if getattr(self, field_name).tzinfo is None:
                raise ValueError(f"{self.key}: {field_name} must be timezone-aware")


@dataclass(frozen=True)
class Identity:
    """One account on one platform, and the evidence that ties it to a Person.

    `confidence` is 1.0 for an exact key (phone in E.164, lowercase email, platform
    user id) and 0.4-0.8 for a name match. Never 1.0 for a guess — §3.1's
    "a wrong guess must look like honest uncertainty".
    """

    key: str
    platform: str
    handle: str
    phone_e164: str | None = None
    email: str | None = None
    display_name: str = ""
    person_key: str | None = None
    confidence: float = 0.0
    matched_by: str = ""       # "phone" | "email" | "platform_id" | "name"

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"{self.key}: confidence must be within 0..1")


@dataclass
class IngestResult:
    """What one file yielded. Counts exist so nothing is silently skipped."""

    platform: str
    source: str
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
