import { useState } from "react";
import {
  Braces,
  Circle,
  Info,
  Palette,
  Search,
  Shapes,
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
  onToggleSearchMode,
  chatOpen,
  onToggleChat,
  onOpenModal,
  storeOk,
  stats,
  platformsFiltered,
  activePlatforms,
  totalPlatforms,
  nodeIcons,
  onToggleNodeIcons,
}) {
  const [query, setQuery] = useState("");

  const submit = () => {
    const text = query.trim();
    if (text) onSearch(text, searchMode);
  };

  return (
    <header className="titlebar">
      <span className="badge" title={storeOk ? "store loaded" : "no store yet"}>
        <span className={`dot${storeOk ? "" : " warn"}`} />
        offline · nothing leaves this machine
      </span>

      <input
        className="searchbox"
        type="search"
        placeholder={
          searchMode === "cypher"
            ? "MATCH (m:Message) RETURN m LIMIT 10"
            : "Search messages…"
        }
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter") submit();
        }}
      />

      <button
        className={searchMode === "cypher" ? "active" : "ghost"}
        onClick={onToggleSearchMode}
        title="Switch between substring search and raw Cypher"
      >
        {searchMode === "cypher" ? <Braces size={13} /> : <Search size={13} />}
        {searchMode === "cypher" ? "Cypher" : "Search"}
      </button>

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
      <button className="ghost" onClick={() => onOpenModal("setup")} title="What this is">
        <Info size={13} /> Setup
      </button>
      {/* The two node looks, side by side. A one-click switch, because comparing
          them is the whole reason both exist. */}
      <button
        className={nodeIcons ? "ghost" : "active"}
        onClick={onToggleNodeIcons}
        title="Circles — shaded platform colour"
      >
        <Circle size={13} />
      </button>
      <button
        className={nodeIcons ? "active" : "ghost"}
        onClick={onToggleNodeIcons}
        title="Icons — the source's own symbol"
      >
        <Shapes size={13} />
      </button>

      <button
        className="ghost"
        onClick={() => onOpenModal("style")}
        title="Force simulation and visuals"
      >
        <Palette size={13} /> Graph Style
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
