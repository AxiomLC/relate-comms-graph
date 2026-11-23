# rework_extraction.md — scratch pad

Working notes for the `Product` leg and the extraction rework. **Not a spec, not a record of
what landed.** `HANDOVER.md` holds what shipped; this file holds the reasoning while the
work is in flight, and the ideas we deliberately declined.

Written 2026-11-23 against the live store (2,124 messages, 171 threads, 110 Places,
102 Organizations, 0 Products) and a fresh read of `extract.py`, `canon.py`, `writer.py`,
`link.py`, `ingest.py`.

---

## 1. What the probes actually showed

Four measurements, run before any plan was written. All of them changed the plan.

### 1.1 A third of the products are invisible to the model

Against `sample_writer`'s 100-name `PRODUCTS` pool, used purely as a label oracle:
**77 of 100 appear in at least one stored body**, and `en_core_web_sm` proposes no span at
all for **23 of those 77** — a 30% recall hole. The failures are not random:

- **every lowercase fuzz spelling** — `the excel renewal`, `iphone`, `rtx`, `gguf`,
  `embeddings`, `patch panel`. Case was the model's only cue.
- **capitalised but contextless** — `Temporal`, `Grafana`, `Airflow`, `Surface Pro`,
  `Pixel`, `Raspberry Pi`, `Apple Silicon`, `NVMe`, `vLLM`, `Fanta`, `Irn-Bru`,
  `Enterprise Licence`, `Free Tier`.
- **the known common-noun tail** — `Seat`, `Contract`.

Conclusion: **a dictionary is mandatory for recall, not a nicety.** There is no rule that
recovers `the excel renewal` without already knowing `Excel` is a name. This settles the
question raised twice before any code was touched.

### 1.2 Products are already in the graph, wearing the wrong label

**29 of 212 entity nodes are product names typed as something else** — 14% of all entity
nodes. `place:tableau` (2), `place:threadripper` (3), `place:cursor` (2), `place:pulsar` (2),
`place:gemini` (2), `place:powerade` (2), `organization:router` (3), `organization:radeon` (2),
`organization:claude`, `organization:looker`, `organization:whisper`, `organization:slack connect`.

This reframes the work. It is **not** "add a fourth kind beside three empty slots" — it is
**re-labeling territory already claimed**. The pipeline must arbitrate against the existing
kinds, and today the first extractor to fire owns the node.

