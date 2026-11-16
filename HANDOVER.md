# HANDOVER.md

Short and dated. **Newest entry at the bottom.** What is next, not what was built —
that lives in [`TECHREADME.md`](TECHREADME.md).

---

## 2026-11-16 — UI built, docs consolidated

**Where it stands.** The app runs end to end: `start.bat` → `http://127.0.0.1:8100`.
Store holds 12,499 messages / 955 threads / 591 correspondents across five platforms.
`pytest tests -q` → 137 passed, 2 skipped.

**Built this session:**

- Full React + esbuild UI in `app/ui/src/` — three columns, Cytoscape + fcose canvas,
  two-state Viewer, local Ollama chat, five modals.
- Six lettered sizes (A–F) computed per platform, platform colours, per-node shade jitter,
  optional platform icons (title-bar toggle), zoom-gated labels.
- Source filter (Utilities modal) wired through the tool layer, so graph, search bar and
  chat all agree.
- Viewer stack persisted to `localStorage`; character-budgeted message loads; Newer/Older
  paging; per-thread search.
- `start.bat` — one window, closing it stops the app.
- Docs consolidated: `README.md`, `TECHREADME.md`, `HANDOVER.md`. `buildNOTES.md` deleted;
  `buildUI.md` → `archive_docs/UI-Cytoscape.md`; Ollama and download guides archived.

**Next, in order:**

1. **Tweak the UI with the author.** This is the current work — styling and behaviour
   iteration, driven by looking at it. Everything tunable is in
   `app/ui/src/config/theme.js` and editable live from Graph Style.
2. **Cross-platform identity.** There is no cross-platform edge in the store, so the
   canvas cannot draw a connection between clusters — every platform is a set of
   disconnected components. `resolution.py` and `writer.write_people()` are unused
   scaffolding for this; neither is called from `ingest()`. Note `Person` is **not** the
   term for the result (see `TECHREADME.md` §0) — it names a future body-extraction type.
3. **Body-entity extraction** (`Person`, `Place`, `Organization`, `Product`). Blocked on a
   candidate generator. Do not start before the Viewer is settled, or there is no way to
   see whether it is right.
4. **SMS adapter.** Payload arrived — see the 2026-11-16 (evening) entry below.

**Open decisions:**

- The platform filter narrows the AI chat as well as the search bar. The author chose this
  deliberately, overriding the earlier "UI state never narrows an agent's query" rule. The
  alternative is a per-call `platforms` argument instead of module state in `tools.py`.
- Per-node gravity is not a fcose feature. Big threads can only be approximated as anchors
  via lower `nodeRepulsion`.

**Known cosmetic issues in the real store:**

- `Facebook user` spans 31 Facebook Messenger threads — a placeholder Correspondent by
  design, but a viewer should render it as a spam account, not a contact.
- One thread holds 707 messages. The Viewer pages, so this is fine, but it is the test case.
- Hostinger sent mail has no `Message-ID` (133 of 221) — keyed by `uid:<UIDVALIDITY>:<UID>`.

---

## 2026-11-16 (evening) — terms settled, SMS + Outlook legs specced

**Where it stands.** Same store, but the vocabulary is now fixed and enforced. `pytest` →
137 passed, 2 skipped. UI built.

**Done this session:**

- **Terms locked** (`TECHREADME.md` §0, `README.md` "Terms — the short key"): Owner,
  Correspondent, Platform, Thread, Message. Plus Download / Export / Root for the ingest
  path. `Person`/`Place`/`Organization`/`Product` are explicitly *not* terms — they name a
  future body-extraction step.
- **`source` eliminated from code and docs.** Three senses split apart:
  `IngestResult.export_path` (the file), `ingest(which=…)` (the spool queue),
  `configure_platforms()` (the filter). `/api/sources` → `/api/platforms`.
- **`PLATFORM_LABELS`** in `nodeTypes.js` — the one place `messenger` and `Fcbk Mssgr`
  meet. Canvas legend now derives from config instead of hardcoded hex.
