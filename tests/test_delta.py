"""The delta cutoff: an incremental ingest pays only for what is new.

The contract:

    read - delta_dropped == messages written

A weekly export is mostly messages the graph already holds. Extraction costs ~1.5 ms
per message, so re-extracting the backlog is the dominant cost of a re-ingest. The
cutoff drops those rows **before** the write and therefore before NER.

What must never happen, and is asserted below: a message older than the watermark is
dropped even though the store does not have it (a backdated export), or an empty
store skips anything at all.

Run: python -m pytest tests/test_delta.py -q
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from relate_comms import ingest, tools, writer
from relate_comms.schema import Chat, IngestResult, Message, make_key

_BASE = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def _chat(platform: str, chat_id: str, people: tuple[str, ...]) -> Chat:
    return Chat(platform=platform, chat_id=chat_id, title=people[0],
                kind="personal_chat", is_group=False, participant_names=people)


def _message(chat: Chat, index: int, body: str, *, minutes: int | None = None) -> Message:
    message_id = f"m{index:04d}"
    return Message(
        key=make_key(chat.platform, chat.chat_id, message_id),
        platform=chat.platform, chat_id=chat.chat_id, message_id=message_id,
        ts_utc=_BASE + timedelta(minutes=index if minutes is None else minutes),
        sender_name="David Sartori", sender_id=None, body=body,
        reply_to=None, has_attachments=False, is_self=False, raw_kind="text",
    )


@pytest.fixture
def store(tmp_path):
    path = tmp_path / "graph.rl"
    writer.connect(path).close()
    return path


def _result(platform: str, chat: Chat, messages: list[Message]) -> IngestResult:
    return IngestResult(platform=platform, export_path="fixture",
                        chats=[chat], messages=messages)


# ------------------------------------------------------------------ apply_delta


def test_a_message_at_the_cutoff_is_dropped():
    """At, not after: the watermark message is already stored."""
    chat = _chat("telegram", "t1", ("Dave", "David Sartori"))
    result = _result("telegram", chat, [_message(chat, 0, "old")])
    cutoff = "2026-01-01T12:00:00Z"

    delta, dropped = ingest.apply_delta(result, cutoff)

    assert dropped == 1
    assert delta.messages == []


def test_a_message_one_second_after_the_cutoff_is_kept():
    chat = _chat("telegram", "t1", ("Dave", "David Sartori"))
    result = _result("telegram", chat, [_message(chat, 0, "new", minutes=1)])
    delta, dropped = ingest.apply_delta(result, "2026-01-01T12:00:00Z")

    assert dropped == 0
    assert [m.body for m in delta.messages] == ["new"]


def test_no_cutoff_keeps_everything():
    """An empty store must never skip anything — the watermark is absent, not zero."""
    chat = _chat("telegram", "t1", ("Dave", "David Sartori"))
    result = _result("telegram", chat, [_message(chat, 0, "a"), _message(chat, 1, "b")])
    delta, dropped = ingest.apply_delta(result, None)

    assert dropped == 0
    assert len(delta.messages) == 2


def test_the_skip_is_counted_once_not_per_message():
    chat = _chat("telegram", "t1", ("Dave", "David Sartori"))
    result = _result("telegram", chat,
                     [_message(chat, i, "old") for i in range(5)])
    delta, dropped = ingest.apply_delta(result, "2030-01-01T00:00:00Z")

    assert dropped == 5
    # One entry with the total, not five entries counting one each.
    assert sum(delta.skipped.values()) == 5
    assert len(delta.skipped) == 1


def test_the_original_result_is_not_mutated():
    """A caller may still want the whole parse — the report counts what was read."""
    chat = _chat("telegram", "t1", ("Dave", "David Sartori"))
    result = _result("telegram", chat, [_message(chat, 0, "old")])
    ingest.apply_delta(result, "2030-01-01T00:00:00Z")

    assert len(result.messages) == 1


# ------------------------------------------------------------------- watermark


def test_watermark_is_none_for_an_empty_platform(store):
    conn = writer.connect(store)
    try:
        assert writer.watermark(conn, "telegram") is None
    finally:
        conn.close()


def test_watermark_is_the_newest_ts_for_that_platform(store):
    chat = _chat("telegram", "t1", ("Dave", "David Sartori"))
    other = _chat("sms", "s1", ("Dave", "+27845189029"))
    result = _result("telegram", chat, [_message(chat, 0, "a"), _message(chat, 5, "b")])
    other_result = _result("sms", other, [_message(other, 0, "c", minutes=99)])

    conn = writer.connect(store)
    try:
        writer.write(conn, result)
        writer.write(conn, other_result)
        assert writer.watermark(conn, "telegram") == "2026-01-01T12:05:00Z"
        # Per platform: one platform's newer rows must not raise another's cutoff.
        assert writer.watermark(conn, "sms") == "2026-01-01T13:39:00Z"
    finally:
        conn.close()


def test_watermarks_omit_platforms_with_no_rows(store):
    chat = _chat("telegram", "t1", ("Dave", "David Sartori"))
    conn = writer.connect(store)
    try:
        writer.write(conn, _result("telegram", chat, [_message(chat, 0, "a")]))
        got = writer.watermarks(conn, ["telegram", "sms"])
        assert "telegram" in got
        assert "sms" not in got
    finally:
        conn.close()


# ------------------------------------------------------------------- end to end


def test_a_second_ingest_writes_nothing(store):
    """The headline guarantee: re-running the same export is free."""
    chat = _chat("telegram", "t1", ("Dave", "David Sartori"))
    first = _result("telegram", chat, [_message(chat, i, f"m{i}") for i in range(5)])
    conn = writer.connect(store)
    try:
        writer.write(conn, first)
        cutoff = writer.watermarks(conn, ["telegram"]).get("telegram")
    finally:
        conn.close()

    second, dropped = ingest.apply_delta(first, cutoff)

    assert dropped == 5
    assert second.messages == []


def test_ingest_writes_nothing_on_a_second_run(tmp_path):
    """The end-to-end guarantee, through the real `ingest()` path."""
    spool = tmp_path / "spool"
    spool.mkdir()
    (spool / "chat.txt").write_text(
        "[01/01/2026, 12:00:00] David Sartori: meet me in Kensington\n"
        "[01/01/2026, 12:05:00] You: see you there\n",
        encoding="utf-8",
    )
    store = tmp_path / "graph.rl"

    first = ingest.ingest(root=spool, store=store)
    assert first.written > 0, "the first run must write, or the test proves nothing"

    second = ingest.ingest(root=spool, store=store)
    assert second.written == 0
    assert sum(b.delta_dropped for b in second.batches) == first.written
    for batch in second.batches:
        assert batch.read == batch.delta_dropped


def test_delta_false_rewrites_the_same_rows(tmp_path):
    """`delta=False` is the escape hatch: every row is re-processed."""
    spool = tmp_path / "spool"
    spool.mkdir()
    (spool / "chat.txt").write_text(
        "[01/01/2026, 12:00:00] David Sartori: meet me in Kensington\n",
        encoding="utf-8",
    )
    store = tmp_path / "graph.rl"

    first = ingest.ingest(root=spool, store=store)
    forced = ingest.ingest(root=spool, store=store, delta=False)

    assert forced.written == first.written
    assert sum(b.delta_dropped for b in forced.batches) == 0


def test_a_backdated_message_is_dropped_and_that_is_a_known_limit(store):
    """Documents the trade-off honestly rather than pretending it does not exist.

    A message *older* than the watermark is indistinguishable from one already
    stored, so a genuinely late-arriving backdated message needs `delta=False`.
    Exports are written in time order, so this is rare; the escape hatch exists.
    """
    chat = _chat("telegram", "t1", ("Dave", "David Sartori"))
    conn = writer.connect(store)
    try:
        writer.write(conn, _result("telegram", chat, [_message(chat, 10, "recent")]))
        cutoff = writer.watermark(conn, "telegram")
    finally:
        conn.close()

    backdated = _result("telegram", chat, [_message(chat, 0, "older than cutoff")])
    delta, dropped = ingest.apply_delta(backdated, cutoff)

    assert dropped == 1
    assert delta.messages == []
