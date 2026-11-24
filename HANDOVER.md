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

> **`outlook` has been reading 0 rows** while `spool/real/outlook/` exists. The `.pst` leg is
> built and tested; this is a data-presence question, not a code one. Check before trusting
> any Outlook claim, and treat a flat-0 platform as "not re-ingested", not as a bug.

**Extraction rework landed 2026-11-23** (commit `f782812`). Three structural changes:
- **`POSSIBLY` is gone.** Fuzzy spelling pairs now fold instead of drawing a guessed edge.
- **`MENTIONS` hangs off the Message, not the Thread.** `Thread → Entity` is a read-time
  projection in `tools._EDGE_QUERIES`. `mention_count` is message-based.
- **`Product` is a live kind** (`extract.PRODUCT_ENABLED = True`), backed by
  `relate_comms/products.py` — 92 entries in three tiers with a four-rule ladder.

**Rebuild needed after any extractor change:** `delta=False` (the UI's **Full re-process**).
A delta run keeps everything already stored, which is exactly wrong after the reading of
bodies changes.

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

**One queue.** `spool/sample/`, `store/spool/` and `paths.sample_dir()` are gone. A sample
is a file dropped in `spool/real/`; `ingest` cannot tell it from a real export.

> **Editing the theme.** `theme.js` is compiled into `app/static/dist/app.js`, so an edit
> needs a rebuild — `npm run watch` on save, else `npm run build` — then a hard refresh.
> **No version bump, no `localStorage` clearing:** only the user's *overrides* are stored
> (`relate.graphStyle.overrides`), as a diff against the defaults, so a key nobody touched
> always follows the file. Detail: `TECHREADME.md` §7.

---

## Next

> **THE NEXT WORK ITEM IS THE ENTITY-LIST LOAD (§0).** Everything else in this section is
> queued behind it. That job is what closes [`rework_extraction.md`](rework_extraction.md)
> — the Product line, the three dictionaries, and the per-kind visibility that reads them.
> AI/LLM wiring (§3) and MCP (§4) remain a standing given; they are not the priority.
>
> **When §0 lands, `rework_extraction.md`, `entity_list_brief.md` and `temp-lists` are all
> finished with.** See the note at the bottom of this file.

### 0. Entity lists — drafted, not yet loaded — **the active job**

**Three lists are drafted** in [`temp-lists`](temp-lists) (2,126 lines) from the brief in
[`entity_list_brief.md`](entity_list_brief.md):

| List | Entries | Current in code |
|---|---|---|
| Places | **684** | `PLACE_DICTIONARY` 97 |
| Organizations | **576** | `ORG_DICTIONARY` 26 |
| Products | **739** (636 `plain`, 22 `gated`) | `products.INDEX` 92 |

Plus **CONSIDERED AND REJECTED** and **UNSURE — your call** sections, which are the point of
the brief: they show where the boundary was drawn.

**Quality checked, not assumed.** Every generic-noun land mine is either absent or in the
rejected section with a reason (`Seat`, `Contract`, `Credits`, `Desk`, `Shoes`, `Watch`,
`Flight`, `Rack`, `Switch`, `Plan` — all zero in `plain`). Only one bare brand slipped
through as `plain` (`Rolex`), which is defensible. The `gated` entries are the genuinely
ambiguous middle, each with its reason — `Slack` (*"cut me some slack"*), `Zoom`
(*"zoom in"*), `Notion`, `Obsidian`, `Asana`, `Confluence`.

**Not loaded yet.** `temp-lists` is not imported by anything. Loading means:

1. **Places / Organizations** — paste into `extract.PLACE_DICTIONARY` / `ORG_DICTIONARY`.
   Safe: proper nouns, measured flat per message up to ~2,000 names.
2. **Products** — `plain` and `gated` into `products._PLAIN` / `_CONTEXT_GATED`; the rejected
   section into `products.GENERIC`. **Needs care**: a common noun in `plain` mints junk
   nodes, and `GENERIC` is the only thing that stops it.
3. **Rebuild** (`delta=False`), then query `MATCH (p:Product) WHERE p.mention_count >= 2`.
   The canvas is not the instrument — hidden single mentions are still stored.

**`sample_writer` was rebalanced alongside it** (2026-11-24): `PRODUCTS` 100 → **184**,
tech 75 / durable 89 / food 20, three frame sets, per-section fuzz variants (physical goods
never hyphenate). The knobs that raise how many entities a body names live in
`sample_writer/config.py` — `BODY_ENTITY_LINES` is the real ceiling, not pool size.

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
person, and `Databricks` a place. `PLACE_DICTIONARY` (97), `ORG_DICTIONARY` (26) and
`products.py` (92) run *before* the model and win.

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
what is still open: [`rework_extraction.md`](rework_extraction.md).

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

**`delta=False`** is the escape hatch, exposed in the UI as the **Full re-process**
checkbox (the control is inverted so the fast path is the one nobody has to think about).
Required after an extractor change, and the only way to re-derive Places for rows written
before extraction existed.

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

### 4. MCP wiring — **standing, not the priority**

`app/mcp/__init__.py` is a docstring. When built it must **not** gain a `.env` read — that
is the guarantee the IMAP credentials rely on. Every capability is already a plain function
in `tools.py`, so the binding is thin by construction.

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

- **2026-11-23** — **Extraction rework: Product leg, message-anchored mentions, no
  `POSSIBLY`.** `POSSIBLY` removed (all 6 edges were typo pairs; `r.score` was null on
  every one) — fuzzy is now a fifth rung in `_fold_groups`. `MENTIONS` moved from Thread to
  Message; `Thread → Entity` became a projection (measured 1.2 ms vs 2.5 ms). `<br>` bodies
  fragment before extraction (28 → 33 mentions, junk spans gone). `Product` is a live kind
  behind `extract.PRODUCT_ENABLED`, backed by `relate_comms/products.py` (92 entries, three
  tiers, four-rule ladder, no weights). **22 Product nodes, 22/22 correct, 0 false
  positives.** Three bugs found on the way: `union()` dropped the absorbed root's reason;
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

## Root-doc retirement — what goes when §0 lands

The root is carrying too many working documents. The plan, so nobody re-derives it:

| File | Fate once §0 (entity lists) lands |
|---|---|
| `entity_list_brief.md` | **Delete.** It is input to a job, not a fact about the app. |
| `temp-lists` | **Delete.** Its content will live in `extract.py` / `products.py`. |
| `rework_extraction.md` | **Delete.** Every open item closes with §0; the measurements worth keeping are already in §2 of this file. |
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
