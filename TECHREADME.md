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

**Extracted kinds are live.** `Place`, `Organization` and `Product` are written by the
pipeline and drawn on the canvas (§4). `Person` is extracted but **not wired** — a person
drawn from a body competes with the Correspondent already on the thread, which is a merge
with a wrong answer that looks right.

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

The store key is `messenger` and must stay that way — it is part of every `Message.key`. The
UI shows **Fcbk Mssgr**, never bare "Messenger", which reads as "a message" beside a
`Message` node. `outlook` is its own platform, not a variant of `email`: a `.pst` and a live
mailbox have different provenance. **There is no `gmail` or `imap` platform** — a Gmail
mailbox is `email` with `imap.gmail.com` as its host.

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
| `paths.py` | `spool_dir()`, `real_dir()`, `store_path()`, `profile_dir()`, `ensure_layout()`, `SPOOL_SCAFFOLD` + `ensure_spool_scaffold()`. |
| `ingest.py` | The pipeline: `_parser_for()`, `detect_platform()`, `discover()`, `parse_batches()`, `ingest()`, `preview()`, `stage()`, `_drop_spam_threads()`. Extraction runs at the end of each batch; `delta=True` is the default. |
| `writer.py` | Cypher writer. `write()` (UNWIND 500), `write_correspondents()` + `_reconcile()` + `_contact_ids()`, `write_entities()`, `thread_display_title()`, `verify_present()`, `handles_from()`, `_ENTITY_WRITE_KINDS`. |
| `canon.py` | The flattening pipe. `canonical(raw, kind=…)` → `Canonical`; `KINDS`, `NICKNAMES`, `candidates()`, `nickname_form()`, `score()`, `fuzzy_available()`. Knobs `NICKNAME_ENABLED`, `FOLD_ON_NAME`, `FUZZY_REPORT`. |
| `extract.py` | **Entity extraction — proposes spans, decides no merge.** `extract()`, `places()`, `organizations()`, `fragments()`, `_arbitrate()`, `Mention` (with `candidates`), `PLACE_DICTIONARY` (691), `ORG_DICTIONARY` (585), `PRODUCT_ENABLED`, `PRODUCT_RESCUE_LABELS`, `DOCUMENT_CHARS`. |
| `products.py` | **The product vocabulary.** `INDEX` (764 entries), `GENERIC` block list, `lookup()`, `has_context()`, `decide()` — the four-rule ladder. `canon` folds spellings; this decides whether a spelling is a name. |
| `link.py` | **Cross-connect.** `link(conn)` — union-find fold over phone / email / name / fuzzy. Runs once at the end of `ingest()`. Owns `merged_by`. |
| `scrub.py` | `Verdict` (keep/hide/block), `AliasMap` (memory-only), Luhn check. |
| `identity.py` · `manifest.py` | Who the **Owner** is (with `tz_offsets`) · what has been ingested (sampled fingerprint, a shortcut never the authority). |
| `tools.py` | **The tool layer.** Schema from each signature. `DRAWABLE_NODE_TYPES` / `DRAWABLE_EDGE_TYPES` derive from the write table filtered by `PRODUCT_ENABLED`, never hand-listed. `_NODE_QUERIES`, `_EDGE_QUERIES`, `_SORTS`. Search: `search_fulltext` (BM25, default), `search_vector` (semantic), `search_messages` (legacy substring scan), `embed_status`, `embed_messages`. |
| `models.py` · `cli.py` | Ollama model choice (`THINK = False`) · `python -m relate_comms`. |
| `adapters/` | `parse(export_path, **kw)` + `detect(path)`. Built: `telegram`, `whatsapp`, `whatsapp_html`, `messenger`, `linkedin`, `email_imap`, `outlook_pst`, `sms`. **WhatsApp has two dialects** — native `chat.txt` and the extension's HTML — both reporting `whatsapp`; `_parser_for()` picks per file. |

### App — `app/`

