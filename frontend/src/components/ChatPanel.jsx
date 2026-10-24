// Chat with StormHaven. The backend keeps all calculations deterministic and falls back safely without Bedrock.
import React, { useEffect, useRef, useState } from "react";
import { sendChat } from "../api/client.js";
import { boundedHistory, chatContextKey, createRequestGate } from "./chatState.js";

const SUGGESTIONS = [
  "Will I lose power?",
  "How long might restoration take?",
  "Why is my outage risk at this level?",
  "What should I do to prepare?",
  "What if 30 repair crews are available?",
];

export default function ChatPanel({ premiseId, scenario, profile, utilityStatus }) {
  const [history, setHistory] = useState([]);       // Bedrock Converse shape
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [failedHistory, setFailedHistory] = useState(null);
  const logRef = useRef(null);
  const gateRef = useRef(createRequestGate());
  const contextKey = chatContextKey(premiseId, scenario, profile, utilityStatus);
  const currentContextRef = useRef(contextKey);
  currentContextRef.current = contextKey;

  // A conversation belongs to one complete outage context, not only one premise.
  useEffect(() => {
    gateRef.current.invalidate();
    setHistory([]); setText(""); setBusy(false); setError(null); setFailedHistory(null);
    return () => gateRef.current.invalidate();
  }, [contextKey]);

  useEffect(() => {
    const log = logRef.current;
    if (log) log.scrollTop = log.scrollHeight;
  }, [history, busy, error]);

  const submitHistory = async (next) => {
    if (!premiseId) return;
    const token = gateRef.current.begin(contextKey);
    if (!token) return;
    const requestedPremise = premiseId;
    setHistory(next); setBusy(true); setError(null); setFailedHistory(null);
    try {
      const { reply } = await sendChat({
        history: next, premise_id: requestedPremise, scenario, profile, utility_status: utilityStatus,
      }, { signal: token.signal });
      if (gateRef.current.isCurrent(token, currentContextRef.current)) {
        setHistory([...next, { role: "assistant", content: [{ text: reply }] }]);
      }
    } catch (err) {
      if (err?.name !== "AbortError" && gateRef.current.isCurrent(token, currentContextRef.current)) {
        setError("I couldn't reach the assistant. Your question was not lost.");
        setFailedHistory(next);
      }
    } finally {
      if (gateRef.current.finish(token)) setBusy(false);
    }
  };

  const sendText = (value) => {
    const question = value.trim();
    if (!question || gateRef.current.isInFlight() || !premiseId) return;
    const next = boundedHistory(history, question);
    setText("");
    submitHistory(next);
  };

  const send = (e) => {
    e.preventDefault();
    sendText(text);
  };

  return (
    <section className="chat" aria-label="Ask StormHaven">
      <h2>Ask StormHaven</h2>
      <div className="chat-suggestions" aria-label="Suggested questions">
        {SUGGESTIONS.map((question) => (
          <button key={question} type="button" onClick={() => sendText(question)} disabled={!premiseId || busy}>
            {question}
          </button>
        ))}
      </div>
      <div className="chat-log" ref={logRef} aria-live="polite" aria-busy={busy}>
        {history.map((m, i) => <p key={i} className={m.role}>{m.content[0].text}</p>)}
        {busy && <p className="assistant chat-loading" role="status">Checking your current outage outlook…</p>}
      </div>
      {error && <div className="chat-error" role="alert">
        <span>{error}</span>
        <button type="button" onClick={() => submitHistory(failedHistory)} disabled={busy || !failedHistory}>Retry</button>
      </div>}
      <form onSubmit={send}>
        <input value={text} onChange={(e) => setText(e.target.value)} maxLength={1200} placeholder="e.g. Will I lose power?"
          aria-label="Your question" disabled={!premiseId} />
        <button type="submit" disabled={!premiseId || busy || !text.trim()}>{busy ? "Checking…" : "Send"}</button>
      </form>
      {!premiseId && <p className="muted">Select your home on the map first.</p>}
      <p className="muted">For privacy, don't enter names, addresses, account numbers, or medical details.</p>
    </section>
  );
}
