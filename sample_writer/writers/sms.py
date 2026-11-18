"""SMS. SyncTech `SMS Backup & Restore` XML, the same document zipped, and a JSON-app shape.

Real attribute set (from `in/sms-20261116212209.xml`):
    <smses count backup_set backup_date type="full">
    <sms protocol address date type subject body toa sc_toa service_center read status
         locked date_sent sub_id readable_date contact_name />
`type` 1 = received, 2 = sent.
"""
from __future__ import annotations

import json
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr
from random import Random

from .. import config
from ..plan import Plan
from ..world import World

KIND = "sms"

BACKUP_SET = "8f3c1e42-1a7d-4c11-9b6e-2d5f70a9c118"
SHORTCODES = ["+14720", "+4478297914273", "CellCApp", "+447700900999"]


def _readable(moment: datetime) -> str:
    return moment.strftime("%b %d, %Y %-I:%M:%S %p") if hasattr(datetime, "strftime") \
        else moment.isoformat()


def _readable_portable(moment: datetime) -> str:
    """`%-I` is glibc-only; build it by hand so Windows works."""
    hour = moment.hour % 12 or 12
    return moment.strftime("%b %d, %Y") + f" {hour}:{moment:%M:%S} " + \
        ("AM" if moment.hour < 12 else "PM")


def _messages(plan: Plan, world: World, rng: Random) -> list[dict]:
    rows: list[dict] = []
    placeholders = config.PLACEHOLDER_NAMES.get("sms", [])
    for index, thread in enumerate(plan.threads):
        if thread.silent:
            continue
        person = thread.participants[0]
        counterpart = person.phone or "+447700900123"
        # §5: real exports carry senders that are not people. `contact_name` is where
        # SMS states that, and "(Unknown)" / "Me" are the two the app sees most.
        contact = person.name
        if placeholders and index % 5 == 4:
            contact = placeholders[index % len(placeholders)]
        moment = thread.start
        for is_owner, body in thread.lines:
            moment = moment + timedelta(minutes=rng.randint(1, 300))
            rows.append({
                "address": counterpart,
                "date": int(moment.timestamp() * 1000),
                "type": 2 if is_owner else 1,
                "body": body,
                "read": 1 if rng.random() < 0.9 else 0,
                "contact_name": "Me" if is_owner else contact,
                "_moment": moment,
            })
        # One recurring shortcode sender per thread, so spam shapes exist in SMS too.
        if thread.owner_replies is False or rng.random() < 0.2:
            spam_at = thread.start
            for _ in range(rng.randint(1, 3)):
                spam_at = spam_at + timedelta(days=rng.randint(1, 20))
                rows.append({
                    "address": rng.choice(SHORTCODES),
                    "date": int(spam_at.timestamp() * 1000),
                    "type": 1,
                    "body": "Your code is " + str(rng.randint(100000, 999999)) +
                            ". Do not share it with anyone.",
                    "read": 0,
                    "contact_name": "(Unknown)",
                    "_moment": spam_at,
                })
    rows.sort(key=lambda r: r["date"])
    return rows


def _xml(rows: list[dict], count_total: int) -> str:
    head = (
        "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>\n"
        "<!--File Created By SMS Backup & Restore v10.21.001 on 16/11/2026 21:22:18-->\n"
        "<!--\n\nTo view this file in a more readable format, visit "
        "https://synctech.com.au/view-backup/\n\n-->\n"
        f'<smses count="{count_total}" backup_set="{BACKUP_SET}" '
        f'backup_date="{int(datetime(2026, 11, 16).timestamp() * 1000)}" type="full">\n'
    )
    parts = [head]
    for row in rows:
        parts.append(
            "<sms "
            f'protocol="0" '
            f'address={quoteattr(row["address"])} '
            f'date="{row["date"]}" '
            f'type="{row["type"]}" '
            f'subject="null" '
            f'body={quoteattr(row["body"])} '
            f'toa="null" sc_toa="null" service_center="null" '
            f'read="{row["read"]}" status="-1" locked="0" '
            f'date_sent="{row["date"] - 3000}" sub_id="-1" '
            f'readable_date={quoteattr(_readable_portable(row["_moment"]))} '
            f'contact_name={quoteattr(row["contact_name"])} />\n'
        )
    parts.append("</smses>\n")
    return "".join(parts)


def write_xml(plan: Plan, world: World, out_dir: Path, rng: Random,
              filer) -> Path:
    folder = out_dir / "sms_xml"
    folder.mkdir(parents=True, exist_ok=True)
    rows = _messages(plan, world, rng)
    target = filer.file(folder, "sms-20261116212209.xml")
    target.write_text(_xml(rows, len(rows)), encoding="utf-8")
    return target


def write_xml_zip(plan: Plan, world: World, out_dir: Path, rng: Random,
                  filer) -> Path:
    folder = out_dir / "sms_xml_zip"
    folder.mkdir(parents=True, exist_ok=True)
    rows = _messages(plan, world, rng)
    target = filer.file(folder, "sms-20261116212209.xml.zip")
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("sms-20261116212209.xml", _xml(rows, len(rows)))
    return target


def write_json_app(plan: Plan, world: World, out_dir: Path, rng: Random,
                   filer) -> Path:
    """A different Android backup app: an array of objects, not `<smses>`.

    Kept because the user asked for it and because it is the honest test of "we do not
    guess": this shape is *not* detectable by the SMS adapter today, so it should be
    reported as unrecognised rather than silently swallowed.
    """
    folder = out_dir / "sms_json_app"
    folder.mkdir(parents=True, exist_ok=True)
    rows = _messages(plan, world, rng)
    document = [
        {
            "id": index + 1,
            "address": row["address"],
            "date": row["date"],
            "type": row["type"],
            "body": row["body"],
            "read": bool(row["read"]),
            "contactName": row["contact_name"],
        }
        for index, row in enumerate(rows)
    ]
    target = filer.file(folder, "sms-backup.json")
    target.write_text(json.dumps(document, ensure_ascii=False, indent=1), encoding="utf-8")
    return target


WRITERS = {"xml": write_xml, "xml_zip": write_xml_zip, "json_app": write_json_app}


def write(plan: Plan, world: World, out_dir: Path, filer) -> list[Path]:
    rng = Random(f"{world.seed}:{plan.platform}")
    return [WRITERS[v](plan, world, out_dir, rng, filer) for v in config.VARIANTS[KIND]]
