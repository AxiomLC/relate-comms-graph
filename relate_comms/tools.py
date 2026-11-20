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

from . import canon, paths


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

# The platforms the UI can toggle. A platform is not a node type: hiding `telegram`
# must remove Telegram threads, their correspondents AND their messages, which a
# node-type filter cannot express.
#
# This is the declared set, not the observed set. A platform with no adapter yet
# stays listed so the UI can show it as "not built" rather than silently omitting
# it — and so adding the adapter needs no change here.
KNOWN_PLATFORMS: tuple[str, ...] = (
    "messenger", "telegram", "linkedin", "email", "outlook", "whatsapp", "sms",
)

# Platforms with no adapter yet. Listed in the UI as "not built", never offered as
# something to ingest. Adding the adapter means deleting the entry here — and the
# mirrored `PLANNED_PLATFORMS` set in `app/ui/src/components/GraphCanvas.jsx`.
PLANNED_PLATFORMS: tuple[str, ...] = ()

# `None` means "no filter" — every platform. An empty list means "nothing", which
# is a legitimate state (the user unticked everything) and must not silently become
# "everything".
_PLATFORMS: list[str] | None = None


def configure_platforms(platforms: Sequence[str] | None) -> None:
    """Restrict every read tool to these platforms. `None` clears the filter.

    This is a **surface** setting, like `write_enabled`: the UI sets it from its
    Utilities modal and the chat inherits it, so "search only what is on the graph"
    is true rather than aspirational. It is deliberately not a tool argument — a
    model must not be able to widen or narrow what the user is looking at.

    Note this contradicts `TECHREADME.md` §5 ("UI state must never narrow an
    agent's query"). The author overrode that for the platform filter on
    2026-11-16: the graph and the search must agree, or a hit appears for a node
    that is not drawn.
    """
    global _PLATFORMS
    if platforms is None:
        _PLATFORMS = None
        return
    cleaned = [str(p).strip().lower() for p in platforms if str(p).strip()]
    _PLATFORMS = cleaned


def active_platforms() -> list[str] | None:
    """The current filter, or `None` for unfiltered."""
    return list(_PLATFORMS) if _PLATFORMS is not None else None


def _platform_clause(alias: str, params: dict[str, Any]) -> str:
    """A Cypher predicate for the active platform filter, or `""`.

    `alias` is the variable the platform property lives on. The parameter is always
    named `$platforms`, so a caller can add the clause to any MATCH without
    inventing a name.

    **A Correspondent is tested against `platforms`, not `platform`.** A merged node
    keeps one `platform` (the first by date) and lists the rest in `platforms`;
    testing the single string would hide it whenever the user filtered by any
    platform but the first. Every other node type has only `platform`, so the
    predicate falls back to it — `coalesce` makes one clause serve both.
    """
    if _PLATFORMS is None:
        return ""
    params["platforms"] = list(_PLATFORMS)
    return (f"ANY(p IN $platforms "
            f"    WHERE p IN coalesce({alias}.platforms, [{alias}.platform]))")


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
_HIDDEN_PARAMS = frozenset({"write_enabled", "platforms"})


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
#
# The four extracted kinds are **queryable but not drawn by default**: they have zero
# rows until body-entity extraction lands. The UI's `NODE_TYPES` config does know them
# (edit 3) and can draw them once ticked, but they stay off in `filter.nodeTypes` for
# the same reason. They are in `_NODE_QUERIES` so a caller can ask for them explicitly
# and so the queries exist before the writer that fills them.
DRAWABLE_NODE_TYPES: tuple[str, ...] = ("Thread", "Correspondent")

# The four kinds a body-entity extractor will produce. One shape, one query, one
# alias — the only thing that differs is the label. `Correspondent` is deliberately
# not in this set: it is written by ingest, not extracted, and it has its own query
# because `thread_count` is counted through `WITH`.
#
# Derived from `canon.KINDS` so the node type and the canonicalisation kind cannot
# drift apart: `canon` says `product`, the store label says `Product`, and there is
# exactly one place that mapping is written.
ENTITY_KINDS: tuple[str, ...] = tuple(kind.capitalize() for kind in canon.KINDS)

# Which variable each node query binds. A dict rather than an `if` chain: the chain
# grew a branch per type and would have needed a fourth for the entity kinds.
_NODE_ALIAS: dict[str, str] = {
    "Thread": "t",
    "Correspondent": "c",
    "Message": "m",
    "Attachment": "a",
    **{kind: "e" for kind in ENTITY_KINDS},
}

