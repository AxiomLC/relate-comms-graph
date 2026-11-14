# buildNOTES.md

Working notes. Plain language. Written 2026-11-14, two days into the Relate hackathon.

The polished pitch lives in `README.md`. The original research is in `docs/`. **This file is
where the actual decisions get made**, and it overrides `docs/` where they disagree.

---

## 1. What we are actually building

> A local, private window into every conversation you've ever had — across every app —
> laid out as one connected graph you can walk, ask questions of, and trust because
> nothing ever left your machine.

Three honest sentences on why it matters:

1. Your messages already are a graph. Sender → message → thread → reply. That structure is
   *fact*, not a model's guess. Most AI tools invent structure from prose; we get it free.
2. That same graph is shredded across five apps. Nobody — not WhatsApp, not Telegram, not
   any AI product — can answer *"who did I talk to about X on more than one platform, and
   when did it stop?"* The answer exists in your data and is invisible today.
3. The data is the most sensitive thing you own. So it never goes to a server. Relate runs
   *inside* the app, on your disk.

The lure, said plainly: **safe, sandboxed, personal, local AI you can traverse.** A private
memory palace for your social life. Nobody has that. That is the product.

Two findings changed the plan, and both were verified:

**1. Relate works here — Stage 0 is done.** `relate-db 1.0.1`, native Windows wheel, DB-API 2.0.
Verified restart-durable and `MERGE`-idempotent. One gotcha: it wants a **plain path**, not a
`file:` URI. This was the highest-uncertainty item in the whole build and it's now a green tick.

**2. LinkedIn is back in — and via a legitimate door.** The **Member Data Portability API**
(EU DMA) exposes `INBOX` snapshot + hourly changelog of `messages`. Self-serve, free, instant
access, no partner programme. The catch: **EU/EEA/CH profile location only**. We ship the
`messages.csv` importer regardless, which is the same data shape from the same request.

Everything else that looked like a LinkedIn "hack" is a trap, and the notes say why: the
`linkedin-api` Voyager package's **repo is deleted (404)** and its last PyPI release was Nov 2024;
the best public Playwright exporter **self-reports corrupt InMail export and detection risk**.

Also corrected: **the hardware.** This box is an i5-12500H (4P+8E, 16 threads, 16 GB LPDDR5) —
roughly 10× the CPU the old docs assumed. Consequence: the LLM recommendation moves from
`qwen3:4b` on a hope to **`qwen3.5:4b`** comfortably at 12–17 tok/s, with **`embeddinggemma`**
for vectors. The iGPU still adds nothing — it shares the same memory bus, and decode is
bandwidth-bound.

---

## 2. What we already know for certain

### 2.0 Stage 0 is done — Relate works here

`pip install relate-db` → **`relate-db 1.0.1`**, native `win_amd64` wheel, Python 3.11.9.
`python tools/verify_relate.py` passes. Verified:

- DB-API 2.0 (`relate.connect(path)`, `cursor()`, `execute()`, `fetchall()`),
- **plain filesystem path, *not* a `file:` URI** — that fails with OS error 123 on Windows,
- `MERGE` on a stable key is **idempotent** — two runs, still 1 Person / 1 Message,
- **survives process restart** — reopened a fresh interpreter, both nodes present,
- `Vector` and `Path` are **native types**, so embeddings and geo go in without conversion.
- 36 KB `.rl` for two nodes — single-file mode is real and small.

Store: `store/stage0.rl` (gitignored). This is the durable layer, proven, on day 1.

### 2.1 Hermes cannot give us WhatsApp history

Checked on this machine:

- `hermes/config.yaml` → WhatsApp enabled in **`bot` mode**.
- `hermes-agent/scripts/whatsapp-bridge/bridge.js` → **`syncFullHistory: false`**.
- The bridge is a **long-poll fan-out** (`GET /messages`). It relays; it does not record.
- `hermes/whatsapp/` holds only `bridge.log` + a live `session/` directory. **No message store.**
- WhatsApp has **no REST history API** (documented in `docs/direction.md` §4). You cannot
  re-fetch what was never written down.

