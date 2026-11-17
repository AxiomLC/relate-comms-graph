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
/*
 * The ingest flow is THREE steps, not one, and the middle one is the point:
 *
 *   1. **Inspect** — read headers only. No bodies, no writes. Answers "how much is
 *      in here, and spread over which months?"
 *   2. **Decide** — the user sees the counts and picks a window. This is the only
 *      place a big export is allowed to be narrowed, and it happens before anything
 *      is written.
 *   3. **Ingest** — parse with the chosen window and write.
 *
 * Why not just cap during ingest: by the time a cap fires, the file is already
 * parsed and the time is already spent. Inspecting first means the user chooses with
 * real numbers in front of them instead of discovering the size afterwards.
 *
 * **`api.inspect` does not exist yet.** It is a placeholder contract — see the
 * function below. Until the server side lands, `inspect()` returns `null` and the
 * modal falls back to the old one-step behaviour, so nothing is broken by the gap.
 */

/**
 * Pre-inspect the chosen inputs. PLACEHOLDER — the server route is not built.
 *
 * The contract this must satisfy when it lands:
 *
 *   POST /api/ingest/inspect  { paths: [...], email: [...] }
 *   -> {
 *        legs: [{
 *          platform: "whatsapp",
 *          path: "…",
 *          total: 124000,          // rows the file states or a header pass counts
 *          months: {"2026-05": 9000, …},   // for the window slider
 *          estimated: true,        // false when the count is exact
 *        }],
 *        total: 137000,
 *      }
 *
 * Cost per format, so the estimate is honest:
 *   - SMS      free — `<smses count="…">` is in the first 4 KB.
 *   - IMAP     cheap — SEARCH per folder, no FETCH, so no bodies are downloaded.
 *   - Telegram streaming pass over `result.json`; timestamps only.
 *   - PST      folder walk; `number_of_sub_messages` per folder.
 *   - WhatsApp must read the whole `chat.txt` — there is no header count.
 */
async function inspect({ paths, email }) {
  if (!api.inspect) return null;
  try {
    return await api.inspect({ paths, email });
  } catch {
    return null; // a failed inspection must never block an ingest
  }
}

/** The window presets. `null` means "everything". */
const WINDOWS = [
  { key: "3m", label: "3 months", months: 3 },
  { key: "6m", label: "6 months", months: 6 },
  { key: "12m", label: "12 months", months: 12 },
  { key: "all", label: "All", months: null },
];

/** `2026-11-17` -> the ISO bound `months` back, or null for "all". */
function windowStart(months) {
  if (!months) return null;
  const date = new Date();
  date.setMonth(date.getMonth() - months);
  return date.toISOString().slice(0, 10);
}

/** How many messages a window would keep, from the pre-inspect histogram. */
function countInWindow(legs, months) {
  if (!months) return legs.reduce((sum, leg) => sum + (leg.total || 0), 0);
  const cutoff = windowStart(months);
  return legs.reduce((sum, leg) => {
    const months_ = leg.months || {};
    return sum + Object.entries(months_)
      .filter(([month]) => month >= cutoff.slice(0, 7))
      .reduce((inner, [, n]) => inner + n, 0);
  }, 0);
}

