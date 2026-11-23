# The graph payload as a detachable module

**Status:** researched, not built. HANDOVER.md §1 points here for the detail.
**Question it answers:** how much work is it to make `/api/graph` a renderer-neutral
payload, so Cytoscape/fcose could be swapped for `2d-force-graph`, `3d-force-graph`
or React Flow without touching ingest, the store, or the tool layer?

---

## 1. Verdict

**Cheap for the data, expensive for the look.** The answer is not one number:

| Part | Work | Risk |
|---|---|---|
| **(a) Freeze the payload contract** — enumerate fields, add a keys-lock test | **~half a day** | none; pure gain even if no second renderer is ever built |
| **(b) Move server-side renderer leakage out of the payload** | **~1 hour** | none — it is 6 lines and 1 dead field |
| **(c) Write the cross-definitions** — chart, vocabulary, capability matrix | **~1 day** | low; it is all documentation |
| **(d) One alternative renderer behind a switch** | **2–4 days** | **high** — this is where the unknown lives |

(a)+(b)+(c) ≈ **two days** and they make the payload genuinely appropriate as a published
contract — worth doing regardless. (d) is only worth starting once a renderer is actually
wanted, and it is the only part that can be half-built and worthless.

**Why (a)–(c) are cheap:** the payload is already clean. Nothing on the server emits a
Cytoscape concept — the only two items in §3 are one dead projection and one docstring. The renderer-facing concepts (bags, ring,
tiers, halo, shade, reveal) all already live on the client, in three files, with the
tuning isolated in `theme.js`.

**Why (d) is not:** the payload is ~5% of the port. `GraphCanvas.jsx` is 1,314 lines, of
which ~1,100 is renderer behaviour that a replacement must either reproduce or knowingly
drop. §8 is the per-feature rehearsal.

---

## 2. The payload as it exists today

Measured from a live `tools.graph_slice(limit=400)`, not from docs.

### Envelope — 10 keys, always present

```
nodes[]  edges[]  counts{nodes,edges}  total  node_types[]  edge_types[]
limit  sort  truncated  edges_skipped
```

`total` is what the store holds; `counts.nodes` is what survived `limit`. They are
deliberately different numbers and the UI says "showing N of total".

### Node — flat dict, one extra key `type` added by the loop

Union of all keys actually returned for `Thread` + `Correspondent`:

| Field | Thread | Correspondent | Meaning |
|---|---|---|---|
| `id` | ✓ | ✓ | `platform:chat_id` or `person:<canonical>` — globally unique, namespace-safe |
| `label` | ✓ | ✓ | display string; the canvas truncates, it never edits |
| `type` | ✓ | ✓ | `"Thread"` / `"Correspondent"` — **the only field the canvas branches on** |
| `platform` | ✓ | ✓ | **first by date**, stable across ingests. Not "dominant". |
| `platforms` | ✗ | ✓ | full list; the source filter and the Viewer pills read this |
| `platform_label` | ✗ | ✓ | `"Telegram-LinkedIn-Email"`, precomposed |
| `merged` | ✗ | ✓ | the `:Merged` label as a boolean — the *decision*, not `platforms.length > 1` |
| `message_count` | ✓ | ✗ | sizes the Thread rung |
| `thread_count` | ✗ | ✓ | sizes the Correspondent rung; counted through `WITH` |
| `first_ts`/`last_ts` | ✓ | ✗ | reveal order, `recent`/`quiet` sorts, Viewer header |
| `is_group` | ✓ | ✗ | discussed in the Viewer |
| `is_silent` | ✓ | ✗ | thread with no `is_self` message; the *quiet* question |
| `primaryPlatform` | ✗ | ✓ | most *messages* — may disagree with `platform` on purpose |
| `dominance` | ✗ | ✓ | largest platform's share, 0.0–1.0 |

Message/Attachment rows are a different, narrower set (`ts_utc`, `is_self`, `raw_kind`)
and are never drawn by default.

### Edge — 3 keys

`{message source, target, type}` where type ∈ `WITH`, `POSSIBLY` by default. `IN`,
`REPLY_TO`, `HAS_ATTACHMENT`, `MENTIONS_<KIND>` exist but are opt-in. Edges carry **no
weight, no label, no style hint** — everything about an edge's appearance is derived
client-side from `edgeWeights.get(edge.source)`, i.e. the source node's own count.

### The invariant that makes this portable

