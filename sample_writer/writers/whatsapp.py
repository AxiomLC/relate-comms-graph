"""WhatsApp. Both dialects the app reads, and the loose text forms.

  chat_txt    native zip: `WhatsApp Chat with X/<id>@s.whatsapp.net/chat.txt`
  underscore  older iPhone packaging: `_chat.txt`
  bare        a loose `.txt`, no zip
  html        the browser-extension dialect: many chats in one zip, `chats/*.html`

**§1 depends on the membership system row.** A group the Owner never wrote in has no
`You:` line at all, so the only group signal the adapter can see is a membership row
(`added`, `removed`, `changed the group name`, `created group`, ...). Every generated
group therefore carries at least one, and no 1:1 ever does.
"""
from __future__ import annotations

import html
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from random import Random

from .. import config
from ..dialogue import MEDIA_BODIES
from ..plan import Plan, Thread
from ..world import World

KIND = "whatsapp"

MEMBERSHIP_ROWS = [
    "changed the group name to '{title}'",
    "created group '{title}'",
    "added {name}",
    "added {name}",
    "removed {name}",
    "joined using this group's invite link",
]


def _stamp(moment: datetime) -> str:
    hour = moment.hour % 12 or 12
    return (moment.strftime("%d/%m/%Y, ") + f"{hour}:{moment:%M:%S} "
            + ("AM" if moment.hour < 12 else "PM"))


def _rows(thread: Thread, world: World, rng: Random) -> list[tuple[datetime, str | None,
                                                                   str]]:
    """(moment, sender or None for a system row, body)."""
    moment = thread.start
    out: list[tuple[datetime, str | None, str]] = []

    if thread.mark == "zero_message":
        # §6: system rows only. The adapter emits no Chat and counts it skipped.
        out.append((moment, None, "Messages and calls are end-to-end encrypted."))
        out.append((moment, None, f"{thread.participants[0].name} added "
                                  f"{thread.participants[1].name}"))
        return out

    out.append((moment, None, "Messages and calls are end-to-end encrypted. "
                              "No one outside of this chat, not even WhatsApp, can read "
                              "or listen to them."))

    if thread.is_group:
        # §1: the membership row that makes an Owner-silent group classifiable at all.
        template = rng.choice(MEMBERSHIP_ROWS)
        out.append((moment, None, template.format(
            title=thread.title, name=thread.participants[-1].name)))
        if thread.mark == "service_rows":
            out.append((moment, None, f"{thread.participants[0].name} changed the "
                                      f"subject to \"{thread.title}\""))

    if thread.silent:
        return out

    rows: list[tuple[str, str]] = (
        [(name, body) for name, body in thread.group_lines] if thread.is_group
        else [(world.owner if is_owner
               else (getattr(thread, "placeholder_sender", None)
                     or thread.participants[0].name), body)
              for is_owner, body in thread.lines]
    )

    step = timedelta(seconds=max(60, int(
        ((thread.end or moment + timedelta(days=30)) - moment).total_seconds()
        / max(1, len(rows))
    )))
    for sender, body in rows:
        moment = moment + step
        if config.INCLUDE_MEDIA_ROWS and rng.random() < 0.04:
            body = rng.choice(MEDIA_BODIES)
        out.append((moment, sender, body))
    return out


def _txt(thread_rows: list[tuple[datetime, str | None, str]]) -> list[str]:
    lines = []
    for moment, sender, body in thread_rows:
        if sender is None:
            lines.append(f"[{_stamp(moment)}] {body}")
        else:
            lines.append(f"[{_stamp(moment)}] {sender}: {body}")
    return lines


def _chat_id(thread: Thread) -> str:
    digits = "".join(ch for ch in str(abs(hash(thread.key))) if ch.isdigit())
    return f"{(digits or '447700900123')[:12]}@s.whatsapp.net"


def _safe(title: str) -> str:
    """A filename that Windows, Linux and macOS all accept."""
    for bad in '\\/:*?"<>|':
        title = title.replace(bad, "-")
    return title.strip() or "chat"


def write_chat_txt(plan: Plan, world: World, out_dir: Path, rng: Random) -> list[Path]:
    """One chat per zip, inside the conversation folder. The native Android export.

    §11a: the native format is **one chat per file** and the chat title is the zip name,
    so `_chat_id()` can derive the thread key. Concatenating every thread into one file
    would still parse, but would produce one giant conversation the real exporter never
    writes.
    """
    folder = out_dir / "whatsapp_chat_txt"
    folder.mkdir(parents=True, exist_ok=True)
    made: list[Path] = []
    for thread in plan.threads:
        if thread.silent:
            continue
        safe = _safe(thread.title)
        target = folder / f"{safe}.zip"
        body = "\r\n".join(_txt(_rows(thread, world, rng))) + "\r\n"
        inner = f"WhatsApp Chat with {safe}/{_chat_id(thread)}/chat.txt"
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(inner, body)
            archive.writestr(inner.replace("chat.txt", "chat.md"), "# WhatsApp chat\n")
        made.append(target)
    return made


