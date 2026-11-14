# buildNOTES.md

Working notes. Decisions live here; history doesn't. Supersedes `docs/` where they disagree.
Updated 2026-11-14.

---

## 1. What this is

> A local, private window into every conversation you've ever had — across every app —
> laid out as one connected graph you can walk and question, which never leaves your machine.

Your messages already **are** a graph: sender → message → thread → reply. That's fact, not a
model's guess. The graph is shredded across five apps, so nobody can answer *"who did I talk
to about X on more than one platform, and when did it stop?"* The answer exists and is
currently invisible.

**The lure:** safe, sandboxed, personal, local AI you can traverse. This is a Neo4j **Relate
Hackathon** entry (theme *"Context, Connected"*, closes **2026-12-11**).

---

## 2. Settled facts

### 2.1 Relate works here — Stage 0 done

`relate-db 1.0.1`, native Windows wheel, DB-API 2.0. Verified by `tools/verify_relate.py`:

- `MERGE` is idempotent (two runs, still 1 Person / 1 Message)
- store survives process restart
- `Vector` and `Path` are native types
- **takes a plain filesystem path, not a `file:` URI** (that fails, OS error 123)

Storage: **single `.rl` file** — inspectable by judges, portable. `store/` is gitignored.

### 2.2 Hardware reality

**i5-12500H, 4P+8E / 16 threads, 16 GB LPDDR5 (soldered, not upgradeable), Iris Xe 80 EU, no
dGPU.** The old `docs/llm-models.md` assumed an i7-6600U with 2 cores — its pessimism is void.

The iGPU is useless for this: 80 EU, no XMX, and it shares the **same** LPDDR5 bus, so it has
zero bandwidth advantage. Decode is bandwidth-bound. Force CPU (`OLLAMA_VULKAN=0`).

### 2.3 Local LLM — measured

See `HowToRunOllama.md` for the runbook. Headline numbers, 8 sample messages, CPU only:

| Model | JSON | Median | Decode |
|---|---|---|---|
| `qwen3.5:4b` | 8/8 | 4.12 s | 8.5 tok/s |
| **`lfm2.5:8b`** | 8/8 | **1.99 s** | **21.3 tok/s** |

`lfm2.5:8b` is MoE, ~1B active per token, so it reads 1/8 of the weights per token — **the
default**. `qwen3.5:4b` kept for `thread_summary` and `semantic_pii`, where consistency beats
speed. Both set in `relate_comms/models.py`.

- **`think: false` is a 28× speedup** (368 tokens → 10 for "hello"). `/no_think` in the
  system prompt does **not** work on Qwen3.5 — tested, no effect.
- **Caveat:** 8 easy messages is not a benchmark. Untested on messy input.

### 2.4 Hermes cannot supply WhatsApp history

`config.yaml` is in `bot` mode, `bridge.js` sets `syncFullHistory: false`, and no message store
exists — it's a long-poll fan-out, not a recorder. WhatsApp has no REST history API, so history
can never be backfilled. **The session is reusable for forward-only capture; that is not in scope.**

### 2.5 No public multi-platform dataset exists

Verified: no public corpus has the same people on 2+ platforms with message text. Copenhagen is
metadata-only by design; Enron is real identifiable people (inventing their DMs would sink a
privacy project); leaked WhatsApp dumps are non-consensual. **The demo corpus must be generated** — §6.

---

## 3. Architecture

Relate is the durable layer. Parsing → resolution → scrub → write.

```
Telegram result.json ─┐
WhatsApp _chat.txt  ──┤
Messenger takeout   ──┼──► Message{platform, chat_id, msg_id, ts_utc,
SMS BR XML          ──┤              sender, body, reply_to, attachments}
Email IMAP/.eml     ──┤              │
LinkedIn csv/API    ──┘              ├─► resolve/  phones→E.164, email→lower, rapidfuzz
                                     └─► scrub/    keep | hide | block
                                                    │
                                                    ▼
                                          Relate .rl file
```

### 3.1 Schema

