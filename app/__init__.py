"""The app: a local-only 3D comms graph UI with an optional local AI.

Three rules this app must never break:

1. **No outbound API calls.** The chat module talks to Ollama on localhost and
   nothing else. There is no "API mode". If the model is not configured the chat
   box simply does not appear; the rest of the UI is unaffected.
2. **Local by default.** The server binds to loopback. Remote UI access is the
   user's own private tunnel; MCP is the authenticated remote path.
3. **One tool layer.** Every surface binds `relate_comms.tools`. Nothing here
   contains its own query or ingest logic.

Layout:

    app/main.py        FastAPI app, startup, static mount
    app/graph/         3D view data: nodes/edges filtered by type toggles
    app/search/        cypher | semantic | hybrid
    app/chat/          local LLM bound to the same tool set
    app/mcp/           same tool set over MCP, with auth
    app/static/        the single-page 3D frontend

Not yet written — this package is a scaffold. See TECHREADME.md §2.
"""