# Node queries are templates: `{where}` is the source-filter predicate (or empty),
# `{order}` is the sort chosen by the caller. Every one of them filters on the node's
# own `platform`, so hiding a source removes the node itself rather than leaving an
# orphan with no edges.
#
# **The sort is not cosmetic.** `limit` truncates, so whichever ordering is in force
# decides which nodes the user can never see. `messages` (the default) keeps the
# biggest threads; `recent` keeps the live ones; `quiet` keeps the ones that went
# silent, which is the question this app exists to answer and the one a
# biggest-first sort hides completely.
_NODE_QUERIES: dict[str, str] = {
    "Thread": (
        "MATCH (t:Thread) "
        "{where}"
        "OPTIONAL MATCH (t)<-[:IN]-(m:Message) "
        "RETURN t.key AS id, t.title AS label, t.platform AS platform, "
        "       t.is_group AS is_group, count(m) AS message_count, "
        "       max(m.ts_utc) AS last_ts, min(m.ts_utc) AS first_ts, "
        # `is_silent` is a fact the canvas needs to offer "hide threads I never
        # spoke in" as a view toggle. Counted here because the messages are already
        # being walked; a second query per thread would be absurd.
        "       sum(CASE WHEN m.is_self THEN 1 ELSE 0 END) = 0 AS is_silent "
        "ORDER BY {order} "
        "LIMIT $n"
    ),
    "Correspondent": (
        # `thread_count` is what tiers a correspondent: it is the only quantity the
        # store has for one. Counted through `WITH`, so a person in ten threads is
        # ten, not the number of messages they sent.
        #
        # `platforms` and `platform_label` are returned because a merged node spans
        # more than one source: the canvas filters on the list, and the Viewer shows
        # the label. `platform` stays the single first-by-date string the filter used
        # to read, so an older client still draws something sensible.
        #
        # `merged` is the `:Merged` label as a boolean. The canvas uses it as the
        # bag-membership test, inverted: a merged node stays outside every platform
        # bag and is pulled by its real edges instead. It is returned as a flag rather
        # than left to `platforms.length > 1` because the label is the merge
        # *decision* and the array is only a report of what that decision saw.
        #
        # `per_platform` is the raw material for `primaryPlatform` / `dominance`,
        # which are derived in Python (`_with_dominance`). It has to be a two-stage
        # aggregation: messages are counted per thread, then summed per platform.
        # A single `count(m)` would count a message once per `WITH` edge it reaches.
        "MATCH (c:Correspondent) "
        "{where}"
        "OPTIONAL MATCH (t:Thread)-[:WITH]->(c) "
        "OPTIONAL MATCH (t)<-[:IN]-(m:Message) "
        "WITH c, t.platform AS p, count(m) AS n, count(DISTINCT t) AS tc "
        # The `WHERE` drops the null row an `OPTIONAL MATCH` emits for a correspondent
        # with no threads at all — otherwise `per_platform` holds one empty entry.
        #
        # The braces are doubled because this template goes through `str.format`,
        # which would otherwise read `{platform: p, ...}` as a placeholder.
        "WITH c, [x IN collect({{platform: p, messages: n, threads: tc}}) "
        "         WHERE x.platform IS NOT NULL] AS per "
        "RETURN c.key AS id, c.display_name AS label, c.platform AS platform, "
        "       coalesce(c.platforms, [c.platform]) AS platforms, "
        "       c.platform_label AS platform_label, per AS per_platform, "
        "       c:Merged AS merged, "
        "       reduce(s = 0, x IN per | s + x.threads) AS thread_count "
        "ORDER BY {order} "
        "LIMIT $n"
    ),
    "Message": (
        "MATCH (m:Message) "
        "{where}"
        "RETURN m.key AS id, m.sender_name AS label, m.platform AS platform, "
        "       m.ts_utc AS ts_utc, m.is_self AS is_self, m.raw_kind AS raw_kind "
        "ORDER BY {order} "
        "LIMIT $n"
    ),
    "Attachment": (
        "MATCH (a:Attachment) "
        "{where}"
        "RETURN a.key AS id, a.filename_scrubbed AS label, a.mime AS mime "
        "ORDER BY {order} "
        "LIMIT $n"
    ),
    # The four extracted kinds share one query. `mention_count` is the only quantity
    # the store will have for them, counted through `MENTIONS` the way a
    # correspondent's `thread_count` is counted through `WITH`. The edge does not
    # exist yet, so this returns 0 today — which is the honest answer, not a bug.
    **{
        kind: (
            f"MATCH (e:{kind}) "
            "{where}"
            "OPTIONAL MATCH (t:Thread)-[:MENTIONS]->(e) "
            "RETURN e.key AS id, e.display_name AS label, e.platform AS platform, "
            "       coalesce(e.platforms, [e.platform]) AS platforms, "
            "       e.platform_label AS platform_label, "
            "       count(DISTINCT t) AS mention_count "
            "ORDER BY {order} "
            "LIMIT $n"
        )
        for kind in ENTITY_KINDS
    },
}

