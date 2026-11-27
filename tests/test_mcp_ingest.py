"""One smoke test: `ingest` works through the MCP binding.

Deliberately shallow. `ingest()` itself is covered by `test_delta.py`,
`test_outlook_ingest.py` and the adapter tests; what is unproven here is only that the
MCP wrapper reaches it with the right arguments and that the guards fire.

**Nothing here touches `store/graph.rl`.** The store comes from `conftest.py`, which
seeds one small store per session and hands each test a copy.
"""
from __future__ import annotations

import pytest

from app.mcp import config, server
from relate_comms import tools


@pytest.fixture()
def mcp_sandbox(tmp_path, monkeypatch):
    """A throwaway store, profile and spool, with `paths` redirected."""
    store = tmp_path / "graph.rl"
    spool = tmp_path / "spool" / "real"
    spool.mkdir(parents=True)

    monkeypatch.setattr(tools, "store_path", lambda: store)
    monkeypatch.setattr(config.paths, "store_path", lambda: store)
    monkeypatch.setattr(config.paths, "profile_dir", lambda: tmp_path / "profile")
    monkeypatch.setattr(config.paths, "real_dir", lambda: spool)
    monkeypatch.delenv(config.KEY_ENV, raising=False)

    (spool / "chat.txt").write_text(
        "[01/01/2026, 12:00:00] David Sartori: meet me in Kensington\n"
        "[01/01/2026, 12:05:00] You: see you there\n",
        encoding="utf-8",
    )
    return tmp_path


def _wait(job_id, timeout=30.0):
    import time

    from app import jobs

    deadline = time.time() + timeout
    while time.time() < deadline:
        found = jobs.status(job_id)
        if found and found["state"] != "running":
            return found
        time.sleep(0.02)
    raise AssertionError("job did not finish")


def test_ingest_through_the_mcp_binding_writes_rows(mcp_sandbox):
    """The command works end to end: wrapper -> guard -> job -> tools.ingest -> store.

    `ingest` returns a job id rather than a report, because it holds the store for its
    whole duration. The result is collected from `job_status`.
    """
    from app import jobs

    bound = server._bind("ingest", "write")

    started = bound()
    assert started["state"] == "running"

    finished = _wait(started["job"])
    assert finished["state"] == "done"
    assert finished["result"]["ok"] is True
    assert tools.evidence_counts()["messages"] == 2
    jobs.clear()


def test_the_guard_runs_before_the_ingest(mcp_sandbox):
    """A refused path must not have written anything, and must not start a job."""
    from app import jobs

    bound = server._bind("ingest", "write")

    with pytest.raises(tools.ToolError, match="outside the repo"):
        bound(paths_in=["C:/Windows"])

    assert jobs.running() is None
    assert not config.paths.store_path().exists()


def test_a_read_level_binding_cannot_ingest(mcp_sandbox):
    """The write key is the gate: a read binding passes `write_enabled=False`."""
    bound = server._bind("ingest", "read")

    with pytest.raises(tools.ToolError, match="write access is disabled"):
        bound()


def test_a_mailbox_is_allowed(mcp_sandbox):
    """`email` names the mailbox, not a secret. The guard must let it through."""
    server._guard_ingest({"email": ["email"]})


def test_an_unconfigured_mailbox_names_its_keys(mcp_sandbox, monkeypatch):
    """The adapter validates, not the guard — and it says which key is missing."""
    from relate_comms.adapters import email_imap

    monkeypatch.setattr(email_imap, "_dotenv", lambda environ=None: {})
    for name in email_imap.IMAP_KEYS:
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(ValueError, match="IMAP_EMAIL"):
        email_imap.account_from_slot()
