import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
} from "react";

import {
  NODE_TYPES,
  PERSON_ICONS,
  PLATFORM_ICONS,
  kindClass,
  nodeIcon,
  platformColor,
  platformLabel,
  truncateLabel,
} from "../config/nodeTypes.js";

/**
 * The canvas: Cytoscape.js + fcose, 2D, Canvas renderer.
 *
 * Why this and not sigma.js is settled in UI-Cytoscape.md §2 — short version: this box
 * has no GPU, `min-zoomed-font-size` is a native label LOD, and there is no build
 * step for the library itself (it is vendored, not bundled).
 *
 * Three things this component owns and nothing else does:
 *
 *  1. **Label LOD.** `min-zoomed-font-size` skips text when `font-size x zoom` is
 *     below the threshold. Threads get a font size proportional to their message
 *     count, so big threads are labelled at a lower zoom than small ones. That is
 *     the whole "labels are a zoom reward" requirement, with no hover handlers.
 *  2. **Halo vs fly-to.** `halo(id)` selects (border + shadow + z-index). `focus(id)`
 *     selects *and* moves the camera. A graph click calls `halo` only — clicking
 *     around must not yank the view (UI-Cytoscape.md §10).
 *  3. **The reveal.** Nodes appear in `first_ts` order over ~2.5 s. Cheap: ~14
 *     class batches, not a per-frame animation.
 */

// The platforms the legend lists, in reading order. `email` stands for all four
// email keys, because they share one label and one colour.
// Every platform the product intends to carry, in a fixed order. A platform with no
// adapter yet is drawn as a placeholder rather than left out: the legend is the map of
// what this graph can hold, and a missing row reads as "this platform does not exist"
// instead of "not built yet". `PLANNED_PLATFORMS` in tools.py is the single source of
// truth for which is which — the same list the Utilities modal greys out.
const LEGEND_PLATFORMS = [
  "messenger", "telegram", "whatsapp", "linkedin", "email", "outlook", "sms",
];

// Mirrors `tools.PLANNED_PLATFORMS`. Kept as a literal because the UI has no build-time
// access to the Python module; the Utilities modal is the authority and this only
// decides whether a swatch is drawn hollow. Empty means every platform in the legend
// has an adapter.
const PLANNED_PLATFORMS = new Set([]);

/**
 * What a node type the config does not know still gets: drawable, smallest ladder,
 * no glyph. A server that grows a kind before the UI does must not blank the canvas.
 */
const FALLBACK_META = {
  drawable: true,
  shape: "ellipse",
  sizeLadder: ["D", "E", "F"],
  countKey: "mention_count",
  labelMax: 28,
  iconKind: null,
};

const metaOf = (node) => NODE_TYPES[node.type] || FALLBACK_META;

/**
 * The id of one platform's bag.
 *
 * Prefixed so it can never collide with a real node id — a Thread key is
 * `platform:chat_id` and a Correspondent key is `person:<canonical>`, so `bag:` is
 * outside both namespaces by construction.
 */
const bagId = (platform) => `bag:${platform}`;

