# rework_extraction.md — scratch pad

Working notes for the extraction rework. **Not a spec.** `HANDOVER.md` holds what shipped;
this holds what is still moving, what was measured, and what was declined.

**Last updated 2026-11-23.** Everything through step 3 and the eval has landed and is
committed (`f782812`). What remains is list curation and the GLiNER decision.

---

## 1. Where it stands

### Done — one line each

| # | Change | Evidence |
|---|---|---|
| 0a | **`POSSIBLY` removed.** Fuzzy pairs fold instead of drawing a guessed edge. | The 6 live edges were all typo pairs; `r.score` was null on every one. 5 folds on the live store. |
| 0b | **`MENTIONS` moved Thread → Message.** `Thread→Entity` is now a read-time projection. | Message-anchored read 1.2 ms vs 2.5 ms; two-hop 2.7 ms. |
| 1 | **`<br>` fragmentation.** HTML bodies read as turns, not one blob. | 28 → 33 mentions; 2 contaminated spans gone; zero spans contain markup. |
| 2 | **`Product` kind + arbitration seam** (`_arbitrate`, `Mention.candidates`). | Suite green; flag now ON. |
| 3 | **Product index** (`products.py`) — 92 entries, 3 tiers, 4-rule ladder, no weights. | 22 Product nodes, 22/22 correct, 0 false positives. |

Suite: **479 passed, 2 skipped.**

### The three corrections that came out of doing it

1. **`en_core_web_sm` DOES emit `PRODUCT`.** Two research reports and two of my own notes said
   it did not. It does — rarely, and frame-sensitively:
   `"I've moved everything onto Ansible."` → PRODUCT; `"Ansible keeps falling over."` →
   nothing. The 23/77 recall hole stands, but the cause is an *unreliable* label, not a
   missing one.
2. **`PERSON` spans were being dropped outright.** The model labels `Grafana`, `Tableau`,
   `Docker` as people in most frames, so the index could never rescue the names it exists
   for. Fixed with `PRODUCT_RESCUE_LABELS` — **only the index** may promote a `PERSON`; the
   naive fix turned `Dave said it was fine.` into a Product.
3. **`DRAWABLE_NODE_TYPES` was a hardcoded four-name list.** Products existed in the store
   with **zero edges drawn**, because an edge is kept only when both endpoints are drawn. Now
   derived from the write table filtered by the flag. Same trap as the edge list, missed for
   nodes.

---

## 2. What is still open

### 2a. List curation — the active job

**Brief written: [`entity_list_brief.md`](entity_list_brief.md)**, for an external agent to
build three lists. Awaiting output.

The reasoning behind it, which the brief encodes:

- **Places and organisations are safe to grow large.** They are proper nouns; a city is
  almost never an ordinary word. 500–2,000 of each is fine.
- **Products are the hard list**, because many product names *are* ordinary nouns — `Seat`,
  `Desk`, `Watch`, `Switch`, `Plan`. Multi-word names (`Toyota Highlander`, `Nike Air Max`)
  can *never* be misread as a sentence, which is why the brief pushes the list toward them.
- **A vendor is not a product.** `Grafana Labs` produced a Product node for "I'm at their
  office". Companies go in the organisation list even when they are famous for a product.

**Size is free; precision is not.** Measured on `EntityRuler`:

| Names | Load (once) | Per message |
|---|---|---|
| 100 | 17 ms | 1.18 ms |
| 500 | 90 ms | 1.24 ms |
| 2,000 | 447 ms | 1.24 ms |
| 10,000 | 1,903 ms | 1.54 ms |

Ten thousand names costs **0.28 ms per message**. The product index is not in spaCy at all —
it is a Python dict, so it is O(1) at any size. The ceiling on list growth is **how many
entries can be classified correctly**, not speed.

### 2b. Single-mention visibility, per kind

`theme.filter.hideSingleMentions` already exists, defaults **off**, and `:Merged` overrides it
(two platforms is two independent sightings). What is proposed:

- **Split it per kind** — Place / Organization / Product each independently hideable.
- Rationale: a big product list is safe to *read* once, because the noise never surfaces.
  A single `Rolex` is hidden; a `Rolex` mentioned four times is visibly right.
