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

## Terms — the short key

Five words mean five specific things in this app. Everything else is prose.

| Term | Means | Never means |
|---|---|---|
| **Owner** | The account owner — whose archives these are. One per platform, stored in `store/profile/identity.json`. | Not a node. Not shown in the UI except as "you" in a message body. |
| **Correspondent** | The other party in a conversation, **on one platform**. A fact from the export, keyed `<platform>:<name>`. | Not a person across platforms. Not an extracted entity. |
| **Platform** | The source: `telegram`, `messenger`, `email`, `linkedin`, `whatsapp`, `outlook`, `sms`. Shown as Telegram, Fcbk Mssgr, Email, LinkedIn, WhatsApp, Outlook, SMS. | Not the file you ingested. Not the user's download. Not the provider — Outlook-over-IMAP is **Email**. |
| **Thread** | One conversation. | Not a message. |
| **Message** | One message. | Not a thread. |

Three more, for the ingest path:

| Term | Means |
|---|---|
| **Download** | The raw file the user got from the platform. Never moved, never deleted. |
| **Export** | The copy inside `spool/`, which is what actually gets parsed. |
| **Root** | The spool queue to read: `spool/real/`. There is **one** queue — a generated sample is just a file dropped in it, and `ingest` cannot tell it from a real export. |

**`Person`, `Place`, `Organization`, `Product` are not terms in this app yet.** They name a
*future* extraction step: entities pulled out of a message body that are neither the Owner
nor a Correspondent. Nothing in the store, the code or the UI uses them today.

**Display note:** the platform key `messenger` is stored as-is (it is part of every
`Message.key`), but the UI always shows it as **Fcbk Mssgr** — never bare "Messenger",
which reads as "a message". The mapping lives in one place,
`PLATFORM_LABELS` in `app/ui/src/config/nodeTypes.js`.

**Outlook is its own platform, not a variant of Email.** The same Outlook account can
arrive two ways and lands on two different lines:

| route | platform | shown as | colour |
|---|---|---|---|
| `.pst` export dropped in the spool | `outlook` | Outlook | purple |
| live IMAP (`--email outlook`) | `email` | Email | red |

That is deliberate. A `.pst` is a file exported at a point in time; IMAP is a live
mailbox. Different provenance, different keys, and merging them would make "where did
this come from" unanswerable.

## Why a graph, why local

| | |
|---|---|
| **Native edges** | `from` / `to` / `reply_to` / `thread` are data fields, not LLM guesses. Most "documents → graph" tools guess at structure; here it is given. |
| **Identity resolution** | The same person appears on three platforms as three Correspondents. Merging them is a real problem, and the demo's money shot. |
| **Privacy by construction** | These are the most sensitive files a person owns. Everything runs locally, and a scrubbing gate sits *before* the write, not after. |
| **No server** | Relate is an embedded engine — one `.rl` file, no port, no Bolt. That is also why this project has its own Cypher writer: every off-the-shelf graph-extraction library needs a Neo4j server to connect to. |

## Where the data lives

**One file holds everything: `store/graph.rl`.** No CSV, no database server, no export
between parse and write. Exports land in `spool/real/<platform>/`, are read into in-memory
records, and merged into that single file.

```
spool/
  real/     telegram/  whatsapp/  messenger/  linkedin/  outlook/  sms/  imap/  gmail/
store/
  graph.rl      the graph — every message, every correspondent
  profile/      identity.json — which account is the Owner, per platform
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
python -m relate_comms ingest --which real --email hostinger --tz-offset -5
```

Per-platform download instructions live in
[`archive_docs/MssgDownloadInstructs.md`](archive_docs/MssgDownloadInstructs.md).

**No real exports yet?** `python -m sample_writer` writes a full fake batch to
`sample_writer/out/` — every platform, every shape the app has a switch for. Drop those in
the same way: `ingest` cannot tell them from a real download. See
[`sample_writer/README.md`](sample_writer/README.md).

### What the demo looks like

1. Drop three archives in: Telegram JSON, WhatsApp `.txt`, LinkedIn zip. (Email reads live.)
2. Ingest — show the refusal log and what was scrubbed.
3. Ask: *"Who did I talk to about [topic] on more than one platform, and when did it stop?"*
4. One `Correspondent` node per platform, edges into each Thread, a timeline, a cluster
   that goes quiet.
5. Flip `phones: block`, re-ingest → same graph shape, PII gone, refusal log lists what
   was withheld.

## Platform reality

| Platform | Grade | Route |
|---|---|---|
| **Telegram** | **A** | Desktop export → `result.json` (officially documented schema) |
| **Email (Gmail)** | **A** | IMAP read-only, App Password. Verified live |
| **Email (Hostinger / cPanel)** | **A** | IMAP read-only, `INBOX` + `INBOX.Sent`. Verified live |
| **Outlook (`.pst`)** | **A** | Export to a `.pst` and drop it in. Verified against a real file |
| **Outlook (live IMAP)** | **F** | Basic auth is dead; needs OAuth2. Lands on the **Email** line |
| **WhatsApp** | B | Per-chat `.txt`/`.zip`. No all-chats export; media placeholders only |
| **LinkedIn** | **A data / F automation** | *Basic* archive → `messages.csv`. Export only |
| **Facebook Messenger** | B/C | *Download your information* → HTML archive. Slow, no API |
| **SMS** | **A** | *SMS Backup & Restore* XML or `.xml.zip`. Verified |
| **Slack** | C | Export needs workspace admin. Not viable |
| **Instagram** | — | Out of scope. Export names no sender |

## Status

**Ingested:** 2,003 messages, 93 correspondents across all seven platforms — Telegram 851 ·
Messenger 655 · Email 151 · SMS 139 · WhatsApp 108 · LinkedIn 93 · Outlook 6. **34
correspondents merged across platforms**, 7 `POSSIBLY` edges.

**Built:** seven file adapters + live IMAP, parallel parse → resolve → scrub → serialised
write → verify → prune, 12-tool layer, FastAPI, and the UI.

**Not built:** body-entity extraction (`Person`, `Place`, `Organization`, `Product`),
semantic search (Relate supports vector indexes; none exists in this store yet).

`pytest tests -q` → **400 passed, 2 skipped**.

## Docs

| Doc | What's in it |
|---|---|
| [`TECHREADME.md`](TECHREADME.md) | Module map, key functions, commands, Relate/Neo4j references — written for an AI |
| [`HANDOVER.md`](HANDOVER.md) | Short, dated, newest at the bottom — what is next |
| [`UIVISUALS.md`](UIVISUALS.md) | Settled UI and visual facts: glows, colour parsing, stylesheet order, the merged-node template |
| [`CytoGravityRecommend.md`](CytoGravityRecommend.md) | Working log for the canvas layout investigation — what fcose actually honours, and the traps. Superseded by `UIVISUALS.md` as facts settle |
| [`archive_docs/MssgDownloadInstructs.md`](archive_docs/MssgDownloadInstructs.md) | How to get each platform's export |
| [`archive_docs/HowToRunOllama.md`](archive_docs/HowToRunOllama.md) | Local model setup on this machine |

## Design principles

- **Deterministic before LLM.** Parsing, normalisation, exact matching and shape scrubbing
  never need a model. Enrichment is optional.
- **Never a silent drop.** Unknown message types are counted and reported.
- **Refusals are append-only and user-visible.**
- **Single writer per graph file;** every other access is read-only.
- **Alias maps are re-identification keys** — memory-only by default.
- **Visually: A node is: halo (behind) → circle body → SVG → border → label.** Five things, in that order. The halo is behind the circle, not between circle and SVG. Selection is the border layer, not a halo.
