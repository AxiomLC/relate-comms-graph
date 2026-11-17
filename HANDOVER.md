# HANDOVER.md

Short and dated. **Newest entry at the bottom.** What is next, not what was built —
that lives in [`TECHREADME.md`](TECHREADME.md). Fixed work gets one line and a pointer;
pending work keeps its detail.

---

## Where it stands

`pytest tests -q` → **164 passed, 2 skipped**. App runs: `start.bat` → `127.0.0.1:8100`.
Store: 12,499 messages / 955 threads / 591 correspondents across five platforms.

**Legs built:** Telegram, WhatsApp, Messenger, LinkedIn, Email (IMAP), Outlook (`.pst`),
SMS (adapter written, run against the real 825 MB file, **not yet in the store**).

---

## Next, in order

1. **SMS leg — finish it.** Adapter exists (`adapters/sms.py`), runs in 7 s on the real
   file, row count reconciles exactly (11,038 stored + 118 skipped = 11,156). Outstanding:
   - **31 rows skipped as "duplicate within run"** — unresolved. Either the file holds
     genuine duplicate rows or the ordinal is not applied on one path. Needs one targeted
     diagnostic, not another re-run.
   - **Group thread keys include the owner**, so the same group gets two thread ids
     depending on who sent. Must exclude the owner from the sorted participant set.
   - **No tests yet.** Needs a synthetic fixture plus the real file behind a skip-if-missing
     guard.
   - Delete `"sms"` from `PLANNED_PLATFORMS` in `tools.py` **and** the mirrored set in
     `GraphCanvas.jsx` — the legend placeholder then fills in.
   - Spec below (§SMS) is still the reference; SyncTech's own field list is authoritative.
2. **Ingest UI — the half-wired gap.** See [`buildINGESTUI.md`](buildINGESTUI.md). Summary:
   pre-inspection (`api.inspect`) does not exist; the silent-groups toggle is Messenger-only
   and must cover Telegram + WhatsApp; the email/Outlook long-silent-thread rule is noted
   but unbuilt.
3. **Email leg** — provider selector, one-mailbox-per-run enforcement, `Message.mailbox`.
   Spec below (§Email).
4. **AI chat + MCP server tests.** Wired, never exercised end to end.
5. **Dummy downloads for every platform.** Outlook is trivial now — copy the committed
   fixture. SMS needs a small `<smses>` generator.
6. **Cross-platform identity.** No cross-platform edge exists, so every platform is a set
   of disconnected components. `resolution.py` and `writer.write_people()` are unused
   scaffolding. Note `Person` is **not** the term for the result (`TECHREADME.md` §0).
7. **Body-entity extraction** (`Person`, `Place`, `Organization`, `Product`). Blocked on a
   candidate generator. Do not start before the Viewer is settled.

---

## Open decisions

- **The platform filter narrows the AI chat as well as the search bar.** Deliberate,
  overriding the earlier "UI state never narrows an agent's query" rule. The alternative is
  a per-call `platforms` argument instead of module state in `tools.py`.
- **Per-node gravity is not a fcose feature.** Big threads can only be approximated as
  anchors via lower `nodeRepulsion`.
- **The Outlook fingerprint can merge two genuinely distinct messages** — same thread, same
  second, byte-identical body, different senders. Accepted: the alternative is every sent
  message appearing twice, which the real file actually exhibits.
- **Email/Outlook spam rule: default on or off is undecided.** Same family of decision as
  the silent-groups toggle, which is default-on.

---

## Known issues in the real store

- `Facebook user` spans 31 Messenger threads — a placeholder Correspondent by design, but
  a viewer should render it as a spam account, not a contact.
- One thread holds 707 messages. The Viewer pages, so this is fine, but it is the test case.
- Hostinger sent mail has no `Message-ID` (133 of 221) — keyed by `uid:<UIDVALIDITY>:<UID>`.
- **147 threads have no Correspondent edge.** 135 are Telegram strangers with a `sender_id`
  and no name — fixed at the source (the id is now the name), so a re-ingest clears them.
  12 are Messenger threads titled `Facebook user`.

---

## 2026-11-16 — UI built, docs consolidated

React + esbuild UI, Cytoscape + fcose canvas, two-state Viewer, local Ollama chat, five
modals. Sizes A–F computed per platform. Viewer stack persisted. `start.bat`. Docs
consolidated into `README` / `TECHREADME` / `HANDOVER`.

## 2026-11-16 (evening) — terms settled

