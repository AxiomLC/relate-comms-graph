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

**1. THE MERGED-BAG CANVAS EDIT — the active work item.** Owner-approved design, not yet
built: [`CytoGravityRecommend.md`](CytoGravityRecommend.md) **§9** is the plan (steps A–D,
piecemeal), **§0** records the traps that must not be repeated (post-layout position
mutation blanks the live canvas; headless probe passes where browsers die), **§7** the
amended settled decisions, **§10** two data-hygiene flags. `tools/ai_visual_graph_tool/`
is the measurement rig; **the user reports visuals, the probe reports geometry — one
change, one build, one reload, confirm before proceeding.** A new agent starting here:
read §9, then §0, then `tools/ai_visual_graph_tool/README.md`.

2. **Messenger group titles** — 117 of 134 real threads are groups; the adapter names each
   after a participant instead of the `<h1>`. The samples happen to be right for one group
   and wrong for the rest, so **the samples will not catch this**.
3. **Body-entity extraction** — `Person`, `Place`, `Organization`, `Product`. Blocked on a
   candidate generator. The schema and canon pipe are already wired for all four. When they
   arrive, the merged-bag tier pattern (§9) is their template: entity bags, centered slots.
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
9. **Two unfocolded spelling-variant pairs stretch long edges across the ring** —
   `dimitri/dimitir whitfield`, `sahfi/shafi hassan`; see
   [`CytoGravityRecommend.md`](CytoGravityRecommend.md) §10. Fix lives in `link.py`, not
   layout.

---

## Open decisions

- **The platform filter narrows the AI chat as well as the search bar.** Deliberate,
  overriding the earlier "UI state never narrows an agent's query" rule. The alternative is
  a per-call `platforms` argument instead of module state in `tools.py`.
- **Per-node gravity is not a fcose feature.** Big threads can only be approximated as
  anchors via lower `nodeRepulsion`. The dominance leash was designed and then withdrawn
  in favour of equal pull — see `CytoGravityRecommend.md` §2.
- **Browser/renderer portability** — owner is evaluating whether the canvas should move off
  cytoscape/fcose (vasturiano 2D force graph, d3-force) because the multi-bag + separate-
  gravity model fights fcose's design. `graph_slice()`'s payload is already a universal
  node/edge structure, so the Python layer is portable as-is; the cost is client-side
  rewrite. Revisit after the merged-bag edit (§9) ships — it may dissolve the pressure.
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

## Done — one line each

- **2026-11-21** — Gravity panel slider ranges widened per probe evidence (ring spread min
  0.5, idealEdgeLength 2, gravity 3 with inverted display, gravityCompound 6 with 0.05
  stall floor, gravityRangeCompound 0.1–1.1, nodeSeparation 400); headless geometry rig
  `tools/ai_visual_graph_tool/` built; post-layout bridge-pull approach **tried and
  reverted** (blanked live canvas — see `CytoGravityRecommend.md` §0); merged-bag design
  recorded as §9. Full round: `CytoGravityRecommend.md` §0/§9; commit `afc8666`.
- **2026-11-19** — Canvas bags landed; bag ring + overlap fixes; naming settled
  (`canon.KINDS`); edit 4 `link.py` cross-connect; edit 3 `NODE_TYPES`-driven canvas; edit
  2 tool layer knows the entity kinds; edit 1 `Correspondent.key = person:<canonical>`;
  `run_cypher` word-bounded write guard; live store rebuilt (2,003 messages / 93
  correspondents / 34 merged / 7 `POSSIBLY`); three email drop-in path bugs fixed;
  `sample_writer` fuzz + timing + bodies + email folders.
- **2026-11-18** — Docs consolidated; `sample_writer` finished; `canon.py` shared flattening
  pipe wired into the Correspondent write (Owner is no longer a Correspondent); thread
  titles `Platform; Name; MM-DD-YYYY->`; store wiped and rebuilt; Viewer cleanup; WhatsApp
  dedupe + HTML correspondents; `.eml` mailboxes discoverable. Detail in `git log`.

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
