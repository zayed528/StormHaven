// Chat with the StormHaven assistant via /api/chat.   Owner: Nandan (UI)
// Floating: a robot button in the bottom-right corner opens/closes the chat window.
// The backend answers offline (deterministic) when Bedrock isn't configured, so this always works.
// Suggested questions = the 4 challenge questions. Assistant text is labeled AI-generated; the fixed 911 message is shown apart.
// Visible text comes from i18n.js (t).
import React, { useEffect, useRef, useState } from "react";
import { sendChat } from "../api/client.js";
import { SAFETY_911_EN } from "../translateEs.js";

// The backend prepends a fixed (not AI-written) 911 message that starts with this.
const SAFETY_PREFIX = "SAFETY:";
// The backend's emergency check is English-only, so Spanish emergencies are also caught here and get the
// same fixed message (never AI-written). Deliberately broad, like the backend: a false alarm costs one line.
const ES_EMERGENCY = /\b(cables?|l[ií]neas?)\s+(el[eé]ctric[oa]s?\s+)?(ca[ií]d[oa]s?|en el suelo)|chispa|fuego|incendio|humo|descarga|electrocut|emergencia|\b911\b|no puedo respirar/i;

// One assistant bubble: the fixed safety message (if any) shown separately, then the labeled AI text.
// Text is shown through t.tr (Spanish when the UI is Spanish); the original English stays in history for the backend.
function AssistantMsg({ t, text }) {
  const [safety, rest] = text.startsWith(SAFETY_PREFIX) ? text.split("\n\n", 2) : [null, text];
  return (
    <div className="assistant">
      {safety && <p className="chat-safety" role="alert">
        <strong>{t.safetyMessage}</strong> {t.tr(safety.slice(SAFETY_PREFIX.length).trim())}</p>}
      <span className="ai-tag">{t.aiLabel}</span>
      <p>{t.tr(rest)}</p>
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

export default function ChatPanel({ t, premiseId, scenario, profile }) {
  const [history, setHistory] = useState([]);       // Bedrock Converse shape
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);
  const [needHome, setNeedHome] = useState(false);  // true = they tried to ask before picking a home
  const logRef = useRef(null);
  const inputRef = useRef(null);
  const closeRef = useRef(null);
  const launcherRef = useRef(null);

  // Keep the newest message (or the "thinking" line) in view, including right after the window opens.
  useEffect(() => {
    const el = logRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [history, busy, open]);

  // On open, put keyboard focus in the question box.
  useEffect(() => { if (open) inputRef.current?.focus(); }, [open]);
  // Once a home is picked, drop the "pick your home first" nudge.
  useEffect(() => { if (premiseId) setNeedHome(false); }, [premiseId]);

  // Closing returns focus to the robot button so keyboard users don't get lost.
  const close = () => { setOpen(false); launcherRef.current?.focus(); };

  // Shared by the form and the suggested-question buttons. Sends the whole conversation; the backend is stateless.
  const ask = async (q) => {
    if (!q.trim() || busy) return;
    // Answers are about one location, so ask for it first (keeps the typed question for after).
    if (!premiseId) { setNeedHome(true); return; }
    const next = [...history, { role: "user", content: [{ text: q.trim() }] }];
    setHistory(next); setText(""); setBusy(true);
    try {
      let { reply } = await sendChat({ history: next, premise_id: premiseId, scenario, profile });
      if (!reply.startsWith(SAFETY_PREFIX) && ES_EMERGENCY.test(q)) reply = `${SAFETY_PREFIX} ${SAFETY_911_EN}\n\n${reply}`;
      setHistory([...next, { role: "assistant", content: [{ text: reply }] }]);
    } catch {
      setHistory([...next, { role: "assistant", content: [{ text: t.chatError }] }]);
    } finally { setBusy(false); }
  };
  const send = (e) => { e.preventDefault(); ask(text); };

  return (<>
    <button ref={launcherRef} type="button" className="chat-launcher" onClick={() => (open ? close() : setOpen(true))}
      aria-label={open ? t.chatClose : t.chatOpen} aria-expanded={open}
      aria-controls="chat-window" title={t.chatTitle}>
      <RobotIcon />
    </button>
    {/* Kept mounted while closed (just hidden) so the conversation survives closing the window. */}
    <section id="chat-window" className="chat" aria-label={t.chatTitle} hidden={!open}
      onKeyDown={(e) => { if (e.key === "Escape") close(); }}>
      <div className="chat-head">
        <h2>{t.chatTitle}</h2>
        <button ref={closeRef} type="button" className="chat-close" onClick={close} aria-label={t.chatCloseShort}>×</button>
      </div>
      {!premiseId && (
        <p className={`chat-hint${needHome ? " nudge" : ""}`} role={needHome ? "alert" : undefined}>
          {needHome ? t.chatHintNudge : ""}{t.chatHint}</p>)}
      <div className="chips" role="group" aria-label={t.suggestedAria}>
        {/* The 4 challenge questions; clicking one sends it like a typed question. */}
        {t.suggested.map((q) => (
          <button key={q} type="button" onClick={() => ask(q)} disabled={busy}>{q}</button>))}
      </div>
      <div className="chat-log" ref={logRef} aria-live="polite">
        {history.map((m, i) => m.role === "assistant"
          ? <AssistantMsg key={i} t={t} text={m.content[0].text} />
          : <p key={i} className="user">{m.content[0].text}</p>)}
        {busy && <p className="assistant typing" role="status">{t.thinking}</p>}
      </div>
      <form onSubmit={send}>
        <input ref={inputRef} value={text} onChange={(e) => setText(e.target.value)} placeholder={t.chatPlaceholder}
          aria-label={t.chatQuestion} />
        <button type="submit" disabled={busy}>{busy ? t.sending : t.send}</button>
      </form>
    </section>
  </>);
}
