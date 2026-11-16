# relate-comms-graph — adjacent notes, assets & prior art

> Third doc in the set. [`direction.md`](direction.md) = the direction.
> [`llm-models.md`](llm-models.md) = model/quant choices.
> **This file = everything else**: reusable code, cross-project lessons, useful
> libraries, prior art, and traps already paid for.

---

## 1. Existing assets on this machine

### 1.1 `desk-relate` — salvageable code (deprecated, but the pieces are good)

| File | Take it? | What it gives you |
|---|---|---|
| `app/parser.py` | **Yes** | `to_text()` router that never raises; eml header/body split; xlsx **cell-address mode** |
| `app/dryrun.py` | **Yes, adapted** | Measure-before-ingest reporting; `MARKER_TERMS` proximity scan for secrets in prose. The pattern is the value — swap file-walk for message-stream. |
| `app/config.py` | Yes | `Knobs` dataclass + legacy alias normalisation + `jlog` JSONL append |
| `app/delta.py` | Concept only | Ledger replay → new/altered/gone. Messages need stable IDs, not mtime. |
| `app/scrubber.py` | **Partly** | 8 regex classes are a fine *starting* set; the verdict model (`keep/hide/block`) and stable aliases (`PHONE-1`) are the reusable idea |
| `app/grapher.py` | Concept only | Cypher builder w/ `MERGE` idempotency + vector index DDL — reusable shape, different schema |
| `make_test_folders.py` | Partly | Fixture-generator *pattern*; the hand-rolled `.xlsx/.pptx` binaries are broken (too minimal to load) |

**Not worth taking:** `llmqa.py` (never ran — Ollama absent), the folder-walk logic, the
`TEXT_EXT` allowlist approach.

### 1.2 Hermes (`NousResearch/hermes-agent`)

- **Baileys bridge** — `scripts/whatsapp-bridge/`, session at
  `~/.hermes/platforms/whatsapp/session`. Re-pairing is the expensive part; reusing
  the session avoids a QR scan.
- ⚠️ **Not present on this machine** — `~/.hermes` doesn't exist in this profile.
  Either it runs on another box, or in WSL/Docker. **Verify before designing around it.**
