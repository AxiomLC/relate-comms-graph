# Locking in node extraction — the Places template

**Status:** built and tested. This doc is now the **template** for the next kinds
(`Organization`, `Product`, then `Person`), not a proposal. Supersedes the Place
material in `NodeExtraction.md` where they differ.

**Scope decision:** English only, v1. The app is public and user data could be from
anywhere, but extraction ships English-only deliberately, and the seam for other
languages is left open above the extractor rather than baked into it.

**Tests:** `pytest tests -q` → 422 passed, 2 skipped. The 22 in
`tests/test_extract_places.py` are this feature's contract.

---

## Why Places, and not People

`Person` looks like the easy first entity because correspondents are already in the
graph. It is not: every thread already carries a `Correspondent`, so a Person extracted
from a body would either duplicate that node or need to be reconciled against it — a
merge problem with a wrong answer that looks correct.

A Place has no existing node type competing with it, so the whole pipeline could be
built and judged on its own terms. It has now been built, and the shape below is what
the other kinds copy.

---

## The order, and why it is this order

    extract per message  ->  fold within a platform  ->  match across platforms

**Extraction comes first, and cannot be replaced by `canon`.** `canon.canonical()`
normalises a name it is handed. It cannot decide that a span of text *is* a place.
Running every capitalised word through `canonical(kind="place")` produces `monday`,
`hi dave` and `ny` — no error, no useful result.

**Folding within a platform comes second.** Two spellings of one place on one platform
become one node, and the surviving node hangs off each thread **once**, no matter how
many messages named it.

**Cross-platform matching comes last.** Only a place that survives per-platform folding,
and appears on more than one platform, becomes `:Merged`.

This is the order `Correspondent` uses, and for the same reason.

### Where each step lives

| Step | Module | Entry point |
|---|---|---|
| Extract | `relate_comms/extract.py` | `extract.extract()` / `extract.places()` |
| Fold | `relate_comms/writer.py` | `writer.write_places()` — calls `canon.canonical(kind="place")` |
| Merge | `relate_comms/link.py` | `link._link_entity()` — reuses `_fold_groups` / `_fold` / `_inherit` |
| Wire | `relate_comms/ingest.py` | inside the per-batch loop, plus `link.link()` at the end |

---

## The node shape — copy this for every kind

An entity node is **structurally identical to a `Correspondent`**. This is not
convenience; it is what lets one `_reconcile`, one folder and one Viewer render them all.

Flat facts, written by the MERGE statement, one per platform:

    handle_<platform>   that platform's spelling
    seen_<platform>     that platform's first sighting (ISO string)

Derived, recomputed by `writer._reconcile(cur, keys, label=…)` after the rows land:

    platform            single string, first by date — what the source filter reads
    platforms           full list, date order
    platform_label      `Telegram-LinkedIn-Email-WhatsApp`
    display_name        spelling from the earliest platform
    first_seen_utc      minimum stamp across platforms
    :Merged             set when `len(platforms) > 1`, removed when not

Entity-only extra: `mention_count`, a **message** count, accumulated with `max` on
re-ingest and summed when two nodes fold.

**`platform` is not `platforms`.** A node on four platforms still has one `platform`
string. Anything that *displays* platforms must read the list. See "The Viewer rule".

---

## Glyphs — what each kind draws

All four kinds are now drawn as **glyphs**, not filled circles. The constraint that
drives everything: a Cytoscape `background-image` cannot be tinted, so a glyph needs **one
file per platform colour**. That is 8 files per kind (7 distinct colours + `merged`),
which is why they are **generated**, not hand-written:

    python scripts/build_entity_icons.py

| Kind | Source art | File prefix |
|---|---|---|
| `Place` | map pin (SVG Repo) | `place-*` |
| `Organization` | office block | `organization-*` |
| `Person` (extracted) | standing figure | `person-extracted-*` |
| `Product` | none yet | draws a plain circle |

The extracted Person is prefixed `person-extracted` so it can never collide with the
Correspondent's `person-*` artwork — same subject, different kind.

### Two rendering bugs this exposed

1. **The entity node query never returned `merged`.** Correspondents had
   `c:Merged AS merged`; the entity query did not. So the canvas had no way to put a
   multi-platform Place in the merged bag, draw its halo, or pick the neutral glyph —
   every entity would have looked single-platform regardless of what the store said.
2. **Dropping the aggregation returned one row per edge.** Fixing (1) introduced a
   duplicate node per `MENTIONS` edge until the query was grouped back to one row.

### The merged halo colour

A merged Correspondent keeps the orange halo: orange means "one person, several
platforms", a verified identity. A merged **Place** takes a **dark grey** halo
(`#5a5f66`, `NODE_TYPES.Place.mergedGlowColor`), because its merge is the weaker claim
— same canonical spelling, two platforms. Same halo geometry, weaker signal.

The gradient stops are derived from the kind's own hex by `mergedStopsFor()` in
`GraphCanvas.jsx`. The transparent stop must be `rgba(...,0)`, never 8-digit hex:
Cytoscape's parser rejects the latter and the resulting null takes the whole stylesheet
down.

---

## The Viewer rule (this was a live bug)

Found after the extraction work landed, and it is the reason this section exists.

`CorrespondentView` and `EntityView` both rendered:

