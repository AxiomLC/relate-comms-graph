# buildUI.md

UI build notes. Decisions live here; the graph/storage side lives in `buildNOTES.md`.
Written 2026-11-15 for handover — assume the reader has not read this chat.

---

## 1. Status

**Backend and API are done. The UI is not built.**

| Layer | State |
|---|---|
| Store | **12,499 messages, 955 threads, 591 correspondents** across 5 platforms |
| `relate_comms/tools.py` | **implemented** — 10 tools registered, 30 tests |
| FastAPI (`app/`) | **implemented** — `/api/graph`, `/api/thread`, `/api/search`, `/api/chat`, `/api/ingest` |
| UI (`app/ui/`) | **not started** — this document |

`app/static/index.html` is a throwaway placeholder that proves the API works. It is not the UI.

### Where to start, in one line

> **Build the canvas, then the Viewer, then the chat.** Those three are the demo.
> Modals (Log, Ingest, Graph Style) are placeholders until they are.

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

## 3. Layout — three columns, full height

Decided by the author, 2026-11-15. The title bar holds **every** control as a button;
nothing lives in a settings page.

```
┌──────────────────────────────────────────────────────────────────────┐
│ ● OFFLINE · nothing leaves this machine                              │
│ [Search……] [Cypher]   [AI] [Log] [Ingest] [Setup] [Graph Style]      │
├──────────────┬───────────────────────────────┬───────────────────────┤
│              │                               │                       │
│   AI CHAT    │       GRAPH CANVAS            │       VIEWER          │
│   25vw       │       flex: 1                 │       25vw            │
│   ⛶ → 40vw   │       (threads + corrs)       │       ⛶ → 40vw        │
│              │       + background haze       │                       │
│   transcript │                               │   node | results      │
│              │                               │                       │
│   [ ask… ]   │                               │                       │
└──────────────┴───────────────────────────────┴───────────────────────┘
```

| # | Area | Position | Width | Toggle | Expand |
|---|---|---|---|---|---|
| 1 | **Title bar** | top | full | — | — |
| 2 | **AI chat** | **left** | 25vw | **yes** — `[AI]` button | ⛶ → 40vw |
| 3 | **Graph canvas** | centre | `flex: 1` | always on | — |
| 4 | **Viewer** | **right** | 25vw | no | ⛶ → 40vw |
| 5 | **Logs** | modal | — | `[Log]` button | — |

**Left to right: AI → Graph → Viewer.** All three are full height, side by side — the same
geometry as `frontal-lobe` (`25vw` normal, `40vw` expanded, `min-width` guards). Toggling the
chat off gives its width to the graph.

**Modals behind title-bar buttons:** Log · Ingest · Setup · Graph Style. Log is a **modal**,
not a drawer — there is no `LogDrawer` in this app.

**Superseded:** an earlier sketch put the chat *above* the Viewer in one right-hand column,
and `buildNOTES.md` §5 put the panel on the left with logs as a strip. Both are dead.

---

## 4. Graph canvas

### 4.1 Thread-first

The canvas draws **Thread nodes only** — 955 of them. Message nodes are **not drawn** and
are not meant to be: 12,499 is not drawable, 955 is. This is a rendering decision; the
store still holds every message and agents still see all of them.

Correspondents also drawn, attached via `Thread-[:WITH]->Correspondent`.

### 4.2 Library — **Cytoscape.js + fcose**, 2D

**Decision (2026-11-15, revised): `Cytoscape.js` with the `fcose` layout extension.**

This replaces an earlier sigma.js v4 decision. Sigma was chosen because it was believed to be
the only library with native zoom-tier labels — **that was wrong.** Cytoscape's
`min-zoomed-font-size` is a native style property that skips text rendering when
`font-size × zoom` falls below the threshold. Same feature, no build step.

**2D, not 3D** was chosen separately and still stands: 3D wins the first 5 seconds and loses
the next 60 — occlusion, unreadable labels, node-hunting. A judge has to click a thread and
understand it.

#### Why Cytoscape won

| Factor | Cytoscape + fcose | sigma.js v4 |
|---|---|---|
| Zoom-tier labels | **native** — `min-zoomed-font-size` | native — `labelRenderedSizeThreshold` |
| Label collision at mid-zoom | no | **yes** — grid declutter |
| Renderer | **Canvas 2D (CPU)** | WebGL (GPU) |
| **No GPU on this box** | **native fit** | software rasteriser |
| Packages | **1 + 1 extension** | 4–5 |
| npm / build / watch | **none** | required |
| Styling | **declarative stylesheet** | imperative reducers |
| Author has shipped it | **yes, tuned params** | no |
| 1,546 nodes | comfortable | fine |
| 12,499 nodes | would struggle | fine — **irrelevant, messages are not drawn** |

