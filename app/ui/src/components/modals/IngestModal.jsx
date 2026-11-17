import { useEffect, useRef, useState } from "react";
import { FileUp, Loader2, Upload } from "lucide-react";

import { api } from "../../lib/api.js";
import { formatBytes } from "../../lib/format.js";
import Modal, { Check, TextField } from "./Modal.jsx";

/**
 * Ingest: one modal, one tab, top to bottom.
 *
 *   ┌ drop box ────────────────────────────────────────────────┐
 *   │ pick one or many files, or paste a path                  │
 *   ├ IMAP ────────────────────────────────────────────────────┤
 *   │ email / password / host / port, saved to ./.env          │
 *   ├ ── separator ────────────────────────────────────────────┤
 *   │ window · silent groups · spam threads · prune            │
 *   └ [ Close ]                        [ Preview ]  [ Ingest ] ┘
 *
 * Three rules the UI must not break:
 *
 *  - **Stage copies, never moves.** A failed parse must not relocate the user's only
 *    download. The server does the copying; the browser only sends contents or paths.
 *  - **Write is a toggle.** Ingest is a WRITE tool, so `write_enabled` is sent
 *    explicitly with every request and is never remembered server-side.
 *  - **Alerts appear only after Ingest is pressed.** Before that the modal is silent
 *    except for the preview counts.
 *
 * The drop box is a real file picker: the browser can hand over file *contents* but
 * never a filesystem path, so `POST /api/ingest/upload` copies them into the spool.
 * A pasted path is the escape hatch for a folder export (Telegram writes a directory,
 * not a file) and for a file too large to upload.
 */

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

/** Which IMAP host a mail domain implies. Mirrors the server's table. */
const HOSTS = {
  "gmail.com": "imap.gmail.com",
  "googlemail.com": "imap.gmail.com",
  "outlook.com": "outlook.office365.com",
  "hotmail.com": "outlook.office365.com",
  "live.com": "outlook.office365.com",
  "yahoo.com": "imap.mail.yahoo.com",
  "icloud.com": "imap.mail.me.com",
  "me.com": "imap.mail.me.com",
  "zoho.com": "imap.zoho.com",
  "fastmail.com": "imap.fastmail.com",
  "gmx.com": "imap.gmx.com",
  "gmx.net": "imap.gmx.com",
  "yandex.com": "imap.yandex.com",
  "aol.com": "imap.aol.com",
  "hostinger.com": "imap.hostinger.com",
};

function hostFor(email) {
  const domain = (email.split("@")[1] || "").toLowerCase();
  if (!domain) return "";
  return HOSTS[domain] || `mail.${domain}`;
}

/** A provider name for the request, from the address. `custom` for anything else. */
function providerFor(email) {
  const domain = (email.split("@")[1] || "").toLowerCase();
  if (!domain) return "";
  const known = {
    "gmail.com": "gmail", "googlemail.com": "gmail",
    "outlook.com": "outlook", "hotmail.com": "outlook", "live.com": "outlook",
    "yahoo.com": "yahoo", "icloud.com": "icloud", "me.com": "icloud",
    "zoho.com": "zoho", "fastmail.com": "fastmail",
    "gmx.com": "gmx", "gmx.net": "gmx", "yandex.com": "yandex",
    "aol.com": "aol", "hostinger.com": "hostinger",
  };
  return known[domain] || "custom";
}

