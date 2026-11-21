# CytoGravityRecommend.md

**Status: OPEN — the merged cluster should be a CENTERED BAG, not loose nodes.**
The long-edge root cause is proven (§6 probe sweep); the chosen fix is the
owner's 2026-11-21 "merged bag" design (§9) — not yet built. §0–§8 below record
how we got here; §9 is the forward plan.

---

## 0. 2026-11-21 — STATE OF PLAY after the slider-range round

**What changed in the UI this round (KEPT — built and verified):**

| Slider | Range change | Why |
|---|---|---|
| ring spread | min 1.0 → **0.5** | the only lever that shortens bag-bridge edges (probe-proven, §6). Owner runs 0.65. |
| idealEdgeLength | min 10 → **2**, step 2 → 1 | owner pinned at 10; floor 2 (spring math degenerates below ~2) |
| gravity | max 1 → **3** | plus **inverted display**: slider left = strong. Stored value stays the plain fcose number (3 − shown) |
| gravityCompound | max 3 → **6**, min 0 → **0.05** | **NEVER 0**: exactly 0 stalls fcose's compound tiling — reproduced in the probe (timeout at 0; 0.05 completes fine). Floor 0.05. |
| gravityRangeCompound | 0.5–4.0 → **0.1–1.1**, step 0.05 | re-centered: anything past ~1.1 was dead space; owner wanted more left travel |
| nodeRepulsion | left 2000–60000 | **dropped** — probe-proven no-op; owner declined further tuning |
| nodeSeparation | max 200 → **400** | owner was pinned at 200 (probe says inert, owner's call) |

All verified live in the browser across piecemeal steps; `npm run build` after each
change; watch mode running so a refresh picks up changes.

**What was tried for the merged-center problem and REVERTED (2026-11-21):**

`pullBridgesToRing()` — post-ring damping pull of each merged node toward the
weighted centroid of the bags it connects to. The probe measured the *geometry* as
correct (bag-bridge p50 169 → 109px at damping 0.6, 34 bridges pulled), but in the
**live browser it blanked the canvas** — Edge black-screen, Chrome lost the canvas
but kept UI chrome, reproduced on a zero-cache profile. Root cause confirmed by
piecemeal bisection:

| Step | Content | Result |
|---|---|---|
| 0 | revert | renders |
| 1 | call restored, damping 0 (function returns immediately) | **renders** — wiring fine |
| 2 | same call, damping 0.6, math runs (read-before-write restructure) | **BLANK** |

So: mutating element positions inside the `layoutstop` handler while the canvas is
still settling is fatal in a live renderer and invisible headless. **Lesson: the
headless probe validates geometry, not render-pipeline integration. Anything that
mutates positions or touches the render path needs a browser refresh check as part
of the change itself, not after.**

The `pullBridgesToRing` code was fully removed from `GraphCanvas.jsx` (v2
read-before-write version included above in history; the function no longer exists
in the file). The probe's mirror remains in `tools/ai_visual_graph_tool/probe.js`
for reference.

**The NEW DESIGN that supersedes all of this — see §9.**

---

## 0a. 2026-11-20 — the headless measurement module (BUILT)

Built as `tools/ai_visual_graph_tool/` (probe.js + run.py + baseline.json + README).
**Working instrument.** Runs cytoscape + fcose headless in Node (vendored UMDs loaded
in one shared vm context, script-tag order, browser-parity), feeds it the real
`graph_slice()` payload via the library directly, replicates the canvas pipeline
(bag construction, fcose with theme physics, `placeBagsOnRing`, no fit), and prints:

- edge lengths sorted, typed `WITH`/`POSSIBLY`, classified bag-bag / bag-bridge /
  bridge-bridge — the §6 confirmation test as numbers;
- ring radius computed, per bag centre before → after the ring move;
- bridges: distance to each bag they connect to vs that bag's reach;
- per-bag spread and overlap.

**Baseline (`baseline.json`)** = owner's live slider positions, transcribed from
screenshots (browser localStorage is invisible to outside processes — screenshots
are the transport). Deep-merged over `theme.js` defaults so only keys the owner
moved appear. `--stock` skips it; `--save-baseline` freezes the effective theme;
`--set group.key=value` overrides for one run; `--runs N` medians the randomized
layout. `--no-api` falls back to `last_payload.json` when the store is unreadable.

Vendored-UMD load recipe (cost real time — record): all four bundles must load into
**one shared vm context** in script order (`layout-base` → `cose-base` →
`cytoscape-fcose`), with `window`/`global`/`self` pointing at it and **no
`module`/`exports`/`define`** (those steer the UMD to CommonJS/AMD branches whose
inner `require` cannot resolve). Per-file contexts break the external-module
handoff and cose-base crashes on `undefined.prototype`.

**Known limitation (2026-11-21):** the probe validated the bridge-pull geometry
while the browser blanked — it cannot see render-pipeline breakage. It is the gate
for *geometry* claims only.

---

## 0b. 2026-11-20 — WHY: screenshots cannot carry tuning state

Recorded as the problem statement for §0a (kept for the record; the module exists
now). The owner moves sliders in the UI, screenshots the canvas, and the IDE agent
eyeballs the result — but the agent cannot read the saved slider values, and "looks
long" is not a measurement. Slider state lives in browser localStorage
(`relate.graphStyle`), which no outside process can read. A future `GET/POST
/api/theme` route would let the agent read/write live settings over HTTP; discussed,
**not built** — parked until needed again.

---

## 1. What is built

| Piece | Where | State |
|---|---|---|
| One invisible bag per platform | `GraphCanvas.jsx` element memo | **done** |
| Bag membership = `:Merged`, inverted | `GraphCanvas.jsx` | **done** |
| Bags pinned to a ring, post-layout | `placeBagsOnRing()` | **done** |
| Labels counted in the layout box | `theme.physics.nodeDimensionsIncludeLabels` | **done** |
| `merged` flag on the API | `tools.py` `_NODE_QUERIES["Correspondent"]` | **done** |
| `POSSIBLY` edges drawn, dashed | `tools.py` `DRAWABLE_EDGE_TYPES` | **done** |

Measured on the live store: **248 nodes, 166 edges, 7 bags, 214 bagged nodes, 34
bridges** (merged Correspondents outside every bag).

Live theme values (`app/ui/src/config/theme.js`, `THEME_VERSION = 9`):

```
physics.idealEdgeLength        22      (was 60)
physics.smartEdgeLength        false   (was implicitly true)
physics.gravityCompound        1.0
physics.gravityRangeCompound   1.5
physics.nodeDimensionsIncludeLabels  true
layout.bagRing                 true
layout.bagRingSpread           1.0     (was 1.35)
```

---

## 2. The design, in one paragraph

Each platform is a **bag**: an invisible compound parent whose only job is to give
fcose a body to solve around. A node goes in a bag **if and only if it is not
`:Merged`** — the label, not `platforms.length`, because a Place mentioned on two
platforms is `:Merged` and must stay outside. Threads are trivially single-platform so
they are trivially bagged. Merged nodes stay outside and are pulled by their real
edges toward every bag they touch, which is what puts them in the middle. The bags are
then moved onto a circle so the pulls point inward from all sides.

**The leash was retracted.** The owner withdrew "pull a merged node toward the platform
it messages most on" in favour of **equal pull from every platform**. Equal pull is
fcose's default for a node outside every bag, so the leash would have broken the
requirement. `primaryPlatform` / `dominance` remain on the API as honest data but are
**not a layout input**. Do not add the leash back without asking.

---

## 3. Traps that cost real time — do not repeat these

**Never put a bag in a `fixedNodeConstraint`.** This broke the app completely: blank
canvas, stalled refresh. `spectralLayout` builds its `nodeIndexes` map with
`if (!nodes[i].isParent())` (`cytoscape-fcose.js:1313`), so a compound is never in it.
The constraint handler reads `xCoords[nodeIndexes.get(bagId)]` → `undefined`, and the
Procrustes transform turns **every** coordinate into `NaN`. The ring is a post-layout
translation instead.

**The bag style rule must be LAST in the stylesheet array.** Cytoscape applies blocks
in order. Placed first, the base `node` rule wins: `background-opacity: 0.92` plus
`background-color: data(color)`, and a bag carries no `color`, so `data(color)` falls
back to Cytoscape's default grey. That rendered as grey boxes around every platform.

**Never `display: "none"` on a bag.** Hiding a parent hides its children and breaks the
compound relationship. Invisibility is `background-opacity: 0`.

**`events: "no"` is what makes a bag non-clickable.** `selectable: false` alone still
lets it swallow taps on its padding.

**Bags are synthetic.** `cy.nodes().length` includes them. The reveal, `onLayoutDone`
and every count filter `.synthetic`.

---

## 4. What the vendored fcose source actually says

Checked against `app/static/vendor/`, not assumed. Several of these contradict the
sliders' own hints.

| Knob | Reality |
|---|---|
| `gravity`, `gravityCompound` | Only act on a graph fcose considers **disconnected** (`cose-base.js` `calculateNodesToApplyGravitationTo`). On a fully wired store they are **mostly inert**. Not the lever for clustering. |
| `nodeSeparation` | Scales the **initial spectral BFS distances only** (`cytoscape-fcose.js:1119`). It does **not** space the settled layout. The old hint claimed otherwise and wasted time. |
| `packComponents` | Gated on `cy.layoutUtilities`, a separate plugin that is **not vendored**. Always a no-op here. |
| `useSmartIdealEdgeLengthCalculation` | Adds `sizeOfSourceInLca + sizeOfTargetInLca - 2*40` to every edge crossing a compound boundary (`layout-base.js:3433`). Those sizes are the **bags'** estimated sizes. |
| `fixedNodeConstraint` | Honoured, but **fatal on a compound** — see §3. |

`layoutBase` / `coseBase` publish themselves on `window` (UMD), so the constants are
reachable from the page. `setSmartEdgeLength()` uses that to flip
`DEFAULT_USE_SMART_IDEAL_EDGE_LENGTH_CALCULATION` on both before `cy.layout()` runs.
Verified in a sandbox: both objects are settable and `coseBase` sees the change.

---

## 5. Everything tried on edge length — and what it did

| Attempt | Result |
|---|---|
| `idealEdgeLength` 60 → 22 | **No visible change.** |
| `smartEdgeLength: false` | **No visible change.** |
| `bagRingSpread` 1.35 → 1.0 | Slightly tighter ring. |
| `gravityCompound` / `gravityRangeCompound` sliders | No effect — see §4, they need a disconnected graph. |
| `nodeSeparation` slider | No effect on the settled layout — see §4. |
| `packComponents` | No effect — plugin not vendored. |

**Six levers, none of them moved the long edges.** That is the important finding: the
long edges are almost certainly **not** a force-layout parameter at all.

---

## 9. THE FORWARD PLAN — 2026-11-21: the merged bag (owner's design)

**Owner's framing, which cuts through the failed post-hoc approaches:** the merged
nodes should become **their own bag** — a proper compound parent, `bag:merged` —
and that bag gets **centered**, the way the other bags get ringed. "Merged nodes
have to become a thing / their own meta product — org, etc, coming also — that
would have their own BAG, then the bag gets centered, compared to the others.
Shouldn't be tough."

Why this supersedes the bridge-pull (§0 revert table): the bridge pull was a
post-hoc *node mover* fighting the ring translation after the solver — and it was
the thing that blanked the canvas. The merged bag instead **gives the solver a
body to place itself**: one more compound in the elements memo, placed by the same
proven `placeBagsOnRing()` translation (special slot: center, radius ≈ 0) rather
than any new post-layout step. No new timing code, no re-entrancy suspect — it
reuses the only post-layout pathway already known to work.

**Design sketch (piecemeal, each step a separate build + reload, confirmed before
the next — per the §0 lesson):**

| Step | Change | Risk |
|---|---|---|
| A | Elements memo: nodes that are `merged` (or otherwise outside every platform bag) get `parent: "bag:merged"`; the bag is created in the same pass (never a separate step — §3). No ring placement yet. | low — pure memo change |
| B | `placeBagsOnRing()`: place `bag:merged` at the CENTER (radius 0, its own angle slot), the seven platform bags on the ring around it. Same batch discipline as the existing ring code. | the load-bearing step |
| C | Styling: the merged bag gets a soft translucent fill (a visible loose blob), unlike the invisible platform bags (`background-opacity: 0`). Rule stays LAST in the stylesheet (§3). | cosmetic |
| D | Probe mirror: bag construction + ring slot update; measure 8-bag geometry vs 7. | measurement only |

**Consequences if built:**

- Bag-bridge edges become **short by construction** — the merged bag sits at the
  center, and its nodes are pulled toward it by the solver itself, not translated
  after the fact. The long-edge problem (§6) dissolves rather than gets patched.
- §7 amendment required: "merged nodes stay outside every bag" was written when
  bags were solver bodies only. Under the new design the merged set IS a bag — its
  own body, not an orphan population. The `:Merged` flag keeps its meaning
  (membership test inverted per-bag); what changes is that the merged set now has
  its own compound.
- Compound-gravity math changes (8 compounds, not 7 + orphans). The probe
  quantifies this in one run before the UI gets the change.
- Future-proofing (owner's point): entity kinds (Person/Organization/Place/Product)
  arriving from body-extraction will follow the same pattern — their own bags,
  their own placement slots — so the ring becomes a **two-tier composition**:
  platform bags outside, entity bags inside, at center. The merged bag is the
  first instance of that second tier.

**Status: NOT BUILT. Next work item. Piecemeal protocol applies.**

---

## 10. Data hygiene note (cached from the probe, 2026-11-21)

Two long-edge outliers are **data, not physics** — `POSSIBLY` fuzzy pairs between
spelling variants of the same person that aliasing did not fold:

- `person:dimitri whitfield` ↔ `person:dimitir whitfield` (329px probe max)
- `person:sahfi hassan` ↔ `person:shafi hassan` (264px)

Each variant sits in a different platform bag, so the unfocold pair stretches an
edge across the ring. Fix lives in `relate_comms/link.py` (fold rules / nickname
forms), not in layout. The probe will keep flagging these until folded; that is
the instrument working, not the graph regressing.

---

## 7. Settled decisions

| Decision | Ruling |
|---|---|
| Bag membership test | **Not `:Merged`.** The label, not the `platforms` array. **(Amended by §9: the merged set becomes its own bag.)** |
| Single-platform Correspondents | **In the bag.** Same rule as Threads; no special case. |
| `platform` | **Unchanged** — first by date. Never redefined as dominant. |
| `primaryPlatform` / `dominance` | On the API, **not a layout input**. The leash was retracted. |
| Bags / ring | **Client-side only**, marked `synthetic`, excluded from every count and the reveal. |
| Bags are invisible bodies | `background-opacity: 0` + `events: "no"` + `z-compound-depth: "bottom"`; **never** `display: none`. **(§9 adds one exception: the merged bag gets a soft visible fill.)** |
| Bag construction | In the child-filtering pass, never a separate step — fcose throws on a parentless child. |
| Naming | `type: "Bag"` in code and selectors; prose says "bag". |
| Ring mechanism | **Post-layout translation**, never `fixedNodeConstraint`. |
| Post-layout mutation of node positions | **DANGEROUS — see §0 revert table.** The bridge-pull blanked live canvases while passing headless. Any future post-layout step must reuse the proven `placeBagsOnRing` translation pattern, and anything new gets the piecemeal build+reload protocol. |
| Slider-range widening | Safe (UI metadata only; no `THEME_VERSION` bump needed unless a default changes). Defensively clamp `gravityCompound` off 0 and `idealEdgeLength` above 2 at consumption time if it ever recurs. |

---

## 8. Files

| File | What it holds |
|---|---|
| `app/ui/src/config/theme.js` | `physics.*`, `layout.bagRing`, `layout.bagRingSpread`, `filter.bags` |
| `app/ui/src/components/GraphCanvas.jsx` | `placeBagsOnRing()`, `setSmartEdgeLength()`, bag construction, bag stylesheet rule (last) |
| `app/ui/src/components/modals/CanvasModal.jsx` | Styling sliders, including the ring and smart-edge-length toggles |
| `relate_comms/tools.py` | `merged` flag, `POSSIBLY` in `DRAWABLE_EDGE_TYPES` |
