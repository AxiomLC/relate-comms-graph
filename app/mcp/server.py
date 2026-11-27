"""The MCP surface: the same tools, a narrower allowlist, two keys.

**Local only.** v1 is stdio — the IDE launches this process and talks to it over the same
pipe it uses for output. No port, no network, nothing to expose. A dev who wants web
access puts their own proxy in front; that is their risk and this server does not arrange
it.

**Two keys, in a file we own** (`app/mcp/config.py`). The owner copies one into their
client config, which passes it as `RELATE_MCP_KEY`:

    read_key    read tools only
    write_key   read + write

No key, or a wrong key, refuses to start. That is the whole auth story, and it is what the
MCP spec asks for on stdio: no OAuth, credentials from the environment.

**Nothing is written twice.** Every tool is already a plain function in
`relate_comms.tools.REGISTRY`; this module binds them and applies policy. The policy is a
per-surface constant, not a registry property.

**What this surface must never do:**

- **return a credential.** `ingest(email=["email"])` takes a *slot name*; the four
  values are read from `.env` inside this process and never appear in a response, a
  tool argument or the activity trace. `.env` holds only the four `IMAP_*` keys.
- inherit the UI's platform filter — a separate process has no UI state to inherit
- accept a `paths_in` outside the repo — `ingest.stage()` copies any path on disk

Run it with `python -m app.mcp`.
"""
from __future__ import annotations

import inspect
import sys
import time
from typing import Any, Callable

from mcp.server.fastmcp import FastMCP

from relate_comms import tools

from . import config

# ---------------------------------------------------------------- allowlist

# The tools this surface exposes. Same definitions as the chat's, a different subset:
# a local 8B model picks wrong from 19 overlapping options, a frontier model in an IDE
# does not. `ingest` is here but shimmed (see `_ingest`); `email` is refused.
_READ_TOOLS = (
    "graph_slice",
    "thread_arc",
    "search_messages",
    "search_fulltext",
    "search_vector",
    "embed_status",
    "screen_body",
    "message_view",
    "types_present",
    "evidence_counts",
    "preview_ingest",
    "verify_ingest",
    "run_cypher",
    "job_status",
    "job_list",
    "activity",
)

_WRITE_TOOLS = (
    "embed_messages",
    "ingest",
    "flush_embeddings",
    "truncate_store",
    "prune_spool",
    "delete_spool",
)

# Parameters the surface owns, never the model. `write_enabled` is set from the key;
# `platforms` is UI state that does not exist here. `confirm` is deliberately *not*
# hidden — the model must be able to say it means it.
_HIDDEN = frozenset({"write_enabled", "platforms"})


def job_status(job_id: str) -> dict[str, Any]:
    """The state of a background job started by `ingest`.

    `state` is `running`, `done` or `failed`. A finished job carries the full report, so
    this is the only call needed to collect an ingest's result. Jobs are in memory only:
    a restart loses them, and an unknown id says so rather than returning an empty object.
    """
    from app import jobs

    found = jobs.status(job_id)
    if found is None:
        raise tools.ToolError(f"no job {job_id!r}; it may have finished and been swept")
    return found


def job_list() -> dict[str, Any]:
    """The job currently holding the store, if any.

    Call this before `ingest`: a second ingest cannot start while one is running, and
    knowing that is better than a collision.
    """
    from app import jobs

    current = jobs.running()
    return {"running": current.to_dict() if current else None}


def activity(limit: int = 40) -> dict[str, Any]:
    """Recent tool calls across every surface, newest last.

    **Read-only, and it does not drain.** The UI's `/api/activity` drains the file so a
    row is shown once; this peeks instead, because an agent asking "what has been
    happening" must not consume the user's view of it.

    Rows carry the source (`search`, `chat`, `mcp`), the call, the milliseconds and a
    status. Arguments are summarised, never dumped — a Cypher query is capped at 300
    characters and a message body never appears.
    """
    from app.mcp import config

    rows = config.peek_activity(limit=max(1, min(int(limit), 200)))
    return {"rows": rows, "count": len(rows)}


