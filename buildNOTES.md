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
| Telegram | Settings → Advanced → Export → JSON | **Plaintext on disk.** One chat first; full exports are GBs. |
| WhatsApp | Per-chat → Export chat → `.txt`, media **off** | Manual, one chat at a time |
| Messenger | Facebook → *Download your information* → JSON | **Slow — start it first** |
| LinkedIn | Data privacy → *Download larger archive*, **Messages only** | Lands in minutes, not 24 h |
| SMS | SMS Backup & Restore → XML | Per-row, no threads — group by address + date |
| Email | IMAP read-only, `UID FETCH` | Gmail needs an **App Password** |

- Spool to `C:/Users/q1fre/relate-spool/`, not `Downloads`.
- Delete the spool after ingest; `archive_copies: false` — parse in place, keep hashes.
- **Never** demo from a live-authenticated session.

---

## 10. Handover — 2026-11-14, before stage 2

**Status:** Stage 0 complete and pushed (`d2279a2`). Next is stage 2 — canonical `Message`
schema, Telegram adapter, Relate writer. **No Ollama needed for that.**

### Start here

Telegram, not because you use it, but because it's the only format with an
**officially documented schema** (`core.telegram.org/import-export`). That means the parser can
be validated against a *spec* rather than a parser's opinion — the only one of the six where
that's true.

**Canonical record to target** (from §3.1, but concrete):

```python
@dataclass(frozen=True)
class Message:
    key: str            # f"{platform}:{chat_id}:{message_id}"  -- build first, never mutate
    platform: str       # "telegram" | "whatsapp" | ...
    chat_id: str
    message_id: str
    ts_utc: datetime    # ALWAYS UTC. Telegram exports local time with no offset.
    sender_name: str
    sender_id: str | None
    body: str           # "" for media-only, do not drop the row
    reply_to: str | None    # resolved to a Message.key, not a raw id
    has_attachments: bool
    is_self: bool
    raw_kind: str       # "text" | "poll" | "sticker" | "call" | "service" | ...
```

**Telegram parses out of** `result.json` → `chats[]` → `messages[]`:

| Field | Note |
|---|---|
| `date` / `date_unixtime` | **Both are strings.** Prefer `date_unixtime`. |
| `from` / `from_id` | `from_id` is `user123` / `channel123` — stable; names aren't. |
| `text` | **Polymorphic.** Plain `str` if no entities; otherwise `list` of `str` and entity dicts. |
| `text_entities` | Companion when `text` is a list. |
| `reply_to_message_id` | Map to a `Message.key`. |
| `edited` / `edited_unixtime` | Both strings; presence means edited. |
| `forwarded_from`, `saved_from` | Keep — good provenance edges. |
| `photo`, `file` | **Relative paths** (`chats/chat_01/photos/...`) — archive is relocatable. |
| `type` | Anything not `message` (service events) — count it, don't drop it. |
| `contacts[].phone_number` | **The strongest join key.** `personal_information.phone_number` too. |

**Gotchas that will bite:**
1. `text` being `str` *or* `list` is the #1 parser bug. Handle both from day one.
2. Single-chat exports emit a bare `Chat` object, not a `Result` wrapper.
3. `date` is local time with **no timezone field**. Convert at parse. Defer it and the timeline lies.
4. Unknown `type` values exist (polls, stickers, calls, joins). **Count and report, never silently skip.**

### Then, in order
1. Stage 1 payload capture — request **Messenger** now (slowest), Telegram one chat, LinkedIn Messages-only.
2. Stage 3 WhatsApp `.txt` — Android dialect `DD/MM/YY, HH:MM - Name: body`, with the U+200E
   LTR mark prefix that precedes media lines. Pin one dialect from the real file.
3. Everything else per §8.

### Loose ends
- `tools/bench_ollama.py` **stalls at `ollama.create`** — known broken, low priority (MoE already gave the speed).
- `num_thread` unmeasured. Theory says 6 on 4P+8E. Not blocking.
- Redaction policy for `fixtures/real/` in a **public** repo is still undecided — settle it before
  the first commit of real data.
- Verified tok/s came from 8 easy messages; re-test on ~50 real redacted ones before trusting it.
