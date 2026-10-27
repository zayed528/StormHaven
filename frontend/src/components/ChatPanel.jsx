// Chat with StormHaven. Calculations remain deterministic; Bedrock is optional.
import React, { useEffect, useRef, useState } from "react";
import { sendChat } from "../api/client.js";
import { SAFETY_911_EN } from "../translateEs.js";
import { boundedHistory, chatContextKey, createRequestGate } from "./chatState.js";

const SAFETY_PREFIX = "SAFETY:";
const ES_EMERGENCY = /\b(cables?|l[ií]neas?)\s+(el[eé]ctric[oa]s?\s+)?(ca[ií]d[oa]s?|en el suelo)|chispa|fuego|incendio|humo|descarga|electrocut|emergencia|\b911\b|no puedo respirar/i;

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

const RISKY_BANDS = new Set(["Moderate", "High", "Very High"]);

// onNeeds(needs): tell the app about needs ticked here, so the answer cards, alerts and texts use them too.
// risk = {band, probability, range} of the answer on screen (for the hardcoded PS5 reply), or null.
export default function ChatPanel({ t, premiseId, scenario, profile, utilityStatus, onNeeds = () => {}, risk = null }) {
  const [history, setHistory] = useState([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);
  const [needHome, setNeedHome] = useState(false);
  const [error, setError] = useState(null);
  const [failedRequest, setFailedRequest] = useState(null);
  const [preparationNeeds, setPreparationNeeds] = useState(null);
  const [selectedPreparationNeeds, setSelectedPreparationNeeds] = useState([]);
  const logRef = useRef(null);
  const inputRef = useRef(null);
  const launcherRef = useRef(null);
  const gateRef = useRef(createRequestGate());
  // Declared needs are left out: ticking them here updates the app's profile, and that must not wipe this conversation.
  const contextKey = chatContextKey(premiseId, scenario, { ...profile, declared_needs: undefined }, utilityStatus);
  const currentContextRef = useRef(contextKey);
  currentContextRef.current = contextKey;
  const suggestions = profile.declared_needs?.length
    ? [...t.suggested, t.needsChatPrompt]
    : t.suggested;

  useEffect(() => {
    gateRef.current.invalidate();
    setHistory([]);
    setText("");
    setBusy(false);
    setError(null);
    setFailedRequest(null);
    setNeedHome(false);
    setPreparationNeeds(null);
    setSelectedPreparationNeeds([]);
    return () => gateRef.current.invalidate();
  }, [contextKey]);

  useEffect(() => {
    const el = logRef.current;
    if (!el) return undefined;
    // Wait one frame so the newest bubble has its final wrapped height before scrolling.
    const frame = requestAnimationFrame(() => { el.scrollTop = el.scrollHeight; });
    return () => cancelAnimationFrame(frame);
  }, [history, busy, error, open]);
  useEffect(() => { if (open) inputRef.current?.focus(); }, [open]);
  // Page load: the robot bounces twice, then says hi in a small bubble for a few seconds (gone as soon as the chat
  // opens). No bounce for people who turn animations off; they still get the bubble.
  const [intro, setIntro] = useState("bounce");    // "bounce" -> "bubble" -> null
  useEffect(() => {
    const still = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    const bounced = still ? 300 : 1700;            // 0.5 s pause + 2 bounces of 0.6 s (styles.css .intro-bounce)
    const toBubble = setTimeout(() => setIntro("bubble"), bounced);
    const done = setTimeout(() => setIntro(null), bounced + 8000);
    return () => { clearTimeout(toBubble); clearTimeout(done); };
  }, []);
  useEffect(() => { if (open) setIntro(null); }, [open]);
  // Phone app: the chat is a full-screen sheet sized to the VISIBLE part of the screen, so the on-screen keyboard
  // never covers the text box (iPhones shrink only the visual viewport when the keyboard opens). src/app/app.css
  // reads --chat-top / --chat-h; the web app ignores them.
  useEffect(() => {
    const vv = window.visualViewport;
    if (!open || !vv) return undefined;
    const root = document.documentElement.style;
    const fit = () => { root.setProperty("--chat-top", `${vv.offsetTop}px`); root.setProperty("--chat-h", `${vv.height}px`); };
    fit();
    vv.addEventListener("resize", fit);
    vv.addEventListener("scroll", fit);
    return () => { vv.removeEventListener("resize", fit); vv.removeEventListener("scroll", fit); };
  }, [open]);
  useEffect(() => { if (premiseId) setNeedHome(false); }, [premiseId]);

  const close = () => { setOpen(false); launcherRef.current?.focus(); };

  const submitHistory = async (next, question, requestProfile = profile) => {
    if (!premiseId) return;
    const token = gateRef.current.begin(contextKey);
    if (!token) return;
    const requestedPremise = premiseId;
    setHistory(next);
    setBusy(true);
    setError(null);
    setFailedRequest(null);
    try {
      let { reply } = await sendChat({
        history: next,
        premise_id: requestedPremise,
        scenario,
        profile: requestProfile,
        utility_status: utilityStatus,
      }, { signal: token.signal });
      if (!reply.startsWith(SAFETY_PREFIX) && ES_EMERGENCY.test(question)) {
        reply = `${SAFETY_PREFIX} ${SAFETY_911_EN}\n\n${reply}`;
      }
      if (gateRef.current.isCurrent(token, currentContextRef.current)) {
        setHistory([...next, { role: "assistant", content: [{ text: reply }] }]);
      }
    } catch (err) {
      if (err?.name !== "AbortError" && gateRef.current.isCurrent(token, currentContextRef.current)) {
        setError(t.chatError);
        setFailedRequest({ history: next, question });
      }
    } finally {
      if (gateRef.current.finish(token)) setBusy(false);
    }
  };

  const preparationQuestion = (question) => /prepare|preparation/i.test(question);

  // A fixed reply (no AI call), shown after "Jed is thinking..." for 1-2 s like a real answer. Goes through the request
  // gate, so changing the home or scenario meanwhile drops the reply, as it would a real one.
  const cannedReply = (question, reply) => {
    const next = boundedHistory(history, question);
    const token = gateRef.current.begin(contextKey);
    if (!token) return;
    setNeedHome(false); setHistory(next); setText(""); setBusy(true);
    setTimeout(() => {
      if (gateRef.current.isCurrent(token, currentContextRef.current))
        setHistory([...next, { role: "assistant", content: [{ text: reply }] }]);
      if (gateRef.current.finish(token)) setBusy(false);
    }, 1000 + Math.random() * 1000);
  };

  const ask = (value) => {
    const question = value.trim();
    if (!question || gateRef.current.isInFlight()) return;
    // Hardcoded (team request): asking about a street address ("Nans Lane") -> Jed explains we never look homes up by
    // address and asks for the Premise ID. Works before a home is chosen, since that's when people try an address.
    if (/\bnan'?s\s+(lane|ln)\b/i.test(question)) { cannedReply(question, t.addressPrivacyReply); return; }
    // Hardcoded (team request): any message mentioning "PS5" -> Jed says it's unlikely they can play during the storm
    // (no AI call). With a Moderate-or-worse home it gives the engine's own risk and outage length as the reason;
    // otherwise (Low risk, or no home chosen yet) the same answer without numbers, so it never contradicts the risk.
    if (/ps\s?5/i.test(question)) {
      cannedReply(question, premiseId && risk && RISKY_BANDS.has(risk.band)
        ? t.ps5Reply(t.bands[risk.band].toLowerCase(), Math.round(risk.probability * 100), risk.range)
        : t.ps5ReplyGeneral);
      return;
    }
    if (!premiseId) { setNeedHome(true); return; }
    if (preparationQuestion(question) && !profile.declared_needs?.length) {
      setSelectedPreparationNeeds([]);
      setPreparationNeeds(question);
      return;
    }
    const next = boundedHistory(history, question);
    setText("");
    submitHistory(next, question);
  };
  const togglePreparationNeed = (need) => {
    setSelectedPreparationNeeds((current) => current.includes(need)
      ? current.filter((item) => item !== need)
      : [...current, need]);
  };
  const continuePreparation = () => {
    if (!preparationNeeds || gateRef.current.isInFlight()) return;
    const next = boundedHistory(history, preparationNeeds);
    const requestProfile = {
      ...profile,
      declared_needs: [...new Set([...(profile.declared_needs || []), ...selectedPreparationNeeds])],
    };
    setPreparationNeeds(null);
    setText("");
    if (selectedPreparationNeeds.length) onNeeds(requestProfile.declared_needs);
    submitHistory(next, preparationNeeds, requestProfile);
  };
  const retry = () => {
    if (failedRequest && !gateRef.current.isInFlight()) {
      submitHistory(failedRequest.history, failedRequest.question);
    }
  };
  const send = (e) => { e.preventDefault(); ask(text); };

  return (<>
    <button ref={launcherRef} type="button" className={`chat-launcher${intro === "bounce" ? " intro-bounce" : ""}`}
      onClick={() => (open ? close() : setOpen(true))}
      aria-label={open ? t.chatClose : t.chatOpen} aria-expanded={open}
      aria-controls="chat-window" title={t.chatTitle}>
      <RobotIcon />
      {/* Greeting bubble (visual only; the button's label already says what it does). Tapping it opens the chat. */}
      {intro === "bubble" && <span className="jed-bubble" aria-hidden="true">{t.chatGreeting}</span>}
    </button>
    <section id="chat-window" className="chat" aria-label={t.chatTitle} hidden={!open}
      onKeyDown={(e) => { if (e.key === "Escape") close(); }} aria-busy={busy}>
      <div className="chat-head">
        <h2>{t.chatTitle}</h2>
        <button type="button" className="chat-close" onClick={close} aria-label={t.chatCloseShort}>×</button>
      </div>
      {!premiseId && (
        <p className={`chat-hint${needHome ? " nudge" : ""}`} role={needHome ? "alert" : undefined}>
          {needHome ? t.chatHintNudge : ""}{t.chatHint}</p>)}
      <div className="chips" role="group" aria-label={t.suggestedAria}>
        {suggestions.map((q) => (
          <button key={q} type="button" onClick={() => ask(q)} disabled={busy}>{q}</button>))}
      </div>
      {preparationNeeds && (
          <fieldset className="chat-needs">
            <legend>{t.needsChatAria}</legend>
            <p>{t.needsChatIntro}</p>
            <div className="chat-needs-grid">
            {Object.entries(t.needs).map(([need, label]) => (
              <label key={need} className="chat-need-option">
                <input type="checkbox" checked={selectedPreparationNeeds.includes(need)}
                  onChange={() => togglePreparationNeed(need)} />
                {label}
              </label>
            ))}
            </div>
            <button type="button" onClick={continuePreparation}>{t.needsChatContinue}</button>
          </fieldset>
      )}
      <div className="chat-log" ref={logRef} aria-live="polite">
        {history.map((m, i) => m.role === "assistant"
          ? <AssistantMsg key={i} t={t} text={m.content[0].text} />
          : <p key={i} className="user">{m.content[0].text}</p>)}
        {busy && <p className="assistant typing" role="status">{t.thinking}</p>}
      </div>
      {error && <div className="chat-error" role="alert">
        <span>{error}</span>
        <button type="button" onClick={retry} disabled={busy || !failedRequest}>{t.chatRetry}</button>
      </div>}
      <form onSubmit={send}>
        <input ref={inputRef} value={text} onChange={(e) => setText(e.target.value)} maxLength={1200}
          placeholder={t.chatPlaceholder} aria-label={t.chatQuestion} />
        <button type="submit" disabled={busy || !text.trim()}>{busy ? t.sending : t.send}</button>
      </form>
      <p className="muted chat-privacy">{t.chatPrivacy}</p>
    </section>
  </>);
}
