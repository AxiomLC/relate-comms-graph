# sample_writer — major edit

**Status:** scoped, not started. This is the design for one coherent change to
`sample_writer/`, in service of a single question:

> Can the app's ingest actually **detect, extract, flatten and write** the three kinds of
> entity evidence a real export contains — and do we know that, or do we assume it?

**Read [`HANDOVER.md`](../HANDOVER.md) first.** This work unblocks Product-node testing,
the `Person` kind, and further AI/LLM wiring. It is deliberately scheduled *before* those,
because every one of them needs a corpus that can prove or fail the claim.

---

## 1. Why this exists — the app functions this exercises

The generator exists so the app can be tested without anyone's real message history. Its
value is exactly the set of app functions it drives. Measured against those, there is a
gap.

| App stage | Function | What the generator must supply | Status |
|---|---|---|---|
| **Detect** | `ingest.detect_platform()`, `discover()`, `peel()` | a dropped folder that is itself an export, or holds exports | ✅ built (Telegram `DataExport` / `ChatExport` / `Telegram Desktop`) |
| **Extract** | `extract.extract()`, `org.Labels`, `ORG_LABELS`, `PLACE_LABELS`, `ORG_DICTIONARY`, `TRUNCATION_TAILS`, `looks_like_document()` | bodies naming real orgs, places, products | ⚠️ only 25 orgs and 15 places; products never mentioned at all |
| **Flatten** | `canon.canonical(kind=…)` — **13 rules** | one body form per rule | ❌ **5 of 13 rules never generated** |
| **Write** | `writer.write_entities()` → `_write_one_kind()`, `_entity_cypher()`, `_reconcile()` | single-, multi- and cross-platform entities of every kind | ⚠️ no product; no controlled distribution |
| **Merge** | `link._link_entity()`, `ENTITY_LABELS` | the same entity on 2–7 platforms | ⚠️ emergent, not controlled |
| **Serve/view** | `tools.graph_slice()`, `GraphCanvas`'s `hideSingleMentions` | a believable long tail at `mention_count: 1` | ❌ one type of entity achieves it, by accident |

### The finding that motivates the whole edit

`canon.canonical()` implements thirteen normalisation rules. The generator can produce
**seven** forms. Five of the app's rules have therefore never been tested by generated data:

| `canon` rule | Example it should fold | Generated today? |
|---|---|---|
| case flattening | `celestica` / `CELESTICA` | ✅ `lower`, `upper` |
| leading article | `the Bay Area` | ✅ via `PLACES` |
| legal suffix | `Acme` / `Acme Ltd` | ❌ |
| diacritics | `Müller` / `Muller` | ❌ |
| postal code | `Austin` / `Austin 78701` | ❌ |
| region tail | `Austin` / `Austin, TX` | ✅ only because `PLACES` contains the literal |
| place qualifier | `N Dakota` / `North Dakota` | ✅ `abbrev` |
| product hyphen | `Coca Cola` / `Coca-Cola` | ❌ |
| person credentials | `Steve Mikano CIA, AIC-M` | ❌ |
| person nickname | `Steve` / `Stephen` | ✅ `NICKNAMES` |
| `&` / `and` conjunction | `Northwind & Co` | ❌ |
| CamelCase split | `celesticaServices` | ❌ |
| article stripping (product) | `the Coca-Cola` | ❌ |

**This is not academic.** The HANDOVER records a real bug: `the Bay Area` and `Bay Area`
became two nodes because nothing generated the article form — it was found by accident on
real data. The same is true today for legal suffixes and diacritics, which are the two most
common organisation drifts in real exports.

---

## 2. The model — two independent axes

Today's knobs conflate two unrelated properties:

- `FUZZ_BODIES_CROSS` = "multi-platform" **and** "spelled differently"
- `FUZZ_BODIES_INTRA` = "single-platform" **and** "spelled differently"

That is why "named once, on one platform, one spelling" could not be expressed, and why
`mention_count: 1` had no honest population.

Split them. Every entity, of every kind, rolls **independently**:

```
axis A  SPELLING    normal | fuzzy(one variant, uniform)
axis B  PLATFORMS   1 | 2–7 (dice)
axis C  MENTIONS    1 | 2+ within each platform it lands on   [body kinds only]
```

