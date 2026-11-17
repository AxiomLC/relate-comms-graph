"""The canvas and the Viewer.

`/api/graph` is the whole drawing; `/api/thread/{key}` is one thread's messages,
paged. The canvas never asks for messages — 12,499 nodes is not drawable — and the
Viewer never asks for the whole graph.
"""
from __future__ import annotations

from fastapi import APIRouter, Query

from relate_comms import tools

router = APIRouter(prefix="/api", tags=["graph"])


@router.get("/graph")
def graph(
    nodes: str | None = Query(
        default=None,
        description="Comma-separated node types. Omit for Thread,Correspondent.",
    ),
    edges: str | None = Query(
        default=None,
        description="Comma-separated edge types. Omit for WITH.",
    ),
    limit: int = Query(default=2000, ge=1, le=20000),
    sort: str = Query(
        default="messages",
        description="Which nodes survive `limit`: messages | recent | quiet",
    ),
) -> dict:
    """Nodes and edges, already shaped for graphology.

    The UI's toggles are sent **explicitly** here when the user changes them. They
    are never applied implicitly: a hidden toggle must not narrow what an agent can
    query, so the default is everything the canvas draws.

    `sort` is not a display preference — `limit` truncates, so the ordering decides
    which nodes the user can never reach.
    """
    return tools.graph_slice(
        node_types=_split(nodes),
        edge_types=_split(edges),
        limit=limit,
        sort=sort,
    )


@router.get("/thread/{thread_key:path}")
def thread(
    thread_key: str,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    q: str | None = Query(default=None, description="Filter inside this thread only"),
) -> dict:
    """One thread's messages, newest first, paged.

    `thread_key` uses `:path` because a key is `platform:chat_id` and chat ids may
    themselves contain a colon.
    """
    return tools.thread_arc(thread_key, skip=skip, limit=limit, query=q)


@router.get("/message/{message_key:path}")
def message(message_key: str) -> dict:
    """One message in full: body, thread, attachments, what it replies to."""
    return tools.message_view(message_key)


def _split(value: str | None) -> list[str] | None:
    """`"Thread,Correspondent"` -> `["Thread", "Correspondent"]`; empty -> None."""
    if not value:
        return None
    items = [part.strip() for part in value.split(",") if part.strip()]
    return items or None
