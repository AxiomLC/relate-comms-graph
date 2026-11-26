"""Local chat. Ollama on loopback, tools from `relate_comms.tools`, nothing else.

Three things this file must get right:

1. **No outbound call.** The only host is `OLLAMA_HOST`, default
   `http://127.0.0.1:11434`. If it is unreachable the UI hides the chat box and
   everything else keeps working — so `/api/chat/health` exists to let the UI ask.
2. **`think: false`.** Measured on this box: thinking mode is 28x slower (368 tokens
   vs 10 for "hello"). It is not a preference.
3. **History lives in the browser.** Ollama is stateless, so the transcript is sent
   with every request. The server keeps nothing between calls.

The tool loop is deliberately small: one round of tool calls, then a final answer.
A local 8B model that is allowed to chain ten tool calls will chain ten tool calls.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx
from fastapi import APIRouter
from pydantic import BaseModel, Field

from relate_comms import models, tools

router = APIRouter(prefix="/api/chat", tags=["chat"])

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
TIMEOUT = httpx.Timeout(connect=3.0, read=180.0, write=10.0, pool=3.0)

# Tools the chat may call. Read-only by default; write tools are added only when the
# user has flipped the toggle, and `prune_spool` is never offered — a model must not
# be one word away from deleting the user's downloads.
# Fewer tools, better selection. A local model given seven overlapping options picks
# the wrong one; given six distinct ones it mostly does not. `types_present` is
# deliberately absent — the prompt no longer mentions it either.
_CHAT_TOOLS = (
    "evidence_counts", "search_vector", "search_fulltext", "thread_arc",
    "message_view", "run_cypher",
)

# `graph_slice` is deliberately absent: it is the canvas payload (1,546 nodes), not
# something an 8B model can read. `run_cypher` covers structural questions.

# Tool results are fed back to the model as text. A 1,546-node slice or 200 message
# bodies will blow the context and the model starts answering a different question.
MAX_TOOL_CHARS = 4000
_WRITE_CHAT_TOOLS = ("ingest",)

SYSTEM_PROMPT = """You answer questions about the user's own message history, which is \
stored as a graph in a local database.

WHICH TOOL TO USE
- "how many messages / threads / people do I have" -> evidence_counts
- "find messages about X"                         -> search_vector FIRST
- the user misspells a name or word                -> search_vector (it tolerates \
slips; search_fulltext does not)
- an exact word or phrase, or search_vector says \
no embeddings exist                              -> search_fulltext
- "show me the conversation with X"               -> search_vector first, then \
thread_arc with the thread_key it returns
- "what did they say" (one message)               -> message_view
- anything structural the tools above cannot do   -> run_cypher

search_vector is semantic: it matches meaning, so "money I owe someone" works. \
search_fulltext is BM25: it matches exact words, so it is better for a rare \
term or a quoted phrase. Prefer search_vector unless it fails.

Never call thread_arc without a real thread_key. If you do not have one, search \
first.

