"""The tool layer — one definition, three surfaces.

Every capability the app can perform is a plain function here. Nothing in this
package imports FastAPI, MCP, or an LLM SDK. That is deliberate:

    app/mcp/     binds these -> MCP tools
    app/chat/    binds these -> local LLM function calls
    app/routers/ binds these -> HTTP for the UI

so the UI, the local model and MCP cannot drift apart. If a tool works from the
chat box it works over MCP, because it is the same function.

WRITE SAFETY (user toggle, not an architectural restriction)
------------------------------------------------------------
Read tools are always available. Mutating tools are tagged `WRITE` and are
refused unless the caller has been granted write access. The UI exposes that as
a toggle; MCP has its own separate toggle. `prune` is `DESTRUCTIVE` and also
requires write access, so a user who enabled write for ingest still cannot have
a model delete spool files accidentally.

TOOL CONTRACT
-------------
Each tool: plain callable, JSON-serialisable args and return value, docstring
that doubles as the LLM tool description. No exceptions escaping as anything
other than ToolError, so a model gets a readable failure instead of a traceback.

`write_enabled` is a keyword-only argument on every mutating tool and is
**excluded from the derived schema** — it is the surface's toggle, not something
a model may set for itself. `confirm` is *not* excluded: a model is expected to
pass it deliberately for `prune_spool`, and the docstring says so.

WHAT IS IMPLEMENTED (2026-11-15)
--------------------------------
READ   graph_slice, thread_arc, search_messages, message_view,
       types_present, evidence_counts, run_cypher
WRITE  ingest, verify_ingest
DESTR. prune_spool

NOT IMPLEMENTED, AND DELIBERATELY NOT REGISTERED
------------------------------------------------
    semantic_search, hybrid_search   no vector index exists in the store and no
                                     embeddings are written; registering a tool
                                     that always fails burns a model turn
    person_profile, who_did_i_talk_to  `Person` and `SENT` have zero rows
                                     (TECHREADME.md §4) — the queries would return
                                     nothing and look like a bug in the tool

TOGGLE MODEL — views filter, queries do not
---------------------------------------------------
The store is always whole. UI node/edge toggles are a VIEW concern: they decide
what a drawing shows, never what a query can reach.

  UI graph canvas   toggles hide nodes/edges from this drawing  (client-side)
  UI search         optional filter on the one query being run  (query-time WHERE)
  UI chat agent     may ask for the whole graph or any subset   (its choice)
  MCP agent         same                                        (its choice)

Therefore NO tool may take the current toggles as an implicit input. Slicing is
always an explicit argument, defaulting to everything:

  graph_slice(node_types=None, edge_types=None, limit=2000)
    node_types=None means "every type the canvas draws" - not "none" and not
    "whatever the UI has on". A hidden UI toggle silently narrowing an agent's
    view is the failure mode nobody catches in a demo.

TRUNCATION IS NEVER SILENT. A slice that hits `limit` must return the count it
returned plus `truncated: true`, or an agent will report "you have 2000 messages"
when the store holds 1215 or 25000.
"""
from __future__ import annotations

import inspect
import re
import types
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Literal, Union, get_args, get_origin, get_type_hints

from . import paths


class Access(str, Enum):
    READ = "read"              # always allowed
    WRITE = "write"            # needs the surface's write toggle
    DESTRUCTIVE = "destructive"  # needs write AND an explicit confirm argument


class ToolError(Exception):
    """A tool failed in a way the caller should see and can act on."""


@dataclass(frozen=True)
class Tool:
    name: str
    fn: Callable[..., Any]
    access: Access
    description: str

    @property
    def schema(self) -> dict[str, Any]:
        """Derived from the signature, in the shape Ollama and MCP both accept."""
        return _schema_from_signature(self.fn)


REGISTRY: dict[str, Tool] = {}


def register(tool: Tool) -> None:
    if tool.name in REGISTRY:
        raise ValueError(f"tool already registered: {tool.name}")
    REGISTRY[tool.name] = tool


def require(access: Access, *, write_enabled: bool, confirmed: bool = False) -> None:
    """Gate a call. Raises ToolError with a message a model can act on."""
    if access is Access.READ:
        return
    if not write_enabled:
        raise ToolError(
            f"write access is disabled for this surface; enable it to use {access.value} tools"
        )
    if access is Access.DESTRUCTIVE and not confirmed:
        raise ToolError(
            "destructive tool requires confirm=true; it will not run on a model's initiative alone"
        )


# ------------------------------------------------------------------ the store

_STORE: Path | None = None


def configure(*, store: str | Path | None = None) -> None:
    """Point the tool layer at a store. `None` restores `paths.store_path()`.

    A module-level override rather than a `store` argument on every tool: a store
    path in the schema is one more thing a model can get wrong, and there is only
    ever one store.
    """
    global _STORE
    _STORE = Path(store) if store else None