| File | Role |
|---|---|
| `main.py` | FastAPI app, `ToolError` → 400, static mount, `/` serves `index.html`. |
| `routers/system.py` | `/api/health`, `/stats`, `/types`, `GET|POST /platforms`. |
| `routers/graph.py` · `search.py` · `chat.py` | `/api/graph`, `/api/thread/{key}`, `/api/message/{key}` · `POST /api/search` · Ollama loopback, one tool round. |
| `routers/ingest.py` | `/api/ingest` (**returns a job id**), `/upload` (file or folder picker → spool), `/preview` (read-only: size + duplicate), `/env` (what is saved, **never the password**), `/truncate` (destructive), `/verify`, `/prune`, `/jobs/{id}`. |
| `jobs.py` | The job registry. `start()` runs work on a thread and returns immediately; `status()` reports it. One job at a time. Exists because an ingest holds the store for its whole duration (Relate is single-writer) and every other surface would otherwise fail with `storage locked`. |
| `mcp/` | **The MCP surface.** `config.py` (two keys, path rule, heartbeat, activity trace), `server.py` (allowlist, `_bind`, ingest guard), `__main__.py` (`python -m app.mcp`). §13. |
| `__main__.py` | `python -m app`, default port **8100**. |

### UI — `app/ui/src/`

React 19 + esbuild. `dist/app.js` is **committed** so a clone runs without npm.

**The UI is its own guide:** [`UIREADME.md`](UIREADME.md) — component map, the five modals,
the activity trace, the badge, and every Cytoscape/fcose trap that cost a day each.

What matters from the backend's side: `theme.js` holds every tunable and only the user's
*overrides* are persisted; `nodeTypes.js` is the single declaration of a kind; `api.js` is
the only server call site. **`npm run build` after any `.jsx`/`.css` edit** — `theme.js` is
compiled into the bundle.

## 3. Schema and the tool layer

**Moved to [`SCHEMA.md`](SCHEMA.md)** — the store's data model (every node and edge type,
the property rules, the locked thread-title format) and the 19-tool registry with its three
bindings.

That file is the one to read before writing a query or adding a tool. This one covers the
pipeline that fills the store.

## 4. Body-entity extraction

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
the model and win: `PLACE_DICTIONARY` (691), `ORG_DICTIONARY` (585), `products.INDEX`
(764).

**Three bugs the list load exposed, all fixed:** a short entry truncated a longer name
(`Kensington Market` → `place:kensington`); products were never in the ruler, so
`Toyota Hilux` split into an ORG and a PRODUCT; and `NORP` was dropped outright, so
`a Persian rug` produced nothing. `NORP` now sits in `PRODUCT_RESCUE_LABELS` beside
`PERSON`.

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

## 5. Invariants — break these and things fail silently