- **Sizes A–F computed per platform**, tie-aware, so Telegram's 486 one-message threads no
  longer fake a "big" band. Threads use A/C/E, correspondents B/D/F.
- **Telegram service-only chats no longer create Threads** — 335 deleted from the store.
- **Messenger spam-group gate** (`exclude_spam_groups`, off by default). 67 of 70 group
  threads are ≥50% housekeeping; the six largest are 96–100%.
- **Edge rendering fixed twice over**: `hideEdgesOnViewport: false` (it was hiding every
  edge while panning) and `THEME_VERSION` (a stale `localStorage` theme was shadowing every
  default change).

**Next, in order:**

1. **Outlook leg** — a separate platform, complete with UI points. The `.pst` adapter
   exists (`adapters/outlook_pst.py`, platform `outlook`) but has never been run against a
   real file. `C:/Users/q1fre/Downloads/Outlook.pst` is available. See the spec below.
2. **Email leg** — one platform, flexible across providers (Gmail, Hostinger, any IMAP),
   complete with UI points. See the spec below.
3. **SMS leg.** Payload in hand. See the spec below.
4. **AI chat + MCP server tests.** Not yet exercised end to end.
5. **Dummy-download scripts** for every platform, so the sample spool proves each leg.

---

### Spec — Outlook leg (a separate platform, not a variant of Email)

**Term: `Outlook`.** Platform key `outlook` (`outlook_pst.PLATFORM`). It is its own leg:
its own cluster, its own colour, its own legend row, its own filter checkbox. It is not
"Email 2" and not a mode of the Email leg.

**Current state.** `outlook_pst.py` is written and registered in `_PARSERS`, and
`detect_platform()` routes `.pst`/`.ost` to it. It has **never been executed against a real
file** — the tests do not cover it.

**What the real file contains** (`Outlook.pst`, 3.3 MB, opened with `pypff`):

```
root
  SPAM Search Folder 2
  Top of Personal Folders
    Deleted Items / Inbox (6) / SubInbox / Outbox / Sent Items (5)
    Calendar (1) / Contacts (1) / Journal / Notes
  Search Root / All Messages
  IPM_VIEWS / IPM_COMMON_VIEWS / Freebusy Data (1) / Reminders / To-Do Search
```

Only **11 messages** total, all from 2011, all `saqib.razzaq@xp.local` — it is an Aspose
sample file, not a real mailbox. Enough to prove the leg, not enough to prove scale.

**Traps found while inspecting it:**

- `pypff.file.open()` needs a **Windows path with backslashes**. A forward-slash path is
  prefixed with the CWD and fails with a confusing `\\?\C:\C:\Users\...` error.
- The API is `folder.number_of_sub_messages`, **not** `number_of_messages`.
- `message.plain_text_body` returns **bytes**, not `str`.
- `Sent Items` messages have `transport_headers = None`. Anything that parses headers must
  tolerate that — the sent side has no `From:`/`Message-ID:` block.
- `delivery_time` is a naive `datetime`; treat it as UTC and say so, or the timeline lies.

**Work:**

1. Run `python -m relate_comms ingest "C:/Users/q1fre/Downloads/Outlook.pst" --which real`
   and read the report. Fix whatever breaks.
2. Add `tests/test_outlook_ingest.py` — the sample file is small enough to commit as a
   fixture, or generate a synthetic one.
