"""Stage 3 acceptance: WhatsApp `.txt` -> canonical rows.

Real exports from this machine are used when present; the tracked fixture always
runs. Every test here exists because one of the two real files broke a naive
parser — see the module docstring in `adapters/whatsapp.py`.

Run: python -m pytest tests -q
"""
from __future__ import annotations

import io
import os
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from relate_comms import ingest as ingest_module
from relate_comms import writer
from relate_comms.adapters import whatsapp
from relate_comms.paths import spool_dir

REAL_EXPORTS = [
    Path.home() / "Downloads" / "+1 (917) 400-4025.zip",
    Path.home() / "Downloads" / "+27 84 518 9029.zip",
]
_REAL = next((p for p in REAL_EXPORTS if p.exists()), None)


def _zip(tmp_path: Path, name: str, text: str) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    target = tmp_path / f"{name}.zip"
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr("chat.txt", text)
    return target


BASIC = (
    "Messages and calls are end-to-end encrypted. No one outside of this chat, "
    "not even WhatsApp, can read or listen to them.\n"
    "[5/22/26, 8:45:50 AM] +1 (917) 400-4025: Hi\n"
    "[5/22/26, 8:45:51 AM] - Messages and calls are end-to-end encrypted. Tap to learn more.\n"
    "[5/22/26, 8:46:38 AM] You: hello there\n"
)


# --------------------------------------------------------------------------- unit

def test_multiline_body_is_joined_not_orphaned(tmp_path):
    """The real US export has a message body that is a bare `[` (pasted JSON).

    A `line.startswith("[")` parser splits it and drops the rest of the message.
    """
    body = 'Here is the shape:\n[\n  { "a": 1 },\n  { "b": 2 }\n]\nAnd that is it.'
    export = _zip(tmp_path, "Multi Line", BASIC + f"[5/23/26, 9:00:00 AM] You: {body}\n")
    result = whatsapp.parse(export)
    last = result.messages[-1]
    assert last.body == body, f"body was split: {last.body!r}"
    assert last.raw_kind == "text"


def test_detection_handles_the_folder_layout(tmp_path):
    """WhatsApp packs the chat inside a folder named after the conversation.

    `archive.open("chat.txt")` raised `KeyError` on every real export, because the
    membership test used basenames while `open()` needs the full member path. Detection
    crashed rather than returning None, so the standard layout was unreadable.
    """
    import zipfile

    from relate_comms import ingest as ingest_module

    path = tmp_path / "WhatsApp Chat with X.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("WhatsApp Chat with X/123@s.whatsapp.net/chat.txt", BASIC)

    assert ingest_module.detect_platform(path) == "whatsapp"
    # And the parser reads the same member.
    assert whatsapp.parse(path).messages


def test_header_must_match_the_whole_prefix():
    lines = ["[not a header", "[5/22/26, 8:45:50 AM] You: ok"]
    groups = whatsapp.split_lines("\n".join(lines))
    assert len(groups) == 1
    assert groups[0][1] == "You: ok"


def test_sender_split_does_not_eat_urls():
    name, body = whatsapp._split_sender("You: see https://example.com/x")
    assert name == "You" and body == "see https://example.com/x"
    # No sender prefix => system row shape.
    assert whatsapp._split_sender("- joined via invite")[0] is None


def test_month_first_detected_from_data(tmp_path):
    us = _zip(tmp_path, "us", BASIC + "[10/27/26, 9:34:12 PM] You: late\n")
    assert whatsapp._detect_month_first(whatsapp.read_export(us)[0].split("\n")) is True

    eu = _zip(tmp_path, "eu", "[19/4/26, 14:32:28] You: bonsoir\n")
    assert whatsapp._detect_month_first(whatsapp.read_export(eu)[0].split("\n")) is False


def test_12am_and_12pm_are_not_off_by_twelve(tmp_path):
    export = _zip(tmp_path, "noon", "[1/2/26, 12:00:00 AM] You: midnight\n"
                                   "[1/2/26, 12:30:00 PM] You: lunch\n")
    result = whatsapp.parse(export, tz_offset_hours=0)
    hours = [m.ts_utc.hour for m in result.messages]
    assert hours == [0, 12]


def test_tz_offset_shifts_to_utc(tmp_path):
    export = _zip(tmp_path, "tz", "[6/1/26, 10:00:00 AM] You: x\n")
    utc = whatsapp.parse(export, tz_offset_hours=0).messages[0].ts_utc
    est = whatsapp.parse(export, tz_offset_hours=-5).messages[0].ts_utc
    assert est - utc == timedelta(hours=5)