```cypher
(:Person     {key, display_name, first_seen_utc, last_seen_utc})
(:Identity   {key, platform, handle, phone_e164, email, display_name})
(:Thread     {key, platform, title, is_group, participant_count})
(:Message    {key, platform, chat_id, message_id, ts_utc, body, has_attachments, is_self})
(:Attachment {key, filename_scrubbed, mime, sha256, size})
(:Place | :Company | :Product {key, name})

(:Person)-[:SENT]->(:Message)
(:Person)-[:MATCHED_BY]->(:Identity)     // exact key, confidence 1.0
(:Person)-[:POSSIBLY]->(:Person)         // fuzzy name, 0.4–0.8
(:Message)-[:IN]->(:Thread)
(:Message)-[:REPLY_TO]->(:Message)
(:Message)-[:MENTIONS]->(:Place|:Company|:Product)
```

- **`Message.key = platform:chat_id:message_id`.** Never an array index or timestamp — this is
  what makes re-ingest idempotent.
- **Two resolution edge types, never one.** A wrong guess must *look* like honest uncertainty.
- **`ts_utc` everywhere.** Telegram and WhatsApp export local time with no offset. Convert at
  parse, or the timeline lies.
- **Messages are atomic — do not chunk them.** One message is already one node, under 500 chars.
  Chunking exists for documents. Topics attach via `MENTIONS`.

### 3.2 Scrub gate

Runs **after** resolution (keys are needed for joins), **before** the write. Verdict per class:
`keep` / `hide` (stable alias `PHONE-1`) / `block` (refuse + log).

- Alias→real mapping is a re-identification key: **memory-only** by default.
- **Append-only, visible refusal log.** Unknown message types (polls, stickers, calls, system
  events) are counted and reported, never dropped.
- Scrub attachment filenames too.

The evidence panel — *"we withheld 14 phone numbers, 6 addresses, 3 attachments"* — **is the
hackathon entry**.

---

## 4. Scope

**In:** Telegram, WhatsApp, Messenger, SMS, Email (IMAP), LinkedIn.

| Platform | Route | Latency |
|---|---|---|
| Telegram | Desktop export → `result.json` (**only officially documented schema**) | minutes |
| WhatsApp | Per-chat `.txt` export, media off | manual |
| Messenger | Facebook → *Download your information* → JSON | hours–day |
| SMS | SMS Backup & Restore → XML | minutes |
| Email | IMAP read-only, `UID FETCH` | live |
| LinkedIn | `messages.csv` (category-scoped, minutes) + **DMA API** if EU | minutes |

**Out — removed from the code path:**
- **Slack** — export needs workspace admin (not available), and it's team-oriented. Would be the
  one importer testable only synthetically.
- **iMessage / Signal** — platform-locked, no Windows path.
- **Live Baileys recorder** — forward-only, and account reputation isn't ours to spend.

**LinkedIn note:** the **EU DMA Member Data Portability API** (`INBOX` snapshot + `messages`
changelog, self-serve, free, instant) is legitimate and documented — but **EU/EEA/CH only**, by
profile location. The `messages.csv` importer ships regardless, same data shape. All scraping
routes are rejected: the `linkedin-api` Voyager repo is **deleted (404)**, and the best public
Playwright exporter self-reports corrupt InMail export.

**Frequency:** LinkedIn and Messenger are **lumps, not syncs** — `spool/` folder drained, full
re-import, dedupe on stable key. A relationship graph barely moves day to day; weekly/monthly is
functionally equivalent to daily.

---

## 5. UI

**The graph is the proof; the UI is the pitch.** It must look like something you'd open daily.

```
┌──────────────────────────────────────────────────────────────────┐
│  ● OFFLINE · nothing leaves this machine          [evidence ▸]   │
├───────────────┬──────────────────────────────────────────────────┤
│ PEOPLE        │   Dave Sartori                                   │
│ ● D.Sartori   │   WhatsApp · Telegram · Messenger · SMS          │
│   mat 3 ●●●   │   ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░┊ quiet 2y      │
│               │                                                  │
│ ● M.Chen      │   "worked together → went quiet"                 │
│   mat 2 ●●    │                                                  │
│               │   ┌──────────── timeline ─────────────────┐      │
│ ● J.Okafor    │   │ 22 ▂▅▇▆▃▂▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁  25 │      │
│   possibly    │   └───────────────────────────────────────┘      │
│               │   [ask: who did I talk to about … ]              │
└───────────────┴──────────────────────────────────────────────────┘
```

- **Offline badge always visible** — top of app, not a settings page.
- **`POSSIBLY` renders differently** (dashed/amber) from `MATCHED_BY` (solid).
- **Show the Cypher.** The ask box translates a question, displays the query, Relate answers.
  Trust through transparency, not promise.