export default function IngestModal({ onClose, onIngested }) {
  // --- drop box ------------------------------------------------------------
  const [paths, setPaths] = useState("");
  const [picked, setPicked] = useState([]);
  const [staged, setStaged] = useState([]);
  const dropRef = useRef(null);
  const fileRef = useRef(null);
  const folderRef = useRef(null);

  // --- IMAP ----------------------------------------------------------------
  const [imapEmail, setImapEmail] = useState("");
  const [imapPassword, setImapPassword] = useState("");
  const [imapHost, setImapHost] = useState("");
  const [imapPort, setImapPort] = useState("993");
  const [envStatus, setEnvStatus] = useState(null);
  const [envSaved, setEnvSaved] = useState(null);

  // --- settings ------------------------------------------------------------
  const [tzOffset, setTzOffset] = useState("");
  const [window_, setWindow] = useState("all");
  const [silentGroups, setSilentGroups] = useState(true);
  const [silentPlatforms, setSilentPlatforms] = useState({
    telegram: true, whatsapp: true, messenger: true,
  });
  const [spamThreads, setSpamThreads] = useState(true);
  const [spamPlatforms, setSpamPlatforms] = useState({ email: true, outlook: true });
  const [spamGroups, setSpamGroups] = useState(false);
  // "off" | "0" | "1" | "2" — the prune policy. A string so the buttons can be a
  // plain list; `Number()` only happens on the way out.
  const [pruneKeep, setPruneKeep] = useState("off");


  // --- run state -----------------------------------------------------------
  const [writeEnabled, setWriteEnabled] = useState(false);
  const [busy, setBusy] = useState(false);
  const [report, setReport] = useState(null);
  const [error, setError] = useState(null);
  const [preview, setPreview] = useState(null);
  const [log, setLog] = useState([]);
  const [halted, setHalted] = useState(null);

  // Double confirm: `wipeStep` 0 = idle, 1 = "are you sure", 2 = "type nothing, press
  // the second button". Two deliberate clicks, because there is no undo.
  const [wipeStep, setWipeStep] = useState(0);
  const [wipeResult, setWipeResult] = useState(null);

  useEffect(() => {
    api.envStatus().then(setEnvStatus).catch(() => setEnvStatus(null));
    refreshPreview();
  }, []);

  /** Newest first, so the last thing that happened is the first thing read. */
  const note = (level, text) =>
    setLog((prev) => [{ level, text, at: new Date() }, ...prev]);

  const pathList = () =>
    paths.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);

  const ticked = (map) => Object.entries(map).filter(([, on]) => on).map(([key]) => key);

  /** Copy picked files into the spool. Nothing is parsed yet. */
  const stageFiles = async (files) => {
    // A cancelled dialog fires `change` with an empty list. Sending it would hit the
    // route's required `files` field and surface a validation error for doing nothing.
    if (!files.length) return;
    setBusy(true);
    setError(null);
    try {
      const result = await api.upload(files, { writeEnabled });
      setStaged((prev) => [...prev, ...(result.staged || [])]);
      setPicked([]);
      if (fileRef.current) fileRef.current.value = "";
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const onDrop = (event) => {
    event.preventDefault();
    dropRef.current?.classList.remove("over");
    stageFiles(Array.from(event.dataTransfer?.files || []));
  };

  /**
   * Read-only pass: what is in the spool, and what has already been ingested.
   *
   * Runs on open and after every stage, so the log can say "already ingested" before
   * the user commits to a parse. Nothing is written.
   */
  const refreshPreview = async () => {
    try {
      const result = await api.preview("real");
      setPreview(result);
      return result;
    } catch {
      setPreview(null);
      return null;
    }
  };

  /** Write IMAP credentials to `./.env`. Its own button, never a side effect. */
  const saveCredentials = async () => {
    setBusy(true);
    setError(null);
    setEnvSaved(null);
    try {
      const result = await api.saveEnv({
        email: imapEmail.trim(),
        password: imapPassword,
        host: imapHost.trim() || null,
        port: Number(imapPort) || 993,
        write_enabled: writeEnabled,
      });
      setEnvSaved(result);
      setImapPassword("");
      api.envStatus().then(setEnvStatus).catch(() => {});
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  /**
   * One ingest run.
   *
   * `skip` is a set of platform names to leave out — that is how "exclude this leg and
   * continue" is expressed. The run is **restarted** rather than resumed: every write
   * is a MERGE on a stable key, so a second run over the same spool adds nothing and
   * costs only the parse. Resuming mid-pipeline would mean holding a half-written
   * batch across a user decision, which is a far worse thing to get wrong.
   */
  const run = async ({ skip = new Set() } = {}) => {
    setBusy(true);
    setError(null);
    setReport(null);
    setHalted(null);
    note("info", "Ingesting…");
    try {
      const months = WINDOWS.find((w) => w.key === window_)?.months ?? null;
      const result = await api.ingest({
        which: "real",
        paths: pathList(),
        email: imapEmail.trim() && !skip.has("email") ? [providerFor(imapEmail)] : [],
        since: windowStart(months),
        tz_offset_hours: tzOffset === "" ? null : Number(tzOffset),
        exclude_silent_groups: silentGroups,
        silent_group_platforms: silentGroups ? ticked(silentPlatforms) : null,
        exclude_spam_threads: spamThreads,
        spam_thread_platforms: spamThreads ? ticked(spamPlatforms) : null,
        exclude_spam_groups: spamGroups,
        prune: pruneKeep !== "off",
        prune_keep: pruneKeep === "off" ? null : Number(pruneKeep),
        write_enabled: writeEnabled,
      });

      // A leg that failed is the one thing worth stopping on: the rest landed, and the
      // user has to decide whether to retry without it.
      const failed = (result.batches || []).filter(
        (batch) => batch.error && !skip.has(batch.platform),
      );
      for (const batch of result.batches || []) {
        if (batch.error) {
          note("warn", `${batch.platform}: ${batch.error}`);
        } else {
          note(
            "ok",
            `${batch.platform}: ${batch.messages} msgs · ${batch.attachments} attachments` +
              (batch.verified ? " · verified" : " · NOT verified"),
          );
        }
      }

      setReport(result);
      onIngested?.(result);
      refreshPreview();

      if (failed.length) {
        setHalted({ failed, skip });
        note("warn", `${failed.length} leg(s) failed — choose to exclude and continue, or cancel`);
      } else {
        note("ok", "done");
      }
    } catch (err) {
      setError(err.message);
      note("warn", err.message);
    } finally {
      setBusy(false);
    }
  };

  /** Wipe the graph. Two clicks, and the manifest always goes with it. */
  const truncate = async () => {
    setBusy(true);
    setError(null);
    setWipeResult(null);
    try {
      const result = await api.truncate({
        write_enabled: writeEnabled,
        confirm: true,
      });
      setWipeResult(result);
      setWipeStep(0);
      setReport(null);
      note("warn", `store truncated — ${result.removed.length} file(s) removed`);
      refreshPreview();
      onIngested?.({});
    } catch (err) {
      setError(err.message);
      note("warn", err.message);
    } finally {
      setBusy(false);
    }
  };

  /** Exclude the failed legs and run again. Nothing is rolled back — MERGE is idempotent. */
  const continueWithout = () => {
    const next = new Set(halted?.skip || []);
    for (const batch of halted?.failed || []) next.add(batch.platform);
    note("info", `continuing without ${[...next].join(", ")}`);
    run({ skip: next });
  };

  /**
   * Cancel. The store is not rolled back, and it does not need to be: every write is a
   * MERGE on a stable key, so re-running the same export later adds nothing. What was
   * written stays written and is correct.
   */
  const cancelRun = () => {
    note("warn", "cancelled — anything already written stays, and re-running is safe");
    setHalted(null);
  };

  const stagedCount = staged.length;
  const hasInput = stagedCount > 0 || pathList().length > 0 || imapEmail.trim() !== "";

  return (
    <Modal
      title="Ingest"
      onClose={onClose}
      wide
      footer={
        <>
          {/* The one gate before the button. Ingest writes to the store, so it is
              armed explicitly and never remembered — a remembered toggle is a toggle
              nobody remembers turning on. */}
          <Check
            label="Ingest Ready"
            checked={writeEnabled}
            onChange={setWriteEnabled}
            hint="Arms the Ingest button. Ingest writes to the store, so it is a deliberate second step and is never remembered."
          />
          <span className="spacer" />
          <button className="ghost" onClick={onClose}>
            Close
          </button>
          <button onClick={run} disabled={busy || !writeEnabled || !hasInput}>
            {busy ? <Loader2 size={13} className="spin" /> : <Upload size={13} />}
            Ingest
          </button>
        </>
      }
    >
      {/* ------------------------------------------------------------ truncate */}
      {/* At the top, because it is the one control that changes what the whole app is
          looking at. Two clicks, no undo. */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          padding: "8px 10px",
          marginBottom: 14,
          border: "1px solid var(--hairline)",
          borderRadius: "var(--radius-sm)",
        }}
      >
        {wipeStep === 0 && (
          <>
            <span className="pager-info" style={{ flex: 1 }}>
              {wipeResult
                ? `store truncated · ${wipeResult.removed.length} file(s) removed`
                : "Wipe the graph and start again. The dedup record goes with it."}
            </span>
            <button className="ghost" onClick={() => setWipeStep(1)} disabled={busy}>
              Truncate Relate DB
            </button>
          </>
        )}
        {wipeStep === 1 && (
          <>
            <span className="pager-info" style={{ flex: 1, color: "var(--orange-text)" }}>
              This deletes <code>store/graph.rl</code> and the list of files already
              ingested. Your exports in <code>spool/real/</code> are kept. There is no
              undo.
            </span>
            <button className="ghost" onClick={() => setWipeStep(0)} disabled={busy}>
              Keep it
            </button>
            <button onClick={() => setWipeStep(2)} disabled={busy}>
              Yes, delete
            </button>
          </>
        )}
        {wipeStep === 2 && (
          <>
            <span className="pager-info" style={{ flex: 1, color: "var(--orange-text)" }}>
              Last chance. Pressing this empties the graph.
            </span>
            <button className="ghost" onClick={() => setWipeStep(0)} disabled={busy}>
              Cancel
            </button>
            <button onClick={truncate} disabled={busy || !writeEnabled}>
              {busy ? <Loader2 size={13} className="spin" /> : null}
              Delete everything
            </button>
          </>
        )}
      </div>

      {/* ---------------------------------------------------------- drop box */}
      {/* The inputs are SIBLINGS of the dropzone, not children. Nested, a click on the
          zone opens the dialog, the input's own click bubbles back to the zone, and the
          dialog opens again — which is how a selection could arrive empty. */}
      <input
        ref={fileRef}
        type="file"
        multiple
        style={{ display: "none" }}
        onChange={(event) => {
          const files = Array.from(event.target.files || []);
          // Clear first, so picking the same file twice still fires `change`.
          event.target.value = "";
          stageFiles(files);
        }}
      />
      {/* A folder pick, for Telegram (a directory holding `result.json`) and for a
          LinkedIn or Messenger archive that arrives unzipped. `webkitdirectory` is
          non-standard but is the only way a browser can hand over a directory. */}
      <input
        ref={folderRef}
        type="file"
        multiple
        webkitdirectory=""
        directory=""
        style={{ display: "none" }}
        onChange={(event) => {
          const files = Array.from(event.target.files || []);
          event.target.value = "";
          stageFiles(files);
        }}
      />
      <div
        className="dropzone"
        ref={dropRef}
        onClick={() => fileRef.current?.click()}
        onDragOver={(event) => {
          event.preventDefault();
          dropRef.current?.classList.add("over");
        }}
        onDragLeave={() => dropRef.current?.classList.remove("over")}
        onDrop={onDrop}
        style={{ cursor: "pointer" }}
      >
        <FileUp size={18} style={{ marginBottom: 6 }} />
        <br />
        <strong>Drop one or many files here, or click to choose.</strong>
        <br />
        Everything stays on this machine. Nothing is uploaded anywhere.
      </div>
      <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
        <button className="ghost" onClick={() => fileRef.current?.click()}>
          Choose files
        </button>
        <button className="ghost" onClick={() => folderRef.current?.click()}>
          Choose a folder
        </button>
        <span className="pager-info" style={{ alignSelf: "center" }}>
          a folder is for Telegram (a directory holding result.json) or an unzipped archive
        </span>
      </div>

      {stagedCount > 0 && (
        <div style={{ marginTop: 8 }}>
          {staged.map((item, index) => (
            <div key={index} className="result-row" style={{ cursor: "default" }}>
              <div className="result-snippet">{item.name}</div>
              <div className="result-meta">
                {item.platform}
                {item.recognised ? "" : " · not recognised, kept"}
              </div>
            </div>
          ))}
        </div>
      )}

      <TextField
        label="…or paste a path"
        value={paths}
        onChange={setPaths}
        placeholder="C:/Users/me/Downloads/Telegram Desktop/ChatExport_2026-11-14"
        hint="One per line. For a folder export (Telegram writes a directory) or a file too large to upload. Files are COPIED into spool/real/<platform>/, chosen by content, never by filename."
      />

      {/* What is already in the spool. Read-only, and the only place a duplicate is
          caught before the parse rather than after it. */}
      {preview && preview.legs.length > 0 && (
        <>
          <h2 className="section">Already in the spool</h2>
          {preview.legs.map((leg, index) => (
            <div key={index} className="result-row" style={{ cursor: "default" }}>
              <div className="result-snippet">
                {leg.platform || "?"} · {leg.path.split(/[\\/]/).slice(-2).join("/")}
              </div>
              <div className="result-meta">
                {formatBytes(leg.bytes)}
                {leg.duplicate
                  ? ` · already ingested${leg.ingested_at ? ` ${leg.ingested_at.slice(0, 10)}` : ""}`
                  : " · new"}
                {leg.large ? " · large file" : ""}
                {leg.recognised ? "" : " · not recognised, kept"}
              </div>
            </div>
          ))}
          {preview.duplicates > 0 && (
            <div className="pager-info" style={{ marginBottom: 8 }}>
              {preview.duplicates} file(s) already ingested. Re-running is safe — every
              write is a MERGE on a stable key — but it costs the parse again.
            </div>
          )}
        </>
      )}

      {/* --------------------------------------------------------------- IMAP */}
      <h2 className="section">IMAP mailbox</h2>
      <div className="empty" style={{ paddingTop: 0, paddingBottom: 8 }}>
        For a live mailbox. A <code>.pst</code> is a file — drop it above instead.
        Outlook.com and O365 no longer allow password sign-in over IMAP; export a{" "}
        <code>.pst</code> for those.
      </div>
      <TextField
        label="email"
        value={imapEmail}
        onChange={(value) => {
          setImapEmail(value);
          if (!imapHost) setImapHost(hostFor(value));
        }}
        placeholder="you@yourdomain.com"
        autoComplete="off"
      />
      <TextField
        label="password"
        type="password"
        value={imapPassword}
        onChange={setImapPassword}
        placeholder="app password for Gmail, Yahoo, iCloud"
        autoComplete="new-password"
      />
      <TextField
        label="host"
        value={imapHost}
        onChange={setImapHost}
        placeholder="filled from the address; edit if wrong"
      />
      <TextField
        label="port"
        value={imapPort}
        onChange={setImapPort}
        placeholder="993"
      />
      <div className="empty" style={{ paddingTop: 0, paddingBottom: 8 }}>
        Local app, manual entry. Never read by MCP or AI. Writes to <code>./.env</code>.
      </div>
      <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 6 }}>
        <button
          className="ghost"
          onClick={saveCredentials}
          disabled={busy || !writeEnabled || !imapEmail.trim() || !imapPassword}
        >
          Save credentials
        </button>
        {envSaved && (
          <span className="pager-info">
            saved {envSaved.provider} → {envSaved.host}:{envSaved.port}
          </span>
        )}
        {!envSaved && envStatus && (
          <span className="pager-info">
            {Object.entries(envStatus.providers || {})
              .filter(([, row]) => row.email_present && row.password_present)
              .map(([name]) => name)
              .join(", ") || "no credentials on disk yet"}
          </span>
        )}
      </div>

      {/* --------------------------------------------------------- separator */}
      <hr
        style={{
          border: "none",
          borderTop: "1px solid var(--hairline)",
          margin: "18px 0 14px",
        }}
      />

      {/* ---------------------------------------------------------- settings */}
      <h2 className="section">How far back</h2>
      <div className="empty" style={{ paddingTop: 0, paddingBottom: 8 }}>
        Applied to every leg at parse time. A message outside the window is counted as
        skipped, never silently dropped.
      </div>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 10 }}>
        {WINDOWS.map((option) => (
          <button
            key={option.key}
            className={window_ === option.key ? "active" : "ghost"}
            onClick={() => setWindow(option.key)}
          >
            {option.label}
          </button>
        ))}
      </div>

      <TextField
        label="tz offset (hours)"
        value={tzOffset}
        onChange={setTzOffset}
        placeholder="leave blank to reuse the recorded offset"
        hint="e.g. -5 for US Eastern. Only Telegram, WhatsApp and Messenger accept it."
      />

      <h2 className="section">Groups</h2>
      <Check
        label="Exclude groups where the Owner never spoke"
        checked={silentGroups}
        onChange={setSilentGroups}
        hint="Parse time, permanent. A group you were added to and never spoke in is not a conversation you had. Ticked, those threads are dropped before any node is created."
      />
      {silentGroups && (
        <div style={{ display: "flex", gap: 16, margin: "2px 0 10px 22px" }}>
          {[
            ["telegram", "Telegram"],
            ["whatsapp", "WhatsApp"],
            ["messenger", "Fcbk Mssgr"],
          ].map(([key, label]) => (
            <Check
              key={key}
              label={label}
              checked={silentPlatforms[key]}
              onChange={(value) =>
                setSilentPlatforms((prev) => ({ ...prev, [key]: value }))
              }
            />
          ))}
        </div>
      )}
      <div className="empty" style={{ paddingTop: 0, paddingBottom: 8, marginLeft: 22 }}>
        Not the same as the Canvas "hide threads where the owner never sent a message" —
        that one is a view toggle and is reversible. This one decides what is stored.
      </div>

      <h2 className="section">Email spam</h2>
      <Check
        label="Exclude email threads of 10+ messages with no Owner reply"
        checked={spamThreads}
        onChange={setSpamThreads}
        hint="Parse time, permanent. A long thread you never replied to is almost always a broadcast, a notification chain or a mailing list. A short thread someone started with you is kept."
      />
      {/* Both sub-toggles default on: the rule is exclude-based, so "all selected"
          means every covered platform is filtered. */}
      {spamThreads && (
        <div style={{ display: "flex", gap: 16, margin: "2px 0 10px 22px" }}>
          {[["email", "Email"], ["outlook", "Outlook"]].map(([key, label]) => (
            <Check
              key={key}
              label={label}
              checked={spamPlatforms[key]}
              onChange={(value) =>
                setSpamPlatforms((prev) => ({ ...prev, [key]: value }))
              }
            />
          ))}
        </div>
      )}

      <Check
        label="Exclude Facebook groups with 50%+ non-conversation messages"
        checked={spamGroups}
        onChange={setSpamGroups}
        hint="Fcbk Mssgr only. Drops group threads where at least half the rows are housekeeping — 'sent a link', 'added X to the group', 'left the group'. Real group chats sit far below that ratio."
      />

      <h2 className="section">Prune prior ingests</h2>
      <div className="empty" style={{ paddingTop: 0, paddingBottom: 8 }}>
        Deletes spool files from earlier runs once this one has verified. A file that
        failed to land is never deleted.
      </div>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 10 }}>
        {[
          ["off", "Off"],
          ["0", "All"],
          ["1", "Keep last"],
          ["2", "Keep last 2"],
        ].map(([key, label]) => (
          <button
            key={key}
            className={pruneKeep === key ? "active" : "ghost"}
            onClick={() => setPruneKeep(key)}
          >
            {label}
          </button>
        ))}
      </div>

      {/* ------------------------------------------------------------ report */}
      {error && <div className="error" style={{ marginTop: 12 }}>{error}</div>}

      {/* --------------------------------------------------------------- halt */}
      {halted && (
        <div className="error" style={{ marginTop: 12 }}>
          <strong>
            {halted.failed.length} leg(s) could not be ingested.
          </strong>
          <div style={{ marginTop: 6 }}>
            {halted.failed.map((batch) => (
              <div key={batch.platform}>
                {batch.platform}: {batch.error}
              </div>
            ))}
          </div>
          <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
            <button onClick={continueWithout} disabled={busy}>
              Exclude and continue
            </button>
            <button className="ghost" onClick={cancelRun} disabled={busy}>
              Cancel
            </button>
          </div>
          <div className="pager-info" style={{ marginTop: 8 }}>
            Continuing re-runs the whole ingest without that leg. Every write is a MERGE
            on a stable key, so nothing already written is duplicated.
          </div>
        </div>
      )}

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
              {Object.entries(batch.skipped || {}).map(([reason, count]) => (
                <div key={reason} className="result-meta">
                  skipped {count}: {reason}
                </div>
              ))}
              {(batch.warnings || []).map((warning, warningIndex) => (
                <div
                  key={warningIndex}
                  className="result-meta"
                  style={{ color: "var(--orange-text)" }}
                >
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

      {/* ---------------------------------------------------------------- log */}
      {/* Below the button, newest at the top. This is the run's own record: what was
          attempted, what landed, what was skipped and why. */}
      <hr
        style={{
          border: "none",
          borderTop: "1px solid var(--hairline)",
          margin: "18px 0 10px",
        }}
      />
      <h2 className="section">Ingest log</h2>
      {log.length === 0 ? (
        <div className="empty" style={{ paddingTop: 0 }}>
          Nothing yet. Press Ingest to start.
        </div>
      ) : (
        <div style={{ maxHeight: 220, overflowY: "auto" }}>
          {log.map((entry, index) => (
            <div
              key={index}
              className="result-meta"
              style={{
                color:
                  entry.level === "warn"
                    ? "var(--orange-text)"
                    : entry.level === "ok"
                      ? "var(--text)"
                      : "var(--muted)",
                padding: "2px 0",
              }}
            >
              {entry.at.toLocaleTimeString()} · {entry.text}
            </div>
          ))}
        </div>
      )}
    </Modal>
  );
}
