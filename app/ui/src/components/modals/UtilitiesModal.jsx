import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2 } from "lucide-react";

import { api } from "../../lib/api.js";
import { formatCount } from "../../lib/format.js";
import { platformColor, platformLabel } from "../../config/nodeTypes.js";
import Modal, { Check } from "./Modal.jsx";

/**
 * Utilities: which platforms are on.
 *
 * A **platform** is the social network (telegram, messenger, email…), not a node
 * type. Unticking `telegram` removes every Telegram thread, correspondent and
 * message — and, because the filter lives in the tool layer, it also narrows the
 * search bar and the AI chat. The graph and the answers cannot disagree, which is
 * the whole point.
 *
 * This deliberately overrides `TECHREADME.md` §5 ("UI state must never narrow an
 * agent's query"). The author's call, 2026-11-16: a hit for a node that is not
 * drawn is worse than a narrowed answer.
 *
 * The list is fetched **unfiltered**, so a hidden platform can always be turned
 * back on.
 */
export default function UtilitiesModal({ onClose, onChanged }) {
  const [rows, setRows] = useState(null);
  const [enabled, setEnabled] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  // --- embeddings ---------------------------------------------------------
  // A separate, opt-in pass. Never part of ingest: measured at 3-42 msg/s
  // depending on body length, so a large store is hours of work.
  const [embed, setEmbed] = useState(null);
  const [embedBusy, setEmbedBusy] = useState(false);
  const [flushBusy, setFlushBusy] = useState(false);
  const [embedLog, setEmbedLog] = useState([]);
  const [embedError, setEmbedError] = useState(null);
  const stopRef = useRef(false);

  const runFlush = async () => {
    setFlushBusy(true);
    setEmbedError(null);
    setEmbedLog((prev) => [...prev, "deleting embeddings…"]);
    try {
      const result = await api.flushEmbeds({ writeEnabled: true });
      setEmbedLog((prev) => [
        ...prev,
        `deleted — ${result.nodes} nodes kept, ${result.edges} edges kept`,
        `reclaimed ${result.reclaimed_mb} MB (${result.mb_before} → ${result.mb_after} MB)`,
      ]);
      // Re-read the status so the button re-arms without a page refresh.
      await refreshEmbed();
    } catch (err) {
      setEmbedError(err.message);
      setEmbedLog((prev) => [...prev, `error: ${err.message}`]);
    } finally {
      setFlushBusy(false);
    }
  };

  const refreshEmbed = useCallback(
    () =>
      api
        .embedStatus()
        .then((data) => {
          setEmbed(data);
          return data;
        })
        .catch((err) => {
          setEmbedError(err.message);
          return null;
        }),
    [],
  );

  useEffect(() => {
    refreshEmbed();
  }, [refreshEmbed]);

  const runEmbed = async () => {
    stopRef.current = false;
    setEmbedBusy(true);
    setEmbedError(null);
    setEmbedLog(["starting…"]);

    let total = 0;
    let skipped = 0;
    try {
      for (;;) {
        if (stopRef.current) {
          setEmbedLog((prev) => [...prev, "stopped by user"]);
          break;
        }
        const result = await api.embed({ limit: 5000, writeEnabled: true });
        total += result.embedded || 0;
        skipped += result.skipped || 0;
        setEmbedLog((prev) => [
          ...prev,
          `batch: ${result.embedded} embedded · ${result.skipped} skipped ` +
            `· ${result.remaining} remaining`,
        ]);
        await refreshEmbed();
        if (result.done || (!result.embedded && !result.skipped)) break;
      }
      setEmbedLog((prev) => [
        ...prev,
        `done — ${total} embedded, ${skipped} skipped this run`,
      ]);
    } catch (err) {
      setEmbedError(err.message);
      setEmbedLog((prev) => [...prev, `error: ${err.message}`]);
    } finally {
      setEmbedBusy(false);
      await refreshEmbed();
    }
  };

  useEffect(() => {
    let cancelled = false;
    api
      .platforms()
      .then((data) => {
        if (cancelled) return;
        setRows(data.platforms || []);
        // `active === null` means unfiltered: everything is on.
        setEnabled(
          data.active === null
            ? (data.platforms || []).map((row) => row.platform)
            : data.active,
        );
      })
      .catch((err) => {
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const apply = async (next) => {
    setEnabled(next);
    setBusy(true);
    setError(null);
    try {
      const data = await api.setPlatforms(next);
      setRows(data.platforms || []);
      onChanged?.(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const toggle = (platform) => {
    const next = enabled.includes(platform)
      ? enabled.filter((value) => value !== platform)
      : [...enabled, platform];
    apply(next);
  };

  const all = (rows || []).map((row) => row.platform);
  const everythingOn = enabled && all.length > 0 && all.every((p) => enabled.includes(p));

  return (
    <Modal
      title="Utilities — platforms"
      onClose={onClose}
      side
      footer={
        <>
          <span className="pager-info">
            {enabled ? `${enabled.length} of ${all.length} on` : "…"}
            {busy && <Loader2 size={12} className="spin" style={{ marginLeft: 6 }} />}
          </span>
          <span className="spacer" />
          <button className="ghost" onClick={() => apply([])} disabled={busy}>
            None
          </button>
          <button className="ghost" onClick={() => apply(null)} disabled={busy}>
            All
          </button>
          <button onClick={onClose}>Done</button>
        </>
      }
    >
      <div className="empty" style={{ paddingTop: 0 }}>
        Unticking a platform removes its threads, correspondents and messages from
        the graph — and from search and the AI chat. The store is untouched; this is
        a view, and it is reversible.
      </div>

      {error && <div className="error">{error}</div>}
      {!rows && !error && <div className="empty">Reading the store…</div>}

      {(rows || []).map((row) => (
        <label key={row.platform} className="check" style={{ marginBottom: 8 }}>
          <input
            type="checkbox"
            checked={!!enabled?.includes(row.platform)}
            onChange={() => toggle(row.platform)}
            disabled={busy || !row.built}
          />
          <span
            className="legend-swatch"
            style={{
              background: row.built ? platformColor(row.platform) : "transparent",
              border: row.built ? "none" : "1px dashed var(--muted)",
              marginRight: 2,
            }}
          />
          <span style={{ minWidth: 90 }}>{platformLabel(row.platform)}</span>
          <span className="pager-info">
            {row.built ? `${formatCount(row.count)} messages` : "not built yet"}
          </span>
        </label>
      ))}

      {rows?.length === 0 && (
        <div className="empty">No messages in the store yet — ingest something first.</div>
      )}

      <div style={{ marginTop: 14 }}>
        <Check
          label="Everything on (no filter)"
          checked={!!everythingOn}
          onChange={() => apply(everythingOn ? [] : null)}
          hint="Clearing the filter is not the same as ticking every box: a platform added later is included automatically."
        />
      </div>

      <hr style={{ margin: "18px 0 14px", border: 0, borderTop: "1px solid var(--line)" }} />

      <div className="pane-title" style={{ marginBottom: 8 }}>
        <strong>Embeddings Ingest</strong>
      </div>

      <div className="pager-info" style={{ marginBottom: 4 }}>
        running: {embed?.model || "embeddinggemma"}
      </div>
      <div className="pager-info" style={{ marginBottom: 4 }}>
        Expect ~60s for 2,000 short messages | 5-15 min for a real 4,000-message
        graph
      </div>
      <div className="pager-info" style={{ marginBottom: 10 }}>
        {embed
          ? `${formatCount(embed.embedded)} embedded · ` +
            `${formatCount(embed.skipped)} screened · ` +
            `vector store ${embed.store_mb} MB`
          : "reading…"}
      </div>

      {embedError && <div className="error">{embedError}</div>}

      <div style={{ display: "flex", gap: 6, marginBottom: 8 }}>
        <button onClick={runEmbed} disabled={embedBusy || flushBusy}>
          {embedBusy ? (
            <>
              <Loader2 size={12} className="spin" /> Embedding…
            </>
          ) : (
            "Embed now"
          )}
        </button>
        {embedBusy && (
          <button className="ghost" onClick={() => (stopRef.current = true)}>
            Stop
          </button>
        )}
        <button
          className="ghost"
          onClick={runFlush}
          disabled={embedBusy || flushBusy || !embed?.embedded}
          title={
            "Delete every vector and reclaim the disk. The graph itself is kept — " +
            "only the embeddings go."
          }
        >
          {flushBusy ? (
            <>
              <Loader2 size={12} className="spin" /> Deleting…
            </>
          ) : (
            "Delete embeds"
          )}
        </button>
      </div>

      {embedLog.length > 0 && (
        <pre className="embed-log">{embedLog.slice(-8).join("\n")}</pre>
      )}
    </Modal>
  );
}