**Conclusion:** live Baileys can never backfill the archive. The session is still good
(last connect 2026-10-24), so we *can* add a recorder — but it only captures **forward** from
the day we switch it on.

**Decision:** WhatsApp `.txt` export is the demo route. A forward-only recorder is a
*nice-to-have*, explicitly deferred, and must be a **separate read-only code path** — never
sending, never bulk-fetching, and never touching the `public-div-6` Hermes profile. Account
reputation is not ours to spend (`docs/adjacent-notes.md` §3.1).

### 2.2 `docs/` is stale in two places

- It says `~/.hermes` doesn't exist. It does — at `%LOCALAPPDATA%\hermes` (Hermes v0.22.5,
  Python 3.14.9 for Hermes, Baileys `7.0.0-rc13`).
- It planned a "`.rl` writer" as an afterthought. Relate is now **the** store, not an export.

- It planned a "`.rl` writer" as an afterthought. Relate is now **the** store, not an export.
- It graded Telegram **A / build first** on cleanliness. True, but it missed the actual reason:
  Telegram is the **only format here with an officially documented schema**, so it's the one we
  can validate against a spec. Also the format with **contacts carrying phone numbers** — the
  strongest `MATCHED_BY` key.

Machine facts: **Python 3.11.9**, Node 22, npm 11, no GPU (i7-6600U, 16 GB DDR3L).
Installed: `networkx`, `pandas`, `pydantic`. **Not** installed: `relate-db`, `phonenumbers`,
`rapidfuzz`, Ollama.

### 2.3 Demo data: researched, and there is no shortcut

Verified 2026-11-14 against primary sources. Two findings, both of which shape §8:

1. **No public dataset has the same people on 2+ platforms with message text.** The closest real
   multiplex corpus is the **Copenhagen Networks Study** (same anonymous IDs across SMS, calls,
   Bluetooth, Facebook friendships) — and it is **metadata only**, because the authors
   deliberately never captured content. Abstract multiplex catalogues (Netzschleuder, KONECT)
   are likewise edge lists with no bodies, no threads, no text.
2. **Real per-platform corpora exist but never overlap**, and the overlapping ones are unusable:
   Enron (real people, no formal license), Avocado (paid LDC agreement), leaked WhatsApp dumps
   (non-consensual private chats — **do not touch, and say so on stage**).

**Consequence:** the cross-platform demo must be **constructed**. We generate it ourselves — see
§8.1. Rejected alternatives, for the record: fabricating Slack DMs for real Enron executives
(inventing comms by identifiable people is the one thing that would sink a privacy project), and
anchoring on the Sinabis CC-BY corpus (clean license, but a fictional German *corporate* email
set — wrong shape for a personal-comms product).

### 2.4 Hardware: the docs were wrong, and it's good news

`docs/llm-models.md` was written around an **i7-6600U (2 cores, 2015, no GPU)**. The actual demo
box is a **Lenovo17: i5-12500H, 12th gen, 4P+8E / 16 threads, 16 GB LPDDR5** (soldered, **not
upgradeable**), Iris Xe **80 EU** (not 96), no discrete GPU.

That's roughly **10× the CPU** of the old notes and changes the LLM conclusion from "barely
possible" to "comfortable." The old notes' pessimism should be disregarded, but **two of its
warnings still hold** and are now confirmed:

- **The iGPU is worthless for this.** 80 EU, no XMX, and it shares the *same* LPDDR5 bus as the
  CPU. Decode is bandwidth-bound, so a shared-memory iGPU has **zero** bandwidth advantage.
  Measured pattern across Vulkan/SYCL/OpenVINO: prefill 2–5× faster, **decode flat**. Force CPU.
- **Don't quantise below Q4_K_M.** Failure mode is invalid JSON, and quant damage hits schema
  adherence first.

---

## 3. Architecture — Relate is the durable layer

