"""Stage 2 acceptance: ingest twice -> identical counts; both export shapes agree.

Runs against the real exports on this machine when present, and always against the
tracked synthetic fixture so the test is meaningful on a clean clone.

Run: python -m pytest tests -q
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import pytest

from relate_comms import writer
from relate_comms.adapters import telegram
from relate_comms.paths import spool_dir, fixture
from relate_comms.schema import make_key

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DUMMY = str(fixture("telegram", "bulk").parent)
DUMMY_SINGLE = str(fixture("telegram", "single").parent)

# Real exports: spool first, then any archived copy under the data root.
# Tests skip cleanly when neither exists (clean clone / CI).
_REAL_CANDIDATES = [
    spool_dir() / "DataExport_2026-11-14" / "result.json",
    spool_dir() / "result.json",
]
_REAL_SINGLE_CANDIDATES = [
    spool_dir() / "ChatExport_2026-11-14 (1)" / "result.json",
]

SERGIO_ID = "1617561215"


def _skip_if_missing(path: str) -> str:
    if not os.path.exists(path):
        pytest.skip(f"real export not on this machine: {path}")
    return path


def _first_existing(candidates) -> str:
    for candidate in candidates:
        if os.path.exists(candidate):
            return str(candidate)
    pytest.skip("no real export under the data root")
    raise AssertionError("unreachable")


# --------------------------------------------------------------------------- unit

def test_text_is_str_or_list():
    assert telegram._join_text("plain") == "plain"
    assert telegram._join_text(["a", {"type": "bold", "text": "b"}, "c"]) == "abc"
    # Entity with no text must not crash or inject None.
    assert telegram._join_text([{"type": "link"}]) == ""
    assert telegram._join_text("") == ""


def test_ts_prefers_unixtime_and_flags_missing_offset():
    with_u = telegram._parse_ts({"date_unixtime": "1693753543", "date": "2023-09-03T17:05:43"})
    assert with_u == datetime.fromtimestamp(1693753543, tz=timezone.utc)
    # No unixtime: local `date` read as UTC rather than machine-local.
    no_u = telegram._parse_ts({"date": "2022-03-16T19:23:47"})
    assert no_u == datetime(2022, 3, 16, 19, 23, 47, tzinfo=timezone.utc)
    assert telegram._parse_ts({}) is None


def test_bare_chat_is_detected():
    bare = os.path.join(DUMMY_SINGLE, "result.json")
    document = json.load(open(bare, encoding="utf-8"))
    chats, warnings = telegram._iter_chats(document)
    assert len(chats) == 1, "single fixture must be one bare Chat, not a Result wrapper"
    assert any("bare Chat" in w for w in warnings)

    result = telegram.parse(bare, self_id="user900000")
    assert len(result.messages) == len(document["messages"])


def test_bulk_fixture_is_a_result_wrapper():
    document = json.load(open(os.path.join(DUMMY, "result.json"), encoding="utf-8"))
    assert "chats" in document and "messages" not in document
    assert document["chats"]["list"], "bulk fixture must contain chats"


def test_key_is_not_just_message_id():
    key = make_key("telegram", "1617561215", "99641")
    assert key == "telegram:1617561215:99641"
    assert key.count(":") == 2


# ----------------------------------------------------------------- synthetic e2e

def test_dummy_download_parses_without_dropping_service_rows():
    result = telegram.parse(DUMMY)
    assert result.messages, "synthetic export yielded nothing"
    kinds = {m.raw_kind for m in result.messages}
    assert any(k.startswith("service:") for k in kinds), "service rows must be kept"
    # Nothing may vanish without a count.
    for message in result.messages:
        assert message.ts_utc.tzinfo is not None


def test_window_filter_counts_skips():
    since = datetime(2022, 3, 20, tzinfo=timezone.utc)
    result = telegram.parse(DUMMY, since=since)
    assert result.skipped.get("before window", 0) > 0
    assert all(m.ts_utc >= since for m in result.messages)


# -------------------------------------------------------------------- real files

def test_bulk_and_single_export_agree():
    bulk_path = _first_existing(_REAL_CANDIDATES)
    single_path = _first_existing(_REAL_SINGLE_CANDIDATES)

    # self_id pinned: is_self must not depend on which file we opened.
    owner = "user1426445212"
    bulk = telegram.parse(bulk_path, include_service=False, self_id=owner)
    single = telegram.parse(single_path, include_service=False, self_id=owner)

    single_keys = {m.key for m in single.messages}
    bulk_keys = {m.key for m in bulk.messages}
    assert single_keys <= bulk_keys, "single-chat export is not a subset of the bulk one"

    by_key = {m.key: m for m in bulk.messages}
    for message in single.messages:
        assert by_key[message.key] == message, f"{message.key} differs between exports"


def test_owner_is_stable_across_exports(tmp_path):
    """Regression: a per-file owner guess made is_self flip between exports."""
    bulk_path = _first_existing(_REAL_CANDIDATES)
    single_path = _first_existing(_REAL_SINGLE_CANDIDATES)
    profile = tmp_path / "profile"

    # First parse (bulk) infers and persists the owner...
    first = telegram.parse(bulk_path, profile_dir=profile, include_service=False)
    # ...so the single-chat file reuses it instead of guessing from 2 people.
    second = telegram.parse(single_path, profile_dir=profile, include_service=False)

    assert first.messages and second.messages
    first_self = {m.key: m.is_self for m in first.messages}
    for message in second.messages:
        if message.key in first_self:
            assert message.is_self == first_self[message.key], (
                f"{message.key}: is_self differs between exports"
            )


def test_batching_is_idempotent_and_linear(tmp_path):
    """UNWIND batching must not change idempotency, and must stay linear.

    Per-row MERGE ran at 133 msg/s (1k) degrading to 64 msg/s (10k). If the
    batched path ever regresses to per-row, the ratio check below catches it.
    """
    import time

    from datetime import timedelta

    from relate_comms.schema import Chat, IngestResult, Message

    def build(n: int) -> IngestResult:
        base = datetime(2025, 1, 1, tzinfo=timezone.utc)
        chats: dict[str, Chat] = {}
        messages = []
        for i in range(n):
            cid, mid = str(i % 100), str(i)
            messages.append(Message(
                key=make_key("telegram", cid, mid), platform="telegram",
                chat_id=cid, message_id=mid, ts_utc=base + timedelta(minutes=i),
                sender_name="Person A", sender_id="user900000", body="x" * 40,
                reply_to=None, has_attachments=False, is_self=True, raw_kind="text",
            ))
            chats[cid] = Chat(platform="telegram", chat_id=cid, title="T",
                              kind="personal_chat", is_group=False)
        return IngestResult(platform="telegram", export_path="bench",
                            chats=list(chats.values()), messages=messages)

    def time_write(store, result) -> float:
        conn = writer.connect(store)
        try:
            started = time.perf_counter()
            writer.write(conn, result)
            return time.perf_counter() - started
        finally:
            conn.close()

    small = build(500)
    large = build(5000)

    small_time = time_write(tmp_path / "small.rl", small)
    large_time = time_write(tmp_path / "large.rl", large)

    # Batching is linear; per-row degrades superlinearly. 10x rows should cost
    # well under 10x wall time, with generous slack for CI noise.
    assert large_time < small_time * 20, (
        f"suspected per-row regression: {large_time:.3f}s for 10x rows "
        f"vs {small_time:.3f}s"
    )

    # And writing the same result twice adds nothing.
    store = tmp_path / "idem.rl"
    result = build(200)
    conn = writer.connect(store)
    try:
        writer.write(conn, result)
        first = writer.stored_keys(conn, "telegram")
        writer.write(conn, result)
        second = writer.stored_keys(conn, "telegram")
    finally:
        conn.close()
    assert first == second
    assert len(second) == 200


def test_ingest_twice_is_idempotent(tmp_path):
    source = str(_first_existing(_REAL_CANDIDATES)) if any(
        os.path.exists(p) for p in _REAL_CANDIDATES
    ) else DUMMY
    store = tmp_path / "stage2.rl"

    # Window derived from the data, so the test is date-independent: whichever
    # source is available, we take everything it has.
    from datetime import timedelta
    earliest = min(m.ts_utc for m in telegram.parse(source, self_id="user900000").messages)
    window = earliest - timedelta(days=1)

    first, written1, verify1 = writer.ingest_file(
        store, source, parser=telegram.parse, include_service=False,
        since=window, self_id="user900000",
    )
    assert verify1["ok"], verify1

    conn = writer.connect(store)
    try:
        keys_after_first = writer.stored_keys(conn, "telegram")
        kinds_first = writer.counts_by_kind(conn, "telegram")
    finally:
        conn.close()

    second, written2, verify2 = writer.ingest_file(
        store, source, parser=telegram.parse, include_service=False,
        since=window, self_id="user900000",
    )
    assert verify2["ok"], verify2
    assert written1 == written2

    conn = writer.connect(store)
    try:
        keys_after_second = writer.stored_keys(conn, "telegram")
        kinds_second = writer.counts_by_kind(conn, "telegram")
    finally:
        conn.close()

    assert keys_after_first == keys_after_second, "second ingest created new rows"
    assert len(keys_after_first) == written1["messages"], "store row count != rows written"
    assert kinds_first == kinds_second, "kind counts drifted between ingests"
    assert first.messages and second.messages
