// Safety banner + the three columns the challenge asks for:
// Confirmed facts (utility only) / Our estimate (model) / What you can do (+ alerts).   Owner: Nandan (was Abby)
import React, { useState } from "react";
import { sendNotify } from "../api/client.js";
import { fmtRange } from "../i18n.js";
import { BAND_COLORS } from "./OutageMap.jsx";
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

export default function ResultsPanel({ t, result, changes, notifyRequest }) {
  const { risk, restoration, guidance, alerts } = result;
  const fallback = risk.source === "fallback";     // location not matched: show the fallback, never numbers
  const trust = [...risk.trust.assumptions, ...restoration.trust.assumptions];
  const missing = [...risk.trust.missing_data, ...restoration.trust.missing_data];
  const activeEsc = alerts.escalations.filter((e) => e.active);
  const sb = t.safety[risk.band] ?? t.safety.Unknown;
  // "What changed": `key` changes with each update so the flash animation replays.
  const flash = (on) => (on ? " changed" : "");
  const k = changes?.stamp ?? 0;

  return (
    // tabIndex -1: App moves focus here after a keyboard lookup, so screen readers start at the answer.
    <section className="results" id="results" tabIndex={-1} aria-label={t.resultsAria}>
      {/* Safety first, visually separate, announced to screen readers via role="alert". */}
      {guidance.safety.length > 0 && (
        <div className={`safety ${BAND_CLASS[risk.band] ?? "unknown"}`} role="alert"><strong>⚠ {sb.title}</strong>
          <p className="safety-intro">{sb.text}</p>
          <ul>{guidance.safety.map((s, i) => <li key={i}>{s.text}</li>)}</ul></div>)}

      {t.engineNote && <p className="muted engine-note">{t.engineNote}</p>}

      <div className="cols">
        {/* Column 1: only utility-confirmed facts (from utility_status), never model output. */}
        <article><h2>{t.confirmedTitle}</h2>
          {restoration.outage_confirmed ? (
            <><p><strong>{t.outageConfirmed}</strong></p>
              {restoration.confirmed_etr && <p>{restoration.confirmed_etr}</p>}
              <p className="muted">{t.utilitySource}</p></>
          ) : <p>{t.noOutage}</p>}
        </article>

        {/* Column 2: everything the model estimated, labeled as such, with its assumptions and limits. */}
        <article><h2>{t.estimateTitle} <span className="tag">{t.modelEstimate}</span></h2>
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
        </article>

        {/* Column 3: what the customer can do, plus alerts. */}
        <article><h2>{t.canDo}</h2>
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
        </article>
      </div>
    </section>
  );
}
