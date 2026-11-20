# HANDOVER.md

**Now and next.** Not a record of everything fixed — that is `git log`. Fixed work gets one
line. Pending work keeps its detail.

Durable facts: [`TECHREADME.md`](TECHREADME.md). Human overview: [`README.md`](README.md).

---

## Where it stands

`pytest tests -q` → **400 passed, 2 skipped**. App runs: `start.bat` → `127.0.0.1:8100`.

**Live store: rebuilt 2026-11-19.** **2,003 messages · 93 correspondents · 34 merged · 7
`POSSIBLY` edges.** Per platform: telegram 851 · messenger 655 · email 151 · sms 139 ·
whatsapp 108 · linkedin 93 · outlook 6. The audit query works:
`MATCH (c:Correspondent:Merged) RETURN c.merged_by, count(*)` → `exact_name 27`,
`nickname 7`.

**Cross-platform merging is automatic on every ingest.** `link.link()` runs once at the
end of `ingest()`, over the whole store, so a new export can supply the phone that links
two nodes written months apart. It is idempotent.

> **The canvas bags by platform.** One invisible parent per platform, built client-side in
> the element memo; a node goes in a bag iff it is **not** `:Merged`. On this store that is
> 214 bagged nodes and 34 bridges outside. `theme.filter.bags` turns it off.

> **Ingest UI.** Drag-and-drop and folder-pick do **not** show what they staged
> (see *Ingest UI — known broken*). **Pasting a path works**, which is how email was ingested:
paste `sample_writer\out\email\email_eml`, the whole folder, not `Inbox/` or `Sent/`.
>
> **The graph is fine.** It shows email correctly once the paste-path ingest runs. The only
> defect is in the modal's drop box and folder select — the staging happens silently and the
> box stays empty, so the user cannot tell whether it worked.

**Legs built:** Telegram, WhatsApp (native `chat.txt` **and** HTML), Messenger, LinkedIn,
Email (IMAP **and** saved `.eml`), Outlook (`.pst`), SMS. All seven are in the live store.

**One variant per platform.** `out/` holds several packagings of the same conversations;
ingesting more than one per platform stores every message twice. Ingest one of:
`linkedin/linkedin_zip`, `messenger/messenger_zip`, `outlook/outlook_copy`, `sms/sms_xml`,
`telegram/telegram_bulk`, `whatsapp/whatsapp_html`, `email/email_eml`.

**One queue.** `spool/sample/`, `store/spool/` and `paths.sample_dir()` are gone. A sample
is a file dropped in `spool/real/`; `ingest` cannot tell it from a real export.

---

## Next

**The four-edit build round is finished** (2026-11-19): node structure → `tools.py` API →
UI node types → cross-connect. The plan document that drove it is gone; what survived is
in `TECHREADME.md` §4 (schema, `link.py`, the knobs) and `git log`.

**Canvas layout is the one open area.** [`CytoGravityRecommend.md`](CytoGravityRecommend.md)
holds it: bags, the ring, what the vendored fcose actually honours, and the unresolved
long-edge problem. **It may or may not be finished** — the owner may hand it to a vision
model and tune the Gravity panel's parameters by eye instead. Read §6 there before
changing any layout code.

What is left:

1. **Long edges on the canvas** — see `CytoGravityRecommend.md` §6. Six force-layout
   levers are ruled out; the leading hypothesis is that `placeBagsOnRing()` moves bags
   *after* the solver, so a bridge ends up ~2× the ring radius from its bag. The decisive
   experiment (ring off) has not been run. **This is the only known visual defect.**
2. **Messenger group titles** — 117 of 134 real threads are groups; the adapter names each
   after a participant instead of the `<h1>`. The samples happen to be right for one group
   and wrong for the rest, so **the samples will not catch this**.
3. **Body-entity extraction** — `Person`, `Place`, `Organization`, `Product`. Blocked on a
   candidate generator. The schema and canon pipe are already wired for all four.
4. **UI chat / LLM** — wired, never exercised end to end. Needs a real conversation and a
   check that `MAX_TOOL_CHARS` truncation is reported rather than silent.
5. **Search relevance** — `search_messages` is a substring scan only, no ranking. A design
   gap, not a test gap.
6. **MCP wiring** — `app/mcp/__init__.py` is a docstring. When built it must **not** gain a
   `.env` read; that is the guarantee the IMAP credentials rely on.
