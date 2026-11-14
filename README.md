# relate-comms-graph

**Your own message archives — across platforms — as one local, privacy-scrubbed graph.**

> ✅ **Working prototype.** Five adapters, live email, identity resolution and a scrub
> gate. See [Status](#status).

---

## The idea

Messaging is already a graph. Every message has a sender, a recipient, a thread, a
reply target, a timestamp, an attachment. That structure is **explicit** — unlike
documents, where a graph tool has to guess at entities from prose.

It is also **fragmented**. Nobody can search across WhatsApp, Telegram, Slack,
Messenger and LinkedIn at once. Each is a separate silo with its own export format.

So the interesting question isn't *"can I search my messages"* — it's:

> **"Who did I talk to about X across more than one platform, and when did it stop?"**

That relationship exists in your data today and is invisible, because it's split
across four apps. A graph makes it visible.

## Why a graph, why local

| | |
|---|---|
| **Native edges** | `from`/`to`/`reply_to`/`thread` are data fields, not LLM inferences. Most "documents → graph" tools guess at structure. Here it's given. |
| **Identity resolution** | The same person appears on 3 platforms under 3 identities. Merging them is a real, respected problem — and the demo's money shot. |
| **Privacy by construction** | These are the most sensitive files a person owns. Everything runs locally; a scrubbing gate sits *before* ingest, not after. |
| **Competition** | Every mature tool (Neo4j KG Builder, GraphRAG, LightRAG, CocoIndex) is documents-only. Nobody joins messaging silos into one graph with a PII gate. |

## Docs

| Doc | What's in it |
|---|---|
| [`MssgDownloadInstructs.md`](MssgDownloadInstructs.md) | **Start here.** How to get each platform's export, what the file looks like, and how ingest reports back |
| [`buildNOTES.md`](buildNOTES.md) | Engineering notes: schema, pipeline, per-platform traps found in real exports, decisions |
| [`HowToRunOllama.md`](HowToRunOllama.md) | Local model setup |

## Platform reality, at a glance

| Platform | Grade | Route |
|---|---|---|
| **Telegram** | **A** | Desktop export → `result.json` (officially documented schema) |
| **Email (Gmail)** | **A** | IMAP read-only, App Password. Verified live: 250 msgs in a 30-day window |
| **Email (Hostinger / cPanel)** | **A** | IMAP read-only, `INBOX` + `INBOX.Sent`. Verified live: 221 msgs, 68 conversations |
| **Email (Outlook)** | **A file / F live** | Basic auth is dead, so live IMAP needs an Azure app. **Use the `.pst` export button** — the app reads the file |
| **WhatsApp** | B | `.txt`/`.zip` per-chat export. No all-chats export; media placeholders only |
| **LinkedIn** | **A data / F automation** | *Basic* archive → `messages.csv`. **Export only — never automate** |
| **Messenger** | B/C | `Download your information` → HTML archive. Slow, no API |
| **Slack** | C | Full export needs workspace **admin**. Not viable for a normal member |
| **Instagram** | — | **Out of scope.** Not this app's messaging; the export names no sender |

**Other email providers** (Yahoo, iCloud, Fastmail, Zoho, Proton, any IMAP host) work
through the same read-only IMAP reader: it asks the server which folder is "sent" or
"all mail" using the standard mailbox flags (RFC 6154), and falls back to common names
(`Sent`, `INBOX.Sent`, `Sent Items`, `Bulk Mail`). Only Gmail and Hostinger are proven
against live mailboxes on this machine; the rest are untested. Per-provider servers and
quirks are listed in [`MssgDownloadInstructs.md`](MssgDownloadInstructs.md).

Why a graph tool should not hardcode email folders: they are **not standardised** and
several providers *translate* them (Gmail in Spanish returns `[Gmail]/Todos`). Asking the
server avoids a silent zero-message import.

## What the demo looks like

1. Drop three archives in a folder: Telegram JSON, WhatsApp `.txt`, LinkedIn zip.
   (Email is the fourth source and reads live instead of from a file.)
2. Ingest — show the refusal log and what was scrubbed.
3. Query: *"Who did I talk to about [topic] on more than one platform, and when did it stop?"*
4. One `Person` node, edges into three platforms, a timeline, a cluster that goes quiet.
5. Flip `phones: block`, re-run → graph shape identical, PII gone, refusal log lists what was withheld.

Step 3 is the shock moment. Step 5 is what no existing tool does.

## Design principles (carried over from earlier work)

- **Deterministic before LLM.** Parsing, normalisation, exact matching and shape
  scrubbing never need a model. Enrichment is optional.
- **Never a silent drop.** Unknown message types get counted and reported.
- **Refusals are append-only and user-visible.**
- **Single writer per graph file;** every other access is read-only.
- **Alias maps are re-identification keys.** Decide explicitly whether they're encrypted.

## Status

Five adapters ingest real data into a local Relate store: **Telegram, WhatsApp, Messenger,
LinkedIn** (from exported files) and **email** (Gmail + any IMAP mailbox live, Outlook from
a `.pst`). Resolution merges the same person across platforms; a scrub gate withholds
phones, emails, addresses and card numbers before anything is written.

11,066 mixed messages ingest in ~3 s. `pytest tests -q` → 94 passed.

Not built yet: SMS, the UI, and persisting `Person`/`Identity` into the store.
See [`buildNOTES.md` §10](buildNOTES.md) for the handover.

**Email setup:** copy `.env.example` to `.env` and fill in your mailbox credentials.
`.env` is gitignored and never committed.

## Scope note

This replaces an earlier project (`desk-relate`) that indexed local documents. That
approach was measured and parked: documents span ~40 file extensions in one real
folder, each needing its own flattening and scrubbing rule, and regex scrubbing
provably misses how people actually write secrets. Messaging has explicit structure,
which is why it's the better input.
