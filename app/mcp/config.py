"""The MCP surface's two keys, and the one path rule.

**Two keys, in a file we own.** The MCP spec says a stdio server SHOULD NOT do OAuth and
should take credentials from the environment instead, so there is no handshake to build.
What we do instead is generate two keys into `store/profile/mcp.json` (gitignored, beside
`identity.json`) and let the owner hand one to the agent through its client config.

    read_key    read tools only
    write_key   read + write

Two keys rather than one boolean because the write key is a separate secret the owner
hands over deliberately: an agent configured with only the read key cannot write even if
it tries.

**This is a handshake, not a wall.** Anyone who can launch the process can read this file
— same user, same permissions. It stops a *different* agent on the machine from quietly
connecting, and it makes granting write a deliberate act. It does not stop malware running
as the user. That is acceptable because the real boundary is already "who can launch a
process on this machine", which for stdio is the whole trust model.

**`.env` holds only mailbox credentials.** The four `IMAP_*` keys, nothing else. This
surface may read them, because an agent that can call `search_fulltext` can already read
every message — the credentials grant no new power, they only let the agent refresh what
it can already see. What it must never do is **return** one: `ingest(email=["email"])`
takes a slot name, and the values never appear in a response, a tool argument or the
activity trace.

The MCP key itself arrives in `os.environ`, from the launching client config.
"""
from __future__ import annotations

import hmac
import json
import os
import secrets
import time
from pathlib import Path
from typing import Any

from relate_comms import paths

_CONFIG_FILE = "mcp.json"

# The environment variable a client config sets. The owner copies one of the two keys
# from `mcp.json` into their IDE's MCP config, which passes it here.
KEY_ENV = "RELATE_MCP_KEY"

# The one path rule: anything inside the repo. That covers `sample_writer/out/` and
# `spool/real/` with no special cases, and nothing outside the repo is reachable.
#
# This is a boundary, not a safety mechanism. `ingest` copies and never deletes the
# source, so a bad path costs a wasted copy, not data. The rule exists so an agent cannot
# read arbitrary files off the machine.
REPO_ROOT = paths.ROOT
ALLOWED_DIRS: tuple[Path, ...] = (REPO_ROOT,)


def config_path() -> Path:
    """Where the keys live. Beside `identity.json`, never committed."""
    return paths.profile_dir() / _CONFIG_FILE


def load() -> dict[str, Any]:
    """Read the key file, generating it on first run.

    Generated once and then left alone: rotating a key is deleting the file, which is a
    deliberate act. A malformed file is regenerated rather than raising, because a broken
    key file must not leave the surface in a half-configured state.
    """
    path = config_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("read_key") and data.get("write_key"):
            return data
    except (OSError, json.JSONDecodeError):
        pass

    data = {
        "read_key": f"r_{secrets.token_urlsafe(24)}",
        "write_key": f"w_{secrets.token_urlsafe(24)}",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data


def presented_key() -> str | None:
    """The key the launching client config handed us, or `None`.

    Read from `os.environ` only. The MCP key never comes from `.env` — that file holds
    mailbox credentials, which this surface may use but never returns.
    """
    value = os.environ.get(KEY_ENV)
    return value.strip() if value and value.strip() else None


def resolve(presented: str | None = None) -> str | None:
    """Which level a key grants: `"write"`, `"read"`, or `None` for no access.

    Compared with `hmac.compare_digest` so a wrong key costs the same time as a right
    one. The write key is checked first: it is the stronger grant, and a store that
    somehow held identical keys would then fail open to the *narrower* level, not wider.
    """
    key = presented if presented is not None else presented_key()
    if not key:
        return None

    data = load()
    if hmac.compare_digest(key, str(data["write_key"])):
        return "write"
    if hmac.compare_digest(key, str(data["read_key"])):
        return "read"
    return None


# ---------------------------------------------------------------- liveness

# How long a heartbeat counts as "an MCP client is connected". The server touches the
# file on every tool call, so a session that is open but idle for longer than this reads
# as gone. Long enough to survive a slow ingest, short enough that a crashed client does
# not leave the badge lit forever.
HEARTBEAT_TTL_SECONDS = 120


def heartbeat_path() -> Path:
    """The file the MCP process touches, and the app's `/api/health` reads.

    A file rather than a socket or a shared process: the two are separate processes by
    design (stdio, §D1), so the only thing they can share is the filesystem.
    """
    return paths.profile_dir() / "mcp.heartbeat"


def touch_heartbeat() -> None:
    """Record that a tool call just happened."""
    path = heartbeat_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(int(time.time())), encoding="utf-8")
    except OSError:
        # A read-only profile must not break a tool call. The badge is a nicety.
        pass


def activity_path() -> Path:
    """The trace the MCP process appends to and the app's UI drains.

    A file for the same reason as the heartbeat: two processes, one filesystem. The UI
    polls it and clears it, so the feed stays a viewport trace rather than a log.
    """
    return paths.profile_dir() / "mcp.activity.jsonl"


def push_activity(text: str, *, status: str = "ok", ms: float | None = None) -> None:
    """Append one row to the trace the UI reads.

    Best-effort: a failure here must never break a tool call. The row is capped at 300
    chars because the UI has a fixed row height and a long Cypher query would push the
    feed off-screen.
    """
    row = {
        "at": time.time(),
        "source": "mcp",
        "text": text[:300],
        "status": status,
    }
    if ms is not None:
        row["ms"] = round(ms, 1)
    try:
        path = activity_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row) + "\n")
    except OSError:
        pass


def peek_activity(limit: int = 40) -> list[dict[str, Any]]:
    """Read the trace **without clearing it**. Newest last.

    The UI drains; an agent peeks. Draining is right for a viewport (a row is shown
    once) and wrong for a question ("what has been happening" must not consume the
    user's view of it).
    """
    path = activity_path()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []

    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows[-limit:]


def drain_activity() -> list[dict[str, Any]]:
    """Read and clear the trace. Called by the app's `/api/activity` endpoint.

    Draining rather than tailing keeps the file from growing without bound and means the
    UI never shows the same row twice. A malformed line is skipped, not raised — a
    half-written row from a killed process must not break the feed.
    """
    path = activity_path()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    try:
        path.unlink()
    except OSError:
        pass

    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def is_active() -> bool:
    """Is an MCP client connected right now?

    True when the heartbeat is younger than `HEARTBEAT_TTL_SECONDS`. A missing file, an
    unreadable one, or a clock that went backwards all read as **not active** — the
    badge must never claim a client is connected when it cannot prove one is.
    """
    try:
        stamp = float(heartbeat_path().read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return False
    age = time.time() - stamp
    return 0 <= age < HEARTBEAT_TTL_SECONDS


def path_allowed(candidate: str | Path) -> bool:
    """Is this path inside the repo?

    Resolved before the test, so `..` and a symlink cannot walk out of the boundary.
    A path that does not exist yet is still checked — `ingest.stage()` raises its own
    `FileNotFoundError`, which is a better message than a permission error.
    """
    try:
        resolved = Path(candidate).expanduser().resolve()
    except (OSError, RuntimeError):
        return False
    return any(resolved == root or root in resolved.parents for root in ALLOWED_DIRS)