# Sort key -> the ORDER BY fragment for each node type. Every fragment ends in a
# unique tiebreaker, or two nodes with equal counts would swap places between loads
# and the canvas would look like it was shuffling itself.
_SORTS: dict[str, dict[str, str]] = {
    "messages": {
        "Thread": "message_count DESC, id",
        "Correspondent": "thread_count DESC, label, id",
        "Message": "ts_utc DESC, id",
        "Attachment": "id",
        **{kind: "mention_count DESC, label, id" for kind in ENTITY_KINDS},
    },
    "recent": {
        "Thread": "last_ts DESC, id",
        "Correspondent": "thread_count DESC, label, id",
        "Message": "ts_utc DESC, id",
        "Attachment": "id",
        **{kind: "mention_count DESC, label, id" for kind in ENTITY_KINDS},
    },
    "quiet": {
        # Least recently active first. `last_ts` is null for a thread with no
        # messages, and those sort first — a thread with nothing in it is the
        # quietest thing there is.
        "Thread": "last_ts ASC, id",
        "Correspondent": "thread_count ASC, label, id",
        "Message": "ts_utc ASC, id",
        "Attachment": "id",
        **{kind: "mention_count ASC, label, id" for kind in ENTITY_KINDS},
    },
}

SORT_KEYS: tuple[str, ...] = tuple(_SORTS)

# One count per node type, so `graph_slice` can report what the limit hid. Same
# `{where}` predicate as the node query, so the two can never disagree.
_COUNT_QUERIES: dict[str, str] = {
    "Thread": "MATCH (t:Thread) {where}RETURN count(t) AS n",
    "Correspondent": "MATCH (c:Correspondent) {where}RETURN count(c) AS n",
    "Message": "MATCH (m:Message) {where}RETURN count(m) AS n",
    "Attachment": "MATCH (a:Attachment) {where}RETURN count(a) AS n",
    **{kind: f"MATCH (e:{kind}) {{where}}RETURN count(e) AS n" for kind in ENTITY_KINDS},
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
    # A fuzzy identity guess, never a fold (direction.md §5: two edge types, never
    # one). Both endpoints stay; the line is what makes the guess visible and
    # ignorable. Written by `link.py` (edit 4), so it has zero rows today.
    "POSSIBLY": "MATCH (a:Correspondent)-[:POSSIBLY]->(b:Correspondent) "
                "{where}"
                "RETURN a.key AS source, b.key AS target",
    # An extracted entity mentioned in a thread. One entry per kind, because the
    # target label differs and Cypher cannot parameterise a label.
    **{
        f"MENTIONS_{kind.upper()}": (
            f"MATCH (t:Thread)-[:MENTIONS]->(e:{kind}) "
            "{where}"
            "RETURN t.key AS source, e.key AS target"
        )
        for kind in ENTITY_KINDS
    },
}

# Which variable each query's platform predicate applies to.
_EDGE_PLATFORM_ALIAS: dict[str, str] = {
    "WITH": "t",
    "IN": "m",
    "REPLY_TO": "m",
    "HAS_ATTACHMENT": "m",
    # The source correspondent: a merged node is filtered on its `platforms` list,
    # which `_platform_clause` already handles.
    "POSSIBLY": "a",
    **{f"MENTIONS_{kind.upper()}": "t" for kind in ENTITY_KINDS},
}

# Edges whose endpoints are both in the default node set. `IN`, `REPLY_TO` and
# `HAS_ATTACHMENT` all start at a Message, so with the default nodes they can only
# ever be dropped — 12,611 of them. They are available on request, never by default.
#
# `POSSIBLY` is drawn by default because both its endpoints are Correspondents, and
# the line IS the product: a fuzzy guess a human can see and ignore. It is written by
# `link.py` at the end of an ingest, so it is empty until one has run.
DRAWABLE_EDGE_TYPES: tuple[str, ...] = ("WITH", "POSSIBLY")