```
  exports/                    canonical records            Relate (.rl file)
  ─────────                   ────────────────             ──────────────────
  Telegram result.json ─┐
  WhatsApp _chat.txt  ──┤                                  (:Person)
  Messenger takeout   ──┼──►  Message{platform,             (:Identity)
  SMS BR XML          ──┤      chat_id, msg_id,               platform, handle
  Email IMAP/.eml     ──┘      ts_utc, sender,              (:Thread)
                               body, reply_to,              (:Message)
                               attachments}                 (:Attachment)
        │                            │                          │
        │                            ▼                          ▼
```
        │                     resolve/ (phones→E.164,     EDGES:
        │                     emails→lower, rapidfuzz)    Person-[:SENT]->Message
        │                            │                     Message-[:IN]->Thread
        │                            ▼                     Message-[:REPLY_TO]->Message
        └──────────────►  scrub/ (keep|hide|block) ───────►  Person-[:MATCHED_BY]->Identity
                                                             Person-[:POSSIBLY]->Person
```

**Why Relate wins here specifically:**

| Relate property | Why it matters for this app |
|---|---|
| In-process, no server | The privacy claim is *structural*, not a setting. There is no port to leak from. |
| Single `.rl` file mode | Judges can clone the repo, run it, and inspect one file. That's the submission checklist. |
| fsync'd WAL, optional durability | "Durable memory" with no database admin. Daily sync is a `MERGE`, not a migration. |
| Vector + traversal in one Cypher statement | *"Someone who talked about X, on 2+ platforms, who went quiet"* is one query, not a pipeline. |
| In-memory speed | Personal corpora are small. Everything fits, so queries feel instant — the "juicy" part of the UI. |

Storage mode decision: **single `.rl` file** for the demo (inspectable, portable), with a
`--store directory` flag for daily use. Never memory-only — this is a *durable* memory layer.

### 3.1 Schema (canonical, stable keys)

```cypher
(:Person   {key, display_name, first_seen_utc, last_seen_utc})
(:Identity {key, platform, handle, phone_e164, email, display_name})
(:Thread   {key, platform, title, is_group, participant_count})
(:Message  {key, platform, chat_id, message_id, ts_utc, body, has_attachments, is_self})
(:Attachment {key, filename_scrubbed, mime, sha256, size})
```

- `Message.key = platform + ":" + chat_id + ":" + message_id` — **never** array index or
  timestamp. This is what makes re-ingest idempotent (`docs/adjacent-notes.md` §5.2).
- Two resolutions edge types, never one: `MATCHED_BY` (exact key, confidence 1.0) and
  `POSSIBLY` (fuzzy name, 0.4–0.8). A wrong guess must *look* like honest uncertainty.
- **`ts_utc` everywhere.** Telegram and WhatsApp exports are local time with no offset.
  Convert at parse. If you defer this, the timeline lies and the demo dies.

### 3.2 Scrub gate — the differentiator

Runs **after** identity resolution (keys are needed for joins, then discarded), **before**
the graph write. Three verdicts per class: `keep` / `hide` (alias) / `block` (refuse + log).

- Aliases are stable across the whole graph: `PHONE-1`, `EMAIL-3`. Not per-thread.
- The alias→real mapping is a **re-identification key**. Decide explicitly and document it.
  Default: held in memory, written only on explicit `--reid-key` flag.
- **Append-only, user-visible refusal log.** Unknown message types (polls, stickers, calls,
  system events) get *counted and reported*, never silently dropped.
- Scrub attachment filenames too. `passport_scan.jpg` is a leak even with a clean body.

Evidence panel in the UI: "we withheld 14 phone numbers, 6 addresses, 3 attachments."
**That screenshot is the hackathon entry.**

---

## 4. Local LLM — required, and here's the honest reason

You asked why we need one. The answer is not "the app doesn't work without it" — the graph
skeleton is 100% deterministic. The answer is **the demo has no soul without it**.

`docs/llm-models.md` §1 already draws the line correctly:

| Task | LLM? |
|---|---|
| Parse → nodes/edges | No — explicit fields, this is parsing |
| Phone/email exact match | No — string normalisation |
| Fuzzy name match | No — `rapidfuzz` beats an LLM, and it's explainable |
| **"Who did I talk to about X"** | **Yes** — topic needs semantics, or you're doing keyword search |
| **Thread/relationship digests** | **Yes** — this is what makes a Person node *readable* |
| **Commitments, meetings** | **Yes** — the future agent hook |
| **Semantic PII** ("his passport is…") | **Yes** — regex provably misses it |
| Embeddings | Yes — small model, for vector search inside Relate |

**Hardware, corrected.** The real box is an **i5-12500H** (4P+8E, 16 threads, 16 GB LPDDR5, ~55
GB/s sustained). Measured anchor points from a CPU-only llama.cpp sweep on comparable DDR5:
**Qwen3-4B Q4 ≈ 20 tok/s, 8B ≈ 9 tok/s**. Scaling for a 45 W laptop chassis, expect **12–17 tok/s
for a 4B**. The `docs/llm-models.md` fear of "single-digit tok/s" was based on the wrong CPU —
it does not apply.

**The bandwidth formula is the one thing to trust before running anything:**
`tok/s ceiling ≈ sustained bandwidth ÷ model file size`. It's also why **MoE with few active
params is the structural win on CPU** — you pay for 1.3B of weights per token, not 8B.

### The setting (supersedes `docs/llm-models.md` §2 and §4)

| Component | Choice |
|---|---|
| Runtime | **Ollama ≥0.40.16, CPU only** |
| Primary model | **`qwen3.5:4b`** — Q4_K_M, 3.3 GB, **Apache-2.0**, 256K ctx |
| Embeddings | **`embeddinggemma`** (768-dim, 622 MB) — note it needs task prefixes |
| Threads | `num_thread 6` (4P+2E) in a Modelfile — **benchmark 4 and 8 too** |
| Context | `num_ctx 8192` |

Why `qwen3.5:4b` over the old `qwen3:4b`: Apache-2.0 (no legal review for a privacy product),
official pullable tag, and critically **75% of its layers are Gated DeltaNet linear attention**,
which allocates **no per-token KV cache**. Result: 8K context costs ~0.27 GB instead of ~1.07 GB.
You can run 32K context and still have 4.5 GB free. On a non-upgradeable 16 GB box, that is the
feature that matters.

**Two Ollama traps, verified:**

1. **`OLLAMA_NUM_THREADS` does not exist.** Feature request #9784 was closed as duplicate. Set
   `num_thread` in a **Modelfile** or per-request `options`. Blog posts get this wrong.
2. **`OLLAMA_NUM_PARALLEL` must stay at 1.** Parallel requests multiply the KV allocation; on
   16 GB that's a silent OOM.

```
OLLAMA_VULKAN=0            # force CPU; the iGPU shares the same bus, so it cannot help decode
OLLAMA_CONTEXT_LENGTH=8192
OLLAMA_FLASH_ATTENTION=1   # required for KV quantisation
OLLAMA_KV_CACHE_TYPE=q8_0  # halves KV; ~zero speed cost
OLLAMA_KEEP_ALIVE=-1       # overnight batch: don't pay reload between chunks
OLLAMA_NUM_PARALLEL=1
OLLAMA_MAX_LOADED_MODELS=1
OLLAMA_NO_CLOUD=1          # this IS the product promise, not a preference
```

**`OLLAMA_NO_CLOUD=1` is a product decision, not a tuning knob.** The pitch is "nothing leaves
the machine." Bundle that default; cloud only as an explicit user action.

**Structured output is solved, and it's why Ollama wins.** Pass a JSON Schema to `format=` and
decoding is **grammar-constrained** — malformed JSON becomes structurally impossible. Use
Pydantic `model_json_schema()` for the schema and `model_validate_json()` for a hard assertion.
Also put the schema *in the prompt* (structure is guaranteed by grammar; content correctness
improves from the prompt). **Keep schemas shallow with `Literal` enums** — enum-constrained
strings are just classification, the easiest thing a 4B can do.

**Turn thinking off for tagging.** Qwen3.5 reasons by default, which inflates decode 3–5× — on a
12 tok/s machine that's the difference between 2 hours and 10. Enable it only for thread
summaries and semantic PII.

**Prefix caching is the big throughput win.** The system prompt + schema is a *fixed* prefix on
all ~50k requests. Put the static block first byte-identical, the message last. `ollama` reuses
the KV for a matching prefix, so you pay prefill once instead of 50,000 times.

**Escape hatches:** runner-up is **`granite4.2:3b`** (2.2 GB, Apache-2.0) — IBM markets it
specifically for structured JSON, and it's small enough to run *two* instances (tagging +
commitment extraction) simultaneously. High-upside experiment is **Ling-3.0-tiny** (MIT, 7.9B
with **1.3B active**) — could be ~2× the speed and smarter than a 4B, but no official Ollama tag
and unverified JSON adherence. Prototype, don't depend.

Ground rule: **the graph builds with zero model calls.** Enrichment decorates. If Ollama
vanishes, the app gets dumber, not broken. That failure mode is deliberate.

---

## 5. The UI — this is a product, not a query console

The graph is the proof. **The UI is the pitch.** "Personal safe message perusal" is the
juice. Design it as something you'd want to open every morning, not something you'd demo.

Sketch of the shape:

```
┌──────────────────────────────────────────────────────────────────┐
│  ● OFFLINE · nothing leaves this machine          [evidence ▸]   │
├───────────────┬──────────────────────────────────────────────────┤
│ PEOPLE        │   Dave Sartori                                   │
│ ● D.Sartori   │   ─────────────────────────────────────────────  │
│   mat 3 ●●●   │   WhatsApp · Telegram · Messenger · SMS         │
│   2021—2024   │   ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░┊ quiet 2y      │
│               │                                                  │
│ ● M.Chen      │   "worked together → went quiet"                 │
│   mat 2 ●●    │                                                  │
│               │   ┌──────────── timeline ─────────────────┐      │
│ ● J.Okafor    │   │ 22 ▂▅▇▆▃▂▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁  25 │      │
│   possibly    │   └───────────────────────────────────────┘      │
│               │                                                  │
│               │   [ask: who did I talk to about … ]              │
│               │                                                  │
│               │   [ask: who did I talk to about … ]              │
└───────────────┴──────────────────────────────────────────────────┘
```

Non-negotiable UI details:

- **The offline badge is always visible.** Not a settings page — the top of the app.
- **`POSSIBLY` edges render differently** (dashed, amber) from `MATCHED_BY` (solid). A wrong
  guess must read as *"we're not sure"*, not as a bug.
- **Evidence panel one click away**, showing what was scrubbed and what was refused.
- **An arc, not a list.** "Met → worked together → went quiet" as a sentence generated from
  the graph. That sentence is the money shot. Person lists are table stakes.
- Ask box writes **Cypher visible to the user** — the LLM translates, Relate answers, and the
  user can see and edit the query. Trust by transparency, not by promise.

---

## 6. Future: human-in-the-loop replies (design for it now, build later)

This is the natural sequel and it should shape the schema today. It needs:

- `(:Message)-[:DRAFTED_FROM]->(:Message)` — provenance on anything AI-written.
- `(:Draft {key, body, model, created_utc, status})` with `status ∈ pending|approved|sent|rejected`.
- A **hard gate**: nothing sends without explicit human approval. Ever. No exceptions.
- Outbound transports are already in scope: **IMAP in, SMTP out**, both from the same account
  config. WhatsApp/Telegram outbound stays switched off — that's where bans come from.

Ship it as a **plugin interface**, not core. `plugins/reply/` exposing
`propose(thread_id) -> Draft[]` and `send(draft_id)` requiring a human token. Core never
imports a plugin.

---

## 7. Daily pull — LinkedIn is BACK IN, via a door nobody mentioned

### 7.1 The finding that reverses the earlier decision

You remembered LinkedIn as "grab-bag takeout or get banned." That was a false dichotomy. There is
a **third door**: the **Member Data Portability API**, which exists because the EU Digital Markets
Act forced it.

- `GET /rest/memberSnapshotData?q=criteria&domain=INBOX` → **full message history.**
  `INBOX` is verbatim in Microsoft's domain list: *"Messages sent and received in the member's
  inbox."*
- `GET /rest/memberChangeLogs?q=memberAndApplication&startTime=…` → **incremental events**, and
  Microsoft's own sample response is a DM. Retention 28 days, query hourly, `count` max 50.
- Self-serve scope `r_dma_portability_self_serve`, **granted instantly on accepting terms, no
  review.** Free. No partner programme, no 3–6 month cycle.
- Header `Linkedin-Version: 202312` — **only** that value; anything else returns `426`.
- Read-only. Your own data only. Token ~1 year, no refresh token.

**This is not a scrape.** Publishing an importer for it is completely unremarkable legally.

**The blocking constraint: EU/EEA/Switzerland members only**, determined by the **location on your
LinkedIn profile**, not your IP. Outside that you get errors on consent. That single fact decides
which of the two routes the demo shows.

### 7.2 What we ship

| Route | Status | Notes |
|---|---|---|
| **`messages.csv` from takeout** | **Ship it** | Desktop only. Category-scoped request lands "within minutes" — that's the lever, not the 24 h large archive. **Flat rows, one per message, with a conversation-ID column** — group by it for threads. Good shape for the graph. |
| **DMA Portability API** | **Ship the importer, gate on region** | Documented, official, live path. One parser likely serves both since both derive from the same LinkedIn domains. |
| Voyager / `linkedin-api` | **REJECT** | **Repo is deleted (404).** PyPI last published 2024-11-07. Its own README warned it may violate ToS. Do not put this in a dependency list a judge will read. |
| Playwright scraping | **REJECT** | The best public implementation self-reports **content-corrupt InMail export** (open `BL-006`) *and* detection risk: *"LinkedIn may recognise the way it's used even from the pattern of allowed GET requests."* |
| Browser extensions | **REJECT** | §8.2 prohibits browser plugins that "scrape or copy the Services." Passive interception is lower-signal but still prohibited. |
| Unipile / Linked Helper / PhantomBuster | **REJECT** | Unipile's own FAQ: *"not officially endorsed by LinkedIn."* Server-side sessions, paid, no personal export. |

### 7.3 Legal reality, stated plainly for the README

LinkedIn User Agreement **effective 2025-11-03**, §8.2 bans software/bots *"to scrape or copy the
Services"* and *"unauthorized automated methods to access the Services."* Note **"access the
Services" is not limited to other people's data** — your own inbox is on the Services.

**hiQ does not help us.** That was a CFAA ruling about *logged-out public* pages. hiQ later lost
the *contract* case, settled for $500k, and was permanently enjoined from scraping. Authenticated
scraping of your own session is the case hiQ lost.

**Enforcement record, honestly:** there is a large documented record of restrictions from
automation *tools*, but **no verifiable published case of someone restricted for read-only
exporting their own message history** — unsurprising, since restriction signals are
volume/pacing/recipient-complaint driven and read-only export produces none. Absence of evidence
isn't permission, but it is a real mitigant.

### 7.4 Frequency — the "daily" requirement was probably wrong anyway

No official re-request cooldown is documented ("once per 30 days" is **unverified folklore** from
secondary sources). Practically people request monthly or quarterly.

**But a daily LinkedIn dump is unnecessary for this product.** A relationship graph barely moves
day to day — who talks to whom, and when, is stable. **Weekly or monthly full re-import plus
dedupe by conversation ID is functionally equivalent.** The only genuine daily case is
"alert me the moment someone replies," and that is exactly what the DMA changelog does for EU
members.

So: **LinkedIn is a lump like everything else**, with an optional live path for EU members. Say
so honestly in the README rather than over-promising a sync.

### 7.5 Everything else is still a lump

**Messenger** is the real prize: takeout-only, no API, but it's where the actual conversational
history lives. One download, hours-to-a-day. Format shifts over time, so the importer is written
against your real payload (§8.1) and gets a `--dialect` guard.

So: **not a live sync. A daily drain of a folder.** The user's `Get a copy of your data` landing
makes it a lump; we treat every lump as a **full re-import with dedupe on stable key**.

```
spool/               ← watched folder, user drops new takeout zips here
  2026-11-14/        ← one dir per drop
  processed/         ← moved after successful ingest (configurable delete)
