/**
 * EVERY tunable value in the UI, in one object.
 *
 * Two reasons this file exists rather than values being scattered through
 * components:
 *
 *  1. The Graph Style modal (UI-Cytoscape.md §12) writes here, live.
 *  2. The whole look is one diff. If the graph feels wrong, this is the file to
 *     open, not a hunt through six components.
 *
 * Each value carries the range that is sane, because "20000" means nothing
 * without "8000 = tight, 40000 = airy".
 */

export const THEME = {
  /* ------------------------------------------------------------------ palette
   * Deep black/green base, dark-orange buttons, thin dark-blue borders, light-blue
   * glow on objects. Deliberately NOT frontal-lobe's black/red.
   */
  palette: {
    bg: "#05070a", // page base
    bgLift: "#0a1410", // panels, inputs — the green lift
    orange: "#8a3d12", // button fill
    orangeText: "#d97a2b", // button label, errors
    blueLine: "#1b2a4a", // 1px borders and outlines
    blueGlow: "#5c8fd6", // nodes, selection halo, active UI
    text: "#c8d2e0", // body copy
    muted: "#6b7a90", // meta, timestamps, placeholders
  },

  /* ------------------------------------------------------------------ physics
   * fcose. Measured in the author's other app at ~1.5k nodes.
   */
  physics: {
    nodeRepulsion: 20000, // 8000 = tight clumps, 40000 = airy
    idealEdgeLength: 60, // 40 = dense, 120 = sparse
    gravity: 0.2, // 0 = drifts apart, 0.5 = pulled into a ball
    nodeSeparation: 75, // BETWEEN disconnected components only
    numIter: 2500, // 1000 = fast and messy, 5000 = slow and settled
    randomize: true, // MANDATORY: elements are re-added on filter change and
    // fresh nodes all start at (0,0) — without this the layout has no spread
    // and clicks land on the wrong node.
    zoomDistance: 1.8, // multiplies the post-layout fit zoom. `fit: true` shrinks
    // until everything is visible, which at this node count puts neighbours
    // closer than a node's own diameter.
    wheelSensitivity: 3.8, // default 1.0 is genuinely slow (1.047x per notch)
  },

  /* ------------------------------------------------------------------- labels
   * Labels are a zoom reward, never hover-to-reveal (§4.3).
   *
   * The mechanism: Cytoscape skips text when `font-size x zoom` falls below
   * `minZoomedFontSize`. Bigger nodes get a bigger font, so they cross the
   * threshold at a LOWER zoom — which is exactly "only large nodes are labelled
   * at mid zoom".
   */
  labels: {
    minZoomedFontSize: 13, // raise to 16 if mid-zoom still looks crowded
    maxWidth: 120, // px, with text-wrap: wrap
    color: "#c8d2e0",
    correspondentColor: "#8fa3bd",
    // Threads carry two lines: the source, then the title. Cytoscape allows ONE
    // label and ONE style, so both lines share a font — the hierarchy comes from
    // uppercasing the source and putting it first, not from a second font size.
    showSourceLine: true,
  },

  /* ------------------------------------------------------------------- tiers
   * SIX sizes for the whole graph, one shared ladder.
   *
   * The rungs interleave by kind: the biggest thread, then the biggest
   * correspondent, then the next thread, then the next correspondent, and so on.
   * So a thread always outranks a correspondent of the same rung, and "biggest"
   * means biggest of its kind — never a single number compared across two
   * different quantities.
   *
   * Why static tiers and not continuous scaling: the distribution is brutally
   * skewed (707 messages in the largest thread, 565 of 591 correspondents have
   * exactly ONE thread). Continuous scaling produces one giant dot and a dust
   * cloud. Six fixed sizes keep the picture readable and the code trivial.
   *
   * Each rung is a pair of thresholds — one for threads (message count), one for
   * correspondents (thread count) — because the two quantities are not comparable.
   * `min` is inclusive; the first rung whose `min` is met wins, top to bottom.
   */
  tiers: {
    // Ordered biggest first. `size` and `font` are what a node in that rung gets.
    ladder: [
      { size: 46, font: 15, threadMin: 200, correspondentMin: 20 },
      { size: 38, font: 14, threadMin: 80, correspondentMin: 8 },
      { size: 31, font: 13, threadMin: 30, correspondentMin: 4 },
      { size: 25, font: 12, threadMin: 12, correspondentMin: 2 },
      { size: 20, font: 11, threadMin: 4, correspondentMin: 1 },
      { size: 15, font: 10, threadMin: 0, correspondentMin: 0 }, // catch-all
    ],
    // Edges get three tiers, keyed on the source thread's size. `WITH` carries no
    // weight property, so the thread's own tier is the only honest signal.
    edge: [
      { min: 80, width: 2.2, opacity: 0.3 },
      { min: 12, width: 1.4, opacity: 0.2 },
      { min: 0, width: 0.8, opacity: 0.12 },
    ],
  },

  /* ------------------------------------------------------------------- visual */
  visual: {
    edgeOpacity: 0.15, // fallback when no tier matches
    edgeWidth: 1,
    glowBlur: 18, // shadow-blur on the selected node
    hazeOpacity: 0.1, // static radial gradient behind the canvas
    // Correspondents glow permanently, so they read as a different class of thing
    // against the threads. Selection therefore cannot also be a glow — it is a
    // bright border plus a much larger blur (see `node:selected` below).
    correspondentGlow: 14,
    correspondentGlowOpacity: 0.55,
    // Per-node lightness jitter, so a platform cluster reads as a family of shades
    // rather than one flat colour. Deterministic from the node id.
    shadeJitter: 0.16, // 0 = every node identical, 0.3 = noisy
    // Draw a Thread as its source's icon instead of a plain circle. The icon is a
    // flat platform colour (baked into the SVG), so shade jitter does not apply to
    // it — jitter would mean one image per node. Correspondents are unaffected.
    nodeIcons: false,
    iconScale: 0.72, // fraction of the node's diameter the icon fills
  },

  /* ------------------------------------------------------------------- reveal
   * Nodes bloom outward in ts_utc order. Highest impact per effort for a demo,
   * and cheap: ~14 style batches, not a per-frame animation.
   */
  reveal: {
    enabled: true,
    durationMs: 2500,
    steps: 14,
  },

  /* ------------------------------------------------------------------ layout */
  layout: {
    name: "fcose",
    fit: true,
    padding: 40,
  },

  /* ------------------------------------------------------------------ filter
   * VIEW ONLY. A hidden toggle must never narrow what an agent can query
   * (TECHREADME.md §5) — this only decides what is drawn.
   */
  filter: {
    nodeTypes: ["Thread", "Correspondent"],
  },

  /* --------------------------------------------------------------------- chat */
  chat: {
    maxTranscript: 40, // turns kept in localStorage before the oldest is dropped
  },
};

/** Deep clone, so the modal can edit a draft without mutating the live config. */
export function cloneTheme(theme = THEME) {
  return JSON.parse(JSON.stringify(theme));
}

const STORAGE_KEY = "relate.graphStyle";

/** Merge a saved partial config over the defaults (new keys keep their default). */
export function loadTheme() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return cloneTheme();
    const saved = JSON.parse(raw);
    return mergeDeep(cloneTheme(), saved);
  } catch {
    return cloneTheme();
  }
}

export function saveTheme(theme) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(theme));
  } catch {
    /* private mode, quota — the look just does not persist */
  }
}

export function resetTheme() {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* ignore */
  }
  return cloneTheme();
}

function mergeDeep(target, source) {
  for (const [key, value] of Object.entries(source || {})) {
    if (value && typeof value === "object" && !Array.isArray(value)) {
      target[key] = mergeDeep(target[key] ?? {}, value);
    } else {
      target[key] = value;
    }
  }
  return target;
}
