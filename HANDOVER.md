# HANDOVER.md

**Now and next.** Not a record of everything fixed — that is `git log`. Fixed work gets one
line. Pending work keeps its detail.

Durable facts: [`TECHREADME.md`](TECHREADME.md). UI and visual facts:
[`UIVISUALS.md`](UIVISUALS.md). Human overview: [`README.md`](README.md).

---

## Where it stands

`pytest tests -q` → **434 passed, 2 skipped**. App runs: `start.bat` → `127.0.0.1:8100`.

**Live store: rebuilt 2026-11-22** (after a truncate, then an ingest of the whole spool).
**2,085 messages · 177 threads · 98 correspondents · 21 `Place` nodes (8 `:Merged`).**
Per platform: telegram 831 · messenger 661 · linkedin 228 · sms 139 · email 128 ·
whatsapp 92 · outlook 6.

> **The manifest's per-file `messages` count is zero for every entry in this build.** The
> bug is fixed (`outcome.read` is recorded instead of what the run wrote), but the existing
> entries were written by the broken code. **The next ingest refreshes them.** Until then
> the "Already in the spool" list cannot say how many messages a file contributed.

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

### 1. The graph as a portable module

**The goal:** `graph_slice()`'s payload is already a universal node/edge structure — every
point is uniform, with no cytoscape-specific shape. Make that explicit and the renderer
becomes swappable.

**Targets, in order of fit:**

| Renderer | Fits when |
|---|---|
| **vasturiano `2d-force-graph`** | closest match to the current look; d3-force instead of fcose |
| **vasturiano `3d-force-graph`** | same data, third dimension — loses label legibility |
| **React Flow / `@xyflow/react`** | nodes become real UI widgets: message lists, badges, collapsible threads, inputs |

**Why it matters:** the multi-bag + separate-gravity model fights fcose's design. fcose is a
force simulation, not a packer, so node overlap cannot be prevented — only reduced. A
renderer with real node components would make overlap a CSS problem instead.

**Work:** (a) document the payload contract as the boundary — node/edge fields, what is
required vs optional; (b) keep every cytoscape concept (bags, ring, tiers) on the client
side of that boundary; (c) build one alternative renderer behind a switch, not a rewrite.

### 2. Body-entity extraction — Places first, one generic pipeline

**v1 extracts `Place` only.** `Person`, `Organization` and `Product` are deferred until the
complete pipeline is proven on Places — including ambiguous matches, reversibility and repeat
ingestion. Then the same architecture serves the other kinds.

**The interface is generic even though v1 ships one kind.** A later `Person` or `Organization`
kind must be an extension of this pipeline, not a second implementation. Where a step can
only do one kind, that belongs in the caller, not in the step.

**Stack:** spaCy `en_core_web_sm` for extraction, existing `canon.canonical()` for
normalisation, RapidFuzz for candidate matches, existing linker architecture for merging.
One new dependency, declared as the optional `extract` extra in `pyproject.toml`
(`pip install -e ".[extract]"`); without it, extraction writes no nodes and the run report
carries one warning — never an error.

**Order — and it cannot be reordered:**

1. **Extract**, per message. spaCy proposes spans with offsets and message keys. Extraction
decides nothing, so a better extractor can be re-run over old messages.
2. **Fold within a platform.** `canon.canonical(kind=…)` converges spellings; RapidFuzz
   proposes typo candidates but never merges.
3. **Match across platforms.** Only then does a place on two platforms become `:Merged`.

This is the order `Correspondent` already uses, for the same reason: per-batch linking only
ever sees one platform.

**Why Places first:** a `Person` extracted from a body competes with the `Correspondent` that
is already on the thread — a merge with a wrong answer that looks right. A Place has no
existing node competing with it, so the pipeline is judged on its own terms.

**`canon` cannot substitute for extraction.** It normalises a name it is handed; it cannot
decide a span *is* a place. Running capitalised words through `canonical(kind="place")`
yields `monday`, `hi dave`, `ny` — no error, no useful result.