7. **Placeholder nodes are not styled on the canvas** — `isPlaceholder()` exists but only
   `Viewer.jsx` uses it. The canvas has no placeholder class.
8. **The size warning has no visible threshold** — `LARGE_FILE_BYTES = 500 MB` renders as
   "· large file" with no explanation.

---

## Open decisions

- **The platform filter narrows the AI chat as well as the search bar.** Deliberate,
  overriding the earlier "UI state never narrows an agent's query" rule. The alternative is
  a per-call `platforms` argument instead of module state in `tools.py`.
- **Per-node gravity is not a fcose feature.** Big threads can only be approximated as
  anchors via lower `nodeRepulsion`. The dominance leash was designed and then withdrawn
  in favour of equal pull — see `CytoGravityRecommend.md` §2.
- **The Outlook fingerprint can merge two genuinely distinct messages** — same thread, same
  second, byte-identical body, different senders. Accepted: the alternative is every sent
  message appearing twice, which the real file exhibits.
- **WhatsApp's minute-resolution key** was a hazard for the old store's second-resolution
  rows. The 2026-11-18 wipe resolved it; the live store is built entirely at minute
  resolution.

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
| **WhatsApp** | `sha256(chat title)[:16]` → `wa_…` | the contact is renamed. **The two-dialect case is fixed** — `read_export` now strips the `WhatsApp Chat with ` prefix, so `X.zip` and `WhatsApp Chat with X.txt` agree. |
| **Email** | `Message-ID`, else `uid:<UIDVALIDITY>:<UID>` | the server bumps `UIDVALIDITY` — every key in the mailbox changes at once |
| Telegram / Messenger | read straight from the export | (stable) |

WhatsApp's `message_key()` also hashes the **body**, so an edited message, a changed media
placeholder or a locale difference duplicates that one row even when the thread id holds.

**Debugging it later:** compare `count(DISTINCT t.key)` against the number of conversations
the export claims. A doubled count with identical titles is this. The fix is a stable
surrogate — persist `(platform, title-or-participants) → chat_id` in `store/profile/` and
reuse it, the way `identity.json` already persists the Owner — not a change to the hash.

## Known issues in the live store

- **6 threads have no Correspondent edge — all Outlook.** Correct by design: the `.pst`
  fixture is a single-account demo mailbox, so every message is `is_self` and there is no
  counterparty to attach. Revisit only with a real multi-party `.pst`.
- **22 owner-silent threads, 90 messages total** — a small, sane tail across five platforms.
- `Facebook user` spans Messenger threads — a placeholder Correspondent by design, and
  platform-scoped so it never merges with LinkedIn's `LinkedIn Member`.
- **Largest thread is 500** (`Telegram; Mary Olver (500)`), then 370 and 200. The Viewer
  pages, so this is fine.
- **LinkedIn has 23 threads and 0 groups.** The adapter computes `is_group`, but no gate is
  warranted until a real group export appears.
- **LinkedIn recipient lists can become one node.** `_split_recipients()` splits on `;` only,
  deliberately, because `TO` also contains names with credentials (`Steve Mikano CIA, AIC-M,
  AINS, SSBB`). A comma-separated list with no semicolons therefore becomes one node.
  `canon.split_list()` implements the separator heuristic but the LinkedIn adapter does not
  call it yet.

---

## Ingest UI — known broken (being tested now)

The **graph is not affected** — it renders email correctly. The defects are confined to the
modal's two picker routes, which stage silently and leave the box showing nothing.

| Path | Behaviour |
|---|---|
| **Paste a path** | **Works.** This is the reliable route. Email ingested this way. |
| **Drag and drop** | Does not work, and the staged list never shows whether staging succeeded. |
| **Select file / select folder** | Selection is not reflected in the box either. |

**Two defects are confirmed in the upload route, and they are the likely cause:**

1. `app/ui/src/lib/api.js` — `body.append("files", file, file.name)` sends only the
   **bare filename**. `webkitRelativePath` is never sent, so the folder a folder-pick hold
   is lost before it reaches the server. The route already has `parts[-2]` logic to keep the
   parent folder; it can never fire.
2. `app/routers/ingest.py::upload` — detects **per uploaded file**. A dropped or picked
   `email_eml/` folder arrives as ~190 individual `.eml` files, none of which is a mailbox
   on its own, so every one is filed under `spool/real/unrecognised/`. The same folder works
   when pasted, because `stage()` now asks `detect_platform()` about the **directory** first.