| Invariant | Why |
|---|---|
| `Message.key = platform:chat_id:message_id` | Makes re-ingest idempotent. Never an array index or timestamp. |
| `ts_utc` everywhere | Telegram/WhatsApp/Messenger export wall-clock with no offset. |
| **A platform is a source, not a provider** | `outlook` is a `.pst`; Outlook-over-IMAP is `email`. Different provenance, different keys. |
| **A merged node is filtered on `platforms`, never `platform`** | `platform` is one string (first by date). Testing it hides a merged node whenever the user filters by any other platform. |
| **Derived Correspondent properties are computed after the rows land** | Relate reads every `UNWIND` row against the pre-statement node, so accumulating in Cypher lets the last row win. |
| **A kind name is a node type name, lowercased** | `canon.KINDS` drives `tools.ENTITY_KINDS`. An unknown kind raises — the pipeline's last branch is `person`, so a typo would silently strip credentials off a product name. |
| **The owner is never a Correspondent** | An adapter that knows the owner must prune them from `participant_names` under both forms. |
| **The tz offset is part of the key** | `ts_utc` hashes into the key. Stored per platform; changing it on a populated store is refused. |
| `MERGE` on `key`, never `CREATE` | Re-ingest must not duplicate. |
| Every title has a fallback, never empty | `writer.thread_display_title()`. |
| One writer per `.rl` file | Concurrent writers are corruption. Hence parallel parse → serialised write. **A reader also takes a lock**, so an ingest holds the store for its whole duration and every other surface fails with `storage locked`. Hence the **job registry** (`app/jobs.py`): `POST /api/ingest` returns a job id in ms, the work runs on a thread, and callers poll `GET /api/jobs/{id}`. One job at a time; a second is refused, not queued. `tools._connect()` also retries for ~2.75 s to clear the app's own short reads. |
| **A variant tree stages one artifact per platform** | `sample_writer/out/` holds several packagings of the same conversations; ingesting two stores every message twice. `ingest._canonical_children()` takes `email_eml`, `linkedin_zip`, `messenger_zip`, `sms_xml`, `Telegram Desktop`, `whatsapp_html` — and **not** `outlook_copy`, because a `.pst` is a copy of the committed fixture. The rule fires only when a folder holds **two or more** known artifact names, and **the spool is never narrowed**. |
| Truncation is never silent | Any tool hitting `limit` returns `truncated: true`; `graph_slice` also returns `total`. |
| **Canvas toggles never narrow a query; Utilities does, deliberately** | Canvas hides clusters and silent threads — drawing only, reversible, still searchable. The **Utilities** platform filter is different: it is module state in `tools.py` (`configure_platforms`), so it narrows `graph_slice`, `search_messages` and the AI chat alike. That overrides the older blanket rule on purpose; the alternative is a per-call `platforms` argument. |
| **Every UI invariant lives in `UIREADME.md`** | Bags are `synthetic`, membership is `:Merged` inverted, icons are an override layer, `shadow-*` does not exist, a bad style value kills the stylesheet. Do not re-derive them here. |
| `write_enabled`, `platforms`, `extra_results` are excluded from tool schemas | They are the surface's toggles, not something a model may set. |
| **A dropped thread leaves no orphan messages** | Any parse-time gate runs before the rows are committed and before the `Chat` is appended. |
| **Legs are independent — any subset, any order, any number of runs** | Every write is a `MERGE`, so ingesting SMS into a five-platform store adds rows and touches nothing else. |
| **A parse-time gate is per platform, never global** | `_kwargs_for()` pops a keyword an adapter does not accept, so adding a platform never means adding a no-op argument. |
| **A credential is never returned** | `.env` holds only the four `IMAP_*` keys. MCP may use them (`ingest(email=["email"])` takes a mailbox name), but the values never appear in a response, a tool argument or the activity trace. |
| **The duplicate stamp is a shortcut, not the authority** | `ingested.json` lets the UI say "already ingested". `verify_present()` still decides pruning. |
| **A drawable type list is derived, never hand-written** | `DRAWABLE_NODE_TYPES` and `DRAWABLE_EDGE_TYPES` follow `writer._ENTITY_WRITE_KINDS` filtered by `PRODUCT_ENABLED`. An edge is kept only when **both** endpoints are drawn, so a kind missing from the node list silently erases every edge it has — this happened to `Product` and the canvas showed zero. |
| **A `MENTIONS` edge hangs off the Message** | `Thread → Entity` is a projection in `_EDGE_QUERIES`, not stored. Re-anchoring it means teaching `link._fold` the new source too — it re-points a loser's edges by pattern, and the wrong pattern matches nothing and then `DETACH DELETE` takes everything left. |
| **Never trust a rebuild through a running server** | Modules cache in the process. A wipe + ingest through a stale server writes a store matching neither the old code nor the new, and reports success. Restart, then rebuild. |
| **No adapter reads media** | A huge download costs the copy, not the parse — which is why size is a warning, not a refusal. |
| **Ingest never embeds** | Embedding is 42 msg/s on short bodies but 3 msg/s on long ones. A 200k store is hours. It is a separate opt-in pass (`embed_messages`), batched, stoppable, and only touches `m.emb IS NULL`. |
| **A search index is created on a writable connection** | `CREATE FULLTEXT INDEX` / `CREATE VECTOR INDEX` on a read-only connection fail with `WriteOnReadOnlyAccessDatabase`. The search tools open writable for the DDL and then run the read-only query on the same connection. |
| **A name is not in any message body** | `search_fulltext` and `search_vector` both call `_name_matches()`. Scanning bodies alone made a correspondent's name unfindable — measured: `Alicia Moreno` had 8 messages and zero bodies containing "moreno". |
| **A greeting is not a sentence** | `screen_body()` drops a body with no subject and no predicate before embedding. Those vectors are near-identical and crowd every semantic result. It **fails open** — no spaCy means embed everything. |
| **Nulling a property frees no disk** | Relate is append-only and has no compaction API. `SET m.emb = null`, `REMOVE m.emb` and `DROP INDEX` all leave the bytes. Only rewriting the store reclaims — `flush_embeddings()` does that, and it must replay `writer._SCHEMA` afterwards because a rebuild copies nodes and edges, **not indexes**. |
| **The flush rewrite is guarded by a fidelity test** | `test_flush_is_byte_identical_for_every_node_and_edge` diffs every node property and every edge before and after. It has already caught two real bugs. Change `flush_embeddings` only with that test green. |
| **A scratch store's name must end in `.rl`** | `graph.rl.flush` is read as a **directory** store: the rebuild writes into a folder and the swap produces an empty graph that reports success. Use `graph.flush.rl`. |
| **An unlabelled `MATCH (a {key: …})` scans every node** | Grouping edges by endpoint labels took a 3,183-edge rebuild from 83 s to under a second. |
| **A WhatsApp chat downloaded both ways is one thread, not two** | `_chat_id()` hashes the chat *title*; `message_key()` truncates to the **minute**. Measured: 46 of 47 keys identical. |
| **A failed leg restarts, it does not resume** | Continue re-runs the whole ingest without the failed leg. |
| **A fixed-name export is replaced, not skipped** | `Outlook.pst` and `email_eml/` never change their name, so a re-export collides. Skipping meant the new snapshot never landed and the ingest re-read the old one — the delta then found nothing new, forever, silently. |
| **The spool scaffold is one definition** | `paths.SPOOL_SCAFFOLD` — `real/<platform>/<artifact>/`, mirroring `sample_writer/out/`. `ensure_layout()` and `delete_spool()` both call `ensure_spool_scaffold()`, so a wipe leaves the scaffold rather than a skeleton of every directory any ingest ever created. |
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

