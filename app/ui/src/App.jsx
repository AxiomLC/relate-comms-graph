import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api } from "./lib/api.js";
import { loadTheme, saveTheme } from "./config/theme.js";
import { useViewerStack } from "./lib/useViewerStack.js";

import ChatPanel from "./components/ChatPanel.jsx";
import CommandBar from "./components/CommandBar.jsx";
import GraphCanvas from "./components/GraphCanvas.jsx";
import Viewer from "./components/Viewer.jsx";
import CanvasModal from "./components/modals/CanvasModal.jsx";
import IngestModal from "./components/modals/IngestModal.jsx";
import LogModal from "./components/modals/LogModal.jsx";
import SetupModal from "./components/modals/SetupModal.jsx";
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
  const [searchMode, setSearchMode] = useState("substring");
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
    try {
      const data = await api.graph({
        nodeTypes,
        sort: sort || theme.filter.sort || "messages",
        limit: limit || theme.filter.limit || 2000,
      });
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
    Promise.all([api.health(), api.stats(), api.platforms()])
      .then(([health, counts, platformData]) => {
        if (cancelled) return;
        setStoreOk(!!health.store_exists);
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
    return () => {
      cancelled = true;
    };
  }, []);

  // Re-fetch when the node types, sort or limit change. All three are view-only, so
  // this is the only thing they touch.
  const filterKey = [
    theme.filter.nodeTypes.join(","),
    theme.filter.sort,
    theme.filter.limit,
  ].join("|");
  useEffect(() => {
    loadGraph(theme.filter.nodeTypes);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterKey]);

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
      canvasRef.current?.focus(node.id);
      openNode(node);
    },
    [openNode],
  );

  const onBack = useCallback(() => {
    // Neither halo nor camera. Pure state restore.
    viewer.back();
  }, [viewer.back]);

  const runSearch = useCallback(
    async (query, mode) => {
      setSearchBusy(true);
      try {
        const result = await api.search({
          query,
          mode,
          limit: mode === "cypher" ? 200 : 40,
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
            mode: "substring",
            query,
            rows: result.hits || [],
            count: result.count || 0,
            truncated: !!result.truncated,
          });
        }
      } catch (err) {
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
    [viewer.push],
  );

  const onChatResults = useCallback((entry) => viewer.push(entry), [viewer.push]);

  const onIngested = useCallback(() => {
    // A write happened. Re-read the counts and the canvas rather than guessing.
    api.stats().then(setStats).catch(() => {});
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
        onToggleSearchMode={() =>
          setSearchMode((mode) => (mode === "cypher" ? "substring" : "cypher"))
        }
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
          />
        </aside>
      </div>

      {modal === "log" && <LogModal onClose={() => setModal(null)} />}
      {modal === "ingest" && (
        <IngestModal onClose={() => setModal(null)} onIngested={onIngested} />
      )}
      {modal === "setup" && <SetupModal onClose={() => setModal(null)} />}
      {modal === "canvas" && (
        <CanvasModal
          theme={theme}
          onChange={updateTheme}
          onClose={() => setModal(null)}
          onRerunLayout={() => canvasRef.current?.rerunLayout()}
          graph={graph}
          platforms={platformRows}
          onReload={(overrides) =>
            loadGraph(theme.filter.nodeTypes, overrides)
          }
        />
      )}
      {modal === "utilities" && (
        <UtilitiesModal onClose={() => setModal(null)} onChanged={onPlatformsChanged} />
      )}
    </div>
  );
}
