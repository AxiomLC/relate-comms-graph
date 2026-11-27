# HANDOVER.md

**What is next, and what just landed.** Not an app guide — that is `TECHREADME.md` (backend)
and `UIREADME.md` (UI). Fixed work gets one line; pending work keeps its detail.

---

## Where it stands

`pytest tests -q` → **587 passed, 10 skipped, 1 known failure** (`canon` camelCase split,
pre-existing). App runs: `start.bat` → `127.0.0.1:8100`.

**No store counts are recorded here on purpose.** The spool is re-ingested constantly, so any
number written down is stale by the next run. Ask the store instead:

```python
tools.evidence_counts()          # or: MATCH (n:<Kind>) RETURN count(n)
```

> **Wipe before measuring.** `delta=False` re-processes but does not delete, so a rebuild over
> an existing store keeps the old world's nodes and every count is inflated.

**Built and working:** seven platform legs, body-entity extraction (Place / Organization /
Product), delta ingest, BM25 + vector search with name matching and body screening, the job
registry, the MCP surface, and the spool scaffold.

---

## Next

### 1. Test the chat's tool use, and try to break it

The local LLM chat is wired and answering but **never exercised end to end on a real
conversation**. Two things to check:

- **Does it pick the right tool?** `_CHAT_TOOLS` is 6 of 19. Ask it things that need
  `thread_arc` after a search, and see whether one round is enough.
- **`MAX_TOOL_CHARS` truncation must be reported, not silent.** A summarised tool result
  that looks complete is how a wrong answer gets believed.

**Known defect:** `_run_turn` pops `tools` before the second pass, so `search → thread_arc`
can never happen. And a think-only response returns `""` — an empty bubble, no error.

### 2. Try to jailbreak the MCP surface

The MCP server is built and gated by two keys. **Nobody has attacked it.** Worth trying:

| Attack | Expected result |
|---|---|
| `ingest(paths_in=["C:/Windows"])` | refused — outside the repo |
| `run_cypher` with `CREATE` on the read key | refused — `write_enabled` is false |
| `run_cypher` with a write form the regex misses | **this is the one to find** |
| `ingest(email=["email"])` then read the response | no password in it |
| `truncate_store` without `confirm` | refused |
| a second `ingest` while one runs | refused with a sentence, not a lock error |

The guard on `run_cypher` is **a pattern match, not a parser**. Finding a write form it does
not recognise is the highest-value result of this exercise.

### 3. Verify nothing ingests attachments or media

**No adapter reads media** — that is an invariant, and it should be proved rather than
assumed. Check:

- a Telegram export with a `photos/` tree: the copy excludes it, the parse ignores it
- a Messenger zip with images: attachment *metadata* lands, bytes never do
- `spool/real/` after an ingest: no binary files
- `Attachment` nodes: `sha256` is null for every text-only export

### 4. Evaluate body-entity quality on the real email

The 226 real Hostinger messages are the first non-sample corpus. Worth asking:

- Are the Places real places, or is `en_core_web_sm` guessing from sentence shape?
- Do any Organizations come from a long newsletter? (`DOCUMENT_CHARS = 2000` guards this.)
- Is `mention_count: 1` the tail it should be, or is the dictionary missing names?
- **The canvas is not the instrument** — query `MATCH (p:Product) WHERE p.mention_count >= 2`.

---

## Open decisions

- **The platform filter narrows the AI chat as well as the search bar.** Deliberate,
  overriding the earlier "UI state never narrows an agent's query" rule. The alternative is a
  per-call `platforms` argument instead of module state in `tools.py`.
- **Per-node gravity is not a fcose feature.** Big threads can only be approximated as
  anchors via lower `nodeRepulsion`. The dominance leash was designed and withdrawn.
- **The Outlook fingerprint can merge two genuinely distinct messages** — same thread, same
  second, byte-identical body, different senders. Accepted: the alternative is every sent
  message appearing twice, which the real file exhibits.
- **Entity extraction is English-only in v1.** Silence beats a wrong node, and the seam sits
  above the extractor so a second language is a second model, not a rewrite.
- **A `Product` may take a span the model called `GPE`/`FAC`/`LOC`/`PERSON`, but never
  `ORG`.** Asymmetric on purpose: `Grafana Labs` contains `Grafana`, and demoting it would
  lose the organisation.
- **`merged_by` has two sources that disagree.** `writer` sets it at write time; `link` can
  only `coalesce` into it. The link-time reason is in `report["merged_by"]` only. Fixing it
  means deciding which is canonical.
- **One mailbox at a time.** The key is `email:<chat_id>:<message_id>` and `chat_id` carries
  no mailbox, so two mailboxes would share a namespace and silently merge. Switching wipes
  the `email` rows first — see `_run_ingest`.

---

## Latent — a re-export can mint a whole new thread

**Not a bug today, because nothing has been re-ingested. It will bite on the first one.**

A thread's identity is `platform:chat_id`, and three platforms *derive* `chat_id` rather than
read it from the export. If the derivation input changes between two exports of the same
conversation, the thread key changes, and because `message_key()` hashes `chat_id` as its
first component, **every message in it gets a new key too**. Result: the conversation exists
twice, with no error and no warning.

