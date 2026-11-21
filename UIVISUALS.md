# UIVISUALS.md

**Settled UI and visual facts.** Not a log, not a plan — only what has been built, seen in a
browser, and would cost real time to rediscover. Anything still being tuned lives in
[`CytoGravityRecommend.md`](CytoGravityRecommend.md) until it stops moving.

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

**`[key]` selectors test field existence, not truthiness.** `node[image]` matches every node
with an `image` field even when the value is `null`. Use a class.

---

## 7. The merged-node template

The pattern for any node that belongs to more than one platform. Built for merged
Correspondents; **Person / Place / Organization / Product reuse it** when body-entity
extraction lands, with their own glyph and a yellow glow.

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

**Future kinds:** same shape, `mergedGlowColor` swapped to yellow. The theme keys are
`visual.mergedGlow*` — they are not Correspondent-specific.

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

Layout mechanics — the ring, `fixedNodeConstraint`, and what fcose actually honours — stay in
[`CytoGravityRecommend.md`](CytoGravityRecommend.md) until that work is finished.

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
