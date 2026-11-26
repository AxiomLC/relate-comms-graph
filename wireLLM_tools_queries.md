# wireLLM_tools_queries.md

Working notes. Two subjects, kept separate on purpose:

- **A. The LLM chat** — what is wired, why it is slow, where the prompt lives.
- **B. Queries** — how the search bar and the chat's tools actually reach Relate.

Status: chat is **wired and answering** (verified live 2026-11-25). It is slow and it
has three defects, listed in §A4. Nothing here is a plan yet; this is the eval.

---

## A. The LLM chat - lfm2.5:8b

### A1. Where the prompt lives

| Piece | File | Symbol |
|---|---|---|
| **System prompt** (the real one) | `app/routers/chat.py` | `SYSTEM_PROMPT` — module-level string |
| Per-turn context hint | `app/ui/src/components/ChatPanel.jsx` | `send()` — appends `[The user is currently looking at …]` |
| Tool allowlist | `app/routers/chat.py` | `_CHAT_TOOLS` |
| Tool descriptions | `relate_comms/tools.py` | each tool's **docstring** — `_register_all()` reads `fn.__doc__` |
| Model + options | `relate_comms/models.py` | `DEFAULT_MODEL`, `THINK`, `OPTIONS` |

**The tool descriptions are docstrings.** Editing a tool's docstring changes what the
model sees. That is the cheapest lever on tool selection and it is easy to forget.

### A2. The call path

```
ChatPanel.jsx  --POST /api/chat-->  app/routers/chat.py::chat
                                        |
                                        +--> _run_turn()  --POST /api/chat--> Ollama
                                        |        |
                                        |        +--> _call_tool() --> tools.REGISTRY[name].fn
                                        |
                                        +--> returns {reply, tool_calls[], model}
```

History is **in the browser** (`localStorage` key `relate.chat.transcript`). Ollama is
stateless; the whole transcript is re-sent every turn. The server keeps nothing.

### A3. Why it is slow, lfm2.5:8b

Measured on this box (i5-12500H, **CPU only, no GPU**):

| Cause | Cost | Fixable? |
|---|---|---|
| No GPU | `lfm2.5:8b` Q4_K_M at ~21 tok/s decode | No. Model size is the only lever. |
| `think: false` | 28× — thinking is 368 tokens vs 10 for "hello" | **Already applied.** If it regresses, chat crawls. |
| Whole transcript re-sent | grows every turn; prompt processing is prefill, not decode | Partly — cap `theme.chat.maxTranscript`. |
| `num_ctx: 8192` | larger context = slower prefill | Lower it if answers stay short. |
| Tool round trip | **two full model calls** per tool-using turn | Structural — see A4.3. |
| 8B model | `qwen3.5:4b` is ~2× faster, 8/8 JSON in the old bakeoff | Swap is one line in `models.py`. |

**"hello" should be ~1–2 s.** If it took much longer, the likely culprits are
`think` not being applied, or Ollama loading the model cold (first call after
`ollama serve` pays the load, ~5–10 s for 5 GB).

**The real cost is the second pass.** Any turn that calls a tool is *two* model calls:
one to decide the tool, one to write the answer. On CPU that is the difference between
2 s and 8 s. This is the single biggest UX lever and it is a design choice, not a bug.

### A4. Three defects found by exercising it — **all three now fixed, see §F**

> **Status 2026-11-25:** A4.1 fixed by `_name_matches()` (§F1). A4.2 fixed — the
> allowlist is now `evidence_counts, search_vector, search_fulltext, thread_arc,
> message_view, run_cypher` and the prompt no longer mentions `types_present`.
> A4.3 **still open**: one tool round only, and an empty reply is still silent.

**A4.1 — There is no name → thread tool. The prompt promises one that does not exist.**

`SYSTEM_PROMPT` says:

> "show me the conversation with X" -> search_messages first, then thread_arc

But `search_messages` scans **message bodies only**:

```cypher
MATCH (m:Message) WHERE toLower(m.body) CONTAINS toLower($q)
```

