"""A job registry for work that outlives an HTTP request.

**Why this exists.** Relate allows one writer, and an ingest holds the store for its whole
duration. While it runs, any other read — the canvas, a search, an MCP call — gets
`storage locked`. The UI never noticed because it is a single client that awaits its own
ingest and asks for nothing else meanwhile. A second surface (MCP) does not know to wait,
so it collides.

A job turns a long call into two short ones: `start()` returns an id immediately, and
`status()` reports progress. The lock is then held only by the worker thread, and every
other surface can see that a job is running instead of failing.

**In memory only.** A job is a fact about this process, not about the store. Restarting
the app loses the record, which is correct: the work either finished (and is in the graph)
or it did not (and the spool still holds the files).
"""
from __future__ import annotations

import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

# A finished job is kept this long so a poller that is a little late still sees the
# result. After that it is dropped, so a long-running app does not accumulate them.
RETAIN_SECONDS = 600

# Only one job may hold the store at a time. A second `start()` while one is running is
# refused rather than queued: the caller asked for work that cannot begin yet, and a
# queue would hide that behind a spinner.
_LOCK = threading.Lock()


@dataclass
class Job:
    id: str
    kind: str
    state: str = "running"          # running | done | failed
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    result: Any = None
    error: str | None = None
    # Free-form progress the worker may update. The UI shows `message` if present.
    progress: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "state": self.state,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "elapsed_s": round((self.finished_at or time.time()) - self.started_at, 1),
            "result": self.result,
            "error": self.error,
            "progress": self.progress,
        }


_JOBS: dict[str, Job] = {}


def _sweep() -> None:
    """Drop finished jobs older than `RETAIN_SECONDS`. Called under the lock."""
    cutoff = time.time() - RETAIN_SECONDS
    for job_id in [
        job.id for job in _JOBS.values()
        if job.finished_at is not None and job.finished_at < cutoff
    ]:
        _JOBS.pop(job_id, None)


def running() -> Job | None:
    """The job currently holding the store, if any."""
    with _LOCK:
        for job in _JOBS.values():
            if job.state == "running":
                return job
    return None


def start(kind: str, work: Callable[[Job], Any]) -> Job:
    """Run `work` on a background thread and return its job immediately.

    `work` receives the `Job` so it can publish progress. Its return value becomes
    `job.result`; an exception becomes `job.error` and `state="failed"` — the caller
    reads it from `status()`, never from a raised exception, because the request that
    started the job has already returned.
    """
    with _LOCK:
        _sweep()
        busy = next((job for job in _JOBS.values() if job.state == "running"), None)
        if busy is not None:
            raise RuntimeError(
                f"a {busy.kind} job is already running ({busy.id}); "
                "wait for it to finish"
            )
        job = Job(id=uuid.uuid4().hex[:12], kind=kind)
        _JOBS[job.id] = job

    def runner() -> None:
        try:
            job.result = work(job)
            job.state = "done"
        except Exception as exc:  # noqa: BLE001 - reported through the job, not raised
            # **Everything is written before `state` changes.** A poller reads the
            # snapshot the moment `state` stops being `running`, so setting it first
            # would let it observe a failed job with no error and no traceback.
            job.error = f"{type(exc).__name__}: {exc}"
            job.progress["traceback"] = traceback.format_exc()[-2000:]
            job.finished_at = time.time()
            job.state = "failed"
        else:
            job.finished_at = time.time()
            job.state = "done"

    threading.Thread(target=runner, name=f"job-{job.id}", daemon=True).start()
    return job


def status(job_id: str) -> dict[str, Any] | None:
    """One job's state, or `None` if it is unknown or has been swept."""
    with _LOCK:
        job = _JOBS.get(job_id)
        return job.to_dict() if job else None


def clear() -> None:
    """Forget every finished job. Used by tests; not exposed over HTTP."""
    with _LOCK:
        for job_id in [j.id for j in _JOBS.values() if j.state != "running"]:
            _JOBS.pop(job_id, None)
