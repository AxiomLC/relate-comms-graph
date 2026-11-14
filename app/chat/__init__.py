"""Local-only chat. Talks to Ollama on loopback; there is no cloud path.

Hard rules:

- **No outbound calls.** The only HTTP client target is `OLLAMA_HOST`
  (default 127.0.0.1:11434). If it is unreachable, the UI hides the chat box and
  everything else keeps working.
- **Same tools as MCP.** Binds `relate_comms.tools`, never re-implements a query.
- **Write is a user toggle.** Read tools always available; WRITE tools refused
  unless the user enabled write; DESTRUCTIVE tools additionally need confirm=true
  so a model cannot prune the spool on its own initiative.
- Model default comes from `relate_comms.models.pick(task)`. Measured on this
  box: lfm2.5:8b (MoE, 21 tok/s) over qwen3.5:4b (8.5 tok/s), 8 samples only.

Not implemented. Target interface:

    POST /api/chat {message, write_enabled: bool}
      -> {"reply", "tool_calls": [{name, args, result}]}

The tool call trace is shown in the UI on purpose: transparency is the pitch.
"""