def _node_where(node_type: str, params: dict[str, Any]) -> str:
    """The `WHERE` line for a node query, honouring the source filter.

    Attachments have no platform, so they are filtered through the message that
    owns them — the only attribution the store can honestly support.
    """
    if node_type == "Attachment":
        clause = _platform_clause("m", params)
        return f"WHERE {clause} " if clause else ""
    alias = _NODE_ALIAS[node_type]
    clause = _platform_clause(alias, params)
    return f"WHERE {clause} " if clause else ""


def _with_dominance(node: dict[str, Any]) -> dict[str, Any]:
    """Add `primaryPlatform` and `dominance` to a Correspondent row.

    **`primaryPlatform` is not `platform`.** `platform` is the first by *date*, so the
    filter and the label do not drift between ingests. `primaryPlatform` is the one
    with the most *messages*, which is a different question and can legitimately
    disagree. Redefining `platform` as dominant would reintroduce exactly the
    instability the date rule exists to prevent.

    `dominance` is the largest platform's share of the node's messages, 0.0-1.0.
    1.0 means every message is on one platform. The canvas uses it as leash length:
    a high-dominance bridge hugs its platform, a 50/50 bridge drifts between them.

    A node with no messages at all (a correspondent in a thread that holds none)
    gets `primaryPlatform = platform` and `dominance = 1.0` — it has one platform and
    nothing to contradict it.
    """
    per = [entry for entry in (node.pop("per_platform", None) or [])
           if entry.get("platform")]
    if not per:
        node["primaryPlatform"] = node.get("platform")
        node["dominance"] = 1.0
        return node

    total = sum(int(entry.get("messages") or 0) for entry in per)
    # Tie-break on the platform name, not on list order: the query's `collect` order
    # is not guaranteed, and a bridge that flips its primary platform between two
    # identical loads would visibly jump on the canvas.
    best = max(per, key=lambda e: (int(e.get("messages") or 0), e["platform"]))
    node["primaryPlatform"] = best["platform"]
    node["dominance"] = round(int(best.get("messages") or 0) / total, 4) if total else 1.0
    return node


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
    sort: str = "messages",
) -> dict[str, Any]:
    """The canvas payload: nodes and edges, ready to hand to graphology.

    `node_types=None` draws every type the canvas draws — Thread and
    Correspondent. Messages are excluded by default because 12,499 nodes is not
    drawable; ask for `["Message"]` explicitly if you want them.

    `edge_types=None` draws every edge whose two endpoints are both drawn.
    An edge with a missing endpoint is counted in `edges_skipped`, never invented.

    `sort` decides **which** nodes survive `limit`: `messages` (biggest first),
    `recent` (most recently active) or `quiet` (least recently active). It is not a
    display preference — the cutoff is real, so the ordering is what makes a hidden
    node hidden.

    Returns `truncated: true` when `limit` cut the node list short, plus `total` —
    the number of nodes that *would* have been drawn. Never assume the returned
    count is the store's count.
    """
    limit = _clamp(limit, 1, 20000)
    wanted_nodes = _resolve_types(node_types, _NODE_QUERIES, DRAWABLE_NODE_TYPES)
    wanted_edges = _resolve_types(edge_types, _EDGE_QUERIES, DRAWABLE_EDGE_TYPES)

    key = str(sort or "messages").strip().lower()
    if key not in _SORTS:
        raise ToolError(f"unknown sort {sort!r}; known sorts are {list(SORT_KEYS)}")
    orders = _SORTS[key]

    nodes: list[dict[str, Any]] = []
    truncated = False
    edges: list[dict[str, Any]] = []
    skipped = 0
    total = 0

    with _session() as conn:
        for node_type in wanted_nodes:
            # Count first, so the UI can say "showing 2,000 of 12,499" instead of
            # leaving the user to guess what the cutoff hid.
            count_params: dict[str, Any] = {}
            count_where = _node_where(node_type, count_params)
            counted = _fetch(
                conn,
                _COUNT_QUERIES[node_type].format(where=count_where),
                count_params,
            )
            total += int(counted[0]["n"]) if counted else 0

            remaining = limit - len(nodes)
            if remaining <= 0:
                truncated = True
                continue
            params: dict[str, Any] = {"n": remaining + 1}
            where = _node_where(node_type, params)
            # Ask for one extra row: that is how we know the limit was hit.
            rows = _fetch(
                conn,
                _NODE_QUERIES[node_type].format(where=where, order=orders[node_type]),
                params,
            )
            if len(rows) > remaining:
                rows = rows[:remaining]
                truncated = True
            for row in rows:
                row["type"] = node_type
                if node_type == "Correspondent":
                    _with_dominance(row)
                nodes.append(row)

        drawn = {node["id"] for node in nodes}
        for edge_type in wanted_edges:
            params = {}
            clause = _platform_clause(_EDGE_PLATFORM_ALIAS[edge_type], params)
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
        "total": total,
        "node_types": wanted_nodes,
        "edge_types": wanted_edges,
        "limit": limit,
        "sort": key,
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
    # A thread on a hidden platform is not readable: the Viewer must not show
    # messages the canvas has removed.
    platform_clause = _platform_clause("m", params)
    if platform_clause:
        clauses.append(platform_clause)
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
        if _PLATFORMS is not None and meta[0].get("platform") not in _PLATFORMS:
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
    platform_clause = _platform_clause("m", params)
    if platform_clause:
        clauses.append(platform_clause)

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
        if _PLATFORMS is not None and rows[0].get("platform") not in _PLATFORMS:
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


