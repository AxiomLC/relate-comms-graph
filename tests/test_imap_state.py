"""The mailbox record, and the delta that reads it.

Two bugs these pin, both of which made a second IMAP ingest look like a first:

1. `cutoff_by_platform` was built from file batches only, so an IMAP fetch — which is
   passed as `extra_results` and appended to `parsed` later — contributed no platform.
   `writer.watermarks()` returned `{}`, `apply_delta(None)` kept everything, and every
   run rewrote the whole mailbox while the report said "same mailbox".
2. Nothing anywhere recorded which mailbox the graph held, so `.env` had to answer a
   question about the store.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from relate_comms import imap_state, ingest as ingest_module, writer
from relate_comms.schema import Chat, IngestResult, Message


def _result(platform: str = "email", n: int = 3, day: int = 0) -> IngestResult:
    result = IngestResult(platform=platform, export_path=f"imap://{platform}")
    chat = Chat(platform=platform, chat_id="c1", title="T", kind="personal_chat",
                is_group=False, participant_names=("A", "B"))
    result.chats.append(chat)
    for i in range(n):
        ts = datetime(2026, 1, 1 + day, 10, i, tzinfo=timezone.utc)
        result.messages.append(Message(
            key=f"{platform}:c1:m{i}", platform=platform, chat_id="c1",
            message_id=f"m{i}", ts_utc=ts, sender_name="A", sender_id=None,
            body=f"body {i}", reply_to=None, has_attachments=False,
            is_self=False, raw_kind="text", forwarded_from=None, saved_from=None,
        ))
    return result


# ------------------------------------------------------------------ the state file

def test_first_when_nothing_is_recorded_and_nothing_is_stored(tmp_path):
    assert imap_state.compare(None, email="a@x.com", store_has_email=False) == "first"


def test_stale_when_the_record_is_gone_but_rows_remain(tmp_path):
    """A hand-deleted record must not read as a first ingest — that would merge mailboxes."""
    assert imap_state.compare(None, email="a@x.com", store_has_email=True) == "stale"


def test_same_mailbox_same_window():
    rec = {"email": "a@x.com", "window": {"since": None, "until": None}}
    assert imap_state.compare(rec, email="A@x.com") == "same"


def test_a_different_mailbox_is_different():
    rec = {"email": "a@x.com", "window": {}}
    assert imap_state.compare(rec, email="b@y.com") == "different"


def test_a_wider_window_is_its_own_verdict():
    """The graph grows with the window; it is a union, not a mirror."""
    rec = {"email": "a@x.com", "window": {"since": None, "until": None}}
    assert imap_state.compare(rec, email="a@x.com", since="2026-01-01") == "window"


def test_save_load_clear_round_trip(tmp_path):
    imap_state.save(tmp_path, email="dev@w57th.agency", host="imap.hostinger.com",
                    port=993, folders=["INBOX"], messages=224,
                    ingested_at="2026-11-27T00:00:00Z")
    loaded = imap_state.load(tmp_path)
    assert loaded["email"] == "dev@w57th.agency"
    assert loaded["messages"] == 224
    assert imap_state.clear(tmp_path) is True
    assert imap_state.load(tmp_path) is None
    assert imap_state.clear(tmp_path) is False


def test_a_corrupt_record_reads_as_absent_rather_than_raising(tmp_path):
    imap_state.path_for(tmp_path).write_text("{not json", encoding="utf-8")
    assert imap_state.load(tmp_path) is None


# ------------------------------------------------------------------ the delta fix

def test_delta_reads_the_watermark_for_an_extra_result(tmp_path):
    """The regression: an IMAP fetch passed as `extra_results` must reach `apply_delta`."""
    store = tmp_path / "g.rl"
    conn = writer.connect(store)
    try:
        writer.write(conn, _result(day=0))
    finally:
        conn.close()

    # A second fetch of the same mailbox, one day later: only the new rows survive.
    later = _result(day=1)
    report = ingest_module.ingest(
        root=tmp_path / "empty_spool",
        store=store,
        profile_dir=tmp_path / "profile",
        extra_results=[later],
        workers=1,
        delta=True,
    )
    assert report.written == 3, report.delta_note or "delta did not drop the old rows"