- Its **feature request #12323** is effectively a spec for this project (see main doc §3.1).
  Worth reading in full — it lists the adjacent issues (#6430, #9485, #7736, #844) and
  explicitly what it is *not*.

### 1.3 Other Relate builds under `Zed/`

- `Relate/`, `relate-sec-graph/`, `relate-src/` — sibling builds. **Do not assume their
  `.rl` schema matches**; check before sharing code. The handover already warns about
  confusing them.
- `frontal-lobe*`, `Nod` — unrelated but see §3 for transferable lessons.

---

## 2. Libraries worth knowing

### 2.1 WhatsApp
- **Baileys** (`@whiskeysockets/baileys`) — MIT, 11.6k★, TS. WebSocket to WhatsApp Web,
  no browser. `syncFullHistory: true`, `Browsers.macOS('Desktop')` for more history.
  Bulk arrives as `messaging.history-set`; `fetchMessageHistory(50, oldestKey, ts)`
  walks backwards, **50 messages per call**.
- **whatstk** — GPL-3.0, robust `.txt` export parser → pandas DataFrame. Handles the
  multiple date formats that break naive regex parsers. **GPL:** fine for internal use,
  a licensing consideration if you ship binaries.
- **whatsapp-chat-exporter** (PyPI) — DB-level parser for Android/iOS backups → HTML/JSON.
  Overkill unless you have raw backups.

### 2.2 Telegram
- **Telethon** / **TDLib** — own-account API, full history, no admin rights.
- Export schema is **officially documented**: <https://core.telegram.org/import-export>
  — read this rather than reverse-engineering `result.json`.
- `result.json` media paths are **relative** (`chats/chat_01/photos/photo_1@…jpg`), which
  is convenient: the archive is self-describing and relocatable.
- Contacts export as **`.vcard` files** → contain phone numbers → **prime join keys**.

### 2.3 Identity resolution / matching
- **rapidfuzz** — MIT, fast C++-backed fuzzy string matching. Use for name candidates
  *before* ever considering an LLM. `token_set_ratio` handles "Dave S" vs "Dave Sartori".
- **phonenumbers** (Google libphonenumber port) — **essential.** Normalises
  `07700 900123` / `+44 7700 900123` / `447700900123` → one E.164 form. Without this,
  phone joins silently fail. Also identifies country/region.
- **email-validator** / `email.utils.parseaddr` — normalise addresses, strip display names.
- **Zingg** — open-source ML entity resolution. Enterprise-shaped; probably too heavy, but
  worth reading for its blocking strategy (you can't compare every person to every person
  — you block on a cheap key first).
- **Dedupe** / **splink** — lighter alternatives if fuzzy matching grows beyond hand-rolled.

### 2.4 Parsing attachments
- **MarkItDown** (already in `desk-relate` venv) — handles pdf/docx/xlsx/pptx/msg.
  Useful because WhatsApp/email attachments are exactly those formats.
- **`extract-msg`** — better than MarkItDown for `.msg` if you need real MIME/attachment
  enumeration rather than flattened text. **Not currently installed** (checked).
- **`xlrd`** for legacy `.xls` — **not installed**, and MarkItDown can't read `.xls` either.
- `pdfminer.six` + `pdfplumber` — already present; `pdfplumber` needed for tables.

### 2.5 Email
- stdlib `imaplib` is fine and dependency-free. `imap-tools` is a much nicer wrapper if
  you don't mind the dependency (handles UID ranges, flags, folder listing sanely).
- Gmail: **App Password required** with 2FA; basic auth is dead.
- Prefer UID-based fetching (`UID FETCH`) over sequence numbers — sequence numbers shift
  when messages are deleted, which corrupts incremental sync.

---

## 3. Transferable lessons from sibling projects

### 3.1 From `Nod` — account reputation is a third axis
`Nod-vs-Hermes-forDave.md` makes a sharp point worth reusing verbatim:

> Sandbox protects your machine. Trust gate protects your *authority*.
> **Neither protects account reputation** — and that's what LinkedIn enforces on.

This applies directly to WhatsApp via Baileys and to anything touching LinkedIn.
An aged, human-paced, low-volume account survives; a fresh automated session doesn't.
Your `public-div-6` Hermes profile has that history built up — **don't burn it on a
hackathon demo**. Use exports for the demo; save live connections for real use.

### 3.2 From `desk-relate` — measure before ingest, refuse loud
The one genuinely good instinct in that build: a `dryrun` that reports *what would
happen* without doing it, and a refusal log that is **append-only and user-visible**.
Carry both forward. For messaging, the equivalent dry-run is: "here are 12,400
messages, 47 people, 9 platforms, 312 attachments, here's what would be scrubbed" —
before writing anything.

### 3.3 From `desk-relate` — the silent-skip anti-pattern
`scrub_staged` silently skipped every non-text extension. Files looked staged and
indexed but weren't. **Never let an unhandled case pass without a log line.** For
messaging: unknown message types (polls, stickers, system events, calls) must be
counted and reported, not dropped.

### 3.4 From the Nod cost doc — background polling is the real bill
If the daily sync polls APIs, cost/CPU accrues 24/7 regardless of whether you look at
the graph. Design for **event-driven or scheduled-with-sleep**, not tight polling.

---

## 4. Prior art — the full honest landscape

### 4.1 Document→graph (mature, crowded — do not compete here)
| Tool | License | Gap for us |
|---|---|---|
| **Neo4j LLM KG Builder** (5.3k★) | Apache-2.0 | Docs only, no email. Weak on spreadsheets/slides (their own docs say so). |
| **Microsoft GraphRAG** | MIT | Docs only; heavy; expensive model calls |
| **LightRAG** | MIT | Docs only; generic schema |
| **CocoIndex** | — | Drive→markdown→Neo4j; real-time; not messages |
| **Memgraph Unstructured2Graph** | — | Docs; Memgraph-only |
| **Neo4j `SimpleKGPipeline`** | Apache-2.0 | Library form of the builder; same limits |
| **Zingg** | open | Entity *resolution* only — solves our hard sub-problem, not the pipeline |

### 4.2 Message→store (exists, but not graph-shaped)
| Tool | What it does | Gap |
|---|---|---|
| **Hermes #12323** (unbuilt) | Proposed unified People DB in SQLite | Not built; SQLite not graph |
| **whatstk** | WhatsApp analysis/visualisation | Single platform, analysis not graph |
| **WhatsApp-Export-Unpacker** | Forensic unpack + transcription, local-only | Single platform, no graph |
| **telegram-download-chat** | CLI/GUI/MCP over `result.json` | Single platform, export→files |

### 4.3 The actual gap
**Nobody joins messaging platforms into one graph with a PII gate.** Three defensible
claims, in order of strength:
1. Cross-platform identity resolution into a graph (the "shock" demo)
2. Privacy gate *before* ingest, local-only (the differentiator vs cloud tools)
3. Native edges — no LLM guessing at structure (the technical argument)

Don't claim "we built document→graph." That's the crowded lane and you'd lose.

---

## 5. Traps already paid for

### 5.1 Platform/licensing
- **LinkedIn:** export only. Automation → account restriction, and a public repo
  demonstrating it is a liability. Also: the archive comes in **two parts**, days apart.
- **WhatsApp via Baileys:** unofficial; bans are real. Read-only, no sending, low volume.
- **Slack:** full history export requires **workspace admin**. Don't promise Slack unless
  the user owns the workspace.
- **GPL contamination:** `whatstk` and `pistocop/messaging-chat-parser` are GPL-3.0.
  Fine to *use*, tricky to *vendor* into an MIT repo. Keep them at arm's length (subprocess
  or optional dependency), or write the small parser yourself.
