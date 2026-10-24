// Chat with the StormHaven assistant via /api/chat.   Owner: Nandan (UI)
// Floating: a robot button in the bottom-right corner opens/closes the chat window.
// The backend answers offline (deterministic) when Bedrock isn't configured, so this always works.
// Suggested questions = the 4 challenge questions. Assistant text is labeled AI-generated; the fixed 911 message is shown apart.
import React, { useEffect, useRef, useState } from "react";
import { sendChat } from "../api/client.js";

// The 4 challenge questions, word for word. Clicking one sends it like a typed question.
const SUGGESTED = ["Will I lose power?", "How long could restoration take?",
                   "What should I do to prepare?", "Do I qualify for outage alerts?"];
// The backend prepends a fixed (not AI-written) 911 message that starts with this.
const SAFETY_PREFIX = "SAFETY:";

// One assistant bubble: the fixed safety message (if any) shown separately, then the labeled AI text.
function AssistantMsg({ text }) {
  const [safety, rest] = text.startsWith(SAFETY_PREFIX) ? text.split("\n\n", 2) : [null, text];
  return (
    <div className="assistant">
      {safety && <p className="chat-safety" role="alert">
        <strong>Safety message:</strong> {safety.slice(SAFETY_PREFIX.length).trim()}</p>}
      <span className="ai-tag">AI-generated explanation</span>
      <p>{rest}</p>
    </div>
  );
}

// Robot icon for the launcher button (inline SVG: looks the same on every OS, unlike an emoji).
const RobotIcon = () => (
  <svg viewBox="0 0 24 24" width="30" height="30" aria-hidden="true" fill="none" stroke="currentColor"
    strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 3.5V6" /><circle cx="12" cy="2.5" r="1.2" fill="currentColor" stroke="none" />
    <rect x="4" y="6" width="16" height="12" rx="3" />
    <circle cx="9" cy="11.5" r="1.5" fill="currentColor" stroke="none" />
    <circle cx="15" cy="11.5" r="1.5" fill="currentColor" stroke="none" />
    <path d="M9.5 15h5" /><path d="M2 10.5v3M22 10.5v3" />
  </svg>
);

export default function ChatPanel({ premiseId, scenario, profile }) {
  const [history, setHistory] = useState([]);       // Bedrock Converse shape
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);
  const logRef = useRef(null);
  const inputRef = useRef(null);
  const closeRef = useRef(null);
  const launcherRef = useRef(null);

  // Keep the newest message (or the "thinking" line) in view, including right after the window opens.
  useEffect(() => {
    const el = logRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [history, busy, open]);

  // On open, put keyboard focus inside the window (the input, or Close if no home is selected yet).
  useEffect(() => {
    if (open) (premiseId ? inputRef : closeRef).current?.focus();
  }, [open]);   // eslint-disable-line react-hooks/exhaustive-deps

  // Closing returns focus to the robot button so keyboard users don't get lost.
  const close = () => { setOpen(false); launcherRef.current?.focus(); };

  // Shared by the form and the suggested-question buttons. Sends the whole conversation; the backend is stateless.
  const ask = async (q) => {
    if (!q.trim() || busy || !premiseId) return;
    const next = [...history, { role: "user", content: [{ text: q.trim() }] }];
    setHistory(next); setText(""); setBusy(true);
    try {
      const { reply } = await sendChat({ history: next, premise_id: premiseId, scenario, profile });
      setHistory([...next, { role: "assistant", content: [{ text: reply }] }]);
    } catch {
      setHistory([...next, { role: "assistant", content: [{ text: "Sorry, I couldn't reach the assistant. Check AEP's outage map." }] }]);
    } finally { setBusy(false); }
  };
  const send = (e) => { e.preventDefault(); ask(text); };

  return (<>
    <button ref={launcherRef} type="button" className="chat-launcher" onClick={() => (open ? close() : setOpen(true))}
      aria-label={open ? "Close StormHaven assistant" : "Open StormHaven assistant"} aria-expanded={open}
      aria-controls="chat-window" title="Ask StormHaven">
      <RobotIcon />
    </button>
    {/* Kept mounted while closed (just hidden) so the conversation survives closing the window. */}
    <section id="chat-window" className="chat" aria-label="Ask StormHaven" hidden={!open}
      onKeyDown={(e) => { if (e.key === "Escape") close(); }}>
      <div className="chat-head">
        <h2>Ask StormHaven</h2>
        <button ref={closeRef} type="button" className="chat-close" onClick={close} aria-label="Close assistant">×</button>
      </div>
      <div className="chips" role="group" aria-label="Suggested questions">
        {SUGGESTED.map((q) => (
          <button key={q} type="button" onClick={() => ask(q)} disabled={!premiseId || busy}>{q}</button>))}
      </div>
      <div className="chat-log" ref={logRef} aria-live="polite">
        {history.map((m, i) => m.role === "assistant"
          ? <AssistantMsg key={i} text={m.content[0].text} />
          : <p key={i} className="user">{m.content[0].text}</p>)}
        {busy && <p className="assistant typing" role="status">StormHaven is thinking…</p>}
      </div>
      <form onSubmit={send}>
        <input ref={inputRef} value={text} onChange={(e) => setText(e.target.value)} placeholder="e.g. Will I lose power?"
          aria-label="Your question" disabled={!premiseId} />
        <button type="submit" disabled={!premiseId || busy}>{busy ? "Sending…" : "Send"}</button>
      </form>
      {!premiseId && <p className="muted">Select your home on the map first.</p>}
    </section>
  </>);
}
