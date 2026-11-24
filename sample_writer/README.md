# sample_writer

A standalone generator for **the relate-comms-graph** app. It writes a batch of **fake**
platform downloads that are structurally identical to real ones — so the whole app can be
exercised end to end without anyone's real message history.

**The build is fully self-contained.** Every run synthesises the downloads from scratch
(`world.py` picks the cast, `plan.py` lays out the threads, each writer renders them). It
needs no real data, no network, and no input to get going:

```
sample_writer/
    out/     <- FAKE downloads appear here; copy these into spool/real/
    in/      <- OPTIONAL: real downloads, only used by `capture`
    schemas/ <- written by `capture` only; local scratch, gitignored
```

`in/` is **not** a required input. The writers imitate the shapes they are coded against;
`capture` is a separate, optional command that reads a real download in `in/` and records
what the app's adapters report — key sets, value types, counts, warnings — into
`schemas/<name>.json`.

> **The generator writes `out/`; the app reads `spool/real/`.** Nothing copies between them
> automatically. A rebuild changes `out/` only — if you then re-ingest without copying, you
> get the *old* corpus and the numbers look identical, which reads like a bug in the
> generator.

---

## Why it exists

`relate-comms-graph` turns a person's messaging history into a searchable relationship
graph. To build and test that you need the awkward corners an export really contains —
threads the owner never spoke in, spam groups, placeholder senders, off-by-one boundary
cases — not a tidy fixture. `sample_writer` manufactures a whole believable export batch on
demand, so the app is always one run away from a realistic demo.

---

## The point: it is meant to be tweaked

Every number that shapes the output lives in [`config.py`](config.py), and changing one
line changes the data:

- `AVG_THREADS_PER_PLATFORM` — more threads (each platform rolls ±`THREADS_JITTER`).
- `BIG_THREAD_COUNT` / `BIG_THREAD_RANGE` / `BIG_THREAD_LOW_WEIGHT` — how many long-running
  threads the world gets, how long they are, and how strongly the short end is favoured.
- `BODY_ENTITY_SHARE` — how often each body kind is chosen (`org` 1.0, `place` 0.7,
  `product` 1.6). A share, not a count: it multiplies the pool size.
- `SPAM_GROUPS = 0` — no spam groups; the build then *reports* the shape as unexercised
  rather than silently dropping it.
- `world.py`'s cast and pools; `dialogue.py`'s topics and sentence frames.
- a platform's shape slightly off? Edit that platform's writer and re-run.

Then copy `out/` into `spool/real/`, truncate, re-ingest. The loop is seconds.

```
python -m sample_writer knobs      # every knob and its current value
```

---

## Platforms

Every run writes to `out/<platform>/<artifact>/`. This is the current surface, **not a
ceiling** — real exporters gain file types and zips over time.

| Platform | Artifacts today | What the app sees |
|---|---|---|
| **Facebook Messenger** | `messenger_zip/`, `messenger_dir/` | `your_facebook_activity/messages/{inbox,filtered_threads,message_requests,e2ee_cutover}/…` |
| **Telegram** | `Telegram Desktop/DataExport_<date>/`, `ChatExport_<date>/` | bulk DataExport and single-chat ChatExport, in the real folder so it drops in as-is |
| **WhatsApp** | `whatsapp-chats-<date>.zip` + `whatsapp_web/` | the extension's bulk zip, plus WhatsApp-Web single-chat zips |
| **LinkedIn** | `linkedin_zip/`, `linkedin_dir/` | `messages.csv` + `Connections.csv` |
| **SMS** | `sms_xml/`, `sms_xml_zip/`, `sms_json_app/` | SyncTech `<smses>`, the compressed form, and a deliberate negative case |
| **Email** | `email_eml/<thread>/*.eml` | one RFC 5322 message per file |
| **Outlook** | `outlook_copy/Outlook.pst` | copy of the committed fixture; a `.pst` cannot be synthesised |

Quirks worth knowing:

- **Dated filenames are dynamic** from the world's clock (`world.end`), so a different seed
  produces differently-named files — exactly like real downloads.
- `messenger_dir` and `linkedin_dir` exist because the adapters branch on `is_dir()`.
- `sms_json_app` **should** be reported unrecognised: it proves the app does not guess.
- **WhatsApp has two dialects.** The writer emits the Web shape (`[10/9/26, 10:23:45 AM]`,
  flat `chat.txt`). The Android export is different — dir-first dates, `.vcf` cards, the
  text file at archive root. The app reads both.
- **Outlook is a byte-for-byte copy** of `tests/fixtures/outlook/Outlook.pst`. A `.pst` is a
  paged MS-PST database with an on-disk B-tree; no maintained pure-Python writer exists and
  every reader is read-only. If you need new Outlook mail, replace the fixture.

> **Naming note.** The store key and artifact folders keep the code name `messenger` (it is
> part of every `Message.key` and must not change). The UI calls the platform **Facebook
> Messenger** — never bare "Messenger", which reads as "a message".

