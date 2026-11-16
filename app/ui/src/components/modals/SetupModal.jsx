import { api } from "../../lib/api.js";
import { formatBytes, formatCount } from "../../lib/format.js";
import Modal, { useFetch } from "./Modal.jsx";

/**
 * Setup: what this is, and what it is not.
 *
 * Deliberately not a settings page — there are no settings. It answers the three
 * questions a judge asks in the first minute: where does the data live, what leaves
 * the machine, and what is the AI.
 */
export default function SetupModal({ onClose }) {
  const health = useFetch(() => api.health(), []);
  const chat = useFetch(() => api.chatHealth(), []);

  return (
    <Modal title="Setup" onClose={onClose} wide>
      <div className="prose">
        <p>
          A local, private window into every conversation you have had, laid out as one
          connected graph you can walk and question. It never leaves this machine.
        </p>

        <h3>Where the data is</h3>
        <dl className="kv">
          <dt>graph</dt>
          <dd className="mono">
            {health.data?.store || "store/graph.rl"}
            {health.data ? ` · ${formatBytes(health.data.store_bytes)}` : ""}
          </dd>
          <dt>exports</dt>
          <dd className="mono">spool/real/&lt;platform&gt;/</dd>
          <dt>owner identity</dt>
          <dd className="mono">store/profile/identity.json</dd>
        </dl>
        <p>
          One <code>.rl</code> file holds every message and every person. It is created the
          first time an ingest runs. Both <code>spool/</code> and <code>store/</code> are
          gitignored.
        </p>

        <h3>What leaves the machine</h3>
        <p>
          Nothing. There is no cloud AI, no telemetry, no deployment. The server binds{" "}
          <code>127.0.0.1</code> and the only network peer is Ollama on the same machine.
        </p>

        <h3>The AI</h3>
        <dl className="kv">
          <dt>host</dt>
          <dd className="mono">{chat.data?.host || "http://127.0.0.1:11434"}</dd>
          <dt>model</dt>
          <dd className="mono">{chat.data?.model || "lfm2.5:8b"}</dd>
          <dt>state</dt>
          <dd>
            {chat.loading
              ? "checking…"
              : chat.data?.ok
                ? chat.data.model_available
                  ? "reachable, model present"
                  : "reachable, model not pulled"
                : "not reachable — the graph still works"}
          </dd>
        </dl>
        <p>
          The chat binds the same functions as the MCP server and the UI buttons. If a tool
          works in the chat box it works everywhere, because it is the same function.
        </p>

        <h3>The canvas</h3>
        <p>
          Threads and correspondents only. Messages are never drawn — 12,499 nodes is not
          drawable, 955 is. Every message is still in the store and still visible to the AI.
          A hidden toggle never narrows what an agent can query.
        </p>

        <h3>What is not built yet</h3>
        <ul>
          <li>
            <strong>Person</strong> — merging one human across platforms. Correspondents are
            facts from the export; a Person is an inference, and it does not exist yet.
          </li>
          <li>
            <strong>Place / Company / Product</strong> — schema only, no extractor.
          </li>
          <li>
            <strong>Semantic search</strong> — Relate has native vector indexes, but no index
            exists in this store yet.
          </li>
        </ul>

        {health.data && (
          <p className="mono" style={{ color: "var(--muted)", marginTop: 18 }}>
            {formatCount(health.data.store_bytes)} bytes ·{" "}
            {health.data.store_exists ? "store present" : "no store"}
          </p>
        )}
      </div>
    </Modal>
  );
}
