import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api } from "./lib/api.js";
import { loadTheme, saveTheme } from "./config/theme.js";
import { useViewerStack } from "./lib/useViewerStack.js";

import { ActivityLog, useActivity } from "./components/ActivityLog.jsx";
import ChatPanel from "./components/ChatPanel.jsx";
import CommandBar from "./components/CommandBar.jsx";
import GraphCanvas from "./components/GraphCanvas.jsx";
import Viewer from "./components/Viewer.jsx";
import CanvasModal from "./components/modals/CanvasModal.jsx";
import GravityModal from "./components/modals/GravityModal.jsx";
import IngestModal from "./components/modals/IngestModal.jsx";
import LogModal from "./components/modals/LogModal.jsx";

import UtilitiesModal from "./components/modals/UtilitiesModal.jsx";

/**
 * The shell. It owns exactly four pieces of state, and each one has a reason:
 *
 *  - `theme`      every tunable, persisted to localStorage (UI-Cytoscape.md §12)
 *  - `viewer`     the state timeline, so halo/fly-to can be decided per push
 *  - `chatOpen`   the one panel with a toggle
 *  - `modal`      which modal is open, if any
 *
 * The halo / fly-to rule (UI-Cytoscape.md §10) is enforced here rather than in the
 * canvas, because only this component knows whether a push came from a graph click
 * or a result row:
 *
 *   graph node click  -> halo, no camera move, viewer = node
 *   result row click  -> halo AND camera move, viewer = node
 *   back              -> neither
 *   AI returns hits   -> neither, viewer = results
 *
 * "Back never moves the camera. Clicking around must not yank the view."
 */
