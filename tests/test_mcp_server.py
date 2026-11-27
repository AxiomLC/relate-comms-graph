"""The MCP server's allowlist, schema shaping and the two ingest limits.

No transport is started here. `build()` returns a server object, and the SDK derives each
tool's JSON schema from the wrapper's signature — so these tests check exactly what a
model would see, without a pipe.
"""
from __future__ import annotations

import inspect

import pytest

from app.mcp import config, server
from relate_comms import tools


@pytest.fixture()
def profile(tmp_path, monkeypatch):
    monkeypatch.setattr(config.paths, "profile_dir", lambda: tmp_path / "profile")
    monkeypatch.delenv(config.KEY_ENV, raising=False)
    return tmp_path / "profile"


def _tools(built) -> dict:
    """The tools a built server exposes, by name."""
    return {tool.name: tool for tool in built._tool_manager.list_tools()}


# ------------------------------------------------------------------ allowlist

def test_no_level_exposes_nothing():
    assert server._allowed(None) == ()


def test_read_level_exposes_only_read_tools():
    names = server._allowed("read")
    assert "search_fulltext" in names
    assert "ingest" not in names
    assert "truncate_store" not in names


def test_write_level_exposes_read_and_write():
    names = server._allowed("write")
    assert "search_fulltext" in names
    assert "ingest" in names
    assert "truncate_store" in names


def test_every_allowlisted_name_exists_in_the_registry():
    """Except the two job tools, which describe this process, not the store."""
    local = {"job_status", "job_list", "activity"}
    for name in server._READ_TOOLS + server._WRITE_TOOLS:
        if name in local:
            continue
        assert name in tools.REGISTRY, name


# ------------------------------------------------------------------ schema

def test_the_surface_parameters_are_hidden_from_the_model(profile):
    built = server.build("write")
    schema = _tools(built)["search_fulltext"].parameters
    assert "write_enabled" not in schema["properties"]
    assert "platforms" not in schema["properties"]


def test_confirm_stays_visible(profile):
    """A destructive tool must be told, in the call, that the caller means it."""
    built = server.build("write")
    schema = _tools(built)["truncate_store"].parameters
    assert "confirm" in schema["properties"]


def test_a_read_tool_keeps_its_own_arguments(profile):
    built = server.build("read")
    schema = _tools(built)["thread_arc"].parameters
    assert "thread_key" in schema["properties"]
    assert schema["required"] == ["thread_key"]


# ------------------------------------------------------------------ ingest guard

def test_ingest_allows_a_mailbox():
    """`email` names the mailbox; the credentials stay in `.env` and are never returned."""
    server._guard_ingest({"email": ["email"]})


def test_ingest_refuses_a_path_outside_the_repo():
    with pytest.raises(tools.ToolError, match="outside the repo"):
        server._guard_ingest({"paths_in": ["C:/Users/someone/Downloads/chat.zip"]})


def test_ingest_allows_a_path_inside_the_repo():
    server._guard_ingest({"paths_in": [str(config.REPO_ROOT / "sample_writer" / "out")]})


def test_ingest_allows_the_spool():
    server._guard_ingest({"paths_in": [str(config.paths.real_dir())]})


def test_ingest_with_no_paths_is_allowed():
    """A plain re-ingest of the spool is the normal case."""
    server._guard_ingest({})


def test_a_single_path_string_is_checked_too():
    with pytest.raises(tools.ToolError, match="outside the repo"):
        server._guard_ingest({"paths_in": "C:/Windows"})


# ------------------------------------------------------------------ write injection

@pytest.fixture()
def fake_write_tool(monkeypatch):
    """A stand-in with the real signature shape: `write_enabled` keyword-only.

    `monkeypatch.setitem` restores the real registry entry afterwards — a plain
    assignment here leaked a fake `embed_messages` into every later test.
    """
    seen: dict = {}

    def fake(limit: int = 10, *, write_enabled: bool = False):
        seen.update(limit=limit, write_enabled=write_enabled)
        return {"ok": True}

    monkeypatch.setitem(
        tools.REGISTRY, "embed_messages",
        tools.Tool(name="embed_messages", fn=fake, access=tools.Access.WRITE,
                   description="fake"),
    )
    return seen


def test_a_write_tool_gets_write_enabled_from_the_key(profile, fake_write_tool):
    """The model cannot set `write_enabled`; the surface injects it."""
    server._bind("embed_messages", "write")()
    assert fake_write_tool["write_enabled"] is True


def test_a_read_level_binding_never_grants_write(profile, fake_write_tool):
    server._bind("embed_messages", "read")()
    assert fake_write_tool["write_enabled"] is False


def test_a_tool_without_write_enabled_is_not_passed_one(profile):
    """A READ tool has no such parameter; passing one is a TypeError."""
    bound = server._bind("evidence_counts", "write")
    assert "write_enabled" not in inspect.signature(bound).parameters