Sigma's two advantages — WebGL throughput and label-grid declutter — only pay off at tens of
thousands of nodes **with a real GPU**. This machine has integrated graphics only
(`buildNOTES.md` §2.2), and the canvas draws 955 threads, not 12,499 messages.

#### fcose parameters (measured in the author's other app)

| Param | Value | Note |
|---|---|---|
| `nodeRepulsion` | 20000 | |
| `idealEdgeLength` | 60 | |
| `gravity` | 0.2 | |
| `nodeSeparation` | 75 | applies **between disconnected components** only; intra-component spacing comes from repulsion + edge length |
| `numIter` | 2500 | |
| `randomize` | **true** | **mandatory** — elements are re-added on every filter change and fresh nodes all start at (0,0), so without it the layout has no spread and clicks land on the wrong node |
| `zoomDistance` | 1.8 | multiplies the post-layout fit zoom; `fit: true` shrinks until everything is visible, which at this node count puts neighbours closer than a node's own diameter |
| `wheelSensitivity` | **3.8** | default 1.0 is genuinely slow — measured 1.047× per notch vs 1.181× for d3-force |

#### Style properties that do the work

| Property | Value | What it does |
|---|---|---|
| `min-zoomed-font-size` | 13 | skips text when `font-size × zoom` < 13 — this **is** the zoom LOD |
| `text-opacity` | 1 | paired with the above |
| `text-wrap` | `wrap` | multi-line labels |
| `text-max-width` | e.g. 120px | with `wrap` |
| `node:selected` | `border-width` / `border-color` / `shadow-*` | selection halo — Cytoscape has **no `box-shadow`**, `shadow-*` is the glow equivalent |
| `z-index` | 9999 on selected | so the halo is not occluded |

Label strings are **truncated upstream in the data model**, so the graph and the Viewer agree.

#### Zoom-to-node from a results row

Expose an imperative handle (`apiRef.current.focus(id)`):

```js
cy.elements().unselect()
n.select()
cy.animate({ center: { eles: n }, zoom: cy.zoom() * 1.3 }, { duration: 400 })
```

Multiplying the **current** zoom rather than setting an absolute level keeps the motion
proportional wherever the user already is.

#### Gotchas

- Selector grammar needs **spaces around operators**: `node[type = "entity"]`, not
  `node[type="entity"]`.
- `wheelSensitivity` defaults to 1.0 and is too slow — set 3.8.

#### Accepted costs

- **Labels can collide at mid-zoom.** `min-zoomed-font-size` hides small labels but does not
  collision-test boxes. Mitigation: raise the threshold, truncate titles upstream.
- **Canvas 2D glow** via `shadow-blur` is decent, not identical to WebGL bloom. At 955 nodes
  nobody will notice.
- **No graphology.** Cytoscape owns its own element model; there is no separate data layer.

#### Fallbacks kept open

`force-graph` 2D and `3d-force-graph` remain viable but give no label LOD for free.

**Rejected, with reasons:**

| Option | Why not |
|---|---|
| **sigma.js v4** | **Superseded 2026-11-15.** Not rejected on quality — rejected on cost. WebGL buys nothing without a GPU, and it needs npm + a build step for a feature Cytoscape has natively. |
| **Juggl** (Obsidian plugin) | **GPL-3** licence blocker, and Obsidian-only. 2D vs 3D was never the question. |
| `3d-force-graph` | MIT, author has used it. **Deselected on readability**: 3D loses labels to occlusion. |
| `@cosmograph/react` | **CC-BY-NC** — forbids commercial use |
| `vis-network` | dated, 84 MB unpacked, no label LOD |
| Cypress/G6/ECharts | enterprise-dashboard look, not space |

### 4.3 Labels appear by zoom — the actual requirement

**Stated by the author:** zoomed out, no labels. Zoom in, labels fade in depending on node
size. The user must **never** have to hover or click a node just to read its name.

Cytoscape gives this with `min-zoomed-font-size` (§4.2). The intent, so it is not lost:

- **Far zoom** — every label suppressed. A clean field of glowing dots.
- **Mid zoom** — only large nodes (big threads) carry labels. The graph stays legible.
- **Close zoom** — all labels appear, including small threads and correspondents.
- **Never** hover-to-reveal, never click-to-reveal. Labels are a zoom reward.

Tune `min-zoomed-font-size` upward if the mid-zoom view is still crowded.

### 4.4 Graph Style modal — a new requirement

Decided 2026-11-15: the title bar gets a **Graph Style** button opening a modal that
adjusts force simulation and visuals **live**. This is the visible payoff of keeping all
style values in one config object (§7).

Suggested controls — following the `PHYSICS` block in `AxiomLC/frontal-lobe`'s
`ui/src/config/theme.js`:

