# CytoGravityRecommend.md

**Can the Cytoscape canvas be told to cluster Threads by platform, with merged nodes
pulled toward whichever platform they talk most on?**

Short answer: **yes**, and mostly without new libraries. But one part of the ask —
"merged nodes lean toward the platform they message most on" — is *not* a gravity setting.
It is a small computed value the backend has to hand the canvas. Details below.

---

## 1. Where we stand today

- Library: `cytoscape` 3.35 + `cytoscape-fcose` 2.2, vendored as plain scripts (no build
  step). `GraphCanvas.jsx` registers it on `window` before use.
- Layout call: `runLayout()` in `app/ui/src/components/GraphCanvas.jsx` (~line 762).
- Tunables: `theme.physics` in `app/ui/src/config/theme.js`.

Right now the layout is **free-floating**: every node is pushed and pulled only by its
edges and a weak global centering (`gravity: 0.2`). Two Telegram threads that share
nothing end up wherever they happen to land, next to WhatsApp threads. There is no
notion of "this belongs with its platform".

Note: `store/graph.rl` is the database itself (binary), not a schema file. Nothing in this
note asks the database to change. Everything here is either (a) a layout option in the
UI, or (b) one extra number on each node the API already returns.

---

## 2. The three mechanisms, in plain terms

fcose gives us three ways to make things group. Only one is worth using.

### A. "Bags" around each platform — *recommended*

Cytoscape supports **compound nodes**: a parent node drawn as a container, with child
nodes inside it. fcose is explicitly built for this (the **f** stands for *fast
Compound*). A parent behaves like a body with real size — children cannot drift out,
whole platforms repel each other, and edges that cross between platforms are stretched
between the two bodies.

**Terminology, settled:** compound node = container = bag = the same object. Cytoscape's
term is "compound node"; this doc says **bag** from here on, and the code should use
`type: "Bag"` so prose, code and CSS selectors all say the same word.

This is what the ask describes, almost word for word. Each platform = one bag.
Telegram's threads go in the Telegram bag. WhatsApp's in the WhatsApp bag. A Thread
only ever belongs to one platform, so **every Thread goes in exactly one bag — no
exceptions**. That is the clean part of this design.

**A bag is invisible and inert.** It is not a thing the user can see, click, drag or
question — it exists to give fcose a body to solve around, nothing more:

```js
// Bag style — one per platform. Invisible, inert, behind everything.
{
  selector: 'node[type = "Bag"]',
  style: {
    "background-opacity": 0,      // fully invisible body
    "background-image": "none",
    "border-width": 0,
    "label": "",                  // no label at any zoom
    "events": "no",               // not clickable, not hoverable, no tap
    "selectable": false,
    "grabbable": false,           // dragging a child must not drag the bag
    "z-compound-depth": "bottom", // drawn behind its children
    "z-index-compare": "manual",
    "z-index": 0,
    "padding": 24,                // breathing room around children
    "compound-sizing-wrt-labels": "exclude",
  },
}
```

Four traps in that style block, each of which silently breaks the feature if missed:

1. **Never `display: "none"`.** Hiding a parent hides its children and breaks the
   compound relationship entirely. Invisibility must be `background-opacity: 0`, not
   `display: none`.
2. **`events: "no"` is what makes it non-clickable.** `selectable: false` alone still
   lets the bag swallow taps — which is worse than it sounds: a tap on the bag's padding
   would fire the background handler, or nothing at all.
3. **`z-compound-depth: "bottom"`** is the property that puts the bag behind children.
   `z-index` alone does not do it.
4. **`padding` + `compound-sizing-wrt-labels: "exclude"`** keep the bag's body tied to
   its children's real geometry. Without the exclude, the label's (empty) box still
   participates in sizing and the bag's border-box drifts.

