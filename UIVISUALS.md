# UIVISUALS.md

**Settled UI and visual facts.** Not a log, not a plan — only what has been built, seen in a
browser, and would cost real time to rediscover.

Backend reference: [`TECHREADME.md`](TECHREADME.md). What is next: [`HANDOVER.md`](HANDOVER.md).

---

## 0. The one rule that explains most of this file

**Cytoscape 3.35.0 is not the Cytoscape most examples describe.** The renderer was rewritten
for WebGL and several long-standing style properties were removed outright. A removed
property does not warn — it is parsed, ignored, and the graph renders without it. Every trap
below is a case of that.

Verify against the shipped bundle, never against documentation or memory:

```bash
grep -c "shadow-blur" node_modules/cytoscape/dist/cytoscape.umd.js   # 0
```

---

## 1. Glows: `underlay-*`, never `shadow-*`

**`shadow-*` does not exist in 3.35.0.** The bundle contains no `shadow-blur`,
`shadowBlur`, `shadow-color` or `shadow-opacity`. Every glow written with them — the
correspondent glow, the selection glow, the first merged-node halo — was a silent no-op.

The replacement is **`underlay-*`**: a shape drawn *behind* the node body.

| Property | Meaning |
|---|---|
| `underlay-shape` | `ellipse`, `round-rectangle`, … |
| `underlay-color` | fill, when `underlay-fill: solid` |
| `underlay-opacity` | 0–1; **0 disables the layer entirely** |
| `underlay-padding` | px the shape extends beyond the node body |
| `underlay-fill` | `solid` \| `linear-gradient` \| `radial-gradient` |
| `underlay-gradient-stop-colors` | one colour per stop |
| `underlay-gradient-stop-positions` | one percentage per stop |

**An underlay has no blur.** A soft glow is a radial gradient whose stops reach zero alpha
at the outer edge — see §2.

**`bounds-expansion` is required** on any node whose underlay extends past its body, or the
halo is clipped at the node's own box.

### A halo cannot hide an edge — settled, do not retry

Cytoscape paints **every edge before every node layer**, so a node's halo is always above
the lines. Making the halo opaque does occlude, but it covers the first `mergedGlowPadding`
px of every *connected* edge too (they stop at `outerWidth()`, inside the halo) while doing
nothing for edges passing behind.

The only escape is `z-index-compare: manual` with the connected edges lifted to a higher
`z-index`. That works visually and **breaks node dragging** — an edge above a node swallows
the grab. Both were tried on 2026-11-21 and reverted.

**There is no stylesheet value that hides a passing edge behind a node.** If this is ever
needed, it is a renderer change, not a style change.

---

## 2. Radial gradient geometry — the hard rim

The gradient radius is `max(paddedWidth, paddedHeight)`, i.e. the node **plus its padding**.
So `100%` is the outer edge of the halo, not the node's edge.

**A stop list that holds full opacity and then drops to zero produces a solid disc with a
crisp outer circle.** The taper has to run across the whole radius:

```js
"underlay-gradient-stop-colors": [
  "rgba(217,122,43,0.5)",
  "rgba(217,122,43,0.28)",
  "rgba(217,122,43,0.09)",
  "rgba(217,122,43,0)",
],
"underlay-gradient-stop-positions": ["0%", "45%", "75%", "100%"],
```

---

## 3. Colour parsing — 8-digit hex blanks the whole app

Cytoscape's `hex2tuple` accepts **3 and 6 digits only**. An 8-digit value such as
`#d97a2b00` parses to `null`; the multi-value branch in `parseImpl` then reads `.value` off
that null and throws.

The throw happens while the stylesheet is being constructed, so **the entire app goes
black** — not just the offending node — and the stack trace points at `cytoscape.min.js`,
not at our code.

**Use `rgba(217,122,43,0)` for a transparent stop.**

This is the same failure class as `background-image: data(x)` with an empty string: a style
value that fails to parse takes the whole stylesheet with it.

---

## 4. Node `opacity` fades the glyph

A background image is drawn at `background-image-opacity × node.effectiveOpacity()`. Setting
`opacity` on a node therefore fades its SVG too — a near-black silhouette comes out washed
grey, which reads as "the glyph is behind the node" when it is not.

**Fade the halo, not the node.** Use `underlay-opacity` and the gradient stops. If the body
itself must be ghosted, use `background-opacity`, which does not touch the image.

---

## 5. Stylesheet order is load-bearing

Cytoscape applies blocks in order and **equal specificity means the later block wins**. Two
consequences, both of which have already caused bugs:

| Rule | Must be | Why |
|---|---|---|
| `node[type = "Bag"]` | **last** | The base `node` rule sets `background-opacity: 0.92` and `background-color: data(color)`. A bag carries no `color`, so `data(color)` falls back to grey — that is how the first version rendered grey boxes around every platform. |
| `node.icon.person.merged` | **after** the per-platform person rules | A merged node still carries a real `platform` value, so it matches its own platform's rule too. Placed first, the platform rule wins and the glyph stays its platform colour. |

---

## 6. Icons

**Icons are an override layer, never the base.** The base `node` rule is a filled circle; a
node whose platform has no icon file matches no icon rule and stays a visible circle. Making
icons the base would leave an unknown platform drawing as nothing.

**Applied as static per-platform rules, never a data map.** `background-image: data(x)`
throws on an empty string and defeats the renderer's image cache.

**A glyph cannot be tinted at runtime.** Each colour is a separate file. `PERSON_ICONS` holds
one per platform colour, plus `merged` — the neutral grey glyph used by any Correspondent
that spans several platforms.

**Icon URLs carry no version stamp.** Replacing glyph artwork is picked up by a hard refresh
alone. The protection lives on the server: `app/main.py`'s `IconsElsewhere` mount sends
`Cache-Control: no-cache` for `/static/icons/*`, so the browser always revalidates and the
`ETag` answers 304 when nothing changed. That is one conditional request per icon, no
re-download, and **nothing in the UI to remember**. The bundle and vendored files keep the
default caching — they change only on `npm run build`, and `/` is already `no-store`.

**`theme.js` needs no mechanism at all.** Only the user's overrides are stored
(`relate.graphStyle.overrides`), as a diff against the defaults, so a key nobody touched
always follows the file after a rebuild + refresh. There is no theme version and there must
not be one — see `theme.js`'s own note.

**`[key]` selectors test field existence, not truthiness.** `node[image]` matches every node
with an `image` field even when the value is `null`. Use a class.

---

## 7. The merged-node template

The pattern for any node that belongs to more than one platform. Built for merged
Correspondents; **Person / Place / Organization / Product reuse it** when body-entity
extraction lands, with their own glyph and their own glow colour.

| Layer | Value | Note |
|---|---|---|
| Glyph | `person-merged.svg`, `#8a97a8` | Neutral grey. Any platform hue would be a lie about which platform it belongs to. |
| Class | `merged` | Added in the elements memo, alongside the `merged` data field. |
| Halo | radial `underlay`, orange `#d97a2b` | §2 for the stops. |
| Node `opacity` | **none** | §4 — it would fade the glyph. |
| Border | `0` | The glyph is the mark; a ring around it reads as a second outline. |

The class is added in `GraphCanvas.jsx`'s elements memo:

```js
const classes = [kind, glyph ? "icon" : null, node.merged ? "merged" : null]
  .filter(Boolean).join(" ");
```

**Kinds and their halo.** The halo shape is shared; the colour is per kind, declared as
`mergedGlowColor` in `NODE_TYPES` and applied by a later `node.merged[type = …]` block.
A kind with **no** `mergedGlowColor` falls through to the base `node.merged` rule and
glows **orange** — so every extracted kind must declare one, or it borrows the
Correspondent bridge signal it is supposed to be weaker than.

| Kind | `mergedGlowColor` | Claim it makes |
|---|---|---|
| Correspondent | `#d97a2b` (orange, the theme default) | one person, several platforms — a verified fold |
| Place | `#c9a227` (yellow) | same canonical spelling on two platforms |
| Organization | `#b8912a` (dark yellow) | same, by name |
| Product | `#b8912a` (dark yellow) | same, by name |
| Person (extracted) | `#8a97a8` (grey) | the closest of the four to a person, still not orange |

The theme keys are `visual.mergedGlow*` — they are not Correspondent-specific. The
per-kind `underlay-gradient-stop-colors` are derived from that kind's hex by
`mergedStopsFor()`, so the ramp always tapers to a transparent stop of its own hue.

---

## 8. Bags

A bag is an invisible compound parent that gives fcose a body to solve around. It is
`synthetic`: not data, not counted, not clickable.

| Trap | Rule |
|---|---|
| Hiding a bag | **Never `display: none`** — that hides its children and breaks the compound relationship. Invisibility is `background-opacity: 0`. |
| Click-through | `events: "no"`. `selectable: false` alone still lets the bag swallow taps on its padding. |
| Stacking | `z-compound-depth: "bottom"`. `z-index` alone does not put it behind its children. |
| Sizing | `padding` + `compound-sizing-wrt-labels: "exclude"`, so the body tracks the children's real geometry. |
| Counting | `cy.nodes().length` includes bags. Every count filters `.synthetic`. |

**Two tiers.** Platform bags sit on a ring; the merged bag sits at the centre. Membership is
`:Merged` inverted — a node with exactly one platform goes in that platform's bag, everything
else goes in the merged bag. The test reads the **label**, not `platforms.length`: a Place
mentioned on two platforms is `:Merged` and must not be bagged by a platform.

**The centre is applied explicitly, and that is load-bearing.** `placeBagsOnRing()` excludes
the merged bag from the ring and then moves it to the **origin**, inside the circle the
platform bags form, with the ring radius offset by the merged bag's own radius so the two
tiers never overlap. Until 2026-11-22 only the exclusion was written — the centring was
assumed to happen "by its own rule" and did not exist, so the merged bag stayed wherever
fcose left it and usually ended up *outside* the ring. Verified by driving the function with
a stubbed graph: merged at `(0,0)`, all platform bags at one equal radius.

**One rule, every kind.** There is no entity-specific bag. A place seen only on Telegram
sits in the Telegram bag beside the threads that mention it; a place on four platforms sits
at the centre. The same applies to `Person`, `Organization` and `Product` when they are drawn
— nothing needs changing for them, because the rule keys on `merged` and the platform count,
never on the node kind.

Layout mechanics — the ring, `fixedNodeConstraint`, and what fcose actually honours — are in
§12 below.

---

## 9. Selection

The selection halo works and is **not** a glow: `border-width: 3` in white plus a doubled
blur. It survived the `shadow-*` removal because the border is what carries it.

Selection cannot also be a glow, because Correspondents glow permanently — the two would be
indistinguishable.

---

## 10. Where the values live

| File | Holds |
|---|---|
| `app/ui/src/config/theme.js` | Every tunable: `physics.*`, `layout.*`, `visual.*`, `tiers.*`, `filter.*`. Only the user's **overrides** are persisted (`relate.graphStyle.overrides`), as a diff against the defaults. |

### Changing a default: edit, rebuild, hard-refresh

**Only the user's overrides are persisted** (`relate.graphStyle.overrides`), stored as a
diff against the defaults. A key the user never touched is not in storage, so it always
follows `theme.js`. No version constant, no manual clearing.

**The rebuild is unavoidable:** `theme.js` is compiled into `app/static/dist/app.js`, so
the browser cannot see an edit until esbuild runs. `npm run watch` does it on save;
otherwise `npm run build`. `start.bat` rebuilds on every launch.

Full checklist: [`TECHREADME.md`](TECHREADME.md) §7.
| `app/ui/src/config/nodeTypes.js` | `NODE_TYPES` (the single declaration of a kind), platform colours, `PLATFORM_ICONS`, `PERSON_ICONS`, `nodeIcon()`. |
| `app/ui/src/components/GraphCanvas.jsx` | `buildStylesheet()`, the elements memo, `placeBagsOnRing()`. |
| `app/static/icons/` | One SVG per platform colour, plus `person-merged.svg`. |

**A modal edit and a hand edit are the same edit.** Both write `theme.js`'s shape.

---

## 11. Verifying a style change

The browser is the only authority on rendering. A headless Cytoscape can confirm that a
stylesheet *parses* and that selectors *resolve*, which catches §3 and §5 before a reload:

```js
const cy = new Cytoscape({ headless: true, styleEnabled: true, elements: [...] });
cy.style().fromJson([...]).update();
cy.nodes()[0].pstyle("underlay-gradient-stop-colors").value;
```

It cannot tell you whether a glow looks right, and it cannot catch render-pipeline breakage.
Anything that mutates positions or touches the render path needs a browser refresh as part of
the change itself.

---

## 12. Layout — what fcose actually honours

Read from the **vendored** source (`app/static/vendor/`), never from documentation. Several
of these contradict the sliders' own hints, and two cost a full day each before they were
proved.

### The overlap problem, and the pass that fixes it

fcose has an overlap branch — `layout-base.js`'s `calcRepulsionForce` calls
`calcSeparationAmount` when `rectA.intersects(rectB)`. **But the rect comes from
`layoutDimensions()`, which for a leaf node is the BODY box only.** The solver sees a 28px
circle, draws it, and has no idea the glyphs are touching. No slider on earth fixes that:
they all tune a force operating on a box the mark has already escaped.

