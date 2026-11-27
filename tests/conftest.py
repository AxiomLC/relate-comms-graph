"""Shared test fixtures.

**No test may touch `store/graph.rl`.** The live store holds the user's real messages, and
a test that reads it is both slow and a privacy leak into CI. Everything here builds a
throwaway store under `tmp_path`.

The one expensive thing is building a store with real content in it, so that is done
**once per session** into a cached `.rl`, and each test gets a copy. A copy is a file
copy — milliseconds — where a rebuild is a full ingest.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from relate_comms import paths, tools, writer

# A tiny WhatsApp chat: two messages, one place name, one correspondent. Enough for a
# search hit, a thread, and an entity mention, and it ingests in well under a second.
_CHAT = (
    "[01/01/2026, 12:00:00] David Sartori: meet me in Kensington\n"
    "[01/01/2026, 12:05:00] You: see you there\n"
    "[02/01/2026, 09:30:00] David Sartori: invoice for the Grafana licence\n"
)


@pytest.fixture(scope="session")
def _seeded_store(tmp_path_factory) -> Path:
    """Build one small populated store for the whole session.

    Session-scoped because the ingest is the expensive part; every test then copies the
    resulting file. Nothing here reads `store/graph.rl`.
    """
    from relate_comms import ingest as ingest_module

    root = tmp_path_factory.mktemp("seed")
    spool = root / "spool"
    spool.mkdir()
    (spool / "chat.txt").write_text(_CHAT, encoding="utf-8")

    store = root / "graph.rl"
    ingest_module.ingest(root=spool, store=store, profile_dir=root / "profile")
    return store


@pytest.fixture()
def store(tmp_path, _seeded_store) -> Path:
    """A private copy of the seeded store, wired into the tool layer.

    A copy rather than a rebuild: `shutil.copy2` is ~1 ms, an ingest is ~1 s. The tool
    layer is pointed at the copy and restored afterwards, so a test that writes cannot
    affect the next one.
    """
    path = tmp_path / "graph.rl"
    shutil.copy2(_seeded_store, path)

    previous = tools.store_path()
    tools.configure(store=path)
    try:
        yield path
    finally:
        tools.configure(store=previous if previous.exists() else None)


@pytest.fixture()
def empty_store(tmp_path) -> Path:
    """A store with the schema and no rows, for tests that only need it to exist."""
    path = tmp_path / "graph.rl"
    writer.connect(path).close()

    previous = tools.store_path()
    tools.configure(store=path)
    try:
        yield path
    finally:
        tools.configure(store=previous if previous.exists() else None)


@pytest.fixture()
def sandbox(tmp_path, monkeypatch):
    """A throwaway store, profile and spool, with `paths` redirected.

    For anything that calls `paths.store_path()` / `paths.real_dir()` directly rather
    than going through `tools.configure`.
    """
    store = tmp_path / "graph.rl"
    profile = tmp_path / "profile"
    spool = tmp_path / "spool" / "real"
    spool.mkdir(parents=True)

    monkeypatch.setattr(paths, "store_path", lambda: store)
    monkeypatch.setattr(paths, "profile_dir", lambda: profile)
    monkeypatch.setattr(paths, "real_dir", lambda: spool)
    return tmp_path
