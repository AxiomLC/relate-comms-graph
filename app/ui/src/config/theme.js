/**
 * EVERY tunable value in the UI, in one object.
 *
 * Two reasons this file exists rather than values being scattered through
 * components:
 *
 *  1. The Canvas modal writes the view controls here, live. Icons, colours, edge
 *     widths and node sizes are dev knobs: edit them here, not in the UI.
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
    idealEdgeLength: 22, // 12 = very dense, 60 = airy
    // fcose adds each compound's estimated size to every edge that crosses a bag
    // boundary (`layout-base.js` `calcIdealEdgeLengths`). With a 31-node Telegram bag
    // that is ~250px of ideal length on every merged-node edge — the long lines.
    // Off, an inter-bag edge is just `idealEdgeLength` like any other.
    smartEdgeLength: false, // true = the old, very long cross-bag edges
    gravity: 0.2, // 0 = drifts apart, 0.5 = pulled into a ball
    nodeSeparation: 75, // BETWEEN disconnected components only
    numIter: 2500, // 1000 = fast and messy, 5000 = slow and settled
    // Compound gravity. Each platform is a bag (an invisible parent node), and this
    // is what squeezes a bag's children toward its own centre — NOT `gravity`, which
    // pulls everything toward the middle of the screen and would crush all seven bags
    // into one ball. 1.0 is fcose's default; raise it if a big bag sprawls.
    gravityCompound: 1.0, // 0.5 = loose bag, 2.0 = tight ball
    gravityRangeCompound: 1.5, // how far the compound pull reaches, in bag radii
    // Labels are part of a node's layout box. Without this a 120px label sits on a
    // 18px node and the solver has no idea it is there — which is most of the
    // "nodes on top of nodes" overlap.
    nodeDimensionsIncludeLabels: true,
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
  },

  /* ------------------------------------------------------------------- tiers
   * SIX lettered sizes, A..F, biggest first. A node's letter is COMPUTED per
   * source (per platform), never from a fixed threshold.
   *
   * Why per source: the platforms are wildly different in scale — 707 messages in
   * the largest Messenger thread, a handful in the largest email thread. One
   * global threshold flattens every source but the biggest into the same dust
   * cloud. Cutting bands inside each source keeps every cluster legible.
   *
   * Which letters each kind may use — declared per kind in `nodeTypes.js`
   * (`sizeLadder`), not here:
   *   Thread        A / C / E   — A is the standout, so threads skip B
   *   Correspondent B / D / F   — B is the biggest correspondent, below A
   *   Person, Place, Organization, Product  D / E / F
   *
   * The two ladders interleave, so a thread always outranks the correspondent of
   * the same band: A thread, B correspondent, C thread, D correspondent, E thread,
   * F correspondent.
   *
   * The band cut is a fraction of that source's own node count, top-down: the
   * top `top` share is the big letter, the next `mid` share the middle letter,
   * everything left the small letter. At least one node always lands in each of
   * the first two bands, so a source with two threads still gets an A and a C.
   */
  tiers: {
    sizes: {
      A: { size: 66, font: 16 },
      B: { size: 50, font: 14 },
      C: { size: 38, font: 12 },
      D: { size: 30, font: 10 },
      E: { size: 24, font: 10 },
      F: { size: 18, font: 9 },
    },
    // Fractions of one source's node count. 0.2 / 0.3 = big 20%, mid 30%, rest
    // small. Deliberately not a percentile of the values — a skewed distribution
    // would put 90% of nodes in one band.
    //
    // A band boundary never splits a group of equal values: the whole group drops
    // into the smaller band. Without that, Telegram's top 20% is 109 threads of
    // which 104 hold a single message, so "big" means nothing.
    bands: { top: 0.2, mid: 0.3 },
    // Edges get three tiers, keyed on the source thread's message count. `WITH`
    // carries no weight property, so the thread's own size is the only signal.
    // Edges are the weakest thing on this canvas: a 0.8px line at 0.4 opacity on a
    // near-black background is invisible until you are almost on top of it. The
    // floor is therefore high — every edge is at least 1.2px and 0.75 — and the
    // tiers separate by width more than by opacity, because opacity is what makes
    // them disappear.
    edge: [
      { min: 80, width: 2.1, opacity: 1 },
      { min: 12, width: 1.4, opacity: 1 },
      { min: 0, width: 0.85, opacity: 1 },
    ],
  },

  /* ------------------------------------------------------------------- visual */
  visual: {
    edgeOpacity: 1, // fallback when no tier matches
    edgeWidth: 0.85,
    // Edges are drawn in a LIGHT version of the platform colour — the light end of
    // that platform's scheme, not white. 0.7 washed every hue out to near-white
    // (a 0.7 mix of #3b6fd4 is #c3d1f0, which reads as grey). 0.35 keeps the hue
    // recognisable while still lifting it off the near-black background.
    edgeLighten: 0.35,
    glowBlur: 18, // shadow-blur on the selected node
    hazeOpacity: 0.2, // static radial gradient behind the canvas
    // Correspondents glow permanently, so they read as a different class of thing
    // against the threads. Selection therefore cannot also be a glow — it is a
    // bright border plus a much larger blur (see `node:selected` below).
    correspondentGlow: 50,
    correspondentGlowOpacity: 1.2,
    // Per-node lightness jitter, so a platform cluster reads as a family of shades
    // rather than one flat colour. Deterministic from the node id.
    shadeJitter: 0.16, // 0 = every node identical, 0.3 = noisy
    // Icons are the only node look. There is no circle mode and no toggle: a thread
    // draws its source's glyph, a correspondent draws the person glyph. The glyph is
    // a flat platform colour baked into the SVG, so `shadeJitter` does not apply to
    // it — jitter would mean one image per node.
    iconScale: 0.72, // fraction of the node's diameter the thread glyph fills
    correspondentIconScale: 0.86, // a person silhouette is narrow, so it needs more
    // Per-platform multiplier on `iconScale`, for glyphs whose own artwork sits
    // smaller or larger inside its 24x24 viewBox. The SVGs were normalised to the
    // same box, but a wide envelope and a compact speech bubble do not read as the
    // same size at the same scale — this is the optical correction.
    //
    // 1.0 is the default, so a platform added later needs no entry.
    iconScaleByPlatform: {
      messenger: 1.15, // Facebook speech bubble reads small
      whatsapp: 1.15, // same
      email: 0.85, // the envelope is wide, so it reads large
      gmail: 0.85, // same glyph as email
      imap: 0.85, // same glyph as email
    },
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
    // Pin the platform bags to a ring, so the picture is "platforms around the
    // outside, bridges in the middle" rather than seven blobs wherever the solver
    // happened to leave them.
    //
    // Applied AFTER the solver, as a translation of each bag's children — not as a
    // `fixedNodeConstraint`. That constraint is fatal on a compound node: fcose's
    // `spectralLayout` never indexes parents, so the constraint reads `undefined` and
    // turns every coordinate into `NaN`. See `placeBagsOnRing`.
    //
    // It is what makes the middle meaningful: a merged node is pulled by its real
    // edges toward every bag it touches, and the bags are arranged so those pulls
    // point inward from all sides.
    //
    // Off = free-floating, exactly as before bags existed.
    bagRing: true,
    // Multiplier on the ring radius. 1.0 packs the bags shoulder to shoulder;
    // raise it to open the middle up for the bridges.
    bagRingSpread: 1.0,
  },

  /* ------------------------------------------------------------------ filter
   * VIEW ONLY. A hidden toggle must never narrow what an agent can query
   * (TECHREADME.md §5) — this only decides what is drawn.
   *
   * `platforms` is the canvas's own cluster toggle, and it is NOT the same thing as
   * the Utilities filter. Utilities narrows what the *tools* return, so search and
   * the AI chat see less. This hides a cluster from the drawing and nothing else.
   *
   * `sort` and `limit` decide which nodes survive truncation, so they are a real
   * choice rather than a preference: `messages` keeps the biggest threads, `quiet`
   * keeps the ones that went silent — the question this app exists to answer.
   */
  filter: {
    // The default set. The four entity kinds are drawable but hold zero rows until
    // body-entity extraction lands, so they are off until someone ticks them.
    nodeTypes: ["Thread", "Correspondent"],
    // One invisible bag per platform, so fcose clusters threads by source instead of
    // letting them float free. Client-side only — a bag is a body for the layout, not
    // data, and it never reaches the server or any count. Off is a real option: with
    // it off the canvas is exactly what it was before bags existed.
    bags: true,
    // Every platform on by default, and the toggle is a plain on/off per platform —
    // the same shape as the node-type list above it. An empty list means "not
    // chosen yet", which the canvas reads as "all on", so a platform added later
    // appears without the user having to tick it.
    platforms: [],
    hideSilent: false, // hide threads the owner never sent a message in
    sort: "messages", // messages | recent | quiet
    limit: 2000, // nodes drawn; the canvas reports the real total beside it
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

/**
 * Bump this whenever a DEFAULT changes in a way that must win over a saved theme.
 *
 * Without it, `loadTheme()` merges the saved object over the defaults, so a value
 * the user once dragged a slider to shadows every later change to that default —
 * which is exactly how the edge brightening appeared to do nothing: the saved
 * `tiers.edge` from an earlier session was still winning.
 *
 * A version mismatch discards the saved theme. That is the right trade: the theme
 * is a look, not data, and a stale look that hides a fix is worse than a reset.
 */
const THEME_VERSION = 9;

/** Merge a saved partial config over the defaults (new keys keep their default). */
export function loadTheme() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return cloneTheme();
    const saved = JSON.parse(raw);
    if (saved?.version !== THEME_VERSION) return cloneTheme();
    return mergeDeep(cloneTheme(), saved);
  } catch {
    return cloneTheme();
  }
}

export function saveTheme(theme) {
  try {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ ...theme, version: THEME_VERSION }),
    );
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
