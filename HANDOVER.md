# HANDOVER.md

**Now and next.** Not a record of everything fixed — that is `git log`. Fixed work gets one
line. Pending work keeps its detail.

Durable facts: [`TECHREADME.md`](TECHREADME.md). Human overview: [`README.md`](README.md).

---

## Where it stands

`pytest tests -q` → **356 passed, 2 skipped**. App runs: `start.bat` → `127.0.0.1:8100`.

**Live store:** 12,164 messages / 620 threads / 591 correspondents across five platforms —
messenger 10,605 · telegram 877 · linkedin 292 · email 221 · whatsapp 169. Largest thread
707 (`Bode Bradshaw`, a Messenger group). **Stale:** built before the canon pipe, so it
still holds the Owner as a Correspondent in 236 threads. The re-ingest clears it.

**Legs built:** Telegram, WhatsApp (native `chat.txt` **and** HTML), Messenger, LinkedIn,
Email (IMAP), Outlook (`.pst`), SMS. Outlook and SMS are built and verified but **not in the
live store**.

**One queue.** `spool/sample/`, `store/spool/` and `paths.sample_dir()` are gone. A sample
is a file dropped in `spool/real/`; `ingest` cannot tell it from a real export.

---

## Next

**The detailed build plan is [`temp-finalBeta-fixes.md`](temp-finalBeta-fixes.md).** It
carries the four ordered edits (node structure → `tools.py` → UI node types → cross-connect),
the locked thread-title schema, the knobs, and the naming decisions. Read that before
starting anything.

In one line each, what is left after it:

1. **Re-ingest twice** — `sample_writer/in/` (the real exports), then `sample_writer/out/`
   (the generated samples). Review both, adjust, then wipe and re-ingest for real. The live
   store was built with every gate off, which is why Messenger's 70 owner-silent groups
   (9,513 of 10,605 messages) are in it.
2. **Messenger group titles** — 97 of 97 groups have a `<title>`; the adapter reads a
   participant's name instead. `sample_writer` also emits participant names as group titles.
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
- **WhatsApp's minute-resolution key** means the live store's 169 WhatsApp rows have
  second-resolution keys. A re-ingest would duplicate rather than merge them. The wipe in
  Next #1 resolves this.

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
| **WhatsApp** | `sha256(chat title)[:16]` → `wa_…` | the contact is renamed, or the title is formatted differently by the two dialects |
| **Email** | `Message-ID`, else `uid:<UIDVALIDITY>:<UID>` | the server bumps `UIDVALIDITY` — every key in the mailbox changes at once |
| Telegram / Messenger | read straight from the export | (stable) |

WhatsApp's `message_key()` also hashes the **body**, so an edited message, a changed media
placeholder or a locale difference duplicates that one row even when the thread id holds.

**Debugging it later:** compare `count(DISTINCT t.key)` against the number of conversations
the export claims. A doubled count with identical titles is this. The fix is a stable
surrogate — persist `(platform, title-or-participants) → chat_id` in `store/profile/` and
reuse it, the way `identity.json` already persists the Owner — not a change to the hash.

## Known issues in the real store

- `Facebook user` spans 31 Messenger threads — a placeholder Correspondent by design.
- **One thread holds 707 messages** (`Bode Bradshaw`, a Messenger group). The Viewer pages,
  so this is fine, but it is the test case. The largest `Facebook user` thread is 252.
- Hostinger sent mail has no `Message-ID` (133 of 221) — keyed by `uid:<UIDVALIDITY>:<UID>`.
- **147 threads have no Correspondent edge.** 135 are Telegram strangers with a `sender_id`
  and no name — fixed at the source, so a re-ingest clears them. 12 are Messenger
  `Facebook user` threads.
- **Messenger's 70 group threads are all owner-silent** and hold 9,513 of 10,605 messages.
- **LinkedIn has 205 threads and 0 groups.** The adapter computes `is_group`, but no gate is
  warranted until a real group export appears.
- **Email: 68 threads, 44 owner-silent, largest silent thread is 2 messages.** The 10+
  spam rule drops nothing today; it exists for a real mailbox.
- **Four LinkedIn Correspondents are whole recipient lists, not people** — 160 to 672
  characters, e.g. `Nigel Harrison,Anat Malkin,Christian Davis,…`. `_split_recipients()`
  splits on `;` only, deliberately, because `TO` also contains names with credentials
  (`Steve Mikano CIA, AIC-M, AINS, SSBB`). A comma-separated list with no semicolons
  therefore becomes one node. `canon.split_list()` now implements the separator heuristic
  (comma with no space = list; comma with a space = inside a name), but the LinkedIn
  adapter does not call it yet.

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