Nothing maps a person's name to their threads. `Correspondent.display_name` is never
searched. So the instruction is unachievable.

Live proof — asked for **Isaac Rubio**, who is a sender in the invoice hits:

```
{"reply":"No conversation containing “Isaac Rubio” was found in the system.",
 "tool_calls":[{"name":"search_messages","args":{"query":"Isaac Rubio"},
                "result":{"hits":[],"count":0}}]}
```

A **confident false negative**. Worse than an error: the user believes the data is
absent. Same for "Olivia McGee".

**A4.2 — `types_present` is in the prompt but not in the allowlist.** *(fixed)*

Prompt said: `"what types of data are there" -> types_present`
Allowlist was: `evidence_counts, search_messages, thread_arc, message_view, run_cypher`

Asking that question returned `tool 'types_present' is not available in this session`.
The prompt line was removed rather than the tool added — six tools is already at the
limit of what a local 8B model selects reliably.

**A4.3 — One tool round only, and an empty reply is silent.**

`_run_turn` pops `tools` before the second pass, so `search → thread_arc` can never
happen even if the model wanted it. And for "Olivia McGee" the reply came back as
`""` — an empty bubble, no error. `_strip_thinking` may be eating a think-only
response.

### A5. Candidate fixes — **1 and 2 done, 3 open**

1. ~~**`find_threads(person)`**~~ — **done differently.** Rather than a new tool, name
   matching went into `_name_matches()` and is called by both `search_fulltext` and
   `search_vector`. One fix, three surfaces (search bar, chat, and MCP when built).
2. ~~**Add `types_present` to `_CHAT_TOOLS`**~~ — the prompt line was deleted instead.
3. **Allow 2 tool rounds**, and **raise on an empty reply** instead of returning `""`.
   **Still open.** `_run_turn` pops `tools` before the second pass, so
   `search → thread_arc` cannot happen. This is the one remaining chat defect.

---

## B. Queries — how they really work

### B1. Two different things are called "search"

| Surface | Entry point | What it does |
|---|---|---|
| **Title-bar search** | `CommandBar` → `App.runSearch` → `POST /api/search` | `mode` is `substring` or `cypher` |
| **Chat tool** | `_call_tool` → `tools.REGISTRY[name].fn` | one of five READ tools |

Both land in `relate_comms/tools.py`. Neither knows about the other.

### B2. The search bar has two modes, and they are different promises

`app/routers/search.py`:

```python
if request.mode == "cypher":
    return tools.run_cypher(request.query, request.params, limit=request.limit)
return tools.search_messages(request.query, limit=..., platform=..., thread_key=...)
```

- **`substring`** — `toLower(m.body) CONTAINS toLower($q)`, ordered `ts_utc DESC`.
  A **scan, not a ranking**. A common word returns the *most recent* hits, not the
  best ones. `mode: "substring"` is returned so the UI can say so.
- **`cypher`** — whatever the user typed, refused if it would write.

The toggle is in `CommandBar`; `App.jsx` holds `searchMode` and sends
`limit: mode === "cypher" ? 200 : 40`.

### B3. What Relate actually is (this constrains everything)

- **Embedded, not a server.** `relate.connect(path)` takes a **filesystem path**.
  No Bolt, no port. One `.rl` file (`store/graph.rl`, ~3.5 MB here).
- `Connection` exposes `execute, executemany, cursor, commit, rollback, close, flush,
  autocommit, namespace` — **nothing else**.
- ~~**No `fulltext` index, no `cosine_similarity()` inline.**~~ **WRONG — corrected
  2026-11-25.** Relate **does** support `CREATE FULLTEXT INDEX` (BM25) and
  `db.index.fulltext.queryNodes`, verified working on the installed 1.0.1. It also has
  `vector.similarity.cosine(a, b)` inline (returns 0–1). Only the *name*
  `cosine_similarity()` is absent. See §C5.