| Group | Controls |
|---|---|
| Physics | fcose `nodeRepulsion`, `idealEdgeLength`, `gravity`, `nodeSeparation`, `numIter`; re-run layout |
| Labels | `min-zoomed-font-size`, label font size, label colour, `text-max-width` |
| Visual | node size, edge opacity, edge width, glow (`shadow-blur`), background haze |
| Layout | freeze / re-run, reset to defaults |
| Filter | which node types are drawn (**view-only — never narrows a query**) |

Persist to `localStorage` so a reload keeps the chosen look.

---

## 5. Viewer — two content states

Ported from `AxiomLC/frontal-lobe`'s `ui/src/components/Viewer.jsx`, which solved this well.
The state machine is worth copying almost verbatim:

- one `{stack, idx}` object so push / dedupe / truncate / cap are atomic
- consecutive duplicate **node** clicks deduped; a re-run of the same search is a new state
- a new action after Back **truncates the forward path**
- stack capped at 50, purged on browser refresh

| State | Kind | Trigger | Shows |
|---|---|---|---|
| **state0** | `results` | search bar, or AI returning hits | a table of results, one row per node |
| **state1** | `node` | graph node click, or a result row click | that node's meta + content |
| **Back** | — | Viewer's own back button | pure state restore |

**What changes from frontal-lobe:** chunks become **messages**; the Connections popdown
becomes the thread's **correspondents**; the cognition/mint card is dropped entirely.

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

In Cytoscape terms: halo = `node:selected` (border + `shadow-*` + `z-index: 9999`);
fly-to = the `cy.animate({ center, zoom: cy.zoom() * 1.3 })` call in §4.2.

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
3. **Kill the spring.** fcose settles once; do not re-run the layout on every interaction.
   A graph that keeps bobbing looks like a physics toy.
4. **Curved, low-opacity edges** (~8–20%). Straight lines on dark read as a wireframe.
   Cytoscape: `curve-style: bezier`, `opacity: 0.15`.
5. **Labels are a zoom reward**, not decoration. `min-zoomed-font-size` hides them at fit
   zoom and reveals them as you zoom in. Hash colours per community so the picture looks
   identical every load.
6. **Timeline reveal on load** — nodes bloom outward in `ts_utc` order over ~2.5 s.
   Highest impact per effort for a demo. Optional, toggleable.

### 6.3 Typography

Inter (or system-ui) at 12–13px for dense panes, 11px meta with `tabular-nums` for
timestamps. **Slightly rounded corners** — radii 8–12px, 12px dominant. Borders at
`rgb(255 255 255 / .06–.09)` rather than lighter greys.

**Deliberately different from `frontal-lobe`:** that app is black/red with Courier + Georgia
and square corners. This one is black/green with Inter and rounded corners, so it does not
read as the same product.

---

## 7. Dev knobs at the top

**One config object at the top of the UI entry script**, every tunable value, heavily
commented. Same pattern as `AxiomLC/optic-nerve-ui`'s `src/config/theme.js` and
`frontal-lobe`'s `ui/src/config/theme.js` — both are worth reading as the template.

Those files are the reference for style: each value carries a comment explaining what it
does and what range is sane, e.g. `nodeRepulsion: 20000, // 8000=tight, 40000=airy`.
Copy that discipline.

**The config object is also what the Graph Style modal writes to** (§4.4), and it persists
to `localStorage`.

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
`buildNOTES.md`). **That layer is now implemented** — 10 tools registered, each with a
derived JSON schema.

What the chat is offered (deliberately five, not ten — a local 8B model given overlapping
options picks the wrong one):

| Tool | Answers |
|---|---|
| `evidence_counts` | "how many messages / threads / people do I have" |
| `search_messages` | "find messages about X" |
| `thread_arc` | "show me the conversation with X" (needs a `thread_key`) |
| `message_view` | "what did they say" (one message) |
| `run_cypher` | anything structural the others cannot do |

**`graph_slice` is not offered to the chat.** It is the canvas payload (1,546 nodes); an 8B
model cannot read it. Tool results are capped at 4,000 chars and a truncated result says so.

**`think: false` is not honoured by `lfm2.5:8b`** — it writes `<think​>` blocks into
`content` anyway. The server strips them (§8.2).

---

## 9. Scaffold to follow

**`AxiomLC/frontal-lobe`** (private) — the author's own code, and the closer match. Read
`ui/src/App.jsx`, `components/Viewer.jsx`, `components/VoicePanel.jsx` and
`config/theme.js` before writing anything.

**Stack: React + esbuild.** React because the Viewer state machine ports almost verbatim;
esbuild because it is one command with no dev server and no config file.

