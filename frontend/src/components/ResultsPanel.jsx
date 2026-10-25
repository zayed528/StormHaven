// The answer for one home, floating over the full-screen map: a safety strip + the three cards the challenge asks for,
// Demo utility status / Our estimate (model) / What you can do (+ alerts), side by side along the bottom. The cards
// slide in from the left one after another when a home is chosen (App remounts this per home).   Owner: Nandan
import React, { useEffect, useState } from "react";
import { sendNotify } from "../api/client.js";
import { fmtRange } from "../i18n.js";
import { BAND_COLORS } from "./OutageMap.jsx";
import { DemoToggle, NeedsPicker } from "./ScenarioControls.jsx";
import StepTimeline from "./StepTimeline.jsx";

// Safety banner color class per risk band (colors match the map dots). Unknown = location not matched.
// Titles and intro sentences live in i18n.js (t.safety).
const BAND_CLASS = { Low: "low", Moderate: "moderate", High: "high", "Very High": "very-high", Unknown: "unknown" };

// "Send this alert as a text" for one message. Shows what the server says it did (sent / dry run / mock).
function SendButton({ t, messageKey, request, eligible }) {
  const [state, setState] = useState(null);       // null | "busy" | "error" | {sent, dry_run, text, mock?}
  if (!eligible) return <p className="muted send-note">{t.needEnroll}</p>;
  const go = async () => {
    setState("busy");
    try { setState(await sendNotify({ message_key: messageKey, ...request })); } catch { setState("error"); }
  };
  const done = state && typeof state === "object";
  return (
    <div className="send">
      <button type="button" onClick={go} disabled={state === "busy"}>{state === "busy" ? t.sending : t.sendText}</button>
      <span role="status" className="send-status">
        {state === "error" && <span className="error">{t.sendError}</span>}
        {done && (state.mock ? t.mock : state.sent ? t.sent : t.dryRun)}
        {done && state.text && <span className="muted"> {t.textWas} “{state.text}”</span>}
      </span>
    </div>
  );
}

