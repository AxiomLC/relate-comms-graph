import { useRef, useState } from "react";
import { Loader2, Upload } from "lucide-react";

import { api } from "../../lib/api.js";
import Modal, { Check, TextField } from "./Modal.jsx";

/**
 * Ingest: one button, one modal (TECHREADME.md §6).
 *
 * The modal is the product's honesty surface. It states what each platform actually
 * demands instead of pretending a magic import exists, and it is the same text as
 * `archive_docs/MssgDownloadInstructs.md` so the two cannot drift. **The modal is now the
 * only copy in the live tree** — if you edit one, edit the other.
 *
 * Two rules the UI must not break:
 *
 *  - **Stage copies, never moves.** A failed parse must not relocate the user's only
 *    download. The server does the copying; the browser only sends paths.
 *  - **Write is a toggle.** Ingest is a WRITE tool, so `write_enabled` is sent
 *    explicitly with every request and is never remembered server-side.
 */
export default function IngestModal({ onClose, onIngested }) {
  const [paths, setPaths] = useState("");
  const [email, setEmail] = useState("");
  const [tzOffset, setTzOffset] = useState("");
  const [writeEnabled, setWriteEnabled] = useState(false);
  const [prune, setPrune] = useState(false);
  const [busy, setBusy] = useState(false);
  const [report, setReport] = useState(null);
  const [error, setError] = useState(null);
  const [tab, setTab] = useState("drop");
  const dropRef = useRef(null);

  const run = async () => {
    setBusy(true);
    setError(null);
    setReport(null);
    try {
      const result = await api.ingest({
        source: "real",
        paths: paths
          .split(/\r?\n/)
          .map((line) => line.trim())
          .filter(Boolean),
        email: email
          .split(",")
          .map((value) => value.trim())
          .filter(Boolean),
        tz_offset_hours: tzOffset === "" ? null : Number(tzOffset),
        prune,
        write_enabled: writeEnabled,
      });
      setReport(result);
      onIngested?.(result);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const onDrop = (event) => {
    event.preventDefault();
    dropRef.current?.classList.remove("over");
    // A browser cannot hand us a filesystem path, and the server must not scan
    // ~/Downloads. So the drop zone explains the one thing that works: paste the
    // path. This is a deliberate limitation, not an oversight.
    setTab("paths");
  };

  return (
    <Modal
      title="Ingest"
      onClose={onClose}
      wide
      footer={
        <>
          <Check
            label="Allow writes"
            checked={writeEnabled}
            onChange={setWriteEnabled}
            hint="Ingest is a WRITE tool. The toggle is per-surface and is never remembered."
          />
          <span className="spacer" />
          <button className="ghost" onClick={onClose}>
            Close
          </button>
          <button onClick={run} disabled={busy || !writeEnabled}>
            {busy ? <Loader2 size={13} className="spin" /> : <Upload size={13} />}
            Ingest
          </button>
        </>
      }
    >
      <div className="tabs">
        <button className={`tab${tab === "drop" ? " active" : ""}`} onClick={() => setTab("drop")}>
          What to download
        </button>
        <button className={`tab${tab === "paths" ? " active" : ""}`} onClick={() => setTab("paths")}>
          Paste a path
        </button>
      </div>

      {tab === "drop" && (
        <>
          <div
            className="dropzone"
            ref={dropRef}
            onDragOver={(event) => {
              event.preventDefault();
              dropRef.current?.classList.add("over");
            }}
            onDragLeave={() => dropRef.current?.classList.remove("over")}
            onDrop={onDrop}
          >
            <strong>Drop your export onto this area.</strong>
            <br />
            Everything stays on this machine. Nothing is uploaded.
            <br />
            <br />
            A browser cannot read a file path, so dropping switches to the path tab —
            paste where the file actually is and the server copies it into the spool.
          </div>

          <div className="prose">
            <h3>Telegram</h3>
            <ul>
              <li>
                Desktop → Settings → Advanced → <em>Export Telegram data</em> → tick{" "}
                <strong>Personal chats</strong> and <strong>JSON</strong>, media off.
              </li>
              <li>
                One bulk export covers every chat. A single-chat export is a
                message-for-message subset of it, so there is no reason to click through
                chats.
              </li>
            </ul>

            <h3>WhatsApp</h3>
            <ul>
              <li>
                WhatsApp Web/Desktop → open a chat → ⋮ → <em>Export chat</em> →{" "}
                <strong>without media</strong>.
              </li>
              <li>
                Per-chat only. The official account-info export contains no messages.
              </li>
              <li>
                <em>Advanced — all chats with a date range:</em> copy{" "}
                <code>msgstore.db.crypt15</code> off the phone plus your 64-digit backup
                key, then run <code>wtsexporter --date "YYYY-MM-DD - YYYY-MM-DD"</code>.
              </li>
            </ul>

            <h3>Messenger</h3>
            <ul>
              <li>
                Facebook → Settings → <em>Your Facebook information</em> →{" "}
                <em>Download your information</em> → Messages, <strong>JSON or HTML</strong>,
                media low.
              </li>
              <li>Takes hours to a day. It is a lump, not a sync.</li>
            </ul>

            <h3>LinkedIn</h3>
            <ul>
              <li>
                Settings → <em>Data privacy</em> → <em>Get a copy of your data</em> →{" "}
                <strong>Want something in particular?</strong> → tick{" "}
                <strong>Messages</strong>.
              </li>
              <li>
                The <em>Basic</em> export already contains <code>messages.csv</code> — the
                larger archive and its 24-hour wait are not needed.
              </li>
            </ul>

            <h3>Email</h3>
            <ul>
              <li>
                Gmail and Hostinger are read <strong>live over IMAP</strong> — there is no
                file to drop. Put <code>GOOGLE_EMAIL</code>/<code>GOOGLE_APP_PASSWORD</code>{" "}
                or <code>HOSTINGER_EMAIL</code>/<code>HOSTINGER_PASSWORD</code> in{" "}
                <code>.env</code>, then name the mailbox in the field below.
              </li>
              <li>
                Outlook is a <code>.pst</code> export — Microsoft killed basic auth, so live
                IMAP is not available.
              </li>
            </ul>

            <h3>Timezone</h3>
            <ul>
              <li>
                Telegram, WhatsApp and Messenger export <strong>wall-clock times with no
                offset</strong>. Declare the offset the export was written in, or the
                timeline lies.
              </li>
              <li>
                It is remembered per platform, so a second run can omit it. Changing it on a
                populated store is refused — it would duplicate every row instead of
                replacing it.
              </li>
            </ul>
          </div>
        </>
      )}

      {tab === "paths" && (
        <>
          <TextField
            label="Export path(s), one per line"
            value={paths}
            onChange={setPaths}
            placeholder="C:/Users/me/Downloads/Telegram Desktop/ChatExport_2026-11-14"
            hint="Files are COPIED into spool/real/<platform>/, chosen by content, never by filename."
          />
          <TextField
            label="Mailboxes (comma-separated)"
            value={email}
            onChange={setEmail}
            placeholder="hostinger, gmail"
            hint="Live IMAP. Credentials come from .env; a missing key names the key, never a value."
          />
          <TextField
            label="tz offset (hours)"
            value={tzOffset}
            onChange={setTzOffset}
            placeholder="leave blank to reuse the recorded offset"
            hint="e.g. -5 for US Eastern. Only Telegram, WhatsApp and Messenger accept it."
          />
          <Check
            label="Prune verified spool files older than 3 days"
            checked={prune}
            onChange={setPrune}
            hint="Only files whose key set is confirmed present in the store. Unverified files are never pruned."
          />
        </>
      )}

      {error && <div className="error" style={{ marginTop: 12 }}>{error}</div>}

      {report && (
        <>
          <h2 className="section">Report</h2>
          <dl className="kv">
            <dt>store</dt>
            <dd className="mono">{report.store}</dd>
            <dt>elapsed</dt>
            <dd>{Number(report.elapsed_s || 0).toFixed(2)}s</dd>
            <dt>workers</dt>
            <dd>{report.workers}</dd>
            {report.owner_note && (
              <>
                <dt>owner</dt>
                <dd>{report.owner_note}</dd>
              </>
            )}
          </dl>

          {(report.batches || []).map((batch, index) => (
            <div key={index} className="result-row" style={{ cursor: "default" }}>
              <div className="result-snippet">
                {batch.platform || "?"} · {batch.path}
              </div>
              <div className="result-meta">
                {batch.messages} msgs · {batch.attachments} attachments
                {batch.verified ? " · verified" : ""}
                {batch.pruned ? " · pruned" : ""}
                {batch.error ? ` · ${batch.error}` : ""}
              </div>
              {(batch.warnings || []).map((warning, warningIndex) => (
                <div key={warningIndex} className="result-meta" style={{ color: "var(--orange-text)" }}>
                  {warning}
                </div>
              ))}
            </div>
          ))}

          {(report.unrecognised || []).length > 0 && (
            <>
              <h2 className="section">Not recognised — kept, not guessed</h2>
              {report.unrecognised.map((path, index) => (
                <div key={index} className="mono" style={{ color: "var(--orange-text)" }}>
                  {path}
                </div>
              ))}
            </>
          )}
        </>
      )}
    </Modal>
  );
}