---

## Use

Run from the **repo root**. `build` **wipes then writes**; `add` **writes alongside**.

| Command | Wipe | Write |
|---|---|---|
| `python -m sample_writer` | all | all platforms, default seed |
| `python -m sample_writer --seed 7` | all | all, seed 7 |
| `python -m sample_writer --platform sms` | that platform | that platform |
| `python -m sample_writer --huge` | all | all + the 1,600-message thread |
| `python -m sample_writer add --seed 5` | **none** | all, no clobber |
| `python -m sample_writer clean` | all | nothing — just wipe |

`add` never overwrites: an existing name becomes `name (1)`, `name (2)`, … You are the
source of truth for which files reach the app.

A missing required shape fails the build with a readable list, not a traceback.

---

## The world

One seed, one cast, one clock. `Mary Olver` is the same person on WhatsApp and in email;
`ABC Corp` is a colleague's employer *and* an email domain. Same seed → byte-identical
output.

Fixed cast: `Mark Jones` (Owner, every platform), `Mary Jones`, `Mary Olver`,
`Brandon Steinhart`, `ABC Corp`. Only `CORR_MULTI_PLATFORM` (**8%**) of the generated names
appear on more than one platform — deliberately sparse, so the graph stays honestly
disconnected.

> **Known gap: the knob is not what the store shows.** Per-platform pools are small
> (Telegram 5, SMS 6) against ~30 threads each, so `_pick_distinct` exhausts its pool and
> falls back to any person in the cast — including people whose `on` set never included
> that platform. Measured 2026-11-24: 52 of 95 Correspondents merged (55%) against a knob
> of 8%. The fix is a bigger per-platform cast, not a smaller knob.

### Long-running threads

`BIG_THREAD_PLATFORMS = ("telegram", "messenger", "whatsapp", "sms")` — the four where a
conversation plausibly stays open for years. LinkedIn, email and Outlook are excluded:
LinkedIn is not used for continuous personal comms, and mail starts a new thread per subject.

The world gets `BIG_THREAD_COUNT = (3, 7)` of them, each `BIG_THREAD_RANGE = (150, 520)`
messages, with the lower half twice as likely (`BIG_THREAD_LOW_WEIGHT = 2.0`). The count and
the platform are rolled **once per build**, and the platform list is shuffled before use, so
the first pass is one big thread per platform rather than three on one.

Bodies are templated, not LLM-written: offline, deterministic, milliseconds.

### Who a body may name

| Pool | Size | Frames used |
|---|---|---|
| `ORGS` | 232 | `ORG_LINES` |
| `PLACES` | 254 | `PLACE_LINES` |
| `PRODUCTS` | **184** | three sets, by section — see below |
| `FIRST_NAME` / `LAST_NAME` | 151 / 133 | the Correspondent cast |

**Products split three ways**, because one frame list cannot serve four vocabularies —
`the Powerade renewal is due` and `they shipped vector store` are nonsense:

| Section | Count | Frames | Example |
|---|---|---|---|
| `tech` | 75 | `INDUSTRIAL_FRAMES` — installed, licensed, migrated off | `we're still on Jira` |
| `durable` | 89 | `DURABLE_FRAMES` — owned and maintained | `the Mazda CX-5 needs new tyres` |
| `food` | 20 | `CONSUMER_FRAMES` — consumed and restocked | `we ran out of Marmite` |

Hardware and software share frames deliberately: `we're still on Jira` and `we shipped the
Jetson Orin config` are the same statement. Only the own-vs-consume distinction changes
the sentence. `VEHICLE_FRAMES` (`needs new tyres`, `in the garage`) apply **only** to the
named `CARS`, so a sofa is never in the garage and a watch is never serviced.

The split is a **dialogue concern only**. Nothing in the app's extraction may branch on it:
a frame set that hinted at the answer would make the corpus easier than a real export.

**`PRODUCTS` is ~half consumer now, on purpose.** It used to be ~90% software — enterprise
platforms, CLI tools, GPU part numbers — which is what a vendor conference looks like, not
a person's phone. A professional with a job also has a car, a mortgage and opinions about
coffee.

---

## Fuzz — the same thing spelled differently

### Three independent dice

Every item rolls three dice that **do not condition on each other**. The percentage applies
to the *whole population of that kind*.

```
axis A  SPELLING    normal | fuzzy (one variant, uniform)
axis B  PLATFORMS   1 | 2..len(PLATFORMS)
axis C  MENTIONS    1 | 2-4, on ONE platform only   [body kinds]
```

| Kind | Knob | Default |
|---|---|---|
| Correspondent | `CORR_FUZZY` | 7% |
| Correspondent | `CORR_MULTI_PLATFORM` | 8% |
| Place / Org / Product | `BODY_FUZZY` | 15% |
| Place / Org / Product | `BODY_MULTI_MENTION` | 8% |
| Place / Org / Product | `BODY_MULTI_PLATFORM` | 4% |

