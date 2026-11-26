# HANDOVER.md

**Now and next.** Not a record of everything fixed — that is `git log`. Fixed work gets one
line. Pending work keeps its detail.

Durable facts: [`TECHREADME.md`](TECHREADME.md). UI and visual facts:
[`UIVISUALS.md`](UIVISUALS.md). Human overview: [`README.md`](README.md).

---

## Where it stands

`pytest tests -q` → green, 2 skipped. App runs: `start.bat` → `127.0.0.1:8100`.

**No store counts are recorded here on purpose.** The spool is re-ingested constantly, so any
number written down is stale by the next run and invites false "regression" alarms. Ask the
store instead:

```python
# one query per kind; labels are Message, Thread, Correspondent, Place, Organization, Product
tools.evidence_counts()          # or: MATCH (n:<Kind>) RETURN count(n)
```

> **`outlook` reads 0 rows unless a `.pst` is in `spool/real/outlook/`.** The `.pst` leg is
> built and tested; this is a data-presence question, not a code one. The sample world now
> copies `Outlook.pst` there, so a fresh build does carry 6 messages. Treat a flat-0
> platform as "not re-ingested", not as a bug.

> **Wipe before measuring.** `delta=False` re-processes but does not delete, so a rebuild
> over an existing store keeps the old world's nodes and every count is inflated. `rm
> store/graph.rl` first, or use the UI's Truncate.

**Extraction is done.** All three body kinds are live and drawing: Place, Organization,
Product. The vocabulary is loaded — `PLACE_DICTIONARY` 691, `ORG_DICTIONARY` 585,
`products.INDEX` 764 — and `extract.PRODUCT_ENABLED = True`. Detail: `TECHREADME.md` §5.

**Search was rebuilt 2026-11-25.** The search bar is now **BM25 fulltext** (ranked,
indexed) with a **Vector** mode for semantic search; raw Cypher is the third. The mode
control is a **radio group** that expands from a caret, plus a plain Search button.
Embeddings are a **separate opt-in pass**, never part of ingest — measured at 42 msg/s
on short bodies but 3 msg/s on long ones, so a 200k store is hours. Utilities gained an
*Embed now* section with a log.

**Search covers names, not just bodies.** Typing `Moreno` used to return nothing:
`Alicia Moreno` exists with 8 messages and **zero** bodies contain the word. `_name_matches()`
now matches `Correspondent.display_name` and returns **thread** rows, in both modes.

**Bodies are screened before embedding.** A body with no subject and no predicate
(`hi`, `ok`, `thanks`, `im going there`) is stamped `emb_skipped` and never embedded —
those vectors are near-identical and crowd every semantic result. Measured: 2,281 →
**1,537 embedded, 744 skipped (33%)**. Detail: `wireLLM_tools_queries.md` §F.

**A vector costs ~30 KB on disk in Relate — 15× its raw size.** The store went
3.5 MB → 64.7 MB for 1,537 vectors, and opening it went 120 ms → 520 ms. **Nulling a
property frees nothing** and there is no compaction API, so `flush_embeddings()`
rewrites the store into a fresh `.rl` and swaps it in: **64.7 MB → 3.6 MB in 1.9 s**,
every node and edge kept. Utilities → *Embeddings Ingest* shows the size and has
**Delete embeds**. Detail: `wireLLM_tools_queries.md` §G.

**`sample_writer` was revamped 2026-11-25.** It now has an `append` command that extends a
world's clock, so incremental ingest is testable: write a world ending in the past, ingest
it, move `END` forward, `append`, ingest again — the delta drops the old stretch and writes
only the new one. Measured: 3,270 messages then 315, with 3,884 dropped as already stored.
The clock lives in `.schedule.json` beside `out/`; every write replaces it. See
`sample_writer/README.md` §"append".

**GLiNER is optional and not needed now.** Unmeasured here; the residual recall hole is
names nobody listed, which is small. Next work is the local LLM chat wired into the UI.

**Rebuild needed after any extractor change:** truncate, then re-ingest. A delta run keeps
everything already stored, which is exactly wrong after the reading of bodies changes.
`delta=False` still exists at the API for a scripted re-extract; the UI control is gone.

> **Restart the server, not just the ingest.** Modules are cached in the running process; a
> rebuild through a stale server writes a store that matches neither the old code nor the
> new. This has happened twice.

> **The manifest's per-file `messages` count is zero for older entries.** Fixed
> (`outcome.read` is recorded instead of what the run wrote); the next ingest refreshes them.

**`npm run build` after any `.jsx`/`.css` edit.** Python edits need only a server restart.
`build` runs `build:css` as a second step — before that, a new CSS rule silently never
reached the browser, because `index.html` loads `dist/app.css` separately.

**Cross-platform merging is automatic on every ingest.** `link.link()` runs once at the end
of `ingest()`, over the whole store, so a new export can supply the phone that links two
nodes written months apart. It is idempotent.

**The canvas is two-tier.** Platform bags on a ring; a **merged bag at the centre** holding
every node that is not in a platform bag. Both are invisible. Merged nodes draw a neutral
grey glyph and an orange radial halo. `theme.filter.bags` turns the whole thing off.

**Legs built:** Telegram, WhatsApp (native `chat.txt` **and** HTML), Messenger, LinkedIn,
Email (IMAP **and** saved `.eml`), Outlook (`.pst`), SMS. All seven are in the live store.

**One variant per platform.** `out/` holds several packagings of the same conversations;
ingesting more than one per platform stores every message twice. Ingest one of:
`linkedin/linkedin_zip`, `messenger/messenger_zip`, `outlook/outlook_copy`, `sms/sms_xml`,
`telegram/telegram_bulk`, `whatsapp/whatsapp_html`, `email/email_eml`.

> **Telegram is the exception, and it is now safe.** `ChatExport_` and `DataExport_` are
alternative shapes of one account, so `write_bulk` skips the chat `write_single` owns.
Ingesting both covers the plan exactly once. Fixed 2026-11-25; before that the same chat
landed twice with different message ids.

**One queue.** `spool/sample/`, `store/spool/` and `paths.sample_dir()` are gone. A sample
is a file dropped in `spool/real/`; `ingest` cannot tell it from a real export.

> **Editing the theme.** `theme.js` is compiled into `app/static/dist/app.js`, so an edit
> needs a rebuild — `npm run watch` on save, else `npm run build` — then a hard refresh.
> **No version bump, no `localStorage` clearing:** only the user's *overrides* are stored
> (`relate.graphStyle.overrides`), as a diff against the defaults, so a key nobody touched
> always follows the file. Detail: `TECHREADME.md` §7.

---

## Next

> **Extraction is closed.** All three body kinds are live and drawing; the lists are loaded
> (691 / 585 / 764) and the bugs the load exposed are fixed. `rework_extraction.md` is a
> retired stub — GLiNER is the only thing left in it, and it is optional.
>
> **Chat is wired and working.** Search is rebuilt (BM25 default, vector mode, name
> matching, screener). **The next big item is the MCP server** (§4).

### ★ NEXT BIG ITEM — the MCP server

**Status: not started.** `app/mcp/` holds one file, `__init__.py`, a docstring. `mcp` is
installed (`pyproject.toml` line 42) and importable, so this is unstarted, not blocked.

**Why it is the next big item.** The app's whole claim is *private* comms. An MCP server
is the one feature that lets another agent read that private store, so it is also the one
feature that can quietly break the claim. It deserves a deliberate build, not a bolt-on.

**The tool set is already decided** — the same `tools.REGISTRY`, a different allowlist.
Nothing is written twice. See `wireLLM_tools_queries.md` §D4 and §D6.

**The gates the docstring already commits to, all mandatory:**

1. **Auth toggle.** Off by default for stdio; **required** for any network transport.
   Never silently unauthenticated on TCP.
2. **Write toggle, separate from the UI's.** An IDE session does not inherit the UI's
   choices. Default off.
3. **Destructive tools need `confirm=true`** in the call itself.
4. **Loopback binding** for any HTTP/socket transport.
5. **Never read `.env`.** That is the guarantee the IMAP credentials rely on.

**The UI is already waiting for it.** `GET /api/health` returns `mcp_active`, hardcoded
`False` in `app/routers/system.py`. The title bar shows **MCP being accessed** instead of
`offline - safe` when it is true, and the activity trace has an `mcp` source tag ready.
Building MCP means setting that flag server-side and calling `activity.push()` — the UI
needs no change.

**Open question to settle first:** should MCP expose `run_cypher`? It is the most
powerful tool and the hardest to guard — the write-guard is a regex, not a parser.

### 0. Entity lists — **DONE** (2026-11-24)

**Loaded, merged not replaced.** The entries already in code were the ones the pipeline was
tested against, and several (the sample pool `Fargo`/`Bismarck`/`North Dakota`/`Bay Area`)
exist so a public clone has something to find.

| List | Entries | Where |
|---|---|---|
| Places | **691** | `extract.PLACE_DICTIONARY` |
| Organizations | **585** | `extract.ORG_DICTIONARY` |
| Products | **764** | `products.INDEX` (699 plain + 28 gated, minus 16 generics) |

The drafted file held 658 products, not the 739 the brief claimed; the difference is the
`CONSIDERED AND REJECTED` section, which is a blocklist, not a list.

**Three bugs the load exposed, all fixed — and all invisible in a re-ingest:**

1. **A short entry truncated a longer name.** `overwrite_ents` on a 691-entry gazetteer cut
   `Kensington Market` (an `ORG` to the model) to `place:kensington`. 32 organizations and 8
   products begin with a place name (`London Stock Exchange`, `Canada Goose Expedition
   Parka`). Fixed by snapshotting the model's spans before the ruler and restoring any span
   it shortened — the ruler wins where it has a *phrase*, the model keeps a span it found
   that is *longer*.
2. **Products were never in the ruler.** Only places and orgs were, so `Toyota Hilux` split
   into `Toyota` (ORG) + `Hilux` (PRODUCT) and the index could only rescue the single token
   it was handed. 7 of 724 entries reached the ruler by accident.
3. **`NORP` was dropped outright.** `Vitra` and `Persian` both come back `NORP`, so
   `a Persian rug` produced nothing at all. Added to `PRODUCT_RESCUE_LABELS` with `PERSON`.

Plus: a leading `The ` is stripped when building a ruler pattern — `The North Face Nuptse`
required the article, so a body writing `North Face Nuptse` never matched.

**Scale is not the constraint; classification is.** Measured on `EntityRuler`: 10,000 names
costs 0.28 ms/message (load 1.9 s once). The product index is a Python dict, O(1) at any
size. The ceiling is how many entries can be classified correctly.

### 0b. Per-kind single-mention visibility — **DONE**

`theme.filter.hideSingleMentions` is now a **per-kind tri-state map**
(`nodeVisibility: { Place, Product, Organization }`), rendered in the Canvas modal as one
radio group per row: **show all / merged only / hide**. Mutually exclusive; there is no
"singles only". Correspondent and Person are greyed placeholders, not wired.

A merged node is decided by **bag membership**, the same rule that parents it to
`bag:merged`, so the filter and the drawing cannot disagree. `hideMerged` and
`singlesCountKey` are gone; their saved overrides no longer match a key and are ignored.

**It still does not replace the generic block.** Hiding works on mention count; blocking
works on what the word *is*. `seat` is mentioned *more* often than a rare product, so a
mention floor promotes junk instead of suppressing it.

**Judging a list:** the canvas is not the instrument. Hidden single mentions are still stored,
counted and searchable — query `MATCH (p:Product) WHERE p.mention_count >= 2`.

### 1. The graph as a portable module

**Detail is in [`detacheable_graph.md`](detacheable_graph.md).** Short version: the
payload is already renderer-neutral; the cost is the canvas, not the data.

- **Cheap (~2 days, do regardless)** — freeze the payload with a key-set test, drop the
  dead `per_platform` projection, and write the cross-definitions (bag ≈ d3
  `forceRadial` / React Flow `parentId`; halo ≈ sprite / `box-shadow`).
- **Expensive (2–4 days, only when wanted)** — one alternative renderer behind a switch.
  `GraphCanvas.jsx` is 1,314 lines and the payload is ~5% of the port.
- **The two losses to expect** are native label LOD and merged-halo occlusion — both
  already recorded as unsolvable in Cytoscape, so a new renderer may *fix* them.

**Stored shape is now portable.** As of 2026-11-23 the store holds facts, not summaries:
`(message)-[:IN]->(thread)` and `(message)-[:MENTIONS]->(entity)`. `Thread → Entity` is a
read-time projection in `tools._EDGE_QUERIES`. That is the triple model another graph engine
would accept — keep it that way, and do not let `_EDGE_QUERIES` become the schema.

### 2. Body-entity extraction — the pipeline, as built

**All three kinds are live: Place, Organization, Product.** One pipeline, one write table
(`writer._ENTITY_WRITE_KINDS`). Adding a kind is a table entry, not an implementation.

**The order, and it cannot be reordered:**

1. **Extract**, per message (and per `<br>` fragment). spaCy proposes spans; `_arbitrate()`
   decides the kind; the index can overrule the model for `GPE`/`FAC`/`LOC`/`PERSON` but
   **never** for `ORG`.
2. **Fold within a platform.** `canon.canonical(kind=…)` converges spellings.
3. **Match across platforms.** `link.link()` merges on exact canonical name.

**The dictionaries are the feature, not a stopgap.** `en_core_web_sm` has no gazetteer — it
is a neural net guessing from sentence shape. It labels `Austin` a person, `Grafana` a
person, and `Databricks` a place. `PLACE_DICTIONARY` (691), `ORG_DICTIONARY` (585) and
`products.py` (764) run *before* the model and win.

**`PRODUCT_ENABLED` is ON** as of 2026-11-23. The flag still exists and still gates
`MENTIONS_PRODUCT` in `DRAWABLE_*`; turning it off returns the graph to Place+Org without a
rebuild.

**The document guard.** `extract.DOCUMENT_CHARS = 2000` (4× p99). Every junk Org came from
ONE 11,719-char marketing newsletter read as a conversation. Reported as a warning, never an
error. **A `count >= 2` floor would have kept every junk node** — the signal and the junk
differ by message LENGTH, not by count.

**The generic block lives in the index, not in `canon`.** `canon` folds `Seat` and `seat` to
one key, which is correct — it is a spelling function. Only the index can say one is a
licence concept and the other is furniture.

**Language:** English only in v1. Non-English input yields no nodes rather than wrong ones;
`extract.language_guess()` warns on the report and never gates the write.

Full design history: [`archive_docs/locking_in_node_extraction.md`](archive_docs/locking_in_node_extraction.md);
the retired extraction stub: [`rework_extraction.md`](rework_extraction.md).

**`canon` cannot substitute for extraction.** It normalises a name it is handed; it cannot
decide a span *is* a place. Running capitalised words through `canonical(kind="place")`
yields `monday`, `hi dave`, `ny` — no error, no useful result.

**No LLM calls in this pipeline.** Extraction is spaCy and rules only. The local LLM is a
chat feature in the UI (§3) and has no role in entity extraction, folding or merging.

**Two `canon` bugs the Place leg exposed, both fixed:** the place branch never stripped a
leading article (`the Bay Area` = `Bay Area` is now one node); and `_REGION_TAIL` was
lowercase-anchored but ran after case flattening, so it never matched and `Kensington,
London` kept its country in the key. Plus new behaviour: `n`/`s`/`e`/`w` + a word expands to
`north`/`south`/`east`/`west`.

**Accepted false positives.** The model calls some products `GPE`/`FAC` in prepositional
frames (`nothing new from Databricks`). With `PRODUCT_ENABLED` on, most of those are now
reclaimed as `Product` by the index — that was 29 of 212 entity nodes. What remains is a
stray node, never a merge, and `mention_count: 1` makes it obvious.

**A Place is never fuzzy-folded.** Two places one letter apart are two places; there is no
second signal to weigh. Entities fold on exact canonical name only
(`ENTITY_EVIDENCE_ORDER = ("exact_name",)`), while a Correspondent also has a `fuzzy` rung —
a typo'd surname has no other reading, a typo'd town does.

**Language:** English only in v1, by decision. Non-English input yields no nodes rather than
wrong ones. `extract.language_guess()` sets a non-blocking **warning** on the batch report;
it never errors and never gates the message write. The seam sits above the extractor, so
another language is a second model and a language guess, not a rewrite.

**Drawn since 2026-11-22.** Places draw with the design's own art (`place-*.svg`, map pin,
8 colour variants from `scripts/build_entity_icons.py`) and the design's own halo —
`#5a5f66` dark grey, not the Correspondent orange, because a Place merge is the weaker
claim. **Bagging is the standard rule for every kind:** one platform → that platform's bag,
merged → the centre. An earlier attempt gave entities their own bag; it stranded
single-platform places away from the conversations that mention them and was removed.