def _level() -> str | None:
    """The access level the presented key grants, or `None`."""
    return config.resolve()


def _allowed(level: str | None) -> tuple[str, ...]:
    if level == "write":
        return _READ_TOOLS + _WRITE_TOOLS
    if level == "read":
        return _READ_TOOLS
    return ()


# ---------------------------------------------------------------- binding

def _bind(name: str, level: str) -> Callable[..., Any]:
    """Wrap one registry tool for MCP.

    The wrapper exists for two reasons, both about the schema the model sees:

    1. **Hide the surface's own parameters.** `write_enabled` and `platforms` are not
       the model's to set, so they are removed from the signature before the SDK derives
       the JSON schema from it.
    2. **Inject them.** The wrapper supplies `write_enabled` from the key, so a write
       tool cannot be called without write access even if the model asks nicely.

    `confirm` stays visible on purpose: a destructive tool must be told, in the call
    itself, that the caller means it.
    """
    tool = tools.REGISTRY[name]
    fn = tool.fn
    signature = inspect.signature(fn)
    visible = [
        param for param in signature.parameters.values()
        if param.name not in _HIDDEN
    ]
    # Only inject what the tool actually accepts. A READ tool has no `write_enabled`
    # parameter, and passing one is a TypeError — which the SDK reports as a tool
    # failure, so every read would break.
    takes_write = "write_enabled" in signature.parameters

    def call(*args: Any, **kwargs: Any) -> Any:
        # Every call stamps the heartbeat, so the app's title bar can say "MCP being
        # accessed" from a fact rather than a guess. Stamped before the work, so a slow
        # ingest still shows as activity while it runs.
        config.touch_heartbeat()
        if takes_write:
            kwargs["write_enabled"] = level == "write"
        # The guard lives here, not in `build()`, so a binding is never unguarded —
        # `_bind` is the only way a tool reaches the server.
        if name == "ingest":
            _guard_ingest(kwargs)

        # One row per call, in the same feed the search bar and chat write to. The
        # arguments are summarised, never dumped: a Cypher query is capped by
        # `push_activity`, and a full body would push the feed off-screen.
        started = time.perf_counter()
        try:
            # **`ingest` returns a job id, not a report.** It holds the store for its
            # whole duration, so awaiting it here would block the client until it timed
            # out while the work carried on invisibly.
            if name == "ingest":
                result = _start_ingest_job(kwargs)
            else:
                result = fn(*args, **kwargs)
        except Exception as exc:
            config.push_activity(
                f"{name}({_summarise(kwargs)}) failed: {type(exc).__name__}",
                status="error",
                ms=(time.perf_counter() - started) * 1000,
            )
            raise
        config.push_activity(
            f"{name}({_summarise(kwargs)})",
            ms=(time.perf_counter() - started) * 1000,
        )
        return result

    call.__name__ = name
    call.__doc__ = tool.description
    call.__signature__ = signature.replace(parameters=visible)  # type: ignore[attr-defined]
    return call


def _summarise(kwargs: dict[str, Any], width: int = 60) -> str:
    """A one-line rendering of a call's arguments for the activity trace.

    Short values are shown, long ones are cut. The point is to recognise the call at a
    glance, not to reproduce it.
    """
    parts = []
    for key, value in kwargs.items():
        if key in _HIDDEN or value in (None, False, [], {}):
            continue
        text = str(value)
        if len(text) > width:
            text = text[:width] + "…"
        parts.append(f"{key}={text}")
    return ", ".join(parts)


