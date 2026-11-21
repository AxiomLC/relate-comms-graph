/**
 * ai_visual_graph_tool — the geometry instrument.
 *
 * Why this exists (CytoGravityRecommend.md §0): debugging the canvas by screenshot
 * means the agent cannot read the saved slider values and "looks long" is not a
 * number. This script runs the SAME pipeline the browser runs — bag construction,
 * fcose with the theme physics, placeBagsOnRing, fit — headless, against the REAL
 * graph_slice() payload, and prints measurements instead of pixels.
 *
 * What it measures:
 *   - edge lengths, sorted, tagged by type and by which sides are outside-bags
 *   - the ring radius placeBagsOnRing computes, and each bag's centre distance
 *     before vs after the ring move
 *   - each bridge (merged node): distance to each bag it touches, before vs after
 *     the ring move — the §6 leading hypothesis, quantified
 *   - per-bag child spread (how sprawling each cluster is)
 *
 * Usage (from the repo root):
 *   python tools/ai_visual_graph_tool/run.py                 # theme defaults, ring on
 *   python tools/ai_visual_graph_tool/run.py --no-ring       # the §6 experiment
 *   python tools/ai_visual_graph_tool/run.py --set physics.gravityCompound=5
 *
 * The browser parity note: fcose positions are seeded by `randomize`, so a single
 * run is one draw from a distribution. `--runs N` repeats the layout N times and
 * reports per-metric median + spread, which is the honest way to compare two
 * settings.
 */
"use strict";

const fs = require("fs");
const path = require("path");
const vm = require("vm");
const Module = require("module");
const { execFileSync } = require("child_process");

const Cytoscape = require("cytoscape");

const ROOT = path.resolve(__dirname, "..", "..");
const VENDOR = path.join(ROOT, "app", "static", "vendor");
const THEME_PATH = path.join(ROOT, "app", "ui", "src", "config", "theme.js");

/* ------------------------------------------------------------- vendored UMDs ---
 * The vendored files are webpack UMD bundles whose interop was built for the
 * BROWSER: `layoutBase`/`coseBase` publish on `window` and fcose's inner
 * `require("cose-base")` is satisfied by script-tag order, not by npm. Under
 * plain `require` the webpack runtime hands back an empty object.
 *
 * So load them the way the browser does: evaluate each bundle in a fresh vm
 * context that has `window`/`global`/`self`, pre-seeded with the earlier bundles
 * under the names webpack's `require` asks for. This is the headless equivalent
 * of the browser's script-tag order:
 *   layout-base.js  → window.layoutBase
 *   cose-base.js    → window.coseBase          (needs layout-base)
 *   cytoscape-fcose → window.cytoscapeFcose    (needs cose-base)
 * The mutation targets (`FDLayoutConstants`, `CoSEConstants`) are then reachable,
 * and the browser's `setSmartEdgeLength()` parity holds.
 */
function loadVendorBundle(source, file) {
  vm.runInContext(source, sharedWindow, { filename: file });
}

/* One SHARED context for all bundles — this is the browser parity point that is
 * easy to miss. In the page every script tag sees the same `window`; cose-base's
 * factory reads `root["layoutBase"]` off THAT shared object, and its internals
 * reach classes from layout-base only through what the factory captured. Loading
 * each bundle in its own fresh context gives the factory a `root` that has no
 * `layoutBase` on it and cose-base crashes on `undefined.prototype`. Same object,
 * script order, no `module`/`exports`/`define` (which would steer the UMD toward
 * CommonJS/AMD branches whose inner require("…") cannot resolve headless). */
const sharedWindow = { console, setTimeout, clearTimeout, Math, JSON, Date };
sharedWindow.global = sharedWindow;
sharedWindow.self = sharedWindow;
sharedWindow.window = sharedWindow;
vm.createContext(sharedWindow);

loadVendorBundle(fs.readFileSync(path.join(VENDOR, "layout-base.js"), "utf8"), "layout-base.js");
loadVendorBundle(fs.readFileSync(path.join(VENDOR, "cose-base.js"), "utf8"), "cose-base.js");
loadVendorBundle(fs.readFileSync(path.join(VENDOR, "cytoscape-fcose.js"), "utf8"), "cytoscape-fcose.js");

const layoutBase = sharedWindow.layoutBase;
const coseBase = sharedWindow.coseBase;
const fcoseRegister = sharedWindow.cytoscapeFcose;
if (!layoutBase || !coseBase || !fcoseRegister) {
  throw new Error(
    `vendored bundles failed to load: layoutBase=${!!layoutBase} coseBase=${!!coseBase} fcose=${!!fcoseRegister}`,
  );
}
Cytoscape.use(fcoseRegister);

