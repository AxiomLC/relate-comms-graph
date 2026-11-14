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
tools/                   dev-only: bench_ollama, create_dummies (moving out)
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
| 2 | **Canonical schema + Telegram adapter + Relate writer** | Ingest twice → identical counts | 2 |
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

- Spool to `C:/Users/q1fre/relate-spool/`, not `Downloads`.
- Delete the spool after ingest; `archive_copies: false` — parse in place, keep hashes.
- **Never** demo from a live-authenticated session.

### 9.1 Ingest is unattended — daily, with 3-day pruning

**The download is one bulk export (all chats).** No per-chat point-and-click. Asking a real
Telegram user to export 500 chats by hand is not a product; the whole-account `result.json`
is one click and contains every chat (verified 2026-11-14: a single-chat export is a
message-for-message subset of the bulk file, same `Message.key`, byte-identical rows).

This runs on a schedule, not in a session:

1. **Daily** — drop an export in `C:/Users/q1fre/relate-spool/`, ingest it, merge into the store.
   Re-ingest is safe: `Message.key = platform:chat_id:message_id` makes it idempotent.
2. **Verify, then prune at 3 days** — a spool file is deleted only after its key set is
   confirmed present in the store (`writer.verify_present`), not merely "the job exited 0".
3. **Bloat is bounded by design** — the spool never accumulates beyond ~3 days of exports,
   and the store holds one row per message key, never a copy per ingest.

Unverified spool files are **never** pruned. A failed verify leaves the file for inspection
and logs a visible refusal — same policy as the scrub gate (§3.2).

Telegram Desktop has no scheduler, so the export is the one manual step; everything after the
file lands is unattended.

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

`tools/create_dummies.py` scrubs real exports into fixtures. Two leaks were found by testing,
both worth remembering:

1. A name can appear **inside a message body**, not just in `from`. Fixed with a two-pass scrub:
   collect every real name, then replace those names inside all free text.
2. **`text_entities` of type `plain` carries the whole body verbatim.** Skipping them as
   "harmless" leaked the body of every media row. Scrub every entity type, `plain` included.

Fixture size is capped by ranking chats on **shape diversity, not volume** — three odd rows teach
a parser more than a hundred plain texts. `--check` parses both fixtures back through the adapter.

---

## 10. Handover — 2026-11-14, after stage 2

**Status:** Stage 2 complete. Canonical `Message`, Telegram adapter (both export shapes), Relate
writer with `verify_present`, owner identity, tool layer scaffold, `app/` scaffold, `pyproject.toml`.
**10 tests passing**, including ingest-twice-identical-counts and bulk-vs-single agreement.

### What stage 2 actually taught us (beyond the spec)

Real exports from this account were read, not just documented. Findings that changed the design:

| Finding | Consequence |
|---|---|
| `personal_information: null`, no Saved Messages | Owner must be **inferred and persisted**. See §9.2 |
| Inferring the owner per-file made `is_self` flip between exports | Caught by a failing test. Fixed by `identity.py` + `.profile/` |
| `text_entities` present on all 1215 rows, incl. `plain` wrapping whole bodies | Body comes from `text`; entities are a signal, never the source |
| Service rows carry `actor`/`actor_id`, never `from` (344/1215) | Sender falls back to actor |
| Entity types include `cashtag`, `mention_name`, `plain` — undocumented | Handler must not KeyError on unknown types |
| `date_unixtime` missing from one export, present in another | Both paths required; `date` is local with no offset |
| Single-chat export is a byte-identical subset of the bulk one | One bulk download replaces a per-chat loop — §9.1 |
| `db.index.vector.queryNodes` works natively | Semantic search needs no sidecar — §5.4 |

### Then, in order

1. **Stage 3** — WhatsApp `.txt` (Android dialect, U+200E LTR mark before media lines). Needs a
   real file first, per §6. Then `sample_data/generators/whatsapp.py`.
2. **Move `tools/create_dummies.py` into `relate_comms/sample_data/`** so it ships and is
   reachable as `python -m relate_comms sample build` (§5.3).
3. **Stage 4/5** — resolution and scrub gate. Until these land, `Person` does not exist, so
   the UI's person-centric tools have nothing to read.
4. **`ingest.py` + `cli.py`** — the shipped pipeline and `--source real|sample` toggle.
5. `tools/bench_graph.py` to run `bench_queries.json` against Relate and Neo4j Cloud.

### Loose ends
- `tools/bench_ollama.py` **stalls at `ollama.create`** — known broken, low priority (MoE already gave the speed).
- `num_thread` unmeasured. Theory says 6 on 4P+8E. Not blocking.
- Verified tok/s came from 8 easy messages; re-test on ~50 real redacted ones before trusting it.
- **Redaction policy for a public repo — settled for fixtures** (see §9.3: two-pass scrub, scrub
  `plain` entities, `--check` round-trip). Still open for any future `fixtures/real/`: none exists
  today and none is planned.
- `Person` nodes do not exist until stage 4, so person-centric UI tools have nothing to read yet.