def _start_ingest_job(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Start an ingest on a background thread and return its job id.

    **The same reason the HTTP route does it.** An ingest holds the store for its whole
    duration, so awaiting it over MCP blocked the client until it timed out — and the
    work carried on in the background, which is the worst of both. Returning a job id
    means the call finishes in milliseconds and the caller polls `job_status`.
    """
    from app import jobs

    # **The write gate is checked here, not inside the thread.** `tools.ingest` would
    # raise it too, but by then the job exists and the caller has been told "started" —
    # a refusal must fail the call, not a background job nobody is watching.
    tools.require(
        tools.Access.WRITE, write_enabled=bool(kwargs.get("write_enabled")),
    )

    def work(job: jobs.Job) -> Any:
        job.progress["stage"] = "ingest"
        result = tools.ingest(**kwargs)
        job.progress["written"] = result.get("written")
        return result

    try:
        job = jobs.start("ingest", work)
    except RuntimeError as exc:
        raise tools.ToolError(str(exc)) from exc

    return {
        "job": job.id,
        "state": job.state,
        "note": "poll job_status(job_id) for the result",
    }


def _guard_ingest(kwargs: dict[str, Any]) -> None:
    """The one limit on `ingest`: `paths_in` must resolve inside the repo.

    `stage()` copies any path on disk into the spool, so this is the thing the write key
    must bound. It is a boundary, not a safety mechanism — `ingest` copies and never
    deletes the source.

    **`email` is allowed.** It reads the mailbox slots from `.env`, which holds nothing
    but the four `IMAP_*` keys. The agent passes `email=["email"]`, never a password: the
    values are used inside this process and never appear in a response, a tool argument
    or the activity trace. An agent that can call `search_fulltext` can already read
    every message, so this grants no new power — it only lets the agent refresh what it
    can already see.
    """
    paths_in = kwargs.get("paths_in") or []
    if isinstance(paths_in, str):
        paths_in = [paths_in]
    outside = [p for p in paths_in if not config.path_allowed(p)]
    if outside:
        raise tools.ToolError(
            f"path outside the repo: {outside[0]!r}. This surface may only ingest "
            f"from inside {config.REPO_ROOT}."
        )


def build(level: str) -> FastMCP:
    """A server exposing the tools `level` allows. `level` is `"read"` or `"write"`."""
    server = FastMCP(
        name="relate-comms-graph",
        instructions=(
            "The user's own message history, across platforms, as one local graph. "
            "Every answer must come from a tool call — never from assumption. "
            "If a search returns nothing, say so plainly rather than guessing."
        ),
    )

    # Two tools live here rather than in `tools.REGISTRY`: they describe *this process's*
    # jobs, not the store, so they have no business in the library's tool layer.
    local = {
        "job_status": job_status,
        "job_list": job_list,
        "activity": activity,
    }

    for name in _allowed(level):
        if name in local:
            server.add_tool(
                local[name],
                name=name,
                description=(local[name].__doc__ or "").strip(),
            )
            continue
        server.add_tool(
            _bind(name, level),
            name=name,
            description=tools.REGISTRY[name].description,
        )

    return server


def _apply_env_overrides() -> None:
    """Point the process at a different store, for tests and for a second graph.

    `tools.configure()` is per-process, so an in-process fixture cannot reach a child
    process. These two variables are the only way to redirect one — and they exist so a
    test never has to touch `store/graph.rl`.
    """
    import os

    store = os.environ.get("RELATE_STORE")
    if store:
        tools.configure(store=store)

    profile = os.environ.get("RELATE_MCP_PROFILE")
    if profile:
        from relate_comms import paths
        paths.profile_dir = lambda: __import__("pathlib").Path(profile)  # type: ignore[assignment]


def main() -> int:
    """Entry point. Refuses to start without a valid key."""
    _apply_env_overrides()
    level = _level()
    if level is None:
        print(
            "MCP refused to start: no valid key.\n"
            f"  Set {config.KEY_ENV} to the read_key or write_key from\n"
            f"  {config.config_path()}\n"
            "  and pass it from your MCP client config.",
            file=sys.stderr,
        )
        return 2

    print(
        f"relate-comms-graph MCP: {level} access, "
        f"{len(_allowed(level))} tools, stdio",
        file=sys.stderr,
    )
    build(level).run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
