import { useCallback, useEffect, useRef, useState } from "react";

/**
 * One activity feed for every surface that touches the store.
 *
 * **Why one feed and not three.** The search bar, the AI chat and (when built) MCP all
 * call the same `tools.REGISTRY`. A user watching the canvas wants one answer to "what
 * is touching my messages right now", not three panels that each tell a third of it.
 *
 * The feed is **in memory only** — it is a viewport trace, not a log file. A reload
 * clears it, which is correct: it describes what just happened, not what happened last
 * week.
 *
 * Entries are capped at `MAX` so a long chat session cannot grow the DOM without bound.
 */
const MAX = 40;

export function useActivity() {
  const [entries, setEntries] = useState([]);
  const idRef = useRef(0);

  const push = useCallback((entry) => {
    idRef.current += 1;
    const next = {
      id: idRef.current,
      at: new Date(),
      ...entry,
    };
    setEntries((prev) => [...prev.slice(-(MAX - 1)), next]);
    return next.id;
  }, []);

  const clear = useCallback(() => setEntries([]), []);

  return { entries, push, clear };
}

/**
 * The viewport trace, bottom-left over the canvas.
 *
 * Deliberately quiet: it is ambient, not a notification. A row appears, ages out of
 * view, and never asks for attention. The one thing it must never do is lie about
 * which surface made a call — hence the `source` tag on every row.
 */
export function ActivityLog({ entries, onClear }) {
  const [open, setOpen] = useState(true);

  if (!entries.length) return null;

  return (
    <div className={`activity${open ? " open" : ""}`}>
      <button
        className="activity-head"
        onClick={() => setOpen((value) => !value)}
        title={open ? "Collapse the activity trace" : "Show the activity trace"}
      >
        <span className="activity-dot" />
        activity
        <span className="activity-count">{entries.length}</span>
        <span className="activity-arrow">{open ? "▾" : "▸"}</span>
      </button>

      {open && (
        <>
          <div className="activity-rows">
            {entries.map((entry) => (
              <div key={entry.id} className={`activity-row ${entry.status || ""}`}>
                <span className={`activity-src ${entry.source}`}>{entry.source}</span>
                <span className="activity-text">{entry.text}</span>
                {entry.ms != null && (
                  <span className="activity-ms">{Math.round(entry.ms)}ms</span>
                )}
              </div>
            ))}
          </div>
          <button className="activity-clear" onClick={onClear}>
            clear
          </button>
        </>
      )}
    </div>
  );
}