**Bags must be built in the same pass that filters children** — the
`theme.filter.platforms` path — never as a separate step. A separate step is how you get
an orphan bag with no children, or a child whose parent was filtered away; fcose errors
on the latter rather than degrading, so this is a hard requirement, not a tidiness note.

### B. Pin platforms to fixed spots ("Telegram always left, WhatsApp always right")

Possible (`relativePlacementConstraint` / `alignmentConstraint`). Useful if you want the
same picture on every reload, but it doesn't itself pull members together, and it
fights the random startup positions the canvas relies on today. **Not recommended now.**

### C. Let the layout sort things by attribute on its own

There is a `tilingCompareBy` option, but it only affects standalone pieces, not the main
relaxation. It will not produce platform clusters. **Skip.**

---

## 3. Recommendation in words

1. **One bag per platform.** Seven platforms, seven bags. Invisible and inert — a body
   for fcose, not a UI object.
2. **Threads are children of their platform's container.** Always exactly one.
3. **Any node with exactly one platform is a child of that platform's container** —
   Threads, single-platform Correspondents, and future single-platform Person / Org /
   Place / Product alike. No per-type branch.
4. **Any node with more than one platform stays outside every container**, and leans
   toward its dominant platform (§5).
5. **Cross-platform edges stay as they are.** They are now the lines that tie the seven
   bags into one picture, which is exactly the behaviour asked for. Each such edge pulls
   bag-to-bag, so the pull is naturally equal in both directions.
6. **Merged nodes lean toward their dominant platform.** Their position isn't guesswork —
   it's decided by one number, `dominance`, described in §5.

### The rule is `:Merged`, inverted

Rule 3 and rule 4 are one predicate, not two, and the store already materialises it:

> **A node goes in a bag if and only if it is not `:Merged`.**

Threads are trivially single-platform, so they are trivially bagged. Merged nodes are
`(:Correspondent:Merged)` etc., so they are trivially outside. That means `:Merged` IS
the bag-membership test — not merely an audit annotation — and the canvas needs no
per-kind judgement at all. This is what makes the rule survive Person / Org / Place /
Product without further thought.

Caveat: the predicate reads the **label**, not the `platforms` array. Two nodes could
theoretically disagree (a node with one platform but labelled `:Merged`). Trust the
label: it is the merge decision, and the array is a report of what that decision saw.

---

## 4. The hard one: where do multi-platform Correspondents go?

A merged Correspondent is, by definition, in Telegram *and* WhatsApp *and* email. It
cannot live in three bags. Three options:

| Option | What it looks like | Verdict |
|---|---|---|
| Put it in the bag with the most messages | Simple, but lies — the node visibly belongs to one platform while its edges go everywhere, and which bag it lands in changes when you re-ingest | Fragile |
| Put it in every bag (copy it) | Visually "correct", but it's now several objects pretending to be one, and clicking one highlights the wrong thing | Confusing |
| **Leave it outside the bags, and nudge it toward its dominant platform** | Sits in the space between containers, visibly tethered to the platform it's most active in | **Recommended** |

Only **single-platform** correspondents are unambiguous, and **they do go in their
platform's bag** — same rule as Threads, no special case. Multi-platform ones are the
"bridges": they stay outside and lean (§5).

**The general rule that survives Person / Org / Place / Product:** not `:Merged` → bagged;
`:Merged` → outside and leashed. Mechanical, no per-type judgement, which matters because
the schema is heading toward five merged kinds. See §3 for why the label, not the
`platforms` array, is the test.

**A Place is the case that proves the rule.** §"Future kinds" of the build plan notes
that a Place's `platforms` means "which platforms *mentioned* it", not "where it lives".
A Place mentioned on Telegram and WhatsApp and nowhere else would still be `:Merged` and
still sit outside the bags — even though `platforms` has two real entries. The label
handles this correctly; a `platforms.length === 1` test on Places would have quietly
given you a bag containing the world's geography.

---

## 5. "Pulled toward whichever platform had more messages" — how