Because the axes are independent, all eight combinations exist — including the two the
user named as most realistic:

- **single-mention, multi-platform** — on Telegram and Slack, named once on each
- **multi-mention, single-platform** — named repeatedly in one export, nowhere else

## 3. What replaces what

| Old knob | New knob | Note |
|---|---|---|
| `FUZZ_BODIES_CROSS` | `BODY_MULTI_PLATFORM` | now a share of all body entities, not a count |
| `FUZZ_BODIES_INTRA` | `BODY_MULTI_MENTION` | now "mentioned ≥2× within a platform" |
| `FUZZ_BODIES_SINGLE` | *(deleted)* | the single/single case is now the majority of the distribution |
| `FUZZ_BODY_SINGLE_KINDS` | *(deleted)* | — |
| `SINGLE_BODY_RATE` (in `dialogue.py`) | *(deleted)* | a rate in the wrong file; superseded |
| `FUZZ_SENDERS_CROSS` | `CORR_MULTI_PLATFORM` | share of the cast |
| `FUZZ_SENDERS_INTRA` | *(kept)* | a sender's two spellings inside one export is a real, separate shape |
| `world.single_orgs` / `single_places` / `_pick_singles()` | *(deleted)* | folded into the axes |
| `dialogue._take_single()` | *(deleted)* | — |

`CORR_FUZZY` / `BODY_FUZZY` are new: no such knob existed, because fuzziness was implied by
the cross/intra shape rather than being its own share.

## 4. The knobs — the whole surface

Each percentage applies to the **whole population of that kind**, independently of the
others. That is the simplification: three numbers per group, no nesting, no interaction.

```python
# Correspondents (sender display names). 8-12% multi-platform today; now explicit.
CORR_FUZZY          = 0.07   # share whose spelling is fuzzy (one variant, uniform)
CORR_MULTI_PLATFORM = 0.12   # share appearing on 2-7 platforms (dice)
CORR_PLATFORMS      = (2, 7) # dice bounds

# Bodies: Place, Organization, Product. Same three numbers, same math.
BODY_FUZZY          = 0.07
BODY_MULTI_PLATFORM = 0.06   # share on 2-7 platforms, mention count independent
BODY_MULTI_MENTION  = 0.13   # share named 2+ times within a platform they land on
BODY_PLATFORMS      = (2, 7)
```

`Person` is **not a body kind** in this phase. It is documented here and generated in its
list, but not wired: a Person extracted from a body competes with the `Correspondent`
already on the thread, which is the merge problem HANDOVER defers. The knob exists so the
shape is not forgotten, and is marked `# not wired`.

## 5. Fuzzy variants — uniform, per kind, no weights

**No weight table.** Each kind declares a list; the dice picks uniformly, so each variant
is `1/len(list)` and the row is 100% by construction. Nothing to keep in sync, nothing that
can fail to sum.

```python
FUZZ_VARIANTS = {
    # Correspondent sender names. `acronym` and `legal_suffix` are meaningless for a person.
    "corr":    ["lower", "upper", "drop_letter", "swap", "nickname", "credentials"],
    # Organizations: companies, councils, NGOs, unions, universities.
    "org":     ["lower", "upper", "drop_letter", "swap", "legal_suffix", "acronym", "diacritic"],
    # Places.
    "place":   ["lower", "upper", "drop_letter", "swap", "abbrev", "postal_code", "region_tail"],
    # Products. Narrowest list: no acronym, no postal code, no credentials.
    "product": ["lower", "upper", "drop_letter", "swap", "hyphen"],
    # PERSON — documented, not wired. Same list as corr minus sender-only forms.
    "person":  ["lower", "upper", "drop_letter", "swap", "nickname", "credentials"],
}
```

### New variants this adds

| Variant | Example | Kinds | `canon` rule it tests |
|---|---|---|---|
| `legal_suffix` | `Acme` → `Acme Ltd` | org | trailing legal form stripped |
| `diacritic` | `Muller` → `Müller` | all | diacritics folded |
| `postal_code` | `Austin` → `Austin 78701` | place | trailing numeric stripped |
| `region_tail` | `Austin` → `Austin, TX` | place | two-letter region tail dropped |
| `hyphen` | `Coca Cola` → `Coca-Cola` | product | hyphen flattened |
| `credentials` | `Steve Mikano` → `Steve Mikano CIA` | corr, person | credential suffix stripped |

### Two honest limits, stated in the code

1. **`acronym` is not a fold.** `IBM` ≠ `International Business Machines` in `canon`, and
   should not be. It is included because real exports do it, and because the *node count*
   is the thing being observed — but it creates two nodes by design, so it must not be
   read as a failed fold.
2. **`abbrev` only fires on qualifier words** (`North`, `South`, …) and `postal_code` /
   `region_tail` only on places. That is why the picker must retry (below) rather than
   pick once.

## 6. Selection semantics — the one rule to get right

A variant that cannot apply must not consume the entity's fuzz share. So:

```
pick = shuffled copy of FUZZ_VARIANTS[kind]
for variant in pick:
    out = fuzz.vary(name, rng, (variant,))
    if out != name: return out          # first that changes something wins
report(f"{kind}: no variant applied to {name!r}")   # only if the whole list failed
```

- **Retry until something applies**, so a fuzzy entity is genuinely fuzzy.
- **Report a total failure** rather than silently returning the normal form — the same rule
  `config.fuzz_lines()` already enforces for knobs that produce nothing.

`fuzz.vary()` already skips a mode that returns the input unchanged, so the loop only needs
to iterate the shuffled list.

## 7. Function areas to edit

### `sample_writer/config.py`
| Area | Change |
|---|---|
| `CORRESPONDENTS`, `CROSS_PLATFORM_MIN/MAX` | **replace** with `CORR_MULTI_PLATFORM`, `CORR_PLATFORMS`, `CORR_FUZZY` |
| `FUZZ_SENDERS_CROSS` | → `CORR_MULTI_PLATFORM` |
| `FUZZ_SENDERS_INTRA` | keep (a real shape: two spellings inside one export) |
| `FUZZ_BODIES_*` block | **replace** with `BODY_FUZZY`, `BODY_MULTI_PLATFORM`, `BODY_MULTI_MENTION`, `BODY_PLATFORMS` |
| `FUZZ_BODIES_SINGLE`, `FUZZ_BODY_SINGLE_KINDS` | **delete** |
| `FUZZ_BODY_KINDS` | keep, drop `person` to `# not wired` |
| new `FUZZ_VARIANTS` | add, per §5 |
| `fuzz_lines()` | report the new distribution: per kind, `normal / fuzzy / multi-platform / multi-mention`, with the requested share beside the achieved one |

**Comment style:** inline, right-of-line, per the user's instruction. The long prose blocks
above each knob move into this document; `config.py` keeps one line per knob.

### `sample_writer/world.py`
| Area | Change |
|---|---|
| `TOPIC_WORDS`, `PEOPLE_ROLES` | **keep** — they produce coherent sentences |
| `COMPANIES`, `PLACES` | **greatly expand** (§9) |
| new `PRODUCTS` | add |
| `ORG_FORMS` | delete (superseded by `FUZZ_VARIANTS`) |
| `body_orgs` / `body_places` / `body_persons` | replace with one generic table: `body_entities: dict[kind, dict[name, EntityPlan]]` |
| `single_orgs`, `single_places`, `_pick_singles()` | **delete** |
| `_assign_labels()` | rework the sender path onto the new axes; keep the Owner invariant |
| `_assign_body_entities()` | rewrite as one pass per kind, rolling A/B/C independently |
| new `body_entity(name, platform)` | unchanged contract, now reads the generic table |
| `fuzz_summary()` | return the new counts, consumed by `fuzz_lines()` |

### `sample_writer/fuzz.py`
| Area | Change |
|---|---|
| `MECHANICAL`, `SENDER_MODES` | keep as the low-level primitives |
| `lower/upper/possessive/drop_letter/swap/abbrev/nicknamed` | keep |
| new `legal_suffix()`, `diacritic()`, `postal_code()`, `region_tail()`, `hyphen()`, `credentials()` | add — pure functions of `(text, rng)`, same contract as the rest |
| new `pick_variant(text, rng, variants)` | the §6 retry loop, returning `(text, applied_variant_or_None)` |
| `vary()` | keep — still the mechanical primitive, no longer the selector |

