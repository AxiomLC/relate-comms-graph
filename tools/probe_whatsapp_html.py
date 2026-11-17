"""Prototype: WhatsApp HTML export -> canonical rows. Measurement only.

Not wired into the app. This exists to answer one question with numbers: does an
HTML adapter read the same conversations as `chat.txt`, and how fast?

Run: python -m tools.probe_whatsapp_html
"""
from __future__ import annotations

import html as html_module
import re
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(r"C:/Users/q1fre/Downloads/temp socials downloads/whatsapp group test")

# --- selectors, mirroring messenger.py's approach ---------------------------------
_HEADER = re.compile(r'<div class="hd">(?P<title>.*?)<small>(?P<meta>.*?)</small>', re.S)
_DAYSEP = re.compile(r'<div class="daysep"><span>(?P<day>[^<]+)</span></div>')
# A row ends where the next row or day separator begins. Matching a fixed number of
# closing divs is fragile — a media row nests deeper than a text row.
_ROW = re.compile(
    r'<div class="row (?P<dir>in|out)">(?P<body>.*?)(?=<div class="row |<div class="daysep"|</div></div><div class="ftr")',
    re.S,
)
_SENDER = re.compile(r'<div class="sender">(?P<name>.*?)</div>', re.S)
_TXT = re.compile(r'<div class="txt">(?P<body>.*?)</div>(?=<div class="time">)', re.S)
_TIME = re.compile(r'<div class="time">(?P<time>[^<]+)</div>')
_PH = re.compile(r'<div class="ph[^"]*">(?P<text>.*?)</div>', re.S)
_CAP = re.compile(r'<div class="cap">(?P<text>.*?)</div>', re.S)
_IMG = re.compile(r'<img class="media"')
_TAG = re.compile(r"<[^>]+>")
_BR = re.compile(r"<br\s*/?>")

_MONTHS = {m: i for i, m in enumerate(
    ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), start=1)}


def _text(fragment: str) -> str:
    """HTML -> text. `<br>` becomes a newline, tags are stripped, entities decoded."""
    with_breaks = _BR.sub("\n", fragment)
    stripped = html_module.unescape(_TAG.sub("", with_breaks))
    return "\n".join(line.strip() for line in stripped.split("\n") if line.strip())


def _day(text: str) -> datetime | None:
    """`26 Sep 2026` -> date. The row only carries a time, so the day comes from here."""
    parts = text.strip().split()
    if len(parts) != 3:
        return None
    try:
        day, month, year = int(parts[0]), _MONTHS.get(parts[1]), int(parts[2])
    except (ValueError, TypeError):
        return None
    if month is None:
        return None
    return datetime(year, month, day, tzinfo=timezone.utc)


def _stamp(day: datetime | None, clock: str) -> datetime | None:
    if day is None:
        return None
    try:
        hour, minute = (int(p) for p in clock.strip().split(":")[:2])
    except (ValueError, TypeError):
        return None
    return day.replace(hour=hour, minute=minute)


def parse_html(document: str) -> dict:
    """Rows from one chat page, plus the header facts."""
    header = _HEADER.search(document)
    title = _text(header.group("title")) if header else ""
    meta = _text(header.group("meta")) if header else ""
    is_group = meta.lower().startswith("group")

    # Walk the document once, tracking the current day separator.
    rows: list[dict] = []
    day = None
    cursor = 0
    for event in sorted(
        [(m.start(), "day", m) for m in _DAYSEP.finditer(document)]
        + [(m.start(), "row", m) for m in _ROW.finditer(document)],
        key=lambda item: item[0],
    ):
        _, kind, match = event
        if kind == "day":
            day = _day(match.group("day"))
            continue

        body = match.group("body")
        sender_match = _SENDER.search(body)
        txt_match = _TXT.search(body)
        time_match = _TIME.search(body)
        ph_match = _PH.search(body)
        cap_match = _CAP.search(body)

        sender = _text(sender_match.group("name")) if sender_match else ""
        clock = time_match.group("time") if time_match else ""
        stamp = _stamp(day, clock)

        if ph_match:
            text = _text(ph_match.group("text"))
            kind_name = "placeholder"
        elif cap_match:
            text = _text(cap_match.group("text"))
            kind_name = "media_caption"
        elif txt_match:
            text = _text(txt_match.group("body"))
            kind_name = "text"
        else:
            text = ""
            kind_name = "empty"

        rows.append({
            "dir": match.group("dir"),
            "sender": sender,
            "ts": stamp,
            "text": text,
            "kind": kind_name,
            "has_media": bool(_IMG.search(body)),
        })
        cursor = match.end()

    return {"title": title, "meta": meta, "is_group": is_group, "rows": rows}


def parse_zip(path: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    with zipfile.ZipFile(path) as archive:
        for name in archive.namelist():
            if not name.endswith(".html") or name == "index.html":
                continue
            document = archive.read(name).decode("utf-8", errors="replace")
            out[name] = parse_html(document)
    return out


def main() -> int:
    started = time.perf_counter()
    parsed = parse_zip(BASE / "whatsapp-chats-20261117.zip")
    elapsed = time.perf_counter() - started

    print(f"HTML parse: {len(parsed)} chats in {elapsed * 1000:.1f} ms\n")
    for name, chat in parsed.items():
        print(f"=== {name} ===")
        print(f"  title    : {chat['title']}")
        print(f"  meta     : {chat['meta']}")
        print(f"  is_group : {chat['is_group']}")
        print(f"  rows     : {len(chat['rows'])}")
        kinds: dict[str, int] = {}
        for row in chat["rows"]:
            kinds[row["kind"]] = kinds.get(row["kind"], 0) + 1
        print(f"  kinds    : {kinds}")
        out_rows = sum(1 for r in chat["rows"] if r["dir"] == "out")
        print(f"  owner    : {out_rows} rows")
        missing_ts = sum(1 for r in chat["rows"] if r["ts"] is None)
        print(f"  no ts    : {missing_ts}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
