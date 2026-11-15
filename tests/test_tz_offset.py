"""The timezone offset is part of every wall-clock message key.

Telegram, WhatsApp and Messenger export local time with no offset, so `ts_utc` —
and therefore `Message.key`, which hashes the timestamp — depends on the offset the
caller declared. Nothing used to persist it, so:

    ingest --tz-offset -5   -> 10,605 Messenger rows keyed at -5
    verify_ingest           -> re-parses at 0, reports all 10,605 missing

The store was intact; it was being read differently. These tests pin the fix:
the offset is recorded per platform and reused by every later re-parse.

Run: python -m pytest tests -q
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from relate_comms import identity, ingest as ingest_module, writer
from relate_comms.adapters import whatsapp
from relate_comms.schema import Chat, IngestResult, Message

_BASE = datetime(2026, 3, 1, 9, 0, tzinfo=timezone.utc)


# ------------------------------------------------------------------ identity

def test_offset_round_trips_per_platform(tmp_path):
    identity.save_tz_offset(tmp_path, "whatsapp", -5)
    identity.save_tz_offset(tmp_path, "telegram", 0)
    assert identity.load_tz_offset(tmp_path, "whatsapp") == -5
    assert identity.load_tz_offset(tmp_path, "telegram") == 0
    assert identity.load_tz_offset(tmp_path, "messenger") is None


def test_offset_does_not_disturb_the_owner(tmp_path):
    identity.save_owner(tmp_path, "user1", evidence="test", platform="telegram")
    identity.save_tz_offset(tmp_path, "telegram", -5)
    assert identity.load_owner(tmp_path, "telegram") == "user1"
    assert identity.load_tz_offset(tmp_path, "telegram") == -5


def test_saving_an_owner_does_not_drop_the_offset(tmp_path):
    """Adapters call `save_owner` during parse; it must not rewrite the file."""
    identity.save_tz_offset(tmp_path, "whatsapp", -5)
    identity.save_owner(tmp_path, "David", evidence="inferred", platform="messenger")
    assert identity.load_tz_offset(tmp_path, "whatsapp") == -5
    assert identity.load_owner(tmp_path, "messenger") == "David"


def test_saving_an_offset_does_not_drop_the_owner(tmp_path):
    identity.save_owner(tmp_path, "David", evidence="inferred", platform="messenger")
    identity.save_tz_offset(tmp_path, "whatsapp", -5)
    assert identity.load_owner(tmp_path, "messenger") == "David"
    assert identity.load_tz_offset(tmp_path, "whatsapp") == -5


def test_changing_an_offset_is_refused_on_a_populated_store(tmp_path):
    """A different offset re-keys every row, so it must not happen by accident."""
    identity.save_tz_offset(tmp_path, "whatsapp", -5)
    with pytest.raises(ValueError, match="duplicate every message"):
        identity.save_tz_offset(tmp_path, "whatsapp", 0)
    assert identity.load_tz_offset(tmp_path, "whatsapp") == -5


def test_changing_an_offset_is_allowed_on_an_empty_store(tmp_path):
    """The normal case while building: wipe the store, re-ingest, no complaint."""
    identity.save_tz_offset(tmp_path, "whatsapp", -5)
    identity.save_tz_offset(tmp_path, "whatsapp", 0, allow_change=True)
    assert identity.load_tz_offset(tmp_path, "whatsapp") == 0


def test_saving_the_same_offset_twice_is_fine(tmp_path):
    identity.save_tz_offset(tmp_path, "whatsapp", -5)
    identity.save_tz_offset(tmp_path, "whatsapp", -5)
    assert identity.load_tz_offset(tmp_path, "whatsapp") == -5


def test_a_corrupt_profile_is_not_a_crash(tmp_path):
    (tmp_path / "identity.json").write_text("{not json", encoding="utf-8")
    assert identity.load_tz_offset(tmp_path, "whatsapp") is None
    identity.save_tz_offset(tmp_path, "whatsapp", -5)
    assert identity.load_tz_offset(tmp_path, "whatsapp") == -5


# -------------------------------------------------------------- _kwargs_for

def test_kwargs_are_resolved_per_platform():
    """One spool, two timezones: each batch gets its own offset."""
    kwargs = {"tz_offsets": {"whatsapp": -5, "telegram": 0}, "since": None}
    assert ingest_module._kwargs_for("whatsapp", kwargs)["tz_offset_hours"] == -5
    assert ingest_module._kwargs_for("telegram", kwargs)["tz_offset_hours"] == 0
    # A platform with no recorded offset keeps the adapter's default.
    assert "tz_offset_hours" not in ingest_module._kwargs_for("messenger", kwargs)


def test_a_utc_platform_never_receives_an_offset():
    """LinkedIn states UTC; handing it an offset is a lie about its data."""
    kwargs = {"tz_offsets": {"linkedin": -5}}
    assert "tz_offset_hours" not in ingest_module._kwargs_for("linkedin", kwargs)


def test_the_offset_map_never_reaches_an_adapter():
    kwargs = {"tz_offsets": {"whatsapp": -5}}
    assert "tz_offsets" not in ingest_module._kwargs_for("whatsapp", kwargs)


# ------------------------------------------------------- end to end, real path

def _wall_clock_result(offset_hours: float) -> IngestResult:
    """What a wall-clock adapter produces at a given offset.

    The key comes from the real adapter's content fingerprint, because that is the
    thing under test: WhatsApp has no message id, so the key hashes the timestamp.
    """
    chat = Chat(platform="whatsapp", chat_id="wa_test", title="Test", kind="personal_chat",
                is_group=False, participant_names=("Me", "Ada"))
    ts = _BASE + timedelta(hours=offset_hours)
    key = whatsapp.message_key("wa_test", ts, "Ada", "hello")
    message = Message(
        key=key,
        platform="whatsapp", chat_id="wa_test", message_id=key.rsplit(":", 1)[1],
        ts_utc=ts, sender_name="Ada", sender_id=None, body="hello",
        reply_to=None, has_attachments=False, is_self=False, raw_kind="text",
    )
    return IngestResult(platform="whatsapp", source="fixture", chats=[chat],
                        messages=[message])


def test_verify_uses_the_persisted_offset(tmp_path):
    """The bug this file exists for: verify at 0 against rows written at -5."""
    store = tmp_path / "graph.rl"
    profile = tmp_path / "profile"

    written = _wall_clock_result(-5)
    conn = writer.connect(store)
    try:
        writer.write(conn, written)
    finally:
        conn.close()

    identity.save_tz_offset(profile, "whatsapp", -5)

    # Re-parsing at 0 produces a different key, which is exactly what used to be
    # reported as "missing".
    at_zero = _wall_clock_result(0)
    assert at_zero.messages[0].key != written.messages[0].key

    conn = writer.connect(store)
    try:
        ok, info = writer.verify_present(conn, _wall_clock_result(-5))
    finally:
        conn.close()
    assert ok, info
    assert info["missing"] == 0


def test_prune_reparses_with_the_persisted_offset(tmp_path, monkeypatch):
    """A verified file must be prunable; the old code could never verify one."""
    store = tmp_path / "graph.rl"
    profile = tmp_path / "profile"
    spool = tmp_path / "spool"
    spool.mkdir()

    payload = spool / "chat.txt"
    payload.write_text("[3/1/26, 9:00:00 AM] Ada: hello\n", encoding="utf-8")
    old = (datetime.now() - timedelta(days=10)).timestamp()
    import os
    os.utime(payload, (old, old))

    identity.save_tz_offset(profile, "whatsapp", -5)

    conn = writer.connect(store)
    try:
        writer.write(conn, _wall_clock_result(-5))
    finally:
        conn.close()

    monkeypatch.setattr(ingest_module.paths, "store_path", lambda: store)
    monkeypatch.setattr(ingest_module.paths, "profile_dir", lambda: profile)
    monkeypatch.setattr(ingest_module, "discover",
                        lambda root: [ingest_module.Batch(path=payload, platform="whatsapp")])
    monkeypatch.setattr(ingest_module, "_PARSERS",
                        {"whatsapp": lambda path, **kw: _wall_clock_result(
                            kw.get("tz_offset_hours", 0))})

    removed = ingest_module.prune_spool(root=spool)
    assert removed == [str(payload)]
    assert not payload.exists()


def test_reingesting_a_fresh_store_with_a_new_offset_works(tmp_path):
    """Wipe the store, re-ingest at a different offset: no error, no duplicates."""
    store = tmp_path / "graph.rl"
    profile = tmp_path / "profile"
    spool = tmp_path / "spool"
    spool.mkdir()

    payload = spool / "chat.txt"
    payload.write_text("[3/1/26, 9:00:00 AM] Ada: hello\n", encoding="utf-8")

    def run(offset: float) -> ingest_module.Report:
        return ingest_module.ingest(
            root=spool, store=store, profile_dir=profile,
            tz_offset_hours=offset, workers=1,
        )

    first = run(-5)
    assert first.ok
    assert identity.load_tz_offset(profile, "whatsapp") == -5

    # Same store, different offset: refused, because it would duplicate.
    with pytest.raises(ValueError, match="duplicate every message"):
        run(0)

    # Fresh store, different offset: allowed.
    store.unlink()
    second = run(0)
    assert second.ok
    assert identity.load_tz_offset(profile, "whatsapp") == 0


def test_prune_keeps_a_file_whose_offset_is_unknown(tmp_path, monkeypatch):
    """No recorded offset means no proof, and no proof means no delete."""
    store = tmp_path / "graph.rl"
    profile = tmp_path / "profile"
    spool = tmp_path / "spool"
    spool.mkdir()

    payload = spool / "chat.txt"
    payload.write_text("[3/1/26, 9:00:00 AM] Ada: hello\n", encoding="utf-8")
    old = (datetime.now() - timedelta(days=10)).timestamp()
    import os
    os.utime(payload, (old, old))

    conn = writer.connect(store)
    try:
        writer.write(conn, _wall_clock_result(-5))
    finally:
        conn.close()

    monkeypatch.setattr(ingest_module.paths, "store_path", lambda: store)
    monkeypatch.setattr(ingest_module.paths, "profile_dir", lambda: profile)
    monkeypatch.setattr(ingest_module, "discover",
                        lambda root: [ingest_module.Batch(path=payload, platform="whatsapp")])
    monkeypatch.setattr(ingest_module, "_PARSERS",
                        {"whatsapp": lambda path, **kw: _wall_clock_result(
                            kw.get("tz_offset_hours", 0))})

    assert ingest_module.prune_spool(root=spool) == []
    assert payload.exists()
