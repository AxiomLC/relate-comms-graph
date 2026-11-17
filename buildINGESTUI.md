# buildINGESTUI.md

**Temporary.** Delete this file once the ingest UI is wired and tested end to end.
It exists because the ingest flow is half-built: the modal has controls the server
does not honour, and the server has parameters the modal never sends. Neither is
written down anywhere else, and a half-wired flow is the easiest thing in this app to
mistake for a finished one.

Newest decisions at the bottom. `TECHREADME.md` holds the durable facts; this holds the
**gap**.

---

## 1. The flow we agreed on

Three steps, and the middle one is the point:

```
1. INSPECT   read headers only, no bodies, no writes
             -> per leg: total rows + a month histogram
2. DECIDE    the user sees the counts and picks a window
             -> this is the only place a big export may be narrowed
3. INGEST    parse with the chosen window, then write
```

**Why not cap during ingest:** by the time a cap fires, the file is already parsed and
the time already spent. Inspecting first means the user chooses with real numbers in
front of them instead of discovering the size afterwards.

**Why not a hard "1k threads → refuse":** it fails after the work is done, and thread
count does not track cost (1,000 threads of 3 messages is small; 50 threads of 700 is
35,000 messages). Measured on this machine: 200,000 messages writes in 42 s, the file
is 85 MB, point lookups stay at 2 ms and thread traversal at 15 ms. Only full scans
grow — a time-window query went 27 ms at 50k to 153 ms at 200k. **The store scales
fine; search latency is the only thing that degrades.**

---

## 2. The modal, in order

The modal is the product's honesty surface. It states what each platform actually
demands instead of pretending a magic import exists.

### Area 1 — What to download (tab)

Static guidance per platform. No controls. Already correct.

### Area 2 — Paths and mailboxes (tab)

| Control | State | Notes |
|---|---|---|
| Export path(s), one per line | **wired** | Files are copied into `spool/real/<platform>/`, chosen by content |
| Mailboxes (comma-separated) | **wired** | Live IMAP; credentials come from `.env` |
| tz offset (hours) | **wired** | Telegram / WhatsApp / Messenger only |
| **How far back** — 3m / 6m / 12m / All | **wired** | Sends `since`; counts per option appear once inspect lands |
| **Include groups where the Owner never spoke** | **NOT WIRED** | See §3 |
| Skip spam group threads (Messenger) | **wired** | `exclude_spam_groups` |
| Prune verified spool files older than 3 days | **wired** | Needs `--confirm` on the CLI; the UI sends `prune` |

### Area 3 — Report

Per batch: messages, attachments, verified, pruned, warnings, skipped counts. Already
correct. **The skipped counts are the honesty mechanism** — a dropped thread is always
counted with its reason, never silently lost.

---

## 3. The gap: "Include groups where the Owner never spoke"

**Agreed behaviour.** Default **checked**. Applies to **Telegram, WhatsApp and
Messenger only**. Deselecting drops those threads. Parse-time gate, **before node
creation**, so a deselected group never enters the store.

**Why default-on:** it matches `TECHREADME.md` §5 — *the store is whole unless the user
asks otherwise*. Nothing is silently missing; the user opts out deliberately.

**Why groups only:** a 1:1 thread with someone who messaged once is still a conversation
the owner had. The rule is about groups the owner was added to and never spoke in.

### What exists today

`exclude_silent_groups` is implemented **for Messenger only**:

- `adapters/messenger.py:340` — the gate, before `result.messages.extend(rows)` and
  before the `Chat` is appended. Correct ordering: a dropped thread leaves no orphan
  messages behind.
- `ingest.py:337` — **pops the flag for every platform except Messenger.** This is the
  line that must change.
- `tools.py`, `routers/ingest.py` — plumbed through, default `False`.

### What must change

1. **`ingest.py:337`** — stop popping it for Telegram and WhatsApp. Keep popping it for
   platforms that have no group concept (email, linkedin, outlook, sms).
2. **`adapters/telegram.py`** — add the gate. `is_group` is already computed
   (`chat_kind not in {"personal_chat", "bot_chat", "saved_messages"}`).
3. **`adapters/whatsapp.py`** — add the gate. `is_group` is already computed
   (`SELF_NAME in senders and len(senders) > 3`).
4. **Default flips to `True`** in `tools.ingest` and `IngestRequest`, and the modal
   sends it checked.
5. **UI control** in Area 2, default checked, labelled *"Include groups where the Owner
   never spoke"*.

### Measured impact on the real store

| platform | group threads | messages | owner-silent |
|---|---|---|---|
| messenger | 70 | 9,513 | **70 (all)** |
| telegram | 9 | 35 | 0 |
| whatsapp | 0 | 0 | 0 |
| email | 1 | 1 | 1 |