export default function App() {
  const [theme, setTheme] = useState(loadTheme);
  const [chatOpen, setChatOpen] = useState(true);
  const [chatExpanded, setChatExpanded] = useState(false);
  const [viewerExpanded, setViewerExpanded] = useState(false);
  const [modal, setModal] = useState(null);
  const [searchMode, setSearchMode] = useState("fulltext");
  const [embedStatus, setEmbedStatus] = useState(null);
  const [mcpConnected, setMcpConnected] = useState(false);
  // One activity feed for every surface that touches the store: search, chat, MCP.
  const activity = useActivity();
  const [graph, setGraph] = useState(null);
  const [graphError, setGraphError] = useState(null);
  const [stats, setStats] = useState(null);
  const [storeOk, setStoreOk] = useState(true);
  const [searchBusy, setSearchBusy] = useState(false);
  // Platform filter, mirrored from the server so the title bar can show it. The
  // server is the source of truth: it is what the tools actually read.
  const [platforms, setPlatforms] = useState({ active: null, total: 0 });
  // The full platform rows, for the Canvas modal's view-only cluster toggle.
  // `platforms` above is only the badge summary.
  const [platformRows, setPlatformRows] = useState({ rows: [] });

  const canvasRef = useRef(null);
  const viewer = useViewerStack();

  // The stack lives in `useViewerStack`; the Viewer renders `viewer.current`.
  //
  // `push` and `back` are stable `useCallback`s with no dependencies, so they can
  // be called from anywhere without a stale closure. The Viewer is a pure function
  // of `entry` — it holds no history of its own, which is what makes Back a state
  // restore rather than a second stack that can disagree with this one.

  // A deep link, so a thread can be opened from a URL and a reload keeps it.
  // `#thread=<key>` is the only form; anything else is ignored rather than guessed.
  const deepLinked = useRef(false);
  useEffect(() => {
    if (deepLinked.current) return;
    const match = /^#thread=(.+)$/.exec(window.location.hash || "");
    if (!match) return;
    deepLinked.current = true;
    const key = decodeURIComponent(match[1]);
    viewer.push({ kind: "node", nodeType: "Thread", id: key, label: key });
  }, [viewer]);

  /* ------------------------------------------------------------------ theme */

  const updateTheme = useCallback((next) => {
    setTheme(next);
    saveTheme(next);
  }, []);

  /* ------------------------------------------------------------------ graph */

  const loadGraph = useCallback(async (nodeTypes, { sort, limit } = {}) => {
    setGraphError(null);
    const fetchGraph = () =>
      api.graph({
        nodeTypes,
        sort: sort || theme.filter.sort || "messages",
        limit: limit || theme.filter.limit || 2000,
      });
    try {
      let data;
      try {
        data = await fetchGraph();
      } catch (err) {
        // **A busy store is transient.** Relate allows one writer, so an ingest running
        // in another surface makes this read fail. Retrying is the correct response —
        // the alternative is a red banner that only a manual refresh clears, which is
        // what the user actually saw.
        if (!/store is busy/i.test(err.message)) throw err;
        await new Promise((resolve) => setTimeout(resolve, 1500));
        data = await fetchGraph();
      }
      setGraph(data);
    } catch (err) {
      setGraphError(err.message);
    }
    // `theme.filter.sort/limit` are read as defaults, not dependencies: the modal
    // passes them explicitly, and depending on the whole theme would refetch on
    // every slider move.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    let cancelled = false;
    // **`embedStatus` is NOT in this Promise.all.** It opens the store, and the store
    // is now ~65 MB because of the vectors, so a connection costs ~0.5 s. Blocking
    // boot on it delayed the whole UI. It is only needed to decide whether to show
    // the "run embeds" pill, so it loads after the app is already usable.
    Promise.all([api.health(), api.stats(), api.platforms()])
      .then(([health, counts, platformData]) => {
        if (cancelled) return;
        setStoreOk(!!health.store_exists);
        setMcpConnected(!!health.mcp_active);
        setStats(counts);
        setPlatforms({
          active: platformData.active,
          total: (platformData.platforms || []).length,
        });
        setPlatformRows({ rows: platformData.platforms || [] });
      })
      .catch(() => {
        /* the canvas will report the real error */
      });

    // Deferred: the pill can appear a moment later without holding up the app.
    api
      .embedStatus()
      .then((embeds) => {
        if (!cancelled) setEmbedStatus(embeds);
      })
      .catch(() => {});

    return () => {
      cancelled = true;
    };
  }, []);

  // **The MCP badge polls.** The MCP server is a separate process, so it can connect or
  // disconnect at any moment and the app has no event to listen for. A 10 s poll of a
  // cheap endpoint is the honest way to show it: the badge lights up when a client
  // starts calling tools and goes dark 2 minutes after the last call.
  useEffect(() => {
    let cancelled = false;
    const tick = () => {
      api
        .health()
        .then((health) => {
          if (!cancelled) setMcpConnected(!!health.mcp_active);
        })
        .catch(() => {});
      // The trace is drained on the same tick: the MCP server appends rows to a file,
      // and this is the only thing that reads them. Draining means a row appears once.
      api
        .activity()
        .then(({ rows }) => {
          if (cancelled || !rows?.length) return;
          rows.forEach((row) =>
            activity.push({
              source: "mcp",
              text: row.text,
              ms: row.ms,
              status: row.status === "error" ? "error" : undefined,
            }),
          );
        })
        .catch(() => {});
    };
    const timer = setInterval(tick, 10000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [activity.push]);

  // The one automatic fetch: the first paint. It reads the saved filter from
  // `loadTheme()`, so a returning user sees the canvas they left. Nothing after this
  // re-fetches without the user pressing a button.
  const booted = useRef(false);
  useEffect(() => {
    if (booted.current) return;
    booted.current = true;
    loadGraph(theme.filter.nodeTypes, {
      sort: theme.filter.sort,
      limit: theme.filter.limit,
    });
    // Mount only. `theme` is read, not watched — a dependency here would restore the
    // exact re-fetch-on-every-edit behaviour this block replaced.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // **No effect watches the filter any more.** Sort, limit and the per-kind
  // visibility are VIEW settings, and the canvas is a window onto the store — search,
  // the Viewer and the AI chat read `graph.rl` directly and are unaffected by any of
  // them. So nothing here re-fetches on a theme change.
  //
  // The Canvas modal holds its edits until the user presses "Re-run layout", which
  // calls `applyCanvas` below: fetch the slice the new settings describe, then let the
  // canvas re-solve. That is exactly how the Gravity modal works, and it is why a
  // filter can now be changed without the graph jumping.
  //
  // The earlier `filterKey` effect was a bug even under the old model: the modal also
  // called `onReload` itself, so one press of a sort button fetched twice.
  const applyCanvas = useCallback(
    async (nextTheme) => {
      const filter = nextTheme?.filter || theme.filter;
      await loadGraph(filter.nodeTypes, { sort: filter.sort, limit: filter.limit });
      // Re-solve AFTER the new elements land. The canvas skips its own layout for a
      // rebuild that preserves positions, so the button has to ask explicitly —
      // otherwise "Re-run layout" would apply the filter without re-running anything.
      canvasRef.current?.rerunLayout();
    },
    [loadGraph, theme.filter],
  );

  /* ---------------------------------------------------------------- actions */

  const openNode = useCallback(
    (node) => {
      viewer.push({ kind: "node", ...node });
    },
    [viewer.push],
  );

  // Keep the URL in step with the Viewer, so a reload lands where the user was.
  useEffect(() => {
    const entry = viewer.current;
    const next =
      entry?.kind === "node" && entry.nodeType === "Thread"
        ? `#thread=${encodeURIComponent(entry.id)}`
        : "";
    if (window.location.hash !== next) {
      window.history.replaceState(null, "", next || window.location.pathname);
    }
  }, [viewer.current]);

  /** A graph click: halo only. The camera stays where the user put it. */
  const onGraphNodeClick = useCallback(
    (node) => {
      canvasRef.current?.halo(node.id);
      openNode(node);
    },
    [openNode],
  );

  /** A result row: halo AND fly-to. */
  const onResultRow = useCallback(
    (node) => {
      canvasRef.current?.halo(node.id);
      const drawn = canvasRef.current?.focus(node.id);
      // A node outside the current slice (cut by `limit`, or filtered out) cannot be
      // flown to. The Viewer still switches, so it says why the camera did not move
      // rather than looking half-broken.
      viewer.push(drawn === false ? { kind: "node", ...node, notDrawn: true } : { kind: "node", ...node });
    },
    [openNode, viewer.push],
  );

  const onBack = useCallback(() => {
    // Neither halo nor camera. Pure state restore.
    viewer.back();
  }, [viewer.back]);

  const runSearch = useCallback(
    async (query, mode) => {
      setSearchBusy(true);
      const started = performance.now();
      const label =
        mode === "vector" ? "vector" : mode === "cypher" ? "cypher" : "bm25";
      try {
        const result = await api.search({
          query,
          mode,
          limit: mode === "cypher" ? 200 : 40,
        });
        activity.push({
          source: "search",
          text: `${label} “${query}” → ${result.count || 0}`,
          ms: performance.now() - started,
        });

        if (mode === "cypher") {
          viewer.push({
            kind: "results",
            mode: "cypher",
            query,
            cypher: result.query,
            rows: result.rows || [],
            count: result.count || 0,
            truncated: !!result.truncated,
          });
        } else {
          viewer.push({
            kind: "results",
            mode: result.mode || mode,
            query,
            rows: result.hits || [],
            count: result.count || 0,
            truncated: !!result.truncated,
          });
        }
      } catch (err) {
        activity.push({
          source: "search",
          text: `${label} “${query}” failed: ${err.message}`,
          ms: performance.now() - started,
          status: "error",
        });
        viewer.push({
          kind: "results",
          mode,
          query,
          rows: [],
          count: 0,
          error: err.message,
        });
      } finally {
        setSearchBusy(false);
      }
    },
    [viewer.push, activity.push],
  );

  const onChatResults = useCallback((entry) => viewer.push(entry), [viewer.push]);

  const onIngested = useCallback(() => {
    // A write happened. Re-read the counts and the canvas rather than guessing.
    api.stats().then(setStats).catch(() => {});
    // **An ingest is a new graph, so it gets a new layout.**
    //
    // The elements effect preserves positions on every rebuild, which is right for a
    // filter toggle and wrong here: new nodes arrive with no position, the bags are
    // translated onto the ring, and no solver ever runs — so every edge from a child to
    // its bag stretches across the canvas until the user presses Re-run layout.
    //
    // `pendingLayout` is the same one-shot flag that button sets, so the effect takes
    // its `forced` path and solves the NEW elements once they exist. Set before
    // `loadGraph`, because the fetch may resolve before React re-renders.
    canvasRef.current?.layoutOnNextData?.();
    loadGraph(theme.filter.nodeTypes);
  }, [loadGraph, theme.filter.nodeTypes]);

  /**
   * The Utilities modal changed the filter. The server already applied it, so the
   * only work here is to re-read what it now returns: the canvas, the counts, and
   * the badge. Search and chat need no wiring — they go through the same tools.
   */
  const onPlatformsChanged = useCallback(
    (data) => {
      setPlatforms({ active: data.active, total: (data.platforms || []).length });
      loadGraph(theme.filter.nodeTypes);
      api.stats().then(setStats).catch(() => {});
      // A thread on a now-hidden platform must not stay on screen.
      const entry = viewer.current;
      if (entry?.kind === "node" && entry.nodeType === "Thread") {
        const platform = String(entry.id).split(":")[0];
        if (data.active !== null && !data.active.includes(platform)) {
          viewer.reset();
        }
      }
    },
    [loadGraph, theme.filter.nodeTypes, viewer],
  );

  /* ----------------------------------------------------------------- render */

  const context = useMemo(() => {
    const entry = viewer.current;
    if (!entry) return null;
    if (entry.kind === "node") {
      return { nodeType: entry.nodeType, label: entry.label || entry.id };
    }
    return { nodeType: "search results", label: entry.query };
  }, [viewer.current]);

  return (
    <div className="shell">
      <CommandBar
        onSearch={runSearch}
        searchMode={searchMode}
        onSetSearchMode={setSearchMode}
        embedStatus={embedStatus}
        mcpConnected={mcpConnected}
        chatOpen={chatOpen}
        onToggleChat={() => setChatOpen((open) => !open)}
        onOpenModal={setModal}
        storeOk={storeOk}
        stats={stats}
        platformsFiltered={platforms.active !== null}
        activePlatforms={platforms.active?.length ?? platforms.total}
        totalPlatforms={platforms.total}
      />

      <div className="columns">
        {chatOpen && (
          <aside className={`pane chat${chatExpanded ? " expanded" : ""}`}>
            <ChatPanel
              theme={theme}
              context={context}
              onResults={onChatResults}
              onActivity={activity.push}
              expanded={chatExpanded}
              onToggleExpand={() => setChatExpanded((value) => !value)}
            />
          </aside>
        )}

        <main style={{ flex: 1, position: "relative", minWidth: 0, display: "flex" }}>
          <GraphCanvas
            ref={canvasRef}
            data={graph}
            theme={theme}
            onNodeClick={onGraphNodeClick}
            onBackgroundClick={() => canvasRef.current?.clearHalo()}
          />

          {graphError && (
            <div
              className="error"
              style={{ position: "absolute", left: 16, top: 16, maxWidth: 420, zIndex: 5 }}
            >
              {graphError}
            </div>
          )}

          {!graph && !graphError && (
            <div
              className="empty"
              style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center" }}
            >
              Loading the graph…
            </div>
          )}

          <div className="canvas-overlay">
            {graph && (
              <span className="canvas-chip">
                {graph.counts.nodes.toLocaleString()} nodes ·{" "}
                {graph.counts.edges.toLocaleString()} edges
                {graph.truncated ? " · truncated" : ""}
              </span>
            )}
            {searchBusy && <span className="canvas-chip">searching…</span>}
          </div>

          {/* One trace for every surface that touches the store. */}
          <ActivityLog entries={activity.entries} onClear={activity.clear} />
        </main>

        <aside className={`pane viewer${viewerExpanded ? " expanded" : ""}`}>
          <Viewer
            entry={viewer.current}
            theme={theme}
            onOpen={openNode}
            onHalo={(id) => canvasRef.current?.halo(id)}
            onFocus={(id) => canvasRef.current?.focus(id)}
            onBack={onBack}
            canBack={viewer.canBack}
            depth={viewer.depth}
            onOpenModal={setModal}
          />
        </aside>
      </div>

      {modal === "log" && <LogModal onClose={() => setModal(null)} />}
      {modal === "ingest" && (
        <IngestModal onClose={() => setModal(null)} onIngested={onIngested} />
      )}

      {modal === "canvas" && (
        <CanvasModal
          theme={theme}
          onChange={updateTheme}
          onClose={() => setModal(null)}
          /* "Re-run layout" is the ONLY apply path: it saves the draft, fetches the
             slice the new settings describe, then re-solves. Until it is pressed the
             canvas is untouched, exactly like the Gravity modal's sliders. */
          onApply={(next) => {
            updateTheme(next);
            applyCanvas(next);
          }}
          graph={graph}
          platforms={platformRows}
        />
      )}
      {modal === "gravity" && (
        <GravityModal
          theme={theme}
          onChange={updateTheme}
          onClose={() => setModal(null)}
          onRerunLayout={() => canvasRef.current?.rerunLayout()}
        />
      )}
      {modal === "utilities" && (
        <UtilitiesModal onClose={() => setModal(null)} onChanged={onPlatformsChanged} />
      )}
    </div>
  );
}