/* ------------------------------------------------------------------ theme ---
 * `theme.js` is an ES module; read it and eval the THEME export. Cheap, and it
 * keeps ONE source of truth: the script always runs with the file the browser
 * builds from, defaults included. A `--set group.key=value` override is applied
 * on top, so a run can test "gravityCompound 5" without editing the file.
 *
 * ON TOP of the defaults sits `baseline.json` — the owner's current best slider
 * positions, transcribed from screenshots of the live Gravity panel (the values
 * live in the browser's localStorage, which no outside process can read; the
 * screenshots are the transport). This is what makes probe runs comparable to
 * what the owner actually sees. `--stock` skips the baseline; `--save-baseline`
 * freezes the current effective theme into it.
 */
const BASELINE_PATH = path.join(__dirname, "baseline.json");

function deepMerge(target, source) {
  for (const [key, value] of Object.entries(source || {})) {
    if (value && typeof value === "object" && !Array.isArray(value)) {
      target[key] = deepMerge(target[key] ?? {}, value);
    } else {
      target[key] = value;
    }
  }
  return target;
}

function loadBaseline() {
  try {
    return JSON.parse(fs.readFileSync(BASELINE_PATH, "utf8"));
  } catch {
    return null;
  }
}

function loadTheme(overrides, { useBaseline = true } = {}) {
  let source = fs.readFileSync(THEME_PATH, "utf8");
  // The file is an ES module; strip `export ` markers so the object literal
  // evaluates inside a plain Function. Anything fancier (real ESM import) would
  // need a build step this tool deliberately avoids.
  source = source.replace(/\bexport\s+/g, "");
  const module_ = { exports: {} };
  // The object literal's top-level `const` declarations land on the function
  // scope, not on `exports` — collect the pieces explicitly rather than hoping
  // `THEME` itself survives.
  const fn = new Function("module", "exports", source + "\n;module.exports = { THEME };");
  fn(module_, module_.exports);
  const theme = JSON.parse(JSON.stringify(module_.exports.THEME));
  const baseline = useBaseline ? loadBaseline() : null;
  if (baseline) deepMerge(theme, baseline);
  for (const [dotted, raw] of Object.entries(overrides || {})) {
    const parts = dotted.split(".");
    let target = theme;
    while (parts.length > 1) {
      target = target[parts.shift()];
    }
    const value = JSON.parse(raw === undefined ? "null" : raw);
    if (target[parts[0]] === undefined) {
      // Tolerate unknown layout.* keys by creating them — the probe must accept
      // future tunables (e.g. layout.bridgePull) that the theme file does not yet
      // carry, while still rejecting physics.* typos.
      if (parts[0] === "layout") {
        target[parts[0]] = value;
      } else {
        throw new Error(`unknown theme key: ${dotted}`);
      }
    }
    target[parts[0]] = value;
  }
  return theme;
}

/* ------------------------------------------------------------------ input --- */
/* The payload comes from the store via the library, exactly as the API serves it.
 * Falls back to a JSON file if Python is unavailable, so the geometry half of the
 * tool still runs offline. */
function fetchPayload(useApi, filters) {
  if (!useApi) {
    const fallback = path.join(__dirname, "last_payload.json");
    if (!fs.existsSync(fallback)) {
      throw new Error("no last_payload.json and --no-api given; cannot load data");
    }
    return JSON.parse(fs.readFileSync(fallback, "utf8"));
  }
  // The payload is spliced in as a literal, NOT via argv: argv would be a shell
  // concern and the embedded JSON quotes would be fragile. `ROOT` is a literal
  // path; `sliceJson` is a JSON document (not user text), so a template literal
  // splice is safe here.
  const sliceJson = JSON.stringify(filters);
  const py = `
import json, sys
sys.path.insert(0, r'''${ROOT.replace(/\\/g, "/")}''')
from relate_comms import tools
slice_args = json.loads(r'''${sliceJson}''')
payload = tools.graph_slice(**slice_args)
print("__PAYLOAD__" + json.dumps(payload))
`;
  const args = ["-c", py];
  const out = execFileSync("python", args, {
    cwd: ROOT,
    encoding: "utf8",
    maxBuffer: 64 * 1024 * 1024,
  });
  for (const line of out.split("\n")) {
    if (line.startsWith("__PAYLOAD__")) {
      return JSON.parse(line.slice("__PAYLOAD__".length));
    }
  }
  throw new Error("python produced no payload; is the store built?");
}

