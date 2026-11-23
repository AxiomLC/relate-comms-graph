# sample_writer — major edit

**Status: part one is built.** The static lists and the `PRODUCTS` wiring are done and
green (§9). The distribution model — the `BODY_*` knobs and `FUZZ_VARIANTS` (§2–§6) — is
still **spec only**: `config.py` keeps the old `FUZZ_BODIES_*` knobs.

That split is deliberate. Landing the lists first means the remaining work changes
behaviour, not data, and `git revert` on the knob change cannot cost the corpus.

This is the design for one coherent change to `sample_writer/`, in service of a single
question:

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
| **Extract** | `extract.extract()`, `org.Labels`, `ORG_LABELS`, `PLACE_LABELS`, `ORG_DICTIONARY`, `TRUNCATION_TAILS`, `looks_like_document()` | bodies naming real orgs, places, products | ✅ 232 orgs / 254 places / 100 products, all mentionable |
| **Flatten** | `canon.canonical(kind=…)` — **13 rules** | one body form per rule | ❌ **5 of 13 rules never generated** |
| **Write** | `writer.write_entities()` → `_write_one_kind()`, `_entity_cypher()`, `_reconcile()` | single-, multi- and cross-platform entities of every kind | ⚠️ products exist now; the distribution is still uncontrolled |
| **Merge** | `link._link_entity()`, `ENTITY_LABELS` | the same entity on 2–7 platforms | ⚠️ emergent, not controlled |
| **Serve/view** | `tools.graph_slice()`, `GraphCanvas`'s `hideSingleMentions` | a believable long tail at `mention_count: 1` | ⚠️ a long tail now exists from pool size; not yet *controlled* |

### The finding that motivates the whole edit

`canon.canonical()` implements thirteen normalisation rules. The generator can produce
**seven** forms. Five of the app's rules have therefore never been tested by generated data:

