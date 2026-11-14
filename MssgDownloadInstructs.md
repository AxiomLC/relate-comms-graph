# How to get your messages

Every platform hands you data in a different box. This page says **what to click**,
**what you get**, and **what it should look like** before you hand it to the app.

Two rules that apply everywhere:

1. **Media off.** Text is what the graph is for. Media makes the file 100× larger and
   the app never reads the pixels.
2. **You keep the original.** The app copies what it ingests into its own spool and
   only deletes that copy — after checking every message actually landed. Your
   download is never moved or deleted.

Put the file somewhere obvious (your Downloads folder is fine). The app's **Ingest**
button opens a drop zone: drag the file onto it.

---

## Telegram — one download, every chat

**Where:** Telegram Desktop → Settings → Advanced → **Export Telegram data**.

Pick **JSON**, turn media **off**, and choose "all chats". You do not need to export
each chat separately.

**You get:** a folder named like `DataExport_2026-11-14/` containing `result.json`.

| What it looks like inside |
|---|
| `{"about": ..., "chats": {"list": [ ... ]}, "left_chats": {...}}` |
| each chat has `name`, `type`, `id`, `messages[]` |
| a single-chat export is the same file but with `messages` at the top level |

Smaller details worth knowing: a message's `text` is sometimes a plain string and
sometimes a list of pieces (bold, links). Dates appear as `date_unixtime` in the bulk
export but only as local `date` in a single-chat export.

> **Caution:** the export is **plain text on disk**. It contains every message you
> have. Delete it when you are done if that matters to you.

---

## WhatsApp — one chat at a time

**Where:** open the chat → ⋮ → **More** → **Export chat** → **Without media**.

Repeat per chat. There is no official "all chats" export; a third-party tool exists
but is not required and is not supported by this app.

**You get:** a `.zip` (or a `.txt`) named after the contact, e.g.
`+1 (917) 400-4025.zip`, containing `chat.txt` and a twin `chat.md`.

| What it looks like inside |
|---|
| `[5/22/26, 8:45:50 AM] +1 (917) 400-4025: Hi` |
| a message can continue over several lines |
| system notices start with `- ` instead of a name |
| media appears as `<image omitted>`, `<document omitted> name.docx`, `<album message>` |
| your own messages are attributed to **`You`** |

The text export has **no message ids**, so the app fingerprints each message from its
timestamp, sender and text. Two identical messages in the same second (a photo album)
are kept as separate rows.

**Time zone:** these exports write local time with no offset. If the app's ingest is
told your UTC offset, the stored times are exact; otherwise times are read as UTC and
flagged.

---

## Messenger (Facebook) — a big archive, but messages are small

**Where:** <https://accountscenter.facebook.com/info_and_permissions/dyi> →
**Messages** → format **HTML** → deselect everything else → *Request download*.

Meta's link expires after about **4 days**. Start this one first; it is the slowest.

**You get:** a `.zip` named like `facebook-<username>-<date>-<code>.zip`.

| What it looks like inside |
|---|
| `your_facebook_activity/messages/inbox/<name>_<id>/message_1.html` |
| `.../filtered_threads/`, `.../message_requests/`, `.../e2ee_cutover/` |
| photos next to the thread folders |

Each message is an HTML block naming its sender — so the app knows who "you" are from
the file itself. Group threads also contain `Participants: ...` blocks; those are
not messages and are counted separately.

---

## LinkedIn — the *Basic* archive is enough

**Where:** <https://www.linkedin.com/mypreferences/d/download-my-data> →
**Basic** archive (the default) → include **Messages** → *Request archive*.

> The "Download larger data archive" option is **not needed**. The Basic export
> already contains `messages.csv` — verified 2026-11-14 on a real archive: 292
> messages across 205 conversations, 216 KB.

**You get:** `Basic_LinkedInDataExport_<date>.zip`.

| What it looks like inside |
|---|
| `messages.csv` at the top level |
| columns: `CONVERSATION ID, CONVERSATION TITLE, FROM, SENDER PROFILE URL, TO, RECIPIENT PROFILE URLS, DATE, SUBJECT, CONTENT, FOLDER, ATTACHMENTS` |
| `DATE` is already UTC: `2026-11-13 13:01:58 UTC` |
| `FOLDER` is `INBOX` or `ARCHIVE` — archived threads are included |