def write_underscore(plan: Plan, world: World, out_dir: Path, rng: Random) -> list[Path]:
    """Older iPhone-style packaging: one zip per chat, `_chat.txt` at the archive root."""
    folder = out_dir / "whatsapp_underscore"
    folder.mkdir(parents=True, exist_ok=True)
    made: list[Path] = []
    for thread in plan.threads:
        if thread.silent:
            continue
        target = folder / f"{_safe(thread.title)}.zip"
        body = "\r\n".join(_txt(_rows(thread, world, rng))) + "\r\n"
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("_chat.txt", body)
        made.append(target)
    return made


def write_bare(plan: Plan, world: World, out_dir: Path, rng: Random) -> list[Path]:
    """Loose text files, one per chat: what a copy-pasted export looks like."""
    folder = out_dir / "whatsapp_bare"
    folder.mkdir(parents=True, exist_ok=True)
    made: list[Path] = []
    for thread in plan.threads:
        if thread.silent:
            continue
        target = folder / f"WhatsApp Chat with {_safe(thread.title)}.txt"
        body = "\r\n".join(_txt(_rows(thread, world, rng))) + "\r\n"
        target.write_text(body, encoding="utf-8")
        made.append(target)
    return made


# ------------------------------------------------------------------- HTML dialect

def _page(thread: Thread, world: World, rng: Random) -> str:
    rows = _rows(thread, world, rng)
    kind = "Group" if thread.is_group else "Chat"
    count = sum(1 for _m, sender, _b in rows if sender is not None)
    head = (
        "<!DOCTYPE html><html><head><meta charset=\"UTF-8\">"
        f"<title>{html.escape(thread.title)} — WhatsApp Chat</title>"
        "<style>body{background:#e5ddd5;font-family:-apple-system,Segoe UI,Roboto,sans-serif}"
        ".row{display:flex;margin:4px 0}.row.out{justify-content:flex-end}"
        ".bubble{max-width:78%;padding:6px 9px;border-radius:8px;background:#fff}"
        ".row.out .bubble{background:#d9fdd3}.sender{font-size:12px;font-weight:600;"
        "color:#075e54}.time{font-size:10px;color:#667781;text-align:right}"
        "</style></head><body><div class=\"wrap\">"
        f"<div class=\"hd\">{html.escape(thread.title)}"
        f"<small>{kind} · {count} messages · exported 17 Nov 2026</small></div>"
        "<div class=\"msgs\">"
    )
    body: list[str] = []
    day = None
    for moment, sender, text in rows:
        if day != moment.date():
            day = moment.date()
            body.append(f'<div class="daysep"><span>{moment:%d %b %Y}</span></div>')
        if sender is None:
            body.append(f'<div class="row sys"><div class="bubble sys">'
                        f"<div class=\"txt\">{html.escape(text)}</div>"
                        f'<div class="time">{moment:%H:%M}</div></div></div>')
            continue
        is_owner = sender == world.owner
        sender_div = ("" if is_owner or not thread.is_group
                      else f'<div class="sender">{html.escape(sender)}</div>')
        body.append(
            f'<div class="row {"out" if is_owner else "in"}"><div class="bubble">'
            f"{sender_div}<div class=\"txt\">{html.escape(text)}</div>"
            f'<div class="time">{moment:%H:%M}</div></div></div>'
        )
    return head + "".join(body) + "</div></div></body></html>"


def write_html(plan: Plan, world: World, out_dir: Path, rng: Random) -> Path:
    """Many chats in one zip, one page each. The browser-extension dialect (§11b)."""
    folder = out_dir / "whatsapp_html"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "whatsapp-chats-20261117.zip"
    pages: list[tuple[str, str]] = []
    used: set[str] = set()
    for index, thread in enumerate(plan.threads):
        sub = "groups" if thread.is_group else "chats"
        stem = thread.title.replace(" ", "_")
        # One page per chat, and two threads can share a title (a person with both a
        # 1:1 and a group). The exporter disambiguates with a suffix; so do we.
        name = f"{sub}/{stem}.html"
        if name in used:
            name = f"{sub}/{stem}_{index}.html"
        used.add(name)
        pages.append((name, _page(thread, world, rng)))

    index = ["<!DOCTYPE html><html><body><h1>WhatsApp chats</h1><ul>"]
    for name, _page_html in pages:
        index.append(f'<li><a href="{html.escape(name)}">{html.escape(name)}</a></li>')
    index.append("</ul></body></html>")

    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, page in pages:
            archive.writestr(name, page)
        archive.writestr("index.html", "".join(index))
    return target


WRITERS = {
    "chat_txt": write_chat_txt,
    "underscore": write_underscore,
    "bare": write_bare,
    "html": write_html,
}


def write(plan: Plan, world: World, out_dir: Path) -> list[Path]:
    """Some dialects write one file per chat, so every result is normalised to a list."""
    rng = Random(f"{world.seed}:{plan.platform}")
    made: list[Path] = []
    for variant in config.VARIANTS[KIND]:
        produced = WRITERS[variant](plan, world, out_dir, rng)
        made.extend(produced if isinstance(produced, list) else [produced])
    return made
