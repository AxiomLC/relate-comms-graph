import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
} from "react";

import {
  PERSON_ICONS,
  PLATFORM_ICONS,
  personIcon,
  platformColor,
  platformIcon,
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
const LEGEND_PLATFORMS = [
  "messenger", "telegram", "whatsapp", "linkedin", "email", "outlook",
];

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
  const elements = useMemo(() => {
    const theme = themeRef.current; // eslint-disable-line no-shadow
    if (!data) return [];

    // Size letters are computed PER SOURCE, because the platforms are not on the
    // same scale (theme.js §tiers). Threads may only be A/C/E and correspondents
    // B/D/F, so the two ladders interleave and a thread always outranks the
    // correspondent of the same band.
    const allNodes = data.nodes || [];
    const threadLetters = assignBands(
      allNodes.filter((node) => node.type === "Thread"),
      "message_count",
      ["A", "C", "E"],
      theme.tiers.bands,
    );
    const correspondentLetters = assignBands(
      allNodes.filter((node) => node.type === "Correspondent"),
      "thread_count",
      ["B", "D", "F"],
      theme.tiers.bands,
    );

    // Message count per thread, for the edge tiers (a `WITH` edge carries no weight).
    const threadCounts = new Map(
      allNodes
        .filter((node) => node.type === "Thread")
        .map((node) => [node.id, node.message_count || 0]),
    );

    const nodes = allNodes.map((node) => {
      const isThread = node.type === "Thread";
      const letter = isThread
        ? threadLetters.get(node.id)
        : correspondentLetters.get(node.id);
      const tier = theme.tiers.sizes[letter] || theme.tiers.sizes.F;

      const base = platformColor(node.platform);
      // The icon is a flat platform colour, so an icon node drops its shaded circle —
      // otherwise the two fight. Threads use the source glyph, correspondents the
      // person glyph; each has its own toggle.
      const icon = isThread
        ? theme.visual.nodeIcons
          ? platformIcon(node.platform)
          : null
        : theme.visual.correspondentIcons
          ? personIcon(node.platform)
          : null;

      return {
        group: "nodes",
        // A CLASS, not a data field. Cytoscape's `[key]` selector tests whether the
        // field EXISTS, so `image: null` matched every node and stripped the fill
        // from the whole graph. A class is unambiguous.
        classes: icon ? (isThread ? "icon" : "icon person") : "",
        data: {
          id: node.id,
          // One line, same as every other node. The source is already carried by
          // the node's colour and, when on, its icon — a SOURCE line above the
          // title was redundant.
          label: isThread
            ? truncateLabel(node.label || node.id, 34)
            : truncateLabel(node.label || node.id, 28),
          rawLabel: node.label || node.id,
          type: node.type,
          platform: node.platform || "",
          messageCount: node.message_count || 0,
          threadCount: node.thread_count || 0,
          firstTs: node.first_ts || null,
          lastTs: node.last_ts || null,
          isGroup: !!node.is_group,
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

    const ids = new Set(nodes.map((n) => n.data.id));
    const edges = (data.edges || [])
      .filter((edge) => ids.has(edge.source) && ids.has(edge.target))
      .map((edge) => {
        // Edge weight comes from the source thread's size — `WITH` stores no count.
        const tier = rungFor(theme.tiers.edge, "min", threadCounts.get(edge.source) ?? 0);
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

    return [...nodes, ...edges];
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, sizeKey]);

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
      onLayoutDone?.({ nodes: cy.nodes().length, edges: cy.edges().length });
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
          none. One row per distinct label, so the four email keys collapse. */}
      <div className="canvas-legend">
        {LEGEND_PLATFORMS.map((platform) => (
          <div className="legend-row" key={platform}>
            <span
              className="legend-swatch"
              style={{ background: platformColor(platform) }}
            />
            {platformLabel(platform)}
          </div>
        ))}
      </div>
    </div>
  );
});

export default GraphCanvas;

/* ======================================================================== pure */

function buildStylesheet(theme) {
  const { palette, labels, visual } = theme;

  return [
    {
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
      // An icon node drops its fill: the glyph IS the mark, and a shaded circle
      // behind a flat-coloured icon reads as a mistake. `background-opacity` affects
      // only the colour — `background-image-opacity` keeps the glyph visible.
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
    // selectors, so a platform's two glyphs never collide.
    ...Object.entries(PLATFORM_ICONS).map(([platform, url]) => ({
      selector: `node.icon[platform = "${platform}"]`,
      style: { "background-image": `url("${url}")` },
    })),
    ...Object.entries(PERSON_ICONS).map(([platform, url]) => ({
      selector: `node.icon.person[platform = "${platform}"]`,
      style: {
        "background-image": `url("${url}")`,
        "background-width": `${Math.round(visual.correspondentIconScale * 100)}%`,
        "background-height": `${Math.round(visual.correspondentIconScale * 100)}%`,
      },
    })),
    {
      // Selector grammar needs spaces around the operator: `[type = "x"]`.
      // Correspondents are circles with a border and glow in their OWN source
      // colour — the glow is the whole point, so it is strong and the border matches
      // the fill rather than the generic blue outline. With the person glyph on, the
      // fill goes away and the glow carries the class distinction instead.
      selector: 'node[type = "Correspondent"]',
      style: {
        shape: "ellipse",
        color: labels.correspondentColor,
        "background-opacity": 1,
        "border-width": 1.5,
        "border-color": "data(color)",
        "border-opacity": 1,
        "shadow-blur": visual.correspondentGlow,
        "shadow-color": "data(color)",
        "shadow-opacity": visual.correspondentGlowOpacity,
        "shadow-offset-x": 0,
        "shadow-offset-y": 0,
      },
    },
    {
      // The glyph replaces the fill, but the glow and border stay: a correspondent
      // must still read as a different class of thing from a thread.
      selector: 'node[type = "Correspondent"].icon',
      style: {
        "background-opacity": 0,
        "border-width": 0,
        "background-image-opacity": 1,
        "background-clip": "none",
      },
    },
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
      selector: ".reveal-hidden",
      style: { opacity: 0 },
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

function runLayout(cy, theme, done) {
  const { physics, layout } = theme;
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
    nodeSeparation: physics.nodeSeparation,
    numIter: physics.numIter,
    // fcose samples every node pair; at 1.5k nodes the default is fine, but
    // `packComponents` keeps disconnected clusters from overlapping.
    packComponents: true,
    uniformNodeDimensions: false,
  };

  const finish = () => {
    // `fit: true` shrinks until everything is visible, which at this node count
    // puts neighbours closer than a node's own diameter. zoomDistance lifts it.
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
    cy.elements().removeClass("reveal-hidden");
    return;
  }

  const nodes = cy.nodes().toArray();
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
  cy.edges().forEach((edge) => {
    const a = order.get(edge.data("source")) ?? total;
    const b = order.get(edge.data("target")) ?? total;
    edgeOrder.set(edge.id(), Math.max(a, b));
  });

  cy.elements().addClass("reveal-hidden");

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
      cy.edges().forEach((edge) => {
        if ((edgeOrder.get(edge.id()) ?? total) < threshold) {
          edge.removeClass("reveal-hidden");
        }
      });
    });

    if (step < steps) {
      timerRef.current = setTimeout(tick, interval);
    } else {
      cy.elements().removeClass("reveal-hidden");
      timerRef.current = null;
    }
  };

  timerRef.current = setTimeout(tick, interval);
}