### `sample_writer/dialogue.py`
| Area | Change |
|---|---|
| `ORG_LINES`, `PLACE_LINES`, `PERSON_LINES` | keep |
| new `PRODUCT_LINES` | add |
| `SINGLE_BODY_RATE` | **delete** |
| `_take_single()` | **delete** |
| `entity_line()` | drop the single-use branch; entity selection now comes from `world`'s plan, and a thread is *told* which entities it may name |

### `sample_writer/README.md`
Update the fuzz section: the two axes, the uniform variant lists, the coverage table from
§1, and the before/after knob names. State plainly that `Person` is documented-not-wired.

### `tests/test_sample_writer.py`
Add assertions for: each kind reaches its `BODY_*` shares within tolerance; every variant in
every list has at least one generated instance; no entity is both "single mention" and
"multi mention"; the Owner is never fuzzed. The suite currently does **434 passed, 2
skipped** and must stay green.

## 8. What this is NOT

- **Not an app change.** Nothing in `relate_comms/` or `app/` needs to change. If this edit
  needs an app change to work, the edit is wrong.
- **Not a `Person` wiring.** Documented, listed, unwired — see §4.
- **Not a model change.** Per the `detachable_graph.md` and HANDOVER findings, a bigger
  spaCy model is not the lever; the generator is.

## 9. Static lists — expand hard

The single biggest win, and the cheapest. `mention_count` needs a genuine long tail, which
needs volume, not cleverness. Target: **hundreds, not tens.**

| List | Today | Target | Domains |
|---|---|---|---|
| `COMPANIES` | 30 | 150+ | tech, robotics, software, hardware, storage, banking, public companies with tickers, government bodies, universities |
| `PLACES` | 15 | 120+ | world cities, US states, UK counties/towns, regions, districts |
| `PRODUCTS` | 0 (**no list at all**) | 80+ | software, services, hardware, models, platforms |
| `GIVEN` / `SURNAMES` | 64 / 45 | 120 / 150 | international, so diacritics occur naturally |

**A note on naming:** the Correspondent pool and the body-Person pool must not overlap. A
body Person equal to a Correspondent's name is precisely the `Person`-vs-`Correspondent`
ambiguity the design defers, so body Persons draw from a separate surname list.

With volume comes the long tail for free: a 150-org pool, each named in a handful of bodies,
produces a realistic `mention_count` distribution without a single extra knob.

## 10. Order of work

1. `config.py` — new knobs + `FUZZ_VARIANTS`, delete the superseded ones. Nothing else
   compiles until this settles.
2. `fuzz.py` — the six new pure functions plus `pick_variant()`. Independently unit-testable,
   no world needed.
3. `world.py` — the generic `body_entities` table and the independent rolls. Delete the
   single-use machinery.
4. `dialogue.py` — remove `SINGLE_BODY_RATE` / `_take_single`, add `PRODUCT_LINES`.
5. Expanded static lists (can be done in parallel; pure data).
6. `fuzz_lines()` + `README.md` + tests.

## 11. Verification, before the next app phase

After the edit, and before Product-node testing or LLM wiring:

```bash
python -m sample_writer --seed 4       # write a world
python -m pytest tests -q              # must stay 434 passed, 2 skipped
python -m sample_writer add --seed 5   # a second world alongside it
```

Then ingest both into an empty store and confirm:

| Claim | Check |
|---|---|
| every `canon` rule was exercised | each of the 13 rules appears in the build log at least once |
| the three shares are real | per kind, achieved `fuzzy` / `multi-platform` / `multi-mention` within ±3% of the knob |
| all four distribution cases exist | single/1, single/N, multi×1/1, multi×1/N all present in the store |
| dedup works on re-ingest | ingesting seed 4 twice adds zero nodes |
| a new world adds nodes | `add --seed 5` then ingest adds new entities, and does not duplicate seed 4's |
| `Product` has no rows | confirms the kind is genuinely unwired, not half-built |

The last row is the point of doing this now: **Product-node testing needs a corpus that
can name products.** Today's cannot — no body ever mentions one.
