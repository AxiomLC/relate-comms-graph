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
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from relate_comms import tools

from .routers import chat, graph, ingest, search, system

STATIC = Path(__file__).parent / "static"


class IconsElsewhere(StaticFiles):
    """Serve `/static/icons/*` with `Cache-Control: no-cache`; everything else as before.

    **Why icons and not the whole static tree.** An icon is a *file at a fixed URL*.
    Replacing `place-merged.svg` reuses the same path, so a browser is entitled to keep
    serving its cached copy — and a hard refresh does not reliably clear an image that
    is referenced from a CSS rule rather than from the HTML. That produced a real "the
    new art did not appear" report while the server was serving the new file.

    `no-cache` does NOT mean "never store": it means "revalidate before reuse". The
    `ETag` / `Last-Modified` this mount already sends answer that check with a 304 when
    nothing changed, so the cost is one conditional request per icon per load — nothing
    on localhost, and it removes the need for any `?v=` query stamp in the UI.

    Deliberately NOT applied to the whole mount: `app.js` and the vendored Cytoscape
    bundles are large and their names carry no hash, so making them revalidate too would
    trade a real download for a problem that does not exist — a rebuild changes them and
    `/` is already `no-store`, so the shell always points at a fresh bundle.
    """

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        # **Normalise the separator.** Starlette passes the relative path with the OS
        # separator, so on Windows this arrives as `icons\place-merged.svg` and a
        # `startswith("icons/")` test silently never matches — the header was absent and
        # nothing said so. Verified, not assumed.
        if path.replace("\\", "/").startswith("icons/"):
            response.headers["Cache-Control"] = "no-cache"
        return response


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

app.mount("/static", IconsElsewhere(directory=STATIC), name="static")


@app.get("/", include_in_schema=False)
def index() -> HTMLResponse:
    """Serve the shell.

    `no-store` because the page is the entry point for a rebuilt bundle: a cached
    shell would keep pointing at a stale `app.js` after `npm run build`, which reads
    as "my change did nothing".
    """
    return HTMLResponse(
        content=(STATIC / "index.html").read_text(encoding="utf-8"),
        headers={"Cache-Control": "no-store"},
    )
