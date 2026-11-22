# sample_writer

A standalone generator for **the relate‑comms‑graph** app. It writes a batch of **fake**
platform downloads that are structurally identical to real ones — so the whole app can be
exercised end to end without anyone's real message history.

**The build is fully self-contained.** Every run synthesises the downloads from scratch
(`world.py` picks the cast, `plan.py` lays out the threads, each writer renders them). It
needs no real data, no network, and no input to get going:

```
sample_writer/
    out/     <- FAKE downloads appear here; drag these into the app's Ingest modal
    in/      <- OPTIONAL: real downloads, only used by `capture` to record shape refs
    schemas/ <- written by `capture` only; local scratch, gitignored
```

`in/` is **not** a required input. The writers imitate the shapes they are coded against;
`capture` is a separate, optional command that reads a real download in `in/` and records
exactly what the app's adapters report — key sets, value types, counts, warnings — into
`schemas/<name>.json` as the reference a writer reproduces. You can run, tweak, and re-run
the build forever without ever touching `in/`.

---

## Why it exists

`relate‑comms‑graph` turns a person's messaging history into a searchable relationship
graph. To build and test that you need the awkward corners an export really contains —
threads the owner never spoke in, spam groups, placeholder senders, off‑by‑one boundary
cases — not a tidy fixture. `sample_writer` manufactures a whole believable export batch
on demand, so the app is always one run away from a realistic demo instead of waiting on a
real archive.

Nothing about the app needs to change to accept the generated files: to the Ingest modal
they are indistinguishable from the real thing.

---

## The point: it is meant to be tweaked

This is not a fixed fixture generator. Every number that shapes the output lives in
[`config.py`](config.py), and changing one line changes the data:

- want 40 threads per platform instead of 20? `THREADS_PER_PLATFORM`.
- want no spam groups? `SPAM_GROUPS = 0` — the build then reports that shape is
  unexercised rather than silently dropping it.
- want different names, topics, or a different owner? `world.py`'s cast and `dialogue.py`'s
  topic pools.
- a platform's shape slightly off? Edit that platform's writer and re-run. Nothing else in
  the app needs to know.

Then truncate the store and re‑ingest. The whole loop is seconds.

**Ask an AI to change any of this** — the knobs are plain module constants with comments,
and each writer is one file. That is deliberately the cheapest thing to modify in the repo.

See every knob and its current value:

```
python -m sample_writer knobs
```

---

## Platforms and current output formats

Every run writes to `out/<platform>/<artifact>/`. The table below is the current surface
and is **not exhaustive by design**:

- Third‑party apps and exporters allow custom bulk downloads of many messaging platforms
  and socials, and their shapes change; and
- a platform's own export gains new file types and additional zips over time.

So expect new platforms and new per‑platform variants to be added — the list is a snapshot,
not a ceiling.

| Platform | Artifacts today | What the app sees |
|---|---|---|
| **Facebook Messenger** | `messenger_zip/`, `messenger_dir/` | `your_facebook_activity/messages/{inbox,filtered_threads,message_requests,e2ee_cutover}/…` (zip and the same tree unzipped) |
| **Telegram** | `Telegram Desktop/DataExport_<date>/`, `Telegram Desktop/ChatExport_<date>/` | bulk DataExport and single‑chat ChatExport, in the real `Telegram Desktop` folder so it drops into Ingest as‑is |
| **WhatsApp** | `whatsapp-chats-<date>.zip` + `whatsapp_web/` | the browser‑extension bulk zip (many chats, `chats/*.html` + `index.html`) at top level, plus `whatsapp_web/` of WhatsApp‑Web single‑chat zips |
| **LinkedIn** | `linkedin_zip/`, `linkedin_dir/` | `messages.csv` + `Connections.csv` |
| **SMS** | `sms_xml/`, `sms_xml_zip/`, `sms_json_app/` | SyncTech `<smses>`, the compressed form, and a deliberate negative case |
| **Email** | `email_eml/<thread>/*.eml` | one RFC 5322 message per file (email is never a discoverable file) |
| **Outlook** | `outlook_copy/Outlook.pst` | copy of the committed fixture; a `.pst` cannot be synthesized |