def test_media_placeholder_becomes_a_kind(tmp_path):
    export = _zip(tmp_path, "media", (
        "[6/1/26, 10:00:00 AM] You: <image omitted>\n"
        "[6/1/26, 10:00:01 AM] You: <video omitted>\n"
        "[6/1/26, 10:00:02 AM] You: <document omitted> report.pdf\n"
        "[6/1/26, 10:00:03 AM] You: [Forwarded] <album message>\n"
    ))
    result = whatsapp.parse(export)
    kinds = [m.raw_kind for m in result.messages]
    assert kinds == ["image", "video", "document", "album"]
    assert all(m.has_attachments for m in result.messages)
    assert result.attachments[0].path == "report.pdf"


def test_same_second_album_rows_stay_distinct(tmp_path):
    """Seven identical `<image omitted>` in one second is a real album, not a bug.

    The real US export has exactly this. Collapsing them would lose six messages.
    """
    rows = "".join("[7/26/26, 2:38:40 PM] You: <image omitted>\n" for _ in range(7))
    export = _zip(tmp_path, "album", rows)
    result = whatsapp.parse(export)
    assert len(result.messages) == 7
    assert len({m.key for m in result.messages}) == 7, "album rows collapsed onto one key"
    assert result.unknown_kinds.get("same-second repeats") == 1


def test_owner_is_the_literal_you(tmp_path):
    export = _zip(tmp_path, "self", BASIC)
    result = whatsapp.parse(export)
    by_body = {m.body: m for m in result.messages if m.body}
    assert by_body["hello there"].is_self is True
    assert by_body["Hi"].is_self is False


def test_system_rows_are_kept_and_kinded(tmp_path):
    export = _zip(tmp_path, "sys", BASIC)
    included = whatsapp.parse(export)
    assert any(m.raw_kind.startswith("system:") for m in included.messages)

    excluded = whatsapp.parse(export, include_service=False)
    assert not any(m.raw_kind.startswith("system:") for m in excluded.messages)
    assert excluded.skipped.get("service excluded by request") == 1


def test_key_is_reproducible_and_chat_scoped(tmp_path):
    one = _zip(tmp_path, "chat one", BASIC)
    two = _zip(tmp_path, "chat two", BASIC)
    first = whatsapp.parse(one)
    again = whatsapp.parse(one)
    other = whatsapp.parse(two)

    assert [m.key for m in first.messages] == [m.key for m in again.messages]
    assert [m.key for m in first.messages] != [m.key for m in other.messages], (
        "the same text in two different chats must not share a key"
    )


def test_window_filter_counts_skips(tmp_path):
    export = _zip(tmp_path, "win", BASIC)
    since = datetime(2026, 5, 22, 8, 46, tzinfo=timezone.utc)
    result = whatsapp.parse(export, since=since)
    assert result.skipped.get("before window", 0) == 2
    assert all(m.ts_utc >= since for m in result.messages)


def test_a_one_to_one_is_never_dropped_by_the_group_gate(tmp_path):
    """The rule is about *groups*. A 1:1 the Owner never replied to is still a
    conversation someone had with them, and hiding it is a view toggle, not a drop."""
    export = _zip(tmp_path, "One to one", BASIC)

    kept = whatsapp.parse(export)
    assert len(kept.chats) == 1
    assert kept.chats[0].is_group is False

    trimmed = whatsapp.parse(export, exclude_silent_groups=True)
    assert len(trimmed.chats) == 1, "a 1:1 thread is never dropped by the group gate"
    assert "group thread the owner never spoke in" not in trimmed.skipped


def test_a_membership_row_proves_group_ness(tmp_path):
    """`SELF_NAME` alone cannot classify a group the Owner never spoke in.

    Verified against a real native export (`Local Community Events (OSA).zip`): six
    senders, 21 membership system rows, **no `You:` line at all**. The old rule
    (`You in senders and len(senders) > 3`) called it a 1:1, so the silent-group gate
    could never fire on exactly the case it exists to catch.

    A membership row is proof: a 1:1 chat has nobody to add or remove.
    """
    text = (
        "[8/25/26, 9:40:16 AM] Alice Meiring SO: Hello everyone\n"
        "[9/4/26, 10:29:35 AM] - +27 82 352 8161 changed the group name to 'Events'\n"
        "[9/15/26, 11:32:23 AM] - +7 996 195-97-83 added +7 914 279-89-62\n"
        "[9/27/26, 11:43:09 AM] +27 66 317 9679: <image omitted>\n"
    )
    export = _zip(tmp_path, "Local Community Events", text)

    result = whatsapp.parse(export)
    assert result.chats[0].is_group is True
    assert not any(m.is_self for m in result.messages)

    trimmed = whatsapp.parse(export, exclude_silent_groups=True)
    assert trimmed.chats == [], "an owner-silent group must be dropped when asked"
    assert trimmed.messages == [], "and its rows must go with it"
    assert trimmed.skipped.get("group thread the owner never spoke in") == 1