Also note the asymmetry that makes this hard: `place:gemini` is a *confident* error (GPE in a
locative frame, the accepted false positive documented in `extract.py`'s header), while
`organization:snowflake` is *nearly right* (Snowflake is a real company **and** a product).
A `Product` kind cannot simply add nodes; it has to take some away.

### 1.3 Fragmentation is real, cheap, and already winning

**149 messages contain `<br>`** — every one of them with more than one fragment. Tested by
running the current extractor over the 149 bodies whole versus split into 352 fragments:

| | mentions |
|---|---|
| whole bodies | 30 |
| fragments | 34 |

Four genuinely new mentions appear (`opensearch`, `supermicro`, `hugging face`, `apple silicon`),
and — more importantly — **six contaminated spans disappear**, including the junk node
`organization:abc corp?<br>`, which existed only because the ruler matched across a tag
boundary. This is the cheapest correction available: no model, no dependency, no threshold.

Sample of what the bodies look like, and why one-body-one-context is wrong:

```
"I'll look at the Coke account tonight.<br>OpenSearch keeps falling over. just sent it over.<br>shall we sort the campaign out?"
"sounds good give me ten minutes.<br>just sent it over.<br>nothing new from Danske Bank."
```

Two unrelated procurement contexts and a social line, read as one span context.

### 1.4 The store is healthy apart from the labeling

- 0 orphan entity nodes (every Place/Org hangs off a Thread) — the `MENTIONS` write is sound.
- 151 of 212 entity nodes are `mention_count: 1`; the tail is the norm, and the existing
  `theme.filter.showSingleMentions` view toggle already handles it without a store change.
- 21 merged entity nodes, 36 merged Correspondents.

### 1.5 Edge names: two vocabularies, and neither is the portable one

**First reading of this was wrong, corrected here.** `types_present()` reports a single
**`MENTIONS`** edge (325 rows) while `graph_slice()` reports `MENTIONS_PLACE` and
`MENTIONS_ORGANIZATION`. That is not drift and not dead code: `_EDGE_QUERIES`
(`tools.py:575`) is a **read-side projection table**, `name -> Cypher string`, and Cypher
cannot parameterise a node label — so one physical edge type is fanned out into one query
entry per kind by a `for kind in ENTITY_KINDS` loop. `MENTIONS_PLACE` is a *projection
name*, not an edge type in the store.

Confirmed on the live store: default canvas load is **506 nodes / 502 edges** =
`WITH` 171, `MENTIONS_ORGANIZATION` 167, `MENTIONS_PLACE` 158, `POSSIBLY` 6. Both entity
edges do draw.

**The edge types, as stored — five, period:**

| Edge | From -> To | Rows | Drawn by default |
|---|---|---|---|
| `IN` | Message -> Thread | 2,124 | no (too many) |
| `WITH` | Thread -> Correspondent | 171 | yes |
| `MENTIONS` | Thread -> Place \| Organization | 325 | yes, as two names |
| `HAS_ATTACHMENT` | Message -> Attachment | 51 | no |
| `POSSIBLY` | Correspondent -> Correspondent | 6 | yes |

`REPLY_TO` is declared in `_EDGE_QUERIES` and written by nothing — zero rows.

**Three facts about this that bear on the Product leg:**

1. **`MENTIONS` is Thread -> Entity, not Message -> Entity.** "Which message named
   Grafana" is not answerable from the edge; only "which thread". Fine for products
   (they cluster by conversation), but if per-message provenance is ever wanted the
   adapter must carry the message key too.
2. **A Product kind needs no new edge type.** Adding `"product"` to the write table plus
   `ENTITY_KINDS` generates `MENTIONS_PRODUCT` through the existing loop. **Do not add a
   `MENTIONS_PRODUCT` edge to the store** — it would be a third physical edge for one
   logical fact.
3. **`types_present()` will not show it.** Its `MENTIONS` count simply rises, with no
   new type listed. Anyone reading the ingest report will see 325 -> N and no explanation.

**Portability — the stated intent that changes what `_EDGE_QUERIES` is allowed to be.**
The extraction output is meant to become a vendor-neutral payload for other graph engines
(FalkorDB, HydraDB, Omni Graph), so `_EDGE_QUERIES` is backend-specific and must not become
the definition of the model. Three layers, kept separate:

| Layer | Contents | Portable? |
|---|---|---|
| **Facts** | `(subject_key, predicate, object_key)` triples | fully |
| **Typing** | node/edge label from *our* closed vocabulary | yes, if the vocabulary is ours |
| **Projection** | `_EDGE_QUERIES`-style Cypher | **no** — one per backend |

Consequences to hold to: `MENTIONS_*` names are projections, not schema; `POSSIBLY` is an
app-specific guess line with no general equivalent; and `WITH`/`IN` are local spellings of
generic relations that a portable vocabulary would rename. None of this blocks the Product
work — it constrains where the Product vocabulary is written down.

**Doc drift still real, separately:** `HANDOVER.md` claims `118 MENTIONS_PLACE`, which is
neither the stored name nor today's count. `DRAWABLE_EDGE_TYPES` (`tools.py:626`) and
`tests/test_tools.py:144` both hardcode the two entity names rather than deriving them from
`ENTITY_KINDS`, so a fourth kind is a third place to edit by hand. Worth folding into
`ENTITY_KINDS` in step 2.

---

## 2. Real-world vocabulary — the thing that sizes this work

The user's framing, which the probes support: real users are professionals and technical
people whose comms are **half ordinary life, half corporate/technical**. `sample_writer` is
*partially* tuned to that. It has `ORGS` (232) and `PLACES` (254) pools and a `PRODUCTS` (100)
pool, but the product pool is a mix of three unrelated vocabularies:

- **SaaS/dev tools** — `Databricks Lakehouse`, `Temporal`, `Grafana`, `dbt Core`, `Kafka`
- **hardware/SKU** — `Threadripper`, `RTX`, `NVMe`, `Raspberry Pi`, `DGX Station`
- **consumer brands** — `Coca-Cola`, `Irn-Bru`, `Weetabix`, `Marmite`, `Monster Energy`
- **commercial abstractions** — `Support Plan`, `Enterprise Licence`, `Seat`, `Credits`, `SLA`

Only the first two categories are what a professional's graph is *for*. The consumer brands
are there to keep the pipeline honest about ordinary chat, and they behave exactly like
products (which is correct — `Coca-Cola` **is** a product, and it should be one). But the
fourth category is the dangerous one: `Seat`, `Credits` and `SLA` are not products, they are
**commercial nouns that appear inside procurement sentences about products**. The generator
carries them as products because a body says `can you get me a {product} seat?` — which is
also why `place:` and `organization:` nodes exist for `seat` and `sla`.

**The consequence for the design:** we cannot build this leg for one vocabulary and pretend
it covers the others. The index must be *generated and extensible*, because a real user's
graph will contain products nobody wrote into a fixture — an internal tool, a vendor SKU, a
new model release. A hand-authored list is a demo artefact.

---

## 3. What the AI research suggested, and what we are NOT doing immediately

Two rounds of research returned. Summarised honestly, with the reason each item is deferred
or adopted.

| Suggestion | Verdict | Why |
|---|---|---|
| **GLiNER-small as a candidate generator** | **Deferred, not declined** | Both rounds recommended it and **neither measured it on this machine.** It is not installed (`ModuleNotFoundError: gliner`), `onnxruntime` is absent. Its own quoted CPU range is 22.7 ms to 512 ms per message — a 22× spread — against our current ~1.5 ms. That is 15–340× our cost. It may well earn its place; it has not earned it yet. Step 6, after the index is measured. |
| **`en_core_web_lg`** | **Declined** | It has a `PRODUCT` label, but the label is OntoNotes `PRODUCT` = "objects, vehicles, foods" — the `Coca-Cola`/`Weetabix` half, not the `Temporal`/`Terraform` half. It costs ~10× the small model and leaves the arbitration problem untouched. It would fix maybe a third of the 23 holes and none of the 29 mislabels. |
| **A local LLM for bulk extraction** | **Declined** | No GPU. Thousands of messages. Determinism required for re-ingest. This is the one recommendation both rounds ranked below everything else, correctly. |
| **Wikidata / Wikipedia entity linking** | **Deferred** | Genuinely the right tool for `Gemini`-the-model vs `Gemini`-the-constellation. But it is GBs on disk and it resolves *famous* entities only — it will not know the internal tool, the vendor SKU, or the obscure enterprise product, which is where the professional graph actually lives. Tier 2 at best, after a generated index exists to compare against. |
| **A learned calibrator (logreg/GBM over ~200 samples)** | **Declined for now** | The only labelled set is one `sample_writer` seed. Fitting on it produces a model tuned to the fixture's vocabulary, which is precisely the overfit the hand rules exist to avoid. Revisit when real exports exist. |
| **Deterministic rule ladder before any scoring** | **Adopted** | The strongest idea in either report: most of these decisions are categorical (blocked generic / protected phrase / exact index hit), not smoothly tradeable. Rules first, weights never. |
| **`unresolved` as a legitimate outcome** | **Adopted** | An entity we cannot type is not a `Place`. Forcing it into one of the existing buckets is how `place:tableau` happened. |
| **Persistent, version-keyed extraction cache** | **Deferred** | Correct answer to the re-ingest cost problem, but it is infrastructure for a problem we do not have yet: a full re-ingest is ~26 s, and `delta=False` is rare. Caching now would be optimising the wrong acceptance criterion. Revisit if GLiNER lands. |
| **Generated-not-authored index** | **Adopted, with a correction** | Right idea. But its proposed seed set (package registries: npm, PyPI, crates.io, Hugging Face) biases hard toward a *developer* graph. A finance or legal professional's products are not on PyPI. The seed is our own graph plus a curated domain list; registries are one source, not the source. |

### The one thing neither report said, that matters

**`canon(kind="product")` already exists and already folds hyphens** (`canon.py:490–500`).
`Coca-Cola` → `coca cola`, article stripping for multi-token products. That means the
canonicalisation half of this work is done, and the fuzz variants `hyphen` and the case
variants already converge. What is *missing* is the step where a span is decided to be a
product at all.

But there is a contradiction to resolve first: `canon` will happily map `Seat` and `seat` to
the same key `seat`. If the index blocks `seat` as generic, then the index and canon disagree
about what a key means. **The block belongs in the index/match layer, not in canon** — canon's
job is spelling, the index's job is deciding whether a spelling is a name. Record this in
whoever touches either file.

---

## 4. The plan

Five steps. Each independently testable; each leaves the app working. Steps 1 and 2 ship
without any new dependency.

### Step 1 — Fragment HTML bodies before extraction  — **DONE 2026-11-23**

**Where:** `extract.py`, in the pipe, not in the adapters.

- Split on `<br>`, `<br/>`, `<br />`, case-insensitive.
- Run extraction per fragment; keep `message_key` as the parent so the `MENTIONS` edge and
  `mention_count` are unchanged. Fragment index is provenance only, never a node.
**Measured effect: +4 mentions, −6 contaminated spans including `organization:abc corp?<br>`.**

**Landed, and re-measured on the rebuilt message-anchored store** (154 `<br>` bodies). The
first figure was taken with an ad-hoc comparison that substituted `\n` for the tag; the
shipped code splits properly. Done against `extract.fragments` disabled via monkeypatch, so
only the split differs:

| | mentions on `<br>` bodies |
|---|---|
| whole body | 28 |
| fragmented | **33** |

**+7 found, −2 contaminated.** The new ones are all real: `abc corp` (×2), `morgan stanley`,
`hsbc`, `runway`, `slack connect`, `seat`. The two removed were markup-bearing or
article-bearing spans: `morgan stanley?<br` and `the abc corp`. **Zero spans now contain
`<` or `>`.**

`MIN_FRAGMENT_CHARS = 1`, not 3. Measured on 374 fragments: 8 are 2 characters (`ok`, `hi`)
and 25 are under 8 — real turns that name nothing, so the floor exists only to drop the
empty piece between adjacent tags, not short turns.

**Where it lives:** `extract.py`, not the adapters. The stored body must stay as the export
wrote it (`canon`'s display path and the Viewer both read it), so only the *reading* of it
changes. `places()` and `organizations()` are fragmented too — a single-body helper that
disagreed with the batch path would only show the difference on the platform that
concatenates turns, which is the worst place to hide it.

**`_pipe_with_context` now yields `list[Mention]`, not `(doc, mentions)`.** The doc was
never read by the caller, and with fragmentation there is no longer one doc per row — a
tuple would invite a caller to assume there is.

Suite **447 passed, 2 skipped** (441 + 6 new). The permanent assertion is
`test_no_span_ever_contains_markup`, plus one that `places()` and `extract()` agree.

**Why here and not in the adapters:** `messenger.py` and `whatsapp_html.py` already strip some
HTML, and their `_text()` is display-oriented. Splitting is an extraction concern — the
stored body should stay as the export wrote it, and extraction should read it correctly. The
`canon` display path and the Viewer keep showing the original.

**Test:** two bodies where a ruler-dictionary name abuts a tag boundary; assert no span
contains `<`. Assert a `MENTIONS` count for a `<br>` message equals the un-split count.

### Step 2 — The `Product` kind, and `unresolved`, behind a flag  — **DONE 2026-11-23**

**Kind registration** (one table entry each, per the existing design):

- `writer._ENTITY_WRITE_KINDS["product"] = "Product"` — the table already exists for exactly
  this; `write_entities` is kind-agnostic by construction.
- `canon.KINDS` already contains `"product"`; `canonical(kind="product")` already folds.
- `link.ENTITY_LABELS` gains `Product`; `_link_entity` works unchanged (exact-name only).
- `ingest` passes `kinds=("place", "organization", "product")` and counts `outcome.products`.
- **`DRAWABLE_EDGE_TYPES` and `tests/test_tools.py` stop hardcoding the entity names** and
  derive them from `ENTITY_KINDS`, so a fourth kind cannot be forgotten in a third place.
  `MENTIONS_PRODUCT` then exists as a projection for free and no new *stored* edge appears
  (§1.5).

**Portability constraint.** The Product vocabulary — the index tiers, the blocked generics,
and the rule ladder — is written as **data in our own closed vocabulary**, not as Cypher or
Relate-specific labels. The facts it produces are `(thread_key, "MENTIONS", entity_key)`
triples; `MENTIONS_PRODUCT` is a projection of those, not the schema. That keeps §1.5's
three-layer split honest and is why the index lives beside `canon`, not beside `tools`.

**The arbitration shape — this is the new part.** `Mention` gains one field:

```python
kind: str = "place"          # what the span IS, after arbitration
candidates: tuple[str, ...]  # what it might be: ("product", "place") — provenance only
```

`extract` becomes: propose spans → score each against the index → emit a `Mention` with the
**winning** kind and the losing candidates kept as provenance. Nothing writes until a kind
is chosen. This is the "do not assign a final type during extraction" idea, implemented as a
*write-time* decision rather than a deferred store: the store keeps one node per name, as it
does today, and the `candidates` tuple on the mention is the audit trail.

**Why not ship `unresolved` as a stored state:** a node with no type does not draw, does not
label, and does not query — it is invisible work. The honest near-term version is *decide at
write time, record the alternatives*, and add a stored-unresolved state only if the review
queue becomes a real UI. Recorded as an open decision, not silently dropped.

**Flag:** `extract.PRODUCT_ENABLED` module constant, default **off** until step 3 lands. Off
means the new code path exists but produces no `product` mentions, so the live store and all
441 tests are unchanged by the merge.

**Test:** a synthetic `Mention(kind="product")` writes a `Product` node with a `MENTIONS`
edge; `write_entities` reports `products: n`; with `PRODUCT_ENABLED = False` the same input
writes zero products and the existing counts are byte-identical.

**Landed.** `extract.PRODUCT_ENABLED = False`, `extract._arbitrate()`, `Mention.candidates`,
`writer._ENTITY_WRITE_KINDS["product"]`, `BatchOutcome.products`, and the `product_key`
index. Suite **454 passed, 2 skipped** (447 + 7).

**The seam is the deliverable, and it is deliberately dumb.** `_arbitrate()` replaces the
`if ent.label_ in PLACE_LABELS ... elif ORG_LABELS` chain with one function that returns
`(winning kind, all candidates)`. With the flag off it is the **identity function** — same
kinds, same order — so every existing count is unchanged. With the flag on it *still* decides
nothing clever, because there is no index to decide with; what changes is that `candidates`
is recorded. That is the plug point step 3 fills in without touching a call site.

**`MENTIONS_PRODUCT` is not advertised while the flag is off.** `DRAWABLE_EDGE_TYPES`
went through three wrong answers on the way: `canon.KINDS` (four kinds, two biome),
`link.ENTITY_LABELS` (follows canon, so it tries to fold Product nodes nothing writes), and
the writer table alone (advertises an edge that can never hold a row). The correct source is
**written AND producible** — writer table filtered by the flag. The failing test that caught
this is worth keeping in mind: it failed because the canvas would have offered a
`MENTIONS_PRODUCT` toggle that drew nothing.

**A test drives the write path directly** with a synthetic `kind="product"` mention, because
no extractor produces one yet. That is the assertion that the leg is *plumbed*, not merely
typed: it proves `Product:grafana` lands with the edge on the Message and `mention_count: 1`.

**`unresolved` is not a stored state.** As §4 step 2 anticipated. The near-term version is
`Mention.candidates`: the alternatives are recorded on the mention, and the store keeps one
node per name as it does today. An untyped node would not draw, label, or query. Revisit only
if the review queue becomes a UI.

### Step 3 — The generated index  — **BUILT, FLAG STILL OFF**

**A correction that changes the argument.** §1.1 and two earlier reports said
`en_core_web_sm` has no `PRODUCT` label. **It does.** Measured directly:

```
labels: CARDINAL DATE EVENT FAC GPE LANGUAGE LAW LOC MONEY NORP ORDINAL ORG
        PERCENT PERSON PRODUCT QUANTITY TIME WORK_OF_ART
"I've moved everything onto Ansible."   -> ('Ansible', 'PRODUCT')
"Ansible keeps falling over."            -> (no entity)
```

So the model is not silent on products — it is **frame-sensitive**, exactly like the `GPE`
false positives `extract.py` already accepts. A label that fires on one preposition and not
another is a coincidence, not a taxonomy. **The 23/77 recall hole stands**, but its cause is
different from the one recorded: not an absent label, an unreliable one. That is the same
argument the Place and Organization dictionaries already rest on.

**Shape.** Deliberately smaller than either report proposed — every field must be *read by a
rule* or it does not exist yet:

```python
@dataclass(frozen=True)
class ProductEntry:
    display: str            # "Grafana"
    key: str                # "grafana"   (matches canon's output)
    aliases: tuple[str, ...] = ()
    generic: bool = False   # blocked as a standalone span
    requires_context: bool = False
```

`vendor`, `kind`, `source[]`, `version` are **not** here. They were in both reports' schemas
and nothing in this plan reads them. Add a field when a rule needs it.

**Three tiers of entry, exactly as the rule ladder consumes them:**

1. **Blocked generics** — never a standalone product: `contract`, `credits`, `seat`, `rack`,
   `switch`, `san`, `ups`, `nas`, `embeddings`, `sla`. `generic=True`.
2. **Context-gated** — a product only inside a protected phrase or with procurement context:
   `support plan`, `enterprise licence`, `free tier`, `onboarding pack`, `migration kit`,
   `cold storage`. `requires_context=True`.
3. **Protected phrases and plain names** — `patch panel`, `slack connect`, `raspberry pi`,
   `surface pro`, `visual studio code`, plus the ordinary one-token products.

**Where the entries come from — generated, then reviewed:**

- **Seed A, from the live graph.** The 212 entity nodes are already a harvest of names the
  app thinks are real. Anything appearing as `ORG`/`FAC`/`GPE` that is in the product
  vocabulary gets re-typed rather than re-discovered. This is why step 2 must land first:
  the index is built *from the graph it is about to correct*.
- **Seed B, the domain list.** Generated from vendored name lists rather than hand-typed —
  ordering matters, because a hand list only ever contains what one person remembered.
- **Seed C, `sample_writer.PRODUCTS`.** The 100 names are the regression set, not a source
  of truth. They must produce ~77 mentions on a default build (the number measured in §1.1).
- **Review queue:** every entry with `requires_context=True` and every candidate that the
  rules could not place. Not a UI yet — a JSON file the ingest report can name.

**The rule ladder** (applied per candidate span, in order, first match wins — no weights):

1. **Generic block wins.** `generic` and no protected phrase → not a product.
2. **Protected phrase wins.** Multi-token protected match → Product, unconditionally.
3. **Exact index hit wins.** `requires_context=False` and the key is in the index → Product.
4. **Context-gated needs context.** `requires_context=True` → Product only if the body
   contains a procurement cue (`renewal`, `licence`, `quote`, `seat`, `subscription`,
   `deployment`, `instance`, `sku`, `purchase`, `upgrade`, `migration`, `tier`).
5. **Otherwise** → leave the span to whatever the model said, and record it as a candidate
   on the mention so a review pass can see what was skipped.

**Built, and the ladder shifted once against the plan.** `relate_comms/products.py`, 92 index
entries, `PRODUCT_ENABLED` still `False`. Suite **479 passed, 2 skipped** (454 + 25).

**Three deviations from the plan above, each forced by a measurement:**

1. **Generics are checked BEFORE the index, and are not in it.** The plan had `generic` as a
   field on an entry. In code that made `decide("Seat")` return `"not indexed"`, which is
   the right verdict for the wrong reason — and the reason is what lands in provenance. A
   separate `GENERIC` set checked first keeps the explanation honest.
2. **`seat` and `contract` are not context cues.** Including them made
   `"a seat by the window"` satisfy the cue test and promote every gated entry in the body.
   A cue has to be a word that is *only* commercial.
3. **The ladder is four rules, not five.** “Protected phrase wins” collapsed into “plain
   name” — a multi-token entry is a protected phrase by construction, so `requires_context`
   was the only distinction that survived. Fewer rules, same behaviour.

**The arbitration is asymmetric, and that is the design.** A `GPE`/`FAC`/`LOC` span may be
reclaimed as a Product; an `ORG` span may not. `Grafana Labs` the company contains `Grafana`
the product, and demoting the org would lose a true fact. So `organization:snowflake` and
`organization:claude` **stay Organizations** — accepted, not accidental.

**A leak the flag had to close.** `en_core_web_sm` does emit `PRODUCT`, so a real model
mention passed arbitration and was then silently dropped by `write_entities(kinds=...)`. A
mention that survives one layer and vanishes in the next is the worst kind of bug: both
layers look correct. `_arbitrate`/the span loop now drops it at the source when the flag is
off, and a test asserts the mention exists with the flag on and does not without it.

**Measured on the live corpus, flag toggled:**

| flag | place | organization | product |
|---|---|---|---|
| off | 63 | 94 | **0** |
| on | 59 | 94 | **10** |

Ten product mentions across five names (`Ansible`, `Excel`, `Fanta`, `Jetson Orin`,
`Pulsar`), four spans moved out of `place`. That is the reclamation working — and it is also
why the flag is **not being turned on yet**: ten mentions from an index of 92 is a thin
yield, and the 23/77 recall hole needs the generated sources (§2) before the leg is worth
trusting in a store.

**Test:** each rule gets a table test. `the excel renewal is due` → Product. `can you get me a
Xeon seat?` → Product (`Xeon`, from rule 3; `seat` blocked by rule 1). `a seat by the window`
→ nothing. `I'm at Grafana Labs all week` → Organization, because `grafana labs` matches an
`ORG` entry and rule 2 of the ladder is never reached for a longer span.

### Step 4 — Measure, then decide on GLiNER

This is the step both reports skipped and it is not optional. On the default build:

- Product mentions found vs the 77 known-present names → **recall of the index**.
- Of those, how many were previously `place:`/`organization:` (the 29) → **recovery count**.
- New `Product` nodes that are not in `PRODUCTS` → **the honest false-positive count**, and
  each one is a real conversation, not a fixture artefact.
- Node count before/after, and whether the canvas stays loadable (the 296-node default load
  is already near the edge of comfortable).

**Only if** the residual recall hole is still material after the index, install
GLiNER-small and benchmark on this machine. The number to beat is 1.5 ms/message. If a
bounded pass over unresolved spans only costs a few seconds on a weekly delta, it is a
candidate; if it costs minutes on a full re-ingest, it is not, because `delta=False` is the
recovery path after any extractor change.

### Step 5 — Docs and the drift

- `HANDOVER.md`: the `Product` leg entry, and the `MENTIONS` vs `MENTIONS_PLACE` correction.
- `extract.py` header: the `candidates` field, the rule ladder, and why the block lives in the
  index and not in `canon`.
- The ~10 common nouns are documented as **decoration, not population**, exactly as
  `HANDOVER.md` §0 already says — their absence from the store is not a bug.

---

## 5. Open decisions — flagged, not hidden

1. **Does a `Product` span beat a `GPE` span, always?** For `Gemini` and `Tableau`, yes. For
   a real user who lives in Gemini, Texas — probably not. The ladder as written says yes
   (rule 3 beats the model), which is a decision to revisit on real data. It is the same
   class of decision as the `Retool` false-positive `extract.py` already accepts from the
   other side.
2. **`Snowflake` is a company and a product.** `organization:snowflake` is arguably correct.
   The ladder will leave it as Organization unless `snowflake cortex` appears (rule 2). That
   is deliberate — a product that is also a vendor is two true statements, and the graph can
   hold both once it has a key namespace per kind.
3. **Should `Product` ever merge across platforms?** `_link_entity` is exact-name only, which
   is right. But `Coca-Cola` vs `Coca Cola` fold in `canon` while `RTX` vs `rtx` fold by
   casefold — both already handled. No new work, recorded so nobody adds fuzzy merge later.
4. **Stored `unresolved` state** — not shipped (see step 2). Revisit if the review queue
   needs to be visible in the UI rather than a JSON file.

---

## 7. Steps 0a/0b — the model change, agreed 2026-11-23

Two changes land **before** the Product leg, because both alter what a `MENTIONS` edge
means and the Product work would otherwise be written twice.

### 0a — `POSSIBLY` is deprecated and removed  — **DONE 2026-11-23**

**Decision:** Correspondents either fold via `canon` or they do not match. No fuzzy edge.

**Why it is not a loss.** The six live edges are all typo pairs a user wants as ONE node:

```
elizabeth esposio   <-> elizabeth esposito
elizaebth esposito  <-> elizabeth esposito
rafeal ritchie      <-> rafael ritchie
vikrm ross          <-> vikram ross
farha tokarev       <-> farah tokarev
```

Every one is a misspelling, not a near-miss of two real people. The edge also does not carry
what it claims: **`r.score` is null on all six rows** — the score is written under a property
name that is not persisted, so the UI can never rank the lines it draws.

**Removal surface** (found by grep, not assumed):

| File | What goes |
|---|---|
| `link.py:470-511` | `_possibly()` — the scorer and the `MERGE` |
| `link.py:385-410` | the re-pointing pass in `_fold` |
| `link.py:22, 81, 87, 95, 357, 531` | docstrings and the `possibly` report key |
| `tools.py:591, 614, 622-626` | `_EDGE_QUERIES`, `_EDGE_PLATFORM_ALIAS`, `DRAWABLE_EDGE_TYPES` |
| `GraphCanvas.jsx:922` | the `edge[type = "POSSIBLY"]` selector |
| `ingest.py:261` | the comment naming it |

The fold that replaces it must be pinned by a test. `vikrm`/`vikram` and
`rafeal`/`rafael` fold; `dimitri whitfield`/`dimitir whitfield` (already an unfocolded pair
in `HANDOVER.md`) folds; two genuinely different people do not. The threshold lives in
`link`, not `canon` — `canon` has no "how close is close enough" concept and should not gain
one.

**Landed.** The fuzzy class is a fifth rung in `_fold_groups`, not a second pass, so a pair
that folds on `phone` never reports itself as `fuzzy`. Verified against the live store on a
copy: **5 folds, all `fuzzy`** — the six old edges minus the duplicate pair. Suite 441
passed, 2 skipped before and after; three tests changed from "most probably one person,
draw a line" to "one person, folded".

**Two bugs found on the way, worth knowing:**

1. **`union()` dropped a group's reason.** It kept the *new root's* reason and discarded the
   absorbed root's, so two unions in sequence could downgrade a group to `exact_name`. It
   was invisible while every rung reported `exact_name` anyway; the fuzzy rung exposed it.
   Now both roots' reasons are considered and the strongest wins.
2. **`merged_by` on the node is written by the *writer*, not by `link`.** `writer` sets it
   from `canon` evidence at write time, and `link` can only fill it with `coalesce` — so a
   node that entered as `exact_name` keeps that value even when the fold that merged it was
   fuzzy. The link-time reason is in `report["merged_by"]` only. **Two sources, one field,
   and they disagree.** Not fixed here because fixing it means deciding which one is
   canonical; recorded so it is not rediscovered. The obvious answer is that `link` owns
   `merged_by` (it is the only thing that *merges*), and the writer should not set it at
   all — but that is a store-wide change.

**Also corrected while there:** `DRAWABLE_EDGE_TYPES` now derives from
`writer._ENTITY_WRITE_KINDS`, not `canon.KINDS`. All three tables disagree today —
`canon.KINDS` has four kinds, `link.ENTITY_LABELS` follows it (and so tries to fold
`Product` nodes nothing writes), and the writer has two. The writer's table is the only one
that says what reaches the store, so it is what an advertised edge follows.

### 0b — `MENTIONS` moves from Thread to Message  — **DONE 2026-11-23**

**Decision:** store `(message)-[:IN]->(thread)` and `(message)-[:MENTIONS]->(entity)`.
`Thread -> Entity` becomes a **read-time projection**. `Message` stays out of the default
canvas node set.

**Measured — it does not cost latency, and the two-hop is free:**

| Operation | Time (2 MB store) |
|---|---|
| Thread-anchored `MENTIONS` read | 2.5 ms |
| Message-anchored `MENTIONS` read | **1.2 ms** |
| Two-hop projection `Thread<-IN-Message-[:MENTIONS]->Entity` | 2.7 ms |

Message-anchored is faster because `msg_key` is indexed and the start node is smaller. The
row count is capped at 325 either way (15.3% of messages name something), so the write cost
is a few hundred extra `MERGE`s against a ~26 s ingest — invisible.

**The real cost is a semantic change, not a timing one.** `mention_count` today means "how
many *threads* named this"; anchored at Message it means "how many *messages*". Same field,
different number, and `theme.filter.showSingleMentions` reads it. Decide and document it;
message-count is the more honest figure, and the `:Merged` override already handles the
cross-platform case.

**Why Message cannot join the default node set** — measured:

| Node set | Nodes | Edges |
|---|---|---|
| Today | 506 | 502 |
| + `Message` | **2,000 (limit hit)** | **177** |

Messages consume the cap (1,706 of 2,000 slots) and starve `MENTIONS_*` to zero. So Message
is **structurally present, query-excluded** — which the UI already supports: it has a
`_NODE_ALIAS`, a sort key, and a count query. The Viewer already lists a thread's messages
in its body, so nothing shown is lost.

**Edit surface:**

1. `writer._write_one_kind` — anchor the `MENTIONS` row at `mention.message_key` instead of
   `thread_key`; `seen_messages` becomes the row key rather than the count source.
2. `_entity_cypher(label)` — the `MERGE` pattern re-anchors `(m:Message)` and still needs
   the Thread to exist, so it keeps an `IN` check or relies on write order.
3. `tools._EDGE_QUERIES` — `MENTIONS_*` becomes a two-hop projection returning thread-level
   endpoints, keeping the canvas payload flat.
4. `tools._EDGE_PLATFORM_ALIAS` — `MENTIONS_*` maps to `"m"`, not `"t"`.
5. `writer._SCHEMA` — index `Message.key` already exists; nothing new needed.

**Store rebuild required.** `delta=False` after this, and the Product work starts against a
clean, message-anchored corpus.

**Landed, and verified on a full rebuild (~10 s, whole spool):**

```
stored:  (Message)-[:MENTIONS]->(entity)   389 rows
         (Thread)-[ :MENTIONS]->(entity)     0 rows
canvas:  518 nodes / 527 edges
         WITH 192 · MENTIONS_ORGANIZATION 173 · MENTIONS_PLACE 162
```

The projection produces the same shape the UI already drew, so nothing in
`GraphCanvas.jsx` changed. Suite 441 passed, 2 skipped.

**One test was rewritten, by design:** `test_mentions_hang_off_the_thread_not_the_message`
asserted the old anchor. It is now
`test_mentions_hang_off_the_message_and_project_to_the_thread`, which asserts all three
facts at once — the stored edge is on the Message, **no** Thread-level edge exists, and
`graph_slice()` still returns the thread→place line.

**Three places `_fold` could have silently eaten the graph.** `_fold` moves a loser's edges
before `DETACH DELETE`, and it was hardcoded to `(t:Thread)-[r:...]`. With `MENTIONS` now
starting at a Message, the old pattern matched nothing — so a Place fold would have re-pointed
zero edges and then deleted every mention the loser had. `_fold` now picks the source from the
edge type. Worth remembering: this is the second place the anchor change reaches, and it is
the kind of place where the failure is silent.

**`mention_count` is now message-based**, as §0b predicted. On this build: Places 113,
Organizations 104, versus 110/102 thread-anchored — small increases, as expected (a thread
naming the same entity twice counted once before, twice now).

---

## 8. Eval — flag ON, corpus rebuilt 2026-11-23

**Corpus first.** The user caught a realism flaw that had been baked into my own reasoning:
`I'm at Grafana Labs all week` was cited as a `GPE` false positive, and **it is not one** — a
professional saying it means the office. Product talk is *I'm on Grafana*.

That was my error, not the template's (`at` + a company is correct English). The real flaw
next door was the template list itself: **one set of frames served four vocabularies**.
`the Powerade renewal is due` and `they shipped vector store last week` are nonsense.

Fixed in `sample_writer/dialogue.py`, two frame sets, not three — hardware and software take
identical sentences, as the user pointed out:

    INDUSTRIAL_FRAMES   13 frames   installed, licensed, deployed, migrated off
    CONSUMER_FRAMES     10 frames   ran out of, in the fridge, on offer
    CONSUMER_PRODUCTS   the 10 drink/food names, listed explicitly

The split is a **dialogue concern only**. Nothing in extraction may branch on it: a frame
set that hinted at the answer would make the corpus easier than the real thing.

**Two extraction bugs the eval exposed, both real:**

1. **`PERSON` spans were dropped outright.** The small model labels `Grafana`, `Tableau` and
   `Docker` as `PERSON` in most frames — so the index could never rescue the names it exists
   for. `PRODUCT_RESCUE_LABELS = {"PERSON"}` lets **only the index** promote them; the naive
   fix of mapping `PERSON` to a kind turned `Dave said it was fine.` into a Product.
2. **`Grafana Labs` was in the product index.** It is a *vendor*, not a product, and the model
   calls it `PERSON` in `I'm at Grafana Labs all week` — so it minted a Product node for a
   premises. Removed. `Snowflake`/`Databricks` stay because the word *is* the product.

**A third bug, found by the numbers not the code:** the canvas showed **no `MENTIONS_PRODUCT`
edges** despite 22 Product nodes. `DRAWABLE_NODE_TYPES` was still a hand-written list of four
names — the same trap already fixed for edges, missed for nodes. Now derived from the write
table filtered by the flag. **An edge is only kept when both endpoints are drawn**, so a kind
missing from the node list silently erases its edges.

### Results

Whole spool, `delta=False`, flag on:

| | count |
|---|---|
| Messages | 2,117 |
| Threads | 175 |
| Correspondents | 94 |
| Places | 98 |
| Organizations | 113 |
| **Products** | **22** |

Canvas: **502 nodes / 572 edges** — `WITH` 185, `MENTIONS_ORGANIZATION` 205,
`MENTIONS_PLACE` 149, `MENTIONS_PRODUCT` 33.

**Precision: 22/22 correct.** Checked every node against the generator's pool. The two that
looked unmatched were `product:coca cola` (pool entry is `Coca-Cola`, folded by `canon`) and
`product:core` (`dbt Core`) — both verified in the messages that produced them. **Zero false
positives.**

**The generic block holds under load.** `can you get me a dbt Core seat?` yields `dbt Core`
and *not* `seat`, in the same body — which is precisely the case the index exists for.

Distinct products found: Coca-Cola (11 mentions), Ansible (3), Excel (3), Docker, Pulsar,
Flink, Marmite, Sprite, Yorkshire Tea (2 each), and 11 more at one.

**Recall is still the open question.** 22 nodes from an index of 92 against a pool of 100.
The remaining gap is names the index does not carry, which is step 3's deferred generation
work (§2), not a bug.

1. Fragment on `<br>` in `extract._pipe_with_context`. Free, measured, no dependency.
2. `Product` kind + `Mention.candidates` + the arbitration seam, flag off. No behaviour change.
3. Generated index in three tiers + the five-rule ladder. Flag on.
4. Measure on a clean rebuild. Decide GLiNER against a real number.
5. Docs, and the `MENTIONS` drift.