```

- Ledger of `(source, key, content_hash)` handles re-imports and **deletions** without
  assuming corruption. A message that vanished yesterday is data, not a bug.
- Only **email (IMAP)** is genuinely incremental; **SMS** is incremental if you re-run
  Backup & Restore. Telegram, WhatsApp, Messenger are lumps.

---

## 8. Build order — 28 days to Dec 11

**The order is now forced by one rule: never write an importer for a format we haven't seen a
real payload of.** Real accounts first, generator second (see §8.1). Telegram leads not because
you use it, but because it's the **only one of the four with an officially documented schema** —
so it's the one format we can validate against a *spec* rather than against a parser's opinion.

| # | Stage | Done when | Days |
|---|---|---|---|
| 0 | ~~**Install Relate**~~ **DONE** — `relate-db 1.0.1`, verified: restart-durable, `MERGE` idempotent. See §2.0 | ✅ `tools/verify_relate.py` passes | done |
| 1 | **Real payload capture** — one small export of each: Telegram JSON (~1 chat), WhatsApp `.txt` (1 chat), SMS Backup & Restore XML (a slice), one `.eml`/mbox, Messenger takeout, LinkedIn `messages.csv`. **Redact, commit as `fixtures/real/`, never raw.** | Real files on disk + a written note of every field observed | 1 |
| 2 | Canonical `Message` schema + **Telegram adapter** + Relate writer, built against the real payload | Ingest twice → identical counts (idempotent) | 2 |
| 3 | **WhatsApp `.txt` adapter** — hand-written, dialect pinned from the real file | Same person appears in both platforms' threads | 1.5 |
| 4 | **Resolution**: `phonenumbers` → E.164, emails lowered, `rapidfuzz` → `POSSIBLY` | A `Person` node has identities on 2+ platforms | 1.5 |
| 5 | **Scrub gate** + stable aliases + refusal log | Flip `phones: block` → same shape, PII gone | 2 |
| 6 | **SMS** (Backup & Restore XML) + **Email** (IMAP read-only `UID FETCH` + `.eml`) | Four platforms, one Person | 2.5 |
| 7 | **Messenger** takeout JSON + **LinkedIn** (`messages.csv`, group by conversation ID) | Six platforms | 2 |
| 8 | **`gen-comms-pipe`** — canon YAML + seeded generator + six writers, emitting **exactly the schemas observed in stage 1** | Round-trip: our writer → an independent parser → identical graph to stage 2–7 output | 3 |
| 9 | **UI** — offline badge, people rail, timeline, arc sentence, evidence panel | Someone can look at it and say "oh" | 4 |
| 10 | **Ollama enrichment** — install Ollama, pull `qwen3.5:4b` + `embeddinggemma`, topics/digests/semantic PII | "Who did I talk to about X" works | 3 |
| 11 | *(optional)* **LinkedIn DMA Portability API** importer, EU-gated | Same parser serves CSV and API | 1 |
| 12 | **Video + README** (must answer: how/why Relate, and which storage mode) | Submitted on Devpost | 2 |

**Out of scope, and say so in the README:** **Slack** — team-oriented, *and* its export needs
workspace admin we don't have, so it would be the one importer testable only synthetically, which
§8.1 forbids. Also out: iMessage, Signal, and the live Baileys recorder.

### 8.1 `gen-comms-pipe` — the rule that makes it trustworthy

> **Build against your real accounts first. Verify the payloads. *Then* build the generator to
> reproduce those exact schemas.**

This is the right order and it is not negotiable, because it removes the two ways a synthetic
dataset launders a bug:

- **The generator can't drift from reality** — it was written *after* the real file, not before it.
- **The parser can't be tuned to fiction** — it was written against real bytes, so the generator
  is graded by the parser, not the other way round.

**Why a generated corpus is in the deliverable at all:** research (see §7.5) confirmed there is
**no public dataset with the same people on 2+ platforms carrying message text**. The closest real
multiplex corpus (Copenhagen) is metadata-only by design. So the cross-platform story *must* be
constructed. We construct it ourselves rather than fabricating platforms for a real company's
executives (Enron) — inventing DMs for identifiable real people would be the one thing that sinks
a privacy project.

```
dataset/
  canon.yaml            hand-authored: people, scenes, places, companies, products, arcs, events
  phrases/              frozen LLM-generated phrase bank, checked in, no model at run time
  generate.py           seeded (--seed 42) → deterministic, byte-identical output
  writers/              telegram.py whatsapp.py sms.py messenger.py email.py
  out/                  the committed corpus, ~2k messages, 40 people
