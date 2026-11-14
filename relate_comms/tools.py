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
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable


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
        """Derived from the signature. Filled in when the first tool lands."""
        raise NotImplementedError("tool schema derivation is not implemented yet")


# Planned tool surface. Registered when each is implemented.
#
# READ
#   search_messages(query, limit)          -> full-text / semantic over Message.body
#   semantic_search(embedding, k)          -> db.index.vector.queryNodes
#   hybrid_search(query, k)               -> vector then traverse
#   run_cypher(query, params, limit)       -> read-only Cypher, returned with the query for display
#   thread_arc(thread_key)                -> "met -> worked -> went quiet" summary
#   person_profile(person_key)            -> identities, platforms, first/last seen
#   graph_slice(node_types, edge_types)    -> nodes/edges filtered for the 3D view
#   message_view(message_key)              -> the viewer box: body as text/MD
#   evidence_counts()                      -> kept/hidden/blocked, non-text kinds
#
# WRITE
#   ingest(source, platform, since, until) -> parse -> write -> verify
#   verify_ingest(batch_id)                -> is every key in the store?
#
# DESTRUCTIVE
#   prune_spool(older_than_days, confirm)  -> only verified files, never else

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