**Messenger is the whole problem** — 70 group threads, all owner-silent, holding 9,513 of
10,605 Messenger messages. Telegram's 9 groups are all ones the owner spoke in, so the
gate is a no-op there today. WhatsApp has no group threads in this store, so **the
WhatsApp gate ships untested** unless a group export is provided.

---

## 3b. The gap: email and Outlook spam threads

**Agreed rule.** At ingest, for **Email and Outlook only**: exclude threads with **more
than 15 messages where the Owner never talks**. Likely spam.

**Why a size threshold, and why only these two legs.** A 1:1 thread someone started with
you is a real conversation, so "owner never spoke" alone is not enough to drop mail. But
a *long* thread the owner never contributed to is almost always a broadcast, a
notification chain, or a mailing list — the shape spam takes in a mailbox. The 15-message
floor is what separates "someone emailed me and I did not reply" from "I am on a list".

**Why not the same rule as the group gate.** `exclude_silent_groups` is group-scoped and
applies to Telegram / WhatsApp / Messenger. Email has no group concept, so it needs its
own rule with its own threshold. Do not merge them.

**Measured on the current store:** 68 email threads, 44 owner-silent, but the largest
silent thread is only 2 messages — so this rule would drop **nothing** today. It exists
for a real mailbox, where a 100-message mailing-list thread is normal.

**Implementation notes when it is built:**

- Needs `Message.is_self` resolved *before* the thread decision, so the gate runs after
  the rows are parsed but before they are committed — the same ordering as the Messenger
  gate, so a dropped thread leaves no orphan messages.
- For IMAP the rows arrive one `FETCH` at a time, so the gate must buffer per thread or
  run as a post-pass over `result.messages` before `result.chats` is built.
- Counted as `skipped["spam thread (long, owner silent)"]`, never silently dropped.
- Off by default or on by default is **undecided** — the silent-groups toggle is
default-on, and this is the same family of decision.

## 4. The gap: pre-inspection

`api.inspect` **does not exist**. The modal calls it, gets `null`, and says so plainly
rather than pretending. Nothing is broken by the gap.

### The contract it must satisfy

```
POST /api/ingest/inspect  { paths: [...], email: [...] }
-> {
     legs: [{
       platform: "whatsapp",
       path: "…",
       total: 124000,                  // exact when the format states it
       months: {"2026-05": 9000, …},   // drives the window counts
       estimated: true,                // false when the count is exact
     }],
     total: 137000,
   }
```

### Cost per format, so the estimate is honest

| format | cost | how |
|---|---|---|
| SMS | **free** | `<smses count="…">` is in the first 4 KB |
| IMAP | **cheap** | `SEARCH` per folder, no `FETCH`, so no bodies downloaded |
| Telegram | streaming pass | timestamps only, no bodies |
| PST | folder walk | `number_of_sub_messages` per folder |
| WhatsApp | **full read** | no header count exists; the whole `chat.txt` must be read |

### The honest caveat

A month histogram requires reading every row, so "pause at 50k" cannot stop early — it
has to finish the file to know the distribution. The flow is therefore *"inspect fully,
write nothing, show the histogram, ask"*, not *"stop mid-parse"*.

---

## 5. Naming collision to avoid

Two controls mean the same thing and must never be confused:

| Where | Wording | Consequence |
|---|---|---|
| **Canvas** modal | "Hide threads where the owner never sent a message" | **View only.** Reversible. Still searchable. |
| **Ingest** modal | "Include groups where the Owner never spoke" | **Parse time.** Permanent. Never stored. |

Opposite polarity, different scope (all threads vs groups only), completely different
consequence. Word them so a user cannot mistake one for the other.

---

## 6. Decisions already settled

- **Timeframe slider** — 3 months / 6 months / 12 months / All. `since`/`until` are
  already honoured by every adapter and plumbed through the API, CLI and tools; only the
  UI was missing, and it now sends `since`.
- **No hard message-count cap.** A soft budget that reports, not a refusal.
- **No manual node sizing in the UI.** Sizes A–F are computed per platform; the table
  moved to `config/theme.js` as a dev knob.
- **Canvas modal** — sort, node count, node types, viewable platforms, hide-silent.
  Styling is a sub-modal with force + label zoom only.
- **Icons are the only node look.** The Circles/Icons title-bar toggle is gone, along
  with `visual.nodeIcons` and `visual.correspondentIcons`. Threads draw their platform
  glyph, correspondents the person glyph, unconditionally. `iconScale` and
  `correspondentIconScale` remain as dev knobs in `config/theme.js`.
  **The icon styling is an override on the base circle, not a replacement for it** —
  so a platform with no icon file keeps the base fill and stays visible.
- **Viewable platforms** — all on by default; `platforms: []` means "not chosen yet" =
  everything on, so a platform added later appears without ticking.
