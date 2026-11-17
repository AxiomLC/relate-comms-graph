"""Truncating the store.

The one rule that matters: **the dedup manifest goes with the graph, always.** Leaving
`ingested.json` behind after a wipe would make the next ingest skip every file it had
ever seen, producing an empty graph that looks like a successful run.

Run: python -m pytest tests -q
"""
from __future__ import annotations

import pytest

from relate_comms import manifest, paths, tools


@pytest.fixture()
def sandbox(tmp_path, monkeypatch):
    """A throwaway store, profile and spool, so nothing real is touched."""
    store = tmp_path / "graph.rl"
    profile = tmp_path / "profile"
    spool = tmp_path / "spool" / "real"

    monkeypatch.setattr(paths, "store_path", lambda: store)
    monkeypatch.setattr(paths, "profile_dir", lambda: profile)
    monkeypatch.setattr(paths, "real_dir", lambda: spool)

    store.write_text("graph", encoding="utf-8")
    profile.mkdir()
    (profile / "identity.json").write_text("{}", encoding="utf-8")
    manifest.record(profile, "abc", platform="telegram", path="p",
                    messages=1, threads=1, bytes_=1)
    (spool / "telegram").mkdir(parents=True)
    (spool / "telegram" / "result.json").write_text("{}", encoding="utf-8")
    return tmp_path


def test_needs_confirm(sandbox):
    with pytest.raises(tools.ToolError, match="confirm=true"):
        tools.truncate_store(write_enabled=True, confirm=False)
    assert paths.store_path().exists(), "a refused call must not delete anything"


def test_needs_write(sandbox):
    with pytest.raises(tools.ToolError, match="write access is disabled"):
        tools.truncate_store(write_enabled=False, confirm=True)
    assert paths.store_path().exists()


def test_removes_graph_and_manifest(sandbox):
    result = tools.truncate_store(write_enabled=True, confirm=True)
    assert not paths.store_path().exists()
    assert not (paths.profile_dir() / manifest.MANIFEST_FILE).exists()
    assert result["store_exists"] is False
    assert len(result["removed"]) == 2


def test_keeps_identity_and_spool_by_default(sandbox):
    """Re-ingesting the same account needs the owner and tz offsets."""
    tools.truncate_store(write_enabled=True, confirm=True)
    assert (paths.profile_dir() / "identity.json").exists()
    assert (paths.real_dir() / "telegram" / "result.json").exists()


def test_can_drop_identity_when_switching_accounts(sandbox):
    tools.truncate_store(write_enabled=True, confirm=True, also_identity=True)
    assert not (paths.profile_dir() / "identity.json").exists()


def test_can_drop_the_spool_when_asked(sandbox):
    tools.truncate_store(write_enabled=True, confirm=True, also_spool=True)
    assert not (paths.real_dir() / "telegram" / "result.json").exists()


def test_a_missing_store_is_not_an_error(sandbox):
    paths.store_path().unlink()
    result = tools.truncate_store(write_enabled=True, confirm=True)
    assert result["store_exists"] is False
    assert any("did not exist" in item for item in result["kept"])
