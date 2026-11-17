# UNDESIRABLES.md

**Temporary.** For `sample_writer`. Delete once the generator covers §12 and §11 is
closed.

**Rewritten 2026-11-17 after the other agent's review.** Five of its six objections were
right and are now answered inline. §14 records the status of the app gaps that were
originally filed here; the app-change log itself has been retired.

---

## 0. The contract

Every item below is a real shape from a real export. Each one has a **switch** in the
app — an ingest gate, a Canvas view option, or a Viewer behaviour — because without the
switch the graph is unusable. A generator that emits only clean conversations proves the
happy path and nothing else.

**Four rules:**

1. **One output, one run.** No divisions. See §13.
2. **Every §12 row present, and countable.** A test must be able to say "there is
   exactly one 10-message silent email thread" without parsing prose.
3. **Determinism.** Same `--seed` → byte-identical output.
4. **Media is never read.** WhatsApp reads only `chat.txt` (or the text of an HTML page),
   Messenger only the HTML, Telegram only `result.json`, LinkedIn only `messages.csv`,
   SMS never decodes `<part data>`, Outlook only message bodies. Generating a 4 GB zip
   with videos tests nothing. Generating a **large** zip does test the copy and the size
   warning.

### Dev knobs, not divisions

The counts below are **defaults**, not law. Put them in `config.py` so a run can be
tuned without editing the generator:

```python
# config.py — every number this doc quotes lives here
OWNER_SILENT_GROUPS = 1        # per group platform
SPAM_GROUP_RATIO = 0.5         # must be >= messenger.SPAM_NOISE_RATIO
EMAIL_LONG_SILENT = (11, 12)   # the two that must drop
EMAIL_BOUNDARY_KEPT = 10       # the one that must not
BIG_THREADS = (200, 500)       # §9
QUIET_YEARS = 3                # §10
```

A knob that changes a shape must not change its **presence**. `BIG_THREADS = (200,)` is
fine; `BIG_THREADS = ()` breaks §12.

---

## 1. Owner-silent group thread

**The biggest one.** 70 Messenger groups in the live store, holding 9,513 of 10,605
Messenger messages.

**Definition:** `is_group = true` and **zero** rows with `is_self = true`.

### How it appears per platform

| Platform | Where | What makes it a group | What makes it silent |
|---|---|---|---|
| **Telegram** | `result.json` → `chats.list[]` | `type` is `private_group`, `private_supergroup`, or `public_channel` — anything not in `{personal_chat, bot_chat, saved_messages}` | no message has `from_id` equal to the owner's `user<id>` |
| **WhatsApp** | `chat.txt` inside the zip | **a membership system row** — see below | no line starts `[date, time] You:` |
| **Messenger** | `message_*.html` under `inbox/<thread>/` | more than one non-owner sender across the sections | no `<h2>` equals the owner's display name |

### WhatsApp — **the rule changed, read this**

The old rule was `You in senders and len(senders) > 3`. **That was a bug and is fixed.**
A group the Owner never wrote in has no `You:` line at all, so it was classified
`personal_chat` and the gate could never fire on it.

The signal is now **a membership system row**, which a 1:1 cannot have:

```
[9/4/26, 10:29:35 AM] - +27 82 352 8161 changed the group name to 'Local Community Events (OSA)'
[9/15/26, 11:32:23 AM] - +7 996 195-97-83 added +7 914 279-89-62
[10/18/26, 9:07:15 PM] - Alice Meiring SO removed +7 921 096-65-88
[10/21/26, 10:29:14 AM] - DSA AO Ingrid removed +7 925 838-77-53
```

The adapter matches `added`, `removed`, `changed the group`, `created group`,
`turned on/off disappearing`, `joined using this group's invite`.

**So a WhatsApp owner-silent group MUST contain at least one membership system row**, or
the generator is emitting something the app cannot classify. Verified against a real
native export: 6 senders, 21 system rows, no `You:` line → `is_group = true`, gate fires.

```txt
Messages and calls are end-to-end encrypted. No one outside of this chat, not even WhatsApp, can read or listen to them.
[9/4/26, 10:29:35 AM] - +27 82 352 8161 changed the group name to 'Neighbourhood Watch'
[9/15/26, 11:32:23 AM] - Alice added Bob
[9/16/26, 8:45:50 AM] Alice: anyone seen the van?
[9/16/26, 8:46:10 AM] Bob: yes, white transit
[9/16/26, 8:47:00 AM] Carol: thanks
```

