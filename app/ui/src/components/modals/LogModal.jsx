import { api } from "../../lib/api.js";
import { formatBytes, formatCount } from "../../lib/format.js";
import Modal, { useFetch } from "./Modal.jsx";

/**
 * The evidence panel — the hackathon entry (TECHREADME.md §5).
 *
 * "We withheld 98 phone numbers, 21 emails, 17 card numbers" is the claim, and it
 * has to be visible without opening a settings page. This modal is that claim plus
 * the store's own numbers, so a judge can check them against the graph.
 */
export default function LogModal({ onClose }) {
  const health = useFetch(() => api.health(), []);
  const stats = useFetch(() => api.stats(), []);
  const types = useFetch(() => api.types(), []);

  return (
    <Modal title="Evidence" onClose={onClose} wide>
      <h2 className="section">Store</h2>
      {health.loading && <div className="empty">Reading…</div>}
      {health.error && <div className="error">{health.error}</div>}
      {health.data && (
        <dl className="kv">
          <dt>file</dt>
          <dd className="mono">{health.data.store}</dd>
          <dt>size</dt>
          <dd>{formatBytes(health.data.store_bytes)}</dd>
          <dt>exists</dt>
          <dd>{health.data.store_exists ? "yes" : "no — ingest something first"}</dd>
        </dl>
      )}

      <h2 className="section">Counts</h2>
      {stats.loading && <div className="empty">Counting…</div>}
      {stats.error && <div className="error">{stats.error}</div>}
      {stats.data && (
        <>
          <div className="stat-grid">
            <Stat label="messages" value={stats.data.messages} />
            <Stat label="threads" value={stats.data.threads} />
            <Stat label="correspondents" value={stats.data.correspondents} />
            <Stat label="attachments" value={stats.data.attachments} />
            <Stat label="withheld" value={stats.data.withheld_total} />
            <Stat label="non-text" value={stats.data.non_text_total} />
          </div>

          <h2 className="section">Withheld — aliased, not deleted</h2>
          {Object.keys(stats.data.withheld || {}).length === 0 ? (
            <div className="empty">
              Nothing was withheld. Either the scrub gate is off, or this store holds no
              PII in the classes it watches.
            </div>
          ) : (
            <dl className="kv">
              {Object.entries(stats.data.withheld).map(([kind, count]) => (
                <Row key={kind} label={kind.replace(/_/g, " ")} value={formatCount(count)} />
              ))}
            </dl>
          )}
          <div className="empty" style={{ paddingTop: 6 }}>
            Aliases like <code>PHONE-1</code> stay in the message bodies, so the relation
            stays visible while the value does not. The alias → real mapping is memory-only
            and is never written to disk.
          </div>

          <h2 className="section">Platforms</h2>
          <dl className="kv">
            {Object.entries(stats.data.platforms || {}).map(([platform, count]) => (
              <Row key={platform} label={platform} value={formatCount(count)} />
            ))}
          </dl>

          <h2 className="section">Not plain text</h2>
          <dl className="kv">
            {Object.entries(stats.data.non_text || {}).map(([kind, count]) => (
              <Row key={kind} label={kind} value={formatCount(count)} />
            ))}
          </dl>
          <div className="empty" style={{ paddingTop: 6 }}>
            Counted and reported, never dropped. A poll, a sticker or a call is a fact
            about the conversation even when there is no body to read.
          </div>
        </>
      )}

      <h2 className="section">Types in the store</h2>
      {types.error && <div className="error">{types.error}</div>}
      {types.data && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 18 }}>
          <div>
            <h2 className="section" style={{ marginTop: 0 }}>Nodes</h2>
            <dl className="kv">
              {types.data.node_types.map((type) => (
                <Row key={type.type} label={type.type} value={formatCount(type.count)} />
              ))}
            </dl>
          </div>
          <div>
            <h2 className="section" style={{ marginTop: 0 }}>Edges</h2>
            <dl className="kv">
              {types.data.edge_types.map((type) => (
                <Row key={type.type} label={type.type} value={formatCount(type.count)} />
              ))}
            </dl>
          </div>
        </div>
      )}
    </Modal>
  );
}

function Stat({ label, value }) {
  return (
    <div className="stat">
      <div className="stat-value">{formatCount(value)}</div>
      <div className="stat-label">{label}</div>
    </div>
  );
}

function Row({ label, value }) {
  return (
    <>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </>
  );
}