⚠ **Icon caching is handled on the server, not in the UI.** `app/main.py`'s `IconsElsewhere`
mount returns `Cache-Control: no-cache` for `/static/icons/*`; the `ETag` then answers 304, so
a replaced glyph appears on a hard refresh with no version to bump. (Starlette passes the path
with the OS separator — the check normalises `\` to `/`, or it never matches on Windows.)

**Still open:**

- **`merged_by` has two sources that disagree.** `writer` sets it from `canon` evidence at
  write time; `link` can only `coalesce` into it, so a node that entered as `exact_name` keeps
  that value even when a later fold was fuzzy. The link-time reason is in
  `report["merged_by"]` only. Fixing it means deciding which is canonical.
- **`merged_by` wording** — surfaced as a hover title on the `Merged` pill ("a spelling
  match, not a verified identity"). Good enough.

Full design: [`archive_docs/locking_in_node_extraction.md`](archive_docs/locking_in_node_extraction.md).

### 2c. Incremental ingest — the delta cutoff

**Built.** `ingest(delta=True)` is the **default**. A weekly export is mostly messages
the graph already holds, and NER costs ~1.5 ms per message, so re-extracting the backlog
was the dominant cost of a re-ingest.

**The rule.** For each platform, read `max(ts_utc)` from the store (`writer.watermark`,
indexed by `_SCHEMA`'s new `msg_ts`). Drop every parsed message at or below it **before**
the write and therefore before `extract`. Conservative by construction: no watermark (an
empty store) keeps everything; a message with no timestamp is kept.

**Measured** on a realistic weekly case — 10,000 stored + 500 new:

| Run | Time |
|---|---|
| full re-process | 25.7 s |
| delta | 2.6 s |
| **speedup** | **10×** |

**`delta=False`** is the escape hatch. It is **no longer a UI control** — the "Full
re-process" checkbox was removed because truncating first achieves the same thing with no
extra cost, and a toggle that needed a paragraph of explanation was a toggle nobody read.
The capability stays at the API for a scripted re-extract, and is required after an
extractor change.

**Known limit, documented in `tests/test_delta.py`:** a message carrying an older
timestamp than the watermark is indistinguishable from one already stored, so a genuinely
backdated export needs `delta=False`. Exports are written in time order, so this is rare.

**Two bugs this exposed, both fixed:**

- **The manifest recorded `msgs=0` for every file.** A delta run writes nothing for a file
  it has already seen, and the manifest was recording what *this run wrote* rather than
  what the *file holds*. That erased the only record of a file's message count and broke
  the "Already in the spool" list. Now records `outcome.read`, captured before the cutoff.
- **The staged drop-in list never cleared after a successful ingest**, so the next run
  looked like it would re-read files already taken. It now clears on success and is kept
  deliberately when a leg failed (the user is about to retry).

### 2d. Drag and drop — `uppie`

**Built.** The drop box now uses [`uppie`](https://github.com/silverwind/uppie)
(`uppie@4.1.7`, BSD-2, zero dependencies, ~8.8 KB) rather than a hand-rolled handler.

**Why a dependency.** A browser reports a dropped **folder** as zero files — `dataTransfer.files`
is empty — so the old `onDrop` silently did nothing for the one export shape that needs it
most (Telegram ships a directory). `uppie` walks `webkitGetAsEntry` to exhaustion, including
the 100-entry `readEntries` batching, and appends each file under its path relative to the
dropped folder.

**Verified in a real browser**, not just by reading the README: folder walk reaches nested
subdirectories, `{ name: "files" }` is required (the default `files[]` is **422** from
FastAPI), the enclosing folder survives into `spool/real/<platform>/<folder>/`, and a
genuine OS drag via CDP works.

**A third bug, in our own code:** `api.request()` forced `content-type: application/json`
on every request with a body, so the `FormData` was sent as JSON and FastAPI answered
`files: Field required`. A `FormData` body now sets no content-type, letting the browser
write the multipart boundary.

**Removed:** the separate "Choose a folder" input (`webkitdirectory`) and the folder button.
Dragging a folder replaces them; the path-paste field remains as the escape hatch.

**Watch for:** an unticked *Ingest Ready* rejects the upload with `write access is disabled`,
and that message lands in INGEST LOG **below** the dropzone — off-screen at normal modal
height, so a correct drop can look like nothing happened.

### 3. The local LLM — **standing, not the priority**

Chat is wired into the UI. Never exercised end to end on a real conversation. Needs a check
that `MAX_TOOL_CHARS` truncation is **reported** rather than silent. `think: false` is a 28×
speedup on this box and must stay applied. Not involved in entity extraction (§2) — chat only.

### 4. MCP wiring — **the next big item**

See the ★ section above. `app/mcp/__init__.py` is a docstring. When built it must **not**
gain a `.env` read — that is the guarantee the IMAP credentials rely on. Every capability
is already a plain function in `tools.py`, so the binding is thin by construction.

---

## Planned — retire the LOG modal for a generated KB

**Not built. Decided 2026-11-25.**

The **Log** modal (`LogModal.jsx`, the *Evidence* panel) is a static read of
`/api/health`, `/api/stats` and `/api/types`. It duplicates what a generated knowledge
base would say better, and it is one more surface to keep in step with the schema.

**The plan:**

1. **A KB file generated on every ingest** — every count, every platform, the schema,
   the store size, the embed coverage. One artifact, written by `ingest()`.
2. **Available as a tool call** (`read_kb` or similar), so any agent — the local chat,
   MCP, a future one — asks the store what it holds instead of guessing.
3. **Then delete `LogModal.jsx`** and its title-bar button.

**Why a file and not a live query.** The same reason `evidence_counts` exists: an agent
that can ask "what is in this store" in one call does not burn a tool round discovering
it. A generated file also gives the user something to read without the app running.

**Do not delete the modal until the KB exists** — it is currently the only place the
store's shape is visible in the UI.

---

## Open decisions

- **The platform filter narrows the AI chat as well as the search bar.** Deliberate,
  overriding the earlier "UI state never narrows an agent's query" rule. The alternative is
  a per-call `platforms` argument instead of module state in `tools.py`.
- **Per-node gravity is not a fcose feature.** Big threads can only be approximated as
  anchors via lower `nodeRepulsion`. The dominance leash was designed and withdrawn in
  favour of equal pull.
- **The Outlook fingerprint can merge two genuinely distinct messages** — same thread, same
  second, byte-identical body, different senders. Accepted: the alternative is every sent
  message appearing twice, which the real file exhibits.
- **WhatsApp's minute-resolution key** was a hazard for the old store's second-resolution
  rows. The 2026-11-18 wipe resolved it; the live store is built entirely at minute
  resolution.
- **Entity extraction is English-only in v1.** A public repo with users from anywhere will
  meet non-English exports. Accepted for v1: silence beats a wrong node, and the seam sits
  above the extractor so a second language is a second model, not a rewrite. Non-English
  input warns on the report; it never errors.
- **Place `:Merged` is a weaker claim than Correspondent `:Merged`.** A Correspondent folds
  on phone or email; a Place folds only on its canonical name. Name matching is the only
  evidence available, so it is shipped best-effort rather than held back.
- **A `Product` may take a span the model called `GPE`/`FAC`/`LOC`/`PERSON`, but never
  `ORG`.** Correct for `Gemini`-the-model and `Tableau`-the-product; wrong for someone who
  lives in Gemini, Texas. Asymmetric on purpose: an `ORG` span is often a *longer* name than
  the product inside it (`Grafana Labs` contains `Grafana`), and demoting it would lose the
  organisation. Revisit on real data.
- **`Snowflake` is a company and a product.** It stays an `organization:` node unless
  `snowflake cortex` appears in the body. Deliberate — the graph can hold both once keys are
  namespaced per kind.
- **`merged_by` has two sources that disagree** (see §2). Unfixed, on purpose: choosing
  between them is a store-wide decision.

---

## Latent — a re-export can mint a whole new thread

**Not a bug today, because nothing has been re-ingested. It will bite on the first one.**

A thread's identity is `platform:chat_id`, and three platforms *derive* `chat_id` rather
than read it from the export. If the derivation input changes between two exports of the
same conversation, the thread key changes, and because `message_key()` hashes `chat_id` as
its first component, **every message in it gets a new key too**. Result: the conversation
exists twice, with no error and no warning.

| Platform | `chat_id` derived from | Changes when |
|---|---|---|
| **LinkedIn** | `sha256(CONVERSATION ID)[:16]` → `li_…` | LinkedIn re-issues conversation ids on some archive regenerations |
| **WhatsApp** | `sha256(chat title)[:16]` → `wa_…` | the contact is renamed. **The two-dialect case is fixed** — `read_export` strips the `WhatsApp Chat with ` prefix, so `X.zip` and `WhatsApp Chat with X.txt` agree. |
| **Email** | `Message-ID`, else `uid:<UIDVALIDITY>:<UID>` | the server bumps `UIDVALIDITY` — every key in the mailbox changes at once |
| Telegram / Messenger | read straight from the export | (stable) |

WhatsApp's `message_key()` also hashes the **body**, so an edited message, a changed media
placeholder or a locale difference duplicates that one row even when the thread id holds.

**Debugging it later:** compare `count(DISTINCT t.key)` against the number of conversations
the export claims. A doubled count with identical titles is this. The fix is a stable
surrogate — persist `(platform, title-or-participants) → chat_id` in `store/profile/` and
reuse it, the way `identity.json` already persists the Owner — not a change to the hash.

---

## Ingest UI — state after the `uppie` rebuild

| Path | Behaviour |
|---|---|
| **Drag a file** | **Works.** Verified with a synthetic drop and a real OS drag. |
| **Drag a folder** | **Works.** `uppie` walks the tree; the folder name survives into the spool. |
| **Select files** | **Works** — the hidden input feeds the same upload path. |
| **Paste a path** | **Works**, unchanged, and still the escape hatch. |
| **Select a folder** | The separate button is **gone**; dragging a folder replaces it. |

**Two of the three old defects are fixed:**

1. ~~`api.js` sent only the bare filename, losing the folder.~~ `uppie` appends each file
   under its path relative to the dropped folder, so `parts[-2]` now fires.
2. ~~A dropped `email_eml/` folder arrived as ~190 loose `.eml` files, all unrecognised.~~
   **Still partly true.** `uppie` now preserves `email_eml/Inbox/...`, so the *parent* is
   right, but `app/routers/ingest.py::upload` still calls `detect_platform()` on each
   **file**, not on the reconstructed directory — so a dropped `.eml` tree can still be
   filed as `unrecognised` even though pasting the same path works. Fixing it means
   grouping uploads by top folder and asking `detect_platform()` about the folder, the way
   `stage()` does.
3. ~~Silent staging.~~ The modal now logs `reading N file(s)…`, `staged N file(s)`, and one
   line per staged file.

**One trap worth knowing:** an unticked *Ingest Ready* rejects the upload with `write access
is disabled`, logged in INGEST LOG **below** the dropzone. A correct drop can look like
nothing happened if that line is off-screen.

---

## Known issues in the live store

- **6 threads have no Correspondent edge — all Outlook.** Correct by design: the `.pst`
  fixture is a single-account demo mailbox, so every message is `is_self`. Revisit only with
  a real multi-party `.pst`.
- **22 owner-silent threads, 90 messages total** — a small, sane tail across five platforms.
- `Facebook user` spans Messenger threads — a placeholder Correspondent by design, and
  platform-scoped so it never merges with LinkedIn's `LinkedIn Member`.
- **LinkedIn recipient lists can become one node.** `_split_recipients()` splits on `;` only,
  deliberately, because `TO` also contains names with credentials (`Steve Mikano CIA, AIC-M,
  AINS, SSBB`). `canon.split_list()` implements the separator heuristic but the adapter does
  not call it yet.
- **The two unfocolded spelling pairs are folded now** — `dimitri/dimitir whitfield` and
  `sahfi/shafi hassan` were the known long-edge stretchers, and the fuzzy fold (2026-11-23)
  takes both. **But `merged_by` says `exact_name`**, not `fuzzy`, on every one of the 48
  merged nodes: the writer stamps the field at write time and `link` can only `coalesce` into
  it. The link-time reason is in `report["merged_by"]` only. Two sources, one field — see
  §2.

---

## Spec — Email leg (one platform, many providers)

**Term: `Email`.** Platform key `email`. **One mailbox at a time.** `--email` is repeatable
but every mailbox lands as platform `email`, so two mailboxes merge into one cluster and
`Message.key` is not guaranteed unique across them.

**The provider is a parameter, not a platform.** Nothing in the adapter may branch on a
provider name. `ENV_ACCOUNTS` is a convenience table of 11, not a whitelist;
`account_from_parts(host, user, password, port=993)` covers anything else.

**Folder detection is provider-agnostic.** Tier 1: RFC 6154 special-use flags (`\All`,
`\Inbox`, `\Sent`) — locale-proof, which is why a Spanish Gmail (`[Gmail]/Todos`) works.
Tier 2: name hints on the last path segment, for servers that publish no flags.

| provider | quirk |
|---|---|
| Gmail | `[Gmail]/All Mail` already holds Inbox + Sent — importing both double-counts |
| Outlook / O365 | Basic auth is dead; needs OAuth2 or an app password |
| Yahoo / AOL / iCloud | App passwords; the displayed password has spaces that are not part of it |
| cPanel / generic | Host is `mail.<domain>`; folders are `INBOX` + `INBOX.Sent` |
| Yandex / GMX | Often publish no special-use flags — tier 2 carries it |

**Work:** one mailbox per run (refuse two `--email` values rather than silently merging);
`Message.mailbox` as a property so the Viewer can say which mailbox a message came from
without splitting the platform.

---

## Cleanup — LinkedIn "Sponsored" messages

74 messages across 73 threads contain raw HTML
(`<p class="spinmail-quill-editor__spin-break">…`), including `%FIRSTNAME%` placeholders.
32 sit in one thread titled `Sponsored Conversation`.

**Fix, in order:** (1) strip HTML in the LinkedIn adapter — reuse the `_text()` pattern from
`messenger.py`; (2) set `raw_kind = "sponsored"` when the body contains
`spinmail-quill-editor` or the sender is `LinkedIn Member` / `LinkedIn Talent Solutions`;
(3) optionally drop them behind a toggle, same shape as `exclude_spam_groups`.

Do 1 and 2. Do 3 only if the Owner wants sponsored mail out of the graph entirely.

---

## Done — one line each

- **2026-11-25** — **Five small fixes.** (1) Vector results now show **`N% match`** —
  only for body hits whose score is 0–1, because a BM25 score is unbounded and means
  nothing as a percentage. (2) **Clicking a result now zooms and halos** — it was
  haloing the *message* key while the canvas draws *Thread* nodes, so nothing matched
  and the camera never moved; it now uses the thread key. (3) The chat shows the user's
  bubble **before** "thinking…", not after the reply. (4) `uvicorn` access logging is
  **off** — the console was buried in `GET /static/icons/*.svg 304` lines; startup,
  shutdown and errors still print. Added `app/static/favicon.svg` (the bag ring + merged
  node, in 32px). (5) A transcript persisted before a model swap keeps the old model
  name on old turns — accurate, but it reads as a bug, so it now says `(then)` when it
  differs from the live model.

- **2026-11-25** — **One activity trace for search, chat and MCP.**
  `components/ActivityLog.jsx` + `useActivity()` replace the static canvas chips with a
  live feed bottom-left: every search (`bm25 “invoice” → 15`), every chat tool call
  (`search_vector({...})`) and, when MCP is built, every MCP call — one row each, tagged
  by source, with milliseconds and a red row on failure. In memory only, capped at 40,
  collapsible, clearable. Brighter than the chips it replaced, because it is meant to be
  read at a glance. **MCP itself is still not built** — `app/mcp/` is one docstring;
  `mcp` is installed and the tool set is decided, so it is unstarted, not blocked.

- **2026-11-25** — **Flush fidelity test; two real bugs it caught.**
  `test_flush_is_byte_identical_for_every_node_and_edge` diffs every node's labels and
  properties and every edge's type, endpoints and properties before and after a flush.
  It caught (1) the rebuild not copying **indexes**, so BM25 broke after a *vector*
  flush — a mode unrelated to vectors; and (2) recreating only the indexes for labels
  that hold nodes, which lost `place_key` and friends on a store with empty entity
  legs. The flush now replays `writer._SCHEMA` in full. Index **definitions** are
  compared, not names (`Message_key` vs `msg_key` is the same index). Suite 500 → **501
  passed**. Documented in `tests/README.md` and `TECHREADME.md` §10 as a Relate
  limitation worth reporting upstream: no surgical property removal, no compaction.

- **2026-11-25** — **Delete embeds: a real flush, 207 s → 1.9 s.** Nulling a property
  frees nothing on Relate (measured: `SET m.emb = null` *grows* the file; `DROP INDEX`
  and `flush()` free nothing; there is no compaction API), so `flush_embeddings()`
  rewrites the store into a fresh `.rl` and swaps it in — **64.7 MB → 3.6 MB in 1.9 s**,
  all 3,113 nodes and 3,183 edges kept. Three bugs found by timing each phase: the
  scratch name `graph.rl.flush` was read as a *directory* store (empty graph, reported
  success); unlabelled `MATCH (a {key: …})` scanned every node per edge (83 s of the
  total); and a rebuild copies nodes and edges but **not indexes**, so the first search
  after a flush failed — it now recreates `msg_body` and `msg_emb`. Utilities shows
  `N embedded · N screened · vector store N MB` with **Embed now** / **Delete embeds**,
  and re-arms without a refresh. Suite 497 → **500 passed**.

- **2026-11-25** — **Search finds names; greetings are screened; modes are radios.**
  Typing `Moreno` returned nothing because `search_fulltext` scanned `m.body` only —
  `Alicia Moreno` exists with 8 messages and **zero** bodies contain the word. Added
  `_name_matches()` (substring on `Correspondent.display_name`, returned as **thread**
  rows, name hits first, no duplicate thread) to both fulltext and vector. Added
  `screen_body()` — a spaCy POS test for subject **and** predicate, so `hi`/`ok`/
  `thanks`/`im going there`/`what time is it at` are stamped `emb_skipped` and never
  embedded; measured **744 of 2,281 (33%)** screened out, and *"money I owe someone"*
  went from `hi` to *"still paying off the Steinway grand"*. The screener fails open.
  The search mode control became a **radio group** expanding from a caret
  (Search / Vector / Cypher) plus a plain Search button — cycling made the current
  mode a guess. `tests/test_search.py` adds 19 tests; suite 478 → **497 passed**.

- **2026-11-25** — **Search rebuilt: BM25 default, vector toggle, embeddings as an
  opt-in pass.** The search bar's three modes are `fulltext` (BM25, default) → `vector`
  (semantic) → `cypher`, cycled by one button. A yellow **run embeds** pill appears when
  Vector is selected and the store has no vectors. Utilities gained an **Embed now**
  section with a live log and a Stop button. **Ingest never embeds** — measured 42 msg/s
  on short bodies, 3 msg/s on long ones, so a 200k store is hours; the pass is batched at
  128 with a halving retry on 400 (the ceiling is token-dependent, not a fixed count).
  Live store fully embedded: 2,281 messages in 55.8 s. Chat tools became
  `search_vector` (default — tolerates typos and natural language) + `search_fulltext`.
  **Two engine facts corrected:** Relate *does* have fulltext indexes (BM25, since
  0.1.1) and vector indexes stay live on later writes and `SET` — both verified on
  1.0.1. `models.py` gained `num_predict` (an unset limit lets reasoning eat the budget
  and return an empty answer), `num_thread: 4` (4P+8E; E-cores lose tok/s) and
  `keep_alive: -1`.

- **2026-11-24** — **Thread titles lost their platform token.** `WhatsApp; Fred Jones;
  01-28-2024->` → `Fred Jones; 01-28-2024->`, in the canvas label and the Viewer alike,
  because the change is in `writer.thread_display_title` (the one place a title is built)
  rather than in either reader. The platform was already carried twice on screen — the
  glyph colour and the Viewer's pill. `TECHREADME.md` §3 schema updated.
- **2026-11-24** — **Entity lists loaded; three extraction bugs fixed.** Places 97 → 691,
  Organizations 26 → 585, Products 92 → 764, merged not replaced. The load exposed three
  bugs a re-ingest could not show: a short dictionary entry truncated a longer name
  (`Kensington Market` → `place:kensington`, and 40 dictionary entries begin with a place
  name); products were never in the `EntityRuler` at all, so `Toyota Hilux` split into two
  half-names; and `NORP` was dropped outright, so `a Persian rug` produced nothing. Fixed
  with a model-span snapshot + restore pass, products added to the ruler, `NORP` added to
  `PRODUCT_RESCUE_LABELS`, and a leading `The ` stripped from ruler patterns. **Four tests
  pin the behaviour** — these are exactly the cases invisible in a 700-node graph.
- **2026-11-24** — **Cast widened; `CORR_MULTI_PLATFORM` finally means something.** 52 of
  95 Correspondents were merging (55%) against a knob of 8%, because per-platform pools ran
  dry (Telegram: 14 people, 29 threads) and `_pick_distinct` fell back to anyone — including
  people whose `on` set never included that platform. Cast 60-120 to **260-340**, names
  151/133 to **460/798** (common US given names and surnames). Now **13 of 172 (8%)**, so the
  knob is the only thing creating a merge. Two bugs found on the way: `canon` split `GmbH`
  into `Gmb H` before the legal-suffix pass, so `Pure Storage GmbH` keyed differently from
  `Pure Storage`; and the spam-group writer coalesced adjacent same-sender rows into one
  `<br>` section, dropping the noise share from 57% to 45% and stopping the app's gate from
  firing.
- **2026-11-24** — **`sample_writer` made less uniform.** `THREADS_PER_PLATFORM` →
  `AVG_THREADS_PER_PLATFORM` + `THREADS_JITTER` (each platform rolls ±30%, so counts are
  24–41 instead of a flat 25). Big threads moved from two platforms to four
  (`BIG_THREAD_PLATFORMS`), randomised 3–7 per world at 150–520 messages with the low half
  twice as likely, and spread one-per-platform before repeating. New `BODY_ENTITY_SHARE`
  weights the kind draw (place 0.7, product 1.6) — measured effect: place 33% → 28%,
  product 33% → 35%. Two bugs found: the §12 contract still demanded a big thread on
  messenger *and* telegram by name, and the big-thread plan was re-rolled per platform call,
  giving every platform the identical size.
- **2026-11-24** — **Tests repointed at the sample world, not personal exports.** Four
  adapter tests read `~/Downloads` (an 825 MB SMS backup, a real Messenger zip) and skipped
  on any other machine; they now read `spool/real/`, which is committed and generated. The
  assertions that were about *that* file were rewritten as properties (a 10–20 message
  email thread, not `11156` rows). Suite 126 s → 68 s. `tests/README.md` documents the
  payloads and how to wire a new format.
- **2026-11-24** — **Ingest modal: one summary line, not a file list.** An email drop is
  ~190 `.eml` files and a `.pst` is thousands; listing them pushed the rest of the modal
  off-screen. Now `190 files ready · email ×190`, grouped by platform, with unrecognised
  files still called out. Per-file detail stays in INGEST LOG.
- **2026-11-23** — **Extraction rework: Product leg, message-anchored mentions, no
  `POSSIBLY`.** `POSSIBLY` removed (all 6 edges were typo pairs; `r.score` was null on
  every one) — fuzzy is now a fifth rung in `_fold_groups`. `MENTIONS` moved from Thread to
  Message; `Thread → Entity` became a projection (measured 1.2 ms vs 2.5 ms). `<br>` bodies
  fragment before extraction (28 → 33 mentions, junk spans gone). `Product` is a live kind
  behind `extract.PRODUCT_ENABLED`, backed by `relate_comms/products.py` (then 92 entries,
  three tiers, four-rule ladder, no weights; **764 as of 2026-11-24**). **22 Product nodes,
  22/22 correct, 0 false positives.** Three bugs found on the way: `union()` dropped the absorbed root's reason;
  `PERSON` spans were dropped outright so the index could never rescue `Grafana`; and
  `DRAWABLE_NODE_TYPES` was a hardcoded list, so Products existed with **zero edges drawn**.
  **Correction:** `en_core_web_sm` *does* emit `PRODUCT` — rarely and frame-sensitively;
  two research reports and two earlier notes said it did not.
- **2026-11-23** — **`sample_writer` fuzz rebuilt on three independent axes.** Spelling /
  platforms / mentions now roll separately per item, so all four body combinations exist
  (`single×1`, `single×N`, `multi×1`, `multi×N`). Knobs are **shares, not counts**:
  `CORR_FUZZY` 7%, `CORR_MULTI_PLATFORM` 8%, `BODY_FUZZY` 15%, `BODY_MULTI_MENTION` 8%,
  `BODY_MULTI_PLATFORM` 4%, `MENTIONS_MULTI` (2,4). `FUZZ_VARIANTS` is a uniform per-kind
  list — no weight table, `1/len(list)` by construction. New variants: `legal_suffix`,
  `postal_code`, `region_tail`, `hyphen`, `credentials`, `acronym`. One generic
  `World.body_entities[kind][name] -> EntityPlan` replaces the four per-kind tables.
  **Shares are not promises:** ~1 body in 12 names an entity, so a flagged item may never
  be written — that is the `mention_count: 1` tail, and it is why `BODY_FUZZY` is 15%.
  Two bugs fixed on the way: `abbrev` abbreviated `St`/`Port`/`Saint`, which `canon`
  expands to `south`/`north` and so minted **different places** (`St Paul` → `south paul`);
  and `_assign_labels()` kept its own hardcoded platform list, ignoring `config.PLATFORMS`.
  Suite **441 passed, 2 skipped**. What the generator does: `sample_writer/README.md`.
- **2026-11-22** — **Organization extraction built** (`canon` article fix, `ORG_LABELS`,
  `ORG_DICTIONARY` 26 names, `TRUNCATION_TAILS`, kind-aware `writer.write_entities`,
  `Organization` in `DRAWABLE_NODE_TYPES`/`EDGE_TYPES`/`nodeTypes`/`nodeLabels`). **The
  noise was not what we thought:** all ~22 junk Orgs (`pdf`, `swf`, `wordprocessing ml
  2003`, `end user license agreement`) came from ONE 11,719-char newsletter, against a
  corpus median of 28 chars. Added `extract.DOCUMENT_CHARS` (2,000, derived from 4x p99)
  — **49 Org nodes → 19**, MIME class gone. A `count >= 2` floor would have kept every
  one of them. Canvas floor added as a VIEW toggle (`filter.showSingleMentions`, default
  off, `:Merged` overrides it) — no store change, no re-ingest.
- **2026-11-22** — **Viewer multi-platform bug: the real cause was the click payload, not
  the Viewer.** `GraphCanvas`'s `tap` handler built `entry` from 8 fields and never sent
  `platforms` or `merged`, so `platformsOf(entry)` fell back to the single `platform`
  string and `entry.merged` was `undefined` — the earlier `CorrespondentView` fix was
  correct and had nothing to render. `platforms`, `merged`, `threadCount`, `mentionCount`
  now travel. **Places drawn**: `DRAWABLE_NODE_TYPES` + `DRAWABLE_EDGE_TYPES`
  (`MENTIONS_PLACE`), `theme.filter.nodeTypes`, and a separate **entity bag** so a spelling
  match never shares a region with a verified person fold.
- **2026-11-22** — Incremental ingest (`delta`, 10x on a weekly case) with a `msg_ts`
  index and a `Full re-process` escape hatch; drag and drop rebuilt on `uppie` so a folder
  drops correctly; three bugs fixed on the way (manifest recording `msgs=0`, the API layer
  forcing JSON on a `FormData` body, the staged list never clearing); merged Correspondents
  finally show every platform plus a `Merged` pill in the Viewer; entity glyphs for Place /
  Organization / Person generated per platform colour.
- **2026-11-22** — Place extraction built end to end (`extract.py` + `writer.write_places` +
  `link._link_entity`, wired into `ingest`); **Viewer bug fixed** — `CorrespondentView` and
  `EntityView` rendered one platform from `entry.platform` and never said "merged", so a
  4-platform node looked like a 1-platform one (the store and API were always correct); now
  one pill per platform from `platforms` plus a `Merged` pill; `npm run build` gained
  `build:css`, because `npm run build` alone never rewrote `static/dist/app.css` and a new
  rule would have silently never reached the browser.

- **2026-11-24** — **Canvas modal rebuilt around the apply button.** Sort, limit, radios and
toggles are held in the modal and applied only on **Re-run layout**, which fetches then
re-solves and keeps the panel open — the Gravity modal's model. Killed a double-fetch bug
(`App.jsx` watched the filter *and* the modal called `onReload`). Node types became one
**tri-state radio group per kind** (show all / merged only / hide) on the three wired kinds.
**Declutter pass** added after the solver: fcose measures a leaf node's BODY box only, so its
own anti-overlap branch never sees the glyph — `declutter()` pushes apart the real boxes
(`includeLabels: false`). **Product glyph** replaced (gift box) with a blue merged halo;
Organization moved to `C/E/F` and light-blue halo, lines 25% thicker; Place kept yellow and
`B/D/E`. **Viewer:** entity views now hop `Message → Thread` (the `Thread-[:MENTIONS]->`
query they used had **zero edges** and always returned nothing), ordered by first appearance;
rows now halo + fly-to + switch, not Viewer-only; orange "not visible on canvas" note; a
text-selection guard so copy/paste no longer navigates. `wheelSensitivity` finally applies
live (it was a constructor-only option). **Docs:** `CytoGravityRecommend.md` folded into
`UIVISUALS.md` §12 and deleted.

- **2026-11-21** — Merged bag built and centred; merged nodes styled (grey glyph + orange
  radial underlay); `UIVISUALS.md` written; theme persistence changed to **overrides-only**
  (removes the `THEME_VERSION` bump); edge tiers re-spread; `shadow-*`/`underlay-*`/
  `line-outline-*` glow attempts on edges **settled as impossible**; halo occlusion
  **settled as impossible** (see `UIVISUALS.md` §1).
- **2026-11-19** — Canvas bags landed; bag ring + overlap fixes; naming settled
  (`canon.KINDS`); `link.py` cross-connect; `NODE_TYPES`-driven canvas; tool layer knows the
  entity kinds; `Correspondent.key = person:<canonical>`; `run_cypher` word-bounded write
  guard; live store rebuilt; three email drop-in path bugs fixed; `sample_writer` fuzz +
  timing + bodies + email folders.
- **2026-11-18** — Docs consolidated; `sample_writer` finished; `canon.py` flattening pipe
  wired into the Correspondent write (Owner is no longer a Correspondent); thread titles
  `Platform; Name; MM-DD-YYYY->`; store wiped and rebuilt; Viewer cleanup; WhatsApp dedupe +
  HTML correspondents; `.eml` mailboxes discoverable.

---

## Root-doc retirement — §0 has landed

| File | Fate |
|---|---|
| `entity_list_brief.md` | **Delete.** Input to a job, not a fact about the app. |
| `temp-lists` | **Delete.** Its content now lives in `extract.py` / `products.py`. |
| `rework_extraction.md` | **Retired stub.** Extraction is closed; only GLiNER (optional) is left. Kept so old links resolve. |
| `detacheable_graph.md` | Keep until §1 (portable module) is built, then fold into `TECHREADME.md`. |

That leaves the five that earn their place: `README.md` (human overview), `TECHREADME.md`
(durable facts), `UIVISUALS.md` (rendering facts), `HANDOVER.md` (now and next), and
`archive_docs/`.

**Before deleting anything, check nothing links to it:**
```bash
grep -rn "<filename>" --include=*.md . | grep -v node_modules
```
A dangling link in `TECHREADME.md` §12 or `README.md`'s doc table is the usual casualty —
both were updated when `CytoGravityRecommend.md` was folded in.
