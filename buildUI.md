# buildUI.md

UI build notes. Decisions live here; the graph/storage side lives in `buildNOTES.md`.
Written 2026-11-15 for handover — assume the reader has not read this chat.

---

## 1. Status

**Nothing is built yet.** `app/` holds five empty `__init__.py` stubs (17 KB total, nothing in them).
Everything below is a decision, not code.

Backend is done and has real data (§10 of `buildNOTES.md`): **12,499 messages, 955 threads,
591 correspondents** across 5 platforms in `store/graph.rl`. The UI is the only thing missing.

### Where to start, in one line

> **Build `relate_comms/tools.py` first.** It is currently *comments only — zero
> implementations*, and the UI, the local chat and MCP all bind the same functions.
> Minimum viable: `graph_slice` + `thread_arc` + `search_messages`.

Full ordering in §10. Backend handover in `buildNOTES.md` §10.

---

## 2. What this UI is for

A local-only viewer for the message graph, judged as a Neo4j Relate Hackathon entry.
The store is demo-ready; nothing can show it. This is the missing half.

**Hard constraints:**

| Constraint | Detail |
|---|---|
| **Local only** | `localhost`. No Cloudflare, no deployment, no build step at runtime. |
| **No cloud AI** | Local Ollama at `127.0.0.1:11434`. No API key, no outbound call. |
| **No outbound calls at all** | Same rule as the library (`buildNOTES.md` §5.1). |
| **Whole store** | UI state must never narrow what an agent can query (§5.2). |

---

## 3. Layout — five areas

Decided by the author, 2026-11-15. The title bar holds **every** control as a button;
nothing lives in a settings page.

```
┌──────────────────────────────────────────────────────────────────────┐
│ ● OFFLINE · nothing leaves this machine                              │
│ [Search……]  [Ingest] [Setup] [KB] [Toggles] [Graph Style] [Logs]     │
├───────────────────────────────────────────────┬──────────────────────┤
│                                               │  AI CHAT             │
│                                               │  ┌────────────────┐  │
│           3D GRAPH CANVAS                     │  │ conversation   │  │
│           (thread nodes only)                 │  │ history        │  │
│           + background haze                   │  └────────────────┘  │
│                                               │  [ ask… ]            │
│                                               ├──────────────────────┤
│                                               │  VIEWER              │
│                                               │  (node | results)    │
└───────────────────────────────────────────────┴──────────────────────┘
```

| # | Area | Notes |
|---|---|---|
| 1 | **Title bar** | offline badge + all buttons |
| 2 | **Search bar** | top. Results land in the Viewer as a `results` state |
| 3 | **AI chat** | right, above the Viewer. Local Ollama |
| 4 | **Viewer** | right, below chat. Two states (§5) |
| 5 | **Logs** | modal from the footer/log button — ingest, main functions, errors, all in one |

**Modals behind title-bar buttons:** Setup · Ingest · KB (graph summary) · Toggles ·
Graph Style · Logs.

**Note a change from the earlier sketch** (`buildNOTES.md` §5): the panel is on the
**right**, not the left, and logs are a **modal**, not a strip.

---

## 4. Graph canvas

### 4.1 Thread-first

The canvas draws **Thread nodes only** — 955 of them. Message nodes are **not drawn** and
are not meant to be: 12,499 is not drawable, 955 is. This is a rendering decision; the
store still holds every message and agents still see all of them.

Correspondents also drawn, attached via `Thread-[:WITH]->Correspondent`.

### 4.2 Library — **sigma.js v4**, 2D

**Decision (2026-11-15): `sigma.js` v4, MIT, WebGL, with `graphology` as its data layer.**

The deciding requirement was not looks — it was **labels that appear by zoom level** (§4.3).
sigma is the only plain-web 2D library that ships this natively.

**2D, not 3D** was chosen separately and still stands: 3D wins the first 5 seconds and loses
the next 60 — occlusion, unreadable labels, node-hunting. A judge has to click a thread and
understand it.

#### Why sigma won

| Library | Zoom-tier labels | Declutter | Verdict |
|---|---|---|---|
| **sigma.js v4** | **native** — `labelRenderedSizeThreshold` | **native** — size-sorted grid | **chosen** |
| Cytoscape.js | yes — `min-zoomed-font-size` + `mapData(degree,…)` | no | runner-up, author has used it |
| force-graph 2D | **no** — DIY in `nodeCanvasObject` | **no** | fallback only |
| vis-network | no label LOD | no | out |

`force-graph`'s `nodeLabel` is a **hover tooltip**, not a rendered label — precisely what was
rejected. Doing it manually in `nodeCanvasObject` means writing collision logic too.

#### The three settings that do the work

