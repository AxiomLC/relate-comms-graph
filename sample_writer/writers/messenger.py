"""Messenger. `your_facebook_activity/messages/...` HTML, zipped and as a folder.

Threads are spread across the four folders Messenger writes (§4):

    inbox/            normal conversations
    filtered_threads/ usually strangers and spam
    message_requests/ people you have not accepted
    e2ee_cutover/     legacy encrypted threads — still real messages, always kept

`thread.folder` is decided in `plan.py`, so the writer only renders.
"""
from __future__ import annotations

import html
import zipfile
from pathlib import Path
from random import Random

from .. import config
from ..plan import Plan, Thread
from ..world import World

KIND = "messenger"
FOLDER = "your_facebook_activity/messages"


def _stamp(thread: Thread) -> str:
    moment = thread.start
    hour = moment.hour % 12 or 12
    suffix = "am" if moment.hour < 12 else "pm"
    return moment.strftime("%b %d, %Y") + f" {hour}:{moment:%M:%S} {suffix}"


def _section(sender: str, body: str, stamp: str, index: int) -> str:
    return (
        f'<section class="_a6-g" aria-labelledby="u_0_{index}"><h2 class="_2ph_ _a6-h '
        f'_a6-i" id="u_0_{index}">{html.escape(sender)}</h2><div class="_2ph_ _a6-p"><div>'
        f"<div></div><div>{html.escape(body)}</div><div></div><div></div></div></div>"
        f'<footer class="_3-94 _a6-o"><div class="_a72d">{stamp}</div></footer></section>'
    )


def _page(title: str, sections: list[str]) -> str:
    return (
        "<html><head><meta http-equiv=\"Content-Type\" content=\"text/html; "
        "charset=UTF-8\" /><style type=\"text/css\">body{background:#fff;"
        "font-family:Helvetica,Arial,sans-serif;font-size:12px}h1{font-size:14px}"
        "</style></head>"
        f'<body class="_5vb_ _2yq _a7o5"><div class="_li"><div class="_a705">'
        f'<header class="_as-_ _a709"><div class="_a70d"><h1>{html.escape(title)}</h1>'
        "</div></header><main class=\"_a706\" role=\"main\">"
        + "".join(sections)
        + "</main></div></div></body></html>"
    )


def _sections(thread: Thread, world: World) -> list[str]:
    if thread.mark == "zero_message":
        return []

    if thread.is_group:
        rows = [(name, body) for name, body in thread.group_lines]
    else:
        sender = getattr(thread, "placeholder_sender", None) or thread.participants[0].name
        rows = [(world.owner if is_owner else sender, body)
                for is_owner, body in thread.lines]

    sections: list[str] = []
    run_sender: str | None = None
    run_body: list[str] = []
    for index, (sender, body) in enumerate(rows):
        if sender == run_sender:
            run_body.append(body)          # back-to-back, joined with <br>
            continue
        if run_sender is not None:
            sections.append(_section(run_sender, "<br>".join(run_body), stamp, len(sections)))
        run_sender, run_body = sender, [body]
        stamp = _stamp(thread)
    if run_sender is not None:
        sections.append(_section(run_sender, "<br>".join(run_body), stamp, len(sections)))
    return sections


def _layout(plan: Plan, world: World) -> dict[str, str]:
    files: dict[str, str] = {}
    for index, thread in enumerate(plan.threads):
        if thread.mark == "zero_message":
            continue
        folder = thread.folder or "inbox"
        name = f"{thread.participants[0].slug}_{9000000 + index}"
        files[f"{FOLDER}/{folder}/{name}/message_1.html"] = _page(
            thread.title, _sections(thread, world)
        )
    return files


def write_zip(plan: Plan, world: World, out_dir: Path, rng: Random) -> Path:
    folder = out_dir / "messenger_zip"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "facebook-sampleuser-2026-11-14-1G300tUX.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, body in _layout(plan, world).items():
            archive.writestr(name, body)
        archive.writestr("start_here.html", "<html><body>Export</body></html>")
    return target


def write_dir(plan: Plan, world: World, out_dir: Path, rng: Random) -> Path:
    folder = out_dir / "messenger_dir"
    for name, body in _layout(plan, world).items():
        target = folder / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    return folder


WRITERS = {"zip": write_zip, "dir": write_dir}


def write(plan: Plan, world: World, out_dir: Path) -> list[Path]:
    rng = Random(f"{world.seed}:{plan.platform}")
    return [WRITERS[v](plan, world, out_dir, rng) for v in config.VARIANTS[KIND]]
