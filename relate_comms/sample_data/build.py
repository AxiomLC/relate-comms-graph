"""Generate sample downloads, and scrub real exports into test fixtures.

WHY THIS SHIPS
--------------
A developer will not point this app at their own comms until they have seen it work
on data they generated themselves. So this is a product feature, not a dev helper:
clone, run, see a graph, then decide.

TWO DESTINATIONS, DELIBERATELY SEPARATE
---------------------------------------
  sample_data/generated/     default. gitignored, reproducible, read by
                             `ingest --source sample`.
  tests/fixtures/            opt-in via --dest fixtures. Committed and PINNED.

They must not be the same folder. If a parser change altered the fixtures, a
failing test could be "fixed" by regenerating instead of by fixing the parser.
Fixtures change only when someone deliberately asks.

SAMPLE SHAPES
-------------
Two payloads, because Telegram has two parse paths and one payload cannot prove both:

  telegram_bulk/result.json    Result wrapper -> chats.list[]
  telegram_single/result.json  bare Chat object -> messages[]

Both are `result.json` inside a folder, matching the shape of a real download.

SCRUBBING CAVEAT: names appear in message BODIES as well as in `from`. The first
version of this script only rewrote the structured fields and leaked a real name
through a message body. Two passes fix it: collect every real name first, then
replace those names inside every free-text field.

Run:
    python -m relate_comms sample build                 # -> sample_data/generated/
    python -m relate_comms sample build --dest fixtures # -> tests/fixtures/
    python -m relate_comms sample build --check         # ...and parse them back
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from pathlib import Path
from typing import Any

PACKAGE = Path(__file__).resolve().parent          # relate_comms/sample_data
ROOT = PACKAGE.parent.parent                       # repo root

GENERATED = PACKAGE / "generated"
FIXTURES = ROOT / "tests" / "fixtures"

# Real exports live in `spool/real/`, gitignored. Used only as shape references when a
# developer happens to have them; the minimal fallback works without them.
from ..paths import real_dir  # noqa: E402

# Generated demo data lands in the same queue shape as real data (§6).
from ..paths import sample_dir  # noqa: E402

SAMPLE = sample_dir()

_SINGLE_CANDIDATES = [
    real_dir() / "ChatExport_2026-11-14 (1)" / "result.json",
    real_dir() / "result.json",
]
_BULK_CANDIDATES = [
    real_dir() / "DataExport_2026-11-14" / "result.json",
]


def _first_existing(paths):
    for path in paths:
        if path.exists():
            return path
    return None


SINGLE_EXPORT = _first_existing(_SINGLE_CANDIDATES)
BULK_EXPORT = _first_existing(_BULK_CANDIDATES)

PERSONS = ["Person A", "Person B", "Person C", "Person D", "Person E", "Person F"]
LINES = [
    "Sample sentence one.",
    "A second line for the dummy.",
    "Short reply.",
    "This row exists to keep the shape.",
    "Placeholder body text.",
    "Another dummy message.",
]

# Fields that hold a person's name, on a message.
_NAME_FIELDS = ("from", "actor", "forwarded_from", "saved_from", "inviter")
# Fields that hold a stable id, on a message.
_ID_FIELDS = ("from_id", "actor_id", "forwarded_from_id")


class Scrubber:
    """Replace identities consistently across one export."""

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self.names: dict[str, str] = {}
        self.ids: dict[str, str] = {}

    def name(self, original: str | None) -> str:
        if not original:
            return ""
        if original not in self.names:
            self.names[original] = PERSONS[len(self.names) % len(PERSONS)]
        return self.names[original]

    def ident(self, original: str | None) -> str:
        if not original:
            return ""
        if original not in self.ids:
            prefix = "".join(ch for ch in original if ch.isalpha()) or "user"
            self.ids[original] = f"{prefix}{900000 + len(self.ids) * 7}"
        return self.ids[original]

    def scrub_text(self, value: str) -> str:
        """Replace every known real name appearing inside free text."""
        for real, fake in sorted(self.names.items(), key=lambda kv: -len(kv[0])):
            if real and real in value:
                value = value.replace(real, fake)
        return value

    def body(self) -> str:
        return self.scrub_text(self.rng.choice(LINES))


def _chats_of(document: dict[str, Any]) -> list[dict[str, Any]]:
    """Chats in this document, for either export shape."""
    if "messages" in document and "chats" not in document:
        return [document]
    found: list[dict[str, Any]] = []
    for container in ("chats", "left_chats"):
        found.extend((document.get(container) or {}).get("list") or [])
    return found


def _collect_names(document: dict[str, Any], scrubber: Scrubber) -> None:
    """Pass 1: learn every real name before any text is rewritten."""
    for chat in _chats_of(document):
        for msg in chat.get("messages") or []:
            for field in _NAME_FIELDS:
                if msg.get(field):
                    scrubber.name(msg[field])
            for member in msg.get("members") or []:
                scrubber.name(member)
    for contact in (document.get("contacts") or {}).get("list") or []:
        for field in ("first_name", "last_name"):
            if contact.get(field):
                scrubber.name(contact[field])
    personal = document.get("personal_information")
    if isinstance(personal, dict):
        for field in ("first_name", "last_name"):
            if personal.get(field):
                scrubber.name(personal[field])


def _scrub_message(msg: dict[str, Any], scrubber: Scrubber) -> None:
    for field in _NAME_FIELDS:
        if field in msg:
            msg[field] = scrubber.name(msg[field])
    for field in _ID_FIELDS:
        if field in msg:
            msg[field] = scrubber.ident(msg[field])

    text = msg.get("text")
    if isinstance(text, str) and text:
        msg["text"] = scrubber.body()
    elif isinstance(text, list):
        rewritten: list[Any] = []
        for item in text:
            if isinstance(item, str):
                rewritten.append(scrubber.body() if item else item)
            elif isinstance(item, dict):
                if item.get("type") == "plain":
                    rewritten.append(scrubber.body())
                else:
                    rewritten.append({**item, "text": scrubber.body()})
            else:
                rewritten.append(item)
        msg["text"] = rewritten

    for entity in msg.get("text_entities") or []:
        # `plain` entities carry the WHOLE message body verbatim. The first version
        # of this script skipped them as "harmless" and leaked the body text of
        # every media row. Scrub every entity type, `plain` included.
        if isinstance(entity, dict) and "text" in entity:
            entity["text"] = scrubber.body()

    if msg.get("title"):
        msg["title"] = "Dummy title"
    if msg.get("members"):
        msg["members"] = [scrubber.name(member) for member in msg["members"]]


def scrub(document: dict[str, Any], scrubber: Scrubber) -> dict[str, Any]:
    _collect_names(document, scrubber)

    for chat in _chats_of(document):
        chat["name"] = "Dummy chat"
        if chat.get("id") is not None:
            # sha256, not hash(): str hashing is randomised per process, which
            # would make the committed fixture differ on every regeneration.
            digest = hashlib.sha256(str(chat["id"]).encode()).hexdigest()[:9]
            chat["id"] = 100000000 + int(digest, 16) % 900000000
        for msg in chat.get("messages") or []:
            _scrub_message(msg, scrubber)

    for contact in (document.get("contacts") or {}).get("list") or []:
        for field in ("first_name", "last_name"):
            if contact.get(field):
                contact[field] = scrubber.name(contact[field]).split()[-1]
        if contact.get("phone_number"):
            contact["phone_number"] = "+00 000 000 0000"

    personal = document.get("personal_information")
    if isinstance(personal, dict):
        for field in ("first_name", "last_name"):
            if personal.get(field):
                personal[field] = scrubber.name(personal[field]).split()[-1]
        if personal.get("phone_number"):
            personal["phone_number"] = "+00 000 000 0000"

    return document


def minimal() -> dict[str, Any]:
    """Fallback when no real export is on disk: every shape we know, hand-written."""
    return {
        "name": "Dummy chat",
        "type": "personal_chat",
        "id": 100000001,
        "messages": [
            {"id": 1, "type": "service", "date": "2024-01-01T09:00:00",
             "actor": "Person A", "actor_id": "user900000", "action": "create_group",
             "title": "Dummy chat", "members": ["Person A", "Person B"], "text": ""},
            {"id": 2, "type": "message", "date": "2024-01-01T09:01:00",
             "date_unixtime": "1704099660", "from": "Person A", "from_id": "user900000",
             "text": "Sample sentence one.",
             "text_entities": [{"type": "plain", "text": "Sample sentence one."}]},
            {"id": 3, "type": "message", "date": "2024-01-01T09:02:00",
             "date_unixtime": "1704099720", "from": "Person B", "from_id": "user900007",
             "text": ["Look: ", {"type": "bold", "text": "bold"}, " end."],
             "text_entities": [{"type": "bold", "text": "bold"}]},
            {"id": 4, "type": "message", "date": "2024-01-01T09:03:00",
             "date_unixtime": "1704099780", "from": "Person A", "from_id": "user900000",
             "file": "voice_messages/audio_1@01-01-2024_09-03-00.ogg",
             "media_type": "voice_message", "mime_type": "audio/ogg",
             "duration_seconds": 2, "text": ""},
            {"id": 5, "type": "message", "date": "2024-01-01T09:04:00",
             "date_unixtime": "1704099840", "from": "Person B", "from_id": "user900007",
             "reply_to_message_id": 3, "text": "Short reply."},
        ],
    }


def build(source: Path | None, seed: int = 20261114) -> tuple[dict[str, Any], str]:
    if source and source.exists():
        document = json.loads(source.read_text(encoding="utf-8"))
        return scrub(document, Scrubber(random.Random(seed))), str(source)
    return minimal(), "built-in minimal"


def shrink(document: dict[str, Any], max_chats: int = 3) -> dict[str, Any]:
    """Keep a few shape-rich chats so the fixture stays small but still teaches.

    Rank by diversity of message kinds, not volume: three odd rows teach a parser
    more than a hundred plain texts. Contacts/sessions are dropped because they
    dominate bytes and say nothing about the message schema.
    """
    if "messages" in document and "chats" not in document:
        return document

    all_chats = (document.get("chats") or {}).get("list") or []
    if not all_chats:
        return document

    def kinds(chat: dict[str, Any]) -> set[str]:
        return {
            str(m.get("action") or m.get("media_type") or m.get("type"))
            for m in chat.get("messages") or []
        }

    ordered = sorted(all_chats, key=lambda c: (len(kinds(c)), len(c.get("messages") or [])),
                     reverse=True)

    kept: list[dict[str, Any]] = []
    covered: set[str] = set()
    for chat in ordered:
        chat_kinds = kinds(chat)
        if chat_kinds - covered or len(kept) < max_chats:
            kept.append(chat)
            covered |= chat_kinds
        if len(kept) >= max_chats:
            break

    document = dict(document)
    document["chats"] = {"about": "Dummy export", "list": kept}
    document["left_chats"] = {"about": "Dummy export", "list": []}
    if isinstance(document.get("contacts"), dict):
        document["contacts"] = {
            "about": "Dummy export",
            "list": (document["contacts"].get("list") or [])[:2],
        }
    for heavy in ("frequent_contacts", "sessions", "web_sessions", "other_data",
                  "stories", "profile_pictures"):
        document.pop(heavy, None)
    return document


def _write(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dest", choices=("generated", "fixtures"), default="generated",
                        help="generated/ is the shipped sample (default); "
                             "fixtures/ are pinned test inputs and must not move casually")
    parser.add_argument("--check", action="store_true",
                        help="after writing, parse both payloads back through the adapter")
    parser.add_argument("--seed", type=int, default=20261114)
    args = parser.parse_args(argv)

    target_root = SAMPLE if args.dest == "generated" else FIXTURES

    single, model_single = build(SINGLE_EXPORT, args.seed)
    bulk, model_bulk = build(BULK_EXPORT, args.seed)
    bulk = shrink(bulk)

    # `spool/sample/telegram/` mirrors `spool/real/telegram/`, so the two queues have
    # the same shape and `--source sample` exercises the same discovery code path.
    platform_root = target_root / "telegram" if args.dest == "generated" else target_root
    single_path = platform_root / "telegram_single" / "result.json"
    bulk_path = platform_root / "telegram_bulk" / "result.json"
    _write(single_path, single)
    _write(bulk_path, bulk)

    print(f"dest:   {target_root}")
    print(f"single: {model_single} -> {len(single['messages'])} msgs "
          f"({single_path.stat().st_size:,} bytes)")
    bulk_rows = sum(len(c.get("messages") or []) for c in
                    (bulk.get("chats") or {}).get("list") or [bulk])
    print(f"bulk:   {model_bulk} -> {bulk_rows} msgs "
          f"({bulk_path.stat().st_size:,} bytes) ")

    if args.check:
        from ..adapters import telegram

        failed = False
        for name, path in (("single", single_path), ("bulk", bulk_path)):
            result = telegram.parse(path, self_id="user900000")
            print(f"  {name}: {len(result.messages)} parsed, "
                  f"{len(result.attachments)} attachments")
            if not result.messages:
                print(f"  FAIL: {name} produced no rows", file=sys.stderr)
                failed = True
        if failed:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