**Fix, in order:** (a) send `file.webkitRelativePath || file.name` in `api.js`; (b) make
`upload` group files by their top folder and ask `detect_platform()` about the reconstructed
folder the way `stage()` does, instead of admitting every leaf file; (c) show the staged
result — `stagedCount > 0` already renders, so if nothing appears the response is empty, and
surfacing `result.ok` / the error text is what proves it.

---

## Done — 2026-11-19 — app files I edited (not just `sample_writer`)

Three app-side bugs, all on the **email drop-in path**. `sample_writer` changes are listed
under its own heading below.

- **`relate_comms/adapters/email_imap.py::detect()`** — used a non-recursive
  `path.iterdir()`, while `parse_eml()` reads with `rglob()`. A folder holding
  `<thread>/NNN.eml` was reported **not email**, so `discover()` filed the whole export as
  unrecognised and the modal sat at "ingesting…" forever. Now recursive, matching the parser.
- **`relate_comms/ingest.py::stage()`** — walked **into** a dropped folder and copied every
  file individually. Each `.eml` then hit `detect_platform()` alone and landed in
  `unrecognised/`, so a pasted `email_eml/` staged ~190 files and wrote nothing. Now a
  directory that `detect_platform()` claims **as a whole** is copied intact with
  `copytree` — the same rule `discover()` already had. Verified: `email_eml` → 1 batch /
  151 messages; `messenger_dir` → 655; `linkedin_dir` → 93.
- **New tests** (`tests/test_sample_writer.py`): `test_email_layout_splits_inbox_and_sent`,
  `test_email_export_is_discovered_by_ingest`, and two staging tests, one per folder export.

**Not yet fixed:** the upload route and `api.js` (see *Ingest UI* above). Paste-path works;
no other route does.

Everything before **2026-11-18** is in `git log`; only the current round is listed.

- **2026-11-19** — **Naming settled: `canon.KINDS` is the single source.** `kind="thing"`
  renamed to `kind="product"`; `canon.canonical()` now raises on an unknown kind instead
  of silently taking the `person` branch (which would strip credentials and resolve
  nicknames on a product name). `tools.ENTITY_KINDS` is derived from `canon.KINDS`, so the
  store label `Product` and the kind `product` cannot drift. `Company` appears nowhere.
- **2026-11-19** — **Bag ring + overlap fixes.** `theme.layout.bagRing` moves each bag's
  children onto a circle **after** the solver, in legend order so the picture is stable.
  `bagRingSpread` opens the middle. **`fixedNodeConstraint` was tried first and broke the
  app** — fcose never indexes a compound in `spectralLayout`'s `nodeIndexes`, so the
  constraint read `undefined` and every coordinate became `NaN` (blank canvas, stalled
  refresh). The ring is a translation of the bag's children instead; see
  `CytoGravityRecommend.md` §3. `nodeDimensionsIncludeLabels: true` — labels are now part
  of the layout box, which is the main "nodes on top of nodes" fix. `gravityCompound` /
  `gravityRangeCompound` and the ring are exposed in the Styling modal; the
  `nodeSeparation` hint was corrected (it scales the initial spectral pass only, it does
  not space the settled layout).