| Platform | `chat_id` derived from | Changes when |
|---|---|---|
| **LinkedIn** | `sha256(CONVERSATION ID)[:16]` → `li_…` | LinkedIn re-issues conversation ids on some archive regenerations |
| **WhatsApp** | `sha256(chat title)[:16]` → `wa_…` | the contact is renamed |
| **Email** | `Message-ID`, else `uid:<UIDVALIDITY>:<UID>` | the server bumps `UIDVALIDITY` — every key in the mailbox changes at once |
| Telegram / Messenger | read straight from the export | (stable) |

**Debugging it later:** compare `count(DISTINCT t.key)` against the number of conversations
the export claims. A doubled count with identical titles is this. The fix is a stable
surrogate — persist `(platform, title-or-participants) → chat_id` in `store/profile/` and
reuse it, the way `identity.json` already persists the Owner.

---

## Known issues in the live store

- **6 threads have no Correspondent edge — all Outlook.** Correct by design: the `.pst`
  fixture is a single-account demo mailbox, so every message is `is_self`.
- **`Facebook user` spans Messenger threads** — a placeholder Correspondent by design, and
  platform-scoped so it never merges with LinkedIn's `LinkedIn Member`.
- **LinkedIn recipient lists can become one node.** `_split_recipients()` splits on `;` only,
  deliberately, because `TO` also contains names with credentials (`Steve Mikano CIA, AIC-M,
  AINS, SSBB`). `canon.split_list()` implements the separator heuristic but the adapter does
  not call it yet.
- **`merged_by` says `exact_name` on every merged node**, not `fuzzy`, even where the fold was
  fuzzy. Two sources, one field — see Open decisions.

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

## Done — recent, one line each

Only what changed the shape of the app. Older history is `git log`.

- **2026-11-26** — **MCP surface built.** `app/mcp/` — two keys in `store/profile/mcp.json`
  (`read_key` 16 tools, `write_key` 21), stdio only, repo-root path rule, heartbeat and
  activity trace shared with the app through two files. `python -m app.mcp`. The title bar
  shows a yellow pulsing **MCP being accessed** badge.
- **2026-11-26** — **Job registry.** `POST /api/ingest` returns a job id in milliseconds and
  the work runs on a thread. Fixes the MCP client timeout on a long ingest and the
  `storage locked` collision when a second surface touched the store.
- **2026-11-26** — **Email: one mailbox, no provider table.** Deleted `ENV_ACCOUNTS` (11
  providers) and every lookup built on it. One block: `IMAP_EMAIL/PASSWORD/HOST/PORT`.
  **The bug this fixed:** `w57th.agency` resolved to the pseudo-provider `custom`, which
  raised — and the error was printed to stderr and swallowed, so the ingest reported success
  with **zero messages and no error**.
- **2026-11-26** — **Mailbox change wipes first.** Switching the address deletes every
  `email` row before reading the new mailbox, because the key carries no mailbox and the
  delta watermark is shared. Credentials are written only after the run succeeds.
- **2026-11-26** — **Spool scaffold.** `paths.SPOOL_SCAFFOLD` is the one definition of an
  empty spool, mirroring `sample_writer/out/`. `ensure_layout()` and `delete_spool()` both
  call it, so a wipe leaves the scaffold rather than a skeleton of every directory any
  ingest ever created.
- **2026-11-26** — **Staging replaces on collision.** `Outlook.pst` and `email_eml/` never
  change their name, so a re-export used to be **skipped** — the new snapshot never landed
  and the ingest re-read the old one, forever, silently.
- **2026-11-26** — **Three repo comments were wrong.** `link.py`, `writer.py` and `tools.py`
  claimed Relate cannot parameterise a property name or a label. **Verified by execution:**
  both work on 1.0.1. The code was right; only the justifications were wrong.
- **2026-11-25** — **Search rebuilt.** BM25 default, vector mode, name matching, body
  screening, mode radios. Embeddings are a separate opt-in pass, never part of ingest.
- **2026-11-25** — **`flush_embeddings()` rewrites the store.** Nulling a property frees
  nothing on Relate, so the only way to reclaim is a fresh `.rl`: **64.7 MB → 3.6 MB in
  1.9 s**, every node and edge kept. Guarded by a fidelity test.
- **2026-11-24** — **Entity lists loaded; three extraction bugs fixed.** Places 97 → 691,
  Organizations 26 → 585, Products 92 → 764. The load exposed a short entry truncating a
  longer name, products never in the `EntityRuler`, and `NORP` dropped outright.
- **2026-11-23** — **Extraction rework: Product leg, message-anchored mentions.**
  `MENTIONS` moved from Thread to Message; `Thread → Entity` became a read-time projection.
- **2026-11-22** — **Incremental ingest** (delta, 10× on a weekly case); drag and drop
  rebuilt on `uppie` so a folder drops correctly.
- **2026-11-21** — **Merged bag built and centred**; theme persistence changed to
  **overrides-only**; `shadow-*` and halo occlusion settled as impossible.
- **2026-11-19** — Canvas bags landed; naming settled (`canon.KINDS`); `link.py`
  cross-connect; `Correspondent.key = person:<canonical>`.