/* --------------------------------------------------- replicate the browser ---
 * Bag construction, mirroring GraphCanvas.jsx's elements memo:
 *   - membership = `:Merged`, INVERTED: a node with exactly one platform is
 *     bagged under it; everything else goes in the MERGED bag (CytoGravity §9).
 *   - the test reads platforms, and `merged` is authoritative when present.
 *   - a bag is created only for a platform that still has a child.
 */
const MERGED_BAG_ID = "bag:merged";
function buildElements(payload, bagsOn) {
  const nodes = (payload.nodes || []).map((node) => {
    // Size: the stylesheet maps width/height from the node's tier size. The probe
    // cannot recompute tiers without importing nodeTypes.js (browser-only), so a
    // monotone proxy is used: threads by message_count, correspondents by
    // thread_count. Only the RELATIVE sizes matter for fcose's packing math.
    const count = Math.max(1, node.message_count || node.thread_count || 1);
    const size = Math.min(66, 12 + 3 * Math.sqrt(count));
    return {
      group: "nodes",
      data: {
        id: node.id,
        label: node.label || node.id || "",
        type: node.type,
        platform: node.platform || "",
        platforms: node.platforms || null,
        merged: !!node.merged,
        message_count: node.message_count || 0,
        size: node.type === "Bag" ? 40 : size,
      },
    };
  });
  const edges = (payload.edges || []).map((edge) => ({
    group: "edges",
    data: {
      id: `${edge.type}:${edge.source}->${edge.target}`,
      source: edge.source,
      target: edge.target,
      type: edge.type,
    },
  }));

  if (!bagsOn) return [...nodes, ...edges];

  const platformsInUse = new Set();
  let mergedBagInUse = false;
  for (const node of nodes) {
    const data = node.data;
    if (data.type === "Bag") continue;
    const platforms = Array.isArray(data.platforms) && data.platforms.length
      ? data.platforms
      : (data.platform ? [data.platform] : []);
    const platform = platforms.length === 1 ? platforms[0] : "";
    if (!data.merged && platform) {
      data.parent = `bag:${platform}`;
      platformsInUse.add(platform);
    } else {
      data.parent = MERGED_BAG_ID;
      mergedBagInUse = true;
    }
  }
  const bagNodes = [];
  for (const platform of platformsInUse) {
    bagNodes.push({
      group: "nodes",
      classes: "synthetic bag",
      data: { id: `bag:${platform}`, type: "Bag", platform, size: 40 },
    });
  }
  if (mergedBagInUse) {
    bagNodes.push({
      group: "nodes",
      classes: "synthetic bag",
      data: { id: MERGED_BAG_ID, type: "Bag", platform: "", size: 40 },
    });
  }
  return [...bagNodes, ...nodes, ...edges];
}

/* The ring, mirroring GraphCanvas.jsx `placeBagsOnRing` exactly, including the
 * NaN guard and the legend ordering. Returns measurements instead of nothing so
 * the script can report what the ring actually did. */
const LEGEND_PLATFORMS = [
  "messenger", "telegram", "whatsapp", "linkedin", "email", "outlook", "sms",
];

function placeBagsOnRing(cy, spread) {
  // Platform bags only — the merged bag is the centre tier (§9) and is excluded
  // exactly as GraphCanvas.jsx excludes it.
  const bags = cy.nodes('[type = "Bag"]').filter((bag) => bag.id() !== MERGED_BAG_ID);
  if (bags.length < 2) return { radius: null, moved: [] };

  const widths = bags.map((bag) => Math.max(bag.outerWidth(), bag.outerHeight()));
  const widest = Math.max(...widths);
  const base = Number.isFinite(widest) && widest > 0 ? widest * 1.6 : 260;
  const radius = Math.max(base, 260) * (spread || 1);

  const ordered = bags.toArray().sort((a, b) => {
    const ai = LEGEND_PLATFORMS.indexOf(a.data("platform"));
    const bi = LEGEND_PLATFORMS.indexOf(b.data("platform"));
    return (ai < 0 ? LEGEND_PLATFORMS.length : ai) - (bi < 0 ? LEGEND_PLATFORMS.length : bi);
  });

  const moved = [];
  cy.batch(() => {
    ordered.forEach((bag, index) => {
      const children = bag.children();
      if (!children.length) return;

      const angle = (2 * Math.PI * index) / ordered.length - Math.PI / 2;
      const target = { x: Math.cos(angle) * radius, y: Math.sin(angle) * radius };

      const box = children.boundingBox();
      const cx = box.x1 + box.w / 2;
      const cy_ = box.y1 + box.h / 2;
      const dx = target.x - cx;
      const dy = target.y - cy_;
      if (!Number.isFinite(dx) || !Number.isFinite(dy)) return;
      const before = Math.hypot(cx, cy_);
      children.forEach((child) => {
        const position = child.position();
        child.position({ x: position.x + dx, y: position.y + dy });
      });
      moved.push({
        platform: bag.data("platform"),
        children: children.length,
        centreDistanceBefore: round(before),
        centreDistanceAfter: round(Math.hypot(target.x, target.y)),
        shift: round(Math.hypot(dx, dy)),
      });
    });
  });
  return { radius: round(radius), moved };
}

