# CytoGravityRecommend.md

**Status: OPEN — edges are still far too long.** Everything else in this document is
built and settled. The one unresolved problem is §6, and it is the reason this file
still exists.

Read §6 first if you are picking this up cold.

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

## 6. THE OPEN PROBLEM — edges still far too long

**Symptom.** The graph renders and the bags are invisible and correctly ringed, but the
edges are enormously long, so the whole picture is spread out and unreadable. Reducing
`idealEdgeLength` by ~60% and disabling smart edge length changed nothing perceptible.

**Leading hypothesis — the ring translation is the cause, not fcose.**

`placeBagsOnRing()` runs *after* the solver. It moves each bag's children so the bag's
centroid lands on a circle of radius `max(widest * 1.6, 260) * spread`. With seven bags
each a few hundred px across, that radius is plausibly **500–800px**.

Merged nodes are **not moved**. So if the solver left a bridge near its bag and the ring
then moves that bag to the far side of the circle, the edge from the bridge to the bag
becomes roughly `2 × radius` — **1000–1600px**. No fcose parameter can shorten that,
because the length was created after the layout finished. This is consistent with all
six failed attempts in §5.

**Things to check first, in order:**

1. **Measure it.** In the browser console:
   ```js
   const cy = document.querySelector('#cy')._cyreg.cy;   // or the canvas ref
   cy.edges().map(e => e.data('type') + ' ' + Math.round(e.length())).sort()
   ```
   If the longest edges are `WITH` edges whose target is a bagged node and whose source
   is a merged node, the hypothesis is confirmed.
2. **Test with the ring off.** Set `layout.bagRing: false` and rebuild. If the long
   edges disappear, the ring is definitively the cause. This is the single most
   informative experiment and it has not been run.
3. **If confirmed**, the fix is to stop translating bags and instead **place the
   bridges relative to the ring** — e.g. after the ring is applied, move each merged
   node to the centroid of the bags it connects to (weighted by edge count), then let a
   short relaxation settle it. That keeps the ring and removes the long edges.

**Alternative hypothesis, if (2) shows the edges are long with the ring off:** the
solver is genuinely placing bridges far from their bags, and the cause is that a merged
node has no compound parent so nothing holds it near anything. In that case the answer
is a *soft* anchor — but note the leash was retracted, so any anchor must pull
**equally** toward all of a node's platforms, not toward a dominant one.

**Do not** re-try `idealEdgeLength`, `smartEdgeLength`, `gravityCompound`,
`nodeSeparation` or `packComponents` as the fix. All five are ruled out in §5.

---

## 7. Settled decisions

| Decision | Ruling |
|---|---|
| Bag membership test | **Not `:Merged`.** The label, not the `platforms` array. |
| Single-platform Correspondents | **In the bag.** Same rule as Threads; no special case. |
| `platform` | **Unchanged** — first by date. Never redefined as dominant. |
| `primaryPlatform` / `dominance` | On the API, **not a layout input**. The leash was retracted. |
| Bags / ring | **Client-side only**, marked `synthetic`, excluded from every count and the reveal. |
| Bags are invisible bodies | `background-opacity: 0` + `events: "no"` + `z-compound-depth: "bottom"`; **never** `display: none`. |
| Bag construction | In the child-filtering pass, never a separate step — fcose throws on a parentless child. |
| Naming | `type: "Bag"` in code and selectors; prose says "bag". |
| Ring mechanism | **Post-layout translation**, never `fixedNodeConstraint`. |

---

## 8. Files

| File | What it holds |
|---|---|
| `app/ui/src/config/theme.js` | `physics.*`, `layout.bagRing`, `layout.bagRingSpread`, `filter.bags` |
| `app/ui/src/components/GraphCanvas.jsx` | `placeBagsOnRing()`, `setSmartEdgeLength()`, bag construction, bag stylesheet rule (last) |
| `app/ui/src/components/modals/CanvasModal.jsx` | Styling sliders, including the ring and smart-edge-length toggles |
| `relate_comms/tools.py` | `merged` flag, `POSSIBLY` in `DRAWABLE_EDGE_TYPES` |