Four senders, one system row, **no `You:` line**.

### Telegram — concrete

```json
{
  "name": "Neighbourhood Watch",
  "type": "private_group",
  "id": 4471,
  "messages": [
    {"id": 1, "type": "message", "date_unixtime": "1700000000",
     "from_id": "user5551", "from": "Alice", "text": "anyone seen the van?"},
    {"id": 2, "type": "message", "date_unixtime": "1700000060",
     "from_id": "user5552", "from": "Bob", "text": "yes, white transit"}
  ]
}
```

Owner is `user1` (from `personal_information.user_id`). Neither row is `user1`.

### Messenger — concrete

```html
<!-- inbox/4471/message_1.html -->
<section class="_a6-g">
  <h2>Alice</h2>
  <div class="_a6-o"><div class="_a6-p">anyone seen the van?</div></div>
  <footer>Jan 01, 2026 10:00:00 am</footer>
</section>
<section class="_a6-g">
  <h2>Bob</h2>
  <div class="_a6-o"><div class="_a6-p">yes, white transit</div></div>
  <footer>Jan 01, 2026 10:01:00 am</footer>
</section>
```

No `<h2>Mark Jones</h2>` anywhere.

### Assertion

`≥1 per group platform`, `is_group == true`, `is_self` count `== 0`, `message_count >= 2`.
For WhatsApp, **also** `≥1` membership system row.

---

## 2. Spam group thread (Messenger only)

**Definition:** `is_group = true` and **≥50%** of rows match a housekeeping phrase
(`SPAM_NOISE_RATIO = 0.5` in `messenger.py`).

The phrase list is closed — `messenger.py:96-104`:

```
sent a link
added <anything up to 80 chars> to the group
left the group
joined the group
changed the group name
changed the group photo
named the group
created a poll
```

### Messenger — concrete

```html
<!-- inbox/9001/message_1.html -->
<section class="_a6-g"><h2>Facebook user</h2>
  <div class="_a6-o"><div class="_a6-p">Alice sent a link.</div></div>
  <footer>Jan 01, 2026 10:00:00 am</footer></section>
<section class="_a6-g"><h2>Facebook user</h2>
  <div class="_a6-o"><div class="_a6-p">Bob added Carol to the group.</div></div>
  <footer>Jan 01, 2026 10:01:00 am</footer></section>
<section class="_a6-g"><h2>Facebook user</h2>
  <div class="_a6-o"><div class="_a6-p">Dave left the group.</div></div>
  <footer>Jan 01, 2026 10:02:00 am</footer></section>
<section class="_a6-g"><h2>Alice</h2>
  <div class="_a6-o"><div class="_a6-p">hi</div></div>
  <footer>Jan 01, 2026 10:03:00 am</footer></section>
```

3 of 4 rows are noise → ratio 0.75 → dropped when the toggle is on.

**The real file has six such giants at 0.60–0.70.** Generate at least one at **exactly
0.50** (2 of 4) as the boundary case — that one must be **dropped**, since the comparison
is `>=`.

### Assertion

`≥1`, `is_group == true`, `noise_rows / total_rows >= 0.5`.

---

## 3. Long email thread, no Owner reply

**Definition:** `message_count > 10` and **zero** `is_self`.

Note **more than 10** — a 10-message thread is **kept**. That off-by-one is the whole
point of the boundary case.

### How to assert this — **answered**

The other agent was right that there is no `.eml`-discovering adapter, and
`email_imap.detect()` returns `False` by design. **Do not add an `.eml` adapter** — email
is a live mailbox, not a file.

**Assert by calling the parser directly**, which is what the existing tests do:

```python
from relate_comms.adapters import email_imap

result = IngestResult(platform="email", export_path="imap://test")
seen, chats = set(), {}
for path in sorted(thread_dir.glob("*.eml")):
    email_imap._parse_raw(
        path.read_bytes(),
        folder="INBOX",
        uid=path.stem,
        uidvalidity="1",
        result=result,
        seen_keys=seen,
        chats=chats,
        account_address="mark@example.com",   # the Owner
    )
```

Then assert on `result.messages` / `chats`. That is the real parser, the real key
derivation, and the real `is_self` logic — only the IMAP transport is skipped.

**The generator's job** is to emit `.eml` files that this call reads correctly. It does
not need an adapter, and the app does not need to change.

### Email — concrete

