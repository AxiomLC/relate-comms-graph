# TECHREADME.md

Condensed technical reference. Written for an AI picking this up cold: module map, key
functions, commands, and the constraints that are not obvious from the code.

Human-facing overview: [`README.md`](README.md). What is next: [`HANDOVER.md`](HANDOVER.md).

---

## 0. Terms — the canonical key

Five terms carry the whole model. If a word is not in this table it is prose, not a concept.
Use these spellings in code, in Cypher, in the UI and in docs.

| Term | Code / store | Definition | Deliberately NOT |
|---|---|---|---|
| **Owner** | `identity.py`, `store/profile/identity.json` | The account owner. Per platform, persisted, with `tz_offsets`. | Not a node. Not a `Correspondent`. |
| **Correspondent** | `(:Correspondent {key, …})`, key `<platform>:<name>` | The other party, **on one platform**. A fact from the export. | Not one human across platforms. Not an extracted entity. |
| **Platform** | `platform` property on every node; `_PLATFORMS` in `tools.py` | The source: `telegram`, `messenger`, `email`, `linkedin`, `whatsapp`, `outlook`, `sms`. | Not the export file. Not the provider — Outlook-over-IMAP is `email`. |
| **Thread** | `(:Thread {key, platform, title, is_group})` | One conversation. | Not a message. |
| **Message** | `(:Message {key, platform, chat_id, message_id, …})` | One message. | Not a thread. |