| Setting | Default | What it does |
|---|---|---|
| `labelRenderedSizeThreshold` | 6 px | A node's **rendered** size must reach this before its label draws. Big nodes cross it first; small ones fade out on zoom-out. This *is* the size-weighted zoom LOD. |
| `labelGridCellSize` | 100 px | Screen-grid cell size for the density pass |
| `labelDensity` | 1 | Labels allowed per cell. The cap shrinks as you zoom out. Within a cell, candidates are sorted **size descending** — so the biggest nodes win the slot |

Demos: <https://www.sigmajs.org/examples/label-rendering/> ·
<https://www.sigmajs.org/examples/large-graph/>

#### Accepted costs

- **graphology is required.** It is a plain in-memory JS object — two flat tables (`id → attrs`,
  `source → target → attrs`) plus adjacency indexes for fast neighbour lookup. It is **not** a
  database, has no query language, and dies on refresh. Converting our JSON to it is ~6 lines:

  ```js
  const g = new Graph()
  for (const n of data.nodes) g.addNode(n.id, n)
  for (const l of data.links) g.addEdge(l.source, l.target)
  ```

- **No bloom/depth.** WebGL 2D. Glow is faked with node colour + halo, not post-processing.
- **Long labels can still collide** — the grid declutters by node size but does not
  collision-test label boxes. Multiple lines are possible (`label` can be a string[]).

#### Fallbacks kept open

`force-graph` 2D and `3d-force-graph` (author has used both) remain viable. Neither gives
label LOD for free, so switching means writing it.

**Rejected, with reasons:**

| Option | Why not |
|---|---|
| **Juggl** (Obsidian plugin) | **Two reasons, neither about 2D:** (1) **GPL-3** — a licence blocker for a public repo; (2) **Obsidian-only** — its own docs say *"Juggl currently only has an implementation for Obsidian"*, so the graph core cannot be ported without work. 2D vs 3D was never the question. |
| `3d-force-graph` | Not rejected on licence — it is MIT and the author has used it. **Deselected on readability**: 3D loses labels to occlusion (§4.2). Kept as a fallback. |
| `@cosmograph/react` | **CC-BY-NC** — forbids commercial use. `cosmos.gl` core is MIT but flat dots only, no labels |
| `vis-network` | dated, 84 MB unpacked, no label LOD |
| Cypress/G6/ECharts | enterprise-dashboard look, not space |

### 4.3 Labels appear by zoom — the actual requirement

**Stated by the author:** zoomed out, no labels. Zoom in, labels fade in depending on node
size. The user must **never** have to hover or click a node just to read its name.

sigma gives this in three settings (§4.2). The intent, so it is not lost:

- **Far zoom** — every label suppressed. A clean field of glowing dots.
- **Mid zoom** — only high-degree nodes (big threads) carry labels. The graph stays legible.
- **Close zoom** — all labels appear, including small threads and correspondents.
- **Never** hover-to-reveal, never click-to-reveal. Labels are a zoom reward.

Tune `labelRenderedSizeThreshold` upward if the mid-zoom view is still crowded.

### 4.4 Graph Style modal — a new requirement

Decided 2026-11-15: the title bar gets a **Graph Style** button opening a modal that
adjusts force simulation and visuals **live**. This is the visible payoff of keeping all
style values in one config object (§7).

Suggested controls — following the `PHYSICS` block in `AxiomLC/frontal-lobe`'s
`ui/src/config/theme.js`:

| Group | Controls |
|---|---|
| Physics | layout force settings (`graphology-layout-forceatlas2` settings), `barnesHut`/`adjustSizes`, freeze / re-run |
| Labels | `labelRenderedSizeThreshold`, `labelDensity`, `labelGridCellSize`, label font size, label colour |
| Visual | node size, link opacity, link width, glow strength, background haze |
| Layout | freeze / re-run simulation, reset to defaults |
| Filter | which node types are drawn (**view-only — never narrows a query**) |

Persist to `localStorage` so a reload keeps the chosen look.

---

## 5. Viewer — two content states

Taken from `AxiomLC/frontal-lobe`'s `ui/src/components/Viewer.jsx`, which solved this
well. That section of the file is worth reading before implementing.

| State | Kind | Trigger | Shows |
|---|---|---|---|
| **state0** | `results` | search bar, or AI returning hits | a table of results, one row per node |
| **state1** | `node` | graph node click, or a result row click | that node's meta + content |
| **Back** | — | Viewer's own back button | pure state restore |

### 5.1 The halo / fly-to rule — copy verbatim

From `frontal-lobe/ui/src/App.jsx`:

```js
// Map halo target — set ONLY by map click and result-row select (§5).
const [haloId, setHaloId] = useState(null)
// Fly-to target — set ONLY by result-row select — the camera rotates to
// this node. Map clicks deliberately don't set it
// (rule: clicking around shouldn't yank the view).
const [flyToId, setFlyToId] = useState(null)
```

| Action | Halo | Fly-to | Viewer state |
|---|---|---|---|
| Click a graph node | ✅ | ❌ | `node` |
| Click a result row | ✅ | ✅ | `node` |
| Back button | ❌ | ❌ | restores |
| AI returns results | ❌ | ❌ | `results` |

**Back never moves the camera.** Clicking around must not yank the view.

### 5.2 Thread node → message bodies

From `buildNOTES.md` §5.5, restated because it is the thing most likely to be got wrong:

- Clicking a Thread opens state1 with that thread's **messages**, ordered `ts_utc DESC`.
- **Flex-scrolls**: renders ~1,000 characters (2–5 messages) with a visible separator.
- **Page button at the bottom** goes to the next page. No infinite spinner, no load-all.
- **Search box pinned at the top, scoped to this thread only.**
- The 707-message thread must work — nothing ever renders it in one go.

```cypher
MATCH (t:Thread {key: $thread_key})<-[:IN]-(m:Message)
RETURN m.key, m.ts_utc, m.is_self, m.sender_name, m.body
ORDER BY m.ts_utc DESC
SKIP $skip LIMIT $limit
```

---

## 6. Look — colours and style, as specified by the author

### 6.1 Palette

| Element | Colour | Notes |
|---|---|---|
| Background | **deep black/green** | base `#05070a`, green lift `#0a1410` |
| Background haze | **slight haze in the graph viewport** | static radial gradient. **Not animated** — CSS gradient animation is expensive on integrated graphics |
| Buttons | **dark orange contrast** | fill `#8a3d12`, text `#d97a2b` |
| Borders / outlines | **thin dark blue** | `#1b2a4a`, 1px |
| Objects (nodes, active UI) | **light blue glow** | `#5c8fd6` at 12–20% opacity |

### 6.2 Techniques worth keeping

From research, 2026-11-15:

1. **Grain overlay** — the single most common trick in premium dark UIs. SVG `feTurbulence`
   as a static background image at 3.5% opacity, `mix-blend-mode: overlay`. Rasterises once,
   near-zero cost. Above ~8% it turns muddy.
2. **Two-tone palette, one accent.** Links near-invisible; nodes carry the colour.
3. **Kill the spring.** `alphaDecay` 0.02–0.03, high `velocityDecay`. A graph that keeps
   bobbing looks like a physics toy.
4. **Curved, low-opacity edges** (~8–20%). Straight lines on dark read as a wireframe.
5. **Labels are a zoom reward**, not decoration. Hide at full zoom, fade in near the top
   nodes by degree. Hash colours per community so the picture looks identical every load.
6. **Timeline reveal on load** — nodes bloom outward in `ts_utc` order over ~2.5 s.
   Highest impact per effort for a demo. Optional, toggleable.

### 6.3 Typography

Inter (or system-ui) at 12–13px for dense panes, 11px meta with `tabular-nums` for
timestamps. Radii ≤14px, 12px dominant. Borders at `rgb(255 255 255 / .06–.09)` rather
than lighter greys.

---

## 7. Dev knobs at the top

**One config object at the top of the UI entry script**, every tunable value, heavily
commented. Same pattern as `AxiomLC/optic-nerve-ui`'s `src/config/theme.js` and
`frontal-lobe`'s `ui/src/config/theme.js` — both are worth reading as the template.

Those files are the reference for style: each value carries a comment explaining what it
does and what range is sane, e.g. `alphaDecay: 0.02, // 0.01=slow/wide, 0.05=fast/tight`.
Copy that discipline.

---

## 8. AI wiring — local Ollama

### 8.1 History lives in the browser

Taken from `frontal-lobe`'s `ui/src/components/VoicePanel.jsx`:

> *"history PERSISTS per browser: session id + transcript in localStorage — a refresh
> keeps the whole conversation"*

Two `localStorage` keys — a session id and the transcript array. Rehydrate on load.

**This works unchanged for Ollama**, with one difference: Ollama is **stateless**, so the
transcript must be sent with every request rather than held server-side.

```
POST /chat  { session_id, messages: [{role, content}, …], message }
         →  Ollama /api/chat  { model: "lfm2.5:8b", stream: true, think: false }
         →  { reply }
```

### 8.2 `think: false` is not optional

`buildNOTES.md` §2.3: thinking mode is **28× slower** on this hardware (368 tokens vs 10
for "hello"). `lfm2.5:8b` is the default, ~21 tok/s CPU-only. Always send `think: false`.

