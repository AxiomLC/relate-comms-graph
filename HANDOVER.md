# HANDOVER.md

**Now and next.** Not a record of everything fixed — that is `git log`. Fixed work gets one
line. Pending work keeps its detail.

Durable facts: [`TECHREADME.md`](TECHREADME.md). Human overview: [`README.md`](README.md).

---

## Where it stands

`pytest tests -q` → **356 passed, 2 skipped**. App runs: `start.bat` → `127.0.0.1:8100`.

**Live store:** rebuilt 2026-11-18 from the six sample variants — **1,853 messages / 133
threads / 131 correspondents / 140 `WITH` edges**. messenger 29 · telegram 26 · sms 27 ·
linkedin 23 · whatsapp 22 · outlook 6. Zero failed, zero unverified, zero unrecognised.
The Owner is no longer a Correspondent anywhere. Outlook's 0 correspondents is correct: the
`.pst` fixture is a single-account demo mailbox.

**Legs built:** Telegram, WhatsApp (native `chat.txt` **and** HTML), Messenger, LinkedIn,
Email (IMAP **and** saved `.eml`), Outlook (`.pst`), SMS. All seven are in the live store.

**One variant per platform.** `out/` holds several packagings of the same conversations;
ingesting more than one per platform stores every message twice. The mapping is in the plan
doc.

**One queue.** `spool/sample/`, `store/spool/` and `paths.sample_dir()` are gone. A sample
is a file dropped in `spool/real/`; `ingest` cannot tell it from a real export.

---

## Next

**The detailed build plan is [`temp-finalBeta-fixes.md`](temp-finalBeta-fixes.md).** It is the
source of truth: the four ordered edits (node structure → `tools.py` → UI node types →
cross-connect), what is verified versus planned, the locked thread-title schema, the knobs,
and the naming decisions. Read that before starting anything.

In one line each, what is left after it:

1. **Cross-connect merge (edit 4)** — the one that produces merged Correspondent nodes. The
   samples are built for it: fuzzed spellings across and within platforms, 8–12% of the cast
   on more than one platform.
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
   `Viewer.jsx` uses it.
8. **The size warning has no visible threshold** — `LARGE_FILE_BYTES = 500 MB` renders as
   "· large file" with no explanation.

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

## Done — one line each

Everything before **2026-11-18** is in `git log`; only the current round is listed.

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