# Labels that mark a node rather than describe its kind. `Merged` is additive — a
# merged Correspondent is still a Correspondent — so it must not appear in the
# Toggles modal as a switchable node type of its own.
_MARKER_LABELS = frozenset({"Merged"})


def types_present() -> dict[str, Any]:
    """Node and edge types that actually hold data, with counts.

    Populates the Toggles modal. A type with zero rows is omitted rather than
    listed as empty — a toggle that draws nothing is a lie about the store.

    Marker labels (`Merged`) are skipped: they are additive annotations on a node
    that already has its real type, and `db.labels()` cannot tell the two apart.
    """
    node_types: list[dict[str, Any]] = []
    edge_types: list[dict[str, Any]] = []
    with _session() as conn:
        for row in _fetch(conn, "CALL db.labels()"):
            label = row["label"]
            if label in _MARKER_LABELS:
                continue
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

# The keyword scan is word-bounded, not a substring test. `:Merged` contains `MERGE`,
# so a substring scan refused the audit query the build plan specifies
# (`MATCH (c:Correspondent:Merged) RETURN c.merged_by, count(*)`) — a read-only
# statement rejected as a write. `_WRITE_PATTERN` matches the keyword only as a whole
# word, so `:Merged`, `merged_by` and `SETTING` all pass while `SET` does not.
_WRITE_PATTERN = re.compile(
    r"\b(?:" + "|".join(re.escape(word) for word in _WRITE_KEYWORDS) + r")\b"
)


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
    # is not mistaken for a write. Word-bounded, so `:Merged` is not read as `MERGE`.
    scrubbed = _STRING_LITERAL.sub("''", text).upper()
    found = _WRITE_PATTERN.search(scrubbed)
    if found:
        raise ToolError(
            f"read-only tool: {found.group(0)} is not allowed here; "
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
    which: str = "real",
    *,
    paths_in: Sequence[str] | None = None,
    email: Sequence[str] | None = None,
    since: str | None = None,
    until: str | None = None,
    tz_offset_hours: float | None = None,
    exclude_spam_groups: bool = False,
    exclude_silent_groups: bool = False,
    silent_group_platforms: Sequence[str] | None = None,
    exclude_spam_threads: bool = False,
    spam_thread_platforms: Sequence[str] | None = None,
    prune: bool = False,
    prune_keep: int | None = None,
    write_enabled: bool = False,
) -> dict[str, Any]:
    """Parse exports into the store: stage, parse, resolve, scrub, write, verify.

    `which` is `"real"` (the user's own exports) or `"sample"` (generated demo
    data) — it selects one of the two spool queues. `paths_in` copies files into the
    spool first — the same call the drop zone makes; nothing outside the spool is
    ever parsed or deleted.

    `email` reads live mailboxes over IMAP (`gmail`, `hostinger`). Email is the
    one platform with no file to drop.

    `exclude_spam_groups` applies to Facebook Messenger only: a group thread whose
    rows are mostly housekeeping (`sent a link`, `added X to the group`) is dropped
    rather than written. Off by default — the store is whole unless asked otherwise.

    `exclude_silent_groups` applies to Telegram, WhatsApp and Messenger: a group
    thread the owner never sent a message in is dropped. A group you never spoke in is
    not a conversation you had, and on the real export Messenger's 70 groups hold
    9,513 of 10,605 messages. `silent_group_platforms` narrows it to the platforms the
    user ticked; `None` means all three.

    `exclude_spam_threads` applies to Email and Outlook: a thread with more than 10
    messages where the owner never replied is dropped as likely spam. Separate from
    the group gate on purpose — different scope, different threshold.
    `spam_thread_platforms` narrows it the same way.

    `prune` deletes spool files **only after verification**. It is off by default and
    is not the same thing as `prune_spool`.

    `prune_keep` selects the policy: `None` is the age rule (older than 3 days), `0`
    keeps nothing, `1` keeps the newest run's files, `2` keeps the newest two. Applied
    after the whole run, because "the last ingest" is a property of the run.
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
        which=str(which),
        since=_iso(since),
        until=_iso(until),
        exclude_spam_groups=bool(exclude_spam_groups),
        exclude_silent_groups=bool(exclude_silent_groups),
        silent_group_platforms=silent_group_platforms,
        exclude_spam_threads=bool(exclude_spam_threads),
        spam_thread_platforms=spam_thread_platforms,
        prune=bool(prune),
        prune_keep=None if prune_keep is None else int(prune_keep),
        tz_offset_hours=None if tz_offset_hours is None else float(tz_offset_hours),
        extra_results=extra_results,
    )
    payload = report.to_dict()
    payload["staged"] = staged
    payload["ok"] = report.ok
    return payload


def preview_ingest(which: str = "real") -> dict[str, Any]:
    """What is in the spool, and what has already been ingested. Read-only.

    The modal runs this before the Ingest button so the user is not asked to commit to
    an unknown quantity. It reports size and duplicate status per file; it does **not**
    count messages, because that needs the full parse this exists to avoid.
    """
    from . import ingest as ingest_module

    return ingest_module.preview(which=str(which))


def truncate_store(
    *,
    write_enabled: bool = False,
    confirm: bool = False,
    also_identity: bool = False,
    also_spool: bool = False,
) -> dict[str, Any]:
    """Delete the graph, and the record of what was ingested into it.

    Destructive: needs write access **and** `confirm=true` in the call itself, so a
    model cannot wipe the store on its own initiative.

    **The manifest goes with the graph, always.** `store/profile/ingested.json` says
    "this file is already in the store"; leaving it behind after a wipe would make the
    next ingest skip every file it had ever seen and produce an empty graph that looks
    like a successful run. That is the one thing this function must not allow.

    `also_identity` removes `store/profile/identity.json` — the per-platform owners and
    tz offsets. Kept by default, because re-ingesting the same account needs them: the
    tz offset is part of every wall-clock message key. Drop it when switching accounts,
    or a stale owner silently marks every row `is_self=False`.

    `also_spool` removes the exports themselves from `spool/real/`. Off by default —
    the spool is the user's own downloads, and a wipe of the graph is not a request to
    delete them. It exists because sample files dropped in for a test will otherwise be
    re-ingested alongside the real ones.
    """
    require(Access.DESTRUCTIVE, write_enabled=write_enabled, confirmed=confirm)

    from . import manifest

    removed: list[str] = []
    kept: list[str] = []

    store = paths.store_path()
    if store.exists():
        store.unlink()
        removed.append(str(store))
    else:
        kept.append(f"{store} (did not exist)")

    # Always, and not optional: see the docstring.
    record = paths.profile_dir() / manifest.MANIFEST_FILE
    if record.exists():
        record.unlink()
        removed.append(str(record))

    identity_file = paths.profile_dir() / "identity.json"
    if also_identity and identity_file.exists():
        identity_file.unlink()
        removed.append(str(identity_file))
    elif identity_file.exists():
        kept.append(str(identity_file))

    if also_spool:
        root = paths.real_dir()
        for entry in sorted(root.rglob("*")):
            if entry.is_file() and entry.name != ".gitkeep":
                entry.unlink()
                removed.append(str(entry))

    return {
        "removed": removed,
        "kept": kept,
        "store_exists": paths.store_path().exists(),
    }


def verify_ingest(which: str = "real") -> dict[str, Any]:
    """Re-parse the spool and report, per file, how many keys are missing.

    The question this answers is "did everything land?", not "did the job exit 0".
    A file whose keys are not all in the store is the one thing that must block a
    prune.
    """
    from . import ingest as ingest_module

    batches = [b for b in ingest_module.discover(paths.real_dir()) if b.recognised]

    if not batches:
        return {"which": which, "files": [], "ok": True, "missing": 0,
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
        "which": which,
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
        (preview_ingest, Access.READ),
        (truncate_store, Access.DESTRUCTIVE),
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