/* Bridges pulled to the ring — mirror of GraphCanvas.jsx pullBridgesToRing. After
 * the ring is applied, each outside node moves partway (damping) toward the
 * weighted centroid of the bags its edges reach. Reported so runs can be compared
 * with and without it. */
function pullBridgesToRing(cy, damping) {
  if (!(damping > 0)) return [];
  const bags = cy.nodes('[type = "Bag"]');
  if (!bags.length) return [];

  const centres = new Map();
  bags.forEach((bag) => {
    const children = bag.children();
    if (!children.length) return;
    const box = children.boundingBox();
    centres.set(bag.id(), { x: box.x1 + box.w / 2, y: box.y1 + box.h / 2 });
  });

  const moved = [];
  cy.batch(() => {
    const outside = cy.nodes().filter(
      (n) => !n.isParent() && n.data("type") !== "Bag" && !n.data("parent"),
    );
    outside.forEach((node) => {
      const weights = new Map();
      let total = 0;
      node.connectedEdges().forEach((edge) => {
        const other = edge.source().id() === node.id() ? edge.target() : edge.source();
        const centre = centres.get(other.data("parent"));
        if (!centre) return;
        weights.set(centre, (weights.get(centre) || 0) + 1);
        total += 1;
      });
      if (!total) return;
      let cx = 0;
      let cyy = 0;
      for (const [centre, weight] of weights) {
        cx += centre.x * weight;
        cyy += centre.y * weight;
      }
      cx /= total;
      cyy /= total;
      const pos = node.position();
      const dx = cx - pos.x;
      const dy = cyy - pos.y;
      if (!Number.isFinite(dx) || !Number.isFinite(dy)) return;
      node.position({ x: pos.x + dx * damping, y: pos.y + dy * damping });
      moved.push({ id: node.id(), pulledBy: total, shift: round(Math.hypot(dx, dy) * damping) });
    });
  });
  return moved;
}

/* ------------------------------------------------------------------ layout --- */
/*
 * ASYNC, and that is the whole point. fcose's `run()` returns BEFORE it has placed
 * anything: the solver runs on a timer and positions land when `layoutstop` fires.
 * The first version of this file snapshotted straight after `run()` and therefore
 * recorded every node at (0,0) — so every measurement it printed described the ring
 * translating a pile at the origin, not a layout. The browser never had this bug
 * because `runLayout()` hangs its `finish()` off `layoutstop`.
 *
 * So: resolve on `layoutstop`, and let `main` await it.
 *
 * AND `layoutstop` IS STILL TOO EARLY. Measured 2026-11-21: the event fires with
 * every node at (0,0); the coordinates are written back a few hundred ms later
 * (the solver's final `setPositions` runs on a follow-up timer). The browser gets
 * away with it because `finish()` is a viewport op that reads positions after the
 * render loop has already ticked. Headless there is no render loop, so the probe
 * must POLL until the positions stop being the origin pile — see `settle()`.
 */