export default function IngestModal({ onClose, onIngested }) {
  const [paths, setPaths] = useState("");
  const [email, setEmail] = useState("");
  const [tzOffset, setTzOffset] = useState("");
  const [writeEnabled, setWriteEnabled] = useState(false);
  const [prune, setPrune] = useState(false);
  const [noSpamGroups, setNoSpamGroups] = useState(false);
  const [busy, setBusy] = useState(false);
  const [report, setReport] = useState(null);
  const [error, setError] = useState(null);
  const [tab, setTab] = useState("drop");
  const [window_, setWindow] = useState("all");
  const [inspection, setInspection] = useState(null);
  const dropRef = useRef(null);

  const pathList = () =>
    paths
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean);

  const emailList = () =>
    email
      .split(",")
      .map((value) => value.trim())
      .filter(Boolean);

  /** Step 1. Read headers only, then show the user what they are about to write. */
  const preInspect = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await inspect({ paths: pathList(), email: emailList() });
      setInspection(result);
      if (!result) {
        // No server route yet: say so plainly rather than pretending.
        setError(
          "Pre-inspection is not wired yet, so the size of this export is unknown " +
            "until it is parsed. Ingest will run with the window you chose.",
        );
      }
    } finally {
      setBusy(false);
    }
  };

  const run = async () => {
    setBusy(true);
    setError(null);
    setReport(null);
    try {
      const months = WINDOWS.find((w) => w.key === window_)?.months ?? null;
      const result = await api.ingest({
        which: "real",
        paths: pathList(),
        email: emailList(),
        since: windowStart(months),
        tz_offset_hours: tzOffset === "" ? null : Number(tzOffset),
        exclude_spam_groups: noSpamGroups,
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
          {/* Step 1. Read-only, so it does not need the write toggle. */}
          <button className="ghost" onClick={preInspect} disabled={busy}>
            {busy ? <Loader2 size={13} className="spin" /> : null}
            Inspect first
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

            <h3>Fcbk Mssgr</h3>
            <ul>
              <li>
                Facebook → Settings → <em>Your Facebook information</em> →{" "}
                <em>Download your information</em> → Messages, <strong>JSON or HTML</strong>,
                media low.
              </li>
              <li>Takes hours to a day. It is a lump, not a sync.</li>
            </ul>

            <h3>SMS</h3>
            <ul>
              <li>
                <strong>Not built yet.</strong> The adapter is pending; nothing breaks if
                you have no SMS export.
              </li>
              <li>
                When it lands it will read <em>SMS Backup &amp; Restore</em> XML, which is
                the only route off an Android phone without root.
              </li>
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
            </ul>

            <h3>Outlook</h3>
            <ul>
              <li>
                Outlook is its own platform, not a variant of Email — it gets its own
                colour and cluster.
              </li>
              <li>
                Outlook.com → Settings → General → <em>Privacy and data</em> →{" "}
                <em>Export mailbox</em>. Microsoft assembles it server-side and mails a
                link.
              </li>
              <li>
                Classic Outlook → File → <em>Open &amp; Export</em> →{" "}
                <em>Import/Export</em> → <em>Export to a file</em> →{" "}
                <strong>Outlook Data File (.pst)</strong>, ticking “Include subfolders”.
              </li>
              <li>
                Microsoft killed basic auth for IMAP, so live IMAP is not available — the
                <code>.pst</code> is the only route.
              </li>
            </ul>

            <h3>Timezone</h3>
            <ul>
              <li>
                Telegram, WhatsApp and Fcbk Mssgr export <strong>wall-clock times with no
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
          <h2 className="section">How far back</h2>
          <div className="empty" style={{ paddingTop: 0, paddingBottom: 8 }}>
            Applied to every leg at parse time. A message outside the window is counted
            as skipped, never silently dropped.
          </div>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 10 }}>
            {WINDOWS.map((option) => (
              <button
                key={option.key}
                className={window_ === option.key ? "active" : "ghost"}
                onClick={() => setWindow(option.key)}
              >
                {option.label}
                {inspection ? (
                  <span className="pager-info" style={{ marginLeft: 6 }}>
                    ~{countInWindow(inspection.legs || [], option.months).toLocaleString()}
                  </span>
                ) : null}
              </button>
            ))}
          </div>

          <Check
            label="Skip spam group threads (Facebook Messenger)"
            checked={noSpamGroups}
            onChange={setNoSpamGroups}
            hint="Drops group threads that are mostly link-spam and join-events — the 700-message groups nobody actually talks in. Real group chats are kept."
          />
          <Check
            label="Prune verified spool files older than 3 days"
            checked={prune}
            onChange={setPrune}
            hint="Only files whose key set is confirmed present in the store. Unverified files are never pruned."
          />
        </>
      )}

      {inspection && (
        <>
          <h2 className="section">What is in here</h2>
          <dl className="kv">
            <dt>total</dt>
            <dd>{Number(inspection.total || 0).toLocaleString()} messages</dd>
          </dl>
          {(inspection.legs || []).map((leg, index) => (
            <div key={index} className="result-row" style={{ cursor: "default" }}>
              <div className="result-snippet">
                {leg.platform || "?"} · {leg.path}
              </div>
              <div className="result-meta">
                {Number(leg.total || 0).toLocaleString()} messages
                {leg.estimated ? " · estimated" : " · exact"}
              </div>
            </div>
          ))}
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