**Modal, top to bottom:** Truncate (double confirm) → drop box (files or a folder, one or
many) → **ready list** → IMAP fields → separator → window / tz / groups / email spam →
Ingest → log (newest first).

**The ready list** is one line per top-level folder picked, with a shortened path
(`C:…\out\telegram\Telegram Desktop`), in orange. A root goes **red** when it is already
ingested or unrecognised. It clears the moment Ingest starts — it describes what is
waiting, not what is stored.

**Media is never copied.** No adapter reads it, so the upload route drops it before a byte
is written and `stage()` excludes it from `copytree`. Attachment *metadata* lives in the
export file, so nothing a message needs is lost. The modal reports the count skipped.

**The spool line** (`spool contains 4 exports: email, linkedin, …`) is an inventory, not a
warning. It used to read "N files are already ingested" in orange, which fired on every
open because the spool still holds what you just ingested.

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

**IMAP is one mailbox, four keys.** `IMAP_EMAIL/PASSWORD/HOST/PORT` in `./.env`. No provider
table and no host guessing — the host is a field the user fills in. Credentials are written
**only after the ingest succeeds**, so a wrong password leaves nothing behind. Switching the
address wipes the `email` rows first (the key carries no mailbox). Outlook/O365 killed basic
auth — the modal points at the `.pst` route.

**Email is IMAP only.** No mbox reader exists: a Gmail Takeout `.mbox` or a webmail `.eml`
zip is reported `unrecognised`, because `discover()` looks for the recognised artifact shapes
and `_EML_SUFFIX = ".eml"`. A folder of `.eml` is the one file shape accepted
(`email_imap.parse_eml`), on the same `email` platform and key space as IMAP.

**Both mail legs remember their newest stored message and skip everything at or before it.**
`apply_delta` never rewrites or deletes, so the rule only moves forward: a backdated message,
or a `.pst` re-exported with older mail added, is skipped as already-stored with no error. To
pull a mailbox backwards, run `delta=False` against an empty store.

**Switching mailboxes replaces the email leg.** `chat_id` carries no mailbox, so the key
namespace and the watermark are shared. The graph records which mailbox it holds in
`store/profile/imap.json` — written only by a verified run, deleted by a truncate — and
that record, not `.env`, decides whether a run is `first`, `same`, `window`, `different`
(wipe the `email` rows) or `stale` (record lost with rows present: refuse rather than
guess). Scoped to `email`; `outlook` and the other platforms are untouched.

**A failed leg** halts with the error named and offers *Exclude and continue* or *Cancel*.
Cancel does not roll back and does not need to — `MERGE` makes a re-run idempotent.

**The log is summaries, not per-file.** One line per platform (`email: 1,204 msgs · 88
attachments`), failures in red, one green verdict. A mailbox is 190 batches and a Messenger
export is 29; a line each turned the log into a wall nobody read.

**The canvas re-lays out after an ingest.** `onIngested` sets the same one-shot flag the
Re-run layout button uses, so the solver runs on the new nodes. Without it the new nodes
kept their seed positions and every edge to a bag stretched across the canvas.

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

python -m relate_comms ingest --email email --tz-offset -5      # the .env mailbox
python -m relate_comms ingest "C:/Users/me/Downloads/chat.zip" --tz-offset -5

python -m sample_writer                  # fake downloads -> sample_writer/out/
python -m sample_writer --seed 5         # wipe & write, seed 5
python -m sample_writer add --seed 5     # write alongside out/, no clobber
python -m sample_writer append           # same world, later END (delta testing)
python -m sample_writer clean            # wipe out/

