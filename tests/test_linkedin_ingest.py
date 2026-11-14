"""LinkedIn `messages.csv` -> canonical rows.

Traps named here were all found in the real Basic export (§10). Fragments are
hand-built so the suite runs on a clean clone.

Run: python -m pytest tests -q
"""
from __future__ import annotations

import csv
import io
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from relate_comms import ingest as ingest_module
from relate_comms import writer
from relate_comms.adapters import linkedin

REAL = Path.home() / "Downloads" / "Basic_LinkedInDataExport_11-14-2026.zip.zip"

COLUMNS = ["CONVERSATION ID", "CONVERSATION TITLE", "FROM", "SENDER PROFILE URL",
           "TO", "RECIPIENT PROFILE URLS", "DATE", "SUBJECT", "CONTENT",
           "FOLDER", "ATTACHMENTS"]


def _row(**kw) -> dict[str, str]:
    base = {c: "" for c in COLUMNS}
    base.update({
        "CONVERSATION ID": "conv-1",
        "FROM": "David Sartori",
        "TO": "Alice Smith",
        "DATE": "2026-01-01 10:00:00 UTC",
        "CONTENT": "hello",
        "FOLDER": "INBOX",
    })
    base.update(kw)
    return base


def _archive(tmp_path: Path, rows: list[dict[str, str]], name: str = "li.zip") -> Path:
    target = tmp_path / name
    target.parent.mkdir(parents=True, exist_ok=True)
    buffer = io.StringIO()
    writer_ = csv.DictWriter(buffer, fieldnames=COLUMNS, quoting=csv.QUOTE_ALL)
    writer_.writeheader()
    writer_.writerows(rows)
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr("messages.csv", buffer.getvalue())
    return target


# --------------------------------------------------------------------------- unit

def test_basic_export_contains_messages():
    """§9.1.3 said the larger archive was required. The real Basic export disproves it."""
    if not REAL.exists():
        pytest.skip("real export not on this machine")
    assert linkedin.detect(REAL) is True


def test_recipients_are_split_on_semicolon_never_comma():
    """Real value: `Steve Mikano CIA, AIC-M, AINS, SSBB` is ONE person."""
    assert linkedin._split_recipients("Steve Mikano CIA, AIC-M, AINS, SSBB") == [
        "Steve Mikano CIA, AIC-M, AINS, SSBB"
    ]
    assert linkedin._split_recipients("A;B") == ["A", "B"]
    assert linkedin._split_recipients("") == []


def test_timestamp_is_already_utc():
    ts = linkedin._parse_ts("2026-11-13 13:01:58 UTC")
    assert ts == datetime(2026, 11, 13, 13, 1, 58, tzinfo=timezone.utc)
    # A declared offset is honoured, not assumed.
    assert linkedin._parse_ts("2026-11-13 13:01:58 -05:00").hour == 18
    assert linkedin._parse_ts("not a date") is None


def test_nbsp_and_newlines_are_normalised():
    cleaned = linkedin._clean("Happy to chat.\xa0 i can chat\nthis afternoon")
    assert "\xa0" not in cleaned
    assert cleaned == "Happy to chat. i can chat\nthis afternoon"


def test_thread_id_is_short_and_stable():
    raw = "2-ZGI2YTNiODYtMWVmMi00MWIwLWE5OTQtMzIxYzFmNjU0Y2JjXzEwMA=="
    first = linkedin._thread_id(raw)
    assert first == linkedin._thread_id(raw)
    assert first.startswith("li_") and "/" not in first and "=" not in first


# ---------------------------------------------------------------------- behaviour

def test_sender_and_recipient_name_is_self(tmp_path):
    archive = _archive(tmp_path, [
        _row(CONTENT="mine", **{"FROM": "David Sartori"}),
        _row(CONTENT="theirs", **{"FROM": "Alice Smith", "TO": "David Sartori"}),
    ])
    result = linkedin.parse(archive, self_id="David Sartori")
    by_body = {m.body: m for m in result.messages}
    assert by_body["mine"].is_self is True
    assert by_body["theirs"].is_self is False


def test_chat_title_falls_back_to_the_other_person(tmp_path):
    """CONVERSATION TITLE is empty for 1:1 DMs."""
    archive = _archive(tmp_path, [_row()])
    result = linkedin.parse(archive, self_id="David Sartori")
    assert result.chats[0].title == "Alice Smith"
    assert not result.chats[0].is_group


def test_explicit_conversation_title_wins(tmp_path):
    archive = _archive(tmp_path, [_row(**{"CONVERSATION TITLE": "InMail: Hiring"})])
    result = linkedin.parse(archive, self_id="David Sartori")
    assert result.chats[0].title == "InMail: Hiring"