function runOnce(cy, theme) {
  const { physics, layout } = theme;

  // Mirror `setSmartEdgeLength`: mutate the vendored constants BEFORE the layout
  // object is constructed — the constant is read in the FDLayout constructor.
  let smartApplied = false;
  for (const constants of [layoutBase.FDLayoutConstants, coseBase.CoSEConstants]) {
    if (constants) {
      constants.DEFAULT_USE_SMART_IDEAL_EDGE_LENGTH_CALCULATION = !!physics.smartEdgeLength;
      smartApplied = true;
    }
  }

  const options = {
    name: layout.name,
    quality: "default",
    animate: false,
    fit: false, // fit is a VIEWPORT op, not geometry; positions are what matter
    randomize: physics.randomize,
    nodeRepulsion: physics.nodeRepulsion,
    idealEdgeLength: physics.idealEdgeLength,
    gravity: physics.gravity,
    gravityCompound: physics.gravityCompound,
    gravityRangeCompound: physics.gravityRangeCompound,
    nodeSeparation: physics.nodeSeparation,
    numIter: physics.numIter,
    nodeDimensionsIncludeLabels: !!physics.nodeDimensionsIncludeLabels,
    packComponents: true,
    uniformNodeDimensions: false,
  };

  // Positions BEFORE the solver, so the ring's effect can be isolated.
  const pre = snapshotPositions(cy);

  return new Promise((resolve, reject) => {
    let instance;
    try {
      instance = cy.layout(options);
    } catch (error) {
      reject(error);
      return;
    }
    instance.one("layoutstop", () => {
      settle(cy).then(() => {
      try {
        const postSolver = snapshotPositions(cy);

        // The ring mutation and its report are one pass: re-deriving the report
        // after a second ring run would move the bags again and lie about what
        // happened.
        let ringInfo = { radius: null, moved: [], applied: false };
        if (layout.bagRing) {
          ringInfo = placeBagsOnRing(cy, layout.bagRingSpread);
          ringInfo.applied = true;
          // NO bridge pull. The app's `pullBridgesToRing` was tried and REVERTED
          // (CytoGravity §0 — it blanked the live canvas). The probe kept applying
          // it, so every run since the revert measured a pipeline the browser does
          // not run. `pullBridgesToRing` stays below for reference only.
        }
        resolve({ pre, postSolver, postRing: snapshotPositions(cy), ringInfo, smartApplied });
      } catch (error) {
        reject(error);
      }
      });
    });
    instance.run();
  });
}

/*
 * Wait until fcose has actually written its coordinates back.
 *
 * `layoutstop` fires while every node is still at (0,0) — the write-back is a
 * follow-up timer. Polling for "more than one distinct position" is the honest
 * test: a real layout of a connected graph never collapses to a single point, and
 * a graph that genuinely has one node needs no wait at all.
 */
function settle(cy, { timeoutMs = 20000, intervalMs = 25 } = {}) {
  const distinct = () => {
    const seen = new Set();
    cy.nodes().forEach((node) => {
      const position = node.position();
      seen.add(`${Math.round(position.x)},${Math.round(position.y)}`);
    });
    return seen.size;
  };
  if (cy.nodes().length < 2) return Promise.resolve();
  const started = Date.now();
  return new Promise((resolve) => {
    const tick = () => {
      if (distinct() > 1 || Date.now() - started > timeoutMs) {
        // One more tick so the last node's write is not half-applied.
        setTimeout(resolve, intervalMs);
        return;
      }
      setTimeout(tick, intervalMs);
    };
    tick();
  });
}

function snapshotPositions(cy) {
  const map = {};
  cy.nodes().forEach((node) => {
    map[node.id()] = { x: round(node.position("x")), y: round(node.position("y")) };
  });
  return map;
}

