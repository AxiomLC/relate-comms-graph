"""Compare the HTML parse against the native `chat.txt` parse, same two chats.

The question is not "does it run" but "does it read the same conversation". So this
diffs the two row sets: count, sender, timestamp, and body.

Run: PYTHONIOENCODING=utf-8 python -m tools.compare_whatsapp_formats
"""
from __future__ import annotations

import time
import zipfile
from pathlib import Path

from relate_comms.adapters import whatsapp

from .probe_whatsapp_html import parse_html, parse_zip

BASE = Path(r"C:/Users/q1fre/Downloads/temp socials downloads/whatsapp group test")

# The two chats that exist in both formats. The group only exists as HTML.
PAIRS = [
    ("chats/Thad_Zurawski_Chicago.html", "Thad Zurawski Chicago.zip"),
    ("chats/Michael_Metzler.html", "Michael Metzler.zip"),
]


def _norm(text: str) -> str:
    return " ".join((text or "").split())


def main() -> int:
    started = time.perf_counter()
    html_chats = parse_zip(BASE / "whatsapp-chats-20261117.zip")
    html_ms = (time.perf_counter() - started) * 1000

    print(f"HTML  : {len(html_chats)} chats in {html_ms:.1f} ms")

    started = time.perf_counter()
    txt_chats = {}
    for _, zip_name in PAIRS:
        txt_chats[zip_name] = whatsapp.parse(BASE / zip_name)
    txt_ms = (time.perf_counter() - started) * 1000
    print(f"chat.txt: {len(txt_chats)} chats in {txt_ms:.1f} ms\n")

    for html_name, zip_name in PAIRS:
        html_rows = html_chats[html_name]["rows"]
        txt_result = txt_chats[zip_name]
        txt_rows = txt_result.messages

        print(f"=== {html_name.split('/')[-1]} vs {zip_name} ===")
        print(f"  HTML rows    : {len(html_rows)}")
        print(f"  chat.txt rows: {len(txt_rows)}")

        # chat.txt keeps system rows (`- [Call]`); the HTML export drops them.
        txt_system = [m for m in txt_rows if m.raw_kind.startswith("system:")]
        txt_real = [m for m in txt_rows if not m.raw_kind.startswith("system:")]
        print(f"  chat.txt system rows: {len(txt_system)}")
        print(f"  chat.txt real rows  : {len(txt_real)}")

        # Compare on (timestamp, body) — sender differs by design, see below.
        html_keys = {(r["ts"], _norm(r["text"])) for r in html_rows}
        txt_keys = {(m.ts_utc, _norm(m.body)) for m in txt_real}

        only_html = html_keys - txt_keys
        only_txt = txt_keys - html_keys
        print(f"  matched      : {len(html_keys & txt_keys)}")
        print(f"  only in HTML : {len(only_html)}")
        print(f"  only in txt  : {len(only_txt)}")

        for ts, body in sorted(only_html)[:4]:
            print(f"    HTML-only {ts} {body[:60]!r}")
        for ts, body in sorted(only_txt)[:4]:
            print(f"    txt-only  {ts} {body[:60]!r}")

        # Sender comparison: HTML has no sender div on owner rows.
        html_senders = {r["sender"] for r in html_rows if r["sender"]}
        txt_senders = {m.sender_name for m in txt_real if m.sender_name}
        print(f"  HTML senders : {sorted(html_senders)}")
        print(f"  txt senders  : {sorted(txt_senders)}")
        print()

    # The group has no chat.txt twin, so report what the HTML alone says.
    group = html_chats["groups/AOAF_B-DAY_GAME_CHAT___.html"]
    print("=== group (HTML only) ===")
    print(f"  title    : {group['title']}")
    print(f"  is_group : {group['is_group']}")
    print(f"  rows     : {len(group['rows'])}")
    print(f"  owner    : {sum(1 for r in group['rows'] if r['dir'] == 'out')} rows")
    print(f"  senders  : {len({r['sender'] for r in group['rows'] if r['sender']})}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