python -m pytest tests -q        # 594 passed, 10 skipped, 0 failures

npm install && npm run build     # -> app/static/dist/app.js
npm run watch                    # rebuild on save, no server
node scripts/vendor.mjs          # re-copy cytoscape + fcose
python scripts/build_entity_icons.py   # regenerate the kind glyphs

# A full ingest from a shell. `ingest()` uses multiprocessing, which cannot re-import
# `__main__` from a heredoc on Windows — a real file is the only way.
python scripts/reingest.py [--delta]

python tools/bench_scale.py --n 20000
```

**No `--reload`.** The editor auto-saves every few seconds, so a watcher restarts the
server mid-request; it also watches the whole repo, so `pytest` makes it thrash.

### Changing a UI default — edit, rebuild, hard-refresh

**No version bump, no `localStorage` clearing.** Only the user's *overrides* are stored
(`relate.graphStyle.overrides`), as a diff against the defaults. A key the user never
touched is not in storage, so it always follows `theme.js`. Full checklist:
[`UIREADME.md`](UIREADME.md) §10.

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

## 8. Debugging

| Symptom | Check |
|---|---|
| Canvas empty, API fine | `curl /api/graph?limit=5` — if it returns nodes, the failure is in the UI. |
| Everything renders as squares | A Cytoscape selector matched too broadly. `[key]` tests field **existence**. |
| Render dies after first paint, or the app goes black | A style value parsed to `null` — `background-image: data(x)` on an empty string, or 8-digit hex. [`UIREADME.md`](UIREADME.md) §3. |
| A glow does nothing | `shadow-*` does not exist in 3.35. Use `underlay-*`. [`UIREADME.md`](UIREADME.md) §1. |
| **A theme edit does nothing** | The bundle was not rebuilt — `theme.js` is compiled into `app.js`. Run `npm run build` (or keep `npm run watch` on) and hard-refresh. §8. |
| **One theme value ignores `theme.js`** | The user has overridden that key; only overrides are persisted. Reset it in the Canvas modal. §8. |
| Thread shows 0 messages | The tz offset differs from the one the store was written with. |
| A route 404s after a rename | The Python server is stale — it loads routes once at startup. Restart it. |
| Blank page, no console clue | A `const` inside a `useMemo` referenced in its dependency array throws `ReferenceError` every render. |
| Chat answers a different question | Tool result exceeded `MAX_TOOL_CHARS` (4,000). Summarised, not silently cut. |
| Chat is very slow | `think: false` not applied, or `num_predict` unset. `archive_docs/Ollama.md` §1. |
| Port 8100 "already in use" | `netstat -ano \| findstr :8100`, then `taskkill /PID <pid> /F`. |
| Ingest reports 0 messages but exits 0 | `verify_ingest` is the check that matters. |
| **`storage locked`** | Another surface holds the store. `tools._connect()` retries ~2.75 s; a long ingest is the case it cannot clear. `GET /api/jobs` says whether one is running. |
| **MCP refuses to start** | No valid key. `store/profile/mcp.json` holds both; pass one as `RELATE_MCP_KEY`. |
| **MCP badge stays green** | No tool call has happened yet — the heartbeat stamps on a call, not on connect. |
| **A re-export changed nothing** | The spool replaced the file but the delta found no new messages — check the window, not the file. |

## 9. Relate / Neo4j

- **Relate is embedded.** `relate.connect(path)` takes a **filesystem path**, not a
  `file:` URI. No Bolt, no port, no server.
- Consequence: every library writing via `neo4j.GraphDatabase.driver(uri)` —
  `neo4j-graphrag`, LangChain's `LLMGraphTransformer`, MS GraphRAG, LightRAG, LlamaIndex —
  **cannot talk to Relate at all.** Not "needs an adapter": there is no socket.
- `relate.Connection` exposes `execute, executemany, cursor, commit, rollback, close,
  flush, autocommit, namespace` and nothing else.
- **There is no compaction, and deleting a property frees no disk.** Measured on 1.0.1:
  `SET m.emb = null` and `REMOVE m.emb` both leave the file the same size or larger;
  `DROP INDEX` frees nothing; `flush()` and `close()` free nothing; `db.checkpoint` is
  listed by `SHOW PROCEDURES` but is not callable (`ProcedureNotFound`). Relate is
  append-only, so the only way to reclaim space is to **rewrite the graph into a fresh
  `.rl`** — which is what `tools.flush_embeddings()` does, in Python, at 1.5 s for
  3,113 nodes and 3,183 edges. **This is a real limitation worth reporting upstream:**
  there is no surgical way to drop a large property (a 768-float vector is ~30 KB on
  disk) without copying the whole store. See `tests/README.md` for the fidelity test
  that guards the rewrite.
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

## 11. MCP — the agent surface

**Local only, stdio.** The IDE launches `python -m app.mcp` and talks over the same pipe it
uses for output. No port, no network, nothing to expose. A dev who wants web access puts
their own proxy in front; that is their risk and this server does not arrange it.

### Two keys, in a file we own

`store/profile/mcp.json` — gitignored, beside `identity.json`, generated on first run:

```json
{ "read_key": "r_…", "write_key": "w_…" }
```

The owner copies one into their client config, which passes it as `RELATE_MCP_KEY`:

```json
{ "command": "python", "args": ["-m", "app.mcp"],
  "env": { "RELATE_MCP_KEY": "r_…" } }