**Multi-mention picks exactly one platform.** A second platform with mentions is what
*multi-platform* means; letting each draw its own count would collapse the two axes.

### How often a name reaches the corpus

**`BODY_ENTITY_LINES` (default 4), not pool size, is the ceiling.** Every thread gets up to
that many entity rows in its opening, drawn from all three pools at once. So the mention
slots are `AVG_THREADS_PER_PLATFORM × BODY_ENTITY_LINES`, divided across 670 items.

**Which kind gets a slot is `BODY_ENTITY_SHARE`, not an even split.** The draw is weighted
by `share × pool size`, so a bigger list is not penalised and a smaller one is not
over-represented. Defaults tilt away from places (0.7) and toward products (1.6), because
the app's users are tech people: they name tools and gear far more than geography.
Measured effect on kind picks: place 33% → 28%, product 33% → 35%.

Measured: roughly **1 body in 12** names an entity. An item that never lands in a body
writes nothing — that is the `mention_count: 1` tail, by design.

**Growing a pool does not add slots, it divides the same ones.** Going from 100 to 184
products made each name ~45% less likely to be mentioned. To exercise a bigger list, raise
`BODY_ENTITY_LINES`.

`BODY_FUZZY` is **15% and not 7%** for the same reason: only about a third of the items a
share flags are ever written, so 15% yields roughly 30 fuzzy spellings reaching the corpus.

### Variants — uniform, no weight table

Each kind declares a list; the dice picks uniformly, so each variant is `1/len(list)` by
construction. No weight dict that can fail to sum.

| Kind | Variants |
|---|---|
| `corr` | `lower`, `upper`, `drop_letter`, `swap`, `nickname`, `credentials` |
| `org` | `lower`, `upper`, `drop_letter`, `swap`, `legal_suffix`, `acronym` |
| `place` | `lower`, `upper`, `drop_letter`, `swap`, `abbrev`, `postal_code`, `region_tail` |
| `product` (tech) | `lower`, `upper`, `drop_letter`, `swap`, `hyphen` |
| `product_durable` / `product_food` | `lower`, `upper`, `drop_letter`, `swap` — **no hyphen** |

**Physical goods do not hyphenate.** `hyphen` exists for software names that carry one
(`Coca-Cola`) or are joined in real writing (`MacBook Pro`); applied to a car it produces
`Mazda-CX-5`, which nobody writes and no normaliser should be asked to fold.

A variant that cannot apply does not consume the item's share: `fuzz.pick_variant()` walks
a shuffled copy and takes the first that changes something.

**Two variants are not folds, by design:**

- `acronym` — `IBM` and `International Business Machines` are two keys. An initialism is
  not always the same identity.
- `drop_letter` / `swap` — a mistyping is not a fold. `canon` cannot know `Northwnd` was
  meant to be `Northwind`; that is what the fuzzy fold and RapidFuzz candidates are for.

Every other variant converges in `canon` and is asserted to.

**The Owner is never fuzzed.** `Mark Jones` is byte-identical everywhere; a fuzzed owner
would break the one invariant ingestion depends on.

**`Person` is not generated.** A person drawn from a body competes with the Correspondent
already on the thread — a merge with a wrong answer that looks right. Listed in
`FUZZ_BODY_KINDS`, documented, never wired.

**`abbrev` only touches compass words.** `North Dakota` → `N Dakota` folds; `St Paul` →
`S Paul` would not, because `canon` expands a leading `n`/`s`/`e`/`w` and nothing else — so
abbreviating `St` would silently produce a *different place*.

Every run reports what the dice produced, so a knob that produces nothing is visible:

```
fuzz: bodies org      items=232 fuzzy=31/15% mention=18/8% platform=8/4%
fuzz: bodies place    items=254 fuzzy=34/15% mention=16/8% platform=12/4%
fuzz: bodies product  items=184 fuzzy=29/15% mention=12/8% platform=6/4%
```

Outlook is outside the fuzz: a `.pst` cannot be synthesised, so `cast_platforms()` excludes
it rather than spending a dice on a platform that can never carry the result.

---

## Second-guessing the output

`tests/test_sample_writer.py` drives the app's **real** adapters against a fresh generation
and asserts every mandated shape behaves. It builds into `config.OUT_DIR`, so **running
`pytest` wipes and rebuilds `out/` at the default seed** — expect that.

---

## `capture` — optional, the reference the writers are coded against

```
python -m sample_writer capture
```

The only command that reads `in/`. It records what the app's adapters report for a real
download — key sets, value types, counts, `unknown_kinds`, `skipped` reasons, warnings —
into `schemas/<name>.json`. That snapshot is the honest definition of "same schema".

It calls the adapters directly, never `ingest.ingest`, so the graph store is untouched. The
build does not need `capture` to have run.
