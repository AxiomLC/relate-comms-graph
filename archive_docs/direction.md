# relate-comms-graph — messaging → local graph (direction doc)

> Status: **research / pre-build.** Not yet started.
> Written 2026-11-13 after `desk-relate` was parked.
> Supersedes the folder-indexing premise of `desk-relate`.
>
> **Doc set:**
> - [`direction.md`](direction.md) - *this file*. Direction, platform reality, architecture.
> - [`llm-models.md`](llm-models.md) - local model & quantisation choices.
> - [`adjacent-notes.md`](adjacent-notes.md) - reusable assets, libraries, prior art, traps.

---

## 1. The idea in one line

Ingest a person's **own message archives** from several platforms into **one local
graph**, so relationships that are split across silos become visible, and run it
**local-only** so the most sensitive data a person owns never leaves the machine.

Not "search your messages." **"See the relationship you couldn't see because it
was spread across four apps."**

---

## 2. Why this beats the folder-indexing idea

| | `desk-relate` (folders) | `relate-comms-graph` |
|---|---|---|
| Data shape | Flat documents, user already filed them | Conversations, already a graph, discarded |
| Graph source | LLM must *infer* entities | Structure is **native** (from/to/reply/thread/attachment) |
| Existing competition | Windows Search, Spotlight, Obsidian | Nothing joins across platforms |
| Privacy angle | Bolted on | The whole reason to use it |
| Demo moment | "I indexed my files" | "This person vanished in 2021 across 3 apps" |

The decisive argument: every competing tool (Neo4j KG Builder, GraphRAG, LightRAG)
extracts *entities from text*. Messaging gives you **edges for free**. That's a
different, more defensible use of a graph database.

---

## 3. What already exists (and what doesn't)

### 3.1 Hermes Agent — the closest thing, and it's unbuilt

