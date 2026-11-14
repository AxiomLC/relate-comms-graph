"""MCP surface. Ships, flagged dangerous, recommended with a LOCAL model only.

Most users will drive this from their IDE. That is the supported path. What
makes it dangerous is the same thing that makes it useful: an agent with write
access to a comms graph can read everything the user ever said.

Safeguards this surface must implement:

1. **Auth toggle.** Off by default for stdio (the process is already yours);
   required for any network transport. Never silently unauthenticated on TCP.
2. **Write toggle, separate from the UI's.** An IDE session does not inherit the
   UI's choices. Default off.
3. **Destructive tools need confirm=true** in the call itself — `prune_spool`
   will not run because a model decided to tidy up.
4. **Loopback binding** for any HTTP/socket transport. Remote access is the
   user's private tunnel, not something this server arranges.

Not implemented. Tools are the registry in `relate_comms.tools`:

    relate_comms/tools.py     <- the definitions (read/write/destructive)
    app/mcp/server.py         <- binds them, adds auth + toggles
"""