A couple of deliberate quirks worth knowing:

- **Dated filenames are dynamic, from the world's clock** (`world.end`), not hardcoded.
  `Telegram Desktop/DataExport_<date>/`, `facebook-sampleuser-<date>-1G300tUX.zip`,
  `Basic_LinkedInDataExport_<date>.zip.zip`, `sms-<timestamp>.xml`, and
  `whatsapp-chats-<date>.zip` all carry the export date, so a different seed produces
  differently-named files — exactly like real downloads.
- `messenger_dir` and `linkedin_dir` exist because the adapters branch on `is_dir()` —
  two code paths, both worth generating.
- `sms_json_app` is a different Android app's shape and **should** be reported
  unrecognised: it proves the app does not guess.
- **WhatsApp Web names single-chat zips by phone number, not contact name.**
  `whatsapp_web/<number>.zip` holds a flat `chat.txt` + `chat.md`, and the contact name
  lives only in the `chat.txt` sender lines. Note the **Android** single-chat export is
  different: it names the zip `WhatsApp Chat with <contact>.zip`, puts the text file at
  the archive root as `WhatsApp Chat with <contact>.txt` (not `chat.txt`), bundles
  `.vcf` contact cards, and writes dates as `22/06/23, 6:55 pm` (day-first, 2-digit
  year, no seconds) — unlike Web's `[10/9/26, 10:23:45 AM]`. The app reads both; the
  writer emits the Web shape, which is what a dev on WhatsApp Web actually gets.
- **`outlook_copy/Outlook.pst` is a byte-for-byte copy of
  `tests/fixtures/outlook/Outlook.pst`** (same SHA-256). A dummy writer **cannot**
  synthesise a `.pst`: the format is a paged `MS-PST` database with an on-disk B-tree
  of nodes and blocks, and no maintained pure-Python writer exists — every reader
  (`libratom`, `libpff`) is read-only. So Outlook is the one platform whose fuzzed
  shapes are **not** generated, and the build log says so. If you need new Outlook
  mail, replace the fixture; do not expect this writer to invent it.

> **Naming note.** The store key and the artifact folders keep the code name `messenger`
> (it is part of every `Message.key` and must not change). The UI and this page call the
> platform **Facebook Messenger** — never bare "Messenger", which reads as "a message".

---

## Use

Run from the **repo root** (not from inside `sample_writer/`). Two commands: `build`
**wipes then writes** a set; `add` **writes alongside** what is already in `out/`.

| Command | Wipe | Write |
|---|---|---|
| `python -m sample_writer` | all platforms | all platforms, default seed |
| `python -m sample_writer --seed 7` | all platforms | all platforms, seed 7 |
| `python -m sample_writer --platform sms` | that platform | that platform |
| `python -m sample_writer --platform whatsapp telegram sms outlook` | those | those |
| `python -m sample_writer --huge` | all platforms | all + the 1,600-message thread |
| `python -m sample_writer add --seed 5` | **none** | all platforms, no clobber |
| `python -m sample_writer add --platform sms --seed 2` | none | just SMS, no clobber |
| `python -m sample_writer clean` | all platforms | nothing — just wipe |

`--platform` takes space-separated names (e.g. `--platform sms telegram outlook`). `--seed`
falls back to the default (`config.SEED`); `--huge` applies to whichever platforms you ask for.

`add` never wipes and never overwrites: a name already on disk becomes `name (1)`, then
`name (2)`, … — Windows-style — dropped into the same folder. So you can run `add` twice
at the same seed and get two identical sets side by side (harmless: ingest dedupes on
content), or run the Wipe command first to start a fresh `out/`. You are the source of
truth for which files to drag into the app's **Ingest** modal; delete any at any time.

There is also `capture` (see below).

Output is a running log: the world summary, then one platform summary line, the artifacts
each platform wrote (aggregated per variant — a dialect that writes one file per chat shows
one line with a count, not all 20+), and every required shape it satisfied:

```
world      seed=20261114 people=64 cross-platform=12%
email       22 threads    117 messages
           -> email\email_eml\  (139 files)
telegram    27 threads    826 messages
           -> telegram\telegram_bulk\result.json
           - telegram: owner-silent group (7 msgs)
           - telegram: zero-message thread
           - telegram: big thread 500
...
done       84 files, 2259 messages, 0.40s -> ...\sample_writer\out
```

A missing required shape fails the build with a readable list, not a traceback.

## Second-guessing the output

`tests/test_sample_writer.py` drives the app's **real** adapters against a fresh generation
and asserts every mandated shape behaves. It builds into `config.OUT_DIR` directly, and the
module fixture now runs a `clean=True` build first, so running `pytest` wipes and
rebuilds `out/` at the default seed — expect that. Build a seed to eyeball, then `pytest`
replaces it with the default.

---

## The world

One seed, one cast, one clock. `Mary Olver` is the same person on WhatsApp and in email;
`ABC Corp` is a colleague's employer *and* an email domain. Same `--seed` → byte‑identical
output.

Fixed cast, always present: `Mark Jones` (Owner, on every platform), `Mary Jones`,
`Mary Olver`, `Brandon Steinhart`, `ABC Corp`. The rest are generated names, and only
**8–12%** of them appear on more than one platform — deliberately sparse, so the graph
stays honestly disconnected until cross-platform resolution is wired.

Bodies are templated, not LLM-written: `dialogue.py` holds topic pools (dog, baseball,
Coca-Cola, Mary Jones, the ABC Corp contract, invoices) plus a Subject→Predicate→Result
sentence builder and a sign-off pool. Offline, deterministic, milliseconds.

---

## Fuzz — the same thing spelled differently

Real downloads disagree with each other about how a name is spelled, and a flatten pass
that has never seen a disagreement cannot be trusted. The build therefore manufactures
them, under knobs in `config.py`:

| Knob | What it produces |
|---|---|
| `FUZZ_SENDERS_CROSS` | one person, two platform spellings — `Chris Fowley` on WhatsApp, `Christopher Fowley` on Telegram |
| `FUZZ_SENDERS_INTRA` | two spellings of one person inside a single export |
| `FUZZ_BODIES_CROSS` | an entity spelled differently on two platforms — `North Dakota` / `N Dakota` |
| `FUZZ_BODIES_INTRA` | several spellings inside one export — `Celestica` / `celestica` / `Celstica` |
| `FUZZ_BODY_KINDS` | which kinds may vary: `org`, `place`, `person` (never `thing`) |

**The Owner is never fuzzed.** `Mark Jones` is emitted byte-identically by every writer;
a fuzzed owner would break the one invariant the app's ingestion depends on.

How it is produced matters: almost none of it is a list of variants. `fuzz.py` derives
each spelling from the string plus a seeded index — case, possessive, a dropped letter,
a transposition, an abbreviation (`North Dakota` → `N Dakota`). The one genuine table is
`NICKNAMES` (`Chris`↔`Christopher`, `Bob`↔`Robert`), because a nickname is a fact about
English rather than a transformation of the letters. `abbrev` is places-only.

The result is reported every run, so a knob that produces nothing is visible rather than
silent:

```
fuzz: senders cross=2/2 intra=4/4 on whatsapp, telegram
fuzz: bodies org=13 place=2 person=8 (kinds=org,place,person)
fuzz: outlook is a copied .pst, so its bodies cannot be fuzzed
```

Outlook is the one platform outside the fuzz: a `.pst` cannot be synthesised (see above).

---

## `capture` — optional, the reference the writers are coded against

```
python -m sample_writer capture
```

`capture` is the **only** command that reads `in/`. It's purely a bookkeeping aid: put a
real download in `in/`, run this, and it records exactly what the app's adapters report for
that file — key sets, value types, counts, `unknown_kinds`, `skipped` reasons, warnings —
into `schemas/<name>.json`. That snapshot is the honest definition of "same schema":
whatever the adapter reports is what the corresponding writer must reproduce.

It calls the adapters directly — never `ingest.ingest` — so the app's graph store is
untouched, and it never writes to `in/`. The build itself does not need `capture` to have
run: the writers carry their shapes independently.