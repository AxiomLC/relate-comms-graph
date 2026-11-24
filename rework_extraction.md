# rework_extraction.md — what is still open

**Not a spec.** `HANDOVER.md` holds what shipped; this holds only what is still moving.
Everything else was deleted on 2026-11-24 — the measurements worth keeping are in
`HANDOVER.md` §2 and `TECHREADME.md`.

**Last updated 2026-11-24.** The lists are loaded. One decision remains.

---

## 1. The lists are in

| List | Entries | Where |
|---|---|---|
| Places | **691** | `extract.PLACE_DICTIONARY` |
| Organizations | **585** | `extract.ORG_DICTIONARY` |
| Products | **764** | `products.INDEX` (699 plain + 28 gated, minus 16 generics) |

Merged, not replaced: the entries that were already in code are the ones the pipeline was
tested against, and several (the sample pool `Fargo`/`Bismarck`/`North Dakota`/`Bay Area`)
exist so a public clone has something to find.

**Three bugs the load exposed, all fixed:**

1. **A short dictionary entry truncated a longer name.** `overwrite_ents` on a 691-entry
   gazetteer cut `Kensington Market` (an `ORG` to the model) down to `place:kensington`.
   32 organizations and 8 products begin with a place name. Fixed by snapshotting the
   model's spans before the ruler and restoring any span it shortened.
2. **Products were never in the ruler at all.** Only places and orgs were, so a multi-word
   product split: `Toyota Hilux` → `Toyota` (ORG) + `Hilux` (PRODUCT). 7 of 724 entries
   reached the ruler by accident.
3. **`NORP` was dropped outright.** `Vitra` and `Persian` both come back `NORP`, so
   `a Persian rug` produced nothing. Added to `PRODUCT_RESCUE_LABELS` alongside `PERSON`.

Plus: a leading `The ` is stripped when building a ruler pattern (`The North Face Nuptse`
required the article, so `North Face Nuptse` never matched).

---

## 2. The one open decision — GLiNER

Still unmeasured on this machine. Not installed; `onnxruntime` absent. Its own quoted CPU
range is 22–512 ms/message against our ~1.5 ms.

**The residual recall hole is now small enough that this is a judgement call, not a gap.**
The lists cover the vocabulary; what remains is names nobody listed. Measure before
installing: if the hole is a handful of nodes per thousand messages, GLiNER is not worth
200× the cost.

---

## 3. Declined, with reasons

| Suggestion | Verdict | Why |
|---|---|---|
| **`en_core_web_lg`** | Declined | Its `PRODUCT` label is OntoNotes "objects, vehicles, foods" — the `Coca-Cola` half, not the `Temporal` half. ~10× the small model, arbitration untouched. |
| **A local LLM for bulk extraction** | Declined | No GPU, thousands of messages, determinism required for re-ingest. |
| **Wikidata / Wikipedia entity linking** | Deferred | Right idea for `Gemini`-the-model vs `Gemini`-the-constellation, but GBs on disk and it resolves only *famous* entities — not the internal tool or the obscure SKU where a professional graph actually lives. |
| **A learned calibrator** | Declined | The only labelled set is one `sample_writer` seed. Fitting on it tunes the rules to the fixture. |
| **Stored `unresolved` state** | Declined | An untyped node does not draw, label or query. `Mention.candidates` records the alternatives instead. |
| **Extraction cache keyed by span + model + index version** | Deferred | Correct answer to a cost we do not have: full re-ingest is ~11 s. Revisit only if GLiNER lands. |
| **GLiNER as a core component** | Deferred, not declined | Both reports recommended it and neither measured it here. |

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
3. **`ORG` spans are never demoted to Product.** `Grafana Labs` the company contains
   `Grafana` the product; demoting would lose a true fact.
4. **Product fuzzy-fold across platforms?** No — `_link_entity` is exact-name only.
   `Coca-Cola`/`Coca Cola` fold in `canon`; `RTX`/`rtx` fold by casefold. Nothing more is
   needed.
5. **`SSD`, `RAID`, `NVMe` are in `_PLAIN`.** They are categories rather than products, but
   they appear in procurement frames where a category *is* what is being discussed. Left in
   deliberately; move to `GENERIC` if they read as noise on real data.
