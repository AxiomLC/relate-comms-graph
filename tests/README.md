# tests/

`python -m pytest tests -q` → **501 passed, 10 skipped**, ~71 s.

Two kinds of test live here, and they answer different questions:

| | Answers | Cost |
|---|---|---|
| **Unit / rule tests** | "did this specific decision break?" | ms |
| **Generated-world tests** | "is the whole pipeline still sane?" | seconds |

A re-ingest tells you volume and shape; it cannot tell you that one rule flipped. The
`Kensington Market` truncation was invisible in a 700-node graph and obvious in a test.
Keep both.

---

## Where the payloads come from

**Nothing here reads your personal exports.** Every "real" file is a **generated sample
world**, committed under `spool/real/`, so the suite runs on any clone.

| Test | Payload | Shape |
|---|---|---|
| `test_sms_ingest.py` | `spool/real/sms/sms-20261101000000.xml` | Android *SMS Backup & Restore*, 129 msgs, 30 chats, text only |
| `test_linkedin_ingest.py` | `spool/real/linkedin/Basic_LinkedInDataExport_11-01-2026.zip.zip` | LinkedIn zip, 167 msgs |
| `test_messenger_ingest.py` | `spool/real/messenger/facebook-sampleuser-2026-11-01-1G300tUX.zip` | Messenger zip, 668 msgs |
| `test_whatsapp_ingest.py` | `spool/real/whatsapp/whatsapp-chats-20261101.zip` | **HTML** dialect, 136 msgs |
| `test_outlook_ingest.py` | `tests/fixtures/outlook/Outlook.pst`, else `spool/real/outlook/**/*.pst` | Aspose sample mailbox |

`spool/real/gmail/`, `spool/real/imap/` and `spool/real/outlook/` are **empty by design**.
Email is one platform with many providers, and a mailbox is not a file you can commit —
those legs are exercised by `test_sample_writer.py`'s `.eml` tree instead. The Outlook
test falls back to `spool/real/outlook/` so a real drop-in `.pst` is picked up when one
appears, and skips cleanly when none does.

**A `.pst` cannot be generated in pure Python** — libpff reads the container format but
does not write it — which is why that one fixture is committed rather than generated.

---

## What `sample_writer` produces, and what is covered

`sample_writer/config.py::VARIANTS` is the source of truth. Every artifact it writes is
tested, or is a documented gap:

| Platform | Variants written | Covered by |
|---|---|---|
| `email` | `eml` | `test_email_eml_tree_parses_through_the_real_parser`, boundary tests |
| `telegram` | `bulk`, `single` | `test_telegram_bulk_ingests`; `single` via `test_ingest_pipeline.py` |
| `whatsapp` | `web` (native `chat.txt`), `html` | both dialects, including parser routing |
| `messenger` | `zip`, `dir` | `test_messenger_*`; `dir` reaches `ingest` as one batch |
| `linkedin` | `zip`, `dir` | `zip` parsed; `dir` is a documented gap (CSVs are inputs) |
| `sms` | `xml`, `xml_zip`, `json_app` | `xml` + `xml_zip` parse; `json_app` is a **negative case** |
| `outlook` | `copy` | `test_outlook_ingest.py` |

`test_every_artifact_is_either_detected_or_documented` walks the whole generated tree and
fails on any artifact that neither detects nor appears in its `known_gaps` tuple. That is
the guard against a new variant being written and silently untested.

### Wiring a new format

When `VARIANTS` gains a shape, three things are needed:

1. **A writer** in `sample_writer/writers/<platform>.py`.
2. **A test** that the artifact detects and parses — add it next to the existing
   per-platform tests in `test_sample_writer.py`.
3. **A decision** for `test_every_artifact_is_either_detected_or_documented`: either the
   artifact detects (nothing to do), or it is a deliberate gap and gets an entry in
   `known_gaps` with a reason.

A format the app is *meant* to reject (`sms_json_app`) is as valuable as one it accepts:
it pins "we do not guess".

---

## Speed

The suite is ~88 s, dominated by `spacy.load` and by whole-world generation, not by test
count. Two rules keep it there:

- **Never call `spacy.load` in a test.** Use `extract._ensure_model()` (cached per
  process), or a module-scoped fixture. A bare `spacy.load` costs ~1 s each time.
- **Generate a world once per module**, not per test — `@pytest.fixture(scope="module")`
  on `generated` and `world`.

If it needs to go faster, `pytest-xdist -n auto` is the next lever; the tests are
independent and share no store.

---

## The flush fidelity test — why it exists

`test_flush_is_byte_identical_for_every_node_and_edge` in `test_search.py` is the most
important test in this directory. Read it before changing `tools.flush_embeddings`.

**Why.** Relate has no compaction. Deleting a property (`REMOVE m.emb`) frees no disk;
the file only grows. So "delete the vectors" is implemented as **our own Python rewrite**:
read every node and edge, write them into a fresh `.rl`, swap it in. That is a copy of
the user's entire graph, written by hand — the highest-risk code in the app.

The test dumps every node's labels and every property, and every edge's type, endpoints
and properties, before and after, and asserts the two sets are identical. It also
asserts every index definition survives.

**It has already caught two real bugs:**

1. The rebuild copied nodes and edges but **not indexes**, so BM25 search broke after a
   vector flush — a mode that has nothing to do with vectors.
2. Recreating only the indexes for labels that *hold nodes* lost `place_key` and
   friends on a store whose entity legs were empty.

**Compare index definitions, not names.** The live store's indexes carry auto-generated
names (`Message_key`) from an older `_SCHEMA`; a rebuild replays the current one and
names them `msg_key`. Same index, different label.

**If you add a property type or a relationship property to the writer, this test is what
stops the flush from silently dropping it.**

---

## Conventions

- **Assert properties, not counts, against generated worlds.** The generator's shares are
  dice over a population, so an exact entity count is flaky by construction. Assert a
  floor, a share within tolerance, or a structural invariant.
- **One-sided assertions for fuzz.** `BODY_FUZZY = 0.15` means "not zero and roughly
  there", never "exactly 15%".
- **Read the knob, never the literal.** `config.BODY_FUZZY`, not `0.15` — the knob moved
  from 0.07 to 0.15 in one pass and tests that hardcoded it would have lied.
- **A test that skips on every machine is not a test.** If a payload cannot be committed,
  generate it or delete the test.
