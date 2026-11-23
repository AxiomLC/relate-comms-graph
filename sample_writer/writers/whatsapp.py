"""WhatsApp. The two shapes a dev actually meets, matching the real exports in `in/`.

  web   WhatsApp Web single-chat zips: `whatsapp_web/<number>.zip`, each flat
        `chat.txt` + `chat.md`. WhatsApp Web names the archive by the contact's
        phone number (not their name), and the contact name lives in the `chat.txt`
        sender lines. This is the native Web/Windows export.
  html  the browser-extension dialect: many chats in one zip, `chats/*.html` + `index`.
        This is the only way to bulk-download, and the shape a dev most often ingests.

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
        # `.label()` not `.name`: a system row still spells a person the way this export
        # spells them. Using the canonical name here meant a decided sender variant could
        # be assigned and then never written — measured on `Xavier Kay`, whose only
        # WhatsApp thread carried one Owner line, so his `Xavire` label appeared nowhere.
        out.append((moment, None, f"{thread.participants[0].label('whatsapp')} added "
                                  f"{thread.participants[1].label('whatsapp')}"))
        return out

    out.append((moment, None, "Messages and calls are end-to-end encrypted. "
                              "No one outside of this chat, not even WhatsApp, can read "
                              "or listen to them."))

    if thread.is_group:
        # §1: the membership row that makes an Owner-silent group classifiable at all.
        template = rng.choice(MEMBERSHIP_ROWS)
        out.append((moment, None, template.format(
            title=thread.title, name=thread.participants[-1].label("whatsapp"))))
        if thread.mark == "service_rows":
            out.append((moment, None,
                        f"{thread.participants[0].label('whatsapp')} changed the "
                        f"subject to \"{thread.title}\""))

    if thread.silent:
        return out

    rows: list[tuple[str, str]] = (
        [(name, body) for name, body in thread.group_lines] if thread.is_group
        else [(world.owner if is_owner
               else (getattr(thread, "placeholder_sender", None)
                     or thread.participants[0].label("whatsapp")), body)
              for is_owner, body in thread.lines]
    )

    # Real timestamps from the thread's irregular schedule (bursts, long silences),
    # not an even step. `plan()` fills `thread.times`; the index offsets past the
    # system rows already emitted above.
    offset = len(out)
    for index, (sender, body) in enumerate(rows):
        slot = offset + index
        if thread.times and slot < len(thread.times):
            moment = thread.times[slot]
        elif thread.times:
            moment = thread.times[-1]
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


def _safe(title: str) -> str:
    """A filename that Windows, Linux and macOS all accept."""
    for bad in '\\/:*?"<>|':
        title = title.replace(bad, "-")
    return title.strip() or "chat"


def write_web(plan: Plan, world: World, out_dir: Path, rng: Random,
              filer) -> list[Path]:
    """WhatsApp Web single-chat zips, one per thread, named by phone number.

    WhatsApp Web names the archive by the contact's **phone number** (`+27 61 164 2135.zip`),
    not their name — the contact name appears only in the `chat.txt` sender lines. Each zip
    holds a flat `chat.txt` and a markdown twin `chat.md`, exactly as the native export does.
    """
    folder = out_dir / "whatsapp_web"
    folder.mkdir(parents=True, exist_ok=True)
    made: list[Path] = []
    for thread in plan.threads:
        if thread.silent:
            continue
        number = thread.participants[0].phone or _safe(thread.title)
        target = filer.file(folder, f"{number}.zip")
        body = "\r\n".join(_txt(_rows(thread, world, rng))) + "\r\n"
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("chat.txt", body)
            archive.writestr("chat.md", f"# WhatsApp chat\n")
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


def write_html(plan: Plan, world: World, out_dir: Path, rng: Random,
               filer) -> Path:
    """Many chats in one zip, one page each. The browser-extension dialect (§11b)."""
    folder = out_dir / "whatsapp_html"
    folder.mkdir(parents=True, exist_ok=True)
    target = filer.file(folder, f"whatsapp-chats-{world.export_date('%Y%m%d')}.zip")
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
    "web": write_web,
    "html": write_html,
}


def write(plan: Plan, world: World, out_dir: Path, filer) -> list[Path]:
    """Some dialects write one file per chat, so every result is normalised to a list."""
    rng = Random(f"{world.seed}:{plan.platform}")
    made: list[Path] = []
    for variant in config.VARIANTS[KIND]:
        produced = WRITERS[variant](plan, world, out_dir, rng, filer)
        made.extend(produced if isinstance(produced, list) else [produced])
    return made
