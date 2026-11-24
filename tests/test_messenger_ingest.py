"""Messenger HTML export -> canonical rows.

Every test names a trap found in the real archive (TECHREADME.md §5). The HTML
fragments are hand-built so the suite runs on a clean clone.

Run: python -m pytest tests -q
"""
from __future__ import annotations

import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from relate_comms import ingest as ingest_module
from relate_comms import writer
from relate_comms.adapters import messenger

# The sample world the app generates, committed to `spool/real/` so these tests run on
# any clone. Not a personal export.
REAL = (Path(__file__).resolve().parents[1] / "spool" / "real" / "messenger"
        / "facebook-sampleuser-2026-11-01-1G300tUX.zip")


def _section(sender: str, body: str, stamp: str | None) -> str:
    footer = f"<footer><div class=\"_a72d\">{stamp}</div></footer>" if stamp else ""
    return (f'<section class="_a6-g"><h2>{sender}</h2>'
            f'<div class="_2ph_ _a6-p"><div><div></div><div>{body}</div>'
            f'<div></div><div></div></div></div>{footer}</section>')


def _archive(tmp_path: Path, threads: dict[str, list[str]]) -> Path:
    """threads: folder -> list of section html. One `message_1.html` per thread."""
    target = tmp_path / "facebook-davidsartori796-2026-11-14-TEST.zip"
    with zipfile.ZipFile(target, "w") as archive:
        for folder, sections in threads.items():
            path = f"your_facebook_activity/messages/inbox/{folder}/message_1.html"
            archive.writestr(path, "<html><body><main>" + "".join(sections)
                             + "</main></body></html>")
    return target


# --------------------------------------------------------------------------- unit

def test_sender_is_the_h2_unlike_instagram():
    html = _section("David Sartori", "hello", "Jan 06, 2026 8:09:48 pm")
    sender, body_html, footer = messenger._section_parts(html)
    assert sender == "David Sartori"
    assert messenger._text(body_html) == "hello"
    assert footer and "Jan 06" in footer


def test_metadata_sections_have_no_footer():
    """`Participants: ...` is a section with an h2 and no footer. Not a message."""
    participants = (
        '<section class="_a6-g"><h2>Participants: David Sartori, Alex Albarran</h2>'
        '<div></div></section>'
    )
    sender, body_html, footer = messenger._section_parts(participants)
    assert sender.startswith("Participants:")
    assert footer is None, "a section with no footer must be treated as metadata"


def test_timestamp_parsing_and_offset():
    ts = messenger._parse_ts("Jan 06, 2026 8:09:48 pm", 0)
    assert ts == datetime(2026, 1, 6, 20, 9, 48, tzinfo=timezone.utc)
    assert messenger._parse_ts("Jan 06, 2026 12:00:00 am", 0).hour == 0
    assert messenger._parse_ts("Jan 06, 2026 12:30:00 pm", 0).hour == 12
    est = messenger._parse_ts("Jan 06, 2026 8:09:48 pm", -5)
    assert est.hour == 1 and est.day == 7


def test_thread_id_uses_numeric_suffix_not_username():
    """People rename; the trailing numeric id is stable."""
    member = ("your_facebook_activity/messages/inbox/kennysettens_1016/message_1.html")
    assert messenger.thread_key_from_path(member) == "1016"
    renamed = ("your_facebook_activity/messages/inbox/kenny_new_name_1016/message_1.html")
    assert messenger.thread_key_from_path(renamed) == "1016"


def test_html_text_unescapes_and_keeps_lines():
    fragment = "<div><div></div><div>a &amp; b</div><div>line two</div><div></div></div>"
    assert messenger._text(fragment) == "a & b\nline two"


# ---------------------------------------------------------------------- behaviour

def test_messages_are_reversed_to_chronological(tmp_path):
    """The export writes newest-first; the thread must read forwards."""
    archive = _archive(tmp_path, {"alice_111": [
        _section("Alice", "second", "Jan 02, 2026 10:00:00 am"),
        _section("Alice", "first", "Jan 01, 2026 10:00:00 am"),
    ]})
    result = messenger.parse(archive, self_id="David Sartori")
    assert [m.body for m in result.messages] == ["first", "second"]


