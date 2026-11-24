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
| **Correspondent** | `(:Correspondent {key, …})`, key `person:<canonical>` | The other party. A fact from the export. Folded across platforms by name at write time, then by phone / email / name in `link.py`. | Not one human across platforms (that is `link.py`). Not an extracted entity. |
| **Platform** | `platform` property on every node; `_PLATFORMS` in `tools.py` | The source: `telegram`, `messenger`, `email`, `linkedin`, `whatsapp`, `outlook`, `sms`. | Not the export file. Not the provider — Outlook-over-IMAP is `email`. |
| **Thread** | `(:Thread {key, platform, title, is_group})` | One conversation. | Not a message. |
| **Message** | `(:Message {key, platform, chat_id, message_id, …})` | One message. | Not a thread. |

Ingest path — three more, not interchangeable: **Download** (the user's file, never moved),
**Export** (`IngestResult.export_path`, the copy in `spool/` that gets parsed), **Spool**
(`paths.real_dir()`, **one queue** — a sample is just a file dropped in it).

**Not terms yet:** `Person`, `Place`, `Organization`, `Product` name a future extraction
step — the queries exist (§4) but no writer fills them, so they hold zero rows.
`resolution.collect/merge` **are** called and their counts land in the report, then the
result is discarded.

**The kind names are the node type names, lowercased.** `canon.KINDS` is
`("person", "organization", "place", "product")` and `tools.ENTITY_KINDS` is derived
from it. `thing` and `company` are gone; `canon.canonical()` raises on an unknown kind
rather than falling through to the `person` branch.

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
| `ingest.py` | The pipeline: `_parser_for()`, `detect_platform()`, `discover()`, `parse_batches()`, `ingest()`, `preview()`, `stage()`, `_drop_spam_threads()`. Extraction runs at the end of each batch; `delta=True` is the default. |
| `writer.py` | Cypher writer. `write()` (UNWIND 500), `write_correspondents()` + `_reconcile()` + `_contact_ids()`, `write_entities()`, `thread_display_title()`, `verify_present()`, `handles_from()`, `_ENTITY_WRITE_KINDS`. |
| `canon.py` | The flattening pipe. `canonical(raw, kind=…)` → `Canonical`; `KINDS`, `NICKNAMES`, `candidates()`, `nickname_form()`, `score()`, `fuzzy_available()`. Knobs `NICKNAME_ENABLED`, `FOLD_ON_NAME`, `FUZZY_REPORT`. |
| `extract.py` | **Entity extraction — proposes spans, decides no merge.** `extract()`, `places()`, `organizations()`, `fragments()`, `_arbitrate()`, `Mention` (with `candidates`), `PLACE_DICTIONARY`, `ORG_DICTIONARY`, `PRODUCT_ENABLED`, `DOCUMENT_CHARS`. |
| `products.py` | **The product vocabulary.** `INDEX` (92 entries), `GENERIC` block list, `lookup()`, `has_context()`, `decide()` — the four-rule ladder. `canon` folds spellings; this decides whether a spelling is a name. |
| `link.py` | **Cross-connect.** `link(conn)` — union-find fold over phone / email / name / fuzzy. Runs once at the end of `ingest()`. Owns `merged_by`. |
| `scrub.py` | `Verdict` (keep/hide/block), `AliasMap` (memory-only), Luhn check. |
| `identity.py` · `manifest.py` | Who the **Owner** is (with `tz_offsets`) · what has been ingested (sampled fingerprint, a shortcut never the authority). |
| `tools.py` | **The tool layer.** Schema from each signature. `DRAWABLE_NODE_TYPES` / `DRAWABLE_EDGE_TYPES` derive from the write table filtered by `PRODUCT_ENABLED`, never hand-listed. `_NODE_QUERIES`, `_EDGE_QUERIES`, `_SORTS`. |
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
| `components/GraphCanvas.jsx` | Cytoscape + fcose. **Icons are the only node look.** Stylesheet traps: [`UIVISUALS.md`](UIVISUALS.md). |
| `components/Viewer.jsx` | Two states, Back, budgeted loads, per-thread search, paging. |
| `components/ChatPanel.jsx` · `CommandBar.jsx` | Ollama chat with tool trace · the title bar. |
| `components/modals/` | `Modal.jsx` (+ `Slider`/`Check`/`TextField`, each with a hover `hint` and a visible `note`), then the five the title bar opens: **Log**, **Ingest**, **Canvas**, **Gravity**, **Utilities**. All are side-docked (`side`) so the graph stays visible. `SetupModal.jsx` exists but is not mounted. |
| `config/theme.js` · `nodeTypes.js` | **Every tunable**, with only the user's *overrides* persisted · `NODE_TYPES` (the single declaration of a kind), platform colours, icons, placeholders. See [`UIVISUALS.md`](UIVISUALS.md) §10. |
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
parse_batches(...)   ingest(*, which="real", delta=True, ...) -> Report
preview(...) -> dict   stage(paths_in) -> list[Path]   detect_platform(path)

# relate_comms/extract.py — proposes spans, merges nothing
extract(rows) -> list[Mention]        places(body) / organizations(body)
fragments(body) -> list[Fragment]     # `<br>` split; offsets index the ORIGINAL body
_arbitrate(text, label, body) -> (kind, candidates)

# relate_comms/products.py — the four-rule ladder, no weights
products.decide(text, body) -> (bool, reason)
products.lookup(text) -> ProductEntry | None     products.has_context(body) -> bool

# relate_comms/writer.py
write(conn, result, *, owner=None) -> dict[str, int]   # UNWIND, BATCH_SIZE = 500
write_correspondents(...)   write_entities(conn, mentions, *, message_meta, kinds)
_reconcile(cur, keys)       thread_display_title(chat, owner=None)   verify_present(...)

# relate_comms/canon.py — the flattening pipe
canonical(raw, *, kind="person", owner=None) -> Canonical
candidates(...)   nickname_form(raw)   score(a, b)   fuzzy_available()
KINDS = ("person", "organization", "place", "product")

# relate_comms/link.py — cross-connect, once per ingest
link(conn, *, fold_on_name=None) -> dict   # {folded, merged_by, groups, entities}
```


## 4. Schema (what exists today)

```cypher
(:Thread        {key, platform, title, is_group})
(:Message       {key, platform, chat_id, message_id, ts_utc, body,
                 has_attachments, is_self, sender_name, sender_id, raw_kind})
(:Attachment    {key, filename_scrubbed, mime, sha256, size})
(:Correspondent {key, display_name, platform, platforms, platform_label,
                 first_seen_utc, merged_by, email, phone_e164,
                 handle_<platform>, seen_<platform>})
(:Place         {key, display_name, platform, platforms, platform_label,
                 first_seen_utc, merged_by, mention_count,
                 handle_<platform>, seen_<platform>})
(:Organization  … same shape as Place)
(:Product       … same shape as Place)

(:Message)-[:IN]->(:Thread)        (:Message)-[:REPLY_TO]->(:Message)
(:Message)-[:HAS_ATTACHMENT]->(:Attachment)
(:Thread)-[:WITH]->(:Correspondent)
(:Message)-[:MENTIONS]->(:Place | :Organization | :Product)
```

**Five edge types, and no more.** `REPLY_TO` is declared and written by nothing. There is
no `POSSIBLY`: a fuzzy spelling pair folds like every other pair, and both endpoints of an
entity edge are `Message`, so `Thread → Entity` is a projection, not an edge — see below.

**The store holds facts, not summaries.** `(message)-[:MENTIONS]->(entity)` and
`(message)-[:IN]->(thread)` are what actually happened; "this thread is about Grafana" is
computed at read time by `tools._EDGE_QUERIES` as a two-hop `MATCH (t:Thread)<-[:IN]-(m)
-[:MENTIONS]->(e)`. That is the triple model another graph engine would accept — do not
let `_EDGE_QUERIES` become the schema.

**All three entity kinds share one write path.** `writer._ENTITY_WRITE_KINDS` maps kind to
store label; the fold, `mention_count`, the `MENTIONS` edge and `_reconcile` are identical.
`mention_count` is **message-based** (not thread-based) since 2026-11-23.

**`Product` is gated by `extract.PRODUCT_ENABLED`.** Off returns the graph to Place+Org with
no rebuild: the index stops promoting spans and `DRAWABLE_*` drops `Product`.

**`Correspondent` is keyed `person:<canonical>`.** Two spellings of one name on one
platform already collapsed via `canon`; dropping the platform prefix means the same
canonical name on two platforms is now **one node** with a `WITH` edge per thread.
Placeholders keep their platform prefix (`messenger:placeholder:facebook user`) so
`Facebook user` and `LinkedIn Member` never fold into one node.

| Property | Rule |
|---|---|
| `platform` | the **first** platform by date — a single string, because the filter reads it |
| `platforms` | every platform, date order. **The filter reads this list.** |
| `platform_label` | `Telegram-WhatsApp-Fcbk Mssgr`, same order |
| `first_seen_utc` | earliest message timestamp across platforms |
| `merged_by` | why a fold happened: `fuzzy` / `exact_name` / `nickname` / `phone` / `email`, or `same_name` when two platforms met under one key with **no fold at all**. `link._fold` owns it. |
| `handle_<p>` · `seen_<p>` | that platform's spelling and first sighting, stored **flat** |

**`primaryPlatform` and `dominance` are query-time, not stored.** `graph_slice`
returns them on every Correspondent: `primaryPlatform` is the platform with the most
**messages**, `dominance` is its share (0.0–1.0). They are deliberately *not* the same
as `platform` — that is first-by-**date**, so the filter and label never drift between
ingests. Measured on the sample store: 17 of 34 merged nodes lean toward a platform
other than their first-by-date one, so the two fields carry different information.

**They are not a layout input.** A merged node is pulled **equally** by every platform
it touches; the dominance leash was designed and then withdrawn. See
[`UIVISUALS.md`](UIVISUALS.md) §8.

**`graph_slice` also returns `merged`** (the `:Merged` label as a boolean) on every
Correspondent. The canvas uses it as the bag-membership test, inverted.

`:Merged` is an additive label on a node spanning more than one platform. It is
filtered out of `types_present()` — it is a marker, not a node type.

**Relate rejects map properties** (`InvalidPropertyType`), so `handles` is stored as
`handle_<platform>` and assembled by `writer.handles_from()` at the API edge.

**Relate evaluates every row of an `UNWIND` against the node as it stood before the
statement.** Accumulating in Cypher therefore cannot work — the last row wins. The
row statement writes only per-platform facts; `writer._reconcile()` computes the
derived properties afterwards.

**Queryable but empty — the queries exist, the rows do not:** `Person`
(`tools.ENTITY_KINDS`). A person extracted from a body would compete with the
`Correspondent` already on the thread, so it is documented but never written.

**Designed but unwritten — do not query against these:** `Identity`, `MATCHED_BY`,
`SENT`, `Draft`.

**Cross-connect is `relate_comms/link.py`, run once at the end of `ingest()`.** It folds
the nodes whose keys differ — a phone-only contact onto a named one — by union-find over
phone / email / name / **fuzzy**, re-pointing every `WITH` or `MENTIONS` edge before the
loser is deleted, then `writer._reconcile()` rebuilds `platforms` / `platform_label` /
`:Merged`. The fuzzy rung is blocked on the surname's first letter and is **last**, so a
pair that folds on phone never reports itself as fuzzy. Two places a letter apart stay two
places — entities use `exact_name` only.

**A named contact's phone or address comes from `sender_id`,** recorded by
`writer._contact_ids()` — only when the value actually is a phone or an address. Without
it a phone fold has nothing to compare, because a sender field is a name.

**Fold knobs live in `canon.py`:** `NICKNAME_ENABLED` (honoured by the pipe itself, since
a nickname is resolved into the *key* at write time) and `FOLD_ON_NAME`.

### Thread title schema — LOCKED

```
<Name>; <MM-DD-YYYY>[-][>][ #n]
```

| Case | Example |
|---|---|
| 1:1, single day | `Bryan Rodgers; 06-02-2026` |
| 1:1, spans days | `Ryan Phillip; 02-13-2025->` |
| Group | `Come to Africa; 10-25-2026->` |
| With subject | `n8n Hackathon today - log in!🪐; 08-16-2025` |
| Same person, same start date | `Ryan Phillip; 02-13-2025-> #2` |
| Name contains a date | `Invoice due 08-16-2025; 08-16-2025` |
| No messages | `Mary Olver` (second `;` omitted) |

**Parse from the outside in:** date block after the **last** `;`, name before it.

**No platform token** (removed 2026-11-24). It spent the widest part of a canvas label on
a fact the node already carries — the glyph is platform-coloured and the Viewer draws a
platform pill beside the title.

**Why `;`:** measured across 500 real titles — `;` 0 occurrences, `[`/`]` 0, `->` 0, `#` 0,
`|` 3, `-` 6. `-` collides on day one; `;` does not.

**Why `->` not an end date:** an end date changes on every ingest because `max(ts)` moves.
`->` changes at most once, ever.

**`#n` by date collision only**, ordered by `chat_id`, never ingest order.

**Display only.** Never parse the title for the platform key; query the `platform` property.
The title no longer contains one at all.

### Naming — settled

| Use | Not |
|---|---|
| `Organization` | `Company` |
| `Product` | `Thing` |
| `Person` (extraction only, never the Owner) | — |

`canon.KINDS` is the single source; `tools.ENTITY_KINDS` derives from it. An unknown kind
raises rather than falling through to the `person` branch. `Company` appears nowhere.

## 5. Body-entity extraction

**Three kinds — Place, Organization, Product — one pipeline.** The order never changes:

```
extract per message  ->  fold within a platform  ->  match across platforms
     extract.py              canon.canonical()          link.link()
```

**The dictionaries ARE the feature.** `en_core_web_sm` has no gazetteer — it is a neural
net guessing from sentence shape. It labels `Austin` a person, `Grafana` a person,
`Databricks` a place, and `"Ansible keeps falling over."` as nothing at all while
`"I've moved everything onto Ansible."` is a `PRODUCT`. It *does* have a `PRODUCT` label;
it is just frame-sensitive and mostly absent. So three hand-written lists run **before**
the model and win: `PLACE_DICTIONARY` (97), `ORG_DICTIONARY` (26), `products.INDEX` (92).

**`products.decide()` is four rules, first match, no weights:**

| # | Rule | Outcome |
|---|---|---|
| 1 | `GENERIC` (`seat`, `contract`, `credits`, `sla`, `rack`, `switch`…) | **never** a product |
| 2 | not in `INDEX` | no |
| 3 | indexed, `requires_context=False` | **yes** |
| 4 | indexed, `requires_context=True` | yes iff the body has a procurement cue |

**The generic block lives here, not in `canon`.** `canon` folds `Seat` and `seat` to one
key — correct, it is a spelling function. Only the index can say one is a licence concept
and the other is furniture. **Hiding cannot replace it:** common nouns get *more* mentions
than rare products, so a mention floor promotes junk instead of suppressing it.

**`_arbitrate()` may overrule the model, asymmetrically.** `GPE`/`FAC`/`LOC` and
`PERSON` may become `Product`; `ORG` may **not** — `Grafana Labs` the company contains
`Grafana` the product, and demoting it would lose a true fact. A `PERSON` span is dropped
unless the index recognises it, which is how `Grafana` is rescued without making `Dave` a
product.

**`<br>` fragmentation runs first.** Messenger and WhatsApp exports concatenate turns;
149 bodies in the sample store do. Parsing them whole let a dictionary name abut a tag and
mint `organization:abc corp?<br>`. Splitting gives 28 → 33 mentions and zero spans
containing markup. `fragments()` returns offsets into the **original** body, so a
`Mention.start` still points at the stored text and no fragment id travels downstream.

**`DOCUMENT_CHARS = 2000`** (4× p99). One 11,719-char marketing newsletter produced every
junk Organization we ever saw. Reported as a warning, never an error.

**No LLM in this path.** spaCy and rules only. The local model is a chat feature.

## 6. Invariants — break these and things fail silently

| Invariant | Why |
|---|---|
| `Message.key = platform:chat_id:message_id` | Makes re-ingest idempotent. Never an array index or timestamp. |
| Canvas bags are `synthetic` | A bag is a layout body, not data. `cy.nodes().length` includes them, so nothing may use that raw — the reveal, `onLayoutDone` and every count filter `.synthetic`. |
| Bag membership is `:Merged`, inverted | The label, not `platforms.length`. A node with one platform goes in that platform's bag; everything else goes in the central merged bag. A length test would bag the world's geography. |
| `ts_utc` everywhere | Telegram/WhatsApp/Messenger export wall-clock with no offset. |
| **A platform is a source, not a provider** | `outlook` is a `.pst`; Outlook-over-IMAP is `email`. Different provenance, different keys. |
| **A merged node is filtered on `platforms`, never `platform`** | `platform` is one string (first by date). Testing it hides a merged node whenever the user filters by any other platform. |
| **Derived Correspondent properties are computed after the rows land** | Relate reads every `UNWIND` row against the pre-statement node, so accumulating in Cypher lets the last row win. |
| **A kind name is a node type name, lowercased** | `canon.KINDS` drives `tools.ENTITY_KINDS`. An unknown kind raises — the pipeline's last branch is `person`, so a typo would silently strip credentials off a product name. |
| **The owner is never a Correspondent** | An adapter that knows the owner must prune them from `participant_names` under both forms. |
| **The tz offset is part of the key** | `ts_utc` hashes into the key. Stored per platform; changing it on a populated store is refused. |
| `MERGE` on `key`, never `CREATE` | Re-ingest must not duplicate. |
| Every title has a fallback, never empty | `writer.thread_display_title()`. |
| One writer per `.rl` file | Concurrent writers are corruption. Hence parallel parse → serialised write. |
| Truncation is never silent | Any tool hitting `limit` returns `truncated: true`; `graph_slice` also returns `total`. |
| **Canvas toggles never narrow a query; Utilities does, deliberately** | Canvas hides clusters and silent threads — drawing only, reversible, still searchable. The **Utilities** platform filter is different: it is module state in `tools.py` (`configure_platforms`), so it narrows `graph_slice`, `search_messages` and the AI chat alike. That overrides the older blanket rule on purpose; the alternative is a per-call `platforms` argument. |
| **Icons are an override layer, never the base** | A platform with no icon file keeps the base fill and stays visible. |
| **Cytoscape 3.35 has no `shadow-*`** | Removed with the WebGL rewrite; glows are `underlay-*` radial gradients. A removed property fails silently. [`UIVISUALS.md`](UIVISUALS.md) §1. |
| **A style value that fails to parse kills the whole stylesheet** | 8-digit hex and `data()` on an empty string both do it. The app goes black, not just the node. [`UIVISUALS.md`](UIVISUALS.md) §3. |
| `write_enabled` and `platforms` are excluded from tool schemas | They are the surface's toggles, not something a model may set. |
| **A dropped thread leaves no orphan messages** | Any parse-time gate runs before the rows are committed and before the `Chat` is appended. |
| **Legs are independent — any subset, any order, any number of runs** | Every write is a `MERGE`, so ingesting SMS into a five-platform store adds rows and touches nothing else. |
| **A parse-time gate is per platform, never global** | `_kwargs_for()` pops a keyword an adapter does not accept, so adding a platform never means adding a no-op argument. |
| **Credentials are never readable by a tool** | `.env` is read only by `email_imap._dotenv()`. `tools.py` has no environment access. |
| **The duplicate stamp is a shortcut, not the authority** | `ingested.json` lets the UI say "already ingested". `verify_present()` still decides pruning. |
| **A drawable type list is derived, never hand-written** | `DRAWABLE_NODE_TYPES` and `DRAWABLE_EDGE_TYPES` follow `writer._ENTITY_WRITE_KINDS` filtered by `PRODUCT_ENABLED`. An edge is kept only when **both** endpoints are drawn, so a kind missing from the node list silently erases every edge it has — this happened to `Product` and the canvas showed zero. |
| **A `MENTIONS` edge hangs off the Message** | `Thread → Entity` is a projection in `_EDGE_QUERIES`, not stored. Re-anchoring it means teaching `link._fold` the new source too — it re-points a loser's edges by pattern, and the wrong pattern matches nothing and then `DETACH DELETE` takes everything left. |
| **Never trust a rebuild through a running server** | Modules cache in the process. A wipe + ingest through a stale server writes a store matching neither the old code nor the new, and reports success. Restart, then rebuild. |
| **No adapter reads media** | A huge download costs the copy, not the parse — which is why size is a warning, not a refusal. |
| **A WhatsApp chat downloaded both ways is one thread, not two** | `_chat_id()` hashes the chat *title*; `message_key()` truncates to the **minute**. Measured: 46 of 47 keys identical. |
| **A failed leg restarts, it does not resume** | Continue re-runs the whole ingest without the failed leg. |
| **Truncating the graph always truncates the manifest** | Left behind, the next ingest skips every file it has seen and produces an empty graph that looks successful. |
| **A redirected store redirects the profile** | `ingest(store=…)` puts the manifest and tz offsets beside that store unless `profile_dir` is given. |
| **Detection must see inside a container it can parse** | `sms.detect()` reads the decompressed `.xml` member of a `.xml.zip`, not the zip's raw bytes. |
| **A platform with two dialects is routed per file, not per platform** | Both WhatsApp dialects report `whatsapp`, so `_parser_for()` decides. Asserting on `detect_platform()` alone passes while the file goes to the wrong adapter. |
| **A recognised directory is one batch, not one per file** | `discover()` offers a folder to `detect_platform()` first and emits it whole if claimed. Messenger and Telegram resolve thread ids from the archive-relative path, so handing them a single `message_1.html` makes each batch parse the *whole* export — measured at 29 batches and 18,330 messages to write 611. |
| **`detect_platform()` answers for a directory too** | `discover()` needs to know whether to emit a folder or walk into it. Only the adapters that can read a folder are consulted (messenger, linkedin, whatsapp_html, `_detect_whatsapp`). |

## 7. Ingest — the modal and its gates

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

## 8. Commands

```bash
python -m app                    # http://127.0.0.1:8100
start.bat                        # Windows: opens browser + server

python -m relate_comms ingest --email hostinger --tz-offset -5
python -m relate_comms ingest "C:/Users/me/Downloads/chat.zip" --tz-offset -5

python -m sample_writer                  # fake downloads -> sample_writer/out/
python -m sample_writer add --seed 5     # write alongside out/, no clobber

python -m pytest tests -q        # 400 passed, 2 skipped

npm install && npm run build     # -> app/static/dist/app.js
npm run watch                    # rebuild on save, no server
node scripts/vendor.mjs          # re-copy cytoscape + fcose
python tools/bench_scale.py --n 20000
```

**No `--reload`.** The editor auto-saves every few seconds, so a watcher restarts the
server mid-request; it also watches the whole repo, so `pytest` makes it thrash.

### Changing a UI default — edit, rebuild, hard-refresh

**No version bump, no `localStorage` clearing.** Only the user's *overrides* are stored
(`relate.graphStyle.overrides`), as a diff against the defaults. A key the user never
touched is not in storage, so it always follows `theme.js`.

**Checklist for a visual change:**

1. Edit `theme.js` (or `GraphCanvas.jsx` for stylesheet rules).
2. **Rebuild** — `npm run watch` does it on save; otherwise `npm run build`.
3. Hard-refresh the browser.

Step 2 is unavoidable: `theme.js` is bundled into `app/static/dist/app.js` by esbuild, so
the browser cannot see the edit until the bundle is rebuilt. `start.bat` also rebuilds on
every launch.

**Why the old design failed.** It saved the whole theme object and merged it back over the
defaults, so a saved value shadowed every later edit — which is why a `THEME_VERSION`
constant existed, and why forgetting to bump it made edits silently do nothing. Storing a
diff removes the whole class of bug.

If a value still does not appear, the user has overridden that key: reset it in the Canvas
modal, or `localStorage.removeItem("relate.graphStyle.overrides")`.

## 9. Debugging

| Symptom | Check |
|---|---|
| Canvas empty, API fine | `curl /api/graph?limit=5` — if it returns nodes, the failure is in the UI. |
| Everything renders as squares | A Cytoscape selector matched too broadly. `[key]` tests field **existence**. |
| Render dies after first paint, or the app goes black | A style value parsed to `null` — `background-image: data(x)` on an empty string, or 8-digit hex. [`UIVISUALS.md`](UIVISUALS.md) §3. |
| A glow does nothing | `shadow-*` does not exist in 3.35. Use `underlay-*`. [`UIVISUALS.md`](UIVISUALS.md) §1. |
| **A theme edit does nothing** | The bundle was not rebuilt — `theme.js` is compiled into `app.js`. Run `npm run build` (or keep `npm run watch` on) and hard-refresh. §8. |
| **One theme value ignores `theme.js`** | The user has overridden that key; only overrides are persisted. Reset it in the Canvas modal. §8. |
| Thread shows 0 messages | The tz offset differs from the one the store was written with. |
| A route 404s after a rename | The Python server is stale — it loads routes once at startup. Restart it. |
| Blank page, no console clue | A `const` inside a `useMemo` referenced in its dependency array throws `ReferenceError` every render. |
| Chat answers a different question | Tool result exceeded `MAX_TOOL_CHARS` (4,000). Summarised, not silently cut. |
| Chat is very slow | `think: false` not applied. Thinking is ~28× slower on this box. |
| Port 8100 "already in use" | `netstat -ano \| findstr :8100`, then `taskkill /PID <pid> /F`. |
| Ingest reports 0 messages but exits 0 | `verify_ingest` is the check that matters. |

## 10. Relate / Neo4j

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

## 11. Local tools on this machine

| Tool | Where | Note |
|---|---|---|
| Ollama | `127.0.0.1:11434` | `lfm2.5:8b` default (MoE, ~21 tok/s CPU), `qwen3.5:4b` fallback, `embeddinggemma` for vectors. **`think: false` is a 28× speedup.** |
| Python | 3.11+ | `pip install -e ".[resolve,app]"` |
| Node | 22+ | Only for UI builds. `dist/app.js` is committed. |
| Relate | pip | Embedded; one `.rl` file. |

Ports in use: **8000 is taken** by another app — this project uses **8100**.

## 12. Where the rest of the detail lives

| Topic | File |
|---|---|
| **Settled UI and visual facts** — glows, colour parsing, stylesheet order, the merged-node template, bags, and what fcose actually honours | [`UIVISUALS.md`](UIVISUALS.md) |
| What is still moving in extraction, what was measured, what was declined | [`rework_extraction.md`](rework_extraction.md) |
| The sample generator — every knob, the pools, the fuzz axes | [`sample_writer/README.md`](sample_writer/README.md) |
| The test payloads, and how to wire a new export format | [`tests/README.md`](tests/README.md) |
| The generator spec — every shape the app has a switch for | [`archive_docs/UNDESIRABLES.md`](archive_docs/UNDESIRABLES.md) |
| Per-platform export shapes and traps | [`archive_docs/MssgDownloadInstructs.md`](archive_docs/MssgDownloadInstructs.md) |
| Ollama on this machine | [`archive_docs/HowToRunOllama.md`](archive_docs/HowToRunOllama.md) |
