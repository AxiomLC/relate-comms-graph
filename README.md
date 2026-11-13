# relate-comms-graph

**Your own message archives — across platforms — as one local, privacy-scrubbed graph.**

> 🚧 **Pre-build. Research and design only.** No code yet. This repo currently holds
> the direction, the platform-by-platform reality check, and the resolved traps.

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
| [`docs/direction.md`](docs/direction.md) | The full direction: per-platform reality check (with honest grades), architecture, graph schema, demo script, daily-sync model |
| [`docs/llm-models.md`](docs/llm-models.md) | Local model & quantisation choices — and why most of this pipeline needs no LLM at all |
| [`docs/adjacent-notes.md`](docs/adjacent-notes.md) | Reusable code from prior work, libraries worth knowing, prior art, and traps already paid for |

## Platform reality, at a glance

| Platform | Grade | Route |
|---|---|---|
| **Telegram** | **A** | Desktop export → `result.json` (officially documented schema), or Telethon. **Build first.** |
| **Email** | **A** | IMAP read-only, or local `.eml`/`.msg`. Best join key (addresses). |
| **WhatsApp** | B | `.txt` export (manual, per-chat) or Baileys via Hermes bridge. No REST history API — persist as it arrives. Ban risk is real. |
| **LinkedIn** | **A data / F automation** | *Get a copy of your data* → archive has `messages.csv`, `Connections.csv`, `Contacts.csv` (with phones). **Export only — never automate.** |
| **Messenger** | B/C | Facebook takeout JSON. Slow, no API. |
| **Slack** | C | Full export needs workspace **admin**. Not viable for a normal member. |

Full reasoning, including why LinkedIn is "the killer you named is the one that kills
you," is in [`docs/direction.md`](docs/direction.md#4-per-platform-reality-check).

## What the demo looks like

1. Drop three archives in a folder: Telegram JSON, WhatsApp `.txt`, LinkedIn zip.
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

Nothing is built. Next step, per [`docs/adjacent-notes.md`](docs/adjacent-notes.md#7-suggested-first-build-order):
a canonical `Message` schema plus a Telegram `result.json` adapter — no LLM, no
credentials beyond your own export.

## Scope note

This replaces an earlier project (`desk-relate`) that indexed local documents. That
approach was measured and parked: documents span ~40 file extensions in one real
folder, each needing its own flattening and scrubbing rule, and regex scrubbing
provably misses how people actually write secrets. Messaging has explicit structure,
which is why it's the better input.