def test_is_self_from_stated_sender(tmp_path):
    archive = _archive(tmp_path, {"alice_111": [
        _section("David Sartori", "mine", "Jan 01, 2026 10:00:00 am"),
        _section("Alice", "theirs", "Jan 01, 2026 10:01:00 am"),
    ]})
    result = messenger.parse(archive, self_id="David Sartori")
    by_body = {m.body: m for m in result.messages}
    assert by_body["mine"].is_self is True
    assert by_body["theirs"].is_self is False


def test_owner_inferred_by_thread_breadth_not_volume(tmp_path):
    """Regression: a spam thread of 8171 rows must not win the ownership guess.

    Real archive had `Facebook user` sending 8171 messages in one thread while the
    owner sent 92 across 35. Counting messages elected the spammer as "me".
    """
    threads: dict[str, list[str]] = {}
    # One loud thread full of spam.
    threads["spam_900"] = [
        _section("Facebook user", f"buy now {i}", "Jan 01, 2026 09:00:00 am")
        for i in range(40)
    ]
    # The owner spread thinly across several threads, each with a different contact.
    for n in range(4):
        threads[f"friend{n}_{200 + n}"] = [
            _section("David Sartori", "hi", "Jan 01, 2026 10:00:00 am"),
            _section(f"Friend{n}", "hey", "Jan 01, 2026 10:01:00 am"),
        ]

    archive = _archive(tmp_path, threads)
    result = messenger.parse(archive)
    assert any("owner inferred as 'David Sartori'" in w for w in result.warnings), result.warnings
    assert sum(m.is_self for m in result.messages) == 4


def test_media_paths_are_kept_but_not_statd(tmp_path):
    archive = _archive(tmp_path, {"alice_111": [
        '<section class="_a6-g"><h2>Alice</h2><div><div></div><div></div>'
        '<div><a href="x/photos/1.jpg"><img src="your_facebook_activity/messages/'
        'inbox/alice_111/photos/1.jpg" /></a></div></div>'
        '<footer><div>Jan 01, 2026 10:00:00 am</div></footer></section>',
    ]})
    result = messenger.parse(archive, self_id="David Sartori")
    assert len(result.attachments) == 1
    assert result.attachments[0].path.endswith("photos/1.jpg")
    assert result.messages[0].has_attachments is True


def test_missed_call_is_kinded_not_attributed(tmp_path):
    archive = _archive(tmp_path, {"kenny_1016": [
        _section("Kenny", "You missed a call from Kenny.", "Jan 06, 2026 8:10:30 pm"),
    ]})
    result = messenger.parse(archive, self_id="David Sartori")
    assert result.messages[0].raw_kind == "call"

    excluded = messenger.parse(archive, self_id="David Sartori", include_service=False)
    assert not excluded.messages
    assert excluded.skipped.get("service excluded by request") == 1


def test_same_second_duplicate_rows_stay_distinct(tmp_path):
    archive = _archive(tmp_path, {"alice_111": [
        _section("Alice", "", "Jan 01, 2026 10:00:00 am") for _ in range(3)
    ]})
    result = messenger.parse(archive, self_id="David Sartori")
    assert len({m.key for m in result.messages}) == 3
    assert result.unknown_kinds.get("same-second repeats") == 1


def test_key_is_stable_across_reparse(tmp_path):
    archive = _archive(tmp_path, {"alice_111": [
        _section("Alice", "hello", "Jan 01, 2026 10:00:00 am"),
    ]})
    first = messenger.parse(archive, self_id="David Sartori")
    again = messenger.parse(archive, self_id="David Sartori")
    assert [m.key for m in first.messages] == [m.key for m in again.messages]


