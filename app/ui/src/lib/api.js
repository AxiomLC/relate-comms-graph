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
  const response = await fetch(path, {
    headers: options.body ? { "content-type": "application/json" } : undefined,
    ...options,
  });

  let data = null;
  try {
    data = await response.json();
  } catch {
    /* empty body — fall through to the status check */
  }

  if (!response.ok) {
    const message =
      (data && (data.error || data.detail)) || `${response.status} ${response.statusText}`;
    throw new Error(typeof message === "string" ? message : JSON.stringify(message));
  }
  return data;
}

export const api = {
  health: () => request("/api/health"),
  stats: () => request("/api/stats"),
  types: () => request("/api/types"),

  /** The canvas payload. `nodeTypes`/`edgeTypes` are explicit, never inherited. */
  graph: ({ nodeTypes, edgeTypes, limit = 2000 } = {}) => {
    const params = new URLSearchParams();
    if (nodeTypes?.length) params.set("nodes", nodeTypes.join(","));
    if (edgeTypes?.length) params.set("edges", edgeTypes.join(","));
    params.set("limit", String(limit));
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
  sources: () => request("/api/sources"),

  setSources: (sources) =>
    request("/api/sources", {
      method: "POST",
      body: JSON.stringify({ sources }),
    }),

  search: ({
    query,
    mode = "substring",
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

  chat: ({ message, messages = [], writeEnabled = false }) =>
    request("/api/chat", {
      method: "POST",
      body: JSON.stringify({ message, messages, write_enabled: writeEnabled }),
    }),

  chatHealth: () => request("/api/chat/health"),

  ingest: (payload) =>
    request("/api/ingest", { method: "POST", body: JSON.stringify(payload) }),

  verify: (source = "real") => request(`/api/ingest/verify?source=${source}`),

  prune: (payload) =>
    request("/api/ingest/prune", { method: "POST", body: JSON.stringify(payload) }),
};
