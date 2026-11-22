import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowLeft, ArrowRight, CornerDownRight, Loader2, Search } from "lucide-react";

import { api } from "../lib/api.js";
import {
  formatCount,
  formatDate,
  formatDateTime,
  monthKey,
  monthLabel,
} from "../lib/format.js";
import {
  NODE_TYPES,
  isPlaceholder,
  platformColor,
  platformLabel,
} from "../config/nodeTypes.js";

/**
 * The Viewer: two content states and a Back button (UI-Cytoscape.md §9).
 *
 *   state0  `results`  a search or an AI answer — one row per hit
 *   state1  `node`     a Thread (its messages), a Correspondent (its threads) or
 *                      one Message
 *
 * The stack itself lives in `App` (`useViewerStack`); this component renders
 * whatever `entry` currently is. That split is deliberate: the halo/fly-to rule
 * needs the stack to know whether a push came from a graph click or a result row,
 * and the camera lives in the canvas.
 *
 * Nothing here ever renders a whole thread. The 707-message thread is the test
 * case, and it pages.
 */

// How many messages one *view load* shows is decided by characters, not by count.
// Three one-sentence replies and one long paragraph should both fill the pane
// roughly once — a fixed count gives you a screen of stubs or one wall of text.
const CHAR_BUDGET = 1000;
const FETCH = 40; // rows asked of the server per request; consumed by budget
const MIN_PER_LOAD = 1; // a single long message still gets its own load

/**
 * Every platform a node spans, in the order the API gives them.
 *
 * `platform` is the single first-by-date string the source filter reads; `platforms`
 * is the full list. A merged node carries both, and they disagree on purpose — so
 * anything that *displays* platforms must read the list, never the string.
 */
function platformsOf(entry) {
  if (Array.isArray(entry?.platforms) && entry.platforms.length) {
    return entry.platforms;
  }
  return entry?.platform ? [entry.platform] : [];
}

export default function Viewer({
  entry,
  theme,
  onOpen,
  onHalo,
  onFocus,
  onBack,
  canBack,
  depth,
}) {
  return (
    <>
      <div className="pane-header">
        <span className="pane-title">Viewer</span>
        {depth > 0 && <span className="pill">{depth}</span>}
        <div className="viewer-nav">
          <button
            className="ghost icon"
            onClick={onBack}
            disabled={!canBack}
            title="Back (the camera does not move)"
          >
            <ArrowLeft size={14} />
          </button>
        </div>
      </div>

      {!entry && <EmptyViewer />}
      {entry?.kind === "results" && (
        <ResultsView entry={entry} onOpen={onOpen} onHalo={onHalo} onFocus={onFocus} />
      )}
      {entry?.kind === "node" && entry.nodeType === "Thread" && (
        <ThreadView entry={entry} onOpen={onOpen} />
      )}
      {entry?.kind === "node" && entry.nodeType === "Correspondent" && (
        <CorrespondentView entry={entry} onOpen={onOpen} />
      )}
      {entry?.kind === "node" && entry.nodeType === "Message" && (
        <MessageView entry={entry} onOpen={onOpen} />
      )}
      {entry?.kind === "node" && ENTITY_TYPES.has(entry.nodeType) && (
        <EntityView entry={entry} onOpen={onOpen} />
      )}
    </>
  );
}

// The four extracted kinds. One view serves all four because the store gives them
// one shape (`key`, `display_name`, `platforms`, `mention_count`) — only the label
// differs. Derived from the config so a kind added there is routed here for free.
const ENTITY_TYPES = new Set(
  Object.entries(NODE_TYPES)
    .filter(([, meta]) => meta.countKey === "mention_count")
    .map(([type]) => type),
);

/* ------------------------------------------------------------------ empty */

