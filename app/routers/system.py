"""Health, store summary, the type list, and the source filter.

The source filter is a **surface** setting: the UI sets it here, and every read
endpoint plus the chat inherits it. That is what makes "search only what the graph
is showing" true rather than a promise.
"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from relate_comms import tools

router = APIRouter(prefix="/api", tags=["system"])


class SourcesRequest(BaseModel):
    sources: list[str] | None = None


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
    }


@router.get("/stats")
def stats() -> dict:
    """The evidence panel: counts, withheld aliases, non-text kinds, platforms."""
    return tools.evidence_counts()


@router.get("/types")
def types() -> dict:
    """Node and edge types that actually hold data, with counts."""
    return tools.types_present()


@router.get("/sources")
def sources() -> dict:
    """Every platform in the store, with counts, plus the active filter.

    Deliberately **unfiltered**: the Utilities modal has to list a source the user
    has hidden, or they could never turn it back on.
    """
    counts = tools.evidence_counts()["platforms"]
    active = tools.active_sources()
    return {
        "sources": [
            {"platform": platform, "count": count}
            for platform, count in counts.items()
        ],
        "active": active,
        "filtered": active is not None,
    }


@router.post("/sources")
def set_sources(request: SourcesRequest) -> dict:
    """Apply the source filter. `null` clears it; `[]` hides everything."""
    tools.configure_sources(request.sources)
    return sources()
