# ai_visual_graph_tool

Headless geometry instrument for the canvas. The IDE agent runs it; the numbers it
prints replace screenshots for every "is the geometry right" question. See
`UIREADME.md` §12 for the fcose facts it exists to measure, and for what it cannot
do (it never replaces the owner's eye for "does it look right", and it cannot see
render-pipeline breakage).

## What it does

Runs the **same pipeline as `GraphCanvas.jsx`** — bag construction (membership =
`:Merged`, inverted), fcose with `theme.physics`, `placeBagsOnRing`, no fit —
headless in Node, against the **real `graph_slice()` payload** read straight from
the store via `relate_comms.tools` (no HTTP, no server).

Then it measures:

- edge lengths (p50/p90/p99/max), tagged `bag-bag` / `bag-bridge` /
  `bridge-bridge` — the §6 confirmation test as numbers
- the longest bag↔bridge edges specifically (the §6 signature)
- the ring: radius computed, each bag's centre distance before → after, shift size
- bridges: distance from each merged node to every bag it touches vs that bag's
  reach — "did the ring yank the bag away from its bridge", quantified
- bags: children, centre distance, footprint box

## Usage

From the repo root:

```bash
python tools/ai_visual_graph_tool/run.py                    # theme defaults, ring on
python tools/ai_visual_graph_tool/run.py --no-ring          # the §6 ring-off experiment
python tools/ai_visual_graph_tool/run.py --set physics.gravityCompound=5
python tools/ai_visual_graph_tool/run.py --set layout.bagRingSpread=1.4 --runs 5
python tools/ai_visual_graph_tool/run.py --no-api           # reuse last_payload.json
```

`--set group.key=value` overrides any theme value for one run (JSON-parsed, so
`true`/`1.5`/"strings" all work). `--sort quiet --limit 1000` changes the slice the
way the Canvas modal would. `--runs N` (default 3) re-runs the randomized layout and
reports the median run — one run is one draw, medians are the signal.

## Setup

`cytoscape` and `cytoscape-fcose` resolve from the repo root `node_modules`
(already installed for the UI build). The vendored `layout-base.js` / `cose-base.js`
are loaded from `app/static/vendor/` for the smart-edge-length constant, exactly as
`setSmartEdgeLength()` does in the browser.

If the store is unreadable, `--no-api` falls back to `last_payload.json` — the
payload of the last successful run, which the probe rewrites each time.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | measured |
| 1 | store unreadable / empty and no fallback payload |
| 2 | `node` not on PATH |
| 3 | probe crashed (stack trace printed) |
