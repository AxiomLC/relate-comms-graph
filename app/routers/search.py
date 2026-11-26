"""Search: the search bar, and raw Cypher for the transparency panel.

`mode` is explicit because the three are different promises:

- `fulltext` — BM25 over bodies. **The default.** Ranked, indexed, milliseconds.
  Word matching, not substring: `"graf"` does not match `"grafana"`.
- `vector`   — semantic. Needs an embed pass; raises a message the UI turns into
  the yellow "run embeds" warning.
- `cypher`   — whatever the user typed, refused if it would write.

`substring` is kept as an alias for `fulltext` so an old client does not 400.
"""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from relate_comms import tools

router = APIRouter(prefix="/api", tags=["search"])


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    mode: Literal["fulltext", "vector", "cypher", "substring"] = "fulltext"
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
    if request.mode == "vector":
        return tools.search_vector(
            request.query, limit=request.limit, platform=request.platform,
        )
    # `fulltext`, and `substring` as a legacy alias.
    return tools.search_fulltext(
        request.query, limit=request.limit, platform=request.platform,
    )


@router.get("/embed/status")
def embed_status() -> dict:
    """How much of the store has vectors. Drives the warning and the progress bar."""
    return tools.embed_status()


class EmbedRequest(BaseModel):
    limit: int = Field(default=5000, ge=1, le=200_000)
    write_enabled: bool = False


@router.post("/embed/flush")
def flush_embeds(request: EmbedRequest) -> dict:
    """Delete every vector and reclaim the disk. Destructive.

    Rewrites the store rather than nulling a property: measured on this engine,
    `SET m.emb = null` frees nothing and `DROP INDEX` frees nothing. Only a fresh
    write reclaims. Measured 64.7 MB -> 3.6 MB in 1.9 s on the live store.
    """
    return tools.flush_embeddings(
        write_enabled=request.write_enabled, confirm=True,
    )


@router.post("/embed")
def embed(request: EmbedRequest) -> dict:
    """Embed one batch of messages that have no vector yet.

    The UI calls this repeatedly until `done` is true, so a long backfill shows
    progress and can be stopped between batches. Deliberately **not** part of
    ingest: measured at ~3-42 msg/s depending on body length, so a large store is
    hours of work that must not block an ingest.
    """
    return tools.embed_messages(
        limit=request.limit, write_enabled=request.write_enabled,
    )