Terms locked (Owner, Correspondent, Platform, Thread, Message). `source` eliminated from
code and docs. `PLATFORM_LABELS` became the one place `messenger` and `Fcbk Mssgr` meet.
Telegram service-only chats stopped creating Threads (335 deleted). Messenger spam-group
gate added. Edge rendering fixed twice (`hideEdgesOnViewport`, `THEME_VERSION`).

## 2026-11-17 — Outlook leg, SMS adapter, Canvas modal

**Outlook — done.** `adapters/outlook_pst.py`, 19 tests, run against a real `.pst`.
Seven bugs found by running it; all recorded in the adapter docstring. The two that
mattered: Inbox and Sent Items hold the same mail (content fingerprint collapses them), and
the owner is stated in MAPI properties (`PR_RECEIVED_BY_EMAIL_ADDRESS` 0x0076 /
`PR_SENT_REPRESENTING_EMAIL_ADDRESS` 0x0065) — not in transport headers, which the Sent
copies lack. Fixture committed at `tests/fixtures/outlook/Outlook.pst`.

**SMS — adapter written, not finished.** See Next #1.

**Canvas modal replaced Graph Style.** Sort (messages / recent / quiet), node count, node
types, viewable platforms (all on by default), hide-silent. Styling is a sub-modal with
force + label zoom only. Icons, colours, edge widths and node sizes are dev knobs in
`config/theme.js`, not UI.

**`graph_slice` now returns `total`** and takes `sort`, so the canvas can say
"2,000 of 12,499" instead of implying it is everything. `sort` is not cosmetic — the limit
truncates, so the ordering decides which nodes are unreachable.

**Icons are the only node look.** The Circles/Icons toggle is gone. The icon styling is an
**override** on the base circle, never a replacement — that layering is what keeps a
platform with no icon file visible.

**Two bugs fixed that were silently wrong:**
- Telegram senders with an id and no name were left blank, so 135 threads had no
  Correspondent and became orphan nodes. The id is now the name.
- The Canvas hide-silent toggle read `hideSilent` inside a `useMemo` without listing it as
  a dependency, so ticking it changed nothing on screen.

---

## Spec — SMS leg

**Term: `SMS`.** Platform key `sms`. Colour dark gold `#b8912a`. Icon
`app/static/icons/sms.svg` (the `phone-svgrepo-com.svg` path, recoloured).

**Payload:** `C:/Users/q1fre/Downloads/sms-20261116212209.xml`, 825 MB, from **SMS Backup
& Restore v10.21.001** (synctech.com.au) on Android.

> **This is one app's format, not "the" SMS format.** It is the most common Android route
> because it needs no root and no PC, but it is third-party. Do not assume a `.xml` is this
> shape — detect by root element and attributes.

**Authoritative spec:** <https://www.synctech.com.au/sms-backup-restore/fields-in-xml-backup-files/>.
New attributes are always optional and existing ones are never renamed, so an unknown
attribute is safe to ignore and a missing one is safe to default.

**Measured on this file:**

| | |
|---|---|
| `<sms>` | 9,440 (5,538 received, 3,902 sent) |
| `<mms>` | 1,716 (1,085 inbox, 631 sent) |
| distinct addresses | 1,195 |
| date range | 2021-08-26 → 2026-11-16 |
| address forms | 7,203 `+E164`, 2,059 bare digits, 178 alphanumeric |
| MMS parts | 1,095 `text/plain`, 575 jpeg, 47 3gpp video, 773 smil |