```

| Key presented | Result |
|---|---|
| none | **refuses to start** |
| `read_key` | 16 tools — read only |
| `write_key` | 21 tools — read + write |

**Two keys, not a boolean**, because the write key is a separate secret handed over
deliberately: an agent configured with only the read key cannot write even if it tries.

**This is a handshake, not a wall.** Anyone who can launch the process can read
`mcp.json` — same user, same permissions. It stops a *different* agent on the machine from
quietly connecting, and it makes granting write a deliberate act. It does not stop malware
running as the user. That is acceptable because the real boundary is already "who can
launch a process on this machine", which for stdio is the whole trust model.

### The one path rule

`ingest(paths_in=[…])` calls `stage()`, which **copies any path on disk** into the spool.
That is a filesystem read primitive, so it is bounded: **any path inside the repo**, and
nothing else. It is a boundary, not a safety mechanism — `ingest` copies and never deletes
the source.

### What MCP may read, and what it must never return

`.env` holds only the four `IMAP_*` keys. MCP may use them: `ingest(email=["email"])` takes
a **mailbox name**, and the values are used inside the process and never appear in a
response, a tool argument or the activity trace. An agent that can call `search_fulltext`
can already read every message, so this grants no new power — it only lets the agent
refresh what it can already see.

### The two files the two processes share

| File | Written by | Read by |
|---|---|---|
| `store/profile/mcp.heartbeat` | every tool call | `/api/health` → `mcp_active` |
| `store/profile/mcp.activity.jsonl` | every tool call | `/api/activity` — **drained**; `activity()` — **peeked** |

`mcp_active` is true while the heartbeat is under 120 s old. A missing, stale, future-dated
or unparseable file all read as **false** — the badge never claims a client it cannot prove.

### Three tools that live in the server, not the registry

`job_status`, `job_list`, `activity` describe **this process's** jobs and trace, not the
store, so they have no business in the library's tool layer.

### `sample_writer` is not exposed

It wipes `out/` on `build`/`clean`, and any clone's IDE agent can already run it directly
with more power than MCP would grant. MCP's WRITE level is *maintenance of a real store*,
not *construction of a fake one*.

## 12. Where the rest of the detail lives

**Five root docs, and they are the app.** If something is not in one of these, it is not
current.

| Doc | What it is |
|---|---|
| [`TECHREADME.md`](TECHREADME.md) | this file — the pipeline, the modules, the invariants |
| [`SCHEMA.md`](SCHEMA.md) | the store's data model and the 19-tool registry |
| [`UIREADME.md`](UIREADME.md) | the UI app, and every renderer trap |
| [`HANDOVER.md`](HANDOVER.md) | what is next, and what just landed |

**Adjacent, current:** [`sample_writer/README.md`](sample_writer/README.md) (every knob and
the `append` cycle) · [`tests/README.md`](tests/README.md) (payloads, wiring a new format) ·
[`archive_docs/MssgDownloadInstructs.md`](archive_docs/MssgDownloadInstructs.md) (how the
Owner gets their socials) · [`archive_docs/Ollama.md`](archive_docs/Ollama.md) (models and
settings).

**Archive — history, not current.** `archive_docs/` holds design records kept so old links
resolve: `UNDESIRABLES.md` (the generator spec the sample world is coded against),
`locking_in_node_extraction.md` (how extraction was settled), `detacheable_graph.md` (the
portable-module study). **Do not treat anything there as describing the app today.**