def test_a_group_the_owner_spoke_in_survives_the_gate(tmp_path):
    """The gate is about silence, not about being a group."""
    text = (
        "[9/4/26, 10:29:35 AM] - Alice changed the group name to 'Events'\n"
        "[9/5/26, 9:00:00 AM] Alice: anyone coming?\n"
        "[9/5/26, 9:01:00 AM] You: I am\n"
    )
    export = _zip(tmp_path, "Events", text)

    result = whatsapp.parse(export, exclude_silent_groups=True)
    assert len(result.chats) == 1
    assert result.chats[0].is_group is True
    assert any(m.is_self for m in result.messages)
    assert "group thread the owner never spoke in" not in result.skipped


def test_membership_evidence_is_read_even_when_service_rows_are_excluded(tmp_path):
    """The evidence is a fact about the chat, not a message we chose to keep.

    `include_service=False` drops the system rows from the store; it must not also
    erase the proof that the chat is a group.
    """
    text = (
        "[9/4/26, 10:29:35 AM] - Alice added Bob\n"
        "[9/5/26, 9:00:00 AM] Alice: hello\n"
    )
    export = _zip(tmp_path, "Events", text)

    result = whatsapp.parse(export, include_service=False)
    assert result.chats[0].is_group is True
    assert not any(m.raw_kind.startswith("system:") for m in result.messages)


# ---------------------------------------------------------------------- pipeline

def test_stage_copies_into_spool_and_ingest_verifies(tmp_path):
    export = _zip(tmp_path / "src", "Someone", BASIC)
    spool = tmp_path / "spool"
    store = tmp_path / "wa.rl"

    staged = ingest_module.stage([export], root=spool)
    assert staged and all(p.exists() for p in staged)
    assert spool in staged[0].parents
    assert export.exists(), "staging must copy, never move the user's download"

    report = ingest_module.ingest(root=spool, store=store, workers=1)
    assert report.ok, ingest_module.format_report(report)
    # BASIC is two real messages plus one `- ` system row; the preamble is counted.
    assert report.written == 3
    assert report.batches[0].skipped.get("preamble before first message") == 1

    # Staging the same file again is a no-op, not a copy of a copy.
    assert ingest_module.stage([export], root=spool) == staged


def test_ingest_twice_is_idempotent(tmp_path):
    export = _zip(tmp_path / "src", "Someone", BASIC)
    spool = tmp_path / "spool"
    store = tmp_path / "wa.rl"
    ingest_module.stage([export], root=spool)

    first = ingest_module.ingest(root=spool, store=store, workers=1)
    second = ingest_module.ingest(root=spool, store=store, workers=1)
    # The first run writes all three; the second finds them already stored and skips
    # them via the delta cutoff. The store must still hold exactly three keys, which
    # is what "idempotent" actually promises.
    assert first.written == 3
    assert second.written == 0
    assert sum(b.delta_dropped for b in second.batches) == 3

    conn = writer.connect(store)
    try:
        keys = writer.stored_keys(conn, "whatsapp")
    finally:
        conn.close()
    assert len(keys) == 3


def test_detection_ignores_a_json_file_in_the_spool(tmp_path):
    (tmp_path / "data.json").write_text('{"hello": 1}', encoding="utf-8")
    _zip(tmp_path, "chat", BASIC)
    batches = ingest_module.discover(tmp_path)
    by_name = {b.path.name: b.platform for b in batches}
    assert by_name["data.json"] is None
    assert by_name["chat.zip"] == "whatsapp"


# ---------------------------------------------------------------------- real files

@pytest.mark.skipif(_REAL is None, reason="no real WhatsApp export on this machine")
def test_real_export_loses_no_rows():
    result = whatsapp.parse(_REAL)
    text, _ = whatsapp.read_export(_REAL)
    headers = sum(1 for line in text.split("\n") if whatsapp._HEADER.match(line))
    assert len(result.messages) == headers, (
        f"{len(result.messages)} rows from {headers} headers"
    )
    assert len({m.key for m in result.messages}) == len(result.messages)
