/**
 * The only place the UI talks to the server.
 *
 * Every call is same-origin (`/api/...`). There is no base URL setting, no proxy and
 * no outbound host — the app is served by `python -m app` on 127.0.0.1 and this file
 * assumes that.
 *
 * Errors: the server turns a `ToolError` into a 400 with `{error: "..."}`. That
 * sentence is what the user should read, so it is thrown as-is.
 */

async function request(path, options = {}) {
  // A `FormData` body must carry NO content-type: the browser sets it, including the
  // multipart boundary. Forcing `application/json` here silently sent the form as
  // JSON, and FastAPI answered `files: Field required` — the failure looked like a
  // dropped folder producing nothing.
  const isForm = options.body instanceof FormData;
  const response = await fetch(path, {
    ...options,
    headers: options.body && !isForm
      ? { "content-type": "application/json", ...(options.headers || {}) }
      : options.headers,
  });

  let data = null;
  try {
    data = await response.json();
  } catch {
    /* empty body — fall through to the status check */
  }

  if (!response.ok) {
    throw new Error(readableError(data, response));
  }
  return data;
}

/**
 * Turn an error body into one sentence.
 *
 * FastAPI's validation failures arrive as `{detail: [{loc, msg, type}]}`, and
 * `JSON.stringify` on that produced a wall of JSON in the modal. A user needs the
 * sentence, not the schema.
 */
function readableError(data, response) {
  const detail = data && (data.error || data.detail);
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const parts = detail
      .map((item) => {
        if (typeof item === "string") return item;
        const field = Array.isArray(item?.loc) ? item.loc.filter((p) => p !== "body").join(".") : "";
        const msg = item?.msg || "invalid";
        return field ? `${field}: ${msg}` : msg;
      })
      .filter(Boolean);
    if (parts.length) return parts.join("; ");
  }
  return `${response.status} ${response.statusText}`;
}

export const api = {
  health: () => request("/api/health"),
  stats: () => request("/api/stats"),
  types: () => request("/api/types"),

  /**
   * Drain the MCP activity trace. **Draining, not tailing** — the server deletes the
   * rows it returns, so a poll never shows the same call twice.
   */
  activity: () => request("/api/activity"),

  /** One background job's state. `state` is `running`, `done` or `failed`. */
  job: (id) => request(`/api/jobs/${encodeURIComponent(id)}`),

  /** The job currently holding the store, if any. */
  jobs: () => request("/api/jobs"),

  /**
   * The canvas payload. `nodeTypes`/`edgeTypes` are explicit, never inherited.
   *
   * `sort` decides which nodes survive `limit` — it is not a display preference,
   * because the cutoff is real.
   */
  graph: ({ nodeTypes, edgeTypes, limit = 2000, sort = "messages" } = {}) => {
    const params = new URLSearchParams();
    if (nodeTypes?.length) params.set("nodes", nodeTypes.join(","));
    if (edgeTypes?.length) params.set("edges", edgeTypes.join(","));
    params.set("limit", String(limit));
    params.set("sort", sort);
    return request(`/api/graph?${params}`);
  },

  /** One thread's messages, newest first, paged. `q` filters inside the thread. */
  thread: (key, { skip = 0, limit = 50, q = null } = {}) => {
    const params = new URLSearchParams({ skip: String(skip), limit: String(limit) });
    if (q) params.set("q", q);
    return request(`/api/thread/${encodeURIComponent(key)}?${params}`);
  },

  message: (key) => request(`/api/message/${encodeURIComponent(key)}`),

  // `params` is forwarded verbatim. Dropping it silently turns every parameterised
  // Cypher statement into a 400 with an undefined `$k` — which is exactly how the
  // thread histogram broke.
  platforms: () => request("/api/platforms"),

  setPlatforms: (platforms) =>
    request("/api/platforms", {
      method: "POST",
      body: JSON.stringify({ platforms }),
    }),

  search: ({
    query,
    mode = "fulltext",
    limit = 25,
    platform = null,
    threadKey = null,
    params = null,
  }) =>
    request("/api/search", {
      method: "POST",
      body: JSON.stringify({
        query,
        mode,
        limit,
        platform,
        thread_key: threadKey,
        params,
      }),
    }),

  embedStatus: () => request("/api/embed/status"),

  embed: ({ limit = 5000, writeEnabled = false } = {}) =>
    request("/api/embed", {
      method: "POST",
      body: JSON.stringify({ limit, write_enabled: writeEnabled }),
    }),

  flushEmbeds: ({ writeEnabled = false } = {}) =>
    request("/api/embed/flush", {
      method: "POST",
      body: JSON.stringify({ write_enabled: writeEnabled, confirm: true }),
    }),

  chat: ({ message, messages = [], writeEnabled = false }) =>
    request("/api/chat", {
      method: "POST",
      body: JSON.stringify({ message, messages, write_enabled: writeEnabled }),
    }),

  chatHealth: () => request("/api/chat/health"),

  ingest: (payload) =>
    request("/api/ingest", { method: "POST", body: JSON.stringify(payload) }),

  /**
   * Copy picked files into the spool. The browser can hand over contents but never a
   * filesystem path, so this is the only way a drop box can work.
   *
   * `write_enabled` is a query parameter because the body is multipart.
   */
  upload: (files, { writeEnabled = false } = {}) => {
    const body = new FormData();
    // `webkitRelativePath` is set only by a folder pick (`<input webkitdirectory>`),
    // and it carries the tree (`ChatExport_x/result.json`). Without it a folder pick
    // collapsed to bare filenames and the server filed every export at the platform
    // root, where two `result.json` files overwrite each other.
    for (const file of files) {
      body.append("files", file, file.webkitRelativePath || file.name);
    }
    return api.uploadForm(body, { writeEnabled });
  },

  /**
   * Upload an ALREADY-BUILT `FormData`.
   *
   * `uppie` produces this itself: it walks a dropped folder with `webkitGetAsEntry`
   * and appends every file under its path relative to the dropped folder, which is
   * how the server gets `ChatExport_2026-11-01/result.json` rather than a bare
   * `result.json`. The field name must be `files` — `files[]` is 422 from FastAPI.
   */
  uploadForm: (body, { writeEnabled = false } = {}) =>
    request(`/api/ingest/upload?write_enabled=${writeEnabled}`, {
      method: "POST",
      body,
    }),

  /** Which `.env` keys exist. Never returns a value — only present/absent. */
  envStatus: () => request("/api/ingest/env"),

  /** Read-only: what is in the spool, and what has already been ingested. */
  preview: (which = "real") => request(`/api/ingest/preview?which=${which}`),

  /** Wipe the graph and the dedup manifest. Destructive; needs confirm. */
  truncate: (payload) =>
    request("/api/ingest/truncate", { method: "POST", body: JSON.stringify(payload) }),

  /** Delete the exports in `spool/real/` only. The graph is untouched. */
  deleteSpool: (payload) =>
    request("/api/ingest/spool/delete", {
      method: "POST",
      body: JSON.stringify(payload),
    }),


  verify: (which = "real") => request(`/api/ingest/verify?which=${which}`),

  prune: (payload) =>
    request("/api/ingest/prune", { method: "POST", body: JSON.stringify(payload) }),
};