3. **Give Outlook its own identity in the UI.** Today `PLATFORM_LABELS` maps `outlook →
   "Email"` and `PLATFORM_COLORS` maps it to `#d9534f`, so a `.pst` cluster is visually
   identical to IMAP mail. That is a real bug. Needs:
   - `PLATFORM_LABELS.outlook = "Outlook"`
   - its own colour in `PLATFORM_COLORS` (distinct from Email's `#d9534f`)
   - its own icon file in `PLATFORM_ICONS` and `PERSON_ICONS`
   - a row in the canvas legend (`LEGEND_PLATFORMS` in `GraphCanvas.jsx`)
   - it already appears in `KNOWN_PLATFORMS`, so the Utilities filter picks it up
4. Decide the folder policy: `Inbox` + `Sent Items` only, or everything except
   `Deleted Items` / `Calendar` / `Contacts` / `Journal` / `Notes` / `Freebusy Data`.
   The adapter already has `include_skipped_folders`.

---

### Spec — Email leg (one platform, many providers)

**Term: `Email`.** Platform key `email`. **One mailbox at a time** — the app supports a
single Email leg, and that leg must be flexible about *which* mailbox it reads.

**Current state.** `email_imap.py` works and is verified live against Gmail and Hostinger.
`--email` is repeatable and `_fetch_mailboxes()` loops over the list, but every mailbox
lands as platform `email`, so two mailboxes merge into one cluster and
`Message.key` (`email:<chat_id>:<message_id>`) is not guaranteed unique across them.

**The flexibility requirement.** The provider is a *parameter*, not a platform. One
`email` platform, provider chosen at ingest time. **Nothing in the adapter may branch on
a provider name** — the extractor must work for any IMAP server.

`ENV_ACCOUNTS` in `email_imap.py` is now a convenience table of 11 providers, not a
whitelist:

| provider | host |
|---|---|
| `gmail` | `imap.gmail.com` |
| `outlook` | `outlook.office365.com` |
| `yahoo` | `imap.mail.yahoo.com` |
| `icloud` | `imap.mail.me.com` |
| `zoho` | `imap.zoho.com` |
| `fastmail` | `imap.fastmail.com` |
| `gmx` | `imap.gmx.com` |
| `yandex` | `imap.yandex.com` |
| `aol` | `imap.aol.com` |
| `hostinger` | `imap.hostinger.com` |
| `cpanel` | `mail.{domain}` — derived from the mailbox address |

Anything else goes through **`account_from_parts(host, user, password, port=993)`**, which
is the escape hatch: if a server speaks IMAP over TLS, those four values are all it takes.

**Folder detection is already provider-agnostic** and must stay that way. `choose_folders()`
works in two tiers:

1. **RFC 6154 special-use flags** (`\All`, `\Inbox`, `\Sent`) — locale-proof. This is why
   a Spanish Gmail account (`[Gmail]/Todos`) works without a hardcoded string.
2. **Name hints** on the last path segment, for servers that publish no flags (Yandex, GMX,
   cPanel): `sent`, `sent items`, `sent messages`, `sent mail`; `all mail`; and a skip list
   (`trash`, `junk`, `spam`, `drafts`, `bin`, `quarantine`, …).

The segment split handles both namespace styles — `[Gmail]/Sent Mail` and `INBOX.Sent` —
because it splits on `/` **and** `.`.

**Known provider quirks to keep in mind when testing:**

| provider | quirk |
|---|---|
| Gmail | `[Gmail]/All Mail` already contains Inbox and Sent — importing both double-counts. `choose_folders()` returns All Mail alone when it exists. |
| Outlook / Office 365 | Basic auth is dead; needs OAuth2 or an app password depending on tenant policy. Live IMAP may simply refuse. |
| Yahoo / AOL / iCloud | App passwords required; the displayed password contains spaces that are not part of it (`_SPACED_APP_PASSWORDS`). |
| cPanel / generic hosting | Host is `mail.<domain>`; folders are usually `INBOX` + `INBOX.Sent`. |
| Yandex / GMX | Often publish no special-use flags — tier 2 name hints carry it. |

**Work:**

1. **Ingest modal: an Email section with a provider selector.** The 11 known providers plus
   `custom`. For `custom`, four fields (host, port, user, password). For the named ones,
   show which `.env` keys are required and whether they are present.
2. **Credentials never persist server-side.** Two acceptable routes, pick one:
   - the modal takes them per request and sends them with the ingest call (never stored);
   - or the modal states plainly that `.env` is the route, and the user edits `.env` then
     presses Ingest. Do **not** write passwords to `localStorage`.
3. **One mailbox per run.** Enforce it: if two `--email` values are passed, refuse with a
   clear message rather than silently merging two mailboxes into one cluster. The
   platform is `email`; there is one of it.
4. **`Message.mailbox`** (`gmail` / `hostinger` / …) as a property, so the Viewer can say
   which mailbox a message came from without splitting the platform. Optional but cheap,
   and it removes the key-collision risk.
5. **`PLATFORM_LABELS.email = "Email"`** stays. Email keeps `#d9534f` and the envelope
   icon; Outlook gets its own.

---

### Spec — SMS leg

**Term: `SMS`.** Platform key `sms`. Colour: **dark gold**, `#b8912a` (already in
`PLATFORM_COLORS`). Icon: `app/static/icons/sms.svg` exists; a `person-sms.svg` exists too.

**Payload inspected:** `C:/Users/q1fre/Downloads/sms-20261116212209.xml`, 825 MB, exported
by **SMS Backup & Restore v10.21.001** (synctech.com.au) on Android.

**Shape:**

```xml
<smses count="11156" backup_set="…" backup_date="…" type="full">
  <sms protocol="0" address="+14720" date="1630048763654" type="1"
       subject="null" body="…" read="1" status="-1" locked="0"
       date_sent="1630048761000" sub_id="-1"
       readable_date="Aug 27, 2021 9:19:23 AM" contact_name="(Unknown)" />
  <mms date="1631679589000" msg_box="1" address="+27116977000" …>
    <parts>
      <part seq="0" ct="text/plain" name="text.000000.txt" text="…" />
      <part seq="1" ct="image/jpeg" name="image.000000.jpg" chset="…" />
    </parts>
    <addrs>
      <addr address="+27116977000" type="137" />
      <addr address="27840258710" type="151" />
    </addrs>
  </mms>
</smses>
```

**Measured on this file:**

| | |
|---|---|
| `<sms>` rows | 9,440 (5,538 inbound `type=1`, 3,902 outbound `type=2`) |
| `<mms>` rows | 1,716 (1,093 carry a `text/plain` part; 508 image, 58 video, 29 audio) |
| distinct addresses | 1,195 |
| date range | 2021-08-26 → 2026-11-16 |
| address forms | 7,203 `+E164`, 2,147 bare digits, 90 alphanumeric (`CellCApp`, `COVID19`) |
| `contact_name` | `(Unknown)` on 2,852, `Me` on 2,107 |

**Mapping to the canonical schema:**

| SMS field | becomes |
|---|---|
| `address` | the Correspondent. Normalise with `resolution.norm_phone` (digits only, ≥8). Alphanumeric senders (`CellCApp`) are **not** phones — keep them as a name-keyed Correspondent. |
| `contact_name` | `display_name` when it is not `(Unknown)` or `Me` |
| `date` | `ts_utc` — **milliseconds** since epoch, UTC. No offset needed; this is the one platform that states absolute time. |
| `type=1` / `type=2` | `is_self` (2 = sent). Do not rely on `contact_name == "Me"`. |
| `body` | `Message.body` |
| `mms` `text/plain` part | `Message.body` |
| `mms` other parts | `AttachmentRef` (path is a name inside the backup, not a real file — keep as a ref, never stat) |
| `msg_box` | `raw_kind` for MMS (`1` = inbox, `2` = sent) |

**Thread model.** SMS has no thread id. One Thread per address is the only honest
mapping — `chat_id = norm_phone(address)` or the alphanumeric sender. Group MMS exists but
is rare; if `addrs` holds more than two entries, key the thread on the sorted address set.

**Traps:**

- **825 MB.** Never `ET.parse()` the whole document. Use `iterparse` with
  `events=("end",)` and `elem.clear()` on each `sms`/`mms`, or the process dies.
- `subject="null"` and `address="null"` are the **string** `null`, not XML nulls.
- `date_sent` is sometimes seconds, not milliseconds (see the MMS rows above). Check
  magnitude before dividing.
- `contact_name` is `(Unknown)` far more often than it is useful — treat it as a hint, not
  a key.
- `readable_date` is redundant; ignore it and use `date`.

**Other formats to support or refuse explicitly:**

| Format | Where from | Handling |
|---|---|---|
| **SMS Backup & Restore XML** | Android, synctech | The format above. Primary target. |
| **SMS Backup+ XML** | Android, janpetrini | Same `<sms>`/`<mms>` shape, different attribute subset (`_id`, `thread_id`, `date_sent` in seconds). One parser, two dialects — detect by root element and attribute presence. |
| **`.csv` from SMS Backup & Restore** | Android | Same fields, flat. Cheap to add once XML works. |
| **iPhone / iMessage** | iOS | `chat.db` (SQLite). Out of scope — needs a Mac or a decrypted backup, and the schema is Apple-specific. Refuse with a clear message. |
| **Google Messages `.json`** | Android | Not a documented export. Refuse. |

**Work:**

1. `adapters/sms.py` — `PLATFORM = "sms"`, `parse(export_path, …)`, `detect(path)`.
   `detect` reads the first 4 KB and looks for `<smses` or `<sms ` plus a `backup_set`
   attribute. Never by filename.
2. `iterparse` streaming; count skipped rows by reason, never silently.
3. Register in `_PARSERS`; add `.xml` to `_CONSIDER_SUFFIXES` (it is not there today).
4. `PLANNED_PLATFORMS` in `tools.py` currently lists `sms` — remove it once the adapter
   lands, and the Utilities modal stops showing "not built yet".
5. Tests: a small synthetic fixture, plus the real file behind a skip-if-missing guard.

---

### Cleanup — LinkedIn "Sponsored" messages

**Symptom.** 74 messages across 73 LinkedIn threads contain raw HTML:

```
<p class="spinmail-quill-editor__spin-break">That's ok, %FIRSTNAME%, I respect your decision.</p>
```

**Cause.** LinkedIn's export ships the message body as HTML for sponsored/InMail
campaigns. The adapter stores it verbatim, so the graph shows markup and `%FIRSTNAME%`
placeholders. 32 of them sit in a single thread titled `Sponsored Conversation`.

**Fix, in order of preference:**

1. **Strip HTML in the LinkedIn adapter** — reuse the `_text()` helper pattern from
   `messenger.py` (tags out, `<br>`/`</p>` → newline, `html.unescape`). This is the root
   fix and helps every HTML-bodied row, not just sponsored ones.
2. **Detect and kind them** — `raw_kind = "sponsored"` when the body contains
   `spinmail-quill-editor` or the sender is `LinkedIn Member` / `LinkedIn Talent Solutions`.
   Lets the UI and the spam gate treat them as a class.
3. **Optionally drop them** behind a toggle, the same shape as `exclude_spam_groups`.

Do 1 and 2. Do 3 only if the author wants sponsored mail out of the graph entirely.

---

### Then — AI chat and MCP

Neither has been exercised end to end. The chat is wired (`routers/chat.py`, one tool
round, `think: false`) and the tool layer is the same functions MCP would bind, so the
work is verification, not construction:

1. Ask the chat a question that must hit two tools (e.g. "who did I talk to about n8n?").
   Confirm the tool trace shows both calls and the answer cites real rows.
2. Confirm `MAX_TOOL_CHARS` summarisation fires rather than silently truncating.
3. Confirm the platform filter narrows the chat's answers, not just the canvas.
4. MCP: expose the 10 tools and check each returns the same shape as the HTTP route.

---

### Then — dummy downloads for every platform

`relate_comms/sample_data/build.py` already generates Telegram, WhatsApp, Messenger and
LinkedIn fixtures. Extend it so `python -m relate_comms sample build` produces a
plausible export for **every** leg, including the new ones:

- `sms.py` — a small `<smses>` document with both `<sms>` and `<mms>`, an alphanumeric
  sender, and a bare-digit address.
- `outlook.py` — a `.pst` cannot be generated in pure Python; instead ship a tiny
  committed fixture and have the builder copy it.
- `email` — IMAP cannot be faked by a file. The builder should emit a `.eml`-shaped
  directory and the adapter should learn to read it, or the sample simply skips email and
  says so.

Each generated export must round-trip: `sample build` → `ingest --which sample` →
`verify_ingest` reports zero missing.