Ingest path — three more, not interchangeable: **Download** (the user's file, never moved),
**Export** (`IngestResult.export_path`, the copy in `spool/` that gets parsed), **Spool**
(`paths.real_dir()`, **one queue** — a sample is just a file dropped in it).

**Not terms yet:** `Person`, `Place`, `Organization`, `Product` name a future extraction
step — no node type, no writer, no query. `resolution.collect/merge` **are** called and
their counts land in the report, then the result is discarded.

### Platform identity table

`PLATFORM_LABELS`, `PLATFORM_COLORS`, `PLATFORM_ICONS`, `PERSON_ICONS` in
`app/ui/src/config/nodeTypes.js` are the implementation; this is the contract. All seven
are built.

| key | label | colour |
|---|---|---|
| `messenger` | Fcbk Mssgr | `#3b6fd4` blue |
| `telegram` | Telegram | `#3fb6b0` aqua |
| `whatsapp` | WhatsApp | `#4caf50` green |
| `linkedin` | LinkedIn | `#5cc8f0` light blue |
| `email` | Email | `#d9534f` red |
| `outlook` | Outlook | `#8b5cf6` purple |
| `sms` | SMS | `#b8912a` dark gold |

`gmail` and `imap` are aliases resolving to `email`. The store key is `messenger` and must
stay that way — it is part of every `Message.key`. The UI shows **Fcbk Mssgr**, never bare
"Messenger", which reads as "a message" beside a `Message` node. `outlook` is its own
platform, not a variant of `email`: a `.pst` and a live mailbox have different provenance.

---

## 1. Shape of the app

```
Browser  --HTTP-->  app/ (FastAPI, 127.0.0.1:8100)  --HTTP-->  Ollama (127.0.0.1:11434)
                          |
                          +--> relate_comms/tools.py  -->  store/graph.rl
```

**One rule explains the architecture:** every capability is a plain function in
`relate_comms/tools.py`. Three surfaces bind the same functions — the UI's HTTP routes, the
local chat's tool calls, and MCP. **Dependency direction:** `app -> relate_comms`, never
back; importing the library must not pull in FastAPI.

## 2. Modules

### Library — `relate_comms/`

| File | Role |
|---|---|
| `schema.py` | Frozen dataclasses: `Message`, `Chat`, `AttachmentRef`, `IngestResult`. |
| `paths.py` | `spool_dir()`, `real_dir()`, `store_path()`, `profile_dir()`, `ensure_layout()`. |
| `ingest.py` | The pipeline: `_parser_for()`, `detect_platform()`, `discover()`, `parse_batches()`, `ingest()`, `preview()`, `stage()`, `_drop_spam_threads()`. |
| `writer.py` | Cypher writer. `write()` (UNWIND 500), `write_correspondents()`, `thread_display_title()`, `verify_present()`. |
| `resolution.py` | Phones/emails/names matching. **Unwired** — counts reported, result discarded. |
| `scrub.py` | `Verdict` (keep/hide/block), `AliasMap` (memory-only), Luhn check. |
| `identity.py` · `manifest.py` | Who the **Owner** is (with `tz_offsets`) · what has been ingested (sampled fingerprint, a shortcut never the authority). |
| `tools.py` | **The tool layer.** 11 tools, schema from each signature. |
| `models.py` · `cli.py` | Ollama model choice (`THINK = False`) · `python -m relate_comms`. |
| `adapters/` | `parse(export_path, **kw)` + `detect(path)`. Built: `telegram`, `whatsapp`, `whatsapp_html`, `messenger`, `linkedin`, `email_imap`, `outlook_pst`, `sms`. **WhatsApp has two dialects** — native `chat.txt` and the extension's HTML — both reporting `whatsapp`; `_parser_for()` picks per file. |

### App — `app/`

| File | Role |
|---|---|
| `main.py` | FastAPI app, `ToolError` → 400, static mount, `/` serves `index.html`. |
| `routers/system.py` | `/api/health`, `/stats`, `/types`, `GET|POST /platforms`. |
| `routers/graph.py` · `search.py` · `chat.py` | `/api/graph`, `/api/thread/{key}`, `/api/message/{key}` · `POST /api/search` · Ollama loopback, one tool round. |
| `routers/ingest.py` | `/api/ingest`, `/upload` (file or folder picker → spool), `/preview` (read-only: size + duplicate), `/env` (credentials → `./.env`, never echoed), `/truncate` (destructive), `/verify`, `/prune`. |
| `__main__.py` | `python -m app`, default port **8100**. |

### UI — `app/ui/src/`

React 19 + esbuild. `dist/app.js` is **committed** so a clone runs without npm.

| File | Role |
|---|---|
| `App.jsx` | Shell. Theme, viewer stack, chat toggle, modal, platform filter. Enforces halo/fly-to. |
| `components/GraphCanvas.jsx` | Cytoscape + fcose. **Icons are the only node look.** |
| `components/Viewer.jsx` | Two states, Back, budgeted loads, per-thread search, paging. |
| `components/ChatPanel.jsx` · `CommandBar.jsx` | Ollama chat with tool trace · the title bar. |
| `components/modals/` | `Modal.jsx` (+ `Slider`/`Check`/`TextField`), Log, Ingest, **Canvas** (+ Styling), Utilities. |
| `config/theme.js` · `nodeTypes.js` | **Every tunable**, persisted · platform colours, icons, placeholders. |
| `lib/api.js` · `useViewerStack.js` | The only server call site · the persisted state timeline. |

## 3. Key functions

```python
# relate_comms/tools.py — the whole surface
graph_slice(node_types=None, edge_types=None, limit=2000, sort="messages")
configure_platforms(platforms)   active_platforms()
thread_arc(thread_key, *, skip=0, limit=50, query=None)
search_messages(query, *, limit=20, platform=None, thread_key=None)
message_view(message_key)
types_present()   evidence_counts()   run_cypher(query, params, *, limit=500)
ingest(...)   preview_ingest(which)   verify_ingest(which)
truncate_store(...)   prune_spool(older_than_days, ...)

# relate_comms/ingest.py
ingest(*, root=None, which="real", store=None, since=None, until=None,
       include_service=True, exclude_spam_groups=False,
       exclude_silent_groups=False, silent_group_platforms=None,
       exclude_spam_threads=False, spam_thread_platforms=None,
       prune=False, prune_keep=None, workers=None, tz_offset_hours=None,
       self_id=None, extra_results=None) -> Report
preview(*, root=None, which="real", profile_dir=None) -> dict   # read-only
stage(paths_in, *, root=None) -> list[Path]      # copies, never moves
detect_platform(path) -> str | None              # by content shape
_parser_for(path, platform)                      # WhatsApp's two dialects

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

(:Message)-[:IN]->(:Thread)        (:Message)-[:REPLY_TO]->(:Message)
(:Message)-[:HAS_ATTACHMENT]->(:Attachment)
(:Thread)-[:WITH]->(:Correspondent)
```

**Designed but unwritten — do not query against these:** `Identity`, `MATCHED_BY`,
`POSSIBLY`, `SENT`, `Place`, `Company`, `Product`, `MENTIONS`, `Draft`.

`Correspondent` is the only identity term. `David Sartori` is currently three
Correspondent nodes, and that is correct — merging one human across platforms is unsolved.

## 5. Invariants — break these and things fail silently

| Invariant | Why |
|---|---|
| `Message.key = platform:chat_id:message_id` | Makes re-ingest idempotent. Never an array index or timestamp. |
| `ts_utc` everywhere | Telegram/WhatsApp/Messenger export wall-clock with no offset. |
| **A platform is a source, not a provider** | `outlook` is a `.pst`; Outlook-over-IMAP is `email`. Different provenance, different keys. |
| **The owner is never a Correspondent** | An adapter that knows the owner must prune them from `participant_names` under both forms. |
| **The tz offset is part of the key** | `ts_utc` hashes into the key. Stored per platform; changing it on a populated store is refused. |
| `MERGE` on `key`, never `CREATE` | Re-ingest must not duplicate. |
| Every title has a fallback, never empty | `writer.thread_display_title()`. |
| One writer per `.rl` file | Concurrent writers are corruption. Hence parallel parse → serialised write. |
| Truncation is never silent | Any tool hitting `limit` returns `truncated: true`; `graph_slice` also returns `total`. |
| **A view toggle never narrows a query** | Canvas hides clusters and silent threads; that is drawing only. `Utilities` narrows what tools return. |
| **Icons are an override layer, never the base** | A platform with no icon file keeps the base fill and stays visible. |
| `write_enabled` and `platforms` are excluded from tool schemas | They are the surface's toggles, not something a model may set. |
| **A dropped thread leaves no orphan messages** | Any parse-time gate runs before the rows are committed and before the `Chat` is appended. |
| **Legs are independent — any subset, any order, any number of runs** | Every write is a `MERGE`, so ingesting SMS into a five-platform store adds rows and touches nothing else. |
| **A parse-time gate is per platform, never global** | `_kwargs_for()` pops a keyword an adapter does not accept, so adding a platform never means adding a no-op argument. |
| **Credentials are never readable by a tool** | `.env` is read only by `email_imap._dotenv()`. `tools.py` has no environment access. |
| **The duplicate stamp is a shortcut, not the authority** | `ingested.json` lets the UI say "already ingested". `verify_present()` still decides pruning. |
| **No adapter reads media** | A huge download costs the copy, not the parse — which is why size is a warning, not a refusal. |
| **A WhatsApp chat downloaded both ways is one thread, not two** | `_chat_id()` hashes the chat *title*; `message_key()` truncates to the **minute**. Measured: 46 of 47 keys identical. |
| **A failed leg restarts, it does not resume** | Continue re-runs the whole ingest without the failed leg. |
| **Truncating the graph always truncates the manifest** | Left behind, the next ingest skips every file it has seen and produces an empty graph that looks successful. |
| **A redirected store redirects the profile** | `ingest(store=…)` puts the manifest and tz offsets beside that store unless `profile_dir` is given. |
| **Detection must see inside a container it can parse** | `sms.detect()` reads the decompressed `.xml` member of a `.xml.zip`, not the zip's raw bytes. |
| **A platform with two dialects is routed per file, not per platform** | Both WhatsApp dialects report `whatsapp`, so `_parser_for()` decides. Asserting on `detect_platform()` alone passes while the file goes to the wrong adapter. |
| **A recognised directory is one batch, not one per file** | `discover()` offers a folder to `detect_platform()` first and emits it whole if claimed. Messenger and Telegram resolve thread ids from the archive-relative path, so handing them a single `message_1.html` makes each batch parse the *whole* export — measured at 29 batches and 18,330 messages to write 611. |
| **`detect_platform()` answers for a directory too** | `discover()` needs to know whether to emit a folder or walk into it. Only the adapters that can read a folder are consulted (messenger, linkedin, whatsapp_html, `_detect_whatsapp`). |

## 6. Ingest — the modal and its gates

**Flow:** preview (read-only: size + duplicate per spool file) → decide → ingest. The
preview deliberately does **not** count messages; that needs the full parse it exists to
avoid.

**Modal, top to bottom:** Truncate (double confirm) → drop box (file or folder, one or
many) → IMAP fields → separator → window / tz / groups / email spam / prune → Ingest → log
(newest first).

| Gate | Scope | Default | Threshold |
|---|---|---|---|
| `exclude_silent_groups` | Telegram / WhatsApp / Messenger | **on** | group with zero `is_self` rows |
| `exclude_spam_groups` | Messenger | off | ≥50% housekeeping rows (`SPAM_NOISE_RATIO`) |
| `exclude_spam_threads` | Email / Outlook | **on** | **more than** 10 messages, zero `is_self` |
| `prune_keep` | all | off | `None` = age rule (3 days), `0` = all, `1`/`2` = keep last N runs |

**Group-ness per platform.** Telegram: `type` not in `{personal_chat, bot_chat,
saved_messages}`. Messenger: more than one non-owner sender. WhatsApp: **a membership
system row** (`added`, `removed`, `changed the group name`) — `You` alone is not enough,
because a group the Owner never spoke in has no `You:` line. `_kwargs_for()` pops the
keyword for any platform outside `silent_group_platforms`.

**Two controls that must never be confused:** Canvas *"Hide threads where the owner never
sent a message"* is **view only**, reversible, still searchable. Ingest *"Exclude groups
where the Owner never spoke"* is **parse time**, permanent, never stored.

**IMAP credentials** go to `./.env` behind an explicit Save button and the write toggle. No
provider selector: the host autofills from the domain and `account_from_parts()` covers
anything unknown. Outlook/O365 killed basic auth — the modal points at the `.pst` route.

**A failed leg** halts with the error named and offers *Exclude and continue* or *Cancel*.
Cancel does not roll back and does not need to — `MERGE` makes a re-run idempotent.

**No hard cap, and size is a warning.** A cap fires after the work is done, and thread count
does not track cost. Measured: 200,000 messages writes in 42 s; point lookups stay at 2 ms,
thread traversal at 15 ms. Only full scans grow (a window query went 27 ms at 50k to 153 ms
at 200k) — **the store scales fine, search latency is the only thing that degrades.** And
since no adapter reads media, a 4 GB zip with videos parses as fast as a 40 MB one: the
advice for a monster download is "re-export without media", which loses no messages.

## 7. Commands

```bash
python -m app                    # http://127.0.0.1:8100
start.bat                        # Windows: opens browser + server

python -m relate_comms ingest --email hostinger --tz-offset -5
python -m relate_comms ingest "C:/Users/me/Downloads/chat.zip" --tz-offset -5
python -m relate_comms sample build --check

python -m pytest tests -q        # 248 passed, 2 skipped

npm install && npm run build     # -> app/static/dist/app.js
npm run watch                    # rebuild on save, no server
node scripts/vendor.mjs          # re-copy cytoscape + fcose
python tools/bench_scale.py --n 20000
```

**No `--reload`.** The editor auto-saves every few seconds, so a watcher restarts the
server mid-request; it also watches the whole repo, so `pytest` makes it thrash.

## 8. Debugging

| Symptom | Check |
|---|---|
| Canvas empty, API fine | `curl /api/graph?limit=5` — if it returns nodes, the failure is in the UI. |
| Everything renders as squares | A Cytoscape selector matched too broadly. `[key]` tests field **existence**. |
| Render dies after first paint | A style value parsed to `null`. `background-image: data(x)` with an empty string does this. |
| Thread shows 0 messages | The tz offset differs from the one the store was written with. |
| A route 404s after a rename | The Python server is stale — it loads routes once at startup. Restart it. |
| Blank page, no console clue | A `const` inside a `useMemo` referenced in its dependency array throws `ReferenceError` every render. |
| Chat answers a different question | Tool result exceeded `MAX_TOOL_CHARS` (4,000). Summarised, not silently cut. |
| Chat is very slow | `think: false` not applied. Thinking is ~28× slower on this box. |
| Port 8100 "already in use" | `netstat -ano \| findstr :8100`, then `taskkill /PID <pid> /F`. |
| Ingest reports 0 messages but exits 0 | `verify_ingest` is the check that matters. |

## 9. Relate / Neo4j

- **Relate is embedded.** `relate.connect(path)` takes a **filesystem path**, not a
  `file:` URI. No Bolt, no port, no server.
- Consequence: every library writing via `neo4j.GraphDatabase.driver(uri)` —
  `neo4j-graphrag`, LangChain's `LLMGraphTransformer`, MS GraphRAG, LightRAG, LlamaIndex —
  **cannot talk to Relate at all.** Not "needs an adapter": there is no socket.
- `relate.Connection` exposes `execute, executemany, cursor, commit, rollback, close,
  flush, autocommit, namespace` and nothing else.
- Vector indexes are native (`CREATE VECTOR INDEX … OPTIONS {indexConfig: …}`,
  `db.index.vector.queryNodes`). There is **no inline `cosine_similarity()`**, so hybrid
  search is "vector query, then traverse".
- Measured: ~1,460–1,500 bytes per message; batched `UNWIND` writes run at **~7,000 msg/s**.

Links: [Relate](https://relate.neo4j.com/) · [openCypher](https://opencypher.org/) ·
[Neo4j Cypher](https://neo4j.com/docs/cypher-manual/current/) ·
[fcose](https://github.com/iVis-at-Bilkent/cytoscape.js-fcose) ·
[Cytoscape.js style](https://js.cytoscape.org/#style)

## 10. Local tools on this machine

| Tool | Where | Note |
|---|---|---|
| Ollama | `127.0.0.1:11434` | `lfm2.5:8b` default (MoE, ~21 tok/s CPU), `qwen3.5:4b` fallback, `embeddinggemma` for vectors. **`think: false` is a 28× speedup.** |
| Python | 3.11+ | `pip install -e ".[resolve,app]"` |
| Node | 22+ | Only for UI builds. `dist/app.js` is committed. |
| Relate | pip | Embedded; one `.rl` file. |

Ports in use: **8000 is taken** by another app — this project uses **8100**.

## 11. Where the rest of the detail lives

| Topic | File |
|---|---|
| The generator spec — every shape the app has a switch for | [`archive_docs/UNDESIRABLES.md`](archive_docs/UNDESIRABLES.md) |
| UI as built, every Cytoscape decision | [`archive_docs/UI-Cytoscape.md`](archive_docs/UI-Cytoscape.md) |
| Per-platform export shapes and traps | [`archive_docs/MssgDownloadInstructs.md`](archive_docs/MssgDownloadInstructs.md) |
| Ollama on this machine | [`archive_docs/HowToRunOllama.md`](archive_docs/HowToRunOllama.md) |