```
email_eml/newsletter-1/001.eml   From: digest@list.example   Subject: Weekly digest
email_eml/newsletter-1/002.eml   From: digest@list.example   Subject: Re: Weekly digest
...
email_eml/newsletter-1/012.eml   From: digest@list.example   Subject: Re: Weekly digest
```

12 files, all `From:` a non-owner address, **no** file `From:` the owner. Thread key is
derived from the subject chain, so the subjects must chain (`Re:` prefixes are fine).

### Boundary cases the generator must emit

| Thread | Messages | Owner replied? | Expected |
|---|---|---|---|
| `newsletter-1` | **12** | no | **dropped** |
| `newsletter-2` | **11** | no | **dropped** |
| `boundary-10` | **10** | no | **kept** |
| `replied-12` | **12** | yes, 1 reply | **kept** |
| `short-3` | **3** | no | **kept** |

### Assertion

`≥2` threads at 11+ messages with zero owner rows, **and** exactly one at 10 with zero
owner rows, **and** one at 11+ with an owner row.

---

## 4. Filtered and message-request threads (Messenger)

Messenger writes three thread folders plus a legacy one:

```
your_facebook_activity/messages/
    inbox/<thread>/message_1.html
    filtered_threads/<thread>/message_1.html
    message_requests/<thread>/message_1.html
    e2ee_cutover/<thread>/message_1.html
```

`filtered_threads/` and `message_requests/` are usually strangers and spam.
`e2ee_cutover/` holds legacy encrypted threads — **still real messages, always kept**.

**The other agent was missing `e2ee_cutover/`.** It must be generated, and it must
**survive** `include_filtered=False`.

### What to generate

- `≥1` thread under `inbox/`
- `≥1` thread under `filtered_threads/`
- `≥1` thread under `message_requests/`
- `≥1` thread under `e2ee_cutover/`

Each with a **distinct** thread id, so a test can assert which folders were read.

### Assertion

With `include_filtered=True` (default): all four present.
With `include_filtered=False`: only `inbox/` and `e2ee_cutover/`.

---

## 5. Placeholder correspondents

Real exports contain sender names that are not people.

| Platform | Placeholder | Where it appears |
|---|---|---|
| Messenger | `Facebook user` | `<h2>` in `message_*.html` |
| LinkedIn | `LinkedIn Member` | `FROM` column in `messages.csv` |
| LinkedIn | `LinkedIn Talent Solutions` | `FROM` column |
| SMS | `(Unknown)` | `contact_name` attribute |
| SMS | `Me` | `contact_name` attribute |

In the live store `Facebook user` spans **31 Messenger threads**. The Viewer renders it
with a `placeholder account` pill; the canvas does not yet style it differently.

### Messenger — concrete

```html
<section class="_a6-g"><h2>Facebook user</h2>
  <div class="_a6-o"><div class="_a6-p">hey</div></div>
  <footer>Jan 01, 2026 10:00:00 am</footer></section>
```

### LinkedIn — concrete

```csv
CONVERSATION ID,CONVERSATION TITLE,FROM,TO,SUBJECT,CONTENT,DATE
2-abc,Sponsored Conversation,LinkedIn Member,Mark Jones,Hello,<p>Buy things</p>,2026-01-01 10:00:00 UTC
```

### Assertion

`≥3` Messenger threads titled `Facebook user`, `≥1` LinkedIn thread from
`LinkedIn Member`, `≥1` SMS row with `contact_name="(Unknown)"`.

---

## 6. Zero-message thread

A thread that exists in the export but yields **no** messages — every row was a service
row, or the window excluded everything.

### Telegram — concrete

```json
{
  "name": "Old Group",
  "type": "private_group",
  "id": 8801,
  "messages": [
    {"id": 1, "type": "service", "date_unixtime": "1700000000",
     "actor": "Alice", "action": "join_group_by_link"}
  ]
}
```

One service row, no `type: "message"` row → the adapter emits **no `Chat`** and counts
`skipped["chat with no non-service messages"]`.

**The other agent's note is right:** an empty `messages: []` array also produces this,
but titling the thread `(no messages)` is a giveaway. Use a real-looking name.

### WhatsApp — concrete

A `chat.txt` whose only lines are system rows:

```
[5/22/26, 8:45:50 AM] Messages and calls are end-to-end encrypted.
[5/22/26, 8:46:00 AM] Alice added Bob.
```

### Assertion

`≥1 per platform`, present in the export, **absent** from `result.chats`, counted in
`result.skipped`.

---

## 7. Service-only rows inside a live thread

