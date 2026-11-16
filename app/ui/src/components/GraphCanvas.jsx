import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
} from "react";

import {
  PLATFORM_ICONS,
  platformColor,
  platformIcon,
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

  // Depends on `data` and `theme`: a tier edit changes sizes, which are element data,
  // so the elements are rebuilt. The layout is NOT re-run by that — only the explicit
  // "Re-run layout" button does that, because a graph that keeps bobbing looks like a
  // physics toy (UI-Cytoscape.md §11).
  const elements = useMemo(() => {
    if (!data) return [];

    // One shared ladder of six rungs. A thread is matched on message count, a
    // correspondent on thread count — the two quantities are not comparable, so each
    // rung carries a threshold for both.
    const threadTiers = new Map();
    for (const node of data.nodes || []) {
      if (node.type === "Thread") {
        threadTiers.set(
          node.id,
          rungFor(theme.tiers.ladder, "threadMin", node.message_count || 0),
        );
      }
    }

    const nodes = (data.nodes || []).map((node) => {
      const isThread = node.type === "Thread";
      const tier = isThread
        ? threadTiers.get(node.id)
        : rungFor(theme.tiers.ladder, "correspondentMin", node.thread_count || 0);

      const base = platformColor(node.platform);
      // Threads only, and only when the toggle is on. The icon is a flat platform
      // colour, so an icon node drops its shaded circle — otherwise the two fight.
      const icon = isThread && theme.visual.nodeIcons ? platformIcon(node.platform) : null;

      return {
        group: "nodes",
        // A CLASS, not a data field. Cytoscape's `[key]` selector tests whether the
        // field EXISTS, so `image: null` matched every node and stripped the fill
        // from the whole graph. A class is unambiguous.
        classes: icon ? "icon" : "",
        data: {
          id: node.id,
          // Two lines for a thread: SOURCE above, title below. Cytoscape allows one
          // label and one style, so the hierarchy is uppercasing + ordering.
          label: isThread
            ? threadLabel(node, theme)
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
        const tier = rungFor(theme.tiers.edge, "min", threadTiers.get(edge.source)?.count ?? 0);
        const platform = nodes.find((n) => n.data.id === edge.source)?.data.platform || "";
        return {
          group: "edges",
          data: {
            id: `${edge.type}:${edge.source}->${edge.target}`,
            source: edge.source,
            target: edge.target,
            type: edge.type,
            color: platformColor(platform),
            width: tier.width,
            opacity: tier.opacity,
          },
        };
      });

    return [...nodes, ...edges];
  }, [data, theme]);

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
      hideEdgesOnViewport: true,
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
      <div className="canvas-legend">
        <div className="legend-row">
          <span className="legend-swatch" style={{ background: "#5c8fd6" }} />
          messenger
        </div>
        <div className="legend-row">
          <span className="legend-swatch" style={{ background: "#4fb3a5" }} />
          telegram
        </div>
        <div className="legend-row">
          <span className="legend-swatch" style={{ background: "#5fa86b" }} />
          whatsapp
        </div>
        <div className="legend-row">
          <span className="legend-swatch" style={{ background: "#7f8fd0" }} />
          linkedin
        </div>
        <div className="legend-row">
          <span className="legend-swatch" style={{ background: "#c08a4a" }} />
          email
        </div>
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
    ...Object.entries(PLATFORM_ICONS).map(([platform, url]) => ({
      selector: `node.icon[platform = "${platform}"]`,
      style: { "background-image": `url("${url}")` },
    })),
    {
      // Selector grammar needs spaces around the operator: `[type = "x"]`.
      // Correspondents glow permanently, in their own source colour, so they read as
      // a different class of thing against the threads.
      selector: 'node[type = "Correspondent"]',
      style: {
        shape: "round-rectangle",
        color: labels.correspondentColor,
        "background-opacity": 0.8,
        "shadow-blur": visual.correspondentGlow,
        "shadow-color": "data(color)",
        "shadow-opacity": visual.correspondentGlowOpacity,
        "shadow-offset-x": 0,
        "shadow-offset-y": 0,
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
 * The first rung whose threshold is met. Rungs are ordered largest-first, so the
 * last one (`min: 0`) is the catch-all and always matches.
 *
 * `key` names the threshold field, because the shared ladder carries one per kind
 * (`threadMin`, `correspondentMin`) while the edge table carries a single `min`.
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
 * A thread's two-line label: SOURCE above, title below.
 *
 * The title is whatever the adapter derived — `writer.thread_display_title()`
 * already guarantees it is never empty (TECHREADME.md §5), so this does not
 * invent a fallback. Truncation happens here, upstream of the canvas, so the graph
 * and the Viewer agree on the string.
 */
function threadLabel(node, theme) {
  const title = truncateLabel(node.label || node.id, 34);
  if (!theme.labels.showSourceLine) return title;
  const source = String(node.platform || "").toUpperCase();
  return source ? `${source}\n${title}` : title;
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