// controls = { needs, onToggleNeed, enrolled, onEnrolled, utilityConfirmed, onUtilityConfirmed } (state lives in App)
export default function ResultsPanel({ t, result, changes, notifyRequest, controls, onClose }) {
  // Esc closes the cards (the map stays; clicking a home opens them again).
  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape" && !e.defaultPrevented && !document.querySelector(".chat:not([hidden])")) onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  const { risk, restoration, guidance, alerts } = result;
  const fallback = risk.source === "fallback";     // location not matched: show the fallback, never numbers
  const trust = [...risk.trust.assumptions, ...restoration.trust.assumptions];
  const missing = [...risk.trust.missing_data, ...restoration.trust.missing_data];
  const activeEsc = alerts.escalations.filter((e) => e.active);
  const sb = t.safety[risk.band] ?? t.safety.Unknown;
  // "What changed": `key` changes with each update so the flash animation replays.
  const flash = (on) => (on ? " changed" : "");
  const k = changes?.stamp ?? 0;
  // Phone layout (decided once per home; App remounts this component for each home).
  const [narrow] = useState(() => window.matchMedia?.("(max-width: 760px)").matches ?? false);

  // The three cards, built by position i (sets the slide-in stagger). Order: on a phone the estimate comes first,
  // since only one card is visible at a time in the swipeable row.
  const cards = {
        // Card 1: utility status. Only the explicit demo toggle fills it; never represented as a live AEP feed.
    status: (i) => (
        <article key="status" className="card" style={{ "--i": i }}><h2>{t.confirmedTitle}</h2>
          {restoration.outage_confirmed ? (
            <><p><strong>{t.outageConfirmed}</strong></p>
              {restoration.confirmed_etr && <p>{restoration.confirmed_etr}</p>}
              <p className="muted">{t.utilitySource}</p></>
          ) : <p>{t.noOutage}</p>}
          <DemoToggle t={t} utilityConfirmed={controls.utilityConfirmed} onUtilityConfirmed={controls.onUtilityConfirmed} />
        </article>),

        // Card 2: everything the model estimated, labeled as such, with its assumptions and limits.
    estimate: (i) => (
        <article key="estimate" className="card" style={{ "--i": i }}><h2>{t.estimateTitle} <span className="tag">{t.modelEstimate}</span></h2>
          {fallback ? (
            <p><strong>{t.fallback}</strong> {t.fallbackMore} {risk.trust.could_change_if.map(t.tr).join(" ")}</p>
          ) : (<>
            <p key={`b${k}`} className={`band${flash(changes?.band)}`} style={{ borderColor: BAND_COLORS[risk.band] ?? "#888" }}>
              {t.bandLine(t.bands[risk.band] ?? risk.band, t.conf[risk.trust.confidence] ?? risk.trust.confidence)}
              {changes?.band && <span className="was"> {t.was} <s>{t.bands[changes.band] ?? changes.band}</s></span>}</p>
            <h3>{t.why}</h3>
            <ul>{risk.factors.map((f, i) => <li key={i}>{t.tr(f.plain_language)}</li>)}</ul>
            <h3>{t.howLong}</h3>
            <p key={`r${k}`} className={flash(changes?.range).trim()}><strong>{t.tr(restoration.range_text)}</strong>
              {changes?.range && <span className="was"> {t.was} <s>{fmtRange(changes.range, t)}</s></span>}</p>
            <ul>{restoration.drivers.map((d, i) => <li key={i}>{t.tr(d.plain_language)}</li>)}</ul>
            <StepTimeline t={t} restoration={restoration} />
          </>)}
          <details><summary>{t.limits}</summary>
            <ul>{trust.map((a, i) => <li key={`a${i}`}>{t.tr(a)}</li>)}</ul>
            {missing.length > 0 && <><h4>{t.dontKnow}</h4><ul>{missing.map((m, i) => <li key={`m${i}`}>{t.tr(m)}</li>)}</ul></>}
            <h4>{t.couldChange}</h4>
            <ul>{risk.trust.could_change_if.map((c, i) => <li key={`c${i}`}>{t.tr(c)}</li>)}</ul>
          </details>
        </article>),

        // Card 3: what the customer can do (changes with the needs they choose to declare here), plus alerts.
    todo: (i) => (
        <article key="todo" className="card" style={{ "--i": i }}><h2>{t.canDo}</h2>
          <NeedsPicker t={t} needs={controls.needs} onToggleNeed={controls.onToggleNeed}
            enrolled={controls.enrolled} onEnrolled={controls.onEnrolled} />
          <ul>{guidance.actions.map((a, i) => (
            <li key={i}>{a.text}{a.reason && <span className="muted"> ({a.reason})</span>}</li>))}</ul>
          <h3>{t.alerts}</h3>
          <p>{alerts.eligible ? t.eligibleYes : t.eligibleNo}</p>
          <ul className="muted">{alerts.reasons.map((r, i) => <li key={i}>{t.tr(r)}</li>)}</ul>
          {activeEsc.length > 0 && (
            <div className="escalation"><strong>{t.followUp}</strong>
              <ul>{activeEsc.map((e, i) => <li key={i}>{t.tr(e.action)}</li>)}</ul></div>)}
          <details open><summary>{t.messagesTitle}</summary>
            {Object.entries(alerts.messages).map(([key, m]) => (
              <figure key={key}><figcaption>{t.messageLabels[key] ?? key}</figcaption><blockquote>{m}</blockquote>
                {/* Remount when the message text changes, so an old "Sent" status never sits under new text. */}
                <SendButton key={m} t={t} messageKey={key} request={notifyRequest} eligible={alerts.eligible} />
              </figure>))}
          </details>
        </article>),
  };
  const order = narrow ? ["estimate", "status", "todo"] : ["status", "estimate", "todo"];

  return (
    // tabIndex -1: App moves focus here after a keyboard lookup, so screen readers start at the answer.
    <section className="results dock" id="results" tabIndex={-1} aria-label={t.resultsAria}>
      <button type="button" className="dock-close" onClick={onClose} aria-label={t.closeResults} title={t.closeResults}>×</button>
      {/* Safety first, visually separate, announced to screen readers via role="alert". */}
      {guidance.safety.length > 0 && (
        <div className={`safety ${BAND_CLASS[risk.band] ?? "unknown"}`} role="alert">
          <details><summary><strong>⚠ {sb.title}</strong> <span className="safety-intro">{sb.text}</span></summary>
            <ul>{guidance.safety.map((s, i) => <li key={i}>{s.text}</li>)}</ul></details></div>)}

      {t.engineNote && <p className="muted engine-note">{t.engineNote}</p>}

      <div className="cols">{order.map((name, i) => cards[name](i))}
      </div>
    </section>
  );
}