**No LLM calls in this pipeline.** Extraction is spaCy and rules only. The local LLM is a
chat feature in the UI (§3) and has no role in entity extraction, folding or merging.

**Built.** `relate_comms/extract.py` (spaCy `en_core_web_sm` + an `EntityRuler` place
dictionary), `writer.write_places()`, `link._link_entity()`, wired into `ingest()`.
`pytest tests -q` → **422 passed, 2 skipped**; 22 of those are `tests/test_extract_places.py`.
On the full sample set: **20 Place nodes, 8 `:Merged`**, e.g. `bay area` on four platforms
and `north dakota` on three.

**Two `canon` bugs this feature exposed, both fixed:**

- The place branch never stripped a leading article, though `ARTICLES` says "thing or
  place" — `the Bay Area` and `Bay Area` were two nodes. Only `product` implemented it.
- `_REGION_TAIL` is lowercase-anchored but runs after case flattening, so it could never
  match and `Kensington, London` kept its country in the key. Now matched
  case-insensitively and compared casefolded; a spelled-out province is still identity.

A third change is new behaviour rather than a fix: `n`/`s`/`e`/`w` + a word expands to
`north`/`south`/`east`/`west` (`N Dakota` → `north dakota`), from a fixed table like
`NICKNAMES`. Without it the sample writer's own `N Dakota` / `North Dakota` pair never folds.

**The extractor needs the ruler.** `en_core_web_sm` labels a bare city `PERSON` with no
locative cue (`Then Austin on Friday`) and `GPE` with one (`Flying to Austin`). The
`EntityRuler` dictionary is what makes the feature not-silently-lossy.

**Accepted false positives.** The model calls some products `GPE`/`FAC` in prepositional
frames (`nothing new from Databricks`, `don't hear from Retool`); `We use Databricks daily`
proposes nothing. Not filtered — suppressing a `GPE` because it looks like a company is
extraction deciding. A stray node costs a node, never a merge, and `mention_count` = 1
makes it obvious.

**A Place is never drawn as `POSSIBLY`.** Two places one letter apart are two places;
there is no second signal to weigh. Fuzzy candidate lines stay Correspondent-only.

**Language:** English only in v1, by decision. Non-English input yields no nodes rather than
wrong ones. `extract.language_guess()` sets a non-blocking **warning** on the batch report
("N message(s) look non-English…"); it never errors and never gates the message write. The
seam sits above the extractor, so another language is a second model and a language guess,
not a rewrite.

**Still open, not done:**

- **Canvas.** Places are queryable (`graph_slice(node_types=["Place"],
  edge_types=["MENTIONS_PLACE"])`) but **not drawn by default** — `DRAWABLE_NODE_TYPES`
  is still `("Thread", "Correspondent")`. Entity bags need a placement slot; the merged-node
  template (grey glyph, radial halo, own bag) is the one to copy. `UIVISUALS.md` §7.
- **`merged_by` remains a weak claim for Places.** A fold means "same canonical name, seen
  on two platforms". The UI must say exactly that, not imply a verified identity.
- **`sample_writer` needs no work** — it already exercises both folds. Verified on
  `sample_writer/out`: `N Dakota`/`North Dakota` and `Bay Area`/`the Bay Area` converge, and
  `toronto`/`austin` merge across three platforms each.

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

### 3. The local LLM

Chat is wired into the UI. Never exercised end to end on a real conversation. Needs a check
that `MAX_TOOL_CHARS` truncation is **reported** rather than silent. `think: false` is a 28×
speedup on this box and must stay applied. Not involved in entity extraction (§2) — chat only.

### 4. MCP wiring

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
- **Two unfocolded spelling-variant pairs stretch long edges across the ring** —
  `dimitri/dimitir whitfield`, `sahfi/shafi hassan`. Fix lives in `link.py`, not layout.

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
