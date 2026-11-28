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
    smartEdgeLength: true, // true = the old, very long cross-bag edges
    gravity: 0.1, // 0 = drifts apart, 0.5 = pulled into a ball
    nodeSeparation: 75, // BETWEEN disconnected components only
    numIter: 2500, // 1000 = fast and messy, 5000 = slow and settled
    // Compound gravity. Each platform is a bag (an invisible parent node), and this
    // is what squeezes a bag's children toward its own centre — NOT `gravity`, which
    // pulls everything toward the middle of the screen and would crush all seven bags
    // into one ball. 1.0 is fcose's default; raise it if a big bag sprawls.
    gravityCompound: 3.0, // 0.5 = loose bag, 2.0 = tight ball
    gravityRangeCompound: 0.5, // how far the compound pull reaches, in bag radii
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
    wheelSensitivity: 1.8, // default 1.0 is genuinely slow (1.047x per notch)
    // **Overlap removal, after the solver.** fcose's own anti-overlap pass measures a
    // leaf node's BODY box only, so anything the glyph draws outside it is invisible to
    // the solver — the reason no slider ever fixed nodes sitting on each other.
    //
    // Labels are excluded on purpose: they are far wider than the marks, and letting
    // them drive separation would spread one cluster across the canvas. Label density is
    // handled separately.
    declutter: {
      enabled: true,
      // Passes over every pair. Each pass re-reads the boxes, so this is the budget for
      // how much movement is allowed to cascade — 24 is enough for the dense clusters and
      // still converges long before it becomes a frame-rate problem.
      iterations: 24,
      // Extra clearance kept between glyphs, in px. 0 lets marks touch edge to edge.
      padding: 4,
      // Fraction of a full separation applied per pass. 1.0 resolves each pair in one
      // move but shakes the whole layout; 0.6 converges smoothly.
      step: 0.6,
    },
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
    minZoomedFontSize: 28, // raise to 16 if mid-zoom still looks crowded
    maxWidth: 80, // px, with text-wrap: wrap
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
    //
    // Widths thinned 30% on 2026-11-21 (2.1/1.4/0.85 -> 1.47/0.98/0.6), then the
    // tiers were spread apart because they read as one weight: the top rung doubled to
    // 12px and the two lower rungs halved to 0.49 / 0.3. The top tier is also faint
    // (opacity 0.3), so it is a soft band rather than a hard line — see `visual` for
    // why a real glow is not possible.
    edge: [
      { min: 60, width: 4, opacity: 0.3 },
      { min: 12, width: 0.7, opacity: 1 },
      { min: 0, width: 0.4, opacity: 1 },
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
    // **An edge cannot glow. Settled 2026-11-21 — do not retry.**
    //  1. `underlay-*` on an edge is only drawn on the texture-cache path, which the
    //     canvas renderer does not take for edges. It paints nothing.
    //  2. `line-outline-*` is drawn, but it is a second stroke of constant width, so it
    //     reads as an outline around the line, not a glow.
    //
    // There is no falloff available: Cytoscape has no blur, and an edge gradient runs
    // source->target, not across the stroke. The only soft-edge lever is width +
    // transparency, which is what `tiers.edge`'s top rung uses.
    glowBlur: 18, // shadow-blur on the selected node
    hazeOpacity: 0.2, // static radial gradient behind the canvas
    // Correspondents glow permanently, so they read as a different class of thing
    // against the threads. Selection therefore cannot also be a glow — it is a
    // bright border plus a much larger blur (see `node:selected` below).
    correspondentGlow: 50,
    correspondentGlowOpacity: 1.2,
    // A MERGED node — the same person seen on more than one platform. It draws a
    // neutral grey glyph and an orange halo, so it reads as a bridge between clusters
    // rather than a member of any one of them.
    //
    // NOT applied to the node any more — Cytoscape multiplies a background image by
    // the node's effective opacity, so fading the node faded the glyph too and a
    // near-black silhouette came out washed grey. Kept as the documented knob for
    // the halo's overall strength, which is `mergedGlowOpacity` below.
    mergedOpacity: 0.55, // unused by the stylesheet; see the note above
    // Orange, not grey: the palette's own `orangeText` reads warm against the
    // black/green page and cannot be mistaken for a platform hue.
    //
    // **This is an UNDERLAY, not a shadow.** Cytoscape 3.35.0 removed every
    // `shadow-*` property when the renderer moved to WebGL — the bundle contains no
    // `shadow-blur` at all, so the old glow silently did nothing. `underlay-*` is the
    // supported replacement: a shape drawn behind the node body.
    //
    // An underlay has no blur, so the falloff comes from a RADIAL GRADIENT: opaque
    // at the centre, transparent at the outer stop. `mergedGlowPadding` is how far
    // the halo reaches beyond the node body.
    mergedGlowPadding: 10, // px the halo extends beyond the node body
    mergedGlowOpacity: 0.6, // overall multiplier on the gradient
    mergedGlowColor: "#d97a2b", // palette.orangeText
    // Stops are fractions of the underlay's radius, and the radius is
    // `max(paddedWidth, paddedHeight)` — i.e. the node PLUS its padding, so 100% is
    // the outer edge of the halo.
    //
    // The taper MUST reach zero at 100%, or the halo ends on a hard rim — that was the
    // first version's bug (full opacity held to 35%, then a cliff).
    //
    // The middle stops carry the glow's body. Too low and the halo reads as a thin
    // ring with a dead zone around it; the values below hold most of the strength
    // through the first half of the radius and then fall away.
    //
    // **TRIED AND REVERTED TWICE (2026-11-21). Do not retry without reading this.**
    //
    // 1. Opaque outer stop alone: covered the first `mergedGlowPadding` px of every
    //    CONNECTED edge (they stop at `outerWidth()`, inside the halo) and did nothing
    //    for edges passing behind.
    // 2. Opaque outer stop + `z-index-compare: manual` lifting `edge.to-merged` above
    //    the node layers: fixed the occlusion, but **broke node dragging** — an edge
    //    above a node swallows the grab.
    //
    // Conclusion: the halo cannot occlude. Cytoscape paints every edge before every
    // node layer, and the only escape (`manual` z-index) costs interaction.
    //
    // **The transparent stop MUST be `rgba(...)`, never 8-digit hex.** Cytoscape's
    // colour parser (`hex2tuple`) accepts only 3 and 6 digits, so `#d97a2b00` parses
    // to `null`; the multi-value branch then reads `.value` off that null and throws
    // inside `parseImpl`, which takes the WHOLE stylesheet down and blanks the app.
    mergedGlowStops: [
      "rgba(217,122,43,0.85)",
      "rgba(217,122,43,0.62)",
      "rgba(217,122,43,0.3)",
      "rgba(217,122,43,0.1)",
      "rgba(217,122,43,0)",
    ],
    mergedGlowStopPositions: ["0%", "40%", "70%", "88%", "100%"],

    // Per-node lightness jitter, so a platform cluster reads as a family of shades
    // rather than one flat colour. Deterministic from the node id.
    shadeJitter: 0.16, // 0 = every node identical, 0.3 = noisy
    // Icons are the only node look. There is no circle mode and no toggle: a thread
    // draws its source's glyph, a correspondent draws the person glyph. The glyph is
    // a flat platform colour baked into the SVG, so `shadeJitter` does not apply to
    // it — jitter would mean one image per node.
    iconScale: 0.72, // fraction of the node's diameter the thread glyph fills
    correspondentIconScale: 0.86, // a person silhouette is narrow, so it needs more
    // Per-KIND multiplier for the extracted entity glyphs. Empty means every entity kind
    // draws at `correspondentIconScale`; a kind that reads too small at canvas scale can
    // be enlarged here without touching the others.
    entityIconScale: {},
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
    bagRingSpread: 0.6,
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
    // Places are drawn by default because they have rows now (21 in the live store).
    // The other three extracted kinds stay off until their extractors land — a ticked
    // kind with zero rows only costs a query. To distrust the extractor, untick
    // `Place` here or in the Canvas modal.
    //
    // **`Product` is included: it has been live and writing since `PRODUCT_ENABLED`
    // went true, and leaving it out meant the canvas never requested the node type —
    // 22 Product nodes sat in the store with no toggle and no way to draw them.**
    nodeTypes: ["Thread", "Correspondent", "Place", "Organization", "Product"],
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
    // The mirror: every message in the thread is the Owner's. A cold-email campaign
    // with no subject and no reply headers collapses into one thread key, so a
    // broadcast reads as a 31-message "conversation" it never was. View only.
    hideBroadcast: false,
    // **One tri-state per kind**, mutually exclusive: `all` | `merged` | `hide`.
    //
    //   all    — draw merged and single-platform nodes alike.
    //   merged — draw ONLY the `bag:merged` population; single-platform nodes go.
    //   hide   — draw none of this kind, merged or not.
    //
    // **There is no "singles only".** Nobody wants the long tail without the strong
    // claims; the axis that matters is "everything / the cross-platform facts / none".
    //
    // Radio, not checkboxes. The three states describe one node population, so any two
    // are contradictory — the earlier two-boolean version could express "neither",
    // which read as a broken control.
    //
    // A node is merged purely by BAG MEMBERSHIP, so `merged` is the same test the
    // canvas already uses to place a node in `bag:merged`. `hideSingleMentions` and
    // `hideMerged` are gone; their saved diffs no longer match a default key and are
    // ignored rather than misread.
    nodeVisibility: {
      Place: "all",
      Product: "all",
      Organization: "all",
    },
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

/**
 * Only the user's OVERRIDES are persisted — never the whole theme.
 *
 * **Why this matters.** The old design saved the entire theme object and merged it
 * back over the defaults on load, so a saved value shadowed every later edit to
 * `theme.js`. Changing a default then required bumping a version constant to force a
 * reset, and forgetting the bump made the edit silently do nothing. That cost hours.
 *
 * Storing a DIFF fixes it at the root: a key the user never touched is not in
 * storage, so it always follows `theme.js`. Edit a default, rebuild, hard-refresh —
 * the new value appears, with no version and no manual clearing.
 *
 * The key is new so an old full-theme object under the previous key is ignored
 * rather than being misread as a diff (which would override everything).
 */
const OVERRIDES_KEY = "relate.graphStyle.overrides";

/** Merge the user's saved overrides over the CURRENT defaults. */
export function loadTheme() {
  try {
    const raw = localStorage.getItem(OVERRIDES_KEY);
    if (!raw) return cloneTheme();
    return mergeDeep(cloneTheme(), JSON.parse(raw));
  } catch {
    return cloneTheme();
  }
}

/**
 * Persist only what differs from the defaults.
 *
 * Setting a value back to its default removes it from storage, so the key starts
 * following `theme.js` again — which is the behaviour that makes editing the file
 * reliable.
 */
export function saveTheme(theme) {
  try {
    const overrides = diffTheme(THEME, theme);
    if (Object.keys(overrides).length === 0) {
      localStorage.removeItem(OVERRIDES_KEY);
    } else {
      localStorage.setItem(OVERRIDES_KEY, JSON.stringify(overrides));
    }
  } catch {
    /* private mode, quota — the look just does not persist */
  }
}

export function resetTheme() {
  try {
    localStorage.removeItem(OVERRIDES_KEY);
  } catch {
    /* ignore */
  }
  return cloneTheme();
}

/**
 * The keys of `theme` that differ from `defaults`, recursively.
 *
 * Arrays are compared whole: `tiers.edge` and `filter.platforms` are edited as units,
 * so a partial array diff would be meaningless and would also break `rungFor`.
 */
function diffTheme(defaults, theme) {
  const out = {};
  for (const [key, value] of Object.entries(theme || {})) {
    const base = defaults?.[key];
    if (value && typeof value === "object" && !Array.isArray(value)) {
      const sub = diffTheme(base && typeof base === "object" ? base : {}, value);
      if (Object.keys(sub).length) out[key] = sub;
    } else if (JSON.stringify(value) !== JSON.stringify(base)) {
      out[key] = value;
    }
  }
  return out;
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