This is the only part that needs data the canvas doesn't have. And it must be done with
**soft pull, not hard pinning** — otherwise you're back to fighting randomize.

**Two new fields — and neither is `platform`.**

`platform` must **not** be redefined. It is deliberately *first by date*, so the filter
and the `platform_label` do not drift between ingests. "Most messages" is a different
question that can legitimately give a different answer, and swapping the definition would
reintroduce exactly the ingest-to-ingest instability the date rule exists to prevent.
Keep them separate:

| Field | Definition | Stability |
|---|---|---|
| `platform` | first platform seen, date order | **existing** — stable across ingests by design |
| `platforms` | all platforms, accumulated | **existing** |
| `primaryPlatform` | platform with the most messages | **new** — can change as the store grows, and that is fine |
| `dominance` | 0.0–1.0, how lopsided the message split is (1.0 = one platform only) | **new** — derived from the same counts |

**Where it is computed: at query time, not at write time.** There is no per-platform
message count in the store today (`seen_<p>` is a first *sighting*, not an activity
measure). It is one traversal:

```
(c)<-[:WITH]-(t)<-[:IN]-(m)  grouped by m.platform  ->  counts, then max/total
```

That belongs in `_NODE_QUERIES["Correspondent"]`, **not** in `_reconcile()`. Query-time
keeps it a derived view: correct as the store grows, with no re-ingest and no stale cached
property. Same reasoning that keeps `primaryPlatform` allowed to change while `platform`
may not.

Note `dominance` is meaningful for **single-platform nodes too** — it is exactly 1.0 — so
the UI can use one field rather than branching on `:Merged`. And it is only defined where
`WITH` edges reach a platform; an org or place with no messages gets `null`, not 0, and
the leash is simply not drawn.

**What the canvas does with it.** Two things, both cheap:

1. **A short invisible "leash".** Give each multi-platform node one extra invisible edge
   to a small invisible anchor node sitting in its dominant platform's bag. Give that
   leash an ideal length proportional to `dominance`. High dominance = short leash = the
   node hugs Telegram. Low dominance = long leash = it drifts between platforms. Set the
   leash's elasticity high so it genuinely pulls but can still be outweighed by real
   edges. This is the standard fcose trick for "soft gravity toward a point" and it
   degrades gracefully — nothing breaks, the node just sits further from the anchor.
   No `dominance` (no messages) means no leash at all; the node floats on its edges only.

2. **A visual echo of dominance.** Where the node sits already reads correctly, but the
   cost is that a high-dominance bridge looks identical to a 50/50 bridge. Suggest the
   border colour or a thin ring on merged nodes uses their **primary platform's** colour,
   and the merged state is already shown by the existing multi-platform label. No new
   styling machinery.

**Why not "just raise gravity"?** The existing `gravity` setting pulls *everything*
toward the middle of the screen. That would crush all seven bags into one ball and
destroy the clustering. The leash is per-node and per-target, which is the difference
between "everything sinks" and "this node leans Telegram".

---

## 6. Things that will bite

