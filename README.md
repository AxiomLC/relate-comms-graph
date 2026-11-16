# relate-comms-graph

**Your own message archives — across platforms — as one local, privacy-scrubbed graph.**

> Working prototype. Five adapters, live email, identity resolution, a scrub gate, and a
> local-only UI. Nothing leaves the machine.

---

## What it is

Your messages already *are* a graph: sender → message → thread → reply. That structure is
explicit, not inferred. But it is shredded across five apps, so nobody can answer:

> **"Who did I talk to about X on more than one platform, and when did it stop?"**

The answer exists in your data today and is invisible. This makes it visible — as one
graph you can walk, search and question, on your own disk.

Built as a **Neo4j Relate** hackathon entry (theme *"Context, Connected"*).

## Why a graph, why local

| | |
|---|---|
| **Native edges** | `from` / `to` / `reply_to` / `thread` are data fields, not LLM guesses. Most "documents → graph" tools guess at structure; here it is given. |
| **Identity resolution** | The same person appears on three platforms under three identities. Merging them is a real problem, and the demo's money shot. |
| **Privacy by construction** | These are the most sensitive files a person owns. Everything runs locally, and a scrubbing gate sits *before* the write, not after. |
| **No server** | Relate is an embedded engine — one `.rl` file, no port, no Bolt. That is also why this project has its own Cypher writer: every off-the-shelf graph-extraction library needs a Neo4j server to connect to. |

## Where the data lives

**One file holds everything: `store/graph.rl`.** No CSV, no database server, no export
between parse and write. Exports land in `spool/real/<platform>/`, are read into in-memory
records, and merged into that single file.

```
spool/
  real/     telegram/  whatsapp/  messenger/  linkedin/  sms/  imap/  gmail/
  sample/   the same folders, for generated demo data
store/
  graph.rl      the graph — every message, every person
  profile/      identity.json — which account is "me", per platform
```

Both folders sit inside the repo and are **gitignored**; only `.gitkeep` files are
committed, so a fresh clone has the shape but no data. `ingest` recreates them if deleted.

**Backup:** `graph.rl` is rebuildable only from `spool/`. Copy it somewhere safe before
running anything destructive.

## Setup

Requires **Python 3.11+**. Node is only needed if you change the UI.

```bash
pip install -e ".[resolve,app]"     # rapidfuzz + fastapi/uvicorn
cp .env.example .env                # only if you want live email
```

Optional, for the AI chat: install [Ollama](https://ollama.com) and pull a model.

```bash
ollama pull lfm2.5:8b
```

## How to run

**Windows:** double-click **`start.bat`** in the root. A console window opens, the browser
opens at `http://127.0.0.1:8100`, and closing the window stops the app.

**Any platform:**

```bash
python -m app                       # http://127.0.0.1:8100
python -m app --port 8110           # if 8100 is taken
```

Port **8100**, not 8000 — 8000 is held by another app on this machine.

### Getting your messages in

Press **Ingest** in the title bar. The modal explains what each platform requires and
accepts a pasted path; files are **copied** into the spool, never moved.

```bash
python -m relate_comms ingest --source real --email hostinger --tz-offset -5
```

Per-platform download instructions live in
[`archive_docs/MssgDownloadInstructs.md`](archive_docs/MssgDownloadInstructs.md).

### What the demo looks like

1. Drop three archives in: Telegram JSON, WhatsApp `.txt`, LinkedIn zip. (Email reads live.)
2. Ingest — show the refusal log and what was scrubbed.
3. Ask: *"Who did I talk to about [topic] on more than one platform, and when did it stop?"*
4. One `Correspondent` node per platform, edges into each thread, a timeline, a cluster
   that goes quiet.
5. Flip `phones: block`, re-ingest → same graph shape, PII gone, refusal log lists what
   was withheld.

## Platform reality

| Platform | Grade | Route |
|---|---|---|
| **Telegram** | **A** | Desktop export → `result.json` (officially documented schema) |
| **Email (Gmail)** | **A** | IMAP read-only, App Password. Verified live |
| **Email (Hostinger / cPanel)** | **A** | IMAP read-only, `INBOX` + `INBOX.Sent`. Verified live |
| **Email (Outlook)** | **A file / F live** | Basic auth is dead. Use the `.pst` export button |
| **WhatsApp** | B | Per-chat `.txt`/`.zip`. No all-chats export; media placeholders only |
| **LinkedIn** | **A data / F automation** | *Basic* archive → `messages.csv`. Export only |
| **Messenger** | B/C | *Download your information* → HTML archive. Slow, no API |
| **SMS** | — | Adapter not built |
| **Slack** | C | Export needs workspace admin. Not viable |
| **Instagram** | — | Out of scope. Export names no sender |

## Status

**Ingested:** 12,499 messages, 955 threads, 591 correspondents, 86 attachments across five
platforms (Messenger 10,605 · Telegram 1,212 · LinkedIn 292 · Email 221 · WhatsApp 169).

**Built:** five file adapters + live IMAP, parallel parse → resolve → scrub → serialised
write → verify → prune, 10-tool layer, FastAPI, and the UI.

**Not built:** `Person` / `Identity` (cross-platform identity — `Correspondent` is a
per-platform fact, `Person` would be the inference), Place/Company/Product, SMS, semantic
search (Relate supports vector indexes; none exists in this store yet).

`pytest tests -q` → **137 passed, 2 skipped**.

## Docs

| Doc | What's in it |
|---|---|
| [`TECHREADME.md`](TECHREADME.md) | Module map, key functions, commands, Relate/Neo4j references — written for an AI |
| [`HANDOVER.md`](HANDOVER.md) | Short, dated, newest at the bottom — what is next |
| [`archive_docs/UI-Cytoscape.md`](archive_docs/UI-Cytoscape.md) | The UI as built, and every Cytoscape decision behind it |
| [`archive_docs/MssgDownloadInstructs.md`](archive_docs/MssgDownloadInstructs.md) | How to get each platform's export |
| [`archive_docs/HowToRunOllama.md`](archive_docs/HowToRunOllama.md) | Local model setup on this machine |

## Design principles

- **Deterministic before LLM.** Parsing, normalisation, exact matching and shape scrubbing
  never need a model. Enrichment is optional.
- **Never a silent drop.** Unknown message types are counted and reported.
- **Refusals are append-only and user-visible.**
- **Single writer per graph file;** every other access is read-only.
- **Alias maps are re-identification keys** — memory-only by default.