[Hermes](https://github.com/NousResearch/hermes-agent) (Nous Research, MIT, ~251k★)
has a messaging gateway for ~22 platforms, but it is a **fan-out adapter layer**
(inbound messages → agent → reply). It does **not** ingest history.

Open feature request **[#12323 — Personal message ingestion pipeline](https://github.com/NousResearch/hermes-agent/issues/12323)**
(often dismissed as unbuilt) asks for almost exactly this project:

- adapters: iMessage, Signal, WhatsApp (Baileys), X DMs, Gmail, later Slack/LinkedIn
- unified store: SQLite/DuckDB at `~/.hermes/people/messages.db`
- identity resolution: merge phone / email / handle / display name → one person
- extraction passes: commitments, meetings, person facts
- marked `innovation` + `type/feature`, **no assignee, no milestone, no PRs**

**Implications:**
- Strong validation that the problem is real and unsolved.
- Hermes' *existing* Baileys bridge (`scripts/whatsapp-bridge/`) and session
  storage at `~/.hermes/platforms/whatsapp/session` are **reusable assets** — we
  already run Hermes here.
- We should consider whether to contribute upstream, or build standalone and
  remain compatible. Standalone first (graph-shaped DB ≠ their SQLite plan).

### 3.2 Tooling worth reusing

| Tool | License | What it gives us | Verdict |
|---|---|---|---|
| **Baileys** (whiskeysockets) | MIT, 11.6k★ | WhatsApp Web protocol over WebSocket, no browser. `syncFullHistory`, `messaging.history-set` for bulk history | **Use it.** Unofficial → ban risk; note it. |
| **whatstk** | GPL-3.0 | Robust WhatsApp `.txt` export parser → pandas | Use for file-based route (mind GPL if redistributing) |
| **pistocop/messaging-chat-parser** | GPL-3.0 | WhatsApp `.txt` + Telegram `result.json` | Reference only (small, 40★) |
| **WhatsApp-Export-Unpacker** | — | Forensic unpacking + voice transcription, local-only | Reference for privacy-first design |
| **telegram-download-chat** | — | CLI/GUI + MCP over `result.json` | Optional; the export alone is enough |
| **Neo4j `SimpleKGPipeline`** | Apache-2.0 | Reference architecture for chunk→entity | Not needed if edges are native |

### 3.3 What nobody has done
- **Cross-platform identity resolution into a graph** (Zingg does ER, but for
  enterprise data, not personal messaging).
- **A scrub/PII gate before ingest.** All existing tools assume you upload.
- **Relate as the store.** Not a moat alone, but it's the hackathon context.

---

## 4. Per-platform reality check

This is the part that decides the demo. **Honest grades only.**

### Telegram — A (best case)
- **Route:** Telegram Desktop → Settings → Advanced → *Export Telegram data* →
  JSON. Produces `result.json` + `chats/` media folder.
- **Schema:** officially documented at <https://core.telegram.org/import-export>.
  Stable, versioned, well-understood.
- **Live API alternative:** Telethon / TDLib (user account, full history, no
  admin rights).
- **Gives:** messages, dates, `from`/`from_id`, reply-to, forwards, media paths,
  contacts (`.vcard` — **contains phone numbers**, useful for joins).
- **Risk:** none significant. User-initiated export or own-account API.
- **Verdict: build first.**

### WhatsApp — B
- **Route A (file):** phone → chat → *Export chat* → `.txt` (+ `.zip` with media).
  Per-chat, manual, one at a time.
- **Route B (live):** Baileys via the existing Hermes bridge. `syncFullHistory: true`
  + `Browsers.macOS('Desktop')` gets substantially more history; bulk history
  arrives via `messaging.history-set` events, and `fetchMessageHistory` pulls
  batches of 50 walking backwards from the oldest message.
- **Critical caveat:** WhatsApp has **no REST history API**. History must be
  *persisted as it arrives* — you cannot re-fetch on demand. Read the docs line:
  *"`fetchMessages()` returns empty arrays because WhatsApp has no REST history API."*
- **Risk:** Baileys is unofficial; **account ban is a real possibility** on
  automated use. Mitigate: read-only, no sending, no bulk automation, dedicated
  number or accept the risk with the user's informed consent.
- **Verdict: second. Prefer the `.txt` export for the demo; Baileys for daily sync.**

### Slack — C
- **Live API:** `conversations.history` requires scopes **and** the workspace plan
  to allow it. Full export is **admin/owner only**.
- **As a normal member:** you can read channels you're in, but DMs are limited and
  history is capped by plan (free tier: 90 days).
- **Route:** user-provided export zip (admin) or bot token with `channels:history`
  / `im:history` — both require permission you may not have.
- **Verdict: only if the user owns the workspace. Otherwise out of scope.**

### Facebook Messenger — B / C
- **Route:** Facebook → *Download your information* → JSON (not HTML). Contains
  message archives in `your_activity_across_facebook/messages/`.
- **Reality:** slow (hours to a day), format shifts over time, no API.
- **Verdict: takeout only, low priority.**

### LinkedIn — **A for data, F for automation**
This is the one you flagged as "the killer." It splits in two:

**Legitimate route (use this):**
- Settings → Data privacy → *Get a copy of your data* → **Download larger
  archive**.
- Contains `messages.csv` (date, sender/recipient, subject, content, profile URL),
  `Connections.csv` (name, company, position, connected-on, **email only if the
  connection allowed it**), `Contacts.csv` (imported contacts **with phone
  numbers**), plus invitations, comments, shares.
- **Mechanics:** arrive in two parts; first email shortly, full archive 1–2 days
  later. User-initiated, fully legitimate, no ban risk.
- **Grade: excellent data.** Messages + connections + contacts with phones is
  exactly what identity resolution needs.

**Automation route (do NOT build):**
- LinkedIn closed third-party messaging APIs years ago and enforces aggressively.
- Mobile-app-protocol hacks / scraping → account restriction. Not worth it for a
  hackathon, and a public repo demonstrating it is a liability.
- **Decision: export-only for LinkedIn. Document it plainly in the README.**

### Email — A
- IMAP (stdlib `imaplib`, read-only) or local `.msg`/`.eml`.
- Gmail needs an **App Password** (2FA required); regular password auth is dead.
- Richest for identity: from/to addresses are stable join keys.

### iMessage / Signal — platform-locked
- iMessage: macOS `chat.db` only — no Windows path.
- Signal: `signal-cli` export or desktop DB.
- **Verdict: out of scope on Windows.**

---

## 5. The hard problem: identity resolution

Everything hinges on this. Be honest about it.

**Join keys, strongest → weakest:**

| Key | Available in | Notes |
|---|---|---|
| Phone (E.164 normalised) | WhatsApp, Telegram contacts, LinkedIn `Contacts.csv`, Signal | **Best key.** Requires normalisation (`+44…` vs `07700…`). |
| Email (lowercased) | Email, LinkedIn (`if shared`), Slack | Strong, but LinkedIn emails are often withheld. |
| Platform handle | per-platform | Weak alone; only joins within one platform. |
| Display name | all | Fuzzy. "Dave S", "Dave Sartori", "dave" — same person. |

**Design decision — two edge types, never one:**

```
MATCHED_BY  (confidence 1.0)   phone→phone, email→email
POSSIBLY    (confidence 0.4–0.8)  name similarity + shared context
```

Never silently merge on a fuzzy name. Showing a user *"possible match: yes/no"* is
more honest than pretending resolution is solved — and it demos better, because the
uncertain edges are visually interesting.

**Scrub interaction:** the PII layer **must not destroy the join key before it's
used**. Scrub *after* resolution, or keep a local-only key table. Alias
(`PHONE-1`) must be stable per person across the whole graph.

---

## 6. Proposed architecture

```
exporters/            one per platform, all → canonical Message records
  telegram_json.py    result.json
  whatsapp_txt.py     _chat.txt (+ media zip)
  whatsapp_baileys/   live, optional daily sync (via Hermes bridge or own)
  linkedin_zip.py     messages.csv + Connections.csv + Contacts.csv
  imap.py             read-only IMAP fetch
  eml_msg.py          local .eml / .msg

  ↓  Message{ id, platform, thread, sender{name,phone,email,handle},
              ts, body, attachments[], reply_to, raw_ref }

resolve/              identity resolution → Person nodes
  normalise.py        phone → E.164, email → lower, name → sort key
  match.py            exact keys first, then fuzzy with confidence

scrub/               PII gate (reuse desk-relate's knobs model)
  rules.py            keep | hide | block per class
  alias.py            stable local alias per person/entity

graph/                Message/Person/Thread/Attachment → .rl
  cypher.py           build statements
  writer.py           single writer, read-only everywhere else
```

**Node/edge sketch:**

```
(:Person {key, display_name})
(:Thread {key, platform, title})
(:Message {key, platform, ts, body_scrubbed, has_attachments})
(:Attachment {key, filename, mime, hash})

(:Person)-[:SENT]->(:Message)
(:Message)-[:IN]->(:Thread)
(:Message)-[:REPLY_TO]->(:Message)
(:Message)-[:HAS]->(:Attachment)
(:Person)-[:POSSIBLY|MATCHED_BY]->(:Person)
(:Thread)-[:ON]->(:Platform)
```

Message IDs must be stable across re-ingest: `platform + chat_id + message_id`.

---

## 7. Demo script (3 minutes)

1. Drop three archives in a folder: **Telegram JSON**, **WhatsApp `.txt`**,
   **LinkedIn zip**.
2. Run ingest. Show the refusal log + what was scrubbed.
3. **Query:** *"Who did I talk to about [topic] on more than one platform, and
   when did it stop?"*
4. Graph shows one `Person` with edges into all three platforms, a timeline, and
   a cluster that goes quiet.
5. **Redaction demo:** flip `phones: block`, re-run → graph shape identical, PII
   gone, refusal log lists what was withheld.

Step 3 is the shocker. Step 5 is the differentiator vs every existing tool.

---

## 8. Daily ingest

Feasible for email (IMAP), Telegram (Telethon), and WhatsApp (Baileys while
session alive). **Not** feasible for LinkedIn or Messenger — those are manual
takeouts, so treat them as periodic full re-imports with dedupe on message ID.

Delta model: same as `desk-relate` — per-source stable ID + content hash, ledger
of what was seen. No need to re-scan everything.

---

## 9. Open questions

1. **Standalone or Hermes skill/plugin?** Leaning standalone, but reading
   `~/.hermes/platforms/whatsapp/session` avoids re-pairing. Ask: would you rather
   this be a Hermes module?
2. **Ban risk tolerance** on WhatsApp via Baileys — dedicated number, or
   export-only for the demo?
3. **First two platforms** — proposal: Telegram + WhatsApp (`txt`). LinkedIn as
   step three once you confirm you have an export.
4. **Scrub before or after resolution?** Proposal: resolve → scrub → write, with
   an in-memory-only key table.
5. **Which hackathon repo** — new `relate-comms-graph`, or fold into `Relate`?

---

## 10. Sources

- Hermes personal message ingestion request — <https://github.com/NousResearch/hermes-agent/issues/12323>
- Hermes WhatsApp/Baileys bridge — <https://hermes-agent.nousresearch.com/docs/user-guide/messaging/whatsapp>
- Baileys — <https://github.com/whiskeysockets/Baileys> · <https://baileys.wiki>
- Baileys history limits — <https://chat-sdk.dev/adapters/community/baileys>
- Telegram export schema — <https://core.telegram.org/import-export>
- LinkedIn data download (what's included) — <https://www.linkedin.com/help/linkedin/answer/a1339364/downloading-your-account-data>
- LinkedIn connections export limits (missing emails) — <https://www.linkedin.com/help/linkedin/answer/a566336/export-connections-from-linkedin>
- whatstk — <https://whatstk.readthedocs.io>
- Neo4j LLM KG Builder (prior art) — <https://github.com/neo4j-labs/llm-graph-builder>