def test_linkedin_member_placeholder_is_not_a_chat_title(tmp_path):
    archive = _archive(tmp_path, [
        _row(**{"FROM": "LinkedIn Member", "TO": "David Sartori"}),
    ])
    result = linkedin.parse(archive, self_id="David Sartori")
    assert result.chats[0].title != "LinkedIn Member"


def test_archived_threads_included_by_default(tmp_path):
    archive = _archive(tmp_path, [_row(FOLDER="ARCHIVE")])
    assert len(linkedin.parse(archive, self_id="David Sartori").messages) == 1
    assert not linkedin.parse(archive, self_id="David Sartori",
                              include_archived=False).messages


def test_same_second_duplicates_stay_distinct(tmp_path):
    archive = _archive(tmp_path, [_row(CONTENT="ok") for _ in range(3)])
    result = linkedin.parse(archive, self_id="David Sartori")
    assert len({m.key for m in result.messages}) == 3
    assert result.unknown_kinds.get("same-second repeats") == 1


def test_owner_inferred_by_conversation_breadth(tmp_path):
    """A long thread must not elect its own author (the Messenger lesson)."""
    rows = [_row(**{"FROM": "Loud Spammer", "TO": "David Sartori", "CONTENT": f"buy {i}"})
            for i in range(30)]
    for n in range(3):
        rows.append(_row(**{"CONVERSATION ID": f"c{n}", "FROM": "David Sartori",
                            "TO": f"Friend{n}"}))
        rows.append(_row(**{"CONVERSATION ID": f"c{n}", "FROM": f"Friend{n}",
                            "TO": "David Sartori"}))
    archive = _archive(tmp_path, rows)
    result = linkedin.parse(archive)
    assert any("owner inferred as 'David Sartori'" in w for w in result.warnings)


def test_key_is_stable(tmp_path):
    archive = _archive(tmp_path, [_row()])
    first = linkedin.parse(archive, self_id="David Sartori")
    again = linkedin.parse(archive, self_id="David Sartori")
    assert [m.key for m in first.messages] == [m.key for m in again.messages]


def test_window_filter_counts_skips(tmp_path):
    archive = _archive(tmp_path, [
        _row(DATE="2026-01-01 10:00:00 UTC"),
        _row(DATE="2026-06-01 10:00:00 UTC"),
    ])
    since = datetime(2026, 5, 1, tzinfo=timezone.utc)
    result = linkedin.parse(archive, since=since, self_id="David Sartori")
    assert len(result.messages) == 1
    assert result.skipped.get("before window") == 1


def test_detection_prefers_linkedin_over_messenger(tmp_path):
    archive = _archive(tmp_path, [_row()])
    assert ingest_module.detect_platform(archive) == "linkedin"


def test_tz_offset_does_not_break_a_utc_adapter(tmp_path):
    """Regression: LinkedIn states UTC, so it rejects `tz_offset_hours`.

    The CLI passes `--tz-offset` for every file. Without filtering, one WhatsApp export
    in the spool made the LinkedIn ingest fail with a TypeError.
    """
    li = _archive(tmp_path / "a", [_row()], name="li.zip")
    spool = tmp_path / "spool"
    store = tmp_path / "mixed.rl"
    ingest_module.stage([li], root=spool)

    report = ingest_module.ingest(root=spool, store=store, workers=1,
                                  self_id="David Sartori", tz_offset_hours=-5)
    assert report.ok, ingest_module.format_report(report)
    assert report.written == 1


def test_pipeline_ingest_and_idempotency(tmp_path):
    archive = _archive(tmp_path, [_row(CONTENT="a"), _row(CONTENT="b")])
    spool = tmp_path / "spool"
    store = tmp_path / "li.rl"
    ingest_module.stage([archive], root=spool)

    first = ingest_module.ingest(root=spool, store=store, workers=1,
                                 self_id="David Sartori")
    assert first.ok, ingest_module.format_report(first)
    assert first.written == 2

    ingest_module.ingest(root=spool, store=store, workers=1, self_id="David Sartori")
    conn = writer.connect(store)
    try:
        keys = writer.stored_keys(conn, "linkedin")
    finally:
        conn.close()
    assert len(keys) == 2


# ---------------------------------------------------------------------- real file

@pytest.mark.skipif(not REAL.exists(), reason="no real LinkedIn export on this machine")
def test_real_export_rows_match_csv():
    result = linkedin.parse(REAL)
    rows = linkedin.read_rows(REAL)
    assert len(result.messages) == len(rows)
    assert len({m.key for m in result.messages}) == len(rows)
    assert all(m.ts_utc.tzinfo is not None for m in result.messages)
    assert 0 < sum(m.is_self for m in result.messages) < len(rows)