- Consequence: **`CONTAINS` is a full scan** — and it is a full scan *by choice*, not by
  necessity. `EXPLAIN` on the real store confirms `NodeByLabelScan` for
  `search_messages`. Measured in `TECHREADME.md` §7: a window query went 27 ms at 50k
  messages to 153 ms at 200k. Fine now, linear forever, and fixable with an index that
  already exists in the engine.

### B4. The write guard on `run_cypher`

Before executing, string literals are stripped and the text is uppercased, then
matched against `_WRITE_PATTERN` word-bounded:

```python
scrubbed = _STRING_LITERAL.sub("''", text).upper()
found = _WRITE_PATTERN.search(scrubbed)
```

Word-bounded so `:Merged` is not read as `MERGE`; literals stripped so
`WHERE m.body CONTAINS 'create'` is not read as a write.

### B5. The schema a query can rely on

```cypher
(:Thread        {key, platform, title, is_group})
(:Message       {key, platform, chat_id, message_id, ts_utc, body, sender_name, is_self, …})
(:Correspondent {key, display_name, platform, platforms, handle_<p>, seen_<p>, …})
(:Place|:Organization|:Product {key, display_name, mention_count, …})

(:Message)-[:IN]->(:Thread)
(:Thread)-[:WITH]->(:Correspondent)
(:Message)-[:MENTIONS]->(:Place|:Organization|:Product)
(:Message)-[:REPLY_TO]->(:Message)          -- declared, written by nothing
(:Message)-[:HAS_ATTACHMENT]->(:Attachment)
```

**`Thread → Entity` is a projection, not an edge.** It is computed at read time in
`tools._EDGE_QUERIES` as a two-hop. Do not query it as if it were stored.

**The name → thread query that does not exist yet** would be:

```cypher
MATCH (t:Thread)-[:WITH]->(c:Correspondent)
WHERE toLower(c.display_name) CONTAINS toLower($name)
RETURN t.key, t.title, t.platform
```

That is the whole of A4.1. It is one `MATCH` away.

### B6. Open questions for the eval

1. Should the search bar search **names** as well as bodies? Today it cannot, and
   that is the same hole as A4.1 — one fix serves both surfaces.
2. Is `substring`-only acceptable, or does the search bar need a second mode
   (`names` / `threads`)? Adding a mode is a UI change; adding name matching to
   `search_messages` is a store change with a different result shape.
3. ~~is a `fulltext` index available in Relate at all?~~ **ANSWERED: yes.** See §C5.
4. Should the chat be allowed two tool rounds? It doubles latency on CPU (§A3).

---

## C. Research findings (2026-11-25)

Two subagents ran: one on `lfm2.5:8b`, one on Relate. Findings below are theirs,
verified against primary sources and the installed engine.

### C1. `lfm2.5:8b` — thinking CANNOT be turned off. This is by design.

**The model is reasoning-only.** Liquid AI's own support table says *"Can switch off:
No"* for LFM2.5-8B-A1B. There is no `enable_thinking` variable in its chat template.