- **2026-11-19** — **Edge length: six levers tried, none worked.** `idealEdgeLength`
  60→22, `smartEdgeLength: false` (disables `useSmartIdealEdgeLengthCalculation`, which
  adds each bag's size to every cross-bag edge), `bagRingSpread` 1.35→1.0, plus
  `gravityCompound`, `nodeSeparation` and `packComponents` — all ruled out, see
  `CytoGravityRecommend.md` §5. **Edges are still far too long and this is the one open
  problem.** Leading hypothesis: `placeBagsOnRing()` moves bags *after* the solver, so a
  bridge left near its bag ends up ~2× the ring radius away from it — a length no fcose
  parameter can undo. The decisive experiment (ring off) has not been run; see §6.
- **2026-11-19** — **Canvas bags landed (`CytoGravityRecommend.md` step 1).** One invisible
  compound parent per platform, built in the same pass that filters children (fcose throws
  on a parentless child). Membership is `:Merged` inverted — the label, not
  `platforms.length`, so a Place mentioned on two platforms stays outside. Bags are
  `synthetic`: excluded from the reveal, `onLayoutDone` and every count. `gravityCompound` /
  `gravityRangeCompound` are theme knobs; `theme.filter.bags` turns the whole thing off.
  `graph_slice` now returns `merged` per Correspondent.
- **2026-11-19** — **`run_cypher` no longer refuses `:Merged`.** The write guard was a
  substring scan, so `MERGED` matched `MERGE` and the plan's own audit query was rejected as
  a write. Now word-bounded; `SET`/`MERGE`/`DELETE` are still refused. 9 tests in
  `tests/test_cypher_guard.py`.
- **2026-11-19** — **Live store rebuilt** from one variant per platform: 2,003 messages, 93
  correspondents, 34 merged, 7 `POSSIBLY`.
- **2026-11-19** — **Edit 4 landed: `relate_comms/link.py`.** Runs once at the end of
  `ingest()`. Folds nodes whose keys differ — a phone-only contact onto a named one — by
  union-find over phone / email / name, re-pointing every `WITH` and `POSSIBLY` edge before
  the loser is deleted, then `_reconcile` rebuilds `platforms` / `platform_label` /
  `:Merged`. Fuzzy pairs get a dashed `POSSIBLY` edge instead, now in
  `DRAWABLE_EDGE_TYPES`. **The prerequisite the plan missed:** the store held no phone or
  email for a *named* contact, so `writer._contact_ids()` now records `sender_id` when it
  is actually a phone or an address. Knobs `canon.NICKNAME_ENABLED` / `FOLD_ON_NAME` are
  live. 10 new tests in `tests/test_link.py`.
- **2026-11-19** — **Edit 3 landed: the canvas is `NODE_TYPES`-driven.** `config/nodeTypes.js`
  declares `drawable` / `shape` / `sizeLadder` / `countKey` / `labelMax` / `edgeWeight` /
  `hideWhenSilent` / `glow` / `iconKind` per kind, and `GraphCanvas` reads it — no
  `node.type === "Thread"` test remains. `Person` / `Place` / `Organization` / `Product`
  are entries (D/E/F ladder, `mention_count`), off in `filter.nodeTypes` until extraction
  lands. Shape and glow rules are generated from the config. `Viewer` gained a generic
  `EntityView` routed by `countKey === "mention_count"`. All four have `iconKind: null`,
  so they draw as the base filled circle — no glyphs, by decision.
- **2026-11-19** — **Edit 2 landed: the tool layer knows the new kinds.** `_NODE_ALIAS`
  replaces the `if` chain; `Person` / `Place` / `Organization` / `Product` each get a node
  query, a count query, three sort entries and a `MENTIONS_<KIND>` edge query — all
  returning 0 until extraction lands, and none in `DRAWABLE_NODE_TYPES`. `POSSIBLY` gets
  an edge query so it draws the moment `link.py` writes one. `graph_slice` now returns
  `primaryPlatform` and `dominance` per Correspondent, derived from a two-stage
  per-platform message count. `primaryPlatform` is **most messages**; `platform` stays
  **first by date** — 17 of 34 merged nodes on the sample store disagree, so they are
  genuinely two fields.
- **2026-11-19** — **Edit 1 landed: `Correspondent.key` is `person:<canonical>`.** One
  canonical name on two platforms is one node. Placeholders stay platform-scoped. New
  properties `platforms`, `platform_label`, `first_seen_utc`, `merged_by`, plus flat
  `handle_<p>` / `seen_<p>` (Relate rejects map properties). `:Merged` marks a node on
  more than one platform and is filtered out of `types_present()`. The platform filter
  and the canvas filter now read `platforms`, not `platform`. Measured on the sample
  variants: 93 correspondents, 34 merged.
- **2026-11-19** — `sample_writer` fuzz: sender labels and body entities can now carry
  different spellings per platform (`Chris`/`Christopher`, `Celestica`/`Celstica`,
  `North Dakota`/`N Dakota`). Derived by rule (`sample_writer/fuzz.py`); one small nickname
  table, no data files. The **Owner is never fuzzed**. Knobs `FUZZ_*` in
  `sample_writer/config.py`; `plan.assert_contract` fails if a knob produces less than it
  asked for.
- **2026-11-19** — `sample_writer` timing: threads are no longer evenly spread. Messages
  arrive in bursts with long silences (`TIMING_BURSTS`, `TIMING_SPAN_DAYS`), so a thread can
  put three messages in one year and two in the next. Spans 0-729 days, clamped to the
  export window.
- **2026-11-19** — `sample_writer` bodies: mixed sentence counts
  (`BODY_SENTENCES_WEIGHTS`, 55/30/15) plus a sign-off pool.
- **2026-11-19** — `sample_writer` email: writes `Inbox/<thread>/` and `Sent/<thread>/` so
  `folder_is_sent()` fires and ownership is decided **structurally**, not only by address
  match.
- **2026-11-19** — **Email is now ingestible from the UI by pasting a path** — the first time
  the email leg has worked outside a test. See the app fixes above.

- **2026-11-18** — Docs consolidated: one spool queue, no stale claims.
- **2026-11-18** — `sample_writer` finished: `add` writes alongside `out/` with Windows-style
  `name (1)` dedupe (`uniquify.Filer`), `--platform` takes space-separated names, `--keep`
  replaced by the `build`/`add` split.
- **2026-11-18** — `canon.py`: the shared flattening pipe. Four kinds, English nickname table,
  `rapidfuzz` for fuzzy, report-only candidates. 69 tests.
- **2026-11-18** — Canon wired into the Correspondent write. **The Owner is no longer a
  Correspondent on any platform** — it was in 236 threads. `ingest._owner_forms()` collects
  every form the Owner is known by, including the display name from other platforms.
- **2026-11-18** — Thread titles: `Platform; Name; MM-DD-YYYY->`. The `->` changes at most
  once, ever, so the label does not drift on re-ingest.
- **2026-11-18** — `Person`/`Identity` scaffolding deleted. `resolution.py` gone,
  `write_people()` gone, `person_key="owner"` gone. `Person` is a future extraction node
  type, never the Owner.
- **2026-11-18** — Viewer: the text block above the histogram deleted; the title carries it.
- **2026-11-18** — `.eml` mailboxes are discoverable. Email was unreachable from the spool;
  it could only be reached from a test. Owner inferred by breadth, since a saved mailbox
  states no account.
- **2026-11-18** — WhatsApp thread dedupe: `WhatsApp Chat with X.txt` and `X.zip` hashed to
  two `wa_` ids. 48 threads → 24.
- **2026-11-18** — WhatsApp HTML 1:1 correspondents: the title-derived sender was never
  added to `participants`, orphaning 16 of 20 threads. Correspondents 5 → 23.
- **2026-11-18** — Viewer: the "not a Person, merging is a later step" note removed, with
  its dead `.arc` CSS.
- **2026-11-18** — Store wiped and rebuilt from the six sample variants: 1,853 messages /
  133 threads / 131 correspondents.

---

## Spec — Email leg (one platform, many providers)

**Term: `Email`.** Platform key `email`. **One mailbox at a time.**

`--email` is repeatable and `_fetch_mailboxes()` loops, but every mailbox lands as platform
`email`, so two mailboxes merge into one cluster and `Message.key` is not guaranteed unique
across them.

**The provider is a parameter, not a platform.** Nothing in the adapter may branch on a
provider name. `ENV_ACCOUNTS` is a convenience table of 11, not a whitelist;
`account_from_parts(host, user, password, port=993)` covers anything else.

**Folder detection is provider-agnostic and must stay that way.** Tier 1: RFC 6154
special-use flags (`\All`, `\Inbox`, `\Sent`) — locale-proof, which is why a Spanish Gmail
(`[Gmail]/Todos`) works. Tier 2: name hints on the last path segment, for servers that
publish no flags.

| provider | quirk |
|---|---|
| Gmail | `[Gmail]/All Mail` already holds Inbox + Sent — importing both double-counts |
| Outlook / O365 | Basic auth is dead; needs OAuth2 or an app password |
| Yahoo / AOL / iCloud | App passwords; the displayed password has spaces that are not part of it |
| cPanel / generic | Host is `mail.<domain>`; folders are `INBOX` + `INBOX.Sent` |
| Yandex / GMX | Often publish no special-use flags — tier 2 carries it |

**Work:** one mailbox per run (refuse two `--email` values rather than silently merging);
`Message.mailbox` (`gmail` / `hostinger` / …) as a property so the Viewer can say which
mailbox a message came from without splitting the platform.

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