Different from §6: the thread **has** real messages, and also has service rows. Those
rows must be **kept** by default (`include_service=True`) and kinded `service:*`.

### Telegram — concrete

```json
{"id": 3, "type": "service", "date_unixtime": "1700000120",
 "actor": "Bob", "action": "pin_message"}
```

### WhatsApp — concrete

```
[5/22/26, 8:47:00 AM] Alice changed the subject to "Trip"
```

### Assertion

`≥1` thread per platform containing both a `type: "message"` row and a `type: "service"`
row; with `include_service=False` the service rows are gone and counted
`skipped["service excluded by request"]`.

---

## 8. One-to-one thread the Owner never replied to — **KEEP THIS**

**Not an undesirable.** This is the boundary case that proves the group gate is
group-scoped. A 1:1 someone started with you is a real conversation; hiding it is a
**view** toggle, not a parse-time drop.

### Telegram — concrete

```json
{
  "name": "Stranger",
  "type": "personal_chat",
  "id": 9901,
  "messages": [
    {"id": 1, "type": "message", "date_unixtime": "1700000000",
     "from_id": "user7777", "from": "Stranger", "text": "hi, is this Mark?"}
  ]
}
```

`type: "personal_chat"` → `is_group = false` → the gate **must not** fire.

### Assertion

`≥1 per platform`, `is_group == false`, `is_self` count `== 0`, and it **survives**
`exclude_silent_groups=True`.

---

## 9. Very large thread

### What to generate — **settled**

**Bake 200 and 500 in. Do not generate 1,600.**

The 1,624 figure is an artefact of the current store, built with every gate **off**. Once
a real wipe-and-re-ingest runs with the silent-group toggle on, Messenger's 70
owner-silent groups (9,513 messages) drop out and the largest thread falls to the low
hundreds. Generating 1,600 would test a shape the app is designed to remove.

| Thread | Messages | Always? |
|---|---|---|
| `big-200` | 200 | **yes** |
| `big-500` | 500 | **yes** |
| `big-1600` | 1,600 | **no — opt-in flag only** |

`--huge` (or `BIG_THREADS = (200, 500, 1600)`) emits the 1,600 case for a one-off paging
test. It is not part of a normal run, because it costs 1,600 messages every time and
tests a shape the gates exist to trim.

Spread the timestamps over years, not one day — a 500-message thread in one hour is not
realistic and breaks the month histogram.

### Assertion

`≥1` thread at 200+, `≥1` at 500+, timestamps spanning ≥2 years. **No thread above 600
unless `--huge`.**

---

## 10. Quiet thread

A thread whose last message is years old, sitting beside live ones.

### Why it matters

The Canvas sort options are `messages` / `recent` / `quiet`. `quiet` keeps the ones that
went silent — the question this app exists to answer.

### What to generate

`≥1 per platform` whose **last** message is 3+ years before the newest message in the
whole export.

### Assertion

`≥1` thread per platform where `max(ts)` is ≥3 years older than the export's `max(ts)`.

---

## 11. WhatsApp — two dialects, both must be generated

**New since the last review.** WhatsApp now has two export routes and the app reads
both. They are the same platform and the same chat, so the generator should emit the
same conversation in both shapes at least once — that is what proves the dedup works.

### 11a. Native `chat.txt` (one chat per zip)

```
Thad Zurawski Chicago.zip
    chat.txt
    chat.md
```

`chat.txt` lines:

```
[11/16/26, 3:01:48 PM] You: Hey man
[11/16/26, 11:09:15 PM] Thad Zurawski Chicago: Hey Dave
[11/16/26, 11:19:20 PM] You: Yea sure
```

**The chat title is the ZIP FILENAME.** That is how `_chat_id()` derives the thread key,
so the filename must be the contact or group name.

### 11b. HTML (many chats per zip)

```
whatsapp-chats-20261117.zip
    chats/Thad_Zurawski_Chicago.html
    chats/Michael_Metzler.html
    groups/AOAF_B-DAY_GAME_CHAT___.html
    index.html
```

One page per chat:

```html
<div class="hd">Thad Zurawski Chicago<small>Chat · 11 messages · exported 17 Nov 2026</small></div>
<div class="msgs">
  <div class="daysep"><span>16 Nov 2026</span></div>
  <div class="row out"><div class="bubble"><div class="txt">Hey man</div>
    <div class="time">15:01</div></div></div>
  <div class="row in"><div class="bubble"><div class="txt">Hey Dave</div>
    <div class="time">23:09</div></div></div>
</div>
```

