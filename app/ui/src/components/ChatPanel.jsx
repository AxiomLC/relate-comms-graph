import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2, Send, Trash2 } from "lucide-react";

import { api } from "../lib/api.js";

/**
 * The AI chat: local Ollama, tools from `relate_comms.tools`, history in the browser.
 *
 * Three rules from UI-Cytoscape.md §9, all of them load-bearing:
 *
 *  1. **History lives in `localStorage`.** Ollama is stateless, so the transcript is
 *     sent with every request. A refresh keeps the whole conversation.
 *  2. **`think: false` is sent by the server**, not here — the model writes
 *     `<think​>` blocks into `content` anyway and the server strips them.
 *  3. **The chat sees the whole store.** The node the user is looking at is passed
 *     as an explicit *hint* in the prompt, never as a filter. A hidden UI state must
 *     not narrow what an agent can query.
 */

const SESSION_KEY = "relate.chat.session";
const TRANSCRIPT_KEY = "relate.chat.transcript";

function newSessionId() {
  return `s-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

function loadTranscript() {
  try {
    const raw = localStorage.getItem(TRANSCRIPT_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export default function ChatPanel({
  theme,
  context,
  onResults,
  onActivity,
  expanded,
  onToggleExpand,
}) {
  const [transcript, setTranscript] = useState(loadTranscript);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [health, setHealth] = useState(null);
  const bodyRef = useRef(null);

  // Ask Ollama once on mount. A false `ok` disables the box and says why — the
  // rest of the app keeps working, which is the point of the check.
  useEffect(() => {
    let cancelled = false;
    api
      .chatHealth()
      .then((result) => {
        if (!cancelled) setHealth(result);
      })
      .catch((err) => {
        if (!cancelled) setHealth({ ok: false, error: err.message });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!localStorage.getItem(SESSION_KEY)) {
      localStorage.setItem(SESSION_KEY, newSessionId());
    }
  }, []);

  useEffect(() => {
    try {
      const trimmed = transcript.slice(-theme.chat.maxTranscript);
      localStorage.setItem(TRANSCRIPT_KEY, JSON.stringify(trimmed));
    } catch {
      /* quota — the conversation just does not persist */
    }
  }, [transcript, theme.chat.maxTranscript]);

  useEffect(() => {
    bodyRef.current?.scrollTo({ top: bodyRef.current.scrollHeight, behavior: "smooth" });
  }, [transcript, busy]);

  const send = useCallback(async () => {
    const text = input.trim();
    if (!text || busy) return;

    setBusy(true);
    setError(null);
    setInput("");

    // **The user's turn lands immediately.** Waiting for the reply to append both
    // meant the box showed "thinking…" with no sign of what was asked — on a CPU
    // model that is several seconds of apparent amnesia.
    setTranscript((prev) => [...prev, { role: "user", content: text }]);

    // The hint is explicit and additive. It is never a filter.
    const hint = context?.label
      ? `\n\n[The user is currently looking at ${context.nodeType || "node"} ` +
        `"${context.label}". This is context, not a filter — answer from the whole store.]`
      : "";

    const history = transcript.map((turn) => ({ role: turn.role, content: turn.content }));
    const started = performance.now();

    try {
      const result = await api.chat({ message: text + hint, messages: history });

      // One row per tool the model actually called, so the trace names the surface
      // and the tool rather than saying "chat happened".
      for (const call of result.tool_calls || []) {
        onActivity?.({
          source: "chat",
          text: `${call.name}(${JSON.stringify(call.args || {})})`,
        });
      }
      onActivity?.({
        source: "chat",
        text: `reply · ${(result.tool_calls || []).length} tool call(s)`,
        ms: performance.now() - started,
      });

      // The user turn is already in the transcript (appended before the request).
      setTranscript((prev) => [
        ...prev,
        {
          role: "assistant",
          content: result.reply,
          toolCalls: result.tool_calls || [],
          model: result.model,
        },
      ]);

      // If a tool returned message hits, land them in the Viewer's results state.
      const hits = collectHits(result.tool_calls || []);
      if (hits.length) {
        onResults?.({
          kind: "results",
          mode: "chat",
          query: text,
          rows: hits,
          count: hits.length,
          truncated: false,
        });
      }
    } catch (err) {
      onActivity?.({
        source: "chat",
        text: `failed: ${err.message}`,
        ms: performance.now() - started,
        status: "error",
      });
      setError(err.message);
      // The user turn is already shown; nothing to re-append.
    } finally {
      setBusy(false);
    }
  }, [input, busy, transcript, context, onResults, onActivity]);

  const clear = () => {
    setTranscript([]);
    setError(null);
    localStorage.setItem(SESSION_KEY, newSessionId());
  };

  const disabled = health && !health.ok;

  return (
    <>
      <div className="pane-header">
        <span className="pane-title">AI</span>
        <span className="pill" title={health?.host || ""}>
          {health?.ok ? health.model : disabled ? "offline" : "…"}
        </span>
        <div style={{ marginLeft: "auto", display: "flex", gap: 4 }}>
          <button className="ghost icon" onClick={clear} title="Clear the transcript">
            <Trash2 size={13} />
          </button>
          <button
            className="ghost icon"
            onClick={onToggleExpand}
            title={expanded ? "Narrow" : "Widen"}
          >
            ⛶
          </button>
        </div>
      </div>

      <div className="chat-body" ref={bodyRef}>
        {disabled && (
          <div className="error">
            Ollama is not reachable at {health.host || "127.0.0.1:11434"}.
            <br />
            Start it with <code>ollama serve</code>. The graph works without it.
          </div>
        )}

        {!transcript.length && !disabled && (
          <div className="empty">
            Ask about your own messages. The model runs on this machine and sees the
            whole store.
            <br />
            <br />
            <em>“how many messages do I have?”</em>
            <br />
            <em>“find messages about the invoice”</em>
            <br />
            <em>“show me the conversation with David”</em>
          </div>
        )}

        {transcript.map((turn, index) => (
          <div key={index} className={`turn ${turn.role}`}>
            <div className="bubble">{turn.content}</div>
            {turn.toolCalls?.length > 0 && (
              <details className="trace">
                <summary>
                  {turn.toolCalls.length} tool call
                  {turn.toolCalls.length === 1 ? "" : "s"}
                  {/* The model that answered **this** turn. A transcript persisted
                      before a model swap keeps the old name on old turns, which is
                      accurate — but it reads as a bug, so the live model is shown
                      beside it when they differ. */}
                  {turn.model && turn.model !== health?.model
                    ? ` · ${turn.model} (then)`
                    : turn.model
                      ? ` · ${turn.model}`
                      : ""}
                </summary>
                {turn.toolCalls.map((call, callIndex) => (
                  <pre key={callIndex}>
                    {call.name}({JSON.stringify(call.args)})
                    {"\n"}
                    {JSON.stringify(call.result).slice(0, 600)}
                  </pre>
                ))}
              </details>
            )}
          </div>
        ))}

        {busy && (
          <div className="turn assistant">
            <div className="bubble">
              <Loader2 size={13} className="spin" /> thinking…
            </div>
          </div>
        )}

        {error && <div className="error">{error}</div>}
      </div>

      <div className="chat-input">
        <textarea
          rows={1}
          placeholder={disabled ? "Ollama is offline" : "Ask…"}
          value={input}
          disabled={disabled || busy}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              send();
            }
          }}
        />
        <button onClick={send} disabled={disabled || busy || !input.trim()}>
          <Send size={13} />
        </button>
      </div>
    </>
  );
}

/**
 * Pull message-shaped rows out of a tool trace so the Viewer can show them.
 *
 * Only `search_messages` and `run_cypher` can produce rows worth rendering; a
 * count or a thread arc is already in the reply text.
 */
function collectHits(toolCalls) {
  const hits = [];
  for (const call of toolCalls) {
    const result = call.result;
    if (!result || typeof result !== "object") continue;
    if (Array.isArray(result.hits)) hits.push(...result.hits);
    else if (Array.isArray(result.rows) && call.name === "run_cypher") {
      hits.push(...result.rows.filter((row) => row && (row.key || row.id)));
    }
  }
  return hits;
}