**Mapping:** `address` → Correspondent via `resolution.norm_phone` (alphanumeric senders
and the 6 email addresses are name-keyed). `date` → `ts_utc` (absolute, no offset needed).
`type=2` / `msg_box=2` → `is_self`. `body` → `Message.body`. MMS `text/plain` part → body;
other parts → `AttachmentRef` (a name inside the backup, never stat'd).

**Thread model.** No thread id exists. One Thread per address; when `<addrs>` holds more
than two entries, key on the sorted address set **minus the owner** — group MMS is not rare
here (112 rows with 17 participants, 3 with 21).

**Traps — all confirmed against the real file:**

- **825 MB.** `iterparse(events=("end",))` with `elem.clear()` on `sms`/`mms` only. Never
  clear `part`/`addr` — the parent still needs them.
- **`date_sent` is mixed units inside one file** — 4,272 rows in seconds, 5,168 in
  milliseconds. Check magnitude per row.
- **`"null"` is a string.** `subject`, `toa`, `sc_toa` on every row; `service_center` on
  5,184; `address="null"` on 37 `<addr>` elements (a missing sender, not a participant).
- **MMS `address` is not the participant list.** For a group it is `~`-joined but **omits
  the owner**. `<addr>` is the authority — SyncTech says so, and all 198 group MMS prove it.
- **`msg_box` ≠ `m_type`.** `msg_box` 1=received / 2=sent; `m_type` 128/132/134, and 134 is
  a delivery receipt (87 here) — not a message.
- **`m_id` is not unique.** 84 repeat across genuinely different messages. Key on a content
  fingerprint with an ordinal, never on `m_id`.
- **`insert-address-token`** is the documented owner placeholder. Zero here; a newer phone
  will produce it.
- **RCS addresses** (`@rcs.google.com`, `@bot.rcs.google.com`) are valid participants. Zero
  here.
- **`<part data>`** is base64 media (739 parts) — never decode it. **`<part cl>`** is the
  filename; `name` is a different attribute.
- **`contact_name`** is `(Unknown)` on 2,674 rows and `Me` on 2,107 — a hint, never a key.

**Other formats:**

| Format | Handling |
|---|---|
| `.xml.zip` | XML is the first entry; may be AES-256 — refuse clearly |
| SMS Backup+ (jberkel) | Same tags, different attribute subset; one parser, two dialects |
| `.csv` | **Not a native export** — third-party converters only |
| iPhone `chat.db` | Out of scope; refuse with a clear message |
| Google Messages `.json` | Not a documented export; refuse |

---

## Spec — Email leg (one platform, many providers)

**Term: `Email`.** Platform key `email`. **One mailbox at a time.**

**Current state.** `email_imap.py` works and is verified live against Gmail and Hostinger.
`--email` is repeatable and `_fetch_mailboxes()` loops, but every mailbox lands as platform
`email`, so two mailboxes merge into one cluster and `Message.key` is not guaranteed unique
across them.

**The flexibility requirement.** The provider is a *parameter*, not a platform. **Nothing in
the adapter may branch on a provider name.**

`ENV_ACCOUNTS` is a convenience table of 11 providers, not a whitelist: `gmail`, `outlook`,
`yahoo`, `icloud`, `zoho`, `fastmail`, `gmx`, `yandex`, `aol`, `hostinger`, `cpanel`
(`mail.{domain}`). Anything else goes through `account_from_parts(host, user, password,
port=993)`.

**Folder detection is provider-agnostic and must stay that way.** Tier 1: RFC 6154
special-use flags (`\All`, `\Inbox`, `\Sent`) — locale-proof, which is why a Spanish Gmail
(`[Gmail]/Todos`) works. Tier 2: name hints on the last path segment, for servers that
publish no flags. The split handles both `[Gmail]/Sent Mail` and `INBOX.Sent`.

**Provider quirks:**

| provider | quirk |
|---|---|
| Gmail | `[Gmail]/All Mail` already holds Inbox + Sent — importing both double-counts |
| Outlook / O365 | Basic auth is dead; needs OAuth2 or an app password |
| Yahoo / AOL / iCloud | App passwords; the displayed password has spaces that are not part of it |
| cPanel / generic | Host is `mail.<domain>`; folders are `INBOX` + `INBOX.Sent` |
| Yandex / GMX | Often publish no special-use flags — tier 2 carries it |

**Work:**

1. Ingest modal: an Email section with a provider selector — the 11 known plus `custom`
   (host, port, user, password). Show which `.env` keys are required and whether present.
2. **Credentials never persist server-side.** Either send them per request, or state plainly
   that `.env` is the route. Never write passwords to `localStorage`.
3. **One mailbox per run.** Refuse two `--email` values with a clear message rather than
   silently merging two mailboxes into one cluster.
4. **`Message.mailbox`** (`gmail` / `hostinger` / …) as a property, so the Viewer can say
   which mailbox a message came from without splitting the platform.
5. `PLATFORM_LABELS.email = "Email"` stays; Email keeps `#d9534f` and the envelope icon.

---

## Cleanup — LinkedIn "Sponsored" messages

74 messages across 73 threads contain raw HTML
(`<p class="spinmail-quill-editor__spin-break">…`), including `%FIRSTNAME%` placeholders.
32 sit in one thread titled `Sponsored Conversation`.

**Fix, in order:** (1) strip HTML in the LinkedIn adapter — reuse the `_text()` pattern from
`messenger.py`; (2) set `raw_kind = "sponsored"` when the body contains
`spinmail-quill-editor` or the sender is `LinkedIn Member` / `LinkedIn Talent Solutions`;
(3) optionally drop them behind a toggle, same shape as `exclude_spam_groups`.

Do 1 and 2. Do 3 only if the author wants sponsored mail out of the graph entirely.