- **An arc, not a list** — "met → worked together → went quiet" generated from the graph.
- Stack: local web app (FastAPI + single HTML) so judges can clone and see it.

### 5.1 Layout — `app/`, not `relate_comms/`

```
app/                     the UI — local only, no outbound calls
  chat/                  local LLM, same tools, write toggle
  graph/                 3D view data, node/edge type toggles
  search/                cypher | semantic | hybrid
  mcp/                   same tools over MCP, auth + write toggles
  static/                single-page 3D frontend
relate_comms/            library — importable with no web server
  adapters/              one module per platform
  sample_data/           generators + generated/ (gitignored)
    generators/          telegram.py done; others TODO until real payloads exist
  search/                semantic + hybrid helpers
  tools.py               THE tool layer: read / write / destructive
  paths.py               data root, spool, store, profile, fixtures
  schema.py  writer.py  identity.py
  ingest.py  cli.py      (planned) the shipped pipeline + `python -m relate_comms`
tests/fixtures/          pinned inputs; committed; never regenerated in place
tools/                   dev-only: bench_ollama, bench_queries.json
```

The UI is a **consumer** of the library. `app -> relate_comms`, never back, so
importing the library never pulls in FastAPI or a web server.

### 5.2 The tool layer is singular

Every capability is a plain function in `relate_comms/tools.py`. Three surfaces
bind the same functions:

| Surface | Binds | Notes |
|---|---|---|
| UI buttons / search | HTTP | no outbound calls |
| Local chat | Ollama, loopback | **no cloud path exists** — unconfigured means the box is hidden |
| MCP | stdio / loopback HTTP | ships; flagged dangerous; recommended with a local model from an IDE |

If a tool works in the chat box it works over MCP, because it is the same
function. This is the only structure that makes "UI has the same tools as MCP"
true rather than aspirational.

**Write safety is a user toggle, not an architectural limit.** `Access.READ`
is always allowed; `WRITE` needs that surface's toggle; `DESTRUCTIVE` needs write
*and* `confirm=true` in the call, so `prune_spool` does not run because a model
decided to tidy up. The UI toggle and the MCP toggle are independent — an IDE
session does not inherit UI choices.

### 5.3 Data locations

| What | Where | Committed |
|---|---|---|
| Real exports | `~/relate-comms/spool/` (`RELATE_DATA_ROOT`) | never |
| Graph store | `~/relate-comms/store/graph.rl` | never |
| Owner identity | `~/relate-comms/profile/identity.json` | never |
| Generated samples | `relate_comms/sample_data/generated/` | no — reproducible |
| Test fixtures | `tests/fixtures/` | **yes** |

Ingest selects a source: `--source real|sample`. Sample data ships as a
generator (`python -m relate_comms sample build`) rather than as files, so a
developer can inspect and reproduce it before pointing the app at their own
comms. Test fixtures are pinned separately so a parser change cannot be "fixed"
by regenerating.

### 5.4 Semantic search is native

Verified 2026-11-14 against Relate 1.0.1:

```cypher
CREATE VECTOR INDEX vidx FOR (n:Msg) ON n.emb
  OPTIONS {indexConfig: {`vector.dimensions`: 384,
                         `vector.similarity_function`: 'cosine'}}

CALL db.index.vector.queryNodes('vidx', 10, $embedding)
  YIELD node, score RETURN node, score ORDER BY score DESC
```

Returns correctly ranked results (`alpha` 1.0, `alphabeta` 0.9969). **No sidecar
index needed.** There is no inline `cosine_similarity()` scalar function, so
distance is only available through the index — which is why hybrid search is
written as "vector query, then traverse" rather than "compute similarity".

### 5.5 The speed claim needs an artifact

`tools/bench_queries.json` holds the comparison set: same Cypher, Run against
Relate locally and against the Neo4j Cloud app. Four tiers — lookup, traversal,
aggregate, vector — because measuring one tier flatters whichever engine wins it.

Rules: warm up 3, measure 20, report median and p95 (not mean). **A result is
only valid if `rows_returned` matches between engines.** A different answer is a
correctness bug, not a speed finding.

---

## 6. `gen-comms-pipe` — the demo corpus

**Rule: real payloads first. Verify them. *Then* generate to those exact schemas.**

