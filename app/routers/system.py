"""Health, store summary, the type list, and the platform filter.

The platform filter is a **surface** setting: the UI sets it here, and every read
endpoint plus the chat inherits it. That is what makes "search only what the graph
is showing" true rather than a promise.

`platform` is the one term for the social network (telegram, messenger, email…).
It is not the export file (`export_path`) and not the user's download.
"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from relate_comms import tools

from app.mcp import config as mcp_config

router = APIRouter(prefix="/api", tags=["system"])


class PlatformsRequest(BaseModel):
    platforms: list[str] | None = None


@router.get("/health")
def health() -> dict:
    """Is the server up, and is there a store behind it?

    Deliberately cheap: it does not open the graph. The UI calls this on load to
    decide whether to show the canvas or the "ingest something first" state.
    """
    path = tools.store_path()
    return {
        "ok": True,
        "store": str(path),
        "store_exists": path.exists(),
        "store_bytes": path.stat().st_size if path.exists() else 0,
        # **A heartbeat, not a flag.** The MCP server is a separate stdio process, so the
        # only thing it can share with this one is the filesystem: it stamps
        # `store/profile/mcp.heartbeat` on every tool call, and this reads how old that
        # stamp is. A missing or stale file reads as False — the badge must never claim
        # a client is connected when it cannot prove one is.
        "mcp_active": mcp_config.is_active(),
    }


@router.get("/activity")
def activity() -> dict:
    """Drain the MCP activity trace.

    **Draining, not tailing.** The MCP server is a separate process, so it appends rows
    to a file; this reads them and deletes the file. That means the UI never shows the
    same row twice and the file cannot grow without bound. Search and chat rows are
    pushed in the browser and never come through here.
    """
    return {"rows": mcp_config.drain_activity()}


@router.get("/stats")
def stats() -> dict:
    """The evidence panel: counts, withheld aliases, non-text kinds, platforms."""
    return tools.evidence_counts()


@router.get("/types")
def types() -> dict:
    """Node and edge types that actually hold data, with counts."""
    return tools.types_present()


@router.get("/platforms")
def platforms() -> dict:
    """Every platform in the store, with counts, plus the active filter.

    Deliberately **unfiltered**: the Utilities modal has to list a platform the user
    has hidden, or they could never turn it back on.
    """
    counts = tools.evidence_counts()["platforms"]
    active = tools.active_platforms()

    # Every known platform is listed, including ones with no adapter yet, so the
    # modal can say "not built" instead of the platform appearing to not exist.
    # A platform with zero rows is still listed: it is a fact about the store.
    rows = [
        {
            "platform": platform,
            "count": counts.get(platform, 0),
            "built": platform not in tools.PLANNED_PLATFORMS,
        }
        for platform in tools.KNOWN_PLATFORMS
    ]
    # Anything in the store that is not in the known list (a future adapter) is
    # appended rather than dropped — the modal must be able to show it.
    for platform, count in counts.items():
        if platform not in tools.KNOWN_PLATFORMS:
            rows.append({"platform": platform, "count": count, "built": True})

    return {
        "platforms": rows,
        "active": active,
        "filtered": active is not None,
    }


@router.post("/platforms")
def set_platforms(request: PlatformsRequest) -> dict:
    """Apply the platform filter. `null` clears it; `[]` hides everything."""
    tools.configure_platforms(request.platforms)
    return platforms()
