# sample_writer

Generates fake platform downloads that are **structurally identical** to real ones, so the
app can be exercised end to end without anyone's real history.

Dumb transform: **a folder in, a folder out.**

```
sample_writer/
    in/      <- put REAL downloads here (gitignored, read-only, never modified)
    out/     <- FAKE downloads appear here; drag these into the app's Ingest modal
```

---

## The point: it is meant to be tweaked

This is not a fixed fixture generator. Every number that shapes the output lives in
**[`config.py`](config.py)**, and changing one line changes the data:

- want 40 threads per platform instead of 20? `THREADS_PER_PLATFORM`.
- want no spam groups? `SPAM_GROUPS = 0` — the build then reports that §2 is unexercised
  rather than silently dropping it.
- want different names, topics, or a different owner? `world.py`'s cast and `dialogue.py`'s
  topic pools.
- sender names vs thread titles wrong, a platform shape slightly off? Edit the writer for
  that platform and re-run. Nothing else in the app needs to know.

Then truncate the store and re-ingest. The whole loop is seconds.

**Ask an AI to change any of this** — the knobs are plain module constants with comments,
and each writer is one file. That is deliberately the cheapest thing to modify in the repo.

See every knob and its current value:

```
python -m sample_writer knobs
```

---

## Use

Run from the **repo root** (not from inside `sample_writer/`).

```
python -m sample_writer                  # in/ -> out/, every platform
python -m sample_writer --platform sms    # one platform (repeatable)
python -m sample_writer --seed 7          # a different world
python -m sample_writer --huge            # also emit the 1,600-message thread
python -m sample_writer --keep            # do not wipe out/<platform>/ first
python -m sample_writer clean             # wipe out/
python -m sample_writer capture           # in/ -> schemas/ (shape references)
```

Output is a running log: the world summary, then one line per platform with thread and
message counts, each artifact written, and every required shape it satisfied:

```
world      seed=20261114 people=64 cross-platform=12%
telegram    27 threads    822 messages
           -> telegram\telegram_bulk\result.json
           - telegram: owner-silent group (10 msgs)
           - telegram: zero-message thread
           - telegram: big thread 500
...
done       84 files, 2314 messages, 0.61s -> ...\sample_writer\out
```

A missing required shape fails the build with a readable list, not a traceback.

---

## What it emits

```
out/<platform>/<artifact>/
```

| Platform | Artifacts | What the app sees |
|---|---|---|
| telegram | `telegram_bulk/`, `telegram_single/` | bulk DataExport and single-chat ChatExport |
| whatsapp | `whatsapp_chat_txt/`, `whatsapp_underscore/`, `whatsapp_bare/`, `whatsapp_html/` | one chat per zip (`chat.txt`), the `_chat.txt` packaging, loose `.txt`, and the HTML dialect |
| messenger | `messenger_zip/`, `messenger_dir/` | `your_facebook_activity/messages/{inbox,filtered_threads,message_requests,e2ee_cutover}/…` |
| linkedin | `linkedin_zip/`, `linkedin_dir/` | `messages.csv` + `Connections.csv` |
| sms | `sms_xml/`, `sms_xml_zip/`, `sms_json_app/` | SyncTech `<smses>`, the compressed form, and a deliberate negative case |
| email | `email_eml/<thread>/*.eml` | one RFC 5322 message per file (email is never a discoverable file) |
| outlook | `outlook_copy/Outlook.pst` | copy of the committed fixture; a `.pst` cannot be synthesized |

`messenger_dir` and `linkedin_dir` exist because the adapters branch on `is_dir()` — two
code paths, both worth generating. `sms_json_app` is a different Android app's shape and
**should** be reported unrecognised: it proves the app does not guess.

---

## One output, every required shape

There are no divisions or modes. Every run contains the shapes the app has switches
against — because that is what a real export looks like. Enforced in `plan.assert_contract()`:

| Requirement | Where it lands |
|---|---|
| Owner-silent group (§1) | telegram, whatsapp, messenger — `is_group` with **zero** owner rows |
| Spam group, ≥50% housekeeping noise (§2) | messenger, under `filtered_threads/` |
| Long silent email: 11 and 12 messages | must be dropped by the spam rule |
| Boundary email: 10 messages, no reply | must be **kept** (the off-by-one) |
| Replied long email: 12 messages | must be kept |
| All four Messenger folders (§4) | `inbox`, `filtered_threads`, `message_requests`, `e2ee_cutover` |
| Placeholder senders (§5) | `Facebook user`, `LinkedIn Member`, `(Unknown)` |
| Zero-message thread (§6) | telegram, whatsapp — absent from the parse, counted as skipped |
| Service rows inside a live thread (§7) | telegram, whatsapp |
| 1:1 the Owner never replied to (§8) | every platform; must survive `exclude_silent_groups` |
| Big threads (§9) | 200 and 500, telegram and messenger; 1,600 only with `--huge` |
| Quiet thread (§10) | 3+ years older than the newest message |
| Both WhatsApp dialects (§11) | native `chat.txt` and HTML |

Duplicate thread titles are rejected by the contract check: on WhatsApp the title is the
thread key, so two threads sharing a name silently overwrite a file.

---

## The world

One seed, one cast, one clock. `Mary Olver` is the same person on WhatsApp and in email;
`ABC Corp` is a colleague's employer *and* an email domain. Same `--seed` → byte-identical
output.

Fixed cast, always present: `Mark Jones` (Owner, on every platform), `Mary Jones`,
`Mary Olver`, `Brandon Steinhart`, `ABC Corp`. The rest are generated names, and only
**8–12%** of them appear on more than one platform — deliberately sparse, so the graph
stays honestly disconnected until cross-platform resolution is wired.

Bodies are templated, not LLM-written: `dialogue.py` holds topic pools (dog, baseball,
Coca-Cola, Mary Jones, the ABC Corp contract, invoices) and turn-taking where a question
draws an answer. Offline, deterministic, milliseconds.

---

## `capture` — where the formats come from

The writers imitate **captured** payloads, not remembered ones. Detection is
content-based, so a file that does not reproduce the exact fingerprint is worthless.

```
python -m sample_writer capture
```

Walks `in/`, runs each file through the app's own adapters, and writes
`schemas/<name>.json`: key sets, value types, counts, `unknown_kinds`, `skipped` reasons,
warnings. It calls the adapters directly — never `ingest.ingest` — so `store/graph.rl` is
untouched, and it never writes to `in/`.

---

## Known app gaps

**None open.** Both gaps this file used to record are fixed:

1. ~~A WhatsApp HTML zip is never routed to `adapters/whatsapp_html.py`.~~ Fixed —
   `ingest._parser_for()` picks the dialect per file, and the test asserts on it rather
   than on `detect_platform()` (both dialects share the platform key `whatsapp`).
2. ~~A loose Messenger HTML directory never detects.~~ Fixed — `messenger.detect()` reads
   a folder and a loose `message_N.html`, and `discover()` now emits a recognised
   directory as **one batch** instead of one per file. `messenger_dir/` ingests as 611
   messages in a single batch.