| `canon` rule | Example it should fold | Generated today? |
|---|---|---|
| case flattening | `celestica` / `CELESTICA` | ✅ `lower`, `upper` |
| leading article | `the Bay Area` | ✅ via `PLACES` |
| legal suffix | `Acme` / `Acme Ltd` | ❌ |
| diacritics | `Müller` / `Muller` | ❌ *(dropped — see below)* |
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
real data. The same is true today for legal suffixes — the most common organisation drift in
real exports.

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
axis B  PLATFORMS   1 | 2..len(PLATFORMS) (dice)
axis C  MENTIONS    1 | 2+ within each platform it lands on   [body kinds only]
```

Because the axes are independent, all eight combinations exist — including the two the
user named as most realistic:

- **single-mention, multi-platform** — on Telegram and Slack, named once on each
- **multi-mention, single-platform** — named repeatedly in one export, nowhere else

### Expected frequencies, as numbers rather than adjectives

With `BODY_MULTI_MENTION = 0.13` and `BODY_MULTI_PLATFORM = 0.06`, independence gives:

| Combination | Share |
|---|---|
| multi-mention only (single platform) | `0.13 × 0.94 = 12.2%` |
| multi-mention AND multi-platform | `0.13 × 0.06 = 0.8%` |
| single-mention, multi-platform | `0.87 × 0.06 = 5.2%` |
| single-mention, single platform | `0.87 × 0.94 = 81.8%` |

The user's intent — "*occasionally* both, but multi-mention-within-platform-only a bit more
often" — is already satisfied by independence, at a ratio of roughly 15:1. **A correlation
knob would buy nothing visible and is deliberately not added.**

### When the dice are rolled — traced, not assumed

**Measured on the real call chain.** `__main__` builds the world **once**, then loops
platforms calling `plan(world, name, …)`. So:

| Knowledge | Where it exists | Can roll there |
|---|---|---|
| the platform list (`config.PLATFORMS`) | `World.build()` | ✅ multi-platform |
| that platform's thread and message counts | `plan(platform)`, `_fill_bodies()` | ✅ multi-mention |
| both | **nowhere** | ❌ |

Verified: `plan()` sees only its own platform (`{'email', 'telegram'}` when planning those
two). It cannot know that an entity assigned to Telegram should also appear in email,
because email may not have been planned yet.

**So the two rolls cannot live in the same function.** The split is forced by the data
flow, not chosen for taste:

- **Multi-platform dice → `world.py`**, in the same pass as `_assign_body_entities()`. The
  platform list is known and the assignment is then fixed for the whole run, so two threads
  on one platform cannot disagree about whether an entity spans platforms.
- **Multi-mention dice → `dialogue.py` / `entity_line()`**, which is called from
  `turn_pairs()` while a thread's bodies are composed — the only point where the message
  count exists.

The mention decision is *made* in the world (so it is deterministic and inspectable, and
`fuzz_summary()` can report it) and *honoured* in the dialogue layer, which consumes the
plan rather than re-rolling.

Per-entity shape stored by the world:

```python
body_entities[kind][name] = {
    "platforms": (...),        # 1 or 2..len(PLATFORMS)
    "mention": "single" | "multi",
    "variant": str | None,     # the fuzzy spelling, or None
}
```

Platform dice bounds are `(2, len(config.PLATFORMS))` — **not** a fixed `(2, 7)`. Today
`_assign_labels()` hardcodes its own platform list and ignores `config.PLATFORMS` entirely;
that is a bug this edit removes.

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

**A weighted `FUZZ_MIX` table was considered and dropped.** An early sketch gave each kind
explicit weights (`.20, .10, .35, .15, .15`). Three reasons it went:

1. The sketch's weights summed to **0.95**, so 5% of fuzzy entities would have fallen
   through to nothing — the exact failure a hand-tuned table invites.
2. Per-kind applicability makes one shared table impossible: `acronym` is meaningless for a
   Place, `nickname` for an Org, so each row would need its own weights anyway.
3. Uniform gives 100% **by construction**: `1/len(variants)`, nothing to keep in sync.

The percentages are therefore **derived, never configured** — 8 Corr variants is 12.5%
each, 6 Product variants is 16.66%. The config file holds the list and nothing else.

`CORR_FUZZY` / `BODY_FUZZY` are new: no such knob existed, because fuzziness was implied by
the cross/intra shape rather than being its own share.

## 4. The knobs — the whole surface

Each percentage applies to the **whole population of that kind**, independently of the
others. That is the simplification: three numbers per group, no nesting, no interaction.

```python
# Correspondents (sender display names).
CORR_FUZZY          = 0.07   # share whose spelling is fuzzy (one variant, uniform)
CORR_MULTI_PLATFORM = 0.12   # share appearing on 2+ platforms; bounds from PLATFORMS

