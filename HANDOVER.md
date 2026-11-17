# HANDOVER.md

**Now and next.** Not a record of everything fixed — that is `git log`. Fixed work gets one
line. Pending work keeps its detail.

Durable facts: [`TECHREADME.md`](TECHREADME.md). Human overview: [`README.md`](README.md).

---

## Where it stands

`pytest tests -q` → **248 passed, 2 skipped**. App runs: `start.bat` → `127.0.0.1:8100`.

**Live store:** 12,164 messages / 620 threads / 591 correspondents across five platforms —
messenger 10,605 · telegram 877 · linkedin 292 · email 221 · whatsapp 169. Largest thread
1,624 (a Messenger group titled `Facebook user`).

**Legs built:** Telegram, WhatsApp (native `chat.txt` **and** HTML), Messenger, LinkedIn,
Email (IMAP), Outlook (`.pst`), SMS. Outlook and SMS are built and verified but **not in the
live store**.

**One queue.** `spool/sample/`, `store/spool/` and `paths.sample_dir()` are gone. A sample
is a file dropped in `spool/real/`; `ingest` cannot tell it from a real export.

---

## Next, in order

### 1. Wipe and re-ingest with the gates on

The live store was built with every gate **off**, which is why Messenger's 70 owner-silent
groups (9,513 of 10,605 messages) are in it. A clean run with the silent-group toggle on
will drop them and the largest thread falls to the low hundreds.

- **Truncate Relate DB** in the Ingest modal (double confirm). It takes the dedup manifest
  with it, deliberately.
- Re-ingest from `spool/real/`. **It is currently empty** — the exports need to come from
  Downloads again.
- Expect the store to shrink substantially. That is the point.

### 2. UI and graph items the Owner raised

- **Placeholder nodes are not styled on the canvas.** `nodeTypes.js` has
  `PLACEHOLDER_NAMES` and `isPlaceholder()`, but only `Viewer.jsx` uses it (a pill).
  `Facebook user` spans 31 Messenger threads and currently draws as a normal contact.
- **The size warning has no visible threshold.** `LARGE_FILE_BYTES = 500 MB` renders as
  "· large file" with no explanation of why it matters or what to do.
- **`prune` and `exclude_spam_groups` are both wired now**, but neither has been exercised
  against a real multi-run spool.

### 3. UI chat / LLM

Wired, never exercised end to end. `_CHAT_TOOLS` is five read tools plus `ingest` when the
write toggle is on. Needs: a real conversation, a check that tool selection picks the right
tool, and a check that `MAX_TOOL_CHARS` truncation is reported rather than silent.

### 4. Search results and query tests

`search_messages` has `substring` and `cypher` modes. No test asserts result **quality** —
only that the call returns. Worth a small fixture store with known answers.

### 5. MCP wiring

`app/mcp/__init__.py` is a docstring and nothing else. The tool registry is ready; the
server is not. When it is built it must **not** gain a `.env` read — that is the one
guarantee the IMAP credentials rely on.

### 6. Cross-platform identity

No cross-platform edge exists, so every platform is a set of disconnected components.
`resolution.py` and `writer.write_people()` are unused scaffolding. `Person` is **not** the
term for the result (`TECHREADME.md` §0).

### 7. Body-entity extraction

`Person`, `Place`, `Organization`, `Product`. Blocked on a candidate generator. Do not
start before the Viewer is settled.

---

## Open decisions

- **The platform filter narrows the AI chat as well as the search bar.** Deliberate,
  overriding the earlier "UI state never narrows an agent's query" rule. The alternative is
  a per-call `platforms` argument instead of module state in `tools.py`.
- **Per-node gravity is not a fcose feature.** Big threads can only be approximated as
  anchors via lower `nodeRepulsion`.
- **The Outlook fingerprint can merge two genuinely distinct messages** — same thread, same
  second, byte-identical body, different senders. Accepted: the alternative is every sent
  message appearing twice, which the real file exhibits.
- **WhatsApp's minute-resolution key** means the live store's 169 WhatsApp rows have
  second-resolution keys. A re-ingest would duplicate rather than merge them. The wipe in
  Next #1 resolves this.

---

## Known issues in the real store

- `Facebook user` spans 31 Messenger threads — a placeholder Correspondent by design.
- **One thread holds 1,624 messages** (a Messenger group titled `Facebook user`). The
  Viewer pages, so this is fine, but it is the test case. The largest *named* thread is 707.
- Hostinger sent mail has no `Message-ID` (133 of 221) — keyed by `uid:<UIDVALIDITY>:<UID>`.
- **147 threads have no Correspondent edge.** 135 are Telegram strangers with a `sender_id`
  and no name — fixed at the source, so a re-ingest clears them. 12 are Messenger
  `Facebook user` threads.
- **Messenger's 70 group threads are all owner-silent** and hold 9,513 of 10,605 messages.
- **LinkedIn has 205 threads and 0 groups.** The adapter computes `is_group`, but no gate is
  warranted until a real group export appears.
- **Email: 68 threads, 44 owner-silent, largest silent thread is 2 messages.** The 10+
  spam rule drops nothing today; it exists for a real mailbox.

---

## Done — one line each

- **2026-11-16** — UI built (React + esbuild, Cytoscape + fcose, two-state Viewer, local
  Ollama chat, five modals). Terms settled. Docs consolidated.
- **2026-11-17** — Outlook leg. SMS adapter. Canvas modal replaced Graph Style.
- **2026-11-17** — Ingest modal rebuilt as one tab: drop box (file **or folder**, one or
  many) → IMAP → separator → gates → log.
- **2026-11-17** — Silent-group gates for Telegram / WhatsApp / Messenger, default on.
  Email + Outlook spam gates at 10+ messages, default on.
- **2026-11-17** — Preview (`GET /api/ingest/preview`): size + duplicate per spool file.
  Dedup manifest at `store/profile/ingested.json`.
- **2026-11-17** — Truncate Relate DB, double confirm, always takes the manifest.
- **2026-11-17** — Ingest log with a halt prompt: exclude-and-continue or cancel.
- **2026-11-17** — IMAP credentials written to `./.env` from the modal; never echoed, never
  read by a tool.
- **2026-11-17** — WhatsApp HTML dialect (`adapters/whatsapp_html.py`). `message_key()`
  truncates to the minute so both dialects collapse. 46 of 47 keys identical.
- **2026-11-17** — `sms.detect()` reads inside a `.xml.zip`.
- **2026-11-17** — One spool queue. `store/spool/` (9.6 MB stale) deleted.
- **2026-11-17** — `ingest(store=…)` now redirects the profile too, so tests stop writing
  into the live `store/profile/`.
- **2026-11-17** — `GraphCanvas.jsx` `hideSilent` ReferenceError fixed (blanked the app).
- **2026-11-17** — `start.bat` no longer passes `--reload`.
- **2026-11-17** — Messenger detects an unzipped export (folder or loose
  `message_N.html`); `_parse_root()` walks back to the archive root so thread ids resolve.

---

## Spec — Email leg (one platform, many providers)

**Term: `Email`.** Platform key `email`. **One mailbox at a time.**

**Current state.** `email_imap.py` works and is verified live against Gmail and Hostinger.
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
