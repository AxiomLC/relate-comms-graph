import { useEffect, useRef, useState } from "react";
import { FileUp, Loader2, Upload } from "lucide-react";
import { uppie } from "uppie";

import { api } from "../../lib/api.js";
import Modal, { Check, TextField } from "./Modal.jsx";

/**
 * One line describing what is staged, grouped by platform.
 *
 * `3 files ready · email, telegram` — or `190 files ready · email` for a mailbox drop.
 * An unrecognised file is called out because it is the one thing the user may need to
 * act on; the names themselves are in INGEST LOG.
 */
/**
 * `C:\Users\me\repo\sample_writer\out\telegram\Telegram Desktop`
 *   -> `C:…\out\telegram\Telegram Desktop`
 *
 * A forked repo lives somewhere else, so the absolute prefix is noise: the last two
 * segments are what identify the export, and the drive letter is what says it is a
 * real path. Two segments are kept because `email_eml` alone is ambiguous while
 * `out\email\email_eml` is not.
 */
function shortenPath(full) {
  const parts = String(full || "").split(/[\\/]+/).filter(Boolean);
  if (parts.length <= 3) return parts.join("\\");
  const drive = parts[0].length === 2 && parts[0][1] === ":" ? parts[0] : "";
  const tail = parts.slice(-2).join("\\");
  return drive ? `${drive}…\\${tail}` : `…\\${tail}`;
}

/**
 * One line per thing the user picked — the top folder of the selection, never its
 * contents.
 *
 * The root is derived from the relative path the browser sent (`email_eml/Inbox/x.eml`
 * -> `email_eml`), so this does not depend on the server's grouping. A folder pick is
 * one line however many files it holds; a multi-file pick is one line per file.
 *
 * `duplicate` is the spool dedup: a root whose files are all already ingested is
 * shown in red, because it will be skipped and silence reads as failure.
 */
function stagedRoots(items) {
  const roots = new Map();
  for (const item of items) {
    const rel = String(item.name || "").split(/[\\/]+/).filter(Boolean);
    const top = rel.length > 1 ? rel[0] : "";
    const key = top || item.path || item.name;
    const row = roots.get(key) || {
      label: top || shortenPath(item.path || item.name),
      count: 0,
      recognised: true,
      duplicate: true,
    };
    row.count += 1;
    row.recognised = row.recognised && item.recognised !== false;
    row.duplicate = row.duplicate && item.duplicate === true;
    roots.set(key, row);
  }
  return [...roots.values()].sort((a, b) => a.label.localeCompare(b.label));
}

/**
 * Ingest: one modal, one tab, top to bottom.
 *
 *   ├ Truncate Graph DB ......... Delete Spool ────────────────┤
 *   │ pick one or many files, or paste a path                  │
 *   ├ IMAP ────────────────────────────────────────────────────┤
 *   │ email / password / host / port, saved to ./.env          │
 *   ├ ── separator ────────────────────────────────────────────┤
 *   │ window · silent groups · spam threads                    │
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

/**
 * **No provider table, no domain guessing.**
 *
 * There used to be a 15-entry `HOSTS` map and a `providerFor()` that turned an unknown
 * domain into the pseudo-provider `custom` — which the server then refused, silently.
 * The host is now a field the user fills in and can see. The only convenience left is
 * the two hosts nobody should have to remember.
 */
const HOST_HINTS = {
  "gmail.com": "imap.gmail.com",
  "googlemail.com": "imap.gmail.com",
};

