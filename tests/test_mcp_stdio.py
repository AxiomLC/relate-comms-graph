"""The server over a real stdio pipe, against a scratch store.

This is the test that proves the thing actually speaks MCP — the unit tests check the
allowlist and the schema, but only a real client handshake proves the transport works.

**The store is a copy**, never `store/graph.rl`. `RELATE_STORE` is how the subprocess is
pointed at it: `tools.configure()` is per-process, so an in-process fixture cannot reach
a child.
"""
from __future__ import annotations

import os
import sys

import pytest

from app.mcp import config

pytest.importorskip("mcp")

from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402


def _params(key: str | None, store) -> StdioServerParameters:
    env = dict(os.environ)
    env["RELATE_STORE"] = str(store)
    env["RELATE_MCP_PROFILE"] = str(store.parent / "profile")
    if key:
        env[config.KEY_ENV] = key
    else:
        env.pop(config.KEY_ENV, None)
    return StdioServerParameters(
        command=sys.executable, args=["-m", "app.mcp"], env=env,
    )


async def _list(key: str | None, store) -> list[str]:
    async with stdio_client(_params(key, store)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listed = await session.list_tools()
            return sorted(tool.name for tool in listed.tools)


def _run(coro):
    import asyncio
    return asyncio.run(coro)


def test_the_read_key_exposes_read_tools_only(store, monkeypatch):
    monkeypatch.setattr(config.paths, "profile_dir", lambda: store.parent / "profile")
    read_key = config.load()["read_key"]

    names = _run(_list(read_key, store))

    assert "search_fulltext" in names
    assert "ingest" not in names
    assert "truncate_store" not in names


def test_the_write_key_exposes_everything(store, monkeypatch):
    monkeypatch.setattr(config.paths, "profile_dir", lambda: store.parent / "profile")
    write_key = config.load()["write_key"]

    names = _run(_list(write_key, store))

    assert "search_fulltext" in names
    assert "ingest" in names
    assert "truncate_store" in names


def test_a_wrong_key_refuses_to_start(store):
    with pytest.raises(BaseException):
        _run(_list("not-a-key", store))


def test_no_key_refuses_to_start(store):
    with pytest.raises(BaseException):
        _run(_list(None, store))