This order is not negotiable, because it removes both ways synthetic data launders a bug:
the generator can't drift from reality (it was written after the real file), and the parser
can't be tuned to fiction (it was graded by the parser, not the reverse).

```
dataset/
  canon.yaml      people, scenes, places, companies, products, arcs, events — hand-authored
  phrases/        frozen LLM-generated phrase bank, checked in, no model at run time
  generate.py     seeded (--seed 42) → deterministic, byte-identical
  writers/        telegram.py whatsapp.py sms.py messenger.py email.py linkedin.py
  out/            committed corpus, ~2k messages, 40 people
```

- Emits **only** formats captured in stage 1. If a field wasn't in the real file, don't invent it.
- `Place` / `Company` / `Product` come from `canon.yaml`, not from the LLM.

**Video policy — two things kept apart, and stated on camera:**

| | Ingested from | On camera |
|---|---|---|
| Proof it works on real data | live accounts | yes — counts, refusal log, no bodies |
| Graph walkthrough | `dataset/out/` | yes — every visible node and edge |

Say the switch out loud in one sentence. *"Real for fidelity, generated for disclosure."* Judges
are Neo4j staff and will ask.

---

## 7. Human-in-the-loop replies (future — schema only)

- `(:Draft {key, body, model, created_utc, status})`, `status ∈ pending|approved|sent|rejected`
- `(:Message)-[:DRAFTED_FROM]->(:Message)` — provenance on anything AI-written
- **Hard gate: nothing sends without explicit human approval.** No exceptions.
- Outbound transports: IMAP in, **SMTP out**. WhatsApp/Telegram outbound stays off.
- Ships as `plugins/reply/`, never imported by core.

---

## 8. Build order — to 2026-12-11

| # | Stage | Done when | Days |
|---|---|---|---|
| 0 | ~~Install Relate~~ | ✅ done | done |
| 1 | **Real payload capture** — one small export per platform, redacted → `fixtures/real/` | Files on disk + field notes | 1 |
| 2 | ~~Canonical schema + Telegram adapter + Relate writer~~ | ✅ done | done |
| 2b | ~~**UNWIND batching in writer**~~ | ✅ done — 64 → 7,000 msg/s, still idempotent | done |
| 2c | **`ingest.py`** — parallel parse, serialised write, `--source real\|sample` | Same graph from sample and real | 1 |
| 3 | WhatsApp `.txt` adapter | Same person in both platforms | 1.5 |
| 4 | Resolution — E.164, lowercased email, `rapidfuzz` | One Person on 2+ platforms | 1.5 |
| 5 | Scrub gate + refusal log | Flip `phones: block` → same shape, PII gone | 2 |
| 6 | SMS + Email | Four platforms, one Person | 2.5 |
| 7 | Messenger + LinkedIn | Six platforms | 2 |
| 8 | `gen-comms-pipe` | Round-trip: our writer → independent parser → same graph | 3 |
| 9 | UI | Someone says "oh" | 4 |
| 10 | Ollama enrichment | "Who did I talk to about X" works | 3 |
| 11 | *(optional)* LinkedIn DMA importer, EU-gated | Same parser serves CSV and API | 1 |
| 12 | Video + README (must answer: how/why Relate, which storage mode) | Submitted on Devpost | 2 |

---

## 9. Getting real payloads

**Gate:** fixtures → redacted 100-message sample → full archive. Never a full archive first.

| Platform | How | Watch out |
|---|---|---|
| Telegram | Settings → Advanced → Export → JSON | **Plaintext on disk.** Full export covers every chat at once — no per-chat clicking. |
| WhatsApp | Per-chat → Export chat → `.txt`, media **off** | Manual, one chat at a time |
| Messenger | Facebook → *Download your information* → JSON | **Slow — start it first** |
| LinkedIn | Data privacy → *Download larger archive*, **Messages only** | Lands in minutes, not 24 h |
| SMS | SMS Backup & Restore → XML | Per-row, no threads — group by address + date |
| Email | IMAP read-only, `UID FETCH` | Gmail needs an **App Password** |

- Spool to `~/relate-comms/spool/` (`RELATE_DATA_ROOT`), not `Downloads`.
- Delete the spool after ingest; `archive_copies: false` — parse in place, keep hashes.
- **Never** demo from a live-authenticated session.