**The header states group-ness**: `Group · 307 messages` vs `Chat · 11 messages`.
**The row class states owner-ness**: `row out` is the Owner, and those rows carry **no
sender div**. In a group, `row in` rows carry `<div class="sender">Name</div>`; in a 1:1
they do not, and the correspondent is named from the chat title.

### What to generate

| Shape | Always? |
|---|---|
| one native `chat.txt` zip, 1:1 | **yes** |
| one native `chat.txt` zip, group with a membership row | **yes** |
| one HTML zip with a 1:1 and a group | **yes** |
| **the same chat in both dialects** | **yes** — this is the dedup test |

### Assertion

- both dialects produce the **same `chat_id`** for the same chat title
- both dialects produce the **same message keys** (46 of 47 measured on real files; the
  one difference is a contact card, where `chat.txt` embeds a raw vCard and the HTML says
  `👤 Contact card` — the HTML wording is kept deliberately)
- ingesting both into one store adds **no duplicate conversation rows**

---

## 12. Checklist for `sample_writer`

**One output. No divisions.** Every row is present in every run unless marked opt-in.

| # | Shape | Per platform | Always? |
|---|---|---|---|
| 1 | Owner-silent group | telegram, whatsapp, messenger | yes |
| 2 | Spam group (≥50% noise) | messenger | yes |
| 3 | Long email, no reply (11, 12) | email | yes |
| 3b | Boundary: 10 messages, no reply (**keep**) | email | yes |
| 3c | 12 messages, owner replied (**keep**) | email | yes |
| 4 | Filtered / message-request / e2ee threads | messenger | yes |
| 5 | Placeholder correspondents | messenger, linkedin, sms | yes |
| 6 | Zero-message thread | telegram, whatsapp | yes |
| 7 | Service rows inside a live thread | telegram, whatsapp | yes |
| 8 | 1:1 the Owner never replied to (**keep**) | all | yes |
| 9 | Large thread (200, 500) | messenger, telegram | yes |
| 9b | Huge thread (1,600) | messenger | **opt-in `--huge`** |
| 10 | Quiet thread (3+ years silent) | all | yes |
| 11 | WhatsApp native + HTML, same chat both ways | whatsapp | yes |

**Assertable, not prose.** Each row should be checkable by a test that reads the
generated file and counts, without parsing message bodies for meaning.

---

## 13. One output, not two — settled

The `fixtures` / `extremes` split is **gone**. It was a hedge against unrealistic data;
§12 is a better answer, because it names the shapes that matter instead of splitting the
world in two and hoping one half covers the edges.

**What replaces it:** one output, one seed, every §12 row present.

**Why this is safe:** the app's gates are what make an export realistic or not. A sample
containing an owner-silent group, a 50%-noise group, a 10-message silent email thread and
a 500-message thread is *more* realistic than two halves that each contain some of them,
because a real export contains all of them at once.

**What must still hold:**

1. **Determinism.** Same `--seed` → byte-identical output.
2. **Every §12 row present, and countable.**
3. **The world is shared.** One cast, one clock: the same person appears on more than one
   platform for 8–12% of the random cast, so cross-platform resolution has something to
   chew on later.
4. **Nothing above 600 messages in a thread** unless `--huge`.

**What to delete:** the `--division` flag, the second output tree, and
`_assert_division_marks`.

**Naming:** the other agent asked to rename `fixtures` → `format`. Agreed — but note
`tests/fixtures/` is a **different thing** (committed, scrubbed test inputs) and keeps
its name. Only the generator's internal division concept is being renamed away, and since
the division is being deleted, the rename is moot.

---

## 14. App gaps — status

§11 of the previous version (11.1–11.8) recorded app changes. All are closed or handled;
the log itself has been retired. **Status, for reference:**

| Item | Status |
|---|---|
| 11.1 WhatsApp group classification | **fixed** — membership system row is the signal |
| 11.2 `exclude_spam_groups` unreachable | **fixed** — own toggle in the modal |
| 11.3 `prune` unreachable | **fixed** — `Off / All / Keep last / Keep last 2` |
| 11.4 10-message boundary untested | **fixed** — 11 added to the test |
| 11.5 `Facebook user` renders as a contact | **partly** — Viewer pill only, canvas not styled |
| 11.6 No way to see why a thread dropped | **closed** — not worth building |
| 11.7 Size warning has no visible threshold | **open** — cosmetic |
| 11.8 WhatsApp HTML | **built** — `adapters/whatsapp_html.py` |