```

Emits **only** the four/five formats we captured in stage 1. If a field wasn't in the real file,
the generator does not invent it.

### 8.2 What the video shows — and what it doesn't

Your call, and it's a good one. Two distinct things, kept apart:

| | Ingested from | On camera |
|---|---|---|
| **Proof it works on real data** | your live accounts | **Yes** — running, counts, refusal log, no bodies shown |
| **Graph walkthrough** | `dataset/out/` generated corpus | **Yes** — every visible Person/Place/Company/edge |

Practically: the demo video opens with the real ingest ("these are my accounts, this is my
machine, nothing left the box, here's what was scrubbed"), then switches to the generated graph
for the traversal, arcs, and queries. State that switch out loud, on camera, in one sentence.
Being explicit is *stronger* than blurring it — judges are Neo4j staff who will ask, and
"real for fidelity, generated for disclosure" is a better answer than a stumble. It also maps
cleanly onto the hackathon's "persistent store judges can inspect": what we ship is the
inspectable corpus, and no judge ever needs your private data.

---

## 9. Testing against real socials

**Gate:** every parser passes fixtures → then a **redacted 100-message sample** → then the full
archive. Never point a new parser at a real archive first.

| Platform | Get it | Watch out |
|---|---|---|
| Telegram | Settings → Advanced → Export → JSON | **Plaintext on disk.** One chat first — full exports are GBs. |
| WhatsApp | Per-chat Export chat → `.txt`, media **off** | Manual, one chat at a time |
| Messenger | Facebook → *Download your information* → **JSON** | **Slow — hours to a day. Request first.** Format drifts. |
| LinkedIn | Settings → Data privacy → *Download larger archive*; request **Messages only** | Category-scoped lands **minutes**, not 24 h. Desktop only. Flat rows — group by conversation ID. |
| SMS | SMS Backup & Restore → XML (`smses`/`sms`) | Per-message rows, no threads — group by address+date ourselves |
| Email | IMAP read-only, `UID FETCH` | Gmail needs an **App Password**; basic auth is dead |

**Start the Messenger download today** — it's the one with real latency, and stage 1 is blocked on
it. LinkedIn's messages-only category request lands in minutes, so it can be done during stage 1.
Request Telegram with a single chat selected first, not the full archive.

- Spool to `C:/Users/q1fre/relate-spool/`, **not** `Downloads`.
- Delete the spool after ingest. `archive_copies: false` by default — parse in place, keep hashes.
- **Never** run the demo from a live-authenticated session. Exports only.

---

## 10. Open decisions

1. ~~Which person is the demo story?~~ **Resolved.** Don't curate an arc in advance — the
   generated corpus *has* authored arcs by construction, and the real-data pass is only there to
   prove fidelity. Stop hunting for a 3-platform friend.
2. **Alias key storage** — memory-only, encrypted file, or accept plaintext locally? Must be
   stated in the README either way.
3. **Relate durability settings** for daily use — fsync every write (safe, slower) or flush on
   exit (fast, loses the last session)? Default safe, flag for fast.
4. **UI stack** — no GPU here, but judges need to run it. Local web app (FastAPI + a single
   HTML file) beats a desktop toolkit for "clone it and see it".
5. **Submit solo?** Hackathon allows teams; Discord/Community channels are open.
6. **Real-payload redaction rules.** Stage 1 commits real export files to a **public** repo.
   Decide the redaction policy *before* the first commit: names → `Person A`, phones → Ofcom
   drama range `+447700900xxx`, bodies → truncated paraphrases, timestamps → date-only? Or keep
   structure and scrub only identifiers. This is the highest-risk step in the whole build.
7. **Is `fixtures/real/` public or a private submodule?** Public repo needs *something* to prove
   fidelity; a private submodule proves nothing to judges. Suggest: commit a **small real-derived
   sample** (2–3 chats, redacted) plus a documented `--replay` flag, and keep full archives local.