export default function IngestModal({ onClose, onIngested }) {
  // --- drop box ------------------------------------------------------------
  const [paths, setPaths] = useState("");
  const [picked, setPicked] = useState([]);
  const [staged, setStaged] = useState([]);
  const dropRef = useRef(null);
  const fileRef = useRef(null);
  const folderRef = useRef(null);
  // `uppie` owns the dropzone's listeners, so the callback it calls lives in a ref:
  // the library binds once, while React re-renders with fresh state on every keystroke.
  const dropHandlerRef = useRef(null);

  // --- IMAP ----------------------------------------------------------------
  // **One checkbox, no button.** Ticking it means "read this mailbox as part of this
  // ingest". The four values travel with the run and reach `.env` only if the run
  // succeeds — so a wrong password leaves nothing behind.
  const [imapOn, setImapOn] = useState(false);
  const [imapEmail, setImapEmail] = useState("");
  const [imapPassword, setImapPassword] = useState("");
  const [imapHost, setImapHost] = useState("");
  const [imapPort, setImapPort] = useState("993");
  // Reveal is local-only: it flips the input's `type`, nothing leaves the browser.
  const [showPassword, setShowPassword] = useState(false);
  const [envStatus, setEnvStatus] = useState(null);

  // **Autofill on a match, never on open.** Nothing is filled until the user has typed
  // at least three characters of the saved address; then host and port fill in. The
  // password field stays empty and its placeholder says one is saved — the secret never
  // enters the DOM.
  //
  // Filling on mount was wrong: the modal opened with a mailbox already in the box, so
  // it looked like the app had chosen one for you.
  const saved = envStatus || {};
  const typed = imapEmail.trim().toLowerCase();
  const matchesSaved =
    typed.length >= 3 && !!saved.email && saved.email.toLowerCase().startsWith(typed);
  const savedPassword = matchesSaved && !!saved.password_present;

  // Fill host and port once a typed prefix matches the saved address. Guarded by
  // `matchesSaved` so it never fires on mount, and by the field being empty so it never
  // overwrites something the user typed.
  useEffect(() => {
    if (!matchesSaved) return;
    setImapHost((current) => current || saved.host || "");
    setImapPort((current) => current || saved.port || "993");
  }, [matchesSaved, saved.host, saved.port]);

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


  // --- run state -----------------------------------------------------------
  // `delta` is the normal path and is no longer a UI choice: it only ever reads
  // messages the store does not already hold. The former "Full re-process" checkbox is
  // gone because truncating first achieves the same thing with no extra cost, and a
  // toggle that needed a paragraph of explanation was a toggle nobody read.
  // The capability still exists at the API (`delta: false`) for a scripted re-extract.
  const [writeEnabled, setWriteEnabled] = useState(false);
  const [busy, setBusy] = useState(false);
  const [report, setReport] = useState(null);
  const [error, setError] = useState(null);
  const [preview, setPreview] = useState(null);
  const [log, setLog] = useState([]);
  // An actionable message shown DIRECTLY under the dropzone. Separate from `error`,
  // which renders far below in the report area and is invisible at modal height.
  const [dropNotice, setDropNotice] = useState(null);
  const [halted, setHalted] = useState(null);

  // Double confirm: `wipeStep` 0 = idle, 1 = "are you sure", 2 = "type nothing, press
  // the second button". Two deliberate clicks, because there is no undo.
  // `spoolStep` is the same ladder for the spool, kept separate so confirming one
  // never arms the other.
  const [wipeStep, setWipeStep] = useState(0);
  const [wipeResult, setWipeResult] = useState(null);
  const [spoolStep, setSpoolStep] = useState(0);
  const [spoolResult, setSpoolResult] = useState(null);

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
    if (!writeEnabled) {
      setDropNotice(
        "Tick Ingest Ready first — files cannot be staged until write access is on."
      );
      return;
    }
    setDropNotice(null);
    setBusy(true);
    setError(null);
    try {
      const result = await api.upload(files, { writeEnabled });
      setStaged((prev) => [...prev, ...(result.staged || [])]);
      setPicked([]);
      if (fileRef.current) fileRef.current.value = "";
      if (folderRef.current) folderRef.current.value = "";
      if (result.skipped_media) {
        note(
          "info",
          `${result.skipped_media} media file(s) skipped — this app reads text only`,
        );
      }
      refreshPreview();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  /**
   * Upload a `FormData` that `uppie` already built from a drop or a folder pick.
   *
   * Why not `dataTransfer.files`: a browser reports a dropped DIRECTORY as zero
   * files, so the old handler silently did nothing for the one case that matters
   * most (Telegram ships a folder). `uppie` reads `webkitGetAsEntry`, walks the tree
   * to exhaustion, and appends each file under its path relative to the dropped
   * folder — so the server sees `ChatExport_2026-11-01/result.json` and files it in
   * `spool/real/telegram/ChatExport_2026-11-01/`.
   */
  const uploadForm = async (formData) => {
    // An empty FormData means "the dialog was cancelled", not "upload nothing".
    const hasFiles = [...formData.keys()].length > 0;
    if (!hasFiles) {
      note("info", "nothing selected");
      return;
    }
    // **Refuse here, not at the server.** The upload route answers 400 when write is
    // disabled, and that message used to land in INGEST LOG at the bottom of the modal —
    // off-screen at normal height, so a correct drop looked like a dead dropzone. This
    // check is local, instant, and appears directly under the dropzone.
    if (!writeEnabled) {
      setDropNotice(
        "Tick Ingest Ready first — files cannot be staged until write access is on."
      );
      note("warn", "upload blocked: Ingest Ready is off");
      return;
    }
    setDropNotice(null);
    setBusy(true);
    setError(null);
    note("info", `reading ${formData.getAll("files").length} file(s)…`);
    try {
      const result = await api.uploadForm(formData, { writeEnabled });
      const staged = result.staged || [];
      setStaged((prev) => [...prev, ...staged]);
      note("ok", `staged ${staged.length} file(s)`);
      if (result.skipped_media) {
        note(
          "info",
          `${result.skipped_media} media file(s) skipped — this app reads text only`,
        );
      }
      refreshPreview();
    } catch (err) {
      setError(err.message);
      note("warn", `upload failed: ${err.message}`);
    } finally {
      setBusy(false);
    }
  };
  // Keep the ref current so uppie's once-bound callback always sees fresh state.
  dropHandlerRef.current = uploadForm;

  // `uppie` attaches its own drag/drop handling to the node. It must run once, after
  // the node exists, and be torn down on unmount — the library has no `destroy()` for
  // a drop target, so the element identity is what changes.
  useEffect(() => {
    const node = dropRef.current;
    if (!node) return undefined;
    uppie(node, { name: "files" }, (_event, formData) => {
      node.classList.remove("over");
      dropHandlerRef.current?.(formData);
    });
    return undefined;
  }, []);

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


  /**
   * One ingest run.
   *
   * `skip` is a set of platform names to leave out — that is how "exclude this leg and
   * continue" is expressed. The run is **restarted** rather than resumed: every write
   * is a MERGE on a stable key, so a second run over the same spool adds nothing and
   * costs only the parse. Resuming mid-pipeline would mean holding a half-written
   * batch across a user decision, which is a far worse thing to get wrong.
   */
  /**
   * Wait for a background job to finish, reporting progress as it goes.
   *
   * Polls every 700 ms — fast enough that a short ingest feels immediate, slow enough
   * that a long one is not a request storm. A job that vanishes (the app restarted) is
   * reported as a failure rather than hanging the modal forever.
   */
  const pollJob = async (jobId, onProgress) => {
    let lastStage = null;
    for (;;) {
      await new Promise((resolve) => setTimeout(resolve, 700));
      let job;
      try {
        job = await api.job(jobId);
      } catch (err) {
        throw new Error(`lost track of the ingest: ${err.message}`);
      }
      if (job.progress?.stage && job.progress.stage !== lastStage) {
        lastStage = job.progress.stage;
        onProgress?.(job);
      }
      if (job.state !== "running") return job;
    }
  };

  const run = async ({ skip = new Set() } = {}) => {
    setBusy(true);
    setError(null);
    setReport(null);
    setHalted(null);
    // The "ready" list has done its job the moment the run starts: what is being read
    // is now the spool, not this list.
    setStaged([]);
    setPicked([]);
    note("info", "Ingesting…");
    try {
      const months = WINDOWS.find((w) => w.key === window_)?.months ?? null;
      // **Start, then poll.** An ingest holds the store for its whole duration, so
      // awaiting it blocked every other surface and a second client collided with it.
      // The server returns a job id in milliseconds; the work runs on a thread.
      const started = await api.ingest({
        which: "real",
        paths: pathList(),
        imap:
          imapOn && imapEmail.trim() && !skip.has("email")
            ? {
                email: imapEmail.trim(),
                password: imapPassword,
                host: imapHost.trim(),
                port: Number(imapPort) || 993,
              }
            : null,
        since: windowStart(months),
        tz_offset_hours: tzOffset === "" ? null : Number(tzOffset),
        exclude_silent_groups: silentGroups,
        silent_group_platforms: silentGroups ? ticked(silentPlatforms) : null,
        exclude_spam_threads: spamThreads,
        spam_thread_platforms: spamThreads ? ticked(spamPlatforms) : null,
        exclude_spam_groups: spamGroups,
        write_enabled: writeEnabled,
      });

      const result = await pollJob(started.job, (job) => {
        if (job.progress?.stage) note("info", `… ${job.progress.stage}`);
      });
      if (result.state === "failed") {
        throw new Error(result.error || "the ingest failed");
      }

      // **The mailbox verdict, before the per-platform lines.** Three cases, and the
      // user needs to know which one happened: a delta, a first ingest, or a
      // replacement that removed the previous mailbox's messages.
      const progress = result.progress || {};
      if (progress.replaced) {
        note(
          "warn",
          `mailbox changed: removed every message from ${progress.replaced} ` +
            `before reading ${progress.saved_mailbox}`,
        );
      } else if (progress.saved_mailbox) {
        note("ok", `mailbox ${progress.saved_mailbox} saved to .env`);
      }

      // A leg that failed is the one thing worth stopping on: the rest landed, and the
      // user has to decide whether to retry without it.
      const failed = (result.batches || []).filter(
        (batch) => batch.error && !skip.has(batch.platform),
      );
      // **Summaries, one line per platform.** A mailbox is 190 batches and a Messenger
      // export is 29; a line each turned the log into a wall nobody reads. What the
      // user needs is "email: 1,204 msgs", then the failures, then one verdict.
      const byPlatform = new Map();
      for (const batch of result.batches || []) {
        if (batch.error) continue;
        const key = batch.platform || "unrecognised";
        const row = byPlatform.get(key) || { messages: 0, attachments: 0, files: 0 };
        row.messages += batch.messages || 0;
        row.attachments += batch.attachments || 0;
        row.files += 1;
        byPlatform.set(key, row);
      }
      for (const [platform, row] of [...byPlatform.entries()].sort()) {
        note(
          "ok",
          `${platform}: ${row.messages} msgs · ${row.attachments} attachments` +
            (row.files > 1 ? ` · ${row.files} files` : ""),
        );
      }
      for (const batch of failed) {
        note("fail", `${batch.platform}: ${batch.error}`);
      }

      setReport(result);
      onIngested?.(result);
      refreshPreview();

      if (failed.length) {
        // Keep the staged list: the user is about to retry without those legs, and an
        // empty list would misrepresent what is still waiting in the spool.
        setHalted({ failed, skip });
        note("fail", `${failed.length} leg(s) failed — exclude and continue, or cancel`);
      } else {
        const total = [...byPlatform.values()].reduce((sum, row) => sum + row.messages, 0);
        const written = result.written ?? 0;
        note(
          "done",
          written === 0 && total === 0
            ? "nothing new · the store already holds everything in this window"
            : `all ingested · ${written} new message(s)`,
        );
      }
    } catch (err) {
      setError(err.message);
      note("fail", err.message);
    } finally {
      setBusy(false);
    }
  };

  /**
   * Destructive actions, both two clicks, both independent of `Ingest Ready`.
   *
   * **Not gated by `writeEnabled`.** Truncate and the spool delete are not steps in a
   * run, and the toggle arms the *Ingest* button only. Their own double confirm IS the
   * arming — two deliberate clicks for one irreversible action, the same guarantee the
   * backend's `write_enabled` + `confirm` pair asks for. Sending `write_enabled: true`
   * here is therefore honest, not a bypass: the user has just confirmed twice.
   *
   * `withSpool` deletes the exports as well. They are separate buttons because they are
   * separate decisions: wiping the graph is not a request to throw away your downloads,
   * but leaving stale exports means the next ingest re-reads what you just removed.
   */
  const truncate = async () => {
    setBusy(true);
    setError(null);
    setWipeResult(null);
    note("info", "truncating the graph…");
    try {
      const result = await api.truncate({
        write_enabled: true,
        confirm: true,
      });
      setWipeResult(result);
      setWipeStep(0);
      setSpoolStep(0);
      setReport(null);
      note(
        "warn",
        `truncated — ${result.removed.length} path(s) removed` +
          (result.kept?.length ? ` · kept ${result.kept.length}` : ""),
      );
      refreshPreview();
      onIngested?.({});
    } catch (err) {
      setError(err.message);
      note("warn", `truncate failed: ${err.message}`);
    } finally {
      setBusy(false);
    }
  };

  /**
   * Delete the spool ONLY. The graph is left exactly as it is.
   *
   * **Not `truncate({withSpool: true})`.** That was the first version and it was wrong:
   * the button said "Delete Spool", so a user clearing old exports silently lost the
   * graph built from them. One button, one consequence.
   */
  const deleteSpool = async () => {
    setBusy(true);
    setError(null);
    setSpoolResult(null);
    note("info", "deleting the spool…");
    try {
      const result = await api.deleteSpool({
        write_enabled: true,
        confirm: true,
        older_than_days: 1,
      });
      setSpoolResult(result);
      setSpoolStep(0);
      note("warn", `spool deleted — ${result.count} file(s) removed`);
      refreshPreview();
    } catch (err) {
      setError(err.message);
      note("warn", `spool delete failed: ${err.message}`);
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
      side
      footer={
        <>
          {/* The one gate before the button. Ingest writes to the store, so it is
              armed explicitly and never remembered — a remembered toggle is a toggle
              nobody remembers turning on. */}
          <Check
            label="Ingest Ready"
            checked={writeEnabled}
            onChange={setWriteEnabled}
            note="confirm"
          />
          <span className="spacer" />
          <button className="ghost" onClick={onClose}>
            Close
          </button>
          <button
            className="primary"
            onClick={run}
            disabled={busy || !writeEnabled || !hasInput}
          >
            {busy ? <Loader2 size={13} className="spin" /> : <Upload size={13} />}
            Ingest
          </button>
        </>
      }
    >
      {/* ------------------------------------------------- truncate / spool delete */}
      {/* At the top, because these change what the whole app is looking at. Truncate is
          left, the spool delete right, on one row: they are the two irreversible
          actions in this modal and they belong together. No explanatory paragraph —
          each button names exactly what it deletes, and the second click is where the
          warning lives. */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 10,
          padding: "8px 10px",
          marginBottom: 14,
          border: "1px solid var(--hairline)",
          borderRadius: "var(--radius-sm)",
        }}
      >
        {/* ---- left: the graph ---- */}
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          {wipeStep === 0 && (
            <button className="ghost" onClick={() => setWipeStep(1)} disabled={busy}>
              Truncate Graph DB
            </button>
          )}
          {wipeStep === 1 && (
            <>
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
              <button className="ghost" onClick={() => setWipeStep(0)} disabled={busy}>
                Cancel
              </button>
              {/* No `!writeEnabled` — see `truncate()`. The double confirm is the arming. */}
              <button onClick={() => truncate()} disabled={busy}>
                {busy ? <Loader2 size={13} className="spin" /> : null}
                Delete everything
              </button>
            </>
          )}
          {wipeResult && wipeStep === 0 && (
            <span className="pager-info" style={{ color: "var(--orange-text)" }}>
              graph truncated
            </span>
          )}
        </div>

        {/* ---- right: the exports themselves ---- */}
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          {spoolStep === 0 && (
            <button className="ghost" onClick={() => setSpoolStep(1)} disabled={busy}>
              Delete Spool
            </button>
          )}
          {spoolStep === 1 && (
            <>
              <button className="ghost" onClick={() => setSpoolStep(0)} disabled={busy}>
                Keep them
              </button>
              <button onClick={() => setSpoolStep(2)} disabled={busy}>
                Yes, delete
              </button>
            </>
          )}
          {spoolStep === 2 && (
            <>
              <button className="ghost" onClick={() => setSpoolStep(0)} disabled={busy}>
                Cancel
              </button>
              <button onClick={deleteSpool} disabled={busy}>
                {busy ? <Loader2 size={13} className="spin" /> : null}
                Delete spool
              </button>
            </>
          )}
          {spoolResult && spoolStep === 0 && (
            <span className="pager-info" style={{ color: "var(--orange-text)" }}>
              spool deleted
            </span>
          )}
        </div>
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
      {/* A folder pick. `webkitdirectory` is the only way a browser will hand over a
          whole tree from a dialog; without it, `Telegram Desktop/` and `email_eml/`
          could only ever arrive by drag and drop. Each file carries
          `webkitRelativePath`, which `api.upload` sends as the multipart filename so
          the server can rebuild the tree. */}
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
      {/* The drop target. `uppie` (the effect above) owns its drag and drop listeners,
          including recursive folder traversal — the browser reports a dropped folder as
          zero files, so a plain `dataTransfer.files` handler silently does nothing for
          the one export shape that needs it most. The `data-uppie` attribute is a marker
          for debugging, not behaviour. */}
      <div
        className="dropzone"
        ref={dropRef}
        data-uppie="drop"
        onClick={() => fileRef.current?.click()}
        onDragLeave={() => dropRef.current?.classList.remove("over")}
        // `uppie` preventDefaults the drop, but the dragenter highlight is ours.
        onDragEnter={(event) => {
          event.preventDefault();
          dropRef.current?.classList.add("over");
        }}
        onDragOver={(event) => {
          event.preventDefault();
          dropRef.current?.classList.add("over");
        }}
        style={{ cursor: "pointer" }}
      >
        <FileUp size={18} style={{ marginBottom: 6 }} />
        <br />
        <strong>Drop files, a folder, or a zip here — or click to choose files.</strong>
        <br />
        A folder works: Telegram ships <code>ChatExport_…/result.json</code>, and dropping
        the folder walks it. Everything stays on this machine.
      </div>
      <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
        <button className="ghost" onClick={() => fileRef.current?.click()}>
          Choose files
        </button>
        <button className="ghost" onClick={() => folderRef.current?.click()}>
          Choose folder
        </button>
        <span className="pager-info" style={{ alignSelf: "center" }}>
          {writeEnabled
            ? "or drag one onto the box, or paste its path below"
            : "tick Ingest Ready below to enable staging"}
        </span>
      </div>

      {dropNotice && (
        <div
          className="pager-info"
          style={{ color: "var(--orange-text)", marginTop: 8 }}
        >
          {dropNotice}
        </div>
      )}

      {stagedCount > 0 && (
        <div style={{ marginTop: 8 }}>
          {/* **One line per picked root, never per file.** This is the "loaded and ready"
              list: it says what is waiting, by the folder the user actually chose, and
              it is cleared the moment Ingest starts. Per-file detail belongs in the
              report below, not here. */}
          {stagedRoots(staged).map((row) => (
            <div
              key={row.label}
              className="mono"
              style={{
                color:
                  !row.recognised || row.duplicate
                    ? "var(--red-text)"
                    : "var(--orange-text)",
                padding: "2px 0",
                wordBreak: "break-all",
              }}
            >
              {row.label}
              {row.count > 1 ? `  (${row.count} files)` : ""}
              {!row.recognised ? "  · not recognised" : ""}
              {row.recognised && row.duplicate ? "  · already ingested, will be skipped" : ""}
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

      {/* What is already in the spool — a plain inventory, not a warning.

          This used to say "N file(s) are already ingested and will be skipped" in
          orange, which fired on every modal open because the spool still holds what
          you just ingested. That reads as an error immediately after a successful run.

          The duplicate warning belongs on the thing you DROP, not on the spool's
          contents: the ready list above already marks a root red when it is already
          ingested. Here we only say what is waiting. */}
      {preview && (preview.legs || []).length > 0 && (
        <div className="pager-info" style={{ margin: "8px 0 4px" }}>
          spool contains {(preview.legs || []).length} export
          {(preview.legs || []).length === 1 ? "" : "s"}:{" "}
          {[...new Set((preview.legs || []).map((leg) => leg.platform || "unrecognised"))]
            .sort()
            .join(", ")}
        </div>
      )}

      {/* --------------------------------------------------------------- IMAP */}
      {/* Two columns, because four stacked fields cost a third of the modal for a leg
          most runs do not use. The descriptor is one line: what this is for, and the
          one caveat that changes what the user does next. */}
      <h2 className="section">IMAP INBOX</h2>
      <div className="empty" style={{ paddingTop: 0, paddingBottom: 8 }}>
        For any IMAP email or Gmail. Outlook is <code>.pst</code> file only as dropped
        above.
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0 12px" }}>
        <TextField
          label="email"
          value={imapEmail}
          onChange={(value) => {
            setImapEmail(value);
            // Fill the host only when it is empty, and only for the two hosts nobody
            // should have to remember. Everything else is typed, not guessed.
            const domain = (value.split("@")[1] || "").toLowerCase();
            if (!imapHost && HOST_HINTS[domain]) setImapHost(HOST_HINTS[domain]);
          }}
          placeholder="you@yourdomain.com"
          autoComplete="off"
        />
        <div style={{ display: "flex", alignItems: "flex-end", gap: 6 }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <TextField
              label="password"
              type={showPassword ? "text" : "password"}
              value={imapPassword}
              onChange={setImapPassword}
              placeholder={savedPassword ? "•••••••• (saved)" : "app password"}
              autoComplete="new-password"
            />
          </div>
          <button
            className="ghost"
            onClick={() => setShowPassword((value) => !value)}
            title={showPassword ? "Hide the password" : "Show the password"}
            style={{ padding: "5px 8px", marginBottom: 1 }}
          >
            {showPassword ? "hide" : "show"}
          </button>
        </div>
        <TextField
          label="host"
          value={imapHost}
          onChange={setImapHost}
          placeholder="imap.gmail.com"
        />
        <TextField
          label="port"
          value={imapPort}
          onChange={setImapPort}
          placeholder="993"
        />
      </div>
      <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 6 }}>
        <Check
          label="Save credentials"
          checked={imapOn}
          onChange={setImapOn}
          hint="Written to ./.env only if the ingest succeeds."
        />
        <span className="pager-info">
          {saved.configured ? `in env: ${saved.email}` : "no credentials saved yet"}
        </span>
      </div>
      {saved.configured && imapEmail.trim() && !matchesSaved ? (
        <div className="empty" style={{ paddingTop: 0, paddingBottom: 6, color: "var(--orange-text)" }}>
          A different mailbox replaces <strong>{saved.email}</strong>: its messages are
          removed from the graph before this one is read.
        </div>
      ) : null}

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
                  entry.level === "fail"
                    ? "var(--red-text)"
                    : entry.level === "done"
                      ? "var(--green-text)"
                      : entry.level === "warn"
                        ? "var(--orange-text)"
                        : entry.level === "ok"
                          ? "var(--text)"
                          : "var(--muted)",
                fontWeight: entry.level === "done" ? 600 : undefined,
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
