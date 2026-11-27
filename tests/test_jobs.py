"""The job registry: one long task at a time, reported instead of awaited.

The property that matters is that `start()` returns immediately and the work happens on
another thread — that is what stops an ingest from blocking every other surface.
"""
from __future__ import annotations

import threading
import time

import pytest

from app import jobs


@pytest.fixture(autouse=True)
def clean():
    jobs.clear()
    yield
    jobs.clear()


def _wait(job_id, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        found = jobs.status(job_id)
        if found and found["state"] != "running":
            return found
        time.sleep(0.01)
    raise AssertionError("job did not finish")


def test_start_returns_before_the_work_finishes():
    gate = threading.Event()

    def work(job):
        gate.wait(2)
        return {"ok": True}

    job = jobs.start("ingest", work)
    assert job.state == "running"

    gate.set()
    assert _wait(job.id)["state"] == "done"


def test_a_result_is_carried_on_the_job():
    job = jobs.start("ingest", lambda j: {"written": 42})
    assert _wait(job.id)["result"] == {"written": 42}


def test_a_failure_is_reported_not_raised():
    def work(job):
        raise ValueError("boom")

    job = jobs.start("ingest", work)
    found = _wait(job.id)

    assert found["state"] == "failed"
    assert "ValueError: boom" in found["error"]
    assert "traceback" in found["progress"]


def test_progress_is_visible_while_running():
    gate = threading.Event()

    def work(job):
        job.progress["stage"] = "parsing"
        gate.wait(2)
        return {}

    job = jobs.start("ingest", work)
    time.sleep(0.05)
    assert jobs.status(job.id)["progress"]["stage"] == "parsing"
    gate.set()
    _wait(job.id)


def test_a_second_job_is_refused_while_one_runs():
    gate = threading.Event()

    def work(job):
        gate.wait(2)
        return {}

    first = jobs.start("ingest", work)
    with pytest.raises(RuntimeError, match="already running"):
        jobs.start("ingest", lambda j: {})

    gate.set()
    _wait(first.id)


def test_a_second_job_is_allowed_after_the_first_finishes():
    first = jobs.start("ingest", lambda j: {})
    _wait(first.id)

    second = jobs.start("ingest", lambda j: {})
    assert _wait(second.id)["state"] == "done"


def test_running_reports_the_active_job():
    gate = threading.Event()

    def work(job):
        gate.wait(2)
        return {}

    job = jobs.start("ingest", work)
    time.sleep(0.05)
    assert jobs.running().id == job.id

    gate.set()
    _wait(job.id)
    assert jobs.running() is None


def test_an_unknown_id_is_none():
    assert jobs.status("nope") is None


def test_elapsed_is_reported():
    job = jobs.start("ingest", lambda j: {})
    found = _wait(job.id)
    assert found["elapsed_s"] >= 0
