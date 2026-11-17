"""LinkedIn. `messages.csv` with the real column set, inside the ZIP or as a folder.

Columns observed in the real export (`in/Basic_LinkedInDataExport...zip`):
    CONVERSATION ID, CONVERSATION TITLE, FROM, SENDER PROFILE URL, TO,
    RECIPIENT PROFILE URLS, DATE, SUBJECT, CONTENT, FOLDER, ATTACHMENTS
`DATE` is `YYYY-MM-DD HH:MM:SS UTC`.
"""
from __future__ import annotations

import csv
import io
import zipfile
from pathlib import Path
from random import Random

from .. import config
from ..plan import Plan
from ..world import World

KIND = "linkedin"

COLUMNS = [
    "CONVERSATION ID", "CONVERSATION TITLE", "FROM", "SENDER PROFILE URL", "TO",
    "RECIPIENT PROFILE URLS", "DATE", "SUBJECT", "CONTENT", "FOLDER", "ATTACHMENTS",
]
CONNECTION_COLUMNS = [
    "First Name", "Last Name", "URL", "Email Address", "Company", "Position",
    "Connected On",
]


def _profile(person) -> str:
    return f"https://www.linkedin.com/in/{person.slug}"


def _rows(plan: Plan, world: World, rng: Random) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for thread in plan.threads:
        if thread.silent:
            continue
        person = thread.participants[0]
        conversation = f"2-{abs(hash(thread.key)):032X}"
        subject = thread.subject if config.SUBJECT_ON_LINKEDIN else ""
        # §5: `LinkedIn Member` / `LinkedIn Talent Solutions` are senders in real exports
        # that are not people. The placeholder name replaces the correspondent's.
        sender_name = getattr(thread, "placeholder_sender", "") or person.name
        for is_owner, body in thread.lines:
            sender = world.owner if is_owner else sender_name
            rows.append({
                "CONVERSATION ID": conversation,
                "CONVERSATION TITLE": "",
                "FROM": sender,
                "SENDER PROFILE URL": "https://www.linkedin.com/in/mark-jones-fixture"
                if is_owner else _profile(person),
                "TO": person.name if is_owner else world.owner,
                "RECIPIENT PROFILE URLS": _profile(person) if is_owner
                else "https://www.linkedin.com/in/mark-jones-fixture",
                "DATE": thread.start.strftime("%Y-%m-%d %H:%M:%S") + " UTC",
                "SUBJECT": subject if is_owner == (len(rows) == 0) else "",
                "CONTENT": body,
                "FOLDER": "INBOX",
                "ATTACHMENTS": "",
            })
    return rows


def _connections(world: World, rng: Random) -> list[dict[str, str]]:
    rows = []
    for person in world.for_platform("linkedin"):
        if person.name == world.owner:
            continue
        first, _, last = person.name.partition(" ")
        rows.append({
            "First Name": first,
            "Last Name": last,
            "URL": _profile(person),
            "Email Address": person.email or "",
            "Company": person.org or "",
            "Position": person.role,
            "Connected On": world.random_time(rng).strftime("%d %b %Y"),
        })
    return rows


def _csv(rows: list[dict[str, str]], columns: list[str]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, lineterminator="\r\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def write_zip(plan: Plan, world: World, out_dir: Path, rng: Random) -> Path:
    folder = out_dir / "linkedin_zip"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "Basic_LinkedInDataExport_11-14-2026.zip.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("messages.csv", _csv(_rows(plan, world, rng), COLUMNS))
        archive.writestr("Connections.csv", _csv(_connections(world, rng), CONNECTION_COLUMNS))
        archive.writestr("Profile.csv", "First Name,Last Name\nMark,Jones\n")
    return target


def write_dir(plan: Plan, world: World, out_dir: Path, rng: Random) -> Path:
    folder = out_dir / "linkedin_dir"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "messages.csv").write_text(
        _csv(_rows(plan, world, rng), COLUMNS), encoding="utf-8"
    )
    (folder / "Connections.csv").write_text(
        _csv(_connections(world, rng), CONNECTION_COLUMNS), encoding="utf-8"
    )
    return folder


WRITERS = {"zip": write_zip, "dir": write_dir}


def write(plan: Plan, world: World, out_dir: Path) -> list[Path]:
    rng = Random(f"{world.seed}:{plan.platform}")
    return [WRITERS[v](plan, world, out_dir, rng) for v in config.VARIANTS[KIND]]