def test_filtered_threads_are_included_by_default(tmp_path):
    target = tmp_path / "fb.zip"
    with zipfile.ZipFile(target, "w") as archive:
        for folder, sections in (("inbox", "a"), ("filtered_threads", "b")):
            archive.writestr(
                f"your_facebook_activity/messages/{folder}/x_1/message_1.html",
                _section("Alice", sections, "Jan 01, 2026 10:00:00 am"))
    assert len(messenger.parse(target, self_id="David Sartori").messages) == 2
    assert len(messenger.parse(target, self_id="David Sartori",
                               include_filtered=False).messages) == 1


def test_detect_accepts_messenger_zip(tmp_path):
    archive = _archive(tmp_path, {"alice_111": [
        _section("Alice", "hello", "Jan 01, 2026 10:00:00 am")]})
    assert messenger.detect(archive) is True
    assert ingest_module.detect_platform(archive) == "messenger"


def test_pipeline_ingest_and_idempotency(tmp_path):
    archive = _archive(tmp_path, {"alice_111": [
        _section("Alice", "hello", "Jan 01, 2026 10:00:00 am"),
        _section("David Sartori", "hi back", "Jan 01, 2026 10:01:00 am"),
    ]})
    spool = tmp_path / "spool"
    store = tmp_path / "fb.rl"
    ingest_module.stage([archive], root=spool)

    first = ingest_module.ingest(root=spool, store=store, workers=1, self_id="David Sartori")
    assert first.ok, ingest_module.format_report(first)
    assert first.written == 2

    second = ingest_module.ingest(root=spool, store=store, workers=1, self_id="David Sartori")
    conn = writer.connect(store)
    try:
        keys = writer.stored_keys(conn, "messenger")
    finally:
        conn.close()
    # Two keys, not four: the second run skips them as already stored.
    assert len(keys) == 2 and second.written == 0


def test_silent_group_is_dropped_only_when_asked(tmp_path):
    """A group the owner never spoke in is not a conversation they had.

    Measured on the real archive: all 70 Messenger group threads are owner-silent and
    hold 9,513 of the 10,605 Messenger messages. Off by default — the store is whole
    unless asked otherwise — and counted when on.
    """
    archive = _archive(tmp_path, {
        "silent_101": [
            _section("Alice", "yo", "Jan 01, 2026 10:00:00 am"),
            _section("Bob", "hey", "Jan 01, 2026 10:01:00 am"),
        ],
        "mine_102": [
            _section("Alice", "yo", "Jan 01, 2026 10:00:00 am"),
            _section("David Sartori", "hello", "Jan 01, 2026 10:01:00 am"),
        ],
    })

    kept = messenger.parse(archive, self_id="David Sartori")
    assert len(kept.chats) == 2
    assert len(kept.messages) == 4

    trimmed = messenger.parse(archive, self_id="David Sartori",
                              exclude_silent_groups=True)
    assert len(trimmed.chats) == 1
    assert len(trimmed.messages) == 2
    # Never silently: the drop is counted with its reason.
    assert trimmed.skipped.get("group thread the owner never spoke in") == 1


def test_silent_gate_never_drops_a_one_to_one(tmp_path):
    """The rule is about *groups*. A 1:1 thread the owner never replied to is still
    a conversation someone had with them, and is a view toggle, not a drop."""
    archive = _archive(tmp_path, {"alice_111": [
        _section("Alice", "hello", "Jan 01, 2026 10:00:00 am"),
    ]})
    result = messenger.parse(archive, self_id="David Sartori",
                             exclude_silent_groups=True)
    assert len(result.chats) == 1
    assert len(result.messages) == 1


# ---------------------------------------------------------------------- real file

@pytest.mark.skipif(not REAL.exists(), reason="no real Messenger export on this machine")
def test_real_archive_parses_with_stated_senders():
    result = messenger.parse(REAL, self_id="Mark Jones")
    # A floor, not a count: the world is regenerated and its size moves with the knobs.
    # What must hold is that the archive is substantial and every row is well-formed.
    assert len(result.messages) > 100
    assert result.chats
    # Every row has an aware timestamp and a chattable sender.
    assert all(m.ts_utc.tzinfo is not None for m in result.messages)
    # is_self is decided by the stated sender, so it must be a strict subset.
    self_rows = sum(m.is_self for m in result.messages)
    assert 0 < self_rows < len(result.messages)
