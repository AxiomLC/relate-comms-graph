# HANDOVER.md

**Now and next.** Not a record of everything fixed — that is `git log`. Fixed work gets one
line. Pending work keeps its detail.

Durable facts: [`TECHREADME.md`](TECHREADME.md). UI and visual facts:
[`UIVISUALS.md`](UIVISUALS.md). Human overview: [`README.md`](README.md).

---

## Where it stands

`pytest tests -q` → **400 passed, 2 skipped**. App runs: `start.bat` → `127.0.0.1:8100`.

**Live store: rebuilt 2026-11-19.** **2,003 messages · 93 correspondents · 34 merged · 7
`POSSIBLY` edges.** Per platform: telegram 851 · messenger 655 · email 151 · sms 139 ·
whatsapp 108 · linkedin 93 · outlook 6. Audit query:
`MATCH (c:Correspondent:Merged) RETURN c.merged_by, count(*)` → `exact_name 27`,
`nickname 7`.

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

### 2. Body-entity extraction — `Person`, `Place`, `Organization`, `Product`

The schema, the queries and `canon.KINDS` are already wired for all four; they hold zero
rows because nothing generates candidates. Three stages, in order:

**a. Canon flattening.** `canon.canonical(raw, kind=…)` already handles all four kinds and
raises on an unknown one. What is missing is the input: a candidate generator that reads
message bodies and proposes `(surface_form, kind)` pairs.

**b. Node production.** Write the extracted entities as nodes with the same shape as
`Correspondent` — `key = <kind>:<canonical>`, `platform`, `mention_count`. The writer path
exists; it needs a source.

**c. Merged nodes across platforms.** An entity mentioned on more than one platform becomes
`:Merged`, exactly as a Correspondent does. `link.link()` already runs over the whole store
and is idempotent, so this is a matter of feeding it the new kinds.

**Canvas:** the merged-node template is the one to copy — grey glyph, radial halo, own bag.
`UIVISUALS.md` §7. Entity bags get their own placement slot; the ring becomes a two-tier
composition (platforms outside, entities inside).

**Blocked on:** the candidate generator. Nothing else.

### 3. The local LLM

Wired, never exercised end to end. Needs a real conversation and a check that
`MAX_TOOL_CHARS` truncation is **reported** rather than silent. `think: false` is a 28×
speedup on this box and must stay applied.

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

## Ingest UI — known broken

The **graph is not affected**. The defects are confined to the modal's two picker routes,
which stage silently and leave the box showing nothing.

| Path | Behaviour |
|---|---|
| **Paste a path** | **Works.** This is the reliable route. |
| **Drag and drop** | Does not work, and the staged list never shows whether staging succeeded. |
| **Select file / select folder** | Selection is not reflected in the box either. |

**Two confirmed defects:**

1. `app/ui/src/lib/api.js` — `body.append("files", file, file.name)` sends only the **bare
   filename**. `webkitRelativePath` is never sent, so the folder a folder-pick holds is lost
   before it reaches the server. The route's `parts[-2]` logic can never fire.
2. `app/routers/ingest.py::upload` — detects **per uploaded file**. A dropped `email_eml/`
   folder arrives as ~190 individual `.eml` files, none of which is a mailbox on its own, so
   every one is filed under `spool/real/unrecognised/`. The same folder works when pasted,
   because `stage()` asks `detect_platform()` about the **directory** first.

**Fix, in order:** (a) send `file.webkitRelativePath || file.name` in `api.js`; (b) make
`upload` group files by their top folder and ask `detect_platform()` about the reconstructed
folder the way `stage()` does; (c) surface `result.ok` / the error text so a silent empty
response is visible.

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
