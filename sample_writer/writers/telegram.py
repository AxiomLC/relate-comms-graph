"""Telegram. Two shapes, matching the real exports in `in/` exactly.

  bulk   DataExport: {about, contacts, frequent_contacts, chats:{about,list}, left_chats}
  single ChatExport: {name, type, id, messages[]}

Service rows (`type: "service"`) are what make §6 (zero-message) and §7 (service rows in
a live thread) expressible: §6 is a chat whose ONLY rows are service rows, and the
adapter then emits no `Chat` for it and counts `skipped`.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from random import Random

from .. import config
from ..plan import Plan, Thread
from ..world import World

KIND = "telegram"
TG_ABOUT = (
    "Here is the data you requested. Remember: unlike other apps, Telegram never uses "
    "your private data to target ads."
)


def _stable_id(text: str, floor: int = 100000) -> int:
    return floor + (abs(hash(text)) % 8999999)


def _entities(text: str) -> list[dict]:
    return [{"type": "plain", "text": text}]


def _message(msg_id: int, moment: datetime, sender: str, sender_id: str,
             body: str, rng: Random) -> dict:
    record: dict = {
        "id": msg_id,
        "type": "message",
        "date": moment.strftime("%Y-%m-%dT%H:%M:%S"),
        "date_unixtime": str(int(moment.timestamp())),
        "from": sender,
        "from_id": sender_id,
        "text": body.split("\n") if "\n" in body else body,
        "text_entities": _entities(body),
    }
    if config.INCLUDE_MEDIA_ROWS and rng.random() < 0.06:
        record["photo"] = f"photos/photo_{msg_id}@10-11-2026_12-00-00.jpg"
        record["photo_file_size"] = rng.randint(40_000, 900_000)
        record["width"] = 1280
        record["height"] = 960
    if rng.random() < 0.03:
        record["reactions"] = [{"emoji": rng.choice(["👍", "❤", "😂"]), "count": 1}]
    return record


def _service(msg_id: int, moment: datetime, action: str, actor: str | None = None) -> dict:
    record: dict = {
        "id": msg_id,
        "type": "service",
        "date": moment.strftime("%Y-%m-%dT%H:%M:%S"),
        "date_unixtime": str(int(moment.timestamp())),
        "text": "",
        "text_entities": [],
        "action": action,
    }
    if actor:
        record["actor"] = actor
        record["actor_id"] = f"user{_stable_id(actor)}"
    return record


def _spread(thread: Thread, index: int, total: int) -> datetime:
    """Distribute messages between `start` and `end`, so a 500-message thread spans time."""
    if not total:
        return thread.start
    start = thread.start
    end = thread.end or start
    span = (end - start).total_seconds()
    return start + (end - start) * (index / max(1, total - 1)) if span else start


def _chat(thread: Thread, world: World, rng: Random, start_id: int) -> tuple[dict, int]:
    messages: list[dict] = []
    msg_id = start_id
    person = thread.participants[0]

    # §6: a chat that holds ONLY service rows. The adapter emits no Chat for it. A chat
    # with an empty `messages` list and no service row is the shape that yields nothing:
    # the adapter builds a Chat as soon as any row is present.
    if thread.mark == "zero_message":
        return {
            "name": thread.title,
            "type": "private_group",
            "id": _stable_id(thread.key, 9000000000),
            "messages": [],
        }, msg_id

    if thread.is_group:
        if config.INCLUDE_SERVICE_ROWS:
            messages.append(_service(msg_id, thread.start, "create_group", person.name))
            msg_id += 1
        for index, (name, body) in enumerate(thread.group_lines):
            messages.append(_message(msg_id, _spread(thread, index, thread.count), name,
                                     f"user{_stable_id(name)}", body, rng))
            msg_id += 1
        # §7: a service row in the MIDDLE of a live group, not just at the head.
        if thread.mark == "service_rows" and config.INCLUDE_SERVICE_ROWS:
            messages.insert(
                max(1, len(messages) // 2),
                _service(msg_id, thread.start, "pin_message",
                         thread.participants[1].name if len(thread.participants) > 1
                         else person.name),
            )
            msg_id += 1
    else:
        sender_name = getattr(thread, "placeholder_sender", None) or person.name
        sender_id = (f"user{_stable_id(sender_name)}"
                     if sender_name != world.owner else "user_fixture_owner")
        for index, (is_owner, body) in enumerate(thread.lines):
            who = world.owner if is_owner else sender_name
            ident = "user_fixture_owner" if is_owner else sender_id
            messages.append(_message(msg_id, _spread(thread, index, thread.count),
                                     who, ident, body, rng))
            msg_id += 1

    return {
        "name": thread.title,
        "type": "private_supergroup" if thread.is_group else "personal_chat",
        "id": _stable_id(thread.key, 9000000000),
        "messages": messages,
    }, msg_id


def write_bulk(plan: Plan, world: World, out_dir: Path, rng: Random,
                filer) -> Path:
    folder = out_dir / "telegram_bulk"
    folder.mkdir(parents=True, exist_ok=True)
    chats, next_id = [], 100000
    for thread in plan.threads:
        chat, next_id = _chat(thread, world, rng, next_id)
        chats.append(chat)
    document = {
        "about": TG_ABOUT,
        "contacts": {"about": "Contacts", "list": []},
        "frequent_contacts": {"about": "Frequently contacted", "list": []},
        "chats": {"about": "Chats", "list": chats},
        "left_chats": {"about": "Left chats", "list": []},
    }
    target = filer.file(folder, "result.json")
    target.write_text(json.dumps(document, ensure_ascii=False, indent=1), encoding="utf-8")
    return target


def write_single(plan: Plan, world: World, out_dir: Path, rng: Random,
                 filer) -> Path:
    folder = out_dir / "telegram_single"
    folder.mkdir(parents=True, exist_ok=True)
    thread = next((t for t in plan.threads if t.count > 1 and not t.is_group),
                  plan.threads[0])
    chat, _ = _chat(thread, world, rng, 90000)
    document = {"name": chat["name"], "type": chat["type"], "id": chat["id"],
                "messages": chat["messages"]}
    target = filer.file(folder, "result.json")
    target.write_text(json.dumps(document, ensure_ascii=False, indent=1), encoding="utf-8")
    return target


WRITERS = {"bulk": write_bulk, "single": write_single}


def write(plan: Plan, world: World, out_dir: Path, filer) -> list[Path]:
    rng = Random(f"{world.seed}:{plan.platform}")
    return [WRITERS[v](plan, world, out_dir, rng, filer) for v in config.VARIANTS[KIND]]