```
package.json                 react, react-dom, lucide-react, esbuild
app/ui/src/
  main.jsx                   entry; mounts App
  App.jsx                    shell; owns haloId, flyToId, viewerPush, chatOpen
  components/
    CommandBar.jsx           title bar: search, Cypher chip, AI/Log/Ingest/Setup/Style
    GraphCanvas.jsx          Cytoscape + fcose, label LOD, halo, fly-to
    Viewer.jsx               the state timeline — the important one
    ChatPanel.jsx            AI chat + localStorage history (text only)
    modals/
      LogModal.jsx           placeholder
      IngestModal.jsx        placeholder
      SetupModal.jsx         placeholder
      GraphStyleModal.jsx    placeholder
  config/
    theme.js                 EVERY tunable, commented
    nodeTypes.js             type → colour/size/toggle
  lib/api.js                 thin fetch client to /api
  styles/globals.css
app/static/
  index.html                 loads dist/app.js
  vendor/                    cytoscape.min.js + cytoscape-fcose.js (committed)
  dist/app.js                BUILT — committed
```

**Build:** `npm run build` (one-shot) or `npm run watch` (rebuild on save, ~50 ms, opens
no port). `dist/app.js` is **committed** so a clone runs without npm.

**No extra server.** esbuild is a compiler, not a server. `python -m app` on `:8000` is the
only process that listens.

**`AxiomLC/optic-nerve-ui`** (private) — same lineage, more polished graph styling.

**Do not** carry over from either: Cloudflare Pages, `wrangler.toml`, Supabase, Supabase
auth/dept scoping, or any cloud LLM leg. Those are the other projects' constraints, not
this one. This runs on `localhost` against `store/graph.rl`.

---

## 10. Build order

Steps 1–2 are **done**.

1. ~~`relate_comms/tools.py`~~ — 10 tools, 30 tests.
2. ~~FastAPI app~~ — `/api/health`, `/stats`, `/types`, `/graph`, `/thread/{key}`,
   `/message/{key}`, `/search`, `/chat`, `/ingest`.
3. **Scaffold** — `package.json`, esbuild, `theme.js`, `api.js`, vendored Cytoscape.
4. **Canvas** — Cytoscape + fcose, threads + correspondents, palette, `min-zoomed-font-size`
   label LOD, halo on select, fly-to from a result row.
5. **Viewer** — two states + back + halo/fly-to split, messages paged.
6. **Search bar** → Viewer state0.
7. **AI chat** — Ollama, `localStorage` history, tool trace shown, results land in state0.
8. **Modals** — Log · Ingest · Setup · Graph Style (placeholders first, wire later).
9. **Polish** — grain, haze, timeline reveal, label fade.

**3–7 are the demo.** Modals are placeholders until those work.

---

## 11. Open questions

- **Timeline reveal** — include or skip? Cheap, high impact, but it delays first paint.
- **Chat panel width** — 25vw like the Viewer, or narrower? Currently 25vw.
- **`Person` node.** The UI shows Correspondents today. Cross-platform identity (`Person`,
  `SENT`) does not exist yet — see `buildNOTES.md` §3.2. Do not design around it.
- **Chat tool selection.** `lfm2.5:8b` still picks the wrong tool on some questions. The
  system prompt now carries a "which tool to use" table; needs testing on real questions.

**Settled since the last revision:** React + esbuild (not Vite, not single HTML);
Cytoscape (not sigma); `dist/` is committed; no extra server.

---

## 12. Do not relitigate

| Decision | Why |
|---|---|
| **Cytoscape.js + fcose, 2D, not 3D** | author's call, 2026-11-15 (revised). Native `min-zoomed-font-size`, no build step for the library, Canvas 2D suits a box with no GPU |
| **React + esbuild** | Viewer ports verbatim from `frontal-lobe`; esbuild is one command, no dev server |
| **`dist/app.js` is committed** | a clone runs without npm |
| **No extra server** | esbuild compiles and exits; `python -m app` is the only listener |
| **Threads drawn, messages not** | 12,499 nodes is not drawable; 955 is |
| **AI left, graph centre, Viewer right** | author's call; all full height, `25vw` / `flex: 1` / `25vw` |
| **Chat has a toggle, Viewer does not** | author's call |
| **Logs are a modal, not a drawer** | author's call |
| **Juggl is out** | GPL-3 + Obsidian-only. Nothing to do with 2D or 3D |
| **Local `localhost` only** | no deployment, no Cloudflare |
| **Ollama, never a cloud key** | privacy is the product |
| **Back never moves the camera** | from `frontal-lobe`; clicking around must not yank the view |
| **UI state never narrows an agent's query** | `buildNOTES.md` §5.2 |
| **Every value in one config object** | the Graph Style modal depends on it |
| **Rounded corners, black/green, Inter** | deliberately not `frontal-lobe`'s square black/red Courier look |