```jsx
{platformLabel(entry.platform)}   // ONE string
```

So a merged 4-platform person looked exactly like a 1-platform person, and nothing said
"merged" anywhere in the meta panel. The store and the API were correct throughout —
`platforms` and `platform_label` were populated on all 34 merged nodes — the Viewer was
the only place that lied.

The rule, now enforced in both views and to be enforced in any future one:

1. Render **one pill per platform**, from `entry.platforms` (falling back to
   `[entry.platform]` for a node written before the list existed).
2. Colour each pill with that platform's `platformColor`.
3. Render a **`Merged`** pill when `entry.merged` is true.
4. Never render `entry.platform` alone as if it were the whole story.

The canvas was never wrong: it reads `merged` and `platforms`, draws the grey glyph and
radial halo, and keeps the node out of the platform bags. The Viewer must match.

---

## What each step must not do

- **Extraction must not merge.** It emits spans with offsets and the message key they came
  from. Nothing is decided at extraction time, so a better extractor can be re-run over old
  messages without touching the graph.
- **Folding must not be fuzzy.** A fuzzy pair proposes a merge; it does not perform one.
- **Cross-platform matching must not run early.** Per-batch linking only ever sees one
  platform, which is exactly what `link.py` was written to avoid.
- **Entities get no `POSSIBLY`.** Two places one letter apart are two places, and there is
  no second signal to weigh. `POSSIBLY` stays Correspondent-only.

### The sentence that decides the design

**Extraction proposes; `canon` folds; `link` merges.** Three verbs, three modules, in that
order. Any change that lets one of them do another's job should be rejected, because the
whole value of the split is that a wrong extractor can be re-run without a re-ingest and a
wrong merge can be undone without touching the messages.

---

## What the build learned that the design did not predict

### 1. The model alone silently loses places

`en_core_web_sm` labels a bare city `PERSON` when the sentence gives no locative cue:

    Then Austin on Friday        -> Austin is PERSON
    Flying to Austin tomorrow    -> Austin is GPE

Same word, opposite verdict. Relying on the model was not merely imprecise, it was
*silently lossy*, which is the one failure the design calls unacceptable. The fix is a
shipped `PLACE_DICTIONARY` applied by `EntityRuler(before="ner", overwrite_ents=True)`.

### 2. Two `canon` bugs were hiding behind this feature

- The `place` branch never stripped a leading article, though `ARTICLES`' own comment
  says "thing or place". `the Bay Area` and `Bay Area` were two nodes. Only `product`
  implemented it.
- `_REGION_TAIL` is lowercase-anchored but runs **after** case flattening, so it could
  never match, and `Kensington, London` kept its country inside the node key.

### 3. Abbreviations needed a table, not fuzz

`N Dakota` does not fold onto `North Dakota` under any string rule. A fixed
`PLACE_QUALIFIERS` table (`n`->`north`, `s`->`south`, `e`->`east`, `w`->`west`), applied
only when a real word follows, does it. Same shape as `NICKNAMES`: every entry is a
claim, auditable, and cannot invent a name it does not recognise.

This mattered because `sample_writer` emits exactly that pair.

### 4. Accepted false positives, deliberately unfiltered

The model calls some products `GPE`/`FAC` in prepositional frames:

    nothing new from Databricks     -> Databricks is GPE
    We use Databricks daily         -> nothing

Those become Place nodes today. They are **not** filtered, because suppressing a `GPE`
that also looks like a company is extraction deciding — and it would also drop a real
place that shares a name with one.

What makes it tolerable is the architecture, not a blocklist: a stray node is derived,
`mention_count` = 1 makes it obvious, deleting it touches no message, and `link` never
merges on it.

---

## English-only, and what that commits us to

- Anything not English is simply not extracted from. It is not mis-extracted: silence is
  cheaper than a wrong node.
- `extract.language_guess()` sets a **non-blocking warning** on the batch report
  ("N message(s) look non-English…"). It never errors and never gates the message write.
- The seam sits above the extractor. A later language is a second model and a per-message
  guess, not a rewrite.
- The UI must not promise more than this. A French or Arabic export should show no Place
  nodes and no error.

---

## `sample_writer` carries the proof — verified, not asserted

The public repo demonstrates the feature through generated data. Both folds are confirmed
against `sample_writer/out`:

    N Dakota / North Dakota      converge to place:north dakota   (3 platforms)
    Bay Area / the Bay Area      converge to place:bay area       (4 platforms)
    toronto, austin              merged across 3 platforms each

Full sample ingest: **20 Place nodes, 8 `:Merged`.**

---

## Carrying this to the next kind

For `Organization`, `Product`, then `Person`:

1. Add the label to `canon.KINDS` — `tools.ENTITY_KINDS` and `link.ENTITY_LABELS` derive
   from it, so the query, the alias and the linker pass follow automatically.
2. Add an index to `writer._SCHEMA`.
3. Add the spaCy label to `extract.PLACE_LABELS`-equivalent selection, or a new selector.
4. Add the evidence ladder to `ENTITY_EVIDENCE_ORDER` if the kind has more than a name.
5. Render it through `EntityView`, obeying the Viewer rule above.

`Person` remains the hard one and should stay last: it competes with `Correspondent`, and
that is a merge problem, not an extraction problem.
