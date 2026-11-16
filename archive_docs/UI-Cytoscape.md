# UI-Cytoscape.md

**Archived reference.** The UI as built, and every Cytoscape decision behind it. Kept
because the library choice, the label LOD mechanism and the fcose parameters are hard-won
and easy to get wrong again.

Live docs: [`../README.md`](../README.md) · [`../TECHREADME.md`](../TECHREADME.md) ·
[`../HANDOVER.md`](../HANDOVER.md).

---

## 1. What the UI is now

Three columns, full height, all controls in the title bar.

```
┌──────────────────────────────────────────────────────────────────────┐
│ ● OFFLINE · nothing leaves this machine                              │
│ [Search……] [Cypher]   [AI] [Log] [Ingest] [Setup] [Style] [⚙] [○][◈] │
├──────────────┬───────────────────────────────┬───────────────────────┤
│   AI CHAT    │       GRAPH CANVAS            │       VIEWER          │
│   25vw       │       flex: 1                 │       25vw            │
│   ⛶ → 40vw   │       threads + corrs         │       ⛶ → 40vw        │
└──────────────┴───────────────────────────────┴───────────────────────┘
```

| Control | Does |
|---|---|
| Search box | substring search, or raw Cypher when the chip is toggled |
| `AI` | toggles the left chat panel |
| `Log` | evidence modal — counts, withheld aliases, non-text kinds, types |
| `Ingest` | drop zone + per-platform instructions + report |
| `Setup` | what this is, where data lives, what leaves the machine |
| `Style` | Graph Style modal — physics, labels, tiers, visual |
| `⚙` (icon only) | Utilities — which **sources** are on |
| `○` / `◈` | node style: shaded circles vs source icons |

**Stack:** React 19 + esbuild. `app/static/dist/app.js` is **committed**, so a clone runs
without npm. Cytoscape and fcose are vendored as plain scripts in `app/static/vendor/`
(not bundled — they change only on upgrade, and bundling them would rebuild 500 KB on
every save during `npm run watch`).

**No extra server.** esbuild is a compiler, not a server. `python -m app` on `:8100` is the
only process that listens.

---

## 2. Why Cytoscape + fcose, 2D

| Factor | Cytoscape + fcose | sigma.js v4 |
|---|---|---|
| Zoom-tier labels | **native** — `min-zoomed-font-size` | native — `labelRenderedSizeThreshold` |
| Label collision at mid-zoom | no | **yes** — grid declutter |
| Renderer | **Canvas 2D (CPU)** | WebGL (GPU) |
| **No GPU on this box** | **native fit** | software rasteriser |
| Packages | 1 + 1 extension | 4–5 |
| npm / build / watch | **none** for the library | required |
| Styling | **declarative stylesheet** | imperative reducers |

Sigma's two advantages — WebGL throughput and label-grid declutter — only pay off at tens
of thousands of nodes **with a real GPU**. This machine has integrated graphics only, and
the canvas draws 955 threads, not 12,499 messages.

**2D, not 3D:** 3D wins the first five seconds and loses the next sixty — occlusion,
unreadable labels, node-hunting. A judge has to click a thread and understand it.

**Rejected:** `Juggl` (GPL-3, Obsidian-only), `@cosmograph/react` (CC-BY-NC),
`vis-network` (dated, 84 MB, no label LOD), `3d-force-graph` (readability),
Cypress/G6/ECharts (enterprise-dashboard look).

---

## 3. Thread-first

The canvas draws **Thread and Correspondent nodes only** — 1,546 of them. Message nodes are
not drawn and are not meant to be: 12,499 is not drawable, 955 is. This is a rendering
decision; the store still holds every message and agents still see all of them.

---

## 4. fcose parameters

Measured in the author's other app at ~1.5k nodes.

| Param | Value | Note |
|---|---|---|
| `nodeRepulsion` | 20000 | 8000 = tight, 40000 = airy |
| `idealEdgeLength` | 60 | 40 = dense, 120 = sparse |
| `gravity` | 0.2 | 0 = drifts apart, 0.5 = a ball |
| `nodeSeparation` | 75 | **between disconnected components only** |
| `numIter` | 2500 | 1000 = fast and messy, 5000 = settled |
| `randomize` | **true** | **mandatory** — elements are re-added on every filter change and fresh nodes all start at (0,0), so without it the layout has no spread and clicks land on the wrong node |
| `zoomDistance` | 1.8 | multiplies the post-layout fit zoom; `fit: true` shrinks until everything is visible, which at this node count puts neighbours closer than a node's own diameter |
| `wheelSensitivity` | **3.8** | default 1.0 is genuinely slow — measured 1.047× per notch vs 1.181× for d3-force |

**fcose must be registered before use:** `cytoscape.use(window.cytoscapeFcose)`. The vendored
UMD bundle publishes itself on `window` and depends on `layout-base` and `cose-base`, which
must be loaded first.

---

## 5. Labels — a zoom reward

**The requirement:** zoomed out, no labels. Zoom in, labels fade in depending on node size.
The user must never hover or click a node just to read its name.

**The mechanism:** `min-zoomed-font-size` skips text rendering when
`font-size × zoom` falls below the threshold. Threads get a font size from their tier, so
big threads cross the threshold at a lower zoom than small ones. That *is* the LOD — no
hover handlers, no collision testing.

| Property | Value | What it does |
|---|---|---|
| `min-zoomed-font-size` | 13 | raise to 16 if mid-zoom is crowded |
| `text-wrap` | `wrap` | multi-line labels |
| `text-max-width` | 120px | with `wrap` |
| `text-valign` | `bottom` | label sits under the node |

**Threads carry two lines:** `TELEGRAM` then the title. Cytoscape allows **one label and one
style**, so both lines share a font — the hierarchy comes from uppercasing the source and
putting it first. The title is whatever `writer.thread_display_title()` produced, which is
already guaranteed non-empty. Truncation happens upstream so the graph and the Viewer agree.

---

## 6. Size tiers

**Six rungs, one shared ladder.** Rung 1 is the biggest thread *and* the biggest
correspondent; rung 2 the next of each. A thread is matched on message count, a
correspondent on thread count — the two quantities are not comparable, so each rung carries
both thresholds.

| Rung | Size | Thread ≥ msgs | Corr ≥ threads |
|---|---|---|---|
| 1 | 46 | 200 | 20 |
| 2 | 38 | 80 | 8 |
| 3 | 31 | 30 | 4 |
| 4 | 25 | 12 | 2 |
| 5 | 20 | 4 | 1 |
| 6 | 15 | 0 | 0 |

**Why static tiers, not continuous scaling:** the distribution is brutally skewed — 707
messages in the largest thread, and 565 of 591 correspondents have exactly one thread.
Continuous scaling produces one giant dot and a dust cloud.

**Edges get three tiers**, keyed on the source thread's message count (2.2 / 1.4 / 0.8 px,
0.3 / 0.2 / 0.12 opacity). `WITH` carries no weight property, so the thread's own size is
the only honest signal.

---

## 7. Colour

One hue per platform, then a **deterministic lightness jitter** per node derived from an
FNV-1a hash of its id. A cluster reads as a family of related tones, individual nodes stay
distinguishable, and the picture is identical on every load.

| Platform | Colour |
|---|---|
| messenger | `#3b6fd4` medium blue |
| telegram | `#5cc8f0` light blue |
| whatsapp | `#4caf50` green |
| linkedin | `#3fb6b0` aqua |
| email | `#d9534f` red |
| sms | `#b8912a` dark yellow |

**Correspondents glow permanently** in their own source colour (`shadow-*`, 14px, 0.55), so
they read as a different class of thing against the threads. Because of that, **selection
cannot also be a glow** — it is a 3px white border plus a doubled blur.

---

## 8. Source icons

Six SVGs in `app/static/icons/`, solid silhouettes recoloured to the platform colour and
normalised to a 24×24 viewBox. Toggled by `visual.nodeIcons` (title-bar `○`/`◈` buttons).

**Threads only.** Correspondents keep their glowing rounded rects, so the two kinds never
look alike.

**Applied as static per-platform style rules**, not a data map:

```js
...Object.entries(PLATFORM_ICONS).map(([platform, url]) => ({
  selector: `node.icon[platform = "${platform}"]`,
  style: { "background-image": `url("${url}")` },
}))
```

Two bugs paid for this:

1. **`node[image]` matched every node.** Cytoscape's `[key]` selector tests whether the
   field **exists**, not whether it is truthy — so `image: null` on every node stripped the
   fill and border from the whole graph. Use a **class** instead.