function EmptyViewer() {
  return (
    <div className="pane-body">
      <div className="empty">
        Click a thread on the canvas to read it.
        <br />
        <br />
        Or search above — results land here, and clicking one moves the camera to
        that node.
        <br />
        <br />
        The canvas draws <strong>threads</strong> and <strong>correspondents</strong>.
        Messages are never drawn: 12,499 nodes is not drawable, 955 is. Every message
        is still in the store and still visible to the AI.
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- results */

function ResultsView({ entry, onOpen, onHalo, onFocus }) {
  const { rows, query, mode, truncated, count, error, cypher } = entry;

  if (error) {
    return (
      <div className="pane-body">
        <div className="error">{error}</div>
      </div>
    );
  }

  return (
    <>
      <div className="viewer-head">
        <h1 className="viewer-title">
          {mode === "cypher" ? "Cypher result" : `“${query}”`}
        </h1>
        <div className="viewer-sub">
          <span>{formatCount(count)} row{count === 1 ? "" : "s"}</span>
          {truncated && <span className="pill">truncated</span>}
          <span className="pill">{mode}</span>
        </div>
        {cypher && (
          <details className="trace" style={{ marginTop: 8 }}>
            <summary>show the query</summary>
            <pre>{cypher}</pre>
          </details>
        )}
      </div>

      <div className="pane-body tight">
        {!rows?.length && <div className="empty">Nothing matched.</div>}
        {(rows || []).map((row, index) => (
          <ResultRow
            key={row.key || row.id || index}
            row={row}
            onOpen={onOpen}
            onHalo={onHalo}
            onFocus={onFocus}
          />
        ))}
      </div>
    </>
  );
}

function ResultRow({ row, onOpen, onHalo, onFocus }) {
  // Two shapes reach here: a message hit from `search_messages`, and a raw Cypher
  // row. Both are rendered defensively — a Cypher row is whatever the user asked for.
  const key = row.key || row.id || row.thread_key;
  const snippet = row.snippet || row.body || row.label || row.title || key;
  const platform = row.platform || "";
  const threadKey = row.thread_key || (row.platform && row.chat_id
    ? `${row.platform}:${row.chat_id}`
    : null);

  const target = row.thread_key || row.type === "Thread" ? "Thread" : null;

  const handle = () => {
    // A result row sets BOTH halo and fly-to (UI-Cytoscape.md §10).
    if (key) onHalo?.(key);
    if (key) onFocus?.(key);

    if (row.kind === "thread" || row.type === "Thread") {
      onOpen?.({
        kind: "node",
        nodeType: "Thread",
        id: row.key || row.id,
        label: row.label || row.title || row.key,
        platform,
      });
      return;
    }
    if (threadKey) {
      onOpen?.({
        kind: "node",
        nodeType: "Thread",
        id: threadKey,
        label: row.thread_title || threadKey,
        platform,
      });
      return;
    }
    if (row.key) {
      onOpen?.({
        kind: "node",
        nodeType: "Message",
        id: row.key,
        label: row.sender_name || row.key,
        platform,
      });
    }
  };

  return (
    <button className="result-row" onClick={handle}>
      <div className="result-snippet">{snippet}</div>
      <div className="result-meta">
        {platformLabel(platform)}
        {row.ts_utc ? ` · ${formatDateTime(row.ts_utc)}` : ""}
        {row.sender_name ? ` · ${row.sender_name}` : ""}
        {row.is_self ? " · you" : ""}
        {target ? "" : ""}
      </div>
    </button>
  );
}

/* ----------------------------------------------------------------- thread */

function ThreadView({ entry, onOpen }) {
  const [data, setData] = useState(null);
  const [messages, setMessages] = useState([]);
  const [total, setTotal] = useState(0);
  const [query, setQuery] = useState("");
  const [histogram, setHistogram] = useState(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [error, setError] = useState(null);

  const scrollRef = useRef(null);
  // Rows fetched but not yet shown, and how far into the thread we have read.
  const buffer = useRef([]);
  const cursor = useRef(0);
  const exhausted = useRef(false);
  const busy = useRef(false);
  // How many view loads have been shown, and the message count at each boundary.
  // `marks[i]` is the index in `messages` where load `i` began — that is what makes
  // "previous page" a real step rather than a scroll-to-top.
  const marks = useRef([0]);
  const [page, setPage] = useState(0);

  /** Pull one server page into the buffer. */
  const fetchPage = useCallback(
    async (nextQuery) => {
      const page = await api.thread(entry.id, {
        skip: cursor.current,
        limit: FETCH,
        q: nextQuery || null,
      });
      setData(page.thread);
      setTotal(page.total);
      setHasMore(page.has_more);
      cursor.current += page.messages.length;
      buffer.current.push(...page.messages);
      if (!page.has_more) exhausted.current = true;
    },
    [entry.id],
  );

  /**
   * Show the next view load: consume buffered rows until the character budget is
   * spent, fetching more if the buffer runs dry. Always shows at least one message,
   * so a single very long body is a load of its own rather than an empty pane.
   */
  const fill = useCallback(
    async (nextQuery, { append = false } = {}) => {
      if (busy.current) return;
      busy.current = true;
      if (append) setLoadingMore(true);
      else setLoading(true);
      setError(null);

      try {
        const batch = [];
        let chars = 0;

        while (chars < CHAR_BUDGET) {
          if (!buffer.current.length) {
            if (exhausted.current) break;
            await fetchPage(nextQuery);
            if (!buffer.current.length) break;
          }
          const message = buffer.current.shift();
          batch.push(message);
          chars += (message.body || "").length;
          if (batch.length >= MIN_PER_LOAD && chars >= CHAR_BUDGET) break;
        }

        if (append) {
          setMessages((prev) => {
            marks.current.push(prev.length);
            return [...prev, ...batch];
          });
          setPage((value) => value + 1);
        } else {
          marks.current = [0];
          setPage(0);
          setMessages(batch);
        }
      } catch (err) {
        setError(err.message);
      } finally {
        busy.current = false;
        setLoading(false);
        setLoadingMore(false);
      }
    },
    [fetchPage],
  );

  /** Start over: clear the buffer, the cursor and the pane. */
  const restart = useCallback(
    (nextQuery) => {
      buffer.current = [];
      cursor.current = 0;
      exhausted.current = false;
      marks.current = [0];
      setPage(0);
      setMessages([]);
      fill(nextQuery, { append: false });
    },
    [fill],
  );

  // A different thread is a different conversation: reset everything.
  useEffect(() => {
    setQuery("");
    setHistogram(null);
    setData(null);
    restart("");
  }, [restart]);

  // The monthly histogram is one cheap aggregate, and it is what makes the arc
  // ("worked together → went quiet") a fact rather than a caption.
  useEffect(() => {
    let cancelled = false;
    api
      .search({
        mode: "cypher",
        query:
          "MATCH (t:Thread {key: $k})<-[:IN]-(m:Message) " +
          "RETURN substring(m.ts_utc, 0, 7) AS month, count(m) AS n ORDER BY month",
        params: { k: entry.id },
        limit: 500,
      })
      .then((result) => {
        if (!cancelled) setHistogram(result.rows || []);
      })
      .catch(() => {
        if (!cancelled) setHistogram(null);
      });
    return () => {
      cancelled = true;
    };
  }, [entry.id]);

  const runSearch = (value) => {
    setQuery(value);
    restart(value);
  };

  const loadMore = () => fill(query, { append: true });

  /**
   * Step back one view load.
   *
   * The rows are already in `messages`, so this is a pure slice — no request, no
   * cursor movement. That is what makes it a page step rather than a re-query, and
   * it is why the buffer is never rewound: going forward again re-shows what was
   * already fetched.
   */
  const previousPage = () => {
    if (page === 0) return;
    // `marks[page]` is where the current load began, so slicing to it drops exactly
    // the last load and leaves the earlier ones intact.
    const end = marks.current[page];
    setMessages((prev) => prev.slice(0, end));
    setPage((value) => value - 1);
    scrollRef.current?.scrollTo({ top: 0 });
  };

  // Scrolling near the bottom loads the next view load. The button stays as the
  // explicit path — a scroll handler alone is unusable with a trackpad that
  // overshoots, and it is the only way to page with the keyboard.
  const onScroll = () => {
    const node = scrollRef.current;
    if (!node || loadingMore || loading) return;
    const remaining = node.scrollHeight - node.scrollTop - node.clientHeight;
    if (remaining < 240) loadMore();
  };

  const thread = data || {
    title: entry.label,
    platform: entry.platform,
    correspondents: [],
    message_count: entry.messageCount,
  };

  return (
    <>
      <div className="viewer-head">
        <h1 className="viewer-title">{thread.title || entry.label}</h1>
        <div className="viewer-sub">
          <span className="pill kind">Thread</span>
          <span className="pill platform" style={{ color: platformColor(thread.platform) }}>
            {platformLabel(thread.platform)}
          </span>
          {thread.is_group && <span className="pill">group</span>}
          <span>{formatCount(thread.message_count ?? total)} messages</span>
          {thread.correspondents?.length > 0 && (
            <span>{thread.correspondents.slice(0, 3).join(", ")}</span>
          )}
        </div>
        <Arc thread={thread} histogram={histogram} />
      </div>

      <div className="thread-search">
        <input
          type="search"
          placeholder="Search inside this thread…"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") runSearch(event.target.value.trim());
            if (event.key === "Escape") {
              setQuery("");
              runSearch("");
            }
          }}
        />
      </div>

      <div className="pane-body tight thread-body" ref={scrollRef} onScroll={onScroll}>
        {loading && <div className="empty">Loading…</div>}
        {error && <div className="error">{error}</div>}
        {!loading && !error && !messages.length && (
          <div className="empty">
            {query ? "No message in this thread matches." : "This thread has no messages."}
          </div>
        )}
        {messages.map((message, index) => (
          <MessageRow
            key={message.key}
            message={message}
            first={index === 0}
            onOpen={() =>
              onOpen?.({
                kind: "node",
                nodeType: "Message",
                id: message.key,
                label: message.sender_name,
                platform: thread.platform,
              })
            }
          />
        ))}
        {loadingMore && (
          <div className="empty" style={{ padding: "10px 0" }}>
            <Loader2 size={13} className="spin" /> loading…
          </div>
        )}
      </div>

      <div className="pager">
        <span className="pager-info">
          {formatCount(messages.length)} of {formatCount(total)}
          {query ? " matching" : ""}
          {marks.current.length > 1 && ` · page ${page + 1}/${marks.current.length}`}
        </span>
        <div style={{ display: "flex", gap: 6 }}>
          <button
            className="ghost"
            onClick={previousPage}
            disabled={loading || page === 0}
            title="Previous page"
          >
            <ArrowLeft size={13} /> Newer
          </button>
          <button onClick={loadMore} disabled={!hasMore || loadingMore} title="Next page">
            {loadingMore ? <Loader2 size={13} className="spin" /> : <ArrowRight size={13} />}
            Older
          </button>
        </div>
      </div>
    </>
  );
}

function MessageRow({ message, onOpen, first }) {
  const isKind = message.raw_kind && message.raw_kind !== "text";
  const body = message.body || (isKind ? `(${message.raw_kind})` : "(empty)");

  return (
    <div className={`msg${first ? " first" : ""}`}>
      {/* A thin meta line per message: who, when, and what kind. It sits ABOVE the
          body so a run of short replies reads as a list of attributed lines rather
          than an unattributed wall. */}
      <div className="msg-who">
        <span className={`name${message.is_self ? " self" : ""}`}>
          {message.is_self ? "you" : message.sender_name || "unknown"}
        </span>
        <span className="when">{formatDateTime(message.ts_utc)}</span>
        {isKind && <span className="pill">{message.raw_kind}</span>}
      </div>
      <div
        className={`msg-body${isKind && !message.body ? " kind" : ""}`}
        onClick={onOpen}
        style={{ cursor: "pointer" }}
        title="Open this message"
      >
        {body}
      </div>
      {message.attachments?.length > 0 && (
        <div className="msg-attach">
          {message.attachments.map((attachment) => (
            <div key={attachment.key}>
              📎 {attachment.path || attachment.key}
              {attachment.mime ? ` · ${attachment.mime}` : ""}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * The arc, from the graph — not a caption written by hand.
 *
 * The sparkline is the monthly histogram. The text line that used to sit above it
 * (`first … · N months · quiet for …`) is gone: the thread title now carries the
 * person and the date range, so the line repeated it. The hover and the dates below
 * the sparkline stay.
 */
function Arc({ thread, histogram }) {
  if (!thread.first_ts && !thread.last_ts) return null;
  if (!histogram?.length) return null;
  return <Sparkline rows={histogram} />;
}

function Sparkline({ rows }) {
  const series = useMemo(() => {
    const map = new Map(rows.map((row) => [row.month, row.n]));
    const keys = [...map.keys()].sort();
    if (!keys.length) return [];
    // Fill the gaps: a month with no messages is information, not a missing bar.
    const [startYear, startMonth] = keys[0].split("-").map(Number);
    const [endYear, endMonth] = keys[keys.length - 1].split("-").map(Number);
    const out = [];
    let year = startYear;
    let month = startMonth;
    let guard = 0;
    while ((year < endYear || (year === endYear && month <= endMonth)) && guard < 400) {
      const key = `${year}-${String(month).padStart(2, "0")}`;
      out.push({ key, n: map.get(key) || 0 });
      month += 1;
      if (month > 12) {
        month = 1;
        year += 1;
      }
      guard += 1;
    }
    return out;
  }, [rows]);

  if (!series.length) return null;
  const max = Math.max(...series.map((point) => point.n), 1);

  return (
    <>
      <div className="spark" title="messages per month">
        {series.map((point) => (
          <div
            key={point.key}
            className={`spark-bar${point.n === 0 ? " empty" : ""}`}
            style={{ height: `${Math.max(2, (point.n / max) * 100)}%` }}
            title={`${monthLabel(`${point.key}-01`)}: ${point.n}`}
          />
        ))}
      </div>
      <div className="spark-axis">
        <span>{monthLabel(`${series[0].key}-01`)}</span>
        <span>{monthLabel(`${series[series.length - 1].key}-01`)}</span>
      </div>
    </>
  );
}

/* ---------------------------------------------------------- correspondent */

function CorrespondentView({ entry, onOpen }) {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setRows(null);
    setError(null);
    api
      .search({
        mode: "cypher",
        query:
          "MATCH (t:Thread)-[:WITH]->(c:Correspondent {key: $k}) " +
          "OPTIONAL MATCH (t)<-[:IN]-(m:Message) " +
          "RETURN t.key AS key, t.title AS label, t.platform AS platform, " +
          "       count(m) AS n, max(m.ts_utc) AS last_ts " +
          "ORDER BY last_ts DESC",
        params: { k: entry.id },
        limit: 200,
      })
      .then((result) => {
        if (!cancelled) setRows(result.rows || []);
      })
      .catch((err) => {
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, [entry.id]);

  return (
    <>
      <div className="viewer-head">
        <h1 className="viewer-title">{entry.label}</h1>
        <div className="viewer-sub">
          <span className="pill kind">Correspondent</span>
          {/* One pill per platform the node spans, each in its own colour.

              **Not `entry.platform`.** That is the single string used by the source
              filter (first platform by date), so a node on four platforms rendered one
              pill and looked identical to a one-platform node — the bug this fixes.
              `entry.platforms` is the full list the API already returns; the fallback
              covers a node written before the list existed. */}
          {platformsOf(entry).map((platform) => (
            <span
              key={platform}
              className="pill platform"
              style={{ color: platformColor(platform) }}
              title={`Seen on ${platformLabel(platform)}`}
            >
              {platformLabel(platform)}
            </span>
          ))}
          {entry.merged && <span className="pill merged">Merged</span>}
          {isPlaceholder(entry.label) && <span className="pill">placeholder account</span>}
        </div>

      </div>

      <div className="pane-body tight">
        {error && <div className="error">{error}</div>}
        {!rows && !error && <div className="empty">Loading…</div>}
        {rows?.length === 0 && <div className="empty">No threads for this correspondent.</div>}
        {(rows || []).map((row) => (
          <button
            key={row.key}
            className="result-row"
            onClick={() =>
              onOpen?.({
                kind: "node",
                nodeType: "Thread",
                id: row.key,
                label: row.label,
                platform: row.platform,
              })
            }
          >
            <div className="result-snippet">{row.label || row.key}</div>
            <div className="result-meta">
              {formatCount(row.n)} messages
              {row.last_ts ? ` · last ${formatDate(row.last_ts)}` : ""}
            </div>
          </button>
        ))}
      </div>
    </>
  );
}

/* ------------------------------------------------------------------ entity */

/**
 * Person / Place / Organization / Product — a name found in a message body.
 *
 * These hold zero rows until body-entity extraction lands, so the thread list is
 * usually empty. The query is written anyway: it is the same `MENTIONS` edge the
 * canvas draws, and it starts working the moment the writer exists.
 */
function EntityView({ entry, onOpen }) {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);
  const meta = NODE_TYPES[entry.nodeType] || {};

  useEffect(() => {
    let cancelled = false;
    setRows(null);
    setError(null);
    api
      .search({
        mode: "cypher",
        query:
          "MATCH (t:Thread)-[:MENTIONS]->(e {key: $k}) " +
          "OPTIONAL MATCH (t)<-[:IN]-(m:Message) " +
          "RETURN t.key AS key, t.title AS label, t.platform AS platform, " +
          "       count(m) AS n, max(m.ts_utc) AS last_ts " +
          "ORDER BY last_ts DESC",
        params: { k: entry.id },
        limit: 200,
      })
      .then((result) => {
        if (!cancelled) setRows(result.rows || []);
      })
      .catch((err) => {
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, [entry.id]);

  return (
    <>
      <div className="viewer-head">
        <h1 className="viewer-title">{entry.label}</h1>
        <div className="viewer-sub">
          <span className="pill kind">{meta.label || entry.nodeType}</span>
          {/* Same rule as `CorrespondentView`: the list, never the single string. */}
          {platformsOf(entry).map((platform) => (
            <span
              key={platform}
              className="pill platform"
              style={{ color: platformColor(platform) }}
              title={`Seen on ${platformLabel(platform)}`}
            >
              {platformLabel(platform)}
            </span>
          ))}
          {entry.merged && <span className="pill merged">Merged</span>}
        </div>
      </div>

      <div className="pane-body tight">
        {error && <div className="error">{error}</div>}
        {!rows && !error && <div className="empty">Loading…</div>}
        {rows?.length === 0 && (
          <div className="empty">
            No threads mention this {String(meta.label || "entity").toLowerCase()}.
          </div>
        )}
        {(rows || []).map((row) => (
          <button
            key={row.key}
            className="result-row"
            onClick={() =>
              onOpen?.({
                kind: "node",
                nodeType: "Thread",
                id: row.key,
                label: row.label,
                platform: row.platform,
              })
            }
          >
            <div className="result-snippet">{row.label || row.key}</div>
            <div className="result-meta">
              {formatCount(row.n)} messages
              {row.last_ts ? ` · last ${formatDate(row.last_ts)}` : ""}
            </div>
          </button>
        ))}
      </div>
    </>
  );
}

/* ----------------------------------------------------------------- message */

function MessageView({ entry, onOpen }) {
  const [message, setMessage] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setMessage(null);
    setError(null);
    api
      .message(entry.id)
      .then((result) => {
        if (!cancelled) setMessage(result);
      })
      .catch((err) => {
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, [entry.id]);

  return (
    <>
      <div className="viewer-head">
        <h1 className="viewer-title">{message?.thread_title || entry.label || "Message"}</h1>
        <div className="viewer-sub">
          {message && (
            <>
              <span className="pill kind">Message</span>
              <span className="pill platform" style={{ color: platformColor(message.platform) }}>
                {platformLabel(message.platform)}
              </span>
              <span>{formatDateTime(message.ts_utc)}</span>
              <span>{message.is_self ? "you" : message.sender_name || "unknown"}</span>
            </>
          )}
        </div>
      </div>

      <div className="pane-body">
        {error && <div className="error">{error}</div>}
        {!message && !error && <div className="empty">Loading…</div>}
        {message && (
          <>
            {message.reply_to && (
              <div className="trace" style={{ marginBottom: 10 }}>
                <div style={{ color: "var(--muted)" }}>
                  <CornerDownRight size={11} /> replying to {message.reply_to.sender_name}
                </div>
                <div style={{ marginTop: 3 }}>{message.reply_to.body}</div>
              </div>
            )}
            <div className="msg-body">{message.body || `(${message.raw_kind})`}</div>
            {message.attachments?.length > 0 && (
              <div className="msg-attach" style={{ marginTop: 10 }}>
                {message.attachments.map((attachment) => (
                  <div key={attachment.key}>
                    📎 {attachment.path || attachment.key}
                    {attachment.mime ? ` · ${attachment.mime}` : ""}
                  </div>
                ))}
              </div>
            )}
            {message.thread_key && (
              <button
                className="ghost"
                style={{ marginTop: 14 }}
                onClick={() =>
                  onOpen?.({
                    kind: "node",
                    nodeType: "Thread",
                    id: message.thread_key,
                    label: message.thread_title,
                    platform: message.platform,
                  })
                }
              >
                <Search size={13} /> open the whole thread
              </button>
            )}
          </>
        )}
      </div>
    </>
  );
}