### 9.1 Ingest is button-driven, with 3-day pruning

**The download is one bulk export (all chats) for Telegram.** No per-chat point-and-click there;
the whole-account `result.json` is one click and contains every chat (verified 2026-11-14: a
single-chat export is a message-for-message subset of the bulk file, same `Message.key`,
byte-identical rows). Other platforms differ — see §9.1.3.

Pipeline and housekeeping:

1. **Ingest** — user drops exports in `~/relate-comms/spool/` and presses Ingest (or `ingest.py`).
   Re-ingest is safe: `Message.key = platform:chat_id:message_id` makes it idempotent.
2. **Verify, then prune at 3 days** — a spool file is deleted only after its key set is
   confirmed present in the store (`writer.verify_present`), not merely "the job exited 0".
3. **Bloat is bounded by design** — the spool never accumulates beyond ~3 days of exports,
   and the store holds one row per message key, never a copy per ingest.

Unverified spool files are **never** pruned. A failed verify leaves the file for inspection
and logs a visible refusal — same policy as the scrub gate (§3.2) and §9.1.1's demotion of cron.

### 9.1.1 Auto-ingest — demoted

Auto-ingest on cron exists but is **not the shipped path**. Only email is genuinely frictionless
(IMAP `UID FETCH` with an app password); everything else needs a manual export, so a scheduler
buys nothing but new failure modes. **Email auto-ingest is a one-liner; the rest is button-driven.**

That is not a limitation to hide — it is the shape of the platforms, and the UI owns it below.

### 9.1.2 Delta, not re-parse

**First ingest** is expensive: full parse, full flatten, full write. **Every ingest after that**
should only apply what is new. `Message.key = platform:chat_id:message_id` makes that possible —
a row whose key is already in the store is skipped before its body is touched.

| Platform | True delta available? | Method |
|---|---|---|
| Email | **yes** | IMAP `UID FETCH` since last UID — the one cron job |
| SMS | yes | SMS Backup & Restore writes a *scheduled* local XML; watch the folder |
| WhatsApp | yes, via key | `msgstore.db.crypt15` + the user's own key, decrypted offline |
| Telegram | no — full archive every time | re-parse, delta *write* (cheap) |
| Messenger / LinkedIn | no | full export, delta write |

**Correction to an earlier assumption (research 2026-11-14):** "WhatsApp is manual export only"
was wrong. The official *Request account info* export genuinely contains **no messages** — but a
local `msgstore.db.crypt14/15` plus the user's own 64-hex key decrypts entirely offline. No
root needed; no session, no account contact, no ban risk.

**WhatsApp bulk export, verified by research 2026-11-14:** `KnugiHK/WhatsApp-Chat-Exporter`
(desktop Python CLI, MIT, active) is the only tool covering *all chats* × *date range* × *chat
selection*, offline. `--date "A - B"`, `--include`/`--exclude`. **Not yet run on this machine** —
flags come from the repo, not from testing. The 64-digit key is a single point of failure: lose it
and `.crypt15` is unreadable forever.

Other corrections worth keeping: **SMS is the best automation case** — scheduled local XML, plain
SQLite, zero ToS surface. **Telegram `tdata` is a dead end** — official maintainers state it holds
no messages, only media/settings cache. **Messenger, Instagram, LinkedIn and Telegram have no
legitimate offline auto-extract**; automating their endpoints needs a live session, which §4
rejects.

Each parser accepts *either* a raw official export *or* a decrypted DB as first-class input.
That decouples ingestion from extraction and keeps every demo offline.

**Measured cost** (`tools/bench_scale.py`, now calling the real writer): ~**1,460–1,500 bytes per
message** in the store. Per-row `MERGE` ran at 133 msg/s (1k) degrading to 64 msg/s (10k); the
batched path runs at **~7,000 msg/s and is linear**. 60k messages ≈ 9 s; 200k ≈ 30 s.

| msgs | per-row (old) | UNWIND (now) |
|---|---|---|
| 1,000 | 7.5 s | **0.13 s** |
| 10,000 | 156 s | **1.33 s** |
| 20,000 | ~10 min | **2.87 s** |

Batching is `BATCH_SIZE = 500` rows per statement. Idempotency is unchanged — every statement is
still a `MERGE` on a stable key, and re-writing adds nothing (verified by test).

### 9.1.3 Ingest UX — one button, one modal