def store_path() -> Path:
    return _STORE or paths.store_path()


# ------------------------------------------------------------- source filter

# The platforms the UI can toggle. A source is a platform, not a node type: hiding
# `telegram` must remove Telegram threads, their correspondents AND their messages,
# which a node-type filter cannot express.
KNOWN_SOURCES: tuple[str, ...] = (
    "messenger", "telegram", "linkedin", "email", "whatsapp", "sms",
)

# `None` means "no filter" — every source. An empty list means "nothing", which is
# a legitimate state (the user unticked everything) and must not silently become
# "everything".
_SOURCES: list[str] | None = None


def configure_sources(sources: Sequence[str] | None) -> None:
    """Restrict every read tool to these platforms. `None` clears the filter.

    This is a **surface** setting, like `write_enabled`: the UI sets it from its
    Utilities modal and the chat inherits it, so "search only what is on the graph"
    is true rather than aspirational. It is deliberately not a tool argument — a
    model must not be able to widen or narrow what the user is looking at.

    Note this contradicts `TECHREADME.md` §5 ("UI state must never narrow an
    agent's query"). The author overrode that for sources on 2026-11-16: the graph
    and the search must agree, or a hit appears for a node that is not drawn.
    """
    global _SOURCES
    if sources is None:
        _SOURCES = None
        return
    cleaned = [str(s).strip().lower() for s in sources if str(s).strip()]
    _SOURCES = cleaned


def active_sources() -> list[str] | None:
    """The current filter, or `None` for unfiltered."""
    return list(_SOURCES) if _SOURCES is not None else None


def _source_clause(alias: str, params: dict[str, Any]) -> str:
    """A Cypher predicate for the active source filter, or `""`.

    `alias` is the variable the platform property lives on. The parameter is always
    named `$sources`, so a caller can add the clause to any MATCH without inventing
    a name.
    """
    if _SOURCES is None:
        return ""
    params["sources"] = list(_SOURCES)
    return f"{alias}.platform IN $sources"


def _connect(*, read_only: bool = True) -> Any:
    path = store_path()
    if not path.exists():
        raise ToolError(
            f"no store at {path}; run `python -m relate_comms ingest` first"
        )
    try:
        import relate
        return relate.connect(str(path), read_only=read_only)
    except ToolError:
        raise
    except Exception as exc:  # noqa: BLE001 - the caller gets a readable failure
        raise ToolError(f"cannot open store {path}: {type(exc).__name__}: {exc}") from exc


@contextmanager
def _session(*, read_only: bool = True) -> Iterator[Any]:
    """One connection per tool call.

    Opening the 19 MB store costs ~120 ms, so a connection per *query* made
    `graph_slice` take 1.2 s. A connection per *call* is the right unit: the
    cursor never outlives the tool, so no surface can read another's stale result
    set, and a multi-query tool pays the open once.
    """
    conn = _connect(read_only=read_only)
    try:
        yield conn
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001 - closing must never mask the real error
            pass