`declutter()` in `GraphCanvas.jsx` closes the gap. It runs after the solver and before the
fit, and pushes apart overlapping pairs using `boundingBox({ includeLabels: false })` — the
box fcose refuses to measure. Knobs live in `theme.physics.declutter`:
`enabled` / `iterations` (24) / `padding` (4) / `step` (0.6). Set `enabled: false` to revert.
Each pass re-reads the boxes in one `cy.batch()`; convergence is fast because a pass with no
overlaps exits immediately.

### Knobs that do nothing

| Knob | Reality |
|---|---|
| `nodeSeparation` | Scales the **initial spectral BFS distances** only (`cytoscape-fcose.js:1119`). It does not space a settled layout. |
| `packComponents` | Gated on `cy.layoutUtilities`, a plugin that is **not vendored**. Always a no-op here. |
| `nodeOverlap` | Does not exist in fcose. It belongs to core `cose` only. |
| `tile` / `tiling*` | Applies to **zero-degree nodes only** (`cose-base.js:1125-1132`). Threads and Correspondents have `WITH` edges, so it never fires. |
| `uniformNodeDimensions` | Uses rect centres instead of clip points. Cheaper, no clustering effect. |

### Gravity — the eligibility rule nobody expects

`calculateNodesToApplyGravitationTo` (`cose-base.js:885-903`) loops over **every graph**,
including each compound's child graph, and keeps the nodes of any that is internally
disconnected:

```js
graph.updateConnected();
if (!graph.isConnected) nodeList = nodeList.concat(graph.getNodes());
```

So the rule is **per bag, not global**. Measured on the live store: each platform bag's
children form **25–30 separate islands** (a Thread hangs off one Correspondent with nothing
joining it to its neighbours), so every bag qualifies and `gravityCompound` genuinely
engages. It looked inert for months because it was assumed to need a globally disconnected
graph.

`gravityCompound` must **never be 0** — exactly 0 stalls fcose's compound tiling. The slider
floor is 0.05.

### Why spokes sprawl

`layout-base.js:3491` — a node feels repulsion only from nodes within
`2 × (level+1) × idealEdgeLength`. A spoke pushed outward by its one neighbour drifts with
nothing pulling it back. That is the mess inside a platform, and it is why
`gravityCompound` + `gravityRangeCompound` are the levers that actually move it.

| Attempt | Result |
|---|---|
| `idealEdgeLength` 60 → 22 | no visible change |
| `smartEdgeLength: false` | no visible change |
| `bagRingSpread` 1.35 → 1.0 | slightly tighter ring |
| `gravityCompound` / `gravityRangeCompound` | **do work** — per-bag disconnection, see above |
| `nodeRepulsion` | effectively inert |

Useful and verified: `nestingFactor` adds length to every **inter-graph** edge
(`layout-base.js:3426-3440`), so `0` stops cross-bag lengthening. `idealEdgeLength` accepts a
**per-edge function** (`cytoscape-fcose.js:477`), e.g.
`e => e.data('kind') === 'WITH' ? 25 : 60` — but its average also sets
`MIN_REPULSION_DIST`, so it is a coupled knob.

### Traps

**Never put a bag in a `fixedNodeConstraint`.** `spectralLayout` builds `nodeIndexes` with
`if (!nodes[i].isParent())`, so a compound is never in it; the handler reads `undefined` and
the Procrustes transform turns every coordinate into `NaN` — blank canvas. The ring is a
post-layout translation instead.

**Post-layout position mutation is dangerous.** A `pullBridgesToRing()` pass measured correct
headless and **blanked the canvas in the browser** (reproduced on a clean profile). The
headless probe validates geometry, not render-pipeline integration. Anything that moves
nodes needs a browser refresh as part of the change.

**The measurement probe** lives in `tools/ai_visual_graph_tool/` (probe.js + run.py +
baseline.json). All four vendored UMDs must load into **one shared vm context** in script
order (`layout-base` → `cose-base` → `cytoscape-fcose`) with `window`/`global`/`self`
pointing at it and **no** `module`/`exports`/`define` — those steer the UMD to a CommonJS
branch whose inner `require` cannot resolve.

### Open data issue

Two `POSSIBLY` fuzzy pairs are **data, not physics**: `person:dimitri whitfield` ↔
`person:dimitir whitfield`, and `person:sahfi hassan` ↔ `person:shafi hassan`. Each variant
sits in a different platform bag, so the unfolded pair stretches an edge across the ring. The
fix belongs in `relate_comms/link.py` fold rules, not in layout.