Two quirks: `CONVERSATION TITLE` is usually empty for 1-to-1 chats (the app falls back
to the other person's name), and a recipient name can contain commas — so it is a
person, not several.

---

## Email — Gmail, Outlook, and any other mailbox

Email is the one **live** source: nothing to download for Gmail or a normal IMAP mailbox.
The app reads it read-only. Outlook is the exception and has a download button.

### Gmail — needs an App Password

**Where:** <https://myaccount.google.com/apppasswords> → create one for "Mail".

A normal Google password **will not work**. App passwords only appear once 2-Step
Verification is on, and Google removed basic password auth for IMAP in March 2025.
Paste the 16 characters shown (Google displays them with spaces; the spaces are not
part of the password).

**What the app reads:** Gmail's `[Gmail]/All Mail` — the only folder that holds both
received and sent mail in one place. Your labels are **not** separate conversations;
reading them all would duplicate every message once per label.

> Gmail renames its folders in non-English accounts (`[Gmail]/Todos` in Spanish). The
> app asks the server which folder is "all mail" rather than looking for that exact
> name, so a translated account still imports.

### Outlook — use the export button

Microsoft disabled password login for Outlook IMAP (2024 for personal accounts), so
live reading needs a registered Azure app and a browser sign-in. **You do not need
that** — Outlook can export a file instead, and the app reads the file.

**Where:** Outlook on the web → Settings → General → **Privacy and data** →
**Export mailbox**. Or classic Outlook → File → Open & Export → Import/Export →
Export to a file → **Outlook Data File (.pst)**, and tick *Include subfolders*.

**You get:** a `.pst` file. Microsoft builds it server-side and emails you a link;
this can take hours for a large mailbox. Drop the `.pst` on the ingest button like any
other export.

### Any other mailbox (IMAP)

Yahoo, iCloud, Fastmail, Zoho, Proton and ordinary web hosts all speak IMAP. The app
already handles them — it asks the server for "sent", "all mail" and "junk" folders
using the standard mailbox flags (RFC 6154), and falls back to recognising common
names like `Sent`, `INBOX.Sent`, `Sent Items` and `Bulk Mail`.

| Provider | Server | Notes |
|---|---|---|
| Gmail / Workspace | `imap.gmail.com:993` | App Password; folder names are translated |
| Outlook / Hotmail / M365 | — | **Use the `.pst` export above**, not IMAP |
| Yahoo | `imap.mail.yahoo.com:993` | App password. Sent folder is `Sent`, junk is `Bulk Mail`, drafts is **`Draft`** (singular) |
| iCloud | `imap.mail.me.com:993` | **App-specific password required.** Sent is `Sent Messages` |
| Fastmail | `imap.fastmail.com:993` | App password only; basic plan has no IMAP at all |
| Zoho | `imap.zoho.com:993` | Enable IMAP in settings first; free plans may not include it |
| Proton | `127.0.0.1:1143` | Paid plans only, and **only through the Proton Mail Bridge desktop app** — start Bridge first |
| Ordinary web hosting (cPanel, Hostinger, etc.) | `imap.<yourdomain>:993` | Usual mailbox password. Sent is normally `INBOX.Sent` |

All of these sit on the same IMAP protocol; only the folder names and login rules
differ. Two of these are proven against live mailboxes on this machine: **Gmail**
(250 messages in a 30-day window) and **Hostinger** (221 messages, 68 conversations,
both inbox and sent).

---

## SMS — Android only *(not built yet)*

**Where:** **SMS Backup & Restore** app → *Back up* → **XML** → save to local storage.

**You get:** one large `.xml` file. There are no chat threads in it — the app groups
messages into conversations by phone number and date.

---

## Which file is which

The app does not trust filenames, because downloads get renamed. It opens the file and
asks what shape it is:

| Platform | File | How the app recognises it |
|---|---|---|
| Telegram | `result.json` | JSON object with `chats` or a bare chat with `messages` |
| WhatsApp | `*.zip` / `*.txt` | a `[date, time]` line at the start of the text |
| Messenger | `*.zip` | `facebook_activity` paths with `message_*.html` |
| LinkedIn | `*.zip` | a `messages.csv` with `CONVERSATION ID` and `CONTENT` columns |
| Outlook | `*.pst` / `*.ost` | the file's own binary signature, not the extension |

Anything it does not recognise is **reported and left alone** — never guessed at,
never deleted.

---

## After you press Ingest

You get a line per file:

```
  ok       whatsapp  Downloads/+1 (917) 400-4025.zip  160 msgs, 2 attach
  ok       linkedin  Downloads/Basic_LinkedInDataExport_11-14-2026.zip  292 msgs
  ok       messenger Downloads/facebook-davidsartori796-...zip  10,605 msgs, 14 attach
  ok       outlook   Downloads/outlook.pst  1,204 msgs, 18 attach
```

- **ok** — parsed, written, and every message confirmed present in the store.
- **UNVERIF** — some messages did not land. The file is kept so this can be investigated.
- **ERROR** — the file could not be read. Kept.
- **SKIPPED** — unrecognised shape. Kept.

Ingesting the same file twice is safe: it updates rather than duplicating. Nothing is
deleted until it has been verified and is more than three days old.

**Both sides of the conversation:** WhatsApp and LinkedIn exports contain only your own
view. Gmail and Hostinger do contain sent mail (Gmail via *All Mail*, Hostinger via
`INBOX.Sent`), so exchanges read naturally there.
