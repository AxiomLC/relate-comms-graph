import { useCallback, useEffect, useMemo, useState } from "react";

/**
 * The Viewer's state timeline, ported from `frontal-lobe/ui/src/components/Viewer.jsx`
 * (UI-Cytoscape.md §9).
 *
 * One `{stack, idx}` object so push / dedupe / truncate / cap are atomic — a
 * separate `stack` and `idx` pair can disagree for a frame, and that frame is
 * exactly when a click lands.
 *
 * Rules, all of them load-bearing:
 *
 *  - consecutive duplicate **node** clicks are deduped (clicking the same thread
 *    twice must not grow the stack)
 *  - a re-run of the same search is a **new** state, not a dedupe — the user asked
 *    again, and the answer may differ
 *  - a new action after Back **truncates the forward path**
 *  - the stack is capped at 50
 *  - it is memory-only: a refresh starts clean
 */

const CAP = 50;
const STORAGE_KEY = "relate.viewer.stack";

export const EMPTY_VIEWER = { stack: [], idx: -1 };

/**
 * Rehydrate from `localStorage`.
 *
 * Only `node` entries survive. A `results` entry is a snapshot of a query that has
 * already run — restoring it would show rows that may no longer match the store,
 * which is worse than an empty Viewer. The stack is capped on read too, because a
 * hand-edited or older value must not be trusted.
 */
function loadState() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return EMPTY_VIEWER;
    const saved = JSON.parse(raw);
    const stack = (saved.stack || []).filter((entry) => entry?.kind === "node");
    if (!stack.length) return EMPTY_VIEWER;
    const trimmed = stack.slice(-CAP);
    return { stack: trimmed, idx: trimmed.length - 1 };
  } catch {
    return EMPTY_VIEWER;
  }
}

export function useViewerStack() {
  const [state, setState] = useState(loadState);

  // Persist on every change. `results` entries are dropped on the way in, so what
  // is written is always restorable.
  useEffect(() => {
    try {
      const stack = state.stack.filter((entry) => entry?.kind === "node");
      if (!stack.length) {
        localStorage.removeItem(STORAGE_KEY);
        return;
      }
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ stack }));
    } catch {
      /* quota or private mode — the stack just does not persist */
    }
  }, [state]);

  /**
   * Fold one pushed entry into the history.
   *
   * The dedupe compares against the entry at `idx` — the one on screen — not
   * against the last entry in the stack. After Back, the entry at `idx` is an
   * older one, and clicking the node you are looking at must still be a no-op.
   */
  const push = useCallback((entry) => {
    if (!entry?.kind) return;
    setState((prev) => {
      const current = prev.idx >= 0 ? prev.stack[prev.idx] : null;

      // Consecutive duplicate node click: no-op. Searches always push.
      if (
        current &&
        entry.kind === "node" &&
        current.kind === "node" &&
        current.nodeType === entry.nodeType &&
        current.id === entry.id
      ) {
        return prev;
      }

      const kept = prev.stack.slice(0, prev.idx + 1);
      kept.push(entry);
      const trimmed = kept.length > CAP ? kept.slice(kept.length - CAP) : kept;
      return { stack: trimmed, idx: trimmed.length - 1 };
    });
  }, []);

  const back = useCallback(() => {
    setState((prev) => (prev.idx > 0 ? { ...prev, idx: prev.idx - 1 } : prev));
  }, []);

  const forward = useCallback(() => {
    setState((prev) =>
      prev.idx < prev.stack.length - 1 ? { ...prev, idx: prev.idx + 1 } : prev,
    );
  }, []);

  const reset = useCallback(() => {
    setState(EMPTY_VIEWER);
    try {
      localStorage.removeItem(STORAGE_KEY);
    } catch {
      /* ignore */
    }
  }, []);

  const current = state.idx >= 0 ? state.stack[state.idx] : null;

  return useMemo(
    () => ({
      current,
      canBack: state.idx > 0,
      canForward: state.idx >= 0 && state.idx < state.stack.length - 1,
      depth: state.idx + 1,
      length: state.stack.length,
      push,
      back,
      forward,
      reset,
    }),
    [current, state, push, back, forward, reset],
  );
}