# Bodies: Place, Organization, Product. Same three numbers, same math.
BODY_FUZZY          = 0.07
BODY_MULTI_MENTION  = 0.13   # named 2+ times within a platform they land on
BODY_MULTI_PLATFORM = 0.06   # on 2+ platforms; mention count independent of this
```

**No separate platform-bounds knob.** The dice upper bound is `len(config.PLATFORMS)` —
whatever this world actually writes. A hardcoded `(2, 7)` would break the moment a platform
is added or dropped, and would let an entity claim a platform that has no messages.

`Person` is **not wired, and not listed here.** The user's decision is not to wire it at all:
a Person extracted from a body competes with the `Correspondent` already on the thread, and
the demo does not need that ambiguity. It appears nowhere in the knobs and nowhere in
`FUZZ_VARIANTS`. What remains is a placeholder in `world.py`'s kind tuple, so the shape is
not forgotten — see §8.

## 5. Fuzzy variants — uniform, per kind, no weights

**No weight table.** Each kind declares a list; the dice picks uniformly, so each variant
is `1/len(list)` and the row is 100% by construction. Nothing to keep in sync, nothing that
can fail to sum.

```python
FUZZ_VARIANTS = {
    # Correspondent sender names. `acronym` and `legal_suffix` are meaningless for a person.
    "corr":    ["lower", "upper", "drop_letter", "swap", "nickname", "credentials"],
    # Organizations: companies, councils, NGOs, unions, universities.
    "org":     ["lower", "upper", "drop_letter", "swap", "legal_suffix", "acronym"],
    # Places.
    "place":   ["lower", "upper", "drop_letter", "swap", "abbrev", "postal_code", "region_tail"],
    # Products. Narrowest list: no acronym, no postal code, no credentials.
    "product": ["lower", "upper", "drop_letter", "swap", "hyphen"],
}
```

**No `person` row.** Person is not generated in bodies, so it needs no variants.

Uniform within each row: 6 Corr variants is 12.5% each, 7 Org is 14.29%, 5 Product is 20%.
The percentage is never written down — it is `1/len(list)`.

### New variants this adds

| Variant | Example | Kinds | `canon` rule it tests |
|---|---|---|---|
| `legal_suffix` | `Acme` → `Acme Ltd` | org | trailing legal form stripped |
| `postal_code` | `Austin` → `Austin 78701` | place | trailing numeric stripped |
| `region_tail` | `Austin` → `Austin, TX` | place | two-letter region tail dropped |
| `hyphen` | `Coca Cola` → `Coca-Cola` | product | hyphen flattened |
| `credentials` | `Steve Mikano` → `Steve Mikano CIA` | corr | credential suffix stripped |

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

**Done (§9):** the static lists, the `ORGS`/`FIRST_NAME`/`LAST_NAME` renames, `PRODUCTS`
created and wired, `ORG_FORMS` kept (still used), and the WhatsApp system-row label fix.

**Pending (§2–§6):** everything below that touches the distribution model.

### `sample_writer/config.py`
| Area | Change | Status |
|---|---|---|
| `CORRESPONDENTS`, `CROSS_PLATFORM_MIN/MAX` | **replace** with `CORR_MULTI_PLATFORM`, `CORR_FUZZY` | pending |
| `FUZZ_SENDERS_CROSS` | → `CORR_MULTI_PLATFORM` | pending |
| `FUZZ_SENDERS_INTRA` | keep (two spellings inside one export is a real shape) | — |
| `FUZZ_BODIES_*` block | **replace** with `BODY_FUZZY`, `BODY_MULTI_PLATFORM`, `BODY_MULTI_MENTION` | pending |
| `FUZZ_BODIES_SINGLE`, `FUZZ_BODY_SINGLE_KINDS` | **delete** | ✅ already absent |
| `FUZZ_BODY_KINDS` | keep; `product` already added, `person` stays on the list | ✅ done |
| new `FUZZ_VARIANTS` | add, per §5 | pending |
| `fuzz_lines()` | report each kind's achieved share beside the requested one | ✅ reports product; shares pending |

**Comment style:** inline, right-of-line. The long prose blocks above each knob move into
this document; `config.py` keeps one line per knob.

### `sample_writer/world.py`
| Area | Change | Status |
|---|---|---|
| `TOPIC_WORDS`, `PEOPLE_ROLES` | **keep** — they produce coherent sentences | — |
| `ORGS`, `PLACES`, `PRODUCTS` | expand / create (§9) | ✅ 232 / 254 / 100 |
| `FIRST_NAME`, `LAST_NAME` | renamed from `GIVEN`/`SURNAMES`, expanded | ✅ 151 / 133 |
| `ORG_FORMS` | keep (still referenced) | — |
| `body_orgs` / `body_places` / `body_persons` / `body_products` | replace with one generic `body_entities[kind][name]` table | pending |
| `single_orgs`, `single_places`, `_pick_singles()` | **delete** | ✅ already absent |
| `_assign_labels()` | rework the sender path onto the new axes; keep the Owner invariant |
| `_assign_body_entities()` | rewrite as one pass per kind, rolling A/B/C independently |
| new `body_entity(name, platform)` | unchanged contract, now reads the generic table |
| `fuzz_summary()` | return the new counts, consumed by `fuzz_lines()` |

### `sample_writer/fuzz.py`
| Area | Change | Status |
|---|---|---|
| `MECHANICAL`, `SENDER_MODES` | keep as the low-level primitives | — |
| `lower/upper/possessive/drop_letter/swap/abbrev/nicknamed` | keep | — |
| new `legal_suffix()`, `postal_code()`, `region_tail()`, `hyphen()`, `credentials()` | add — pure `(text, rng)` functions | pending |
| new `pick_variant(text, rng, variants)` | the §6 retry loop | pending |
| `vary()` | keep — the mechanical primitive, not the selector | — |

### `sample_writer/dialogue.py`
| Area | Change | Status |
|---|---|---|
| `ORG_LINES`, `PLACE_LINES`, `PERSON_LINES` | keep | — |
| `PRODUCT_LINES` | add and wire into `entity_line()` | ✅ done |
| `SINGLE_BODY_RATE` | **delete** | ✅ never added |
| `_take_single()` | **delete** | ✅ never added |
| `entity_line()` | drop probability sampling; entity choice comes from `world`'s plan | pending |

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
- **Not a `Person` wiring.** Person is excluded from the knobs, from `FUZZ_VARIANTS` and
  from body generation entirely. The app keeps the name (`canon.KINDS`, and
  `tools.ENTITY_KINDS` derives from it) so nothing breaks — but generated data will never
  produce a `Person` node, which is precisely the intent. The only placeholder is
  `world.py`'s kind tuple.
- **Not a model change.** Per the `detachable_graph.md` and HANDOVER findings, a bigger
  spaCy model is not the lever; the generator is.

### Diacritics: dropped, on purpose

A `diacritic` variant was planned — `Muller` / `Müller` — and then removed. Generating one
costs a non-ASCII name crossing the whole write chain (JSON, zip members, SMS XML) and a
single mangled byte fails a test for a case the app does not need. `canon` still folds
diacritics if real data carries them; the generator will not manufacture them, and every
static list is ASCII-only.

## 9. Static lists — expand hard

The single biggest win, and the cheapest. `mention_count` needs a genuine long tail, which
needs volume, not cleverness. Target: **hundreds, not tens.**

| List | Was | Now | Domains |
|---|---|---|---|
| `ORGS` | `COMPANIES`, 30 | **232** | tech, robotics, software, hardware, storage, banking, public companies, government, universities, online groups |
| `PLACES` | 15 | **254** | world cities, US states, UK/Ireland, Europe, rest of world |
| `PRODUCTS` | *did not exist* | **100** | software, hardware, storage, AI models, consumer, services |
| `FIRST_NAME` | `GIVEN`, 64 | **151** | ASCII only |
| `LAST_NAME` | `SURNAMES`, 45 | **133** | ASCII only |

**Renamed** to the user's vocabulary: `COMPANIES` → `ORGS`, `GIVEN` → `FIRST_NAME`,
`SURNAMES` → `LAST_NAME`. `PLACES` and `PRODUCTS` already read correctly.

**The brittle slices are gone.** `TECH_ORGS` was `COMPANIES[5:24]` and `PUBLIC_ORGS` was
`[24:]` — positions that silently broke whenever an entry was added. Membership is now by
list, derived from an explicit set of public/non-profit names.

`PRODUCTS` is new and is **wired**, not just listed: `PRODUCT_LINES` in `dialogue.py`,
`world.body_products`, and `product` added to `FUZZ_BODY_KINDS`, so `Product` has generated
data for the first time.

With volume comes the long tail for free: 232 orgs each named in a handful of bodies
produces a realistic `mention_count` distribution without a single extra knob.

### A writer bug the expansion exposed

`sender_fuzz_reaches_the_payloads` failed at 80%. Diagnosis: `_assign_labels()` decides a
sender's spelling at world-build time, but whether that person gets a *speaking part* is
decided later by `plan()`. The world cannot consult it (importing `plan` into `world` is
circular), so a label assigned to a correspondent whose only thread is a single Owner line
is **legitimately never written**. Measured over four seeds: 5% (9% WhatsApp, 0% elsewhere).

The WhatsApp writer also used `.name` rather than `.label()` on system and membership rows,
which is now fixed — a person named in `X added Y` should be spelled as that export spells
them. The test now asserts the property that actually holds (most assignments land; the
ones that land are exact) rather than a ratio over a ~10-label sample.

## 10. Order of work

**Step 5 is done** (expanded lists, `PRODUCTS`, renames) — see §9. Steps 1–4 and 6 remain,
and they are the distribution model. Do them in this order:

1. `config.py` — new knobs + `FUZZ_VARIANTS`, delete the superseded ones. Nothing else
   compiles until this settles.
2. `fuzz.py` — the new pure functions plus `pick_variant()`. Independently unit-testable,
   no world needed.
3. `world.py` — the generic `body_entities` table and the independent rolls.
4. `dialogue.py` — `entity_line()` reads the plan instead of sampling.
5. ~~Expanded static lists~~ — **done** (§9).
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