### 8.3 What the AI can see

**Everything.** The chat queries the whole store, never a narrowed view (§5.2, §8.1 of
`buildNOTES.md`). The UI's current node may be passed as an **explicit hint**
("user is looking at thread X") but must never become an implicit filter.

### 8.4 Tools

The chat and MCP bind the **same** functions from `relate_comms/tools.py` (§5.2 of
`buildNOTES.md`). That file is still only comments — no implementations. Whoever builds
the chat has to build the tool layer first, or the chat can only do free text.

---

## 9. Scaffold to follow

**`AxiomLC/frontal-lobe`** (private) — the closer match, and the author's own code.

```
ui/
  src/
    App.jsx                    shell; owns haloId, flyToId, viewerPush
    components/
      CommandBar.jsx           top bar with search
      NeuralMap.jsx            graph canvas
      Viewer.jsx               the state timeline — the important one
      LogDrawer.jsx            logs
      UtilitiesDrawer.jsx      toggles
      InputDrawer.jsx          ingest / setup
      CypherPanel.jsx          raw Cypher
      VoicePanel.jsx           AI chat + localStorage history
    config/
      theme.js                 dev knobs
      nodeTypes.js             type → colour/icon/toggle
      cypherTemplates.js
    lib/api.js                 thin fetch client to the Python service
    styles/globals.css
```

**`AxiomLC/optic-nerve-ui`** (private) — same lineage, more polished graph styling:
glow sprites, label tiers, orphan column, `ENTITY_COLOR` per type.

**Do not** carry over from either: Cloudflare Pages, `wrangler.toml`, Supabase, Supabase
auth/dept scoping, or any cloud LLM leg. Those are the other projects' constraints, not
this one. This runs on `localhost` against `store/graph.rl`.

---

## 10. Build order

1. **`relate_comms/tools.py` implementations** — nothing else can be built without a
   query surface. `thread_view`, `graph_slice`, `search_messages`, `run_cypher`.
2. **FastAPI app** — `/health`, `/stats`, `/graph`, `/thread/{key}`, `/search`, `/chat`.
3. **Canvas** — `sigma.js` v4 + `graphology`, threads + correspondents, 2D, palette applied,
   labels appearing by zoom (§4.3).
4. **Viewer** — two states + back + halo/fly-to split.
5. **Search bar** → Viewer state0.
6. **AI chat** → Ollama, `localStorage` history, results land in Viewer state0.
7. **Modals** — Setup · Ingest · KB · Toggles · Graph Style · Logs.
8. **Polish** — grain, haze, timeline reveal, label fade.

Step 1 is the gate. Everything above it is rendering.

---

## 11. Open questions for the next thread

- **React + Vite, or one `index.html`?** Decided in favour of the Vite scaffold (same as
  `frontal-lobe`), but nothing is written yet — reversible if a build step becomes
  annoying. `buildNOTES.md` §5.1 originally said "single HTML".
- **`tools.py` is all comments.** How much of the tool surface is needed for the demo?
  Minimum viable: `graph_slice` + `thread_view` + `search_messages`.
- **Which Ollama model for chat?** `lfm2.5:8b` is the measured default, but it was
  benchmarked on 8 easy extraction prompts, not conversation (`buildNOTES.md` §2.3).
  Re-test before committing.
- **How hard is the graphology step?** Conversion itself is ~6 lines; the open question is
  whether `graph_slice` should emit graphology-ready JSON directly, so the client does no
  shaping at all. Prefer composing on the Python side.
- **Timeline reveal** — include or skip? Cheap, high impact, but it delays first paint.
- **`Person` node.** The UI can show Correspondents today. Cross-platform identity
  (`Person`, `SENT`) does not exist yet — see `buildNOTES.md` §3.2. Do not design around it.

---

## 12. Do not relitigate

| Decision | Why |
|---|---|
| **sigma.js v4 + graphology, 2D, not 3D** | author's call, 2026-11-15. Chosen for native zoom-tier labels (§4.3). Fallbacks `force-graph` / `3d-force-graph` stay open |
| **Threads drawn, messages not** | 12,499 nodes is not drawable; 955 is |
| **Juggl is out** | GPL-3 + Obsidian-only. **Nothing to do with 2D or 3D** — it was rejected on licence and platform, and the 2D decision was made separately |
| **Local `localhost` only** | no deployment, no Cloudflare |
| **Ollama, never a cloud key** | privacy is the product |
| **Back never moves the camera** | from `frontal-lobe`; clicking around must not yank the view |
| **UI state never narrows an agent's query** | `buildNOTES.md` §5.2 |
| **Every value in one config object** | the Graph Style modal depends on it |
