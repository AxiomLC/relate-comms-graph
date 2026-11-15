"""Health, store summary and the type list that populates the Toggles modal."""
from __future__ import annotations

from fastapi import APIRouter

from relate_comms import tools

router = APIRouter(prefix="/api", tags=["system"])


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