/* ---------------------------------------------------------------- measures --- */
function measure(cy, payload) {
  const bags = cy.nodes('[type = "Bag"]');
  const bagByPlatform = {};
  bags.forEach((bag) => { bagByPlatform[bag.data("platform")] = bag; });

  // Three populations now, not two: a PLATFORM bag (on the ring), the MERGED bag
  // (the centre tier), and anything with no parent (bags off). "Has a parent" no
  // longer means "is in a platform bag", so the classification reads the parent id.
  const parentOf = {};
  cy.nodes().forEach((node) => {
    if (node.isParent() || node.data("type") === "Bag") return;
    parentOf[node.id()] = node.data("parent") || "";
  });
  const isBagged = {};
  for (const [id, parent] of Object.entries(parentOf)) {
    isBagged[id] = !!parent && parent !== MERGED_BAG_ID;
  }
  const isMergedBagged = {};
  for (const [id, parent] of Object.entries(parentOf)) {
    isMergedBagged[id] = parent === MERGED_BAG_ID;
  }

  // --- edges: length, type, and which populations each side belongs to
  const edgeRows = [];
  cy.edges().forEach((edge) => {
    const source = edge.source();
    const target = edge.target();
    if (source.data("type") === "Bag" || target.data("type") === "Bag") return;
    const srcBagged = isBagged[source.id()];
    const tgtBagged = isBagged[target.id()];
    const srcMergedBag = isMergedBagged[source.id()];
    const tgtMergedBag = isMergedBagged[target.id()];
    const kind = srcBagged && tgtBagged ? "bag-bag"
      : srcBagged && tgtMergedBag ? "bag-merged"
      : srcMergedBag && tgtBagged ? "merged-bag"
      : srcMergedBag && tgtMergedBag ? "merged-merged"
      : srcBagged && !tgtBagged && !tgtMergedBag ? "bag-bridge"
      : !srcBagged && !srcMergedBag && tgtBagged ? "bridge-bag"
      : "bridge-bridge";
    edgeRows.push({
      length: edge.isEdge()
        ? round(Math.hypot(
            edge.source().position("x") - edge.target().position("x"),
            edge.source().position("y") - edge.target().position("y"),
          ))
        : 0,
      type: edge.data("type"),
      kind,
      source: source.id(),
      target: target.id(),
      crossBag: srcBagged !== tgtBagged,
      // The §9 metric: how far a merged node sits from the platform bag it talks to.
      // Under the merged-bag design these are the edges that must get SHORT.
      mergedSpan: (srcBagged && tgtMergedBag) || (srcMergedBag && tgtBagged),
    });
  });
  edgeRows.sort((a, b) => b.length - a.length);

  // --- merged-bag members: distance to each PLATFORM bag they connect to
  // Connectivity is read from the PAYLOAD's edges (type + endpoints), not from
  // cytoscape classes, so the same rule applies with and without bags.
  //
  // Under §9 the population to watch is the merged bag's members: each one should
  // sit near the centre, so its distance to every platform bag it talks to is the
  // number the design is supposed to shrink. With bags off there is no merged bag,
  // and every merged node is its own row — the old behaviour, kept for comparison.
  const platformsByNode = {};
  for (const node of payload.nodes || []) {
    platformsByNode[node.id] = Array.isArray(node.platforms) && node.platforms.length
      ? node.platforms
      : (node.platform ? [node.platform] : []);
  }
  const bagEdgesByBridge = {};
  for (const edge of payload.edges || []) {
    for (const [from, to] of [[edge.source, edge.target], [edge.target, edge.source]]) {
      if (!isBagged[to]) continue;
      const toBag = bagByPlatform[(platformsByNode[to] || [])[0]];
      if (!toBag) continue;
      // `from` is the node being measured: a merged-bag member, or (bags off) any
      // node without a platform bag.
      if (!isMergedBagged[from] && isBagged[from]) continue;
      (bagEdgesByBridge[from] = bagEdgesByBridge[from] || new Map())
        .set(toBag.id(), (bagEdgesByBridge[from].get(toBag.id()) || 0) + 1);
    }
  }
  const bridgeRows = [];
  for (const bridgeId of Object.keys(bagEdgesByBridge)) {
    const node = cy.getElementById(bridgeId);
    if (!node || !node.length || node.data("type") === "Bag") continue;
    const touch = [];
    for (const [bagId, count] of bagEdgesByBridge[bridgeId]) {
      const bag = cy.getElementById(bagId);
      if (!bag.length) continue;
      const children = bag.children();
      const box = children.boundingBox();
      const centre = { x: box.x1 + box.w / 2, y: box.y1 + box.h / 2 };
      const distance = round(Math.hypot(
        node.position("x") - centre.x,
        node.position("y") - centre.y,
      ));
      // Rough reach: the bag's half-diagonal. A bridge further than this is
      // outside its bag's footprint, which is the readable definition of "far".
      const reach = round(0.5 * Math.hypot(box.w, box.h));
      touch.push({ bag: bagId.replace(/^bag:/, ""), edgeCount: count, distance, reach });
    }
    touch.sort((a, b) => b.distance - a.distance);
    bridgeRows.push({ bridge: bridgeId, merged: !!node.data("merged"), touch });
  }
  bridgeRows.sort((a, b) => b.touch[0].distance - a.touch[0].distance);

  // --- bags: spread of each cluster, overlap between bag footprints
  const bagRows = [];
  bags.forEach((bag) => {
    const children = bag.children();
    const box = children.boundingBox();
    const centre = { x: box.x1 + box.w / 2, y: box.y1 + box.h / 2 };
    bagRows.push({
      // The merged bag has no platform; name it so the report is readable.
      platform: bag.id() === MERGED_BAG_ID ? "merged" : bag.data("platform"),
      mergedBag: bag.id() === MERGED_BAG_ID,
      children: children.length,
      centreDistance: round(Math.hypot(centre.x, centre.y)),
      width: round(box.w),
      height: round(box.h),
    });
  });
  bagRows.sort((a, b) => b.centreDistance - a.centreDistance);

  // --- headline numbers
  const lengths = edgeRows.map((row) => row.length);
  const quantile = (sorted, q) => {
    if (!sorted.length) return null;
    const index = Math.min(sorted.length - 1, Math.floor(q * sorted.length));
    return sorted[index];
  };
  const spans = edgeRows.filter((edge) => edge.mergedSpan);
  const mergedSpans = edgeRows.filter((edge) => edge.mergedSpan).map((edge) => edge.length);
  const sortedMergedSpans = [...mergedSpans].sort((a, b) => a - b);
  const sortedLengths = [...lengths].sort((a, b) => a - b);
  const head = {
    nodes: cy.nodes().filter((n) => !n.isParent()).length - bags.length,
    edges: edgeRows.length,
    bags: bags.length,
    baggedNodes: Object.values(isBagged).filter(Boolean).length,
    bridges: bridgeRows.length,
    edgeLength: {
      p50: quantile(sortedLengths, 0.5),
      p90: quantile(sortedLengths, 0.9),
      p99: quantile(sortedLengths, 0.99),
      max: sortedLengths[sortedLengths.length - 1] ?? null,
      ideal: themePhysics ? themePhysics.idealEdgeLength : null,
      bagBridgeShare: lengths.length
        ? Math.round((spans.length / lengths.length) * 100)
        : 0,
      // Merged-node edges only — the number the merged bag is supposed to move.
      mergedSpan: {
        count: mergedSpans.length,
        p50: quantile(sortedMergedSpans, 0.5),
        p90: quantile(sortedMergedSpans, 0.9),
        max: sortedMergedSpans[sortedMergedSpans.length - 1] ?? null,
      },
    },
  };
  return { head, edgeRows, bridgeRows, bagRows, spans };
}

