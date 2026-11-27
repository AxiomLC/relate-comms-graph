"""The heartbeat and the activity trace — the two files the two processes share.

The MCP server is a separate stdio process, so the only channel to the app is the
filesystem. These tests pin the two properties that matter: a stale or missing file must
read as **not active**, and the trace must be **drained**, not tailed.
"""
from __future__ import annotations

import json
import time

import pytest

from app.mcp import config


@pytest.fixture()
def profile(tmp_path, monkeypatch):
    monkeypatch.setattr(config.paths, "profile_dir", lambda: tmp_path / "profile")
    monkeypatch.delenv(config.KEY_ENV, raising=False)
    return tmp_path / "profile"


# ------------------------------------------------------------------ heartbeat

def test_no_heartbeat_is_not_active(profile):
    assert config.is_active() is False


def test_a_fresh_heartbeat_is_active(profile):
    config.touch_heartbeat()
    assert config.is_active() is True


def test_a_stale_heartbeat_is_not_active(profile):
    config.touch_heartbeat()
    path = config.heartbeat_path()
    path.write_text(str(int(time.time()) - config.HEARTBEAT_TTL_SECONDS - 5),
                    encoding="utf-8")
    assert config.is_active() is False


def test_a_heartbeat_from_the_future_is_not_active(profile):
    """A clock that went backwards must not light the badge forever."""
    config.touch_heartbeat()
    config.heartbeat_path().write_text(str(int(time.time()) + 600), encoding="utf-8")
    assert config.is_active() is False


def test_a_garbage_heartbeat_is_not_active(profile):
    config.heartbeat_path().parent.mkdir(parents=True, exist_ok=True)
    config.heartbeat_path().write_text("not a number", encoding="utf-8")
    assert config.is_active() is False


# ------------------------------------------------------------------ activity

def test_no_trace_drains_to_nothing(profile):
    assert config.drain_activity() == []


def test_a_pushed_row_is_drained_once(profile):
    config.push_activity("search_fulltext(query=invoice)", ms=12.5)

    first = config.drain_activity()
    assert len(first) == 1
    assert first[0]["source"] == "mcp"
    assert first[0]["text"] == "search_fulltext(query=invoice)"
    assert first[0]["ms"] == 12.5

    # Draining, not tailing: the second read is empty.
    assert config.drain_activity() == []


def test_an_error_row_keeps_its_status(profile):
    config.push_activity("ingest() failed: ToolError", status="error")
    assert config.drain_activity()[0]["status"] == "error"


def test_a_long_text_is_capped(profile):
    config.push_activity("x" * 1000)
    assert len(config.drain_activity()[0]["text"]) == 300


def test_a_malformed_line_is_skipped(profile):
    config.push_activity("good row")
    path = config.activity_path()
    with path.open("a", encoding="utf-8") as handle:
        handle.write("{not json\n")

    rows = config.drain_activity()
    assert len(rows) == 1
    assert rows[0]["text"] == "good row"