| Risk | Why it matters | Mitigation |
|---|---|---|
| **Bags vs. the platform filter** | Hiding a platform (`theme.filter.platforms`) rebuilds the graph. If a bag survives without its children — or a child survives without its bag — fcose **throws**, it does not degrade | Bags must be built in the same pass that filters children. Never a separate step. See §2A |
| **Bags vs. `randomize: true`** | Random start positions are mandatory today (comment in `theme.js`), and bags are less reliable with fully random starts | Accept slightly looser bags per run, or fix each bag's seed position. Do not turn randomize off unless quality moves to `proof` — that's slower |
| **`packComponents: true`** | Already on. It packs *disconnected* pieces. With bags, most things are connected, so it mostly stops mattering — but don't assume it's doing the clustering. It isn't, today | Leave it on; expect it to do less |
| **Bag labels vs. label easing** | Your labels are a zoom reward. Any bag label would ignore that and shout at every zoom level | Settled: bags carry no label at all (`.label: ""`). Not a tuning question |
| **Big bags dominate** | Telegram has 26 threads, Outlook has 6 (and zero correspondents). Without care the big bags take the whole canvas | `gravityCompound` is the knob that squeezes each bag internally — tune it, don't tune global `gravity` |
| **Synthetic nodes leak into every count** | Bags, leash anchors and leash edges are **client-side only** — same class of problem as `Merged` in `types_present()`. Layout, the reveal sequence, and the "N drawn" readout all count nodes, so ~7 bags + N anchors + N leashes would appear as data that does not exist | Exclude via a `synthetic` class: the reveal sequence, the `onLayoutDone` node/edge counts, and any node-count the Canvas modal shows. `cy.nodes()` includes bags — do not use its `.length` raw anywhere |
| **Synthetics must never come from the server** | If bags or anchors are ever persisted, they hit `db.labels()` the same way `Merged` does and pollute `types_present()` | Bag/anchor construction stays in `GraphCanvas`'s element memo. If it ever moves server-side, it needs the same exclusion `Merged` gets in the Toggles modal |
| **Merged nodes and the client filter** | The canvas currently reads `node.platform` to decide visibility. A merged node with `platform: telegram` but `platforms: [telegram, whatsapp]` will vanish when WhatsApp is unticked | Already a known item in the build plan (edit 3). Bags make it *worse* if unaddressed, because a child can be hidden while its bag stays |

---

## 7. Suggested order of work

1. **Bags first, no leashes.** One bag per platform, single-platform nodes as children,
   everything else outside. Add the bag style block from §2A verbatim, plus
   `gravityCompound` in the theme. Exclude bags from the counts and the reveal in the same
   commit — it is not a follow-up. Run it and look. This alone gets you 80% of the ask.
2. **Then the leash.** Add `primaryPlatform` + `dominance` to the API response, then the
   hidden anchor edges. Do this after step 1 because the leash is only meaningful once
   bags exist to lean toward.
3. **Then the visual echo.** Only if the picture still reads ambiguously.

Each step is independently revertible, and step 1 changes nothing about the data.

---

## 8. Straight answer to the two questions asked

- *"Can Cytoscape be configured so major node types cluster together?"*
  **Yes.** One container per platform, nodes inside, and fcose does the rest. This is its
  primary use case, not a workaround.
- *"Are cross-cluster edges pulled at equal gravity?"*
  **Yes, for free.** An edge between two bags pulls bag-to-bag with the same spring
  constants on both ends. There is no per-platform weighting to add unless you *want*
  cross-platform links to be weaker — that's one optional knob (`edgeElasticity`), not a
  requirement.

---

## 9. Settled decisions (post-review)

| Decision | Ruling |
|---|---|
| Bag membership test | **Not `:Merged`.** The label, not the `platforms` array. |
| Single-platform Correspondents | **In the bag.** Same rule as Threads; no special case. |
| Where Correspondents go | §3 rule 3 + §4 now agree; the earlier contradiction is resolved |
| `platform` | **Unchanged** — first by date. Never redefined as dominant |
| `primaryPlatform` / `dominance` | New, **query-time**, in `_NODE_QUERIES["Correspondent"]`; never `_reconcile()` |
| Bags / anchors / leashes | **Client-side only**, marked `synthetic`, excluded from every count and the reveal |
| Bags are invisible bodies | `background-opacity: 0` + `events: "no"` + `z-compound-depth: "bottom"`; **never** `display: none` |
| Bag construction | In the child-filtering pass, never a separate step — fcose throws on a parentless child |
| Naming | `type: "Bag"` in code and selectors; prose says "bag" |

Open: whether the leash anchors are one per platform (shared) or one per node. One per
platform is fewer objects; one per node allows the leash length to vary freely per node.
That is the only structural question left, and it is worth answering after step 1 of §7
has been seen on screen.