let themePhysics = null;

/* ------------------------------------------------------------------ report --- */
function round(value) {
  return Number.isFinite(value) ? Math.round(value * 10) / 10 : value;
}

function fmtRow(edge) {
  return `  ${String(edge.length).padStart(7)}  ${edge.type.padEnd(8)} ${edge.kind.padEnd(14)} ${edge.source} -> ${edge.target}`;
}

function report(result, ringInfo, label) {
  const { head, edgeRows, bridgeRows, bagRows, spans } = result;
  const lines = [];
  lines.push(`\n== ${label} ==`);
  lines.push(
    `nodes ${head.nodes} | edges ${head.edges} | bags ${head.bags} | ` +
    `bagged ${head.baggedNodes} | bridges ${head.bridges}`,
  );
  lines.push(
    `edge length px: p50 ${head.edgeLength.p50} | p90 ${head.edgeLength.p90} | ` +
    `p99 ${head.edgeLength.p99} | max ${head.edgeLength.max} | ideal ${head.edgeLength.ideal}`,
  );
  const span = head.edgeLength.mergedSpan;
  lines.push(
    `merged-node edges: n ${span.count} | p50 ${span.p50} | p90 ${span.p90} | max ${span.max}` +
    `  <- the §9 number`,
  );
  if (ringInfo && ringInfo.applied) {
    lines.push(`\n-- ring (radius ${ringInfo.radius}px) --`);
    for (const move of ringInfo.moved) {
      lines.push(
        `  ${move.platform.padEnd(10)} n=${String(move.children).padStart(4)} ` +
        `centre ${move.centreDistanceBefore} -> ${move.centreDistanceAfter} ` +
        `(shifted ${move.shift}px)`,
      );
    }
  } else {
    lines.push(`\n-- ring OFF — no post-layout translation applied --`);
  }

  lines.push(`\n-- longest 15 edges --`);
  for (const edge of edgeRows.slice(0, 15)) lines.push(fmtRow(edge));

  lines.push(`\n-- longest 10 merged-node edges (the §9 signature) --`);
  for (const edge of spans.slice(0, 10)) lines.push(fmtRow(edge));

  lines.push(`\n-- bags (centre distance, spread) --`);
  for (const bag of bagRows) {
    lines.push(
      `  ${bag.platform.padEnd(10)} n=${String(bag.children).padStart(4)} ` +
      `centre=${String(bag.centreDistance).padStart(7)} box=${bag.width}x${bag.height}`,
    );
  }

  lines.push(`\n-- merged-bag members, worst first (distance to each platform bag they touch) --`);
  for (const bridge of bridgeRows.slice(0, 15)) {
    const parts = bridge.touch.map((touch) =>
      `${touch.bag}:${touch.distance}px (reach ${touch.reach}, n=${touch.edgeCount})`,
    );
    lines.push(`  ${bridge.bridge}\n    ${parts.join("  |  ")}`);
  }
  return lines.join("\n");
}