def _fetch(conn: Any, cypher: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Run one statement on an open connection and return plain dicts."""
    try:
        cur = conn.cursor()
        cur.execute(cypher, params or {})
        return [dict(row) for row in cur.fetchall()]
    except ToolError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ToolError(f"query failed: {type(exc).__name__}: {exc}") from exc


def _scalar(conn: Any, cypher: str, params: dict[str, Any] | None = None) -> Any:
    rows = _fetch(conn, cypher, params)
    return next(iter(rows[0].values())) if rows else None


# ------------------------------------------------------------------- schema

# Never shown to a model: the surface's own toggles, not model-settable arguments.
# `sources` is here for the same reason as `write_enabled` — it is the UI's state,
# and a model that could set it would be able to answer from data the user hid.
_HIDDEN_PARAMS = frozenset({"write_enabled", "sources"})


def _json_type(annotation: Any) -> dict[str, Any]:
    """Python annotation -> JSON Schema fragment. Unknown types become `{}`."""
    if annotation is inspect.Parameter.empty or annotation is Any:
        return {}

    origin = get_origin(annotation)
    if origin is Union or origin is types.UnionType:
        args = [a for a in get_args(annotation) if a is not type(None)]
        if len(args) == 1:
            return _json_type(args[0])
        return {"anyOf": [_json_type(a) for a in args]}

    if origin is Literal:
        return {"enum": list(get_args(annotation))}

    if origin in (list, tuple, set, frozenset) or origin is Sequence:
        args = get_args(annotation)
        item = _json_type(args[0]) if args else {}
        return {"type": "array", "items": item} if item else {"type": "array"}

    if origin is dict or annotation is dict:
        return {"type": "object"}
    # `bool` before `int`: they are distinct types, but the order documents intent.
    if annotation is bool:
        return {"type": "boolean"}
    if annotation is int:
        return {"type": "integer"}
    if annotation is float:
        return {"type": "number"}
    if annotation is str:
        return {"type": "string"}
    return {}


def _schema_from_signature(fn: Callable[..., Any]) -> dict[str, Any]:
    hints = get_type_hints(fn)
    signature = inspect.signature(fn)
    properties: dict[str, Any] = {}
    required: list[str] = []

    for name, param in signature.parameters.items():
        if name in _HIDDEN_PARAMS:
            continue
        if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
            continue
        prop = _json_type(hints.get(name, param.annotation))
        if param.default is inspect.Parameter.empty:
            required.append(name)
        elif param.default is not None:
            prop = {**prop, "default": param.default}
        properties[name] = prop

    return {
        "name": fn.__name__,
        "description": (fn.__doc__ or "").strip(),
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": required,
        },
    }


# ------------------------------------------------------------------ helpers

def _clamp(value: int, low: int, high: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = low
    return max(low, min(number, high))


def _iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ToolError(f"not an ISO-8601 date: {value!r}") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _snippet(body: str, needle: str, width: int = 160) -> str:
    """A window around the first match, with ellipses. Never the whole body."""
    if not body:
        return ""
    index = body.lower().find(needle.lower())
    if index < 0:
        text = body[:width]
        return text + ("…" if len(body) > width else "")
    start = max(0, index - width // 3)
    end = min(len(body), start + width)
    text = body[start:end].replace("\n", " ")
    return ("…" if start else "") + text + ("…" if end < len(body) else "")


# --------------------------------------------------------------- read tools

# The canvas draws these and nothing else (UI-Cytoscape.md §3): 955 threads is
# drawable, 12,499 messages is not. Asking for `Message` is explicit, never default.
DRAWABLE_NODE_TYPES: tuple[str, ...] = ("Thread", "Correspondent")

# Node queries are templates: `{where}` is the source-filter predicate (or empty).
# Every one of them filters on the node's own `platform`, so hiding a source removes
# the node itself rather than leaving an orphan with no edges.
_NODE_QUERIES: dict[str, str] = {
    "Thread": (
        "MATCH (t:Thread) "
        "{where}"
        "OPTIONAL MATCH (t)<-[:IN]-(m:Message) "
        "RETURN t.key AS id, t.title AS label, t.platform AS platform, "
        "       t.is_group AS is_group, count(m) AS message_count, "
        "       max(m.ts_utc) AS last_ts, min(m.ts_utc) AS first_ts "
        "ORDER BY message_count DESC, id "
        "LIMIT $n"
    ),
    "Correspondent": (
        # `thread_count` is what tiers a correspondent: it is the only quantity the
        # store has for one. Counted through `WITH`, so a person in ten threads is
        # ten, not the number of messages they sent.
        "MATCH (c:Correspondent) "
        "{where}"
        "OPTIONAL MATCH (t:Thread)-[:WITH]->(c) "
        "RETURN c.key AS id, c.display_name AS label, c.platform AS platform, "
        "       count(DISTINCT t) AS thread_count "
        "ORDER BY thread_count DESC, label, id "
        "LIMIT $n"
    ),
    "Message": (
        "MATCH (m:Message) "
        "{where}"
        "RETURN m.key AS id, m.sender_name AS label, m.platform AS platform, "
        "       m.ts_utc AS ts_utc, m.is_self AS is_self, m.raw_kind AS raw_kind "
        "ORDER BY m.ts_utc DESC "
        "LIMIT $n"
    ),
    "Attachment": (
        "MATCH (a:Attachment) "
        "{where}"
        "RETURN a.key AS id, a.filename_scrubbed AS label, a.mime AS mime "
        "ORDER BY id "
        "LIMIT $n"
    ),
}

# `Attachment` has no platform of its own; it inherits the message's. The filter is
# applied through the owning message, which is the only honest way to attribute it.
_ATTACHMENT_SOURCE_WHERE = (
    "MATCH (m:Message)-[:HAS_ATTACHMENT]->(a) WHERE {pred} "
)

_EDGE_QUERIES: dict[str, str] = {
    "WITH": "MATCH (t:Thread)-[:WITH]->(c:Correspondent) "
            "{where}"
            "RETURN t.key AS source, c.key AS target",
    "IN": "MATCH (m:Message)-[:IN]->(t:Thread) "
          "{where}"
          "RETURN m.key AS source, t.key AS target",
    "REPLY_TO": "MATCH (m:Message)-[:REPLY_TO]->(r:Message) "
                "{where}"
                "RETURN m.key AS source, r.key AS target",
    "HAS_ATTACHMENT": "MATCH (m:Message)-[:HAS_ATTACHMENT]->(a:Attachment) "
                      "{where}"
                      "RETURN m.key AS source, a.key AS target",
}

# Which variable each query's platform predicate applies to.
_EDGE_SOURCE_ALIAS: dict[str, str] = {
    "WITH": "t",
    "IN": "m",
    "REPLY_TO": "m",
    "HAS_ATTACHMENT": "m",
}

# Edges whose endpoints are both in the default node set. `IN`, `REPLY_TO` and
# `HAS_ATTACHMENT` all start at a Message, so with the default nodes they can only
# ever be dropped — 12,611 of them. They are available on request, never by default.
DRAWABLE_EDGE_TYPES: tuple[str, ...] = ("WITH",)


def _node_where(node_type: str, params: dict[str, Any]) -> str:
    """The `WHERE` line for a node query, honouring the source filter.

    Attachments have no platform, so they are filtered through the message that
    owns them — the only attribution the store can honestly support.
    """
    if node_type == "Attachment":
        clause = _source_clause("m", params)
        return f"WHERE {clause} " if clause else ""
    alias = "m" if node_type == "Message" else ("c" if node_type == "Correspondent" else "t")
    clause = _source_clause(alias, params)
    return f"WHERE {clause} " if clause else ""


def _resolve_types(
    requested: Sequence[str] | None, known: dict[str, str], default: Sequence[str],
) -> list[str]:
    if requested is None:
        return list(default)
    if isinstance(requested, str):
        requested = [requested]
    resolved: list[str] = []
    for name in requested:
        clean = str(name).strip()
        if clean not in known:
            raise ToolError(
                f"unknown type {clean!r}; known types are {sorted(known)}"
            )
        if clean not in resolved:
            resolved.append(clean)
    return resolved


def graph_slice(
    node_types: Sequence[str] | None = None,
    edge_types: Sequence[str] | None = None,
    limit: int = 2000,
) -> dict[str, Any]:
    """The canvas payload: nodes and edges, ready to hand to graphology.

    `node_types=None` draws every type the canvas draws — Thread and
    Correspondent. Messages are excluded by default because 12,499 nodes is not
    drawable; ask for `["Message"]` explicitly if you want them.

    `edge_types=None` draws every edge whose two endpoints are both drawn.
    An edge with a missing endpoint is counted in `edges_skipped`, never invented.

    Returns `truncated: true` when `limit` cut the node list short. Never assume
    the returned count is the store's count.
    """
    limit = _clamp(limit, 1, 20000)
    wanted_nodes = _resolve_types(node_types, _NODE_QUERIES, DRAWABLE_NODE_TYPES)
    wanted_edges = _resolve_types(edge_types, _EDGE_QUERIES, DRAWABLE_EDGE_TYPES)

    nodes: list[dict[str, Any]] = []
    truncated = False
    edges: list[dict[str, Any]] = []
    skipped = 0

    with _session() as conn:
        for node_type in wanted_nodes:
            remaining = limit - len(nodes)
            if remaining <= 0:
                truncated = True
                break
            params: dict[str, Any] = {"n": remaining + 1}
            where = _node_where(node_type, params)
            # Ask for one extra row: that is how we know the limit was hit.
            rows = _fetch(
                conn, _NODE_QUERIES[node_type].format(where=where), params,
            )
            if len(rows) > remaining:
                rows = rows[:remaining]
                truncated = True
            for row in rows:
                row["type"] = node_type
                nodes.append(row)

        drawn = {node["id"] for node in nodes}
        for edge_type in wanted_edges:
            params = {}
            clause = _source_clause(_EDGE_SOURCE_ALIAS[edge_type], params)
            where = f"WHERE {clause} " if clause else ""
            for row in _fetch(
                conn, _EDGE_QUERIES[edge_type].format(where=where), params,
            ):
                if row["source"] in drawn and row["target"] in drawn:
                    row["type"] = edge_type
                    edges.append(row)
                else:
                    skipped += 1

    return {
        "nodes": nodes,
        "edges": edges,
        "counts": {"nodes": len(nodes), "edges": len(edges)},
        "node_types": wanted_nodes,
        "edge_types": wanted_edges,
        "limit": limit,
        "truncated": truncated,
        "edges_skipped": skipped,
    }


def thread_arc(
    thread_key: str,
    *,
    skip: int = 0,
    limit: int = 50,
    query: str | None = None,
) -> dict[str, Any]:
    """One thread's messages, newest first — what the Viewer renders.

    `skip`/`limit` page the thread; the 707-message thread must never be rendered
    in one go. `query` filters **inside this thread only**, never the store.

    `total` is the count matching the filter, so the caller can page correctly
    without guessing. `has_more` is `skip + len(messages) < total`.
    """
    if not thread_key or not str(thread_key).strip():
        raise ToolError("thread_key is required")
    key = str(thread_key).strip()
    skip = _clamp(skip, 0, 1_000_000)
    limit = _clamp(limit, 1, 200)

    params: dict[str, Any] = {"k": key}
    clauses: list[str] = []
    if query and str(query).strip():
        clauses.append("toLower(m.body) CONTAINS toLower($q)")
        params["q"] = str(query).strip()
    # A thread from a hidden source is not readable: the Viewer must not show
    # messages the canvas has removed.
    source = _source_clause("m", params)
    if source:
        clauses.append(source)
    where = f"WHERE {' AND '.join(clauses)} " if clauses else ""

    with _session() as conn:
        meta = _fetch(
            conn,
            "MATCH (t:Thread {key: $k}) "
            "OPTIONAL MATCH (t)-[:WITH]->(c:Correspondent) "
            "RETURN t.key AS key, t.title AS title, t.platform AS platform, "
            "       t.is_group AS is_group, collect(c.display_name) AS correspondents",
            {"k": key},
        )
        if not meta:
            raise ToolError(f"no thread with key {key!r}")
        if _SOURCES is not None and meta[0].get("platform") not in _SOURCES:
            raise ToolError(
                f"thread {key!r} is from {meta[0].get('platform')!r}, "
                "which is hidden by the source filter"
            )

        total = _scalar(
            conn,
            f"MATCH (t:Thread {{key: $k}})<-[:IN]-(m:Message) {where}RETURN count(m) AS n",
            params,
        ) or 0

        # The thread's own span, unfiltered. The Viewer's arc ("first … · quiet 2y")
        # is three facts, and two of them are these. Kept as a separate query so the
        # correspondents OPTIONAL MATCH above cannot multiply the message rows.
        span = _fetch(
            conn,
            "MATCH (t:Thread {key: $k})<-[:IN]-(m:Message) "
            "RETURN min(m.ts_utc) AS first_ts, max(m.ts_utc) AS last_ts",
            {"k": key},
        )

        params.update({"s": skip, "n": limit})
        rows = _fetch(
            conn,
            "MATCH (t:Thread {key: $k})<-[:IN]-(m:Message) "
            f"{where}"
            "RETURN m.key AS key, m.ts_utc AS ts_utc, m.is_self AS is_self, "
            "       m.sender_name AS sender_name, m.body AS body, "
            "       m.raw_kind AS raw_kind, m.has_attachments AS has_attachments "
            "ORDER BY m.ts_utc DESC "
            "SKIP $s LIMIT $n",
            params,
        )
        attachments = _attachments_for(conn, [row["key"] for row in rows])

    thread = meta[0]
    thread["correspondents"] = [n for n in thread.get("correspondents") or [] if n]
    if span:
        thread["first_ts"] = span[0].get("first_ts")
        thread["last_ts"] = span[0].get("last_ts")
    for row in rows:
        row["attachments"] = attachments.get(row["key"], [])

    thread["message_count"] = total
    return {
        "thread": thread,
        "messages": rows,
        "skip": skip,
        "limit": limit,
        "total": total,
        "has_more": skip + len(rows) < total,
        "query": params.get("q"),
    }


def _attachments_for(
    conn: Any, message_keys: Sequence[str],
) -> dict[str, list[dict[str, Any]]]:
    if not message_keys:
        return {}
    rows = _fetch(
        conn,
        "MATCH (m:Message)-[:HAS_ATTACHMENT]->(a:Attachment) "
        "WHERE m.key IN $keys "
        "RETURN m.key AS msg_key, a.key AS key, a.filename_scrubbed AS path, "
        "       a.mime AS mime, a.size AS size",
        {"keys": list(message_keys)},
    )
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        msg_key = row.pop("msg_key")
        grouped.setdefault(msg_key, []).append(row)
    return grouped


def search_messages(
    query: str,
    *,
    limit: int = 20,
    platform: str | None = None,
    thread_key: str | None = None,
) -> dict[str, Any]:
    """Case-insensitive substring search over message bodies, newest first.

    This is a substring scan, not a relevance ranking — `mode` says so. Results
    are ordered by `ts_utc DESC`, so a common word returns the most recent hits
    rather than the best ones.

    `platform` and `thread_key` narrow the search; both are explicit arguments.
    The active **source filter** also applies, so a search can only return what the
    canvas is drawing — that is the point of the Utilities modal.
    """
    if not query or not str(query).strip():
        raise ToolError("query is required")
    needle = str(query).strip()
    limit = _clamp(limit, 1, 200)

    clauses = ["toLower(m.body) CONTAINS toLower($q)"]
    params: dict[str, Any] = {"q": needle, "n": limit + 1}
    if platform and str(platform).strip():
        clauses.append("m.platform = $platform")
        params["platform"] = str(platform).strip()
    if thread_key and str(thread_key).strip():
        clauses.append("m.chat_id = $chat_id")
        params["chat_id"] = _chat_id_from_thread_key(str(thread_key).strip())
    source = _source_clause("m", params)
    if source:
        clauses.append(source)

    with _session() as conn:
        rows = _fetch(
            conn,
            "MATCH (m:Message) "
            f"WHERE {' AND '.join(clauses)} "
            "RETURN m.key AS key, m.ts_utc AS ts_utc, m.platform AS platform, "
            "       m.chat_id AS chat_id, m.sender_name AS sender_name, "
            "       m.is_self AS is_self, m.body AS body "
            "ORDER BY m.ts_utc DESC "
            "LIMIT $n",
            params,
        )

    truncated = len(rows) > limit
    rows = rows[:limit]
    hits = [
        {
            "key": row["key"],
            "ts_utc": row["ts_utc"],
            "platform": row["platform"],
            "thread_key": f"{row['platform']}:{row['chat_id']}",
            "sender_name": row["sender_name"],
            "is_self": row["is_self"],
            "snippet": _snippet(row["body"] or "", needle),
        }
        for row in rows
    ]
    return {
        "query": needle,
        "mode": "substring",
        "hits": hits,
        "count": len(hits),
        "limit": limit,
        "truncated": truncated,
    }


def _chat_id_from_thread_key(thread_key: str) -> str:
    """`platform:chat_id` -> `chat_id`. Chat ids may themselves contain `:`."""
    _, _, chat_id = thread_key.partition(":")
    if not chat_id:
        raise ToolError(f"not a thread key: {thread_key!r}")
    return chat_id


def message_view(message_key: str) -> dict[str, Any]:
    """One message in full, with its thread, attachments and what it replies to.

    The Viewer's `node` state for a message. Bodies are returned whole here —
    this is one message, not a page of them.
    """
    if not message_key or not str(message_key).strip():
        raise ToolError("message_key is required")
    key = str(message_key).strip()

    with _session() as conn:
        rows = _fetch(
            conn,
            "MATCH (m:Message {key: $k}) "
            "OPTIONAL MATCH (m)-[:IN]->(t:Thread) "
            "RETURN m.key AS key, m.platform AS platform, m.chat_id AS chat_id, "
            "       m.ts_utc AS ts_utc, m.sender_name AS sender_name, "
            "       m.sender_id AS sender_id, m.body AS body, m.is_self AS is_self, "
            "       m.raw_kind AS raw_kind, m.has_attachments AS has_attachments, "
            "       t.key AS thread_key, t.title AS thread_title",
            {"k": key},
        )
        if not rows:
            raise ToolError(f"no message with key {key!r}")
        if _SOURCES is not None and rows[0].get("platform") not in _SOURCES:
            raise ToolError(
                f"message {key!r} is from {rows[0].get('platform')!r}, "
                "which is hidden by the source filter"
            )

        reply = _fetch(
            conn,
            "MATCH (m:Message {key: $k})-[:REPLY_TO]->(r:Message) "
            "RETURN r.key AS key, r.ts_utc AS ts_utc, r.sender_name AS sender_name, "
            "       r.body AS body",
            {"k": key},
        )
        attachments = _attachments_for(conn, [key])

    message = rows[0]
    message["attachments"] = attachments.get(key, [])
    message["reply_to"] = reply[0] if reply else None
    return message


def types_present() -> dict[str, Any]:
    """Node and edge types that actually hold data, with counts.

    Populates the Toggles modal. A type with zero rows is omitted rather than
    listed as empty — a toggle that draws nothing is a lie about the store.
    """
    node_types: list[dict[str, Any]] = []
    edge_types: list[dict[str, Any]] = []
    with _session() as conn:
        for row in _fetch(conn, "CALL db.labels()"):
            label = row["label"]
            count = _scalar(conn, "MATCH (n) WHERE $lbl IN labels(n) RETURN count(n) AS n",
                            {"lbl": label}) or 0
            if count:
                node_types.append({"type": label, "count": count})

        for row in _fetch(conn, "CALL db.relationshipTypes()"):
            rel = row["relationshipType"]
            count = _scalar(conn, "MATCH ()-[r]->() WHERE type(r) = $t RETURN count(r) AS n",
                            {"t": rel}) or 0
            if count:
                edge_types.append({"type": rel, "count": count})

    return {
        "node_types": sorted(node_types, key=lambda t: t["type"]),
        "edge_types": sorted(edge_types, key=lambda t: t["type"]),
    }


# Alias prefixes the scrub gate writes (`scrub.AliasMap`): `PHONE-1`, `EMAIL-2`.
_ALIAS_PREFIXES: dict[str, str] = {
    "PHONE": "phones",
    "EMAIL": "emails",
    "ADDR": "addresses",
    "CARD": "card_numbers",
}
_ALIAS_RE = re.compile(r"\b(PHONE|EMAIL|ADDR|CARD)-(\d+)\b")


def evidence_counts() -> dict[str, Any]:
    """The evidence panel: what was withheld, and what is not plain text.

    `withheld` counts **distinct aliases**, not messages — "we withheld 14 phone
    numbers" is the claim, and one number repeated across 30 messages is one
    number. Aliases are recovered by scanning bodies for the `PHONE-1` shape,
    which is the only trace the scrub gate leaves by design.

    Blocked messages are absent from the store by construction, so they cannot be
    counted here; the ingest report is the record for those.
    """
    with _session() as conn:
        bodies = _fetch(
            conn,
            "MATCH (m:Message) "
            "WHERE m.body CONTAINS 'PHONE-' OR m.body CONTAINS 'EMAIL-' "
            "   OR m.body CONTAINS 'ADDR-' OR m.body CONTAINS 'CARD-' "
            "RETURN m.body AS body",
        )
        non_text = {
            row["kind"]: row["n"]
            for row in _fetch(
                conn,
                "MATCH (m:Message) WHERE m.raw_kind <> 'text' "
                "RETURN m.raw_kind AS kind, count(m) AS n ORDER BY n DESC",
            )
        }
        platforms = {
            row["platform"]: row["n"]
            for row in _fetch(
                conn,
                "MATCH (m:Message) RETURN m.platform AS platform, count(m) AS n "
                "ORDER BY n DESC",
            )
        }
        totals = {
            "messages": _scalar(conn, "MATCH (m:Message) RETURN count(m) AS n") or 0,
            "threads": _scalar(conn, "MATCH (t:Thread) RETURN count(t) AS n") or 0,
            "correspondents":
                _scalar(conn, "MATCH (c:Correspondent) RETURN count(c) AS n") or 0,
            "attachments":
                _scalar(conn, "MATCH (a:Attachment) RETURN count(a) AS n") or 0,
        }

    seen: dict[str, set[str]] = {kind: set() for kind in _ALIAS_PREFIXES.values()}
    for row in bodies:
        for prefix, number in _ALIAS_RE.findall(row["body"] or ""):
            seen[_ALIAS_PREFIXES[prefix]].add(f"{prefix}-{number}")

    withheld = {kind: len(values) for kind, values in seen.items() if values}

    return {
        **totals,
        "withheld": withheld,
        "withheld_total": sum(withheld.values()),
        "non_text": non_text,
        "non_text_total": sum(non_text.values()),
        "platforms": platforms,
    }


# Statements that would mutate the store. The connection is opened read-only, so
# the engine refuses these anyway — this list exists to turn an engine error into
# a sentence a model can act on.
_WRITE_KEYWORDS = (
    "CREATE", "MERGE", "DELETE", "DETACH", "SET", "REMOVE", "DROP", "FOREACH",
    "LOAD CSV", "ALTER", "GRANT", "DENY", "REVOKE", "CALL DBMS", "CALL APOC",
)
_STRING_LITERAL = re.compile(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"")


def run_cypher(
    query: str,
    params: dict[str, Any] | None = None,
    *,
    limit: int = 500,
) -> dict[str, Any]:
    """Run a read-only Cypher statement and return its rows.

    For the transparency panel and for an agent that needs a shape no other tool
    covers. Write statements are refused before they reach the engine.

    Truncation happens after the query runs, so a statement with its own `LIMIT`
    is not rewritten. `truncated: true` means rows were dropped from the response,
    not that the query was altered.
    """
    if not query or not str(query).strip():
        raise ToolError("query is required")
    text = str(query).strip()
    limit = _clamp(limit, 1, 5000)

    # Scan with string literals removed, so `WHERE m.body CONTAINS 'create'`
    # is not mistaken for a write.
    scrubbed = _STRING_LITERAL.sub("''", text).upper()
    for keyword in _WRITE_KEYWORDS:
        if keyword in scrubbed:
            raise ToolError(
                f"read-only tool: {keyword} is not allowed here; "
                "use ingest or prune_spool for writes"
            )

    with _session() as conn:
        try:
            cur = conn.cursor()
            cur.execute(text, params or {})
            rows = [dict(row) for row in cur.fetchall()]
            columns = list(cur.columns)
        except ToolError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ToolError(f"cypher failed: {type(exc).__name__}: {exc}") from exc

    truncated = len(rows) > limit
    return {
        "query": text,
        "params": params or {},
        "columns": columns,
        "rows": rows[:limit],
        "count": min(len(rows), limit),
        "limit": limit,
        "truncated": truncated,
    }


# -------------------------------------------------------------- write tools

def ingest(
    source: str = "real",
    *,
    paths_in: Sequence[str] | None = None,
    email: Sequence[str] | None = None,
    since: str | None = None,
    until: str | None = None,
    tz_offset_hours: float | None = None,
    prune: bool = False,
    write_enabled: bool = False,
) -> dict[str, Any]:
    """Parse exports into the store: stage, parse, resolve, scrub, write, verify.

    `source` is `"real"` (the user's own exports) or `"sample"` (generated demo
    data). `paths_in` copies files into the spool first — the same call the drop
    zone makes; nothing outside the spool is ever parsed or deleted.

    `email` reads live mailboxes over IMAP (`gmail`, `hostinger`). Email is the
    one platform with no file to drop.

    `prune` deletes spool files older than 3 days **only after verification**.
    It is off by default and is not the same thing as `prune_spool`.
    """
    require(Access.WRITE, write_enabled=write_enabled)

    from . import ingest as ingest_module

    staged: list[str] = []
    if paths_in:
        try:
            staged = [str(p) for p in ingest_module.stage(list(paths_in))]
        except FileNotFoundError as exc:
            raise ToolError(str(exc)) from exc

    extra_results = []
    if email:
        from .cli import _fetch_mailboxes
        extra_results = _fetch_mailboxes(list(email), _iso(since), _iso(until))

    report = ingest_module.ingest(
        source=str(source),
        since=_iso(since),
        until=_iso(until),
        prune=bool(prune),
        tz_offset_hours=None if tz_offset_hours is None else float(tz_offset_hours),
        extra_results=extra_results,
    )
    payload = report.to_dict()
    payload["staged"] = staged
    payload["ok"] = report.ok
    return payload


def verify_ingest(source: str = "real") -> dict[str, Any]:
    """Re-parse the spool and report, per file, how many keys are missing.

    The question this answers is "did everything land?", not "did the job exit 0".
    A file whose keys are not all in the store is the one thing that must block a
    prune.
    """
    from . import ingest as ingest_module

    batches = [b for b in ingest_module.discover(
        paths.sample_dir() if source == "sample" else paths.real_dir()
    ) if b.recognised]

    if not batches:
        return {"source": source, "files": [], "ok": True, "missing": 0,
                "note": "no recognised exports in the spool"}

    # Re-parse with the offset the store was built with. A wall-clock platform's
    # key hashes `ts_utc`, so verifying at the default 0 against rows written at -5
    # reports every key missing while the store is perfectly intact.
    from . import identity

    profile = paths.profile_dir()
    offsets = {
        platform: identity.load_tz_offset(profile, platform)
        for platform in {b.platform for b in batches if b.platform}
    }
    parse_kwargs: dict[str, Any] = {
        "tz_offsets": {p: o for p, o in offsets.items() if o is not None},
    }

    parsed = ingest_module.parse_batches(batches, parse_kwargs=parse_kwargs, workers=1)
    conn = _connect()
    try:
        from . import writer
        files: list[dict[str, Any]] = []
        total_missing = 0
        for batch, result, error in parsed:
            if error or result is None:
                files.append({"path": str(batch.path), "platform": batch.platform,
                              "error": error or "parse produced no result"})
                continue
            ok, info = writer.verify_present(conn, result)
            total_missing += info["missing"]
            files.append({"path": str(batch.path), "platform": batch.platform,
                          "ok": ok, **info})
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass

    return {
        "source": source,
        "files": files,
        "missing": total_missing,
        "ok": total_missing == 0 and not any("error" in f for f in files),
    }


def prune_spool(
    older_than_days: int = 3,
    *,
    write_enabled: bool = False,
    confirm: bool = False,
) -> dict[str, Any]:
    """Delete spool files older than N days that already verified into the store.

    Destructive: requires write access **and** `confirm=true` in the call itself,
    so a model cannot tidy up the user's downloads on its own initiative. A file
    that cannot be re-parsed, or whose keys are not all present, is kept.
    """
    require(Access.DESTRUCTIVE, write_enabled=write_enabled, confirmed=confirm)

    from . import ingest as ingest_module

    days = _clamp(older_than_days, 1, 3650)
    removed = ingest_module.prune_spool(older_than=timedelta(days=days))
    return {"removed": removed, "count": len(removed), "older_than_days": days}


# --------------------------------------------------------------- registration

def _register_all() -> None:
    for fn, access in (
        (graph_slice, Access.READ),
        (thread_arc, Access.READ),
        (search_messages, Access.READ),
        (message_view, Access.READ),
        (types_present, Access.READ),
        (evidence_counts, Access.READ),
        (run_cypher, Access.READ),
        (ingest, Access.WRITE),
        (verify_ingest, Access.READ),
        (prune_spool, Access.DESTRUCTIVE),
    ):
        register(Tool(
            name=fn.__name__,
            fn=fn,
            access=access,
            description=(fn.__doc__ or "").strip(),
        ))


_register_all()