There is **no auto-discovery**. The user brings files to a known folder, then presses a button.

The UI has a single **Ingest** button. It opens a modal:

> **Download your chats to `~/Downloads`, then press INGEST.**
>
> | Platform | Where | Notes |
> |---|---|---|
> | Telegram | Desktop → Settings → Advanced → *Export Telegram data* → JSON, media off | one click, every chat |
> | WhatsApp | Per chat → ⋮ → *More* → *Export chat* | one chat at a time; for **all** chats use the advanced Python route below |
> | Messenger | <https://accountscenter.facebook.com/info_and_permissions/dyi> → *Messages* → JSON | 4-day expiry on the link |
> | LinkedIn | <https://www.linkedin.com/mypreferences/d/download-my-data> → choose **"Download larger data archive…"** (top radio, *not* the basic one) → *Request archive* | `messages.csv` is bundled inside; up to 24 h |
> | Email | IMAP host + app password in settings | only genuinely automatic source |
> | SMS | SMS Backup & Restore → XML to a local folder | Android only |
>
> **Advanced — WhatsApp, all chats with a date range:** copy `msgstore.db.crypt15` off the phone
> plus your 64-digit backup key, then run `wtsexporter --date "YYYY-MM-DD - YYYY-MM-DD"`.
>
> Everything stays on this machine. Nothing is uploaded.

The modal is the product's honesty surface: it tells the user exactly what each platform demands
instead of pretending a magic import exists. Two link caveats — the Meta and LinkedIn URLs were
**not verified from this machine** (both are login-walled), so each row also gives a navigation
path to fall back on if a URL rots.

### 9.1.4 Parallel parse, serialised write

The pipeline shape is fixed by one constraint: **`.rl` is a single file with one writer.**

```
  export A ─┐
  export B ─┼─► parse in parallel (process pool) ─► one write queue ─► .rl store
  export C ─┘         I/O + CPU bound                serialised
```

- **Parsing parallelises cleanly.** Six JSON/XML files are independent; nothing is shared.
- **Writing must not parallelise** against the same store. Concurrent writers to one `.rl`
  file is a corruption, not a speed-up.
- So: parse → `IngestResult` objects → a single writer consumes them in order.

**Resolved (stage 2b):** per-row `MERGE` ran at 133 msg/s (1k rows) degrading to 64 msg/s (10k).
`UNWIND $rows AS row` batching with `BATCH_SIZE = 500` now runs at **~7,000 msg/s and is linear**.
A 200k-message corpus ingests in ~30 s. Re-measure with `tools/bench_scale.py --n 20000`.

**Deletions:** a key that vanishes from a *later* full export means the message was deleted on
the platform. Cheap to detect (set difference on keys) and cheap to act on. Not required for the
demo; do it only if it stays cheap. **Message edits need no handling** — we keep the most recent
copy, which is what a re-parse naturally overwrites.

### 9.2 Who is "me" — `relate_comms/identity.py`

`is_self` must not depend on which file was opened. Deriving the owner per-file made the
same message `is_self=True` from the bulk export and `False` from a single-chat export —
caught by a failing test, not by reasoning.

| Order | Source | Trust |
|---|---|---|
| 1 | `self_id=` passed by the caller | absolute |
| 2 | `.profile/identity.json` (persisted) | absolute |
| 3 | `personal_information.user_id` in the file | a fact Telegram stated |
| 4 | `from_id` appearing in the most **distinct chats** | inference — warns |

Real account exports from this machine had `personal_information: null` and no Saved
Messages, so step 4 is the first-run path. It picks the publisher's own id
(`user1426445212`, 47 chats / 347 msgs) and persists it. `.profile/` is gitignored: it is
re-identification material, same class as the alias map in §3.2.

### 9.3 Dummies vs fixtures

Real layout is in §5.1. Two things are worth repeating because they were got wrong once:

- **`tests/fixtures/` is committed and pinned.** It is not where sample data is generated to.
- **`relate_comms/sample_data/generated/` is gitignored**, because it is reproducible. Shipping
the generator rather than the files is what lets a developer inspect and reproduce the data
before trusting the app with their own comms.

`relate_comms/sample_data/build.py` generates both sample payloads and scrubs real exports into
fixtures. Two leaks were found by testing, both worth remembering:

1. A name can appear **inside a message body**, not just in `from`. Fixed with a two-pass scrub:
   collect every real name, then replace those names inside all free text.
2. **`text_entities` of type `plain` carries the whole body verbatim.** Skipping them as
   "harmless" leaked the body of every media row. Scrub every entity type, `plain` included.

Fixture size is capped by ranking chats on **shape diversity, not volume** — three odd rows teach
a parser more than a hundred plain texts. `--check` parses both payloads back through the adapter.

```bash
python -m relate_comms sample build                  # -> sample_data/generated/ (gitignored)
python -m relate_comms sample build --dest fixtures  # -> tests/fixtures/ (pinned)
```

Deterministic: regenerating the same source gives byte-identical output (verified by md5).

---
---

## 10. Handover — updated 2026-11-14 20:35

**Where we are:** stage 2 **and 2b complete** and pushed — Telegram adapter (both export shapes),
batched Relate writer with `verify_present`, identity, tool layer, `app/` scaffold, sample
generation. **11 tests pass.** Nothing below is already built.

**Verify state before touching anything:**

```bash
python -m pytest tests -q                     # expect 11 passed
python -m relate_comms sample build --check   # regenerates samples + round-trips
python tools/bench_scale.py --n 5000          # ingest throughput, measured
```

Real exports live **outside the repo** at `~/relate-comms/spool/` (`RELATE_DATA_ROOT`). If empty,
the 4 real-data tests skip — expected, not a failure.

### Next, in priority order

1. **`ingest.py`** — parse → write → verify, with `--source real|sample`. Parse in parallel
   (process pool), write serialised through one queue (§9.1.4). `cli.py` currently stubs it.
   `writer.write()` is already batched at ~7,000 msg/s, so there is no speed blocker.
2. **Stage 3: WhatsApp `.txt` adapter.** Android dialect, U+200E LTR mark before media lines.
   Real file first (§6), then `sample_data/generators/whatsapp.py`.
3. **Stage 4/5: resolution + scrub gate.** `Person`/`Identity` arrive here. Do **not** treat other
   node types as blocked — `Message`, `Thread`, `Attachment` already work; person-shaped queries
   just return nothing until then.
4. **`tools/bench_graph.py`** — run `bench_queries.json` against Relate local vs Neo4j Cloud.

### Open research questions (spawn a sub-agent)

- **WhatsApp bulk export is researched but unrun.** `KnugiHK/WhatsApp-Chat-Exporter` is claimed to
  cover all chats × date range × chat selection offline. Verify on this machine before building
  an importer against it — `pip install`, check `wtsexporter --help`, confirm the flags.
- **Auto-extraction for the other four.** Research 2026-11-14 found no legitimate offline
  auto-extract for Messenger, Instagram, Telegram or LinkedIn. Any follow-up must prove a tool is
  maintained, offline and account-safe — or it is rejected. Do not plan an extractor until settled.

### Decisions already made (do not relitigate)

| Decision | Why |
|---|---|
| One bulk export, no per-chat clicking | Single-chat export is a byte-identical subset |
| **Auto-ingest demoted to email only** | Only email is frictionless; cron elsewhere adds failure modes |
| **Ingest is one button + one modal** | The modal states each platform's real requirement (§9.1.3) |
| Store is always whole; toggles are view-only | A hidden UI toggle must never narrow an agent's query (§5.2) |
| Write access is a per-surface toggle | UI, chat and MCP each decide independently |
| `prune` needs `confirm=true` | A model must not delete spool files on its own initiative |
| Fixtures pinned, generated samples gitignored | Otherwise a failing test gets "fixed" by regenerating |
| Message edits need no handling | We keep the most recent copy; re-parse overwrites |

### Loose ends

- `tools/bench_ollama.py` stalls at `ollama.create` — known broken, low priority.
- `num_thread` unmeasured; theory says 6 on 4P+8E. Not blocking.
- tok/s came from 8 easy messages; re-test on ~50 real redacted ones before trusting it.
- **Fixtures keep real timestamps.** Names/bodies/ids are scrubbed, dates are not. Add a
  per-export date offset if that matters.
- **Relate is embedded with a `.rl` file on disk, not RAM-only.** Measured ~1,460–1,500 bytes/msg
  (thread count barely affects it); 10k msgs ≈ 15 MB. The speed pitch is "no server, no network
  round trip", not "in memory".
