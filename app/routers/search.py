"""Search: the search bar, and raw Cypher for the transparency panel.

`mode` is explicit because the two are different promises. `substring` is a scan
over bodies; `cypher` is whatever the user typed, refused if it would write.
"""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from relate_comms import tools

router = APIRouter(prefix="/api", tags=["search"])


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    mode: Literal["substring", "cypher"] = "substring"
    limit: int = Field(default=20, ge=1, le=500)
    platform: str | None = None
    thread_key: str | None = None
    params: dict[str, Any] | None = None


@router.post("/search")
def search(request: SearchRequest) -> dict:
    """Run a search and return rows for the Viewer's `results` state.

    The response always carries the query that ran, so the UI can show it. That is
    the transparency panel: the user sees exactly what was asked of the graph.
    """
    if request.mode == "cypher":
        return tools.run_cypher(request.query, request.params, limit=request.limit)
    return tools.search_messages(
        request.query,
        limit=request.limit,
        platform=request.platform,
        thread_key=request.thread_key,
    )