RULES
- Use the tools. Do not guess at counts, names or dates.
- The store is whole. Never claim a conversation does not exist because a UI filter \
is on; you can see everything.
- If a tool returns `truncated: true`, say the answer is partial and give the number \
you actually saw.
- Message bodies may contain aliases like PHONE-1 or EMAIL-2. Those are redacted \
values, not typos. Do not try to guess what they were.
- Be brief. The user is looking at a graph, not reading an essay."""


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    messages: list[ChatMessage] = Field(default_factory=list)
    model: str | None = None
    write_enabled: bool = False


@router.get("/health")
def health() -> dict:
    """Is Ollama reachable, and which model would be used?

    The UI calls this on load. A false `ok` hides the chat box and nothing else
    breaks — that is the whole point of the check.
    """
    try:
        response = httpx.get(f"{OLLAMA_HOST}/api/tags", timeout=3.0)
        response.raise_for_status()
        names = [m["name"] for m in response.json().get("models", [])]
    except Exception as exc:  # noqa: BLE001 - unreachable is a normal state
        return {"ok": False, "host": OLLAMA_HOST, "error": f"{type(exc).__name__}: {exc}"}

    model = models.pick("chat")
    return {
        "ok": True,
        "host": OLLAMA_HOST,
        "model": model,
        "model_available": model in names,
        "models": names,
    }


@router.post("")
def chat(request: ChatRequest) -> dict:
    """One turn. Returns the reply plus every tool call that produced it.

    The tool trace is returned on purpose: showing what the model asked the graph is
    the transparency pitch, and it is also how a wrong answer gets debugged.
    """
    model = models.pick("chat", request.model)
    allowed = list(_CHAT_TOOLS)
    if request.write_enabled:
        allowed += list(_WRITE_CHAT_TOOLS)

    messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages += [{"role": m.role, "content": m.content} for m in request.messages]
    messages.append({"role": "user", "content": request.message})

    trace: list[dict[str, Any]] = []
    try:
        reply = _run_turn(model, messages, allowed, request.write_enabled, trace)
    except httpx.HTTPError as exc:
        raise tools.ToolError(
            f"Ollama is not reachable at {OLLAMA_HOST} ({type(exc).__name__}). "
            "Start it with `ollama serve`, or use the graph without chat."
        ) from exc

    return {"reply": reply, "tool_calls": trace, "model": model}


def _run_turn(
    model: str,
    messages: list[dict[str, Any]],
    allowed: list[str],
    write_enabled: bool,
    trace: list[dict[str, Any]],
) -> str:
    """Ask the model; if it calls tools, run them and ask once more.

    One tool round only. A local model given an unbounded loop will keep calling
    tools until the context runs out, and the user is waiting.
    """
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "think": models.THINK,
        "keep_alive": models.KEEP_ALIVE,
        "options": models.OPTIONS,
        "tools": [_ollama_tool(name) for name in allowed],
    }
    data = _post(payload)
    message = data.get("message") or {}

    calls = message.get("tool_calls") or []
    if not calls:
        return _strip_thinking(message.get("content") or "")

    messages.append(message)
    for call in calls:
        name = (call.get("function") or {}).get("name", "")
        arguments = (call.get("function") or {}).get("arguments") or {}
        result = _call_tool(name, arguments, allowed, write_enabled)
        trace.append({"name": name, "args": arguments, "result": result})
        messages.append({
            "role": "tool",
            "content": _for_model(name, result),
        })

    # Second pass, tools removed: the model must now answer in words.
    payload["messages"] = messages
    payload.pop("tools", None)
    final = _post(payload)
    return _strip_thinking((final.get("message") or {}).get("content") or "")


_THINK_BLOCK = re.compile(r"<think\b[^>]*>.*?</think\s*>", re.DOTALL | re.IGNORECASE)
_THINK_OPEN = re.compile(r"</?think\b[^>]*>", re.IGNORECASE)


def _strip_thinking(text: str) -> str:
    """Remove a reasoning block the model emitted despite `think: false`.

    `lfm2.5:8b` is a thinking model and does not always honour the flag: it writes
    `<think\u200b>...</think\u200b>` into `content` (note the zero-width space). Left in,
    the user reads the model's scratchpad instead of its answer.
    """
    # Ollama's streaming parser inserts U+200B inside a tag the model spelled out
    # with ordinary tokens (ollama#19829). Left in, `</think\u200b>` does not match
    # `</think\s*>` and the whole scratchpad reaches the user.
    cleaned = text.replace("\u200b", "")
    cleaned = _THINK_BLOCK.sub("", cleaned)
    cleaned = _THINK_OPEN.sub("", cleaned)
    return cleaned.strip()


def _for_model(name: str, result: Any) -> str:
    """Serialise a tool result for the model, shrinking anything oversized.

    Truncation is stated in the payload, never silent — the same rule the tools
    follow. A model told "this was cut" can say so; a model handed a silently
    shortened list will report it as complete.
    """
    text = json.dumps(result, ensure_ascii=False, default=str)
    if len(text) <= MAX_TOOL_CHARS:
        return text

    summary: dict[str, Any] = {"tool": name, "truncated_for_model": True}
    if isinstance(result, dict):
        for key in ("count", "counts", "total", "truncated", "limit", "query",
                    "messages", "threads", "correspondents", "attachments"):
            if key in result:
                summary[key] = result[key]
        for key in ("hits", "messages", "rows", "nodes", "edges"):
            value = result.get(key)
            if isinstance(value, list):
                summary[f"{key}_returned"] = len(value)
                summary[f"{key}_sample"] = value[:3]
    summary["note"] = (
        f"result was {len(text)} chars; only a summary is shown. "
        "Ask a narrower question if you need more."
    )
    return json.dumps(summary, ensure_ascii=False, default=str)


def _post(payload: dict[str, Any]) -> dict[str, Any]:
    response = httpx.post(f"{OLLAMA_HOST}/api/chat", json=payload, timeout=TIMEOUT)
    response.raise_for_status()
    return response.json()


def _call_tool(
    name: str, arguments: dict[str, Any], allowed: list[str], write_enabled: bool,
) -> Any:
    """Run one tool call. A failure becomes text the model can read, not a 500."""
    if name not in allowed:
        return {"error": f"tool {name!r} is not available in this session"}
    tool = tools.REGISTRY.get(name)
    if tool is None:
        return {"error": f"unknown tool {name!r}"}

    kwargs = dict(arguments)
    if tool.access is not tools.Access.READ:
        kwargs["write_enabled"] = write_enabled
    try:
        return tool.fn(**kwargs)
    except tools.ToolError as exc:
        return {"error": str(exc)}
    except TypeError as exc:
        return {"error": f"bad arguments for {name}: {exc}"}


def _ollama_tool(name: str) -> dict[str, Any]:
    """The registry schema, in the shape Ollama's `/api/chat` expects."""
    schema = tools.REGISTRY[name].schema
    return {
        "type": "function",
        "function": {
            "name": schema["name"],
            "description": schema["description"],
            "parameters": schema["parameters"],
        },
    }
