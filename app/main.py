"""The FastAPI app: the browser's backend.

This is the hub the UI talks to. It owns no query logic — every endpoint is a thin
wrapper over `relate_comms.tools`, which is also what the chat and MCP bind. If a
tool works here it works everywhere, because it is the same function.

    Browser  --HTTP-->  this app  --HTTP-->  Ollama (127.0.0.1:11434)
                            |
                            +--> relate_comms/tools.py --> store/graph.rl

Two rules this file enforces:

1. **Loopback only.** The server binds 127.0.0.1. There is no deployment story and
   no outbound call; the only network peer is Ollama on the same machine.
2. **A tool failure is a 400 with a sentence in it**, never a 500 traceback. The
   tool layer raises `ToolError`; the handler below turns it into JSON a model or a
   human can act on.

Run: python -m app
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from relate_comms import tools

from .routers import chat, graph, ingest, search, system

STATIC = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Point the tool layer at a store before the first request.

    `RELATE_STORE` overrides the default so a test or a second store can be served
    without touching the repo's `store/graph.rl`.
    """
    tools.configure(store=os.environ.get("RELATE_STORE") or None)
    yield


app = FastAPI(
    title="relate-comms",
    version="0.2.0",
    description="A local-only viewer for your message graph.",
    lifespan=lifespan,
)


@app.exception_handler(tools.ToolError)
async def tool_error_handler(request: Request, exc: tools.ToolError) -> JSONResponse:
    """A tool refused or failed. 400, not 500 — the caller can fix this."""
    return JSONResponse(status_code=400, content={"error": str(exc)})


app.include_router(system.router)
app.include_router(graph.router)
app.include_router(search.router)
app.include_router(chat.router)
app.include_router(ingest.router)

app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")
