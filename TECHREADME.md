# TECHREADME.md

Condensed technical reference. Written for an AI picking this up cold: module map, key
functions, commands, and the constraints that are not obvious from the code.

Human-facing overview: [`README.md`](README.md). What is next: [`HANDOVER.md`](HANDOVER.md).

---

## 0. Terms — the canonical key

Five terms carry the whole model. If a word is not in this table, it is prose, not a
concept. Use these spellings in code, in Cypher, in the UI and in docs.

| Term | Code / store | Definition | Deliberately NOT |
|---|---|---|---|
| **Owner** | `identity.py`, `store/profile/identity.json` | The account owner. Per platform, persisted, with `tz_offsets`. | Not a node. Not a `Correspondent`. Shown on UI only as "you" inside a message body. |
| **Correspondent** | `(:Correspondent {key, display_name, platform, handle, email, phone_e164})`, key `<platform>:<name>` | The other party, **on one platform**. A fact from the export. | Not one human across platforms. Not an extracted entity. |
| **Platform** | `platform` property on every node; `_PLATFORMS` filter in `tools.py` | The social network: `telegram`, `messenger`, `email`, `linkedin`, `whatsapp`, `sms`. | Not the export file. Not the user's download. |
| **Thread** | `(:Thread {key, platform, title, is_group})` | One conversation. | Not a message. |
| **Message** | `(:Message {key, platform, chat_id, message_id, …})` | One message. | Not a thread. |

Ingest path — three more, and they are not interchangeable:

| Term | Code | Definition |
|---|---|---|
| **Download** | (user's filesystem) | The raw file the user got from the platform. Never moved, never deleted. |
| **Export** | `IngestResult.export_path`, `parse(export_path)` | The copy inside `spool/`, which is what gets parsed. For live email, an `imap://` URL. |
| **Root** | `ingest(root=…)`, `ingest(which=…)`, `--which` | Which spool queue to read: `real` (the user's) or `sample` (generated demo data). |

### Not terms yet

`Person`, `Place`, `Organization`, `Product` name a **future extraction step**: entities
pulled out of a message body that are neither the Owner nor a Correspondent. There is no
node type, no writer, no query and no UI for them. Never query against them.

`schema.Person`, `schema.Identity`, `resolution.py` and `writer.write_people()` exist but
produce nothing in the store. Be precise about which is which:

- `resolution.collect()` / `resolution.merge()` **are** called from `ingest()` — their
  counts land in the report as `who_matched` / `identities`, then the result is discarded.
- `writer.write_people()` is **never** called, so no `Person` or `Identity` node is ever
  written and no `MATCHED_BY` / `SENT` edge exists.

### The `messenger` / Facebook Messenger split

The store key is `messenger` and must stay that way: it is part of every `Message.key`
(`platform:chat_id:message_id`), and changing it would orphan every existing row. The UI
shows **Fcbk Mssgr** — never bare "Messenger", which reads as "a message" beside a
`Message` node. Abbreviated on purpose: the full name is too long for a legend row and a
Viewer pill.

The mapping lives in exactly one place — `PLATFORM_LABELS` in
`app/ui/src/config/nodeTypes.js`. Never hardcode either spelling elsewhere. The four email
keys (`email`, `gmail`, `imap`, `outlook`) collapse to one label, `Email`.

---

## 1. Shape of the app

```
Browser  --HTTP-->  app/ (FastAPI, 127.0.0.1:8100)  --HTTP-->  Ollama (127.0.0.1:11434)
                          |
                          +--> relate_comms/tools.py  -->  store/graph.rl
```

**One rule that explains the architecture:** every capability is a plain function in
`relate_comms/tools.py`. Three surfaces bind the same functions — the UI's HTTP routes, the
local chat's tool calls, and MCP. If a tool works in the chat box it works everywhere,
because it is the same function.

**Dependency direction:** `app -> relate_comms`, never back. Importing the library must not
pull in FastAPI or a web server.

## 2. Modules

### Library — `relate_comms/`

| File | Role |
|---|---|
| `schema.py` | Frozen dataclasses: `Message`, `Chat`, `AttachmentRef`, `IngestResult`. `make_key()` builds `platform:chat_id:message_id`. (`Person` / `Identity` exist here but are unused — see §0.) |
| `paths.py` | `data_root()`, `spool_dir()`, `real_dir()`, `sample_dir()`, `store_path()`, `profile_dir()`, `ensure_layout()`. No env override by design. |
| `ingest.py` | The pipeline. `_PARSERS` registry, `detect_platform()` (by content, never filename), `discover()`, `parse_batches()` (process pool), `ingest()`, `stage()`, `format_report()`. |
| `writer.py` | Cypher writer. `write()` (UNWIND batches of 500), `write_correspondents()`, `thread_display_title()`, `verify_present()`, `stored_keys()`. `write_people()` exists but is never called. |
| `resolution.py` | Phones → last 10 digits, emails → lowercase, names → rapidfuzz. `Resolver`, `Candidate`, `NAME_MAX = 0.80`. **Unwired** — no caller in `ingest()`. |
| `scrub.py` | `Verdict` (keep/hide/block), `AliasMap` (memory-only), `scrub_result()`, Luhn check for cards. |
| `identity.py` | Who the **Owner** is. Per-platform, persisted to `store/profile/identity.json`, with `tz_offsets`. |
| `tools.py` | **The tool layer.** 10 registered tools, schema derived from each signature. |
| `models.py` | Ollama model choice. `pick(task)`, `THINK = False`, `OPTIONS`. |
| `cli.py` | `python -m relate_comms` — `ingest`, `sample build`. |
| `adapters/` | One module per platform; each exposes `parse(export_path, **kw) -> IngestResult` and `detect(path)`. |

### App — `app/`

| File | Role |
|---|---|
| `main.py` | FastAPI app, `ToolError` → 400, static mount, `/` serves `index.html`. |
| `routers/system.py` | `/api/health`, `/stats`, `/types`, `GET|POST /platforms`. |
| `routers/graph.py` | `/api/graph`, `/api/thread/{key}`, `/api/message/{key}`. |
| `routers/search.py` | `POST /api/search` — `mode: substring|cypher`. |
| `routers/chat.py` | `/api/chat/health`, `POST /api/chat`. Ollama loopback, one tool round. |
| `routers/ingest.py` | `POST /api/ingest`, `GET /api/ingest/verify`, `POST /api/ingest/prune`. |
| `__main__.py` | `python -m app`, default port **8100**. |

### UI — `app/ui/src/`

React 19 + esbuild. `dist/app.js` is **committed** so a clone runs without npm.

| File | Role |
|---|---|
| `App.jsx` | Shell. Owns theme, viewer stack, chat toggle, modal, platform filter. Enforces the halo/fly-to rule. |
| `components/GraphCanvas.jsx` | Cytoscape + fcose. Tiers, shades, icons, labels, reveal, `halo()`/`focus()`. |
| `components/Viewer.jsx` | Two states, Back, character-budgeted message loads, per-thread search, paging. |
| `components/ChatPanel.jsx` | Ollama chat, `localStorage` transcript, tool trace. |
| `components/CommandBar.jsx` | Title bar. Every control is a button here. |
| `components/modals/` | `Modal.jsx` (shell + `Slider`/`Check`/`TextField`), Log, Ingest, Setup, GraphStyle, Utilities. |
| `config/theme.js` | **Every tunable.** The Graph Style modal writes here; persists to `localStorage`. |
| `config/nodeTypes.js` | Platform colours, icons, placeholder names, label truncation. |
| `lib/api.js` | The only place the UI talks to the server. |
| `lib/useViewerStack.js` | The state timeline, persisted to `localStorage`. |

## 3. Key functions

```python
# relate_comms/tools.py — the whole surface
graph_slice(node_types=None, edge_types=None, limit=2000)   # canvas payload
configure_platforms(platforms)   active_platforms()        # the surface filter
thread_arc(thread_key, *, skip=0, limit=50, query=None)     # Viewer messages
search_messages(query, *, limit=20, platform=None, thread_key=None)
message_view(message_key)
types_present()          evidence_counts()      run_cypher(query, params, *, limit=500)
ingest(...)              verify_ingest(which)   prune_spool(older_than_days, ...)
```

```python
# relate_comms/ingest.py
ingest(*, root=None, which="real", store=None, since=None, until=None,
       include_service=True, prune=False, workers=None, tz_offset_hours=None,
       self_id=None, email=None, extra_results=None) -> Report
stage(paths_in, *, root=None) -> list[Path]      # copies, never moves
detect_platform(path) -> str | None              # by content shape
```

```python
# relate_comms/writer.py
write(conn, result, *, owner=None) -> dict[str, int]   # UNWIND, BATCH_SIZE = 500
thread_display_title(chat, owner=None) -> str          # never empty
verify_present(conn, result) -> tuple[bool, dict]
```

## 4. Schema (what exists today)

```cypher
(:Thread        {key, platform, title, is_group})
(:Message       {key, platform, chat_id, message_id, ts_utc, body,
                 has_attachments, is_self, sender_name, sender_id, raw_kind})
(:Attachment    {key, filename_scrubbed, mime, sha256, size})
(:Correspondent {key, display_name, platform, handle, email, phone_e164})

(:Message)-[:IN]->(:Thread)
(:Message)-[:REPLY_TO]->(:Message)
(:Message)-[:HAS_ATTACHMENT]->(:Attachment)
(:Thread)-[:WITH]->(:Correspondent)
```

**Written today:** the four node types and four edges above.

**Designed but unwritten — do not query against these:** `Identity`, `MATCHED_BY`,
`POSSIBLY`, `SENT`, `Place`, `Company`, `Product`, `MENTIONS`, `Draft`. A query against
them returns zero rows.

**`Correspondent` is the only identity term.** It is one platform, a fact from the export,
keyed `<platform>:<name>`. `David Sartori` is currently three Correspondent nodes, and that
is correct — merging one human across platforms is unsolved, and `Person` is not the name
for it (see §0).

## 5. Invariants — break these and things fail silently

| Invariant | Why |
|---|---|
| `Message.key = platform:chat_id:message_id` | Makes re-ingest idempotent. Never an array index or timestamp. |
| `ts_utc` everywhere | Telegram/WhatsApp/Facebook Messenger export wall-clock with no offset. Convert at parse or the timeline lies. |
| **The tz offset is part of the key** | `ts_utc` hashes into the key, so a different `--tz-offset` produces different keys. Stored per platform in `identity.json` (`tz_offsets`) and reused when omitted. Changing it on a populated store is refused. |
| `MERGE` on `key`, never `CREATE` | Re-ingest must not duplicate. |
| Every title has a fallback, never empty | `writer.thread_display_title()`. 291 of 955 threads rendered `""` before this existed. |
| One writer per `.rl` file | Concurrent writers are corruption, not speed-up. Hence parallel parse → serialised write. |
| Messages are atomic — never chunk | One message is already one node, under 500 chars. |
| Truncation is never silent | Any tool that hits `limit` returns `truncated: true`. |
| `write_enabled` and `platforms` are excluded from tool schemas | They are the surface's toggles, not something a model may set. |

## 6. Commands

```bash
# run
python -m app                                   # http://127.0.0.1:8100
start.bat                                       # Windows: opens browser + server
python -m app --port 8110

# ingest
python -m relate_comms ingest --which real --email hostinger --tz-offset -5
python -m relate_comms ingest "C:/Users/me/Downloads/chat.zip" --tz-offset -5
python -m relate_comms ingest --which sample
python -m relate_comms sample build --check

# test
python -m pytest tests -q                       # 137 passed, 2 skipped
python -m pytest tests -q -k telegram

# UI
npm install
npm run build                                   # -> app/static/dist/app.js
npm run watch                                   # rebuild on save, no server
node scripts/vendor.mjs                         # re-copy cytoscape + fcose

# bench
python tools/bench_scale.py --n 20000
```

## 7. Debugging

| Symptom | Check |
|---|---|
| Canvas empty, API fine | `curl /api/graph?limit=5` — if it returns nodes, the failure is in the UI. Check the browser console. |
| Everything renders as squares | A Cytoscape style selector matched too broadly. `[key]` tests field **existence**, not truthiness. |
| Render dies after first paint | A style value parsed to `null`. `background-image: data(x)` with an empty string does exactly this. |
| Thread shows 0 messages | The tz offset differs from the one the store was written with. Check `store/profile/identity.json` → `tz_offsets`. |
| A route 404s after a rename | The Python server is stale. It loads routes once at startup — restart it. `--reload` avoids this. |
| esbuild "Unexpected ," | A mid-keystroke save. The file is fine; watch recovers on the next save. |
| Chat answers a different question | Tool result exceeded `MAX_TOOL_CHARS` (4,000). It is summarised, not silently cut. |
| Chat is very slow | `think: false` not applied. Thinking is ~28× slower on this box. |
| Port 8100 "already in use" | A stale server. `netstat -ano \| findstr :8100`, then `taskkill /PID <pid> /F`. |
| Ingest reports 0 messages but exits 0 | `verify_ingest` is the check that matters; a batch can parse and write nothing. |

## 8. Relate / Neo4j

- **Relate is embedded.** `relate.connect(path)` takes a **filesystem path**, not a
  `file:` URI. There is no Bolt, no port, no server, no subprocess.
- Consequence: every library that writes via `neo4j.GraphDatabase.driver(uri)` —
  `neo4j-graphrag`, LangChain's `LLMGraphTransformer`, Neo4j KG Builder, MS GraphRAG,
  LightRAG, LlamaIndex `PropertyGraphIndex` — **cannot talk to Relate at all.** Not
  "needs an adapter": there is no socket. They could at most emit JSON for `writer.py`.
- `relate.Connection` exposes `execute, executemany, cursor, commit, rollback, close,
  flush, autocommit, namespace` and nothing else.
- Vector indexes are native:
  ```cypher
  CREATE VECTOR INDEX vidx FOR (n:Msg) ON n.emb
    OPTIONS {indexConfig: {`vector.dimensions`: 384,
                           `vector.similarity_function`: 'cosine'}}
  CALL db.index.vector.queryNodes('vidx', 10, $embedding) YIELD node, score
  ```
  There is **no inline `cosine_similarity()`** scalar, so hybrid search is "vector query,
  then traverse", not "compute similarity".
- Measured: ~1,460–1,500 bytes per message in the store. Batched `UNWIND` writes run at
  **~7,000 msg/s** and are linear (per-row `MERGE` was 133 msg/s degrading to 64).

Links: [Relate](https://relate.neo4j.com/) ·
[openCypher](https://opencypher.org/) ·
[Neo4j Cypher manual](https://neo4j.com/docs/cypher-manual/current/) ·
[fcose layout](https://github.com/iVis-at-Bilkent/cytoscape.js-fcose) ·
[Cytoscape.js style docs](https://js.cytoscape.org/#style)

## 9. Local tools on this machine

| Tool | Where | Note |
|---|---|---|
| Ollama | `127.0.0.1:11434` | `lfm2.5:8b` default (MoE, ~21 tok/s CPU), `qwen3.5:4b` fallback, `embeddinggemma` for vectors. **`think: false` is a 28× speedup.** |
| Python | 3.11+ | `pip install -e ".[resolve,app]"` |
| Node | 22+ | Only for UI builds. `dist/app.js` is committed. |
| Relate | pip | Embedded; one `.rl` file. |

Ports in use on this box: **8000 is taken** by another app — this project uses **8100**.

## 10. Where the rest of the detail lives

| Topic | File |
|---|---|
| UI as built, every Cytoscape decision | [`archive_docs/UI-Cytoscape.md`](archive_docs/UI-Cytoscape.md) |
| Per-platform export shapes and traps | [`archive_docs/MssgDownloadInstructs.md`](archive_docs/MssgDownloadInstructs.md) |
| Ollama on this machine | [`archive_docs/HowToRunOllama.md`](archive_docs/HowToRunOllama.md) |
| Earlier direction research | [`archive_docs/`](archive_docs/) |
