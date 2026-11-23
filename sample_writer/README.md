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
`CORR_MULTI_PLATFORM` (**8%**) of them appear on more than one platform — deliberately
sparse, so the graph stays honestly disconnected until cross-platform resolution is
wired.

Bodies are templated, not LLM-written: `dialogue.py` holds topic pools (dog, baseball,
Coca-Cola, Mary Jones, the ABC Corp contract, invoices) plus a Subject→Predicate→Result
sentence builder and a sign-off pool. Offline, deterministic, milliseconds.

### Who a body may name

Four pools, in `world.py`, all large on purpose — a wide pool is what gives the app a
realistic `mention_count` distribution without an extra knob.

| Pool | Size | Named in a body by |
|---|---|---|
| `ORGS` | 232 | `ORG_LINES` |
| `PLACES` | 254 | `PLACE_LINES` |
| `PRODUCTS` | 100 | `PRODUCT_LINES` |
| `FIRST_NAME` / `LAST_NAME` | 151 / 133 | the Correspondent cast |

`PRODUCTS` exists so `Product` has generated data to be tested with; a body says
`we're still on {product}` or `the {product} renewal is due`, never a company.

---

## Fuzz — the same thing spelled differently

Real downloads disagree with each other about how a name is spelled, and a flatten pass
that has never seen a disagreement cannot be trusted. The build therefore manufactures
them.

### The model: three independent dice

Every item rolls three dice that **do not condition on each other**. The percentage
applies to the *whole population of that kind* — "fuzzy or otherwise", "multi-mention or
not" — so every combination below can occur.

```
axis A  SPELLING    normal | fuzzy (one variant, uniform)
axis B  PLATFORMS   1 | 2..len(PLATFORMS)
axis C  MENTIONS    1 | 2-4, on ONE platform only   [body kinds]
```

| Kind | Knob | Default | What one item does |
|---|---|---|---|
| Correspondent | `CORR_FUZZY` | 7% | spelled one alternate way, uniform over 6 variants |
| Correspondent | `CORR_MULTI_PLATFORM` | 8% | appears on 2+ platforms |
| Place / Org / Product | `BODY_FUZZY` | 15% | one alternate spelling, uniform over its 7 / 6 / 5 variants |
| Place / Org / Product | `BODY_MULTI_MENTION` | 8% | named 2-4x on **one** platform |
| Place / Org / Product | `BODY_MULTI_PLATFORM` | 4% | on 2+ platforms, whatever its mention count |

Independence means all four body combinations exist, roughly:

| Combination | Share |
|---|---|
| single mention, single platform | 84% |
| multi-mention only (one platform) | 7% |
| single mention, multi-platform | 4% |
| multi-mention and multi-platform | 0.3% |

**Multi-mention picks exactly one platform.** A second platform with mentions is what
*multi-platform* means, so letting each platform draw its own count would collapse the
two axes into one.

### Shares, not promises

A body names an entity in only about **1 in 12 messages** — roughly 202 slots in a
2,500-message world, against 586 items in the pools. An item that never lands in a body
writes nothing.

That is deliberate, and it is where the `mention_count: 1` tail comes from. It is also
why `BODY_FUZZY` is **15% and not 7%**: only about a third of the items a share flags
are ever written, so 15% yields roughly 30 fuzzy spellings actually reaching the corpus.
No allocation pass exists, and none is wanted — `entity_line()` samples freely, and an
accidental repeat mention merely adds to `mention_count`.

### Variants — uniform, no weight table

Each kind declares a list; the dice picks uniformly, so each variant is `1/len(list)`
and the row is 100% by construction. There is no weight dict that can fail to sum.

| Kind | Variants |
|---|---|
| `corr` | `lower`, `upper`, `drop_letter`, `swap`, `nickname`, `credentials` |
| `org` | `lower`, `upper`, `drop_letter`, `swap`, `legal_suffix`, `acronym` |
| `place` | `lower`, `upper`, `drop_letter`, `swap`, `abbrev`, `postal_code`, `region_tail` |
| `product` | `lower`, `upper`, `drop_letter`, `swap`, `hyphen` |

A variant that cannot apply does not consume the item's share: `fuzz.pick_variant()`
walks a shuffled copy and takes the first that changes something, reporting only if the
whole list fails.

**Two variants are not folds, by design.** `acronym` (`IBM` ≠ `International Business
Machines`) and `drop_letter`/`swap` (`Northwnd` ≠ `Northwind`) deliberately produce a
*second* key — the first because an initialism is not always the same identity, the
second because a mistyping is what RapidFuzz candidate lines are for. Every other
variant converges in `canon` and is asserted to.

**The Owner is never fuzzed.** `Mark Jones` is emitted byte-identically by every writer;
a fuzzed owner would break the one invariant the app's ingestion depends on.

**`Person` is not generated.** A person extracted from a body competes with the
Correspondent already on the thread, so the kind is listed in `FUZZ_BODY_KINDS` but has
no table and no variants — it is documented, not wired.

**`abbrev` only touches compass words.** `North Dakota` → `N Dakota` folds; `St Paul` →
`S Paul` does not, because `canon` expands a leading `n`/`s`/`e`/`w` to
`north`/`south`/`east`/`west` and nothing else — so abbreviating `St` would silently
produce a *different place*.

The result is reported every run, so a knob that produces nothing is visible rather than
silent:

```
fuzz: corr fuzzy=17/7% multi-platform=6/8% of 71
fuzz: senders intra=17/12 on whatsapp, telegram, messenger
fuzz: bodies org      items=232 fuzzy=35/15% mention=11/8% platform=13/4%
fuzz: bodies place    items=254 fuzzy=43/15% mention=23/8% platform=10/4%
fuzz: bodies product  items=100 fuzzy=17/15% mention=8/8% platform=6/4%
```

Outlook is the one platform outside the fuzz: a `.pst` cannot be synthesised (see above),
so `World.cast_platforms()` excludes it rather than spending a dice on a platform that
can never carry the result.

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