Every node is a **uniform flat record distinguished only by `type`**, and every edge is a
bare `(source, target, type)` triple. No nested `data:` wrapper, no compound structure, no
per-renderer shape. That is already the universal graph contract that d3-force-graph,
React Flow, graphology and Sigma all accept after one mapping function each.

---

## 3. Renderer leakage on the server — two leftovers, both small

1. **`per_platform` is computed and thrown away.** `_NODE_QUERIES["Correspondent"]`
   returns `per AS per_platform`, and `_with_dominance` immediately `pop`s it to derive
   `primaryPlatform`/`dominance`. **No client, test or tool reads it** — confirmed on the
   live payload, it never reaches the wire. It costs a wider Cypher projection inside one
   function. Fix: keep the arithmetic, stop putting the transient on the row.
2. **The `graph_slice` docstring says "ready to hand to graphology".** Harmless — the
   payload really is graphology-shaped, and graphology itself is renderer-agnostic — but a
   docstring naming a specific library is the one place the code suggests one is required.
   Fix: say "a renderer-neutral node/edge list".

**One genuine vocabulary clash, not a bug:** the word **"bag"** means "invisible compound
parent for the layout" everywhere in this repo, and `2d-force-graph` has no such concept.
In d3-force it is a `forceX`/`forceY` ring; in React Flow it would be a `group` node with
`parentId`. The payload never contains the word, so nothing breaks — but §5's vocabulary
table is what stops a future reader from assuming the field exists.

---

## 4. What the client owns (and a replacement must re-implement)

All of it is in `app/ui/src`, and none of it is reachable from the payload contract.

| Concept | Where | Lines | Payload reads |
|---|---|---|---|
| `NODE_TYPES` — per-kind `drawable`, `sizeLadder`, `countKey`, `labelMax`, `edgeWeight`, `glow`, `iconKind`, `hideWhenSilent` | `config/nodeTypes.js` | 344 (data + helpers) | `node.type` only |
| `THEME` — palette, physics, tiers, labels, visual, reveal, layout, filter | `config/theme.js` | 407 | none |
| **Stylesheet** — 16 selector groups, icons, halos, gutters, selection | `GraphCanvas.jsx:589–940` | **352** | none |
| **Elements build** — filter, band assignment, nested culture | `GraphCanvas.jsx:155–375` | **220** | `platforms`, `merged`, `is_silent`, `label`, counts, `first_ts` |
| **Bags** — `bagId`, `MERGED_BAG_ID`, membership rule, empty-bag pruning | `GraphCanvas.jsx:103–113, 288–339` | ~60 | `platforms` + `merged` |
| **Band sizing** — `assignBands`, `snapToRunEnd`, `rungFor` | `GraphCanvas.jsx:945–1032` | 88 | `message_count` / `thread_count` |
| **Colour** — `shade` (FNV-1a jitter), `lighten`, `mergedStopsFor` | `GraphCanvas.jsx:35–42, 1042–1085` | ~60 | `id`, `platform` |
| **Ring** — `placeBagsOnRing` | `GraphCanvas.jsx:1105–1154` | 50 | none (geometry) |
| **Layout** — `runLayout`, `setSmartEdgeLength`, fcose options | `GraphCanvas.jsx:1180–1249` | 70 | none |
| **Reveal** — `startReveal`, 14 batches by `firstTs` | `GraphCanvas.jsx:1251–1314` | 63 | `first_ts` |

**The four concepts that define this graph's identity, and their nearest equivalent:**

1. **Two-tier composition** — platform bags on a ring, one merged bag of everything else
   at the centre. Equivalent: d3 `forceRadial` per group; React Flow `parentId` + a
   separate `group` node.
2. **Per-kind interleaved size ladder** — Thread A/C/E, Correspondent B/D/F, so a thread
   always outranks the correspondent of the same band. Equivalent: any renderer; it is
   just `assignBands` + a size table, portable unchanged.
3. **Merged = bridge** — grey glyph + orange radial halo, drawn outside every platform
   bag so real edges pull it between clusters. Equivalent: d3 node colour + a canvas
   radial gradient sprite; React Flow a CSS `box-shadow` (much easier there).
4. **Label LOD as a zoom reward** — `min-zoomed-font-size` × per-node font size. **This
   has no direct equivalent anywhere else.** d3-force-graph needs a `zoom` handler that
   toggles label visibility per node; React Flow needs a zoom-derived CSS class. It is the
   single concept most likely to be lost in a port.

---

## 5. Cross-definitions (the "translation layer")

The point of the contract: a renderer swap is a mapping function plus a list of things it
cannot do. Neither should ever require reading `GraphCanvas.jsx`.

### Vocabulary

| This repo | Cytoscape/fcose | d3-force / `2d-force-graph` | React Flow |
|---|---|---|---|
| node | node | node | node (`Node`) |
| edge | edge | link | edge (`Edge`) |
| `type` | node class + `data.type` | `type` for the accessor | `Node.type` (component selector) |
| bag | compound parent node | *(none)* — `forceX`/`forceY` target | `parentId` + a `group` node |
| platform bag | parent on the ring | radial anchor at angle θ | `group` positioned on a ring |
| merged bag | centred parent | `forceX/Y` toward the origin | `group` at the centre |
| `merged` | class + underlay | node colour / sprite | CSS class |
| size ladder | `node.width/height` | `nodeVal` / sprite scale | `style.width/height` |
| label LOD | `min-zoomed-font-size` | *(build it)* — zoom handler | *(build it)* — zoom state + class |
| reveal | class batches over 14 `setTimeout`s | node opacity animation | `style.opacity` transition |
| hue jitter | `background-color` per node | same | same |
| halo | `underlay-*` radial gradient | coloured sprite / canvas blur | `box-shadow` / `filter: blur` |

### Capability matrix — what each renderer can and cannot do

| Feature | Cytoscape | `2d-force-graph` | `3d-force-graph` | React Flow |
|---|---|---|---|---|
| 2,000 nodes at 60fps, no GPU | ✓ (Canvas) | ✓ (Canvas/WebGL) | ✗ this box | ~✓ (DOM nodes) |
| Invisible compound parent | ✓ native | ✗ (emulate anchor) | ✗ | ✓ `parentId` |
| Per-node sizing from data | ✓ | ✓ `nodeVal` | ✓ | ✓ CSS |
| Native label LOD | ✓ | ✗ build it | ✗ | ✗ build it |
| Real UI inside a node | ✗ | ✗ | ✗ | **✓ (its only win)** |
| Stylesheet in one object | ✓ | ✗ (JS accessors) | ✗ | ✗ (CSS + components) |
| Drag / grab | ✓ | ✓ | ✓ | ✓ |
| Radial halo without a sprite | ✗ (underlay only) | ~✓ | ✓ | **✓ easiest** |

**Reading the matrix:** `2d-force-graph` is the only drop-in that keeps the *look* and
loses the *bag*; React Flow is the only one that gains real node widgets and loses the
2,000-node performance. `3d-force-graph` is out on hardware alone — no GPU here.

---

## 6. The contract test (the actual deliverable of part (a))

A test that pins the payload's *shape*, not its values, so any field added or removed
forces a conscious edit:

```python
# tests/test_graph_contract.py  (proposed)
ENVELOPE = {"nodes", "edges", "counts", "total", "node_types", "edge_types",
            "limit", "sort", "truncated", "edges_skipped"}
THREAD     = {"id", "label", "type", "platform", "message_count",
              "first_ts", "last_ts", "is_group", "is_silent"}
CORRESPONDENT = {"id", "label", "type", "platform", "platforms", "platform_label",
                 "merged", "thread_count", "primaryPlatform", "dominance"}

def test_the_payload_shape_is_the_contract(store):
    s = tools.graph_slice(node_types=["Thread", "Correspondent"], limit=400)
    assert set(s) == ENVELOPE
    for node in s["nodes"]:
        expected = THREAD if node["type"] == "Thread" else CORRESPONDENT
        assert set(node) == expected, node["id"]
    for edge in s["edges"]:
        assert set(edge) == {"source", "target", "type"}
```

**Verified against the live store (2026-11-22): passes as written** — 177 Threads and 98
Correspondents, zero key mismatches, zero `per_platform` on the wire. So this is a
regression guard, not a cleanup: it locks in a shape that is already correct today. That
is the best possible starting position for making the payload a published contract.

**Why equality on the key set and not a subset check:** a subset check passes silently
when a renderer adds a field for its own convenience, which is exactly how the payload
becomes Cytoscape-shaped again without anyone deciding it should.

---

## 7. The mapping function (the whole of a new renderer's data layer)

Every candidate needs this and nothing more to draw something:

```js
// payload -> renderer-neutral graph, ~40 lines, one file, no component knowledge
function toGraph(data) {
  const nodes = data.nodes.map((n) => ({
    id: n.id,
    label: n.label,
    kind: n.type,                       // branch here, never on Cytoscape classes
    buckets: n.platforms?.length ? n.platforms : [n.platform],  // bag input
    primary: n.platform,                // colour input
    weight: n.message_count ?? n.thread_count ?? 0,
    merged: !!n.merged,
    firstTs: n.first_ts ?? null,
    silent: !!n.is_silent,
  }));
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const links = data.edges
    .filter((e) => byId.has(e.source) && byId.has(e.target))
    .map((e) => ({ source: e.source, target: e.target, kind: e.type }));
  // bags are DERIVED here, not requested from the server
  const bags = new Map();
  for (const n of nodes) {
    const key = !n.merged && n.buckets.length === 1 ? n.buckets[0] : "merged";
    (bags.get(key) ?? bags.set(key, []).get(key)).push(n.id);
  }
  return { nodes, links, bags };
}
```

`bags` is the one concept with no server representation, by design — it is derived from
`platforms` + `merged`, which is precisely the information a different renderer needs to
decide its own grouping. **That derivation is the translation layer**: nothing else in the
contract is renderer-specific.

---

## 8. Rehearsing a `2d-force-graph` port (part (d), concretely)

The closest fit: d3-force underneath, Canvas/WebGL, same radial idea available as
`forceRadial`, no build step for the library.

| Feature | Port cost | Outcome |
|---|---|---|
| Nodes, links, `nodeVal` sizing | trivial | ✓ better than now |
| `assignBands` / `rungFor` / `shade` | **zero** — pure functions, copy verbatim | ✓ identical |
| Colours and lightening | trivial — accessors instead of a stylesheet | ✓ |
| Bag → ring | moderate — `forceRadial` per platform + `forceX/Y` to origin for merged | ~ close, not identical |
| Label LOD | **build it** — `onZoom` + per-node label visibility | ~ worse; needs tuning |
| Merged halo | moderate — coloured sprite or `filter: blur` on a canvas | ✓ likely better (real blur) |
| Reveal | moderate — `nodeOpacity` tweened | ✓ |
| Click → Viewer | trivial — `onNodeClick`, same entry shape `{nodeType, id, label, …}` | ✓ |
| Selection / `focus` vs `halo` | moderate — bespoke | ~ |
| Edge tiers and `thick` | trivial — accessors | ✓ |

**Realistic total: 2–4 days**, of which roughly one day is the label-LOD and selection
bespoke work and the rest is mechanical. Nothing in it touches Python.

**The cheap way to buy the option without paying for the port:** do §3 and §6 now (~a
day), keep `theme.js` as the only place look lives (already true), and ship no second
renderer. The payload is then contractually frozen and the next person can add a renderer
against a tested boundary instead of against `GraphCanvas.jsx`.

---

## 9. Work plan

**Phase 1 — contract (half a day). No behaviour change.**
1. Delete `per_platform` from the wire (§3.1); keep `_with_dominance`'s arithmetic.
2. Add `tests/test_graph_contract.py` (§6) — key-set equality for envelope, both node
   kinds, edges.
3. Fold §2's table into `TECHREADME.md` §4 with a `required`/`optional` column, and point
   at this file for the renderer comparison.

**Phase 2 — vocabulary and matrix (half a day).**
4. Keep §5's vocabulary and capability matrix here as the reference; `TECHREADY` gets a
   one-line pointer only.

**Phase 3 — optional, only when a renderer is wanted (2–4 days).**
5. Write `toGraph()` (§7) as a standalone module behind `theme.layout.renderer`.
6. Port `GraphCanvas.jsx` to `GraphCanvasD3.jsx`; keep both mountable so the switch is
   reversible.
7. Accept the losses explicitly: label LOD and merged-halo occlusion are the two that
   will feel worse at first. Both are already documented as unsolvable in Cytoscape
   (`theme.js` §visual, `UIVISUALS.md` §1) — a new renderer may actually *fix* them,
   which is the strongest argument for the port and not a reason to hurry it.

**Non-goals.** No change to ingest, the store, `link.py`, extraction, or the tool layer.
The payload is the boundary; nothing on the other side of it should ever need a query
change.