- **Telegram:** exports are **decrypted plaintext on disk**. Warn the user loudly.

### 5.2 Data correctness
- **Phone normalisation is mandatory** before any join. Mixed formats are the #1 cause of
  "why didn't it match?"
- **LinkedIn emails are usually absent** (only if the connection enabled sharing). Don't
  design a join that requires them.
- **Message IDs must be stable across re-ingest.** Use `platform + chat_id + message_id`.
  Do not use array index or timestamp.
- **Timezones:** Telegram exports local time; WhatsApp exports local time; email has
  proper offsets. Normalise to UTC on ingest or your timeline lies.
- **Group chats:** a message has one sender but N participants. Model `Thread` membership
  separately from `SENT`, or you'll duplicate edges.
- **Deleted/edited messages:** exports are snapshots. A message present yesterday may be
  gone today — your delta must handle `gone` without assuming corruption.
- **Self-messages / "Notes to self"** — real, common, and a surprisingly good signal.

### 5.3 Security
- Archives contain **unencrypted** full history. Default storage location should be a
  dedicated directory the user knows about, not `Downloads`.
- The **spool copy is a second unredacted copy.** For `desk-relate` this was flagged as a
  hazard; here it's worse (more sensitive data). Consider `archive_copies: false` — parse
  from the export in place, keep only hashes.
- **Attachment filenames leak** ("passport_scan.jpg"). Scrub names too, not just bodies.
- **Alias table is a re-identification key.** If `PHONE-1 → +4477…` is stored in plaintext
  next to the graph, the graph is not anonymised. Decide explicitly: is the alias map
  encrypted, or is it acceptable locally?

### 5.4 Demo risk
- **Biggest risk: the demo data is boring.** Three platforms with 20 messages each shows
  nothing. Pick one person who appears on 3+ platforms and has a real arc (met → worked
  together → went quiet). Curate the story, then let the query find it.
- **Second risk: identity resolution produces garbage matches** live on stage. Show
  confidence levels; make `POSSIBLY` visually distinct so a wrong guess looks like honest
  uncertainty rather than a bug.
- **Third risk: GraphRAG-style tools already demoed this.** Have the "we join silos + PII
  gate" answer ready in one sentence.

---

## 6. Relate-specific notes

- Relate is **single-process** — one writer per `.rl`. Never open the same graph from a
  REPL while ingest runs.
- Install from **GitHub releases wheel** (1.0.1 at time of writing); PyPI publish hadn't
  landed.
- Vector index DDL used in `desk-relate`:
  `CREATE VECTOR INDEX doc_embedding IF NOT EXISTS FOR (d:Document) ON (d.embedding)
   OPTIONS {indexConfig: {`vector.dimensions`: N, `vector.similarity_function`: 'cosine'}}`
- `MERGE` on a stable `key` gives idempotent re-ingest — essential for daily sync.
- Graph lives in RAM when loaded. For 100k+ messages, **keep bodies out of the graph**
  where possible (store excerpts or hashes + a sidecar store), or memory becomes the
  ceiling before the model does.

---

## 7. Suggested first build order

1. **Canonical `Message` schema** + a Telegram `result.json` adapter (cleanest source,
   documented schema, zero ban risk).
2. **Graph writer** for `Person/Thread/Message` with stable keys — no LLM, no scrub.
   Prove idempotent re-ingest.
3. **Phone/email normalisation** (`phonenumbers`) + exact-match resolution.
4. **Second adapter** (WhatsApp `.txt`) — now the join is testable end to end.
5. **Scrub gate**, reusing the `keep/hide/block` model.
6. **LinkedIn zip** adapter — messages + connections + contacts (phones).
7. **LLM enrichment** (only now) — commitments, digests, topic tags.
8. Fuzzy `POSSIBLY` edges + confidence display.

Steps 1–4 need **no LLM and no credentials beyond a Telegram export** — that's the
shortest path to a working demo.