2. **`background-image: data(image)` throws** when the value is an empty string: it parses
   to `null`, then reads `.value` off it. The throw happens during style application, which
   kills the entire render — the graph flashes once and disappears. Static rules avoid it
   and also keep the renderer's image cache effective (six rasterisations, not one per node).

---

## 9. Viewer

Two content states and a Back button, ported from `frontal-lobe`'s Viewer.

| State | Kind | Trigger | Shows |
|---|---|---|---|
| state0 | `results` | search bar, or AI returning hits | a table of results, one row per node |
| state1 | `node` | graph node click, or a result row | that node's meta + content |
| Back | — | Viewer's own button | pure state restore |

**Rules:** consecutive duplicate node clicks are deduped; a re-run of the same search is a
new state; a new action after Back truncates the forward path; the stack is capped at 50 and
persisted to `localStorage` (`relate.viewer.stack`). Only `node` entries survive a reload —
a `results` entry is a snapshot of a query that already ran.

**Thread view:** character-budgeted loads (~1,000 chars, minimum one message), so three
one-sentence replies and one long paragraph both fill the pane once. A thin meta line per
message (`who · when · kind`), a divider between messages, a search box pinned at the top
scoped to that thread, and Newer/Older page steps. Scroll near the bottom loads the next
page. The 707-message thread is the test case and nothing ever renders it in one go.

---

## 10. Halo vs fly-to

| Action | Halo | Fly-to | Viewer state |
|---|---|---|---|
| Click a graph node | ✅ | ❌ | `node` |
| Click a result row | ✅ | ✅ | `node` |
| Back button | ❌ | ❌ | restores |
| AI returns results | ❌ | ❌ | `results` |

**Back never moves the camera. Clicking around must not yank the view.**

In Cytoscape terms: halo = `node:selected`; fly-to =
`cy.animate({ center: { eles: n }, zoom: cy.zoom() * 1.3 }, { duration: 400 })`.
Multiplying the **current** zoom rather than setting an absolute level keeps the motion
proportional wherever the user already is.

---

## 11. Look

| Element | Colour |
|---|---|
| Background | `#05070a`, green lift `#0a1410` |
| Background haze | static radial gradient, **not animated** (CSS gradient animation is expensive on integrated graphics) |
| Buttons | fill `#8a3d12`, text `#d97a2b` |
| Borders | `#1b2a4a`, 1px |
| Objects | `#5c8fd6` at 12–20% opacity |

**Techniques worth keeping:**

1. **Grain overlay** — SVG `feTurbulence` as a static background at 3.5% opacity,
   `mix-blend-mode: overlay`. Rasterises once, near-zero cost. Above ~8% it turns muddy.
2. **Two-tone palette, one accent.** Links near-invisible; nodes carry the colour.
3. **Kill the spring.** fcose settles once; do not re-run the layout on every interaction.
4. **Curved, low-opacity edges** — straight lines on dark read as a wireframe.
5. **Timeline reveal** — nodes bloom outward in `ts_utc` order over ~2.5 s, in ~14 style
   batches rather than a per-frame animation.

**Typography:** Inter at 12–13px for dense panes, 11px meta with `tabular-nums` for
timestamps. Radii 8–12px. Borders at `rgb(255 255 255 / .06–.09)`.

---

## 12. Config

**Every tunable is in `app/ui/src/config/theme.js`**, one object, each value commented with
its sane range. The Graph Style modal writes to it and it persists to `localStorage`
(`relate.graphStyle`). A modal edit and a hand edit are the same edit.

---

## 13. Gotchas

- Selector grammar needs **spaces around operators**: `node[type = "entity"]`, not
  `node[type="entity"]`.
- `wheelSensitivity` defaults to 1.0 and is too slow — set 3.8.
- `[key]` tests field **existence**, not truthiness. Use classes for conditional styling.
- `background-image: data(x)` throws on an empty string and kills the render.
- Cytoscape has **no `box-shadow`**; `shadow-*` is the glow equivalent.
- Cytoscape has **no per-node gravity**. Big threads can only be approximated as anchors via
  lower `nodeRepulsion`.
- **No cross-platform edges exist** in the store, so cross-cluster connections cannot be
  drawn until `Person` / `MATCHED_BY` is wired.