| Attempt | Result |
|---|---|
| `think: false` in `/api/chat` | **Accepted, no-op.** The registry manifest uses the `lfm2` renderer with `IsThinking: false`, so it never emits think tags anyway. |
| `think: true` | **Rejected** — unsupported value. |
| `/no_think` in the prompt | **No.** Qwen3-only convention; LFM2 has no such token. |
| `PARAMETER think false` in Modelfile | **`unknown parameter`.** `think` is a request field, not a Modelfile param. |
| `OLLAMA_THINK` env var | **Does not exist.** Open feature request (ollama#10928). |

**So what is `THINK = False` in `models.py` doing?** Nothing harmful — it is the only
legal value — but it is **not** saving the 28× the docs claim. That measurement was
probably taken on a different model. **The 28× claim in `TECHREADME.md` §11 and
`chat.py`'s docstring should be re-verified or removed.**

**The `<think\u200b>` zero-width space is a symptom, not a bug.** It comes from an
Ollama streaming-parser workaround (ollama#19829): a close tag the model *spells out*
with ordinary tokens gets misread as a real tag, so the parser inserts U+200B to break
the match. Consequence for us: **`_strip_thinking` must strip `\u200b` too**, or a
regex on `<think\u200b>` silently misses.

**The only reliable hack is client-side stripping** — which `_strip_thinking` already
does. Budget for it: reasoning tokens count against `num_predict`, so a low limit
produces an empty `content` (this is likely the empty-reply bug in A4.3).

**The real fix is a different model.** Qwen3.5-4B beats LFM2.5-8B on 3 of 4 tool
benchmarks (BFCLv3 71.06 vs 64.79; Tau² Retail 71.93 vs 39.82) at **half the size**,
and its `think: false` genuinely works. `qwen3.5:4b` is **already pulled on this box.**

### C2. Fastest settings on CPU-only

| Lever | Recommendation | Why |
|---|---|---|
| `num_ctx` | **8192** (current) — do not raise | prefill is the CPU bottleneck; unused context still costs |
| `num_predict` | **set explicitly, 1024–2048** | default `-1` lets reasoning eat the whole budget → empty reply |
| `keep_alive` | **`-1`** | a 5 GB cold load is pure latency; pin the model in RAM |
| `num_thread` | **4** (P-cores only), test 6/8 | i5-12500H is 4P+8E; oversubscribing onto E-cores often *loses* tok/s |
| `OLLAMA_KV_CACHE_TYPE=q8_0` | try it | halves KV memory; needs flash attention |
| Quant | **stay Q4_K_M** | MoE with ~1.5B active — file size helps less than for a dense model |

**No public i5-12500H tok/s figure exists** — UNVERIFIED. Closest proxy is Liquid AI's
phone figure (~30 tok/s). Benchmark locally with `eval_count / eval_duration`.

### C3. Tool-calling caveat specific to LFM2

LFM2 writes tool calls as **Python**, not JSON: `[get_weather(city="Paris")]`. Ollama's
`lfm2` parser converts it — but anything bypassing that parser gets Python syntax.
Also: bracket-heavy text can crash the parser on `hf.co/` pulls (llama.cpp#23838).
The official `lfm2.5:8b` library build is not affected.

### C4. Relate is **Cypher 25**, not openCypher

The dialect is Neo4j's Cypher 25, embedded, minus server/cluster/APOC/GDS surface.
`CYPHER 25` is accepted; any other version is refused.

**Supported** (verified on 1.0.1): `MATCH`, `OPTIONAL MATCH`, `WITH`, `UNWIND`,
`MERGE` + `ON CREATE`/`ON MATCH`, `FOREACH`, `CALL { }` subqueries, `EXISTS { }`,
`COUNT { }`, `UNION`, `CREATE INDEX`, `CREATE VECTOR INDEX`, **`CREATE FULLTEXT INDEX`**.

**Absent:** APOC, GDS, `CREATE DATABASE`, users/roles, nested transactions.

**Relate-specific extensions:** the `SEARCH` clause, `COMBINE … USING WRRF` (hybrid,
preview), `CREATE GRAPH TYPE`, `LET`/`FILTER`/`NEXT`, `s'{…}'` interpolation.

### C5. Three repo notes are WRONG on the engine we actually run

| Repo claim | Reality on 1.0.1 |
|---|---|
| "No fulltext index" (`wireLLM_tools_queries.md` B3) | **FALSE.** `CREATE FULLTEXT INDEX msg_body FOR (m:Message) ON EACH [m.body]` works; `SEARCH … IN (FULLTEXT INDEX …)` and `db.index.fulltext.queryNodes` both work. |
| "Relate cannot parameterise a property name in `SET`" (`link.py:456`) | **FALSE.** `SET n[$p] = "v"` works. The repo's own `_CORRESPONDENT_CYPHER` already uses `SET c[row.handle_prop]`. |
| "Relate cannot parameterise a label in `MATCH`" (`writer.py:354`) | **FALSE.** `MATCH (n:$($lbl))` works (Cypher 25 dynamic labels). |

**Also half-wrong:** "no inline `cosine_similarity()`" — the *name* is absent, but
`vector.similarity.cosine(a, b)` exists and returns 0–1.

**And one that is right but for the wrong reason:** `msg_ts` exists for the delta
watermark, but `EXPLAIN` shows the watermark query (`WHERE m.platform = $p`) does a
`NodeByLabelScan` — the index is **dead weight**. Only equality on `key` produces
`NodeIndexSeek`.

### C6. What this means for search

`search_messages` is a full scan **by choice**. The engine has had BM25 fulltext since
0.1.1. A `CREATE FULLTEXT INDEX` would replace the scan — **but** it is *word*
matching, not substring: `"graf"` would not match `"grafana"`. So a substring UI needs
the fulltext index **plus a post-filter**, or a `TEXT` index.

**This is the decision to make, not a bug to fix.** Substring semantics are what the
search bar promises today; BM25 would be faster but would change what a query means.

---

## D. Wiring a full toolset — chat vs MCP (my analysis)

### D1. The registry is already the single source

`Tool` carries `name`, `fn`, `access`, `description`, and its `.schema` is **derived
from the function signature** — and the docstring says so explicitly:

> "Derived from the signature, in the shape Ollama and MCP both accept."

So the answer to "same thing or separate?" is already encoded: **one registry, two
bindings.** The chat binds it in `app/routers/chat.py::_ollama_tool`; MCP would bind
the same `REGISTRY` in `app/mcp/server.py`.

### D2. But they must NOT be identical surfaces

Same *definitions*, different *policy*. The differences are real:

| Dimension | Chat (in-app) | MCP (IDE) |
|---|---|---|
| **Trust boundary** | the user, in the app, watching | an external agent, unattended |
| **Write default** | off, toggle in UI | **off, separate toggle** (`__init__.py` §2) |
| **Destructive** | `confirm=true` required | same, plus auth |
| **Tool subset** | **5 of 13** — an 8B model picks wrong from 13 | all 13, or by capability |
| **Platform filter** | inherits the UI's (`configure_platforms`) | **must not** — no UI state to inherit |
| **Credentials** | never (`.env` is IMAP-only) | **must never gain a `.env` read** (HANDOVER §4) |

**The tool *subset* is the important asymmetry.** `_CHAT_TOOLS` is 5 tools because a
local 8B model given 13 overlapping options picks the wrong one. MCP has no such
constraint — a frontier model in an IDE can handle 13. So: **same registry, different
allowlist, and the allowlist is a per-surface constant, not a registry property.**

### D3. What is missing from the registry (both surfaces need it)

1. **`find_threads(person)`** — the A4.1 hole. Neither surface can answer "show me the
   conversation with X". This is the highest-value addition and it is ~30 lines.
2. **`types_present`** — already registered, just missing from `_CHAT_TOOLS`.
3. **A name-aware search** — either a new tool or an extension of `search_messages`.

### D4. Recommended shape

```
relate_comms/tools.py          REGISTRY — 13 tools, one definition each
        |
        +-- app/routers/chat.py    _CHAT_TOOLS (5) + write toggle + platform filter
        +-- app/mcp/server.py      all tools + auth + separate write toggle
        +-- app/routers/search.py  search_messages / run_cypher only
```

**Do not build a second tool layer for MCP.** The registry exists precisely so this
does not happen, and `Tool.schema`'s docstring already promises MCP compatibility.

**Do add a `surfaces` field to `Tool`** if the allowlists start to diverge further —
e.g. `surfaces=("chat","mcp")`. Today a module constant is enough; a field is the
growth path when it stops being enough.

### D5. Open questions

1. Should MCP expose `run_cypher`? It is the most powerful tool and the hardest to
   guard. The write-guard is a regex, not a parser.
2. Should the chat get a second tool round (A4.3)? It doubles CPU latency. **Still open.**
3. ~~Does the search bar become name-aware?~~ **Decided: yes** — `_name_matches()`
   serves both modes and the chat (§F1).
4. Is `lfm2.5:8b` the right model at all, given C1? `qwen3.5:4b` is already pulled,
   faster, better at tools, and its thinking switch actually works.

### D7. The activity trace — one feed for all three surfaces (2026-11-25)

**Built.** `app/ui/src/components/ActivityLog.jsx` + `useActivity()`, rendered over the
canvas bottom-left, replacing the old static chips.

**Why one feed.** The search bar, the AI chat and MCP all call the same
`tools.REGISTRY`. A user watching the canvas wants one answer to "what is touching my
messages right now", not three panels each telling a third of it.

| Source | Row |
|---|---|
| `search` | `bm25 “invoice” → 15` · `vector “money I owe” → 3` · `cypher …` |
| `chat` | one row per tool call: `search_vector({"query":"invoice"})`, then `reply · 1 tool call(s)` |
| `mcp` | reserved — the same `push()` call, once the server exists |

Every row carries the **source tag** and, where it is meaningful, the **milliseconds**.
A failure is a red row, not a silent one. The feed is **in memory only** — a viewport
trace, not a log file — capped at 40 rows, collapsible, with a clear button.

**It is deliberately brighter than the old chips.** The chips were `--muted` on a 0.72
black; the trace is `--text` on 0.82 with a coloured source tag, because it is meant to
be read at a glance rather than noticed only when it changes.

### D6. MCP status — **NOT BUILT** (2026-11-25)

`app/mcp/` contains **one file**: `__init__.py`, a docstring. There is no `server.py`,
no transport, no auth. `mcp` *is* installed (`pyproject.toml` line 42) and importable,
so the dependency is ready and the work is unstarted, not blocked.

**What the docstring already commits to** (and what any implementation must honour):

1. **Auth toggle.** Off by default for stdio; **required** for any network transport.
   Never silently unauthenticated on TCP.
2. **Write toggle, separate from the UI's.** An IDE session does not inherit the UI's
   choices. Default off.
3. **Destructive tools need `confirm=true`** in the call itself.
4. **Loopback binding** for any HTTP/socket transport.
5. **Never read `.env`.** That is the guarantee the IMAP credentials rely on —
   `tools.py` has no environment access and MCP must not add one.

**The tool set is already decided** (§D4): the same `tools.REGISTRY`, a different
allowlist. Nothing needs writing twice.

**The UI already has a hook for it.** `GET /api/health` returns `mcp_active`, currently
hardcoded `False` in `app/routers/system.py`. The title bar reads it and shows
`MCP being accessed` instead of `offline - safe`. Building MCP means setting that flag
from the server, not changing the UI.

---

## E. DECIDED 2026-11-25 — search architecture

### E1. The decision

| Surface | Default | Alternative |
|---|---|---|
| **Search bar** | **BM25 fulltext** | a **Vector** toggle beside it |
| **LLM chat** | **vector** (typos, natural language) | BM25 available as a tool |
| **Ingest** | **never embeds** | embeddings are a separate opt-in pass |

**Why BM25 is the search-bar default:** zero ingest cost, builds in seconds, no model,
and it is what a search bar traditionally means. It also removes the full scan.

**Why the chat defaults to vector:** a user types "money I owe someone" and misspells
names. BM25 is word-exact and cannot bridge that. The chat is already slow, so one
379 ms embed is noise against a 2–8 s turn.

**Why embeddings are NOT in ingest:** measured on this box (§E2). A full-payload
clone at 200k messages would spend 5.5 hours embedding. Ingest must stay fast.

### E2. Measured embedding cost (this box, CPU-only, 2026-11-25)

`embeddinggemma`, 768 dims, real bodies from `store/graph.rl`:

| Test | Result |
|---|---|
| Warm single embed | **361 ms** |
| Batch 64 | 36 msg/s |
| Batch 256 | **42 msg/s** (best; 512 is flaky, 320–448 fail) |
| Query embed (search bar) | **379 ms** |
| Full backfill, 2,281 msgs | **0.9 min** |
| 500-message delta | **11.5 s** |

**Body length dominates.** The store median is 30 chars — unusually short:

| Body | Throughput |
|---|---|
| ~35 chars | 34.7 msg/s |
| ~230 chars | 16.1 msg/s |
| ~1400 chars | **3.0 msg/s** |

**Realistic projection** (a clone with email threads, ~10 msg/s):

| Store | At 42 msg/s | At 10 msg/s |
|---|---|---|
| 2,281 | 0.9 min | 3.8 min |
| 50,000 | 20 min | 83 min |
| 200,000 | 79 min | 5.5 hrs |
| 1,000,000 | 6.6 hrs | 28 hrs |

**Consequence:** the backfill is a one-time, user-initiated, background job with
progress and a stop button. The graph stays usable while it runs. A delta only embeds
`m.emb IS NULL`, so a weekly ingest costs seconds.

### E3. Verified engine facts behind this

- **Fulltext works.** `CREATE FULLTEXT INDEX msg_body FOR (m:Message) ON EACH [m.body]`
  and `SEARCH m IN (FULLTEXT INDEX msg_body FOR $q LIMIT n) SCORE AS s` — verified on
  1.0.1. BM25 ranking.
- **Vector works and stays live.** Verified on `:memory:` — the index sees nodes
  written *after* creation, and re-indexes on `SET`. So a re-embed needs no rebuild.
- **Vector is exact NN, not HNSW.** Brute-force over vectors. Fine at 2k, linear at 1M.
- **BM25 is word matching, not substring.** `"graf"` does not match `"grafana"`.
  This is a behaviour change from today's `CONTAINS` and must be stated in the UI.
- **Batch ceiling is 256.** 320–448 return 400; 512 works but is slower and flaky.

### E4. UI decisions

1. **Search bar:** a **Vector** toggle beside the existing Cypher toggle. Three modes
   become `fulltext` (default) / `vector` / `cypher`.
2. **No embeddings yet:** a **yellow warning** appears when Vector is selected —
   "run embeds" — pointing at Utilities.
3. **Utilities modal gains a section below the platform list:** **Embed now**, with a
   subtext naming the local model and the expected time, plus a log.
4. **Both tools are available to the LLM chat**, which defaults to vector.

### E5. Still open

- ~~`find_threads(person)` (A4.1) is not covered by either search mode.~~ **FIXED
  2026-11-25** — see §F1.
- Should the Vector toggle persist across reloads, or reset to BM25 each session?
- Does the embed pass need to respect the platform filter, or embed everything?

---

## F. Built 2026-11-25 — names, screener, mode radios

### F1. A name is not in any message body

**The bug the user hit:** typing `Moreno` returned nothing. Measured on the live
store — `Alicia Moreno` exists as a Correspondent with **8 messages**, and **zero**
message bodies contain the word "moreno". `search_fulltext` scanned `m.body` only.

**The fix:** `_name_matches()` — a substring match on `Correspondent.display_name`,
returned as **thread** rows (`type: "Thread"`, `thread_key`), because "find this
person" means "show me the conversations" and the Viewer already opens a Thread from
such a row. Name hits come **first**, and a thread surfaced by name is not repeated
as a body hit.

Both `search_fulltext` and `search_vector` call it. Names are substring-matched
(a surname is a fragment of a full name); bodies stay word-matched.

### F2. The screener — a subject and a predicate, or no vector

**The problem:** `hi`, `ok`, `thanks`, `im going there` embed to near-identical
vectors and crowd every semantic result. Measured: *"money I owe someone"* returned
`hi` three times.

**The test is spaCy POS, not length.** `what time is it at` is 19 chars and worthless;
`Hetzner is down` is 15 chars and worth keeping. Length alone gets both wrong.

| Rule | Outcome |
|---|---|
| noun **and** verb | keep |
| neither | drop — `no-content` |
| noun, no verb | drop — `no-predicate` |
| verb, no noun | drop — `no-subject` |
| WH-word first, no PROPN, no content noun | drop — `dangling-question` |

**Fails open.** No spaCy, or a parse error, keeps the body: a missing vector is a
silent hole in search, a junk vector is only noise, and noise is visible.

**Skipped bodies are stamped `emb_skipped`, not deleted.** They stay searchable by
fulltext, and the pass never re-examines them. A later screener change can clear the
stamp.

**Measured effect on the live store:** 2,281 messages → **1,537 embedded, 744
screened out (33%)**, in 57.3 s. *"money I owe someone"* went from `hi` to **"still
paying off the Steinway grand"**.

### F3. The mode selector is a radio group, not a cycle

Cycling made the current mode a guess. Now: a caret button showing the active mode,
which expands a radio group to the right — **Search / Vector / Cypher** — and a plain
**Search** button that runs whatever is in the box.

### F4. Tests

`tests/test_search.py` — 22 tests. The ones that matter are invisible in a graph
screenshot: a correspondent's name is findable, a greeting is not embedded, and a
flush keeps every node and edge while deleting every vector. The screener has a
fail-open test, because the failure mode is silent.

---

## G. Flush — deleting vectors and reclaiming disk (2026-11-25)

### G1. Nulling a property frees nothing

Measured on this engine, on a 200-node store with 768-dim vectors:

| Operation | File size |
|---|---|
| write 200 vectors | 3.60 MB |
| `SET m.e = null` | **3.60 MB** (grew, not shrank) |
| `DROP INDEX` | **3.60 MB** |
| `flush()` then `close()` | **3.60 MB** |
| **rebuild into a fresh file** | **0.06 MB** |

Relate appends to a WAL and has **no compaction API**. `Connection` exposes
`execute, executemany, cursor, commit, rollback, close, flush, autocommit, namespace,
set_namespace` — nothing else. So a "flush" that only nulls the property is a lie:
it leaves the bytes on disk.

**The only thing that reclaims is rewriting the store.** `flush_embeddings()` reads
every node and relationship, writes them into a sibling `.rl` without `emb` /
`emb_skipped`, and swaps it in. The original is kept as `.bak.rl` until the rename
succeeds.

### G2. Three bugs, each found by timing a phase

| Version | Time | Cause |
|---|---|---|
| per-node `execute()` | **207 s** | 6,300 round trips |
| one `UNWIND` per label | **51 s** | edges still slow |
| edges grouped by endpoint labels | **1.9 s** | planner uses the key index |

**Bug 1 — the scratch name.** `graph.rl.flush` ends in `.flush`, so Relate read it as
a **directory** store. The rebuild wrote into a folder, the swap produced an empty
graph, and it reported success. The name must end in `.rl`: `graph.flush.rl`.

**Bug 2 — unlabelled edge match.** `MATCH (a {key: row.f})` with no label scans every
node. At 3,183 edges that was 83 s of the 51 s total. Naming both endpoint labels
lets the planner use the key index.

**Bug 3 — indexes are not copied.** The rebuild copies nodes and edges, not indexes,
so the first search after a flush failed with `IndexDoesNotExist`. The flush now
recreates both `msg_body` and `msg_emb` before returning.

### G3. Measured on the live store

**64.7 MB → 3.6 MB in 1.9 s**, 3,113 nodes and 3,183 edges kept, every count
unchanged (2,281 messages, 253 threads, 220 correspondents, 114 places).

**Re-embedding costs 55 s** for 1,537 messages, and the store returns to **46.4 MB** —
not 64.7, because the first 64.7 carried two re-embeds' worth of dead WAL.

### G4. UI

Utilities → *Embeddings Ingest* shows `N embedded · N screened · vector store N MB`,
with **Embed now** and **Delete embeds**. Delete logs the node/edge counts and the
reclaimed megabytes, then re-reads the status so **Embed now** re-arms with no page
refresh.

### G5. The real lesson

**A 768-float vector costs ~30 KB on disk in Relate** — 15× its raw size. That is why
the store went 3.5 MB → 64.7 MB for 1,537 vectors, and why opening it went from
120 ms to 520 ms. Embeddings are not free storage, and the UI must show the size.