const GraphCanvas = forwardRef(function GraphCanvas(
  { data, theme, onNodeClick, onBackgroundClick, onLayoutDone },
  ref,
) {
  const hostRef = useRef(null);
  const cyRef = useRef(null);
  const revealTimer = useRef(null);

  // Sizes come from the tier tables, so the theme needs no derived data any more.
  const themeRef = useRef(theme);
  themeRef.current = theme;

  /* ---------------------------------------------------------------- stylesheet */

  const stylesheet = useMemo(() => buildStylesheet(theme), [theme]);

  /* ------------------------------------------------------------------ elements */

  // Depends on `data` and the SIZE TABLE only — deliberately not on the whole theme.
  //
  // Every element carries its own `size` and `fontSize` as data, so a size edit has
  // to rebuild them. But rebuilding also re-adds every element and re-runs fcose,
  // and depending on `theme` meant that dragging ANY slider (glow, haze, edge
  // lighten) threw away the layout and re-ran 2500 iterations. That is why the
  // sliders felt broken. `themeRef` is read for the rest, so the values are still
  // current without being a dependency.
  const sizeKey = JSON.stringify(theme.tiers.sizes);
  const platformKey = (theme.filter.platforms || []).join(",");
  // Bags change the element set, so the toggle has to rebuild it — the same reason
  // `hideSilent` is a dependency below.
  const bagsOn = !!theme.filter.bags;
  // `hideSilent` is read inside the elements memo, so it MUST be a dependency —
  // without it the toggle changed the theme and nothing on screen, because the memo
  // never re-ran. Same class of bug as the stale `tiers.edge` theme.
  //
  // It is declared HERE, outside the memo, because a dependency array is evaluated in
  // the enclosing scope: a `const` declared inside the callback is not visible to it,
  // and referencing it there throws `hideSilent is not defined` on every render —
  // which blanks the whole app.
  const hideSilent = !!theme.filter.hideSilent;
  const elements = useMemo(() => {
    const theme = themeRef.current; // eslint-disable-line no-shadow
    if (!data) return [];

    // Size letters are computed PER SOURCE, because the platforms are not on the
    // same scale (theme.js §tiers). Threads may only be A/C/E and correspondents
    // B/D/F, so the two ladders interleave and a thread always outranks the
    // correspondent of the same band.
    // View-only filters. The server already applied the *node type* filter; these
    // are purely visual and never reach a query, which is why they live here rather
    // than in `loadGraph`.
    //
    // An empty `platforms` list means "every platform on", so a platform added later
    // appears without the user ticking it.
    // A merged Correspondent carries one `platform` (the first by date) and the
    // full list in `platforms`. Testing the single string would hide it whenever the
    // user unticked anything but the first, even though the server kept it.
    const platformsOf = (node) =>
      Array.isArray(node.platforms) && node.platforms.length
        ? node.platforms
        : [node.platform];
    const chosen = theme.filter.platforms || [];
    const allNodes = (data.nodes || []).filter((node) => {
      if (chosen.length && !platformsOf(node).some((p) => chosen.includes(p))) {
        return false;
      }
      // A thread the owner never spoke in. `message_count` is the only signal the
      // canvas has, so a thread with no messages is not hidden by this — it is
      // already invisible for other reasons.
      if (hideSilent && metaOf(node).hideWhenSilent && node.is_silent) return false;
      return true;
    });

    // One ladder per KIND, from the config. Threads are A/C/E and correspondents
    // B/D/F so the two interleave; the entity kinds share D/E/F. Adding a kind is a
    // `NODE_TYPES` entry, not a branch here.
    const lettersByType = new Map();
    for (const [type, meta] of Object.entries(NODE_TYPES)) {
      if (!meta.drawable || !meta.sizeLadder) continue;
      const group = allNodes.filter((node) => node.type === type);
      if (!group.length) continue;
      lettersByType.set(
        type,
        assignBands(group, meta.countKey, meta.sizeLadder, theme.tiers.bands),
      );
    }

    // The weight an edge leaving a node is tiered on. `WITH` stores no count, so the
    // source thread's own size is the only signal the canvas has.
    const edgeWeights = new Map(
      allNodes.map((node) => {
        const meta = metaOf(node);
        return [node.id, node[meta.edgeWeight || meta.countKey] || 0];
      }),
    );

    const nodes = allNodes.map((node) => {
      const meta = metaOf(node);
      // A bag is a body for fcose, not a node the user can see. It carries no size,
      // no label and no colour, and the stylesheet makes it invisible and inert.
      if (node.type === "Bag") {
        return {
          group: "nodes",
          classes: "synthetic bag",
          data: { id: node.id, type: "Bag", platform: node.platform || "" },
        };
      }
      const letter = lettersByType.get(node.type)?.get(node.id);
      const tier = theme.tiers.sizes[letter] || theme.tiers.sizes.F;

      const base = platformColor(node.platform);
      // Icons are the only node look — there is no circle mode. A thread draws its
      // source's glyph, a correspondent draws the person glyph. The glyph is a flat
      // platform colour baked into the SVG, so an icon node drops its shaded fill:
      // a shaded circle behind a flat-coloured icon reads as a mistake.
      //
      // The URL is applied by a static per-platform style rule, never as a data
      // field — `background-image: data(x)` throws inside Cytoscape when the value
      // is an empty string, which killed the whole render once.
      //
      // A platform with no icon file needs no special case: the base `node` rule is
      // a filled circle, and the `node.icon` override is the only thing that removes
      // it. A node with no glyph simply never matches an icon rule, so it stays a
      // visible circle. That is the whole reason the icon styling is an override
      // layer rather than the base.
      const glyph = nodeIcon(node.type, node.platform);
      // `icon` is added only when there IS a glyph, because that class is what removes
      // the base fill. The four extracted kinds have no glyph by decision, so they
      // keep the base filled circle. Glow is keyed on `type`, not on this class.
      const kind = kindClass(node.type);
      const classes = [kind, glyph ? "icon" : null].filter(Boolean).join(" ");

      return {
        group: "nodes",
        // A CLASS, not a data field. Cytoscape's `[key]` selector tests whether the
        // field EXISTS, so `image: null` matched every node and stripped the fill
        // from the whole graph. A class is unambiguous.
        classes,
        data: {
          id: node.id,
          // One line, same as every other node. The source is already carried by
          // the node's icon — a SOURCE line above the title was redundant.
          label: truncateLabel(node.label || node.id, meta.labelMax),
          rawLabel: node.label || node.id,
          type: node.type,
          platform: node.platform || "",
          messageCount: node.message_count || 0,
          threadCount: node.thread_count || 0,
          firstTs: node.first_ts || null,
          lastTs: node.last_ts || null,
          isGroup: !!node.is_group,
          // `:Merged` is the bag-membership test, inverted: a merged node stays
          // outside every bag and is pulled by its real edges instead.
          merged: !!node.merged,
          // A shade of the platform colour, deterministic from the id, so a cluster
          // reads as a family and the picture is identical on every load.
          color: shade(base, node.id, theme.visual.shadeJitter),
          size: tier.size,
          fontSize: tier.font,
          // The image itself is NOT a data field. `background-image: data(image)`
          // throws inside Cytoscape when the value is an empty string (it parses to
          // null, then reads `.value` off it), which killed the whole render. The
          // URL is applied by a static per-platform style rule instead — five rules,
          // five cached rasterisations.
        },
      };
    });

    // ------------------------------------------------------------------ bags
    //
    // One invisible parent per platform, so fcose has a body to solve around and
    // threads cluster by source. Built HERE, in the same pass that filters children,
    // and never as a separate step: fcose throws on a child whose parent is missing,
    // so a bag that survives its children (or the reverse) is a hard failure, not a
    // cosmetic one.
    //
    // Membership is `:Merged`, inverted. A node with one platform goes in that
    // platform's bag; a merged node stays outside and is pulled by its real edges.
    // The test reads the LABEL, not `platforms.length`: a Place mentioned on two
    // platforms is `:Merged` and must stay outside, and a `platforms.length === 1`
    // test would have quietly bagged the world's geography.
    //
    // Bags are synthetic. They are excluded from the reveal and from every count —
    // `cy.nodes().length` includes them, so nothing may use that raw.
    const bagNodes = [];
    if (theme.filter.bags) {
      const platformsInUse = new Set();
      for (const node of nodes) {
        const platforms = platformsOf(node.data);
        if (node.data.merged || platforms.length !== 1) continue;
        const platform = platforms[0];
        if (!platform) continue;
        node.data.parent = bagId(platform);
        platformsInUse.add(platform);
      }
      // A bag is only created for a platform that still has a child. An empty bag is
      // not merely untidy: fcose treats a childless compound as a node with no
      // members and the layout degrades around it.
      for (const platform of platformsInUse) {
        bagNodes.push({
          group: "nodes",
          classes: "synthetic bag",
          data: { id: bagId(platform), type: "Bag", platform },
        });
      }
    }

    const ids = new Set(nodes.map((n) => n.data.id));
    const edges = (data.edges || [])
      .filter((edge) => ids.has(edge.source) && ids.has(edge.target))
      .map((edge) => {
        // Edge weight comes from the source node's own count — `WITH` stores none.
        const tier = rungFor(theme.tiers.edge, "min", edgeWeights.get(edge.source) ?? 0);
        const platform = nodes.find((n) => n.data.id === edge.source)?.data.platform || "";
        return {
          group: "edges",
          data: {
            id: `${edge.type}:${edge.source}->${edge.target}`,
            source: edge.source,
            target: edge.target,
            type: edge.type,
            // Lightened, because a raw platform colour as a 1px line on black is
            // invisible (theme.js §visual.edgeLighten).
            color: lighten(platformColor(platform), theme.visual.edgeLighten),
            width: tier.width,
            opacity: tier.opacity,
          },
        };
      });

    // Bags first, so a parent exists before the child that names it is added.
    return [...bagNodes, ...nodes, ...edges];
    // `platformKey`, `hideSilent` and `bagsOn` are dependencies because hiding a
    // cluster, hiding a silent thread or turning bags on must rebuild the elements;
    // the rest of the theme stays out of it so a slider move does not throw away the
    // layout.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, sizeKey, platformKey, hideSilent, bagsOn]);

  /* ------------------------------------------------------------------- create */

  useEffect(() => {
    if (!hostRef.current || cyRef.current) return undefined;

    // fcose is vendored as a UMD bundle and publishes itself on `window`; it must be
    // registered with Cytoscape before a layout by that name can run.
    if (window.cytoscapeFcose && !window.__fcoseRegistered) {
      window.cytoscape.use(window.cytoscapeFcose);
      window.__fcoseRegistered = true;
    }

    const cy = window.cytoscape({
      container: hostRef.current,
      elements: [],
      style: stylesheet,
      // Default 1.0 is genuinely slow: measured 1.047x per notch vs 1.181x for
      // d3-force. 3.8 makes the wheel feel like a map.
      wheelSensitivity: themeRef.current.physics.wheelSensitivity,
      boxSelectionEnabled: false,
      selectionType: "single",
      minZoom: 0.05,
      maxZoom: 6,
      textureOnViewport: false,
      // MUST stay false. `true` hides every edge while panning or zooming, which
      // reads as "the edges are dim" — they are not dim, they are absent until the
      // view settles. It is a performance flag for huge graphs; at 975 edges there
      // is nothing to save.
      hideEdgesOnViewport: false,
      pixelRatio: "auto",
    });

    cyRef.current = cy;

    cy.on("tap", "node", (event) => {
      const node = event.target;
      // `nodeType`, not `type`: the Viewer branches on `entry.nodeType`, and an
      // entry carrying only `type` matches no branch and renders nothing at all.
      onNodeClick?.({
        nodeType: node.data("type"),
        id: node.data("id"),
        label: node.data("rawLabel"),
        platform: node.data("platform"),
        messageCount: node.data("messageCount"),
        firstTs: node.data("firstTs"),
        lastTs: node.data("lastTs"),
        isGroup: node.data("isGroup"),
      });
    });

    cy.on("tap", (event) => {
      if (event.target === cy) onBackgroundClick?.();
    });

    const observer = new ResizeObserver(() => cy.resize());
    observer.observe(hostRef.current);

    return () => {
      observer.disconnect();
      if (revealTimer.current) clearTimeout(revealTimer.current);
      cy.destroy();
      cyRef.current = null;
    };
    // Created once. Data and style are applied by the effects below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /* -------------------------------------------------------------------- style */

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.style().fromJson(stylesheet).update();
  }, [stylesheet]);

  /* --------------------------------------------------------------------- data */

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;

    if (revealTimer.current) {
      clearTimeout(revealTimer.current);
      revealTimer.current = null;
    }

    cy.elements().remove();
    if (!elements.length) return;

    cy.add(elements);

    runLayout(cy, themeRef.current, () => {
      // Synthetic nodes (bags) are not data. Counting them would make the readout
      // claim nodes the store does not hold — the same class of lie `Merged` would
      // tell in `types_present()` if it were not filtered there.
      onLayoutDone?.({
        nodes: cy.nodes().not(".synthetic").length,
        edges: cy.edges().not(".synthetic").length,
      });
      startReveal(cy, themeRef.current, revealTimer);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [elements]);

  /* ------------------------------------------------------------------ handle */

  useImperativeHandle(
    ref,
    () => ({
      /** Halo only. Used by a graph click and by AI results. */
      halo(id) {
        const cy = cyRef.current;
        if (!cy) return;
        const node = cy.getElementById(id);
        if (!node || node.empty()) return;
        cy.elements().unselect();
        node.select();
      },

      /** Halo + camera. Used by a result row only. */
      focus(id) {
        const cy = cyRef.current;
        if (!cy) return;
        const node = cy.getElementById(id);
        if (!node || node.empty()) return;
        cy.elements().unselect();
        node.select();
        // Multiply the CURRENT zoom rather than setting an absolute level, so the
        // motion is proportional wherever the user already is.
        cy.animate(
          { center: { eles: node }, zoom: cy.zoom() * 1.3 },
          { duration: 400 },
        );
      },

      clearHalo() {
        cyRef.current?.elements().unselect();
      },

      fit() {
        cyRef.current?.animate({ fit: { eles: cyRef.current.elements(), padding: 40 } },
          { duration: 300 });
      },

      rerunLayout() {
        const cy = cyRef.current;
        if (!cy) return;
        runLayout(cy, themeRef.current, () => onLayoutDone?.({}));
      },

      zoomBy(factor) {
        const cy = cyRef.current;
        if (!cy) return;
        cy.zoom({ level: cy.zoom() * factor, renderedPosition: {
          x: cy.width() / 2, y: cy.height() / 2,
        } });
      },

      getCy() {
        return cyRef.current;
      },
    }),
    [onLayoutDone],
  );

  /* -------------------------------------------------------------------- view */

  const haze = theme.visual.hazeOpacity;

  return (
    <div
      className="pane graph"
      style={{
        background: `radial-gradient(circle at 50% 42%, rgba(92,143,214,${haze}), transparent 62%), radial-gradient(circle at 20% 85%, rgba(79,179,165,${haze * 0.5}), transparent 55%), var(--bg)`,
      }}
    >
      <div id="cy" ref={hostRef} />
      {/* Derived from the config, never hardcoded: the legend drifted out of sync
          with PLATFORM_COLORS once already, and a legend that lies is worse than
          none. One row per distinct label, so the three IMAP keys collapse onto
          `Email` while `Outlook` keeps its own row. A platform with no adapter yet
          is drawn hollow rather than omitted. */}
      <div className="canvas-legend">
        {LEGEND_PLATFORMS.map((platform) => {
          const planned = PLANNED_PLATFORMS.has(platform);
          return (
            <div
              className={`legend-row${planned ? " planned" : ""}`}
              key={platform}
              title={planned ? "Adapter not built yet" : undefined}
            >
              <span
                className="legend-swatch"
                style={
                  planned
                    ? { border: `1px dashed ${platformColor(platform)}` }
                    : { background: platformColor(platform) }
                }
              />
              {platformLabel(platform)}
            </div>
          );
        })}
      </div>
    </div>
  );
});

export default GraphCanvas;

/* ======================================================================== pure */

function buildStylesheet(theme) {
  const { palette, labels, visual } = theme;

  /**
   * The thread glyph's fill fraction, corrected per platform.
   *
   * The base `iconScale` is one number for every glyph, but the artwork inside each
   * 24x24 viewBox does not occupy the same share of it — an envelope is wide and
   * reads large, a speech bubble is compact and reads small. `iconScaleByPlatform`
   * is the optical correction, and 1.0 is the default so a new platform needs no
   * entry.
   */
  const iconScaleFor = (visual, platform) =>
    visual.iconScale * (visual.iconScaleByPlatform?.[platform] ?? 1);

  return [
    {
      // The base rule is a FILLED CIRCLE, and it stays that way. Icons are an
      // override layer on top of it, not a replacement for it.
      //
      // That layering is what makes the fallback free: a node whose platform has no
      // icon file simply never matches an icon rule, so it keeps this fill and stays
      // visible. Making the icon styling the base instead would leave every node
      // with no fill and no border, and an unknown platform would draw as nothing at
      // all — an invisible node, which is the one failure this app must never have.
      selector: "node",
      style: {
        "background-color": "data(color)",
        "background-opacity": 0.92,
        "background-fit": "contain",
        "background-width": `${Math.round(visual.iconScale * 100)}%`,
        "background-height": `${Math.round(visual.iconScale * 100)}%`,
        "background-image-opacity": 1,
        "background-clip": "none",
        width: "data(size)",
        height: "data(size)",
        "border-width": 1,
        "border-color": "rgba(27,42,74,0.9)",
        "border-opacity": 0.9,
        label: "data(label)",
        "font-size": "data(fontSize)",
        "font-family": "Inter, system-ui, sans-serif",
        color: labels.color,
        "text-valign": "bottom",
        "text-halign": "center",
        "text-margin-y": 4,
        "text-wrap": "wrap",
        "text-max-width": `${labels.maxWidth}px`,
        // THIS is the zoom LOD. Text is skipped when font-size x zoom < this.
        "min-zoomed-font-size": labels.minZoomedFontSize,
        "text-opacity": 1,
        "overlay-opacity": 0,
        "transition-property": "opacity",
        "transition-duration": "160ms",
      },
    },
    {
      // The icon override. A glyph IS the mark, so the shaded circle behind it goes:
      // a flat-coloured icon on a shaded disc reads as a mistake. `background-opacity`
      // affects only the colour — `background-image-opacity` keeps the glyph visible.
      //
      // This is the ONLY thing that removes the base fill, which is why a platform
      // with no icon file is still drawn as a circle rather than vanishing.
      selector: "node.icon",
      style: {
        "background-opacity": 0,
        "border-width": 0,
        "background-image-opacity": 1,
        "background-clip": "none",
      },
    },
    // One static rule per platform, so the URL is a literal rather than a data map.
    // `background-image: data(x)` throws inside Cytoscape when a node's value is an
    // empty string, and it would also defeat the renderer's image cache.
    //
    // `node.icon` (threads) and `node.icon.person` (correspondents) are separate
    // selectors, so a platform's two glyphs never collide. `Person` / `Place` /
    // `Organization` / `Product` have no glyph by decision, so they match no rule
    // here and keep the base filled circle.
    // `iconScaleByPlatform` is the optical correction: the SVGs share a 24x24 box,
    // but a wide envelope and a compact speech bubble do not read as the same size at
    // the same scale. A platform with no entry keeps the base scale.
    ...Object.entries(PLATFORM_ICONS).map(([platform, url]) => ({
      selector: `node.icon[platform = "${platform}"]`,
      style: {
        "background-image": `url("${url}")`,
        "background-width": `${Math.round(iconScaleFor(visual, platform) * 100)}%`,
        "background-height": `${Math.round(iconScaleFor(visual, platform) * 100)}%`,
      },
    })),
    ...Object.entries(PERSON_ICONS).map(([platform, url]) => ({
      selector: `node.icon.person[platform = "${platform}"]`,
      style: {
        "background-image": `url("${url}")`,
        "background-width": `${Math.round(visual.correspondentIconScale * 100)}%`,
        "background-height": `${Math.round(visual.correspondentIconScale * 100)}%`,
      },
    })),
    // Shape and glow are generated from `NODE_TYPES`, so a new kind is a config
    // entry rather than a rule. Both are static literals — never `data()` — because
    // a mapper that fails to parse takes the whole stylesheet down with it.
    //
    // `Bag` is excluded: it is synthetic, it has its own rule above, and giving it a
    // shape or a glow would draw it.
    //
    // Selector grammar needs spaces around the operator: `[type = "x"]`.
    ...Object.entries(NODE_TYPES)
      .filter(([, meta]) => meta.drawable && meta.shape)
      .map(([type, meta]) => ({
        selector: `node[type = "${type}"]`,
        style: { shape: meta.shape },
      })),
    ...Object.entries(NODE_TYPES)
      .filter(([, meta]) => meta.drawable && meta.glow)
      .map(([type]) => ({
        // A non-thread kind keeps a permanent glow in its OWN source colour — that
        // glow is what makes it read as a different class of thing from a thread,
        // now that both are glyphs. The fill and border are left to the base rule
        // and the icon override; only the glow is added here.
        //
        // This is keyed on `type`, not on the kind class, so a kind with no glyph
        // file yet still glows instead of looking like a plain circle.
        selector: `node[type = "${type}"]`,
        style: {
          color: labels.correspondentColor,
          "border-color": "data(color)",
          "border-opacity": 1,
          "shadow-blur": visual.correspondentGlow,
          "shadow-color": "data(color)",
          "shadow-opacity": visual.correspondentGlowOpacity,
          "shadow-offset-x": 0,
          "shadow-offset-y": 0,
        },
      })),
    {
      // Selection cannot also be a glow now that correspondents glow by default, so
      // it is a bright border plus a much larger blur. Threads keep the glow-only
      // treatment because they have none of their own.
      selector: "node:selected",
      style: {
        "border-width": 3,
        "border-color": "#ffffff",
        "border-opacity": 1,
        "shadow-blur": visual.glowBlur * 2,
        "shadow-color": "#ffffff",
        "shadow-opacity": 0.9,
        "shadow-offset-x": 0,
        "shadow-offset-y": 0,
        "z-index": 9999,
      },
    },
    {
      selector: "edge",
      style: {
        width: "data(width)",
        "line-color": "data(color)",
        opacity: "data(opacity)",
        "curve-style": "bezier",
        "control-point-step-size": 40,
        "target-arrow-shape": "none",
        "overlay-opacity": 0,
        "transition-property": "opacity",
        "transition-duration": "160ms",
      },
    },
    {
      // A fuzzy identity guess, never a fact. Dashed and thin so it reads as a
      // question beside a solid `WITH` line — the same distinction the store makes
      // between a fold and an edge (direction.md §5).
      selector: 'edge[type = "POSSIBLY"]',
      style: {
        "line-style": "dashed",
        "line-dash-pattern": [6, 6],
        width: 1,
        opacity: 0.55,
      },
    },
    {
      selector: ".reveal-hidden",
      style: { opacity: 0 },
    },
    {
      // A bag: an invisible, inert body for fcose. One per platform, never seen.
      //
      // **This rule is LAST on purpose.** Cytoscape applies stylesheet blocks in
      // order, so a bag rule placed before the base `node` rule loses to it: the base
      // sets `background-opacity: 0.92` and `background-color: data(color)`, and a bag
      // carries no `color`, so `data(color)` falls back to Cytoscape's default grey.
      // That is exactly how the first version rendered — grey boxes around every
      // platform. Do not move this block up.
      //
      // Four traps, each of which silently breaks the feature:
      //  1. NEVER `display: "none"` — hiding a parent hides its children and breaks
      //     the compound relationship. Invisibility is `background-opacity: 0`.
      //  2. `events: "no"` is what makes it non-clickable; `selectable: false` alone
      //     still lets the bag swallow taps on its padding.
      //  3. `z-compound-depth: "bottom"` is what puts it behind its children;
      //     `z-index` alone does not.
      //  4. `padding` + `compound-sizing-wrt-labels: "exclude"` keep the body tied to
      //     the children's real geometry rather than an empty label box.
      selector: 'node[type = "Bag"]',
      style: {
        // Every property the base rule sets that could paint anything, overridden
        // explicitly. `background-color` is set to the page colour rather than left
        // to `data(color)`, so there is no fallback grey to leak through.
        "background-color": palette.bg,
        "background-opacity": 0,
        "background-image": "none",
        "background-image-opacity": 0,
        "border-width": 0,
        "border-opacity": 0,
        "shadow-opacity": 0,
        "overlay-opacity": 0,
        label: "",
        "text-opacity": 0,
        events: "no",
        selectable: false,
        grabbable: false,
        "z-compound-depth": "bottom",
        "z-index-compare": "manual",
        "z-index": 0,
        padding: 24,
        "compound-sizing-wrt-labels": "exclude",
      },
    },
  ];
}

/**
 * Assign a size letter to every node of one kind, cutting bands INSIDE each source.
 *
 * `letters` is ordered biggest-first and has exactly three entries — big, mid,
 * small. `bands` gives the share of that source's nodes in the first two bands; the
 * remainder is the small letter.
 *
 * The cut is by rank, not by value: sort the source's nodes descending and take the
 * top `top` share, then the next `mid` share. A value-based cut (mean ± stddev, or
 * percentiles of the value) collapses on this data, where 565 of 591 correspondents
 * have exactly one thread and the largest thread holds 707 messages.
 *
 * At least one node lands in each of the first two bands, so a source with two
 * threads still gets an A and a C rather than two identical dots.
 *
 * Returns `Map<nodeId, letter>`.
 */
function assignBands(nodes, countKey, letters, bands) {
  const result = new Map();
  if (!nodes.length) return result;

  const [big, mid, small] = letters;
  const top = bands?.top ?? 0.2;
  const middle = bands?.mid ?? 0.3;

  // Group by platform, then rank inside each group.
  const byPlatform = new Map();
  for (const node of nodes) {
    const platform = String(node.platform || "").toLowerCase();
    if (!byPlatform.has(platform)) byPlatform.set(platform, []);
    byPlatform.get(platform).push(node);
  }

  for (const group of byPlatform.values()) {
    const ranked = [...group].sort(
      (a, b) => (Number(b[countKey]) || 0) - (Number(a[countKey]) || 0),
    );
    const total = ranked.length;
    // Rounded up so a small platform still splits; clamped so the small band keeps
    // at least one node whenever there are three or more to go round.
    let bigCount = Math.max(1, Math.round(total * top));
    let midCount = Math.max(1, Math.round(total * middle));
    if (total >= 3 && bigCount + midCount > total - 1) {
      midCount = Math.max(1, total - bigCount - 1);
    }
    if (bigCount + midCount > total) {
      midCount = Math.max(0, total - bigCount);
    }

    // Never split a run of equal values across a boundary — the whole run drops
    // into the smaller band. This is what stops Telegram's "big" band from being
    // 109 threads of which 104 hold one message: the 1-message run is one group,
    // so it lands entirely in the small band and A means genuinely big.
    bigCount = snapToRunEnd(ranked, bigCount, countKey);
    midCount = snapToRunEnd(ranked, bigCount + midCount, countKey) - bigCount;

    // ...unless snapping empties the mid band. Telegram is 486 one-message threads
    // out of 547, so after snapping, A is the 61 threads with more than one message
    // and everything else is one giant tie run. Keep that honest A — it is the whole
    // point of the letter — and split the leftover run between mid and small so the
    // ladder still has three visible rungs.
    if (midCount === 0 && total - bigCount > 1) {
      midCount = Math.max(1, Math.round((total - bigCount) * middle));
    }

    ranked.forEach((node, index) => {
      const letter = index < bigCount ? big : index < bigCount + midCount ? mid : small;
      result.set(node.id, letter);
    });
  }

  return result;
}

/**
 * Move a band boundary back to the start of the run of equal values it would split.
 *
 * `ranked` is sorted descending, so a boundary at `index` splits a run when
 * `ranked[index - 1]` and `ranked[index]` hold the same count. Walking back to the
 * first index of that run keeps every equal node in the same band.
 */
function snapToRunEnd(ranked, index, countKey) {
  if (index <= 0 || index >= ranked.length) return index;
  const value = Number(ranked[index][countKey]) || 0;
  let cursor = index;
  while (cursor > 0 && (Number(ranked[cursor - 1][countKey]) || 0) === value) {
    cursor -= 1;
  }
  return cursor;
}

/**
 * The first rung whose threshold is met. Rungs are ordered largest-first, so the
 * last one (`min: 0`) is the catch-all and always matches.
 *
 * Returns the rung plus the value it matched on, because the edge tiers are keyed on
 * the source thread's message count and need that number back.
 */
function rungFor(table, key, value) {
  const count = Number(value) || 0;
  for (const rung of table) {
    if (count >= (rung[key] ?? 0)) return { ...rung, count };
  }
  return { ...table[table.length - 1], count };
}


/**
 * A deterministic shade of a platform colour.
 *
 * Same id always gives the same shade, so a cluster reads as a family of related
 * tones and the picture is identical on every load. `jitter` is the fraction of
 * lightness the shade may move in either direction.
 */
function shade(hex, id, jitter) {
  if (!jitter) return hex;
  const [r, g, b] = hexToRgb(hex);
  // Cheap stable hash — FNV-1a over the id.
  let hash = 2166136261;
  for (let i = 0; i < id.length; i += 1) {
    hash ^= id.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  const t = ((hash >>> 0) % 1000) / 1000; // 0..1
  const delta = (t * 2 - 1) * jitter; // -jitter..+jitter
  const mix = delta > 0 ? 255 : 0;
  const amount = Math.abs(delta);
  return rgbToHex(
    Math.round(r + (mix - r) * amount),
    Math.round(g + (mix - g) * amount),
    Math.round(b + (mix - b) * amount),
  );
}

/** Mix a hex colour toward white. `amount` 0 = unchanged, 1 = white. */
function lighten(hex, amount) {
  if (!amount) return hex;
  const [r, g, b] = hexToRgb(hex);
  const mix = (value) => Math.round(value + (255 - value) * amount);
  return rgbToHex(mix(r), mix(g), mix(b));
}

function hexToRgb(hex) {
  const clean = String(hex).replace("#", "");
  const full = clean.length === 3
    ? clean.split("").map((c) => c + c).join("")
    : clean;
  return [
    parseInt(full.slice(0, 2), 16) || 0,
    parseInt(full.slice(2, 4), 16) || 0,
    parseInt(full.slice(4, 6), 16) || 0,
  ];
}

function rgbToHex(r, g, b) {
  const part = (value) => Math.max(0, Math.min(255, value)).toString(16).padStart(2, "0");
  return `#${part(r)}${part(g)}${part(b)}`;
}

/**
 * Move each platform bag onto a circle, after the layout has settled.
 *
 * **Why not `fixedNodeConstraint`.** That is the obvious fcose mechanism, and it is
 * fatal here: `spectralLayout` builds its `nodeIndexes` map with
 * `if (!nodes[i].isParent())` (`cytoscape-fcose.js:1313`), so a compound node is
 * never in it. The constraint handler then reads `xCoords[nodeIndexes.get(bagId)]`,
 * gets `undefined`, and the Procrustes transform turns every coordinate into `NaN` —
 * a blank canvas and a stalled refresh. Do not put a bag in a constraint.
 *
 * So the ring is applied as a **translation** instead. Each bag's children are moved
 * as a block so the bag's centroid lands on the circle; the merged nodes outside the
 * bags are not moved at all, which is exactly the intent — the bags go to the
 * outside, the bridges stay where their edges put them, and the middle is what is
 * left.
 *
 * Order is the legend order, so a platform is always in the same place. A graph that
 * reshuffles itself between visits reads as noise.
 */
function placeBagsOnRing(cy, spread = 1) {
  const bags = cy.nodes('[type = "Bag"]');
  if (bags.length < 2) return;

  // Radius from the bags' own footprint, so seven of them sit shoulder to shoulder
  // without touching and a small store does not get a vast empty circle.
  const widest = Math.max(
    ...bags.map((bag) => Math.max(bag.outerWidth(), bag.outerHeight())),
  );
  // A compound whose bounds have not settled reports `NaN`, and a `NaN` radius would
  // put every child at `NaN` — the same blank canvas the constraint produced. Fall
  // back to a fixed radius rather than trusting the measurement.
  const base = Number.isFinite(widest) && widest > 0 ? widest * 1.6 : 260;
  const radius = Math.max(base, 260) * (spread || 1);

  const ordered = bags.toArray().sort((a, b) => {
    const ai = LEGEND_PLATFORMS.indexOf(a.data("platform"));
    const bi = LEGEND_PLATFORMS.indexOf(b.data("platform"));
    // A platform not in the legend still gets a stable slot, after the known ones.
    return (ai < 0 ? LEGEND_PLATFORMS.length : ai) - (bi < 0 ? LEGEND_PLATFORMS.length : bi);
  });

  cy.batch(() => {
    ordered.forEach((bag, index) => {
      const children = bag.children();
      if (!children.length) return;

      const angle = (2 * Math.PI * index) / ordered.length - Math.PI / 2;
      const target = { x: Math.cos(angle) * radius, y: Math.sin(angle) * radius };

      // The bag's own box is the union of its children, so moving the children moves
      // the bag. Its centre is read from the children, not from `bag.position()`,
      // which for a compound is derived and can lag a frame behind.
      //
      // `position()` is ABSOLUTE even for a child (Cytoscape's `relativePosition()`
      // is the one that subtracts the parent), so an absolute delta is right here.
      const box = children.boundingBox();
      const dx = target.x - (box.x1 + box.w / 2);
      const dy = target.y - (box.y1 + box.h / 2);
      if (!Number.isFinite(dx) || !Number.isFinite(dy)) return;

      children.forEach((child) => {
        const position = child.position();
        child.position({ x: position.x + dx, y: position.y + dy });
      });
    });
  });
}

/**
 * Turn fcose's "smart" ideal-edge-length calculation on or off.
 *
 * `calcIdealEdgeLengths` (`layout-base.js`) adds `sizeOfSourceInLca +
 * sizeOfTargetInLca - 2 * SIMPLE_NODE_SIZE` to every edge that crosses a compound
 * boundary. Those sizes are the BAGS' estimated sizes, so a 31-node Telegram bag adds
 * ~250px to every merged-node edge. That is the long-line problem, and it is not a
 * slider — it is a global constant read when the layout object is constructed.
 *
 * The constant is reachable from the page because `layout-base.js` and `cose-base.js`
 * are vendored as UMD scripts that publish `layoutBase` / `coseBase` on `window`.
 * Setting it here, before `cy.layout(options)` runs, is the only way to change it.
 */
function setSmartEdgeLength(enabled) {
  const targets = [
    window.layoutBase?.FDLayoutConstants,
    window.coseBase?.CoSEConstants,
  ].filter(Boolean);
  for (const constants of targets) {
    constants.DEFAULT_USE_SMART_IDEAL_EDGE_LENGTH_CALCULATION = !!enabled;
  }
  return targets.length > 0;
}

function runLayout(cy, theme, done) {
  const { physics, layout } = theme;

  // Must happen before the layout object is constructed: the constant is read in the
  // `FDLayout` constructor, not per iteration.
  setSmartEdgeLength(physics.smartEdgeLength);
  const options = {
    name: layout.name,
    quality: "default",
    animate: false,
    fit: layout.fit,
    padding: layout.padding,
    randomize: physics.randomize,
    nodeRepulsion: physics.nodeRepulsion,
    idealEdgeLength: physics.idealEdgeLength,
    gravity: physics.gravity,
    // Compound gravity is what squeezes each bag toward its own centre. Global
    // `gravity` pulls everything toward the middle of the screen and would crush the
    // seven bags into one ball, so the two are not interchangeable.
    //
    // Both only act on a graph fcose considers DISCONNECTED (`cose-base.js`
    // `calculateNodesToApplyGravitationTo`), so on a fully wired store they are
    // mostly inert. They are not the lever for clustering — the ring is.
    gravityCompound: physics.gravityCompound,
    gravityRangeCompound: physics.gravityRangeCompound,
    nodeSeparation: physics.nodeSeparation,
    numIter: physics.numIter,
    // Labels are part of a node's box. Without this the solver places an 18px node
    // and then draws a 120px label over its neighbours.
    nodeDimensionsIncludeLabels: !!physics.nodeDimensionsIncludeLabels,
    // `packComponents` is a NO-OP here: fcose gates it on `cy.layoutUtilities`, a
    // separate plugin that is not vendored. Left on because it is harmless and would
    // start working the day the plugin is added.
    packComponents: true,
    uniformNodeDimensions: false,
  };

  const finish = () => {
    // The ring is applied AFTER the solver, as a translation. See `placeBagsOnRing`
    // for why it cannot be a `fixedNodeConstraint`.
    if (layout.bagRing) placeBagsOnRing(cy, layout.bagRingSpread);
    // STEP 2 BLANKED THE CANVAS (2026-11-21) — read-before-write did NOT fix it.
    // Disabled again. Next suspect is the mutation itself inside `layoutstop`;
    // step 3 will schedule the pull one tick after finish() via rAF.
    // if (layout.bagRing) pullBridgesToRing(cy, 0.6);

    // `fit: true` shrinks until everything is visible, which at this node count
    // puts neighbours closer than a node's own diameter. zoomDistance lifts it.
    //
    // Re-fit after the ring moved things, and fit to the real nodes only: a bag is
    // synthetic and its box is just its children's, so including it changes nothing
    // except the chance of a stale bound.
    if (layout.fit) cy.fit(cy.elements().not(".synthetic"), layout.padding);
    const distance = physics.zoomDistance || 1;
    if (distance !== 1) cy.zoom(cy.zoom() * distance);
    done?.();
  };

  try {
    const instance = cy.layout(options);
    instance.one("layoutstop", finish);
    instance.run();
  } catch (error) {
    // fcose missing (vendor script failed to load) — fall back to a layout that
    // always exists, and say so rather than showing a blank canvas.
    console.error("fcose layout failed, falling back to cose", error);
    cy.layout({ name: "cose", animate: false, fit: true, padding: 40 }).run();
    finish();
  }
}

function startReveal(cy, theme, timerRef) {
  if (!theme.reveal.enabled) {
    cy.elements().not(".synthetic").removeClass("reveal-hidden");
    return;
  }

  // Bags are synthetic: they are not data, so they must not appear in the reveal.
  // `cy.nodes()` includes them, which is why nothing may use its `.length` raw.
  const nodes = cy.nodes().not(".synthetic").toArray();
  if (!nodes.length) return;

  // Order by first message, so the graph grows the way the relationship did.
  // Correspondents have no timestamp; they land at the end.
  const ordered = [...nodes].sort((a, b) => {
    const at = a.data("firstTs");
    const bt = b.data("firstTs");
    if (!at && !bt) return 0;
    if (!at) return 1;
    if (!bt) return -1;
    return at < bt ? -1 : at > bt ? 1 : 0;
  });

  const order = new Map();
  ordered.forEach((node, index) => order.set(node.id(), index));

  const total = ordered.length;
  const edgeOrder = new Map();
  cy.edges().not(".synthetic").forEach((edge) => {
    const a = order.get(edge.data("source")) ?? total;
    const b = order.get(edge.data("target")) ?? total;
    edgeOrder.set(edge.id(), Math.max(a, b));
  });

  // Bags are never hidden: hiding a parent would hide its children with it.
  cy.elements().not(".synthetic").addClass("reveal-hidden");

  const steps = Math.max(1, theme.reveal.steps);
  const interval = Math.max(16, theme.reveal.durationMs / steps);
  let step = 0;

  const tick = () => {
    step += 1;
    const threshold = Math.ceil((step / steps) * total);
    cy.batch(() => {
      ordered.forEach((node, index) => {
        if (index < threshold) node.removeClass("reveal-hidden");
      });
      cy.edges().not(".synthetic").forEach((edge) => {
        if ((edgeOrder.get(edge.id()) ?? total) < threshold) {
          edge.removeClass("reveal-hidden");
        }
      });
    });

    if (step < steps) {
      timerRef.current = setTimeout(tick, interval);
    } else {
      cy.elements().not(".synthetic").removeClass("reveal-hidden");
      timerRef.current = null;
    }
  };

  timerRef.current = setTimeout(tick, interval);
}