- **It does not replace the generic block.** Hiding works on mention count; blocking works on
  what the word *is*. `seat` is mentioned *more* often than a rare product, so a mention floor
  promotes junk rather than suppressing it — the two mechanisms cover different failures.

**Consequence to remember:** hidden single mentions are still in the store, still counted,
still searchable. The canvas is not the way to judge a list — query
`MATCH (p:Product) WHERE p.mention_count >= 2`.

### 2c. Step 4 — measure, then decide on GLiNER

Still unmeasured on this machine. Not installed; `onnxruntime` absent. Its own quoted CPU range
is 22–512 ms/message against our ~1.5 ms. **Do not install until the lists are in**, because
the residual recall hole is what would justify it — and that number is not known yet.

### 2d. Step 5 — docs

`HANDOVER.md` needs the Product leg and the `MENTIONS` correction. Done as part of this pass.

---

## 3. Declined, with reasons

| Suggestion | Verdict | Why |
|---|---|---|
| **`en_core_web_lg`** | Declined | Its `PRODUCT` label is OntoNotes "objects, vehicles, foods" — the `Coca-Cola` half, not the `Temporal` half. ~10× the small model, arbitration untouched. |
| **A local LLM for bulk extraction** | Declined | No GPU, thousands of messages, determinism required for re-ingest. |
| **Wikidata / Wikipedia entity linking** | Deferred | Right idea for `Gemini`-the-model vs `Gemini`-the-constellation, but GBs on disk and it resolves only *famous* entities — not the internal tool or the obscure SKU where a professional graph actually lives. |
| **A learned calibrator** | Declined for now | The only labelled set is one `sample_writer` seed. Fitting on it tunes the rules to the fixture. |
| **Stored `unresolved` state** | Declined | An untyped node does not draw, label or query. `Mention.candidates` records the alternatives instead. |
| **Extraction cache keyed by span + model + index version** | Deferred | Correct answer to a cost we do not have: full re-ingest is ~10 s. Revisit only if GLiNER lands. |
| **GLiNER as a core component** | Deferred, not declined | Both reports recommended it and neither measured it here. Its 22–512 ms spread is unbounded until someone runs it. |

**Adopted from the research:** rules before weights (most decisions are categorical);
`unresolved` as a legitimate outcome; generated-not-authored lists.
**Corrected in the research:** package registries as a seed source bias hard toward a
*developer* graph — a lawyer's products are not on PyPI.

---

## 4. Open decisions

1. **Does a Product beat a `GPE`, always?** As built, yes. Correct for `Gemini` and
   `Tableau`; wrong for someone who lives in Gemini, Texas. Revisit on real data.
2. **`Snowflake` is a company and a product.** It stays an `organization:` node unless
   `snowflake cortex` appears. Deliberate — the graph can hold both once keys are namespaced
   per kind.
3. **`ORG` spans are never demoted to Product.** `Grafana Labs` the company contains `Grafana`
   the product; demoting would lose a true fact.
4. **Should `Product` fuzzy-fold across platforms?** Not today — `_link_entity` is exact-name
   only. `Coca-Cola`/`Coca Cola` fold in `canon`; `RTX`/`rtx` fold by casefold. Nothing more
   is needed.

---

## 5. Reference — the measurements behind the design

**The recall hole.** Of 100 generator product names, 77 appear in stored bodies; spaCy
proposes **no span at all** for 23. Every lowercase fuzz spelling (`the excel renewal`,
`iphone`, `rtx`, `gguf`) and most capitalised-but-contextless names (`Temporal`, `Grafana`,
`Surface Pro`, `Pixel`, `Raspberry Pi`).

**The mislabelling.** 29 of 212 entity nodes were products under the wrong kind —
`place:tableau`, `place:gemini`, `place:pulsar`, `organization:claude`, `organization:router`.

**The fragmentation win.** 149 `<br>` bodies; 28 mentions whole vs 33 fragmented; the two
dropped were `morgan stanley?<br` and `the abc corp`.

**Eval after all of it** (whole spool, flag on): 2,117 messages · 175 threads · 94
Correspondents · 98 Places · 113 Organizations · **22 Products**. Canvas 502 nodes / 572
edges. Product precision **22/22**.

**Known limits, unchanged:** English only; name-matched `:Merged` is a weaker claim than
phone/email; `mention_count: 1` is the norm (151 of 212 entity nodes).