/* -------------------------------------------------------------------- main --- */
function parseArgs(argv) {
  const options = {
    runs: 3,
    api: true,
    set: {},
    slice: { node_types: null, edge_types: null, limit: 2000, sort: "messages" },
    top: 15,
    stock: false,
    saveBaseline: false,
  };
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === "--no-ring") options.set["layout.bagRing"] = "false";
    else if (arg === "--no-api") options.api = false;
    else if (arg === "--stock") options.stock = true;
    else if (arg === "--save-baseline") options.saveBaseline = true;
    else if (arg === "--runs") options.runs = Number(argv[++i]);
    else if (arg.startsWith("--set.")) {
      const dotted = arg.slice("--set.".length);
      options.set[dotted] = argv[++i];
    } else if (arg === "--sort") options.slice.sort = argv[++i];
    else if (arg === "--limit") options.slice.limit = Number(argv[++i]);
    else throw new Error(`unknown argument: ${arg}`);
  }
  return options;
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  const theme = loadTheme(options.set, { useBaseline: !options.stock });
  themePhysics = theme.physics;
  if (options.saveBaseline) {
    const snapshot = {
      _provenance: `Saved ${new Date().toISOString().slice(0, 10)} from probe run with overrides: ${
        Object.entries(options.set).map(([k, v]) => `${k}=${v}`).join(" ") || "none"
      }`,
      ...JSON.parse(JSON.stringify(theme)),
    };
    delete snapshot.chat;
    fs.writeFileSync(BASELINE_PATH, JSON.stringify(snapshot, null, 2) + "\n");
    console.error(`baseline saved: ${BASELINE_PATH}`);
  }

  const payload = fetchPayload(options.api, options.slice);
  const label = Object.entries(options.set)
    .map(([key, value]) => `${key}=${value}`)
    .join(" ") || "theme defaults";
  console.error(`payload: ${payload.counts.nodes} nodes, ${payload.counts.edges} edges`);
  console.error(`theme: ${label} | ring ${theme.layout.bagRing} spread ${theme.layout.bagRingSpread}`);
  console.error(`runs: ${options.runs} (fcose randomizes; median across runs is the signal)`);

  const elements = buildElements(payload, !!theme.filter.bags);
  const runs = [];
  for (let index = 0; index < options.runs; index++) {
    const cy = new Cytoscape({
      headless: true,
      styleEnabled: true, // headless skips style otherwise; fcose reads node size
      elements: JSON.parse(JSON.stringify(elements)),
      // The real stylesheet sets node size via data/tiers; the probe only needs
      // plausible non-uniform sizes for the solver's packing math.
      style: [
        { selector: "node", style: { width: "data(size)", height: "data(size)", "background-color": "#888" } },
      ],
    });
    const run = await runOnce(cy, theme);
    const measured = measure(cy, payload);
    runs.push({ run, measured });
    if (index === 0) {
      fs.writeFileSync(
        path.join(__dirname, "last_run_positions.json"),
        JSON.stringify({ theme: label, positions: run.postSolver }, null, 1),
      );
    }
    cy.destroy();
  }

  // Median per headline metric across runs.
  const median = (values) => {
    const sorted = [...values].sort((a, b) => a - b);
    const mid = Math.floor(sorted.length / 2);
    return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
  };
  console.log(`\n### ${options.runs} runs, median headline numbers ###`);
  for (const key of ["p50", "p90", "p99", "max"]) {
    console.log(
      `edge length ${key}: ${median(runs.map((run) => run.measured.head.edgeLength[key]))} px`,
    );
  }
  console.log(
    `bag-bridge share of edges: ${median(runs.map((run) => run.measured.head.edgeLength.bagBridgeShare))}%`,
  );
  console.log(report(medianRun(runs), runs[Math.floor(runs.length / 2)].run.ringInfo, label));

  function medianRun(runs) {
    // Pick the run whose p90 is the median p90 — a representative run, not an
    // average of geometries (averaging coordinates produces mush).
    const sorted = [...runs].sort((a, b) => a.measured.head.edgeLength.p90 - b.measured.head.edgeLength.p90);
    return sorted[Math.floor(sorted.length / 2)].measured;
  }
}

main().catch((error) => {
  console.error(`ai_visual_graph_tool: ${error.message}`);
  if (process.env.PROBE_DEBUG) console.error(error.stack);
  process.exit(1);
});
