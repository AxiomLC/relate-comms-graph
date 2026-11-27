import { useState } from "react";
import {
  Orbit,
  Palette,
  SlidersHorizontal,
  Sparkles,
  Terminal,
  Upload,
} from "lucide-react";

/**
 * The title bar. Every control is a button here — nothing lives in a settings page
 * (UI-Cytoscape.md §1).
 *
 * The offline badge is not decoration: it is the product claim, and it stays
 * visible at all times.
 */
export default function CommandBar({
  onSearch,
  searchMode,
  onSetSearchMode,
  chatOpen,
  onToggleChat,
  onOpenModal,
  storeOk,
  stats,
  platformsFiltered,
  activePlatforms,
  totalPlatforms,
  embedStatus,
  mcpConnected,
}) {
  const [query, setQuery] = useState("");

  const submit = () => {
    const text = query.trim();
    if (text) onSearch(text, searchMode);
  };

  // Vector search is only meaningful once the store has vectors. `missing > 0` is
  // the honest test: a half-embedded store still answers, just from fewer messages.
  const vectorNeedsEmbeds =
    searchMode === "vector" && embedStatus && embedStatus.missing > 0;

  const MODES = [
    {
      key: "fulltext",
      label: "search",
      hint: "BM25 full-text — ranked, word matching, plus correspondent names",
    },
    {
      key: "vector",
      label: "vector",
      hint: "Semantic — matches meaning, tolerates typos. Needs embeddings.",
    },
    {
      key: "cypher",
      label: "cypher",
      hint: "Raw read-only Cypher against the graph",
    },
  ];

  return (
    <header className="titlebar">
      <span
        className={`badge${mcpConnected ? " mcp" : ""}`}
        title={
          mcpConnected
            ? "An MCP client is reading this store right now"
            : storeOk
              ? "store loaded · nothing leaves this machine"
              : "no store yet"
        }
      >
        {/* Three states, three colours: no store (amber), MCP connected (yellow),
            otherwise green. MCP outranks the store state because it is the one thing
            the user needs to notice. */}
        <span
          className={`dot${mcpConnected ? " mcp" : storeOk ? "" : " warn"}`}
        />
        {mcpConnected ? "MCP being accessed" : "offline - safe"}
      </span>

      <input
        className="searchbox"
        type="search"
        placeholder={
          searchMode === "cypher"
            ? "MATCH (m:Message) RETURN m LIMIT 10"
            : searchMode === "vector"
              ? "Describe what you are looking for…"
              : "Search messages…"
        }
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter") submit();
        }}
      />

      {/* **The mode radios, always visible.** No button to reveal them: they are
          three words, and hiding three words behind a click bought nothing. */}
      <div className="mode-radios" role="radiogroup" aria-label="Search mode">
        {MODES.map((mode) => (
          <label
            key={mode.key}
            className={`mode-radio${mode.key === searchMode ? " on" : ""}`}
            title={mode.hint}
          >
            <input
              type="radio"
              name="search-mode"
              checked={mode.key === searchMode}
              onChange={() => onSetSearchMode(mode.key)}
            />
            {mode.label}
          </label>
        ))}
      </div>

      {vectorNeedsEmbeds && (
        <button
          className="warn-pill"
          onClick={() => onOpenModal("utilities")}
          title={
            `${embedStatus.missing.toLocaleString()} of ` +
            `${embedStatus.total.toLocaleString()} messages have no vector. ` +
            "Open Utilities to run Embed now."
          }
        >
          run embeds
        </button>
      )}

      <span className="spacer" />

      {stats && (
        <span className="badge" style={{ textTransform: "none", letterSpacing: 0 }}>
          {Number(stats.messages || 0).toLocaleString()} msgs ·{" "}
          {Number(stats.threads || 0).toLocaleString()} threads
        </span>
      )}

      <button
        className={chatOpen ? "active" : "ghost"}
        onClick={onToggleChat}
        title="Toggle the AI chat"
      >
        <Sparkles size={13} /> AI
      </button>
      <button className="ghost" onClick={() => onOpenModal("log")} title="Evidence and logs">
        <Terminal size={13} /> Log
      </button>
      <button className="ghost" onClick={() => onOpenModal("ingest")} title="Bring in an export">
        <Upload size={13} /> Ingest
      </button>


      <button
        className="ghost"
        onClick={() => onOpenModal("canvas")}
        title="What is drawn: sort, node count, node types, platform clusters"
      >
        <Palette size={13} /> Canvas
      </button>
      {/* Its own button, not a sub-page of Canvas: this panel is tuned while watching
          the graph, so it docks to the right instead of covering the canvas. */}
      <button
        className="ghost"
        onClick={() => onOpenModal("gravity")}
        title="Gravity — force simulation and label threshold, live"
      >
        <Orbit size={13} /> Gravity
      </button>
      {/* Icon only, by request: the title bar is already dense, and this control
          is used far less often than the ones beside it. */}
      <button
        className={`ghost icon${platformsFiltered ? " active" : ""}`}
        onClick={() => onOpenModal("utilities")}
        title={
          platformsFiltered
            ? `Platforms filtered — ${activePlatforms} of ${totalPlatforms} on`
            : "Utilities — choose which platforms are shown"
        }
        aria-label="Utilities"
      >
        <SlidersHorizontal size={14} />
      </button>
    </header>
  );
}
