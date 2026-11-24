import { useEffect, useRef, useState } from "react";
import "./App.css";

const API_URL = (import.meta.env.VITE_API_URL || "http://localhost:8000").replace(/\/$/, "");

const FAILURE_OPTIONS = [
  { label: "No simulated failure", value: "" },
  { label: "key_1 fails with 429", value: "key_1=429" },
  { label: "key_1 fails with 500", value: "key_1=500" },
  { label: "key_1 = 429 and key_2 = 500", value: "key_1=429,key_2=500" },
  { label: "All keys fail with 429", value: "*=429" },
];

function newSessionId() {
  const rand =
    typeof crypto !== "undefined" && crypto.randomUUID
      ? crypto.randomUUID().replace(/-/g, "").slice(0, 8)
      : Math.random().toString(36).slice(2, 10);
  return `s-${rand}`;
}

function errorText(status, body) {
  const detail = body && body.detail;
  if (Array.isArray(detail)) {
    return "Invalid request: " + detail.map((d) => d.msg).join("; ");
  }
  if (status === 503) {
    return "All AI providers are unavailable right now. Please try again in a moment.";
  }
  if (typeof detail === "string") return detail;
  return `Something went wrong (HTTP ${status}). Please try again.`;
}

function Meta({ meta }) {
  const fromCache = meta.resolution_source === "LLM_CACHE";
  return (
    <div className="meta">
      <span
        className={`badge ${fromCache ? "badge-cache" : "badge-live"}`}
        data-testid="meta-source"
      >
        {meta.resolution_source}
      </span>
      {meta.fallback_attempts > 0 && (
        <span className="badge badge-fallback">
          fallback used ({meta.fallback_attempts} failed)
        </span>
      )}
      <span className="chip">
        <span className="chip-label">Model</span>
        <span data-testid="meta-model">{meta.model}</span>
      </span>
      <span className="chip">
        <span className="chip-label">Latency</span>
        <span data-testid="meta-latency">{meta.latency_ms} ms</span>
      </span>
      <span className="chip">
        <span className="chip-label">Input tokens</span>
        <span data-testid="meta-input-tokens">{meta.input_tokens}</span>
      </span>
      <span className="chip">
        <span className="chip-label">Output tokens</span>
        <span data-testid="meta-output-tokens">{meta.output_tokens}</span>
      </span>
      <span className="chip">
        <span className="chip-label">Key</span>
        <span data-testid="meta-key">{meta.key_id ?? "none"}</span>
      </span>
    </div>
  );
}

export default function App() {
  const [sessionId, setSessionId] = useState(newSessionId);
  const [items, setItems] = useState([]);
  const [input, setInput] = useState("");
  const [systemPrompt, setSystemPrompt] = useState("");
  const [failure, setFailure] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [items, loading]);

  async function send() {
    if (loading) return;
    const message = input.trim();
    setInput("");
    setItems((prev) => [...prev, { kind: "user", text: message || "(empty message)" }]);
    setLoading(true);

    const headers = { "Content-Type": "application/json" };
    if (failure) headers["X-Simulate-Failure"] = failure;
    const body = { session_id: sessionId, message };
    if (systemPrompt.trim()) body.system_prompt = systemPrompt.trim();

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 120000);
    try {
      const res = await fetch(`${API_URL}/chat`, {
        method: "POST",
        headers,
        body: JSON.stringify(body),
        signal: controller.signal,
      });
      let data = null;
      try {
        data = await res.json();
      } catch {
        data = null;
      }
      if (res.ok && data) {
        setItems((prev) => [...prev, { kind: "assistant", text: data.reply, meta: data.metadata }]);
      } else {
        setItems((prev) => [...prev, { kind: "error", text: errorText(res.status, data) }]);
      }
    } catch (err) {
      const text =
        err.name === "AbortError"
          ? "The request took too long. Please try again."
          : "Cannot reach the server. Check your connection and try again.";
      setItems((prev) => [...prev, { kind: "error", text }]);
    } finally {
      clearTimeout(timer);
      setLoading(false);
    }
  }

  function onKeyDown(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  }

  function newChat() {
    setSessionId(newSessionId());
    setItems([]);
  }

  return (
    <div className="app">
      <div className="topbar">
        <div>
          <h1>LLM Chatbot</h1>
          <div className="session">Session: {sessionId}</div>
        </div>
        <button className="btn" onClick={newChat}>New chat</button>
      </div>

      <details className="settings">
        <summary>Session settings</summary>
        <label>
          System prompt (optional)
          <textarea
            data-testid="system-prompt-input"
            rows={2}
            value={systemPrompt}
            onChange={(e) => setSystemPrompt(e.target.value)}
            placeholder="e.g. Answer like a pirate."
          />
        </label>
        <label>
          Simulate failure (for demos)
          <select value={failure} onChange={(e) => setFailure(e.target.value)}>
            {FAILURE_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </label>
      </details>

      <div className="messages">
        {items.length === 0 && (
          <div className="empty">Send a message to start the conversation.</div>
        )}
        {items.map((item, i) => {
          if (item.kind === "user") {
            return <div key={i} className="bubble user">{item.text}</div>;
          }
          if (item.kind === "error") {
            return <div key={i} className="bubble error" role="alert">{item.text}</div>;
          }
          return (
            <div key={i} className="bubble assistant" data-testid="assistant-message">
              <div className="reply">{item.text}</div>
              <Meta meta={item.meta} />
            </div>
          );
        })}
        {loading && <div className="typing">Thinking…</div>}
        <div ref={bottomRef} />
      </div>

      <div className="composer">
        <textarea
          data-testid="chat-input"
          rows={1}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Type a message and press Enter"
        />
        <button
          className="send"
          data-testid="send-button"
          onClick={send}
          disabled={loading}
        >
          Send
        </button>
      </div>
    </div>
  );
}