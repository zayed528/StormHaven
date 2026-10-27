// The answer for one home, floating over the full-screen map: a safety strip + three cards side by side along the
// bottom: How long (the restoration range, "What if...?" changes, the timeline, the limits) / the outage risk and
// why + what you can do / Alerts. A slim line above the cards says what AEP has confirmed (vs. our estimates). The cards slide in from the left one after
// another when a home is chosen (App remounts this per home).   Owner: Nandan
import React, { useEffect, useRef, useState } from "react";
import { sendNotify } from "../api/client.js";
import { fmtRange } from "../i18n.js";
import { BAND_COLORS } from "./OutageMap.jsx";
import StormToggle, { levelFor } from "./ScenarioControls.jsx";
import StepTimeline from "./StepTimeline.jsx";

// Safety banner color class per risk band (colors match the map dots). Unknown = location not matched.
// Titles and intro sentences live in i18n.js (t.safety).
const BAND_CLASS = { Low: "low", Moderate: "moderate", High: "high", "Very High": "very-high", Unknown: "unknown" };
// The strip takes the color of the STORM it's for (Typical green, Strong yellow, Severe orange, Record red), so each
// What-if storm looks different; the home's own risk is in its title and in the risk card's colored bar.
const STORM_CLASS = ["low", "moderate", "high", "very-high"];
const ACTIONS_SHOWN = 4;        // "What you can do": items shown before "more"

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

// whatIf = { scenario, onScenario, baseCrews, moreCrews } (state lives in App): the "What if...?" controls change the
// scenario sent to the engines, so every number in the cards (and the map) follows.
// confirmed = show the "Not confirmed by AEP" / "Confirmed by AEP" note (web app; the phone app turns it off).
// swipeToClose = the phone app: swipe the cards down to close them (the x is kept only for keyboard users).
// stormPct = the storm strength THIS answer was computed for (it can lag the What-if buttons while a new answer loads),
// so the safety strip never names one storm next to another storm's risk.
export default function ResultsPanel({ t, result, changes, notifyRequest, whatIf, onClose, confirmed = true,
  swipeToClose = false, stormPct = null }) {
  // Swipe down to close: starts on a downward drag (not on a sideways swipe between cards, nor while a card is scrolled
  // down inside); the cards follow the finger; let go past CLOSE_PX and they slide away, else they spring back.
  // Native listeners, not React's: the move handler must be able to stop the browser's own scroll / pull-to-refresh
  // (React's touch listeners can't), or the browser takes over the drag and cancels it.
  const [drag, setDrag] = useState({ y: 0, on: false });
  const dockRef = useRef(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    const el = dockRef.current;
    if (!swipeToClose || !el) return undefined;
    const CLOSE_PX = 80;
    let s = null;
    const startDrag = (e) => {
      const card = e.target.closest(".card");
      const f = e.changedTouches[0];          // follow THIS finger (not whichever touch happens to be first)
      s = card && card.scrollTop > 0 ? null : { id: f.identifier, x: f.clientX, y: f.clientY, active: false, dy: 0 };
    };
    const move = (e) => {
      const f = s && [...e.touches].find((x) => x.identifier === s.id);
      if (!f) return;
      const dx = f.clientX - s.x, dy = f.clientY - s.y;
      if (!s.active) {
        if (Math.abs(dx) < 8 && Math.abs(dy) < 8) return;
        if (dy > 0 && dy > Math.abs(dx)) s.active = true;
        else { s = null; return; }
      }
      e.preventDefault();
      s.dy = Math.max(0, dy);
      setDrag({ y: s.dy, on: true });
    };
    const end = () => {
      const done = s;
      s = null;
      if (!done?.active) return;
      if (done.dy > CLOSE_PX) { setDrag({ y: window.innerHeight, on: false }); setTimeout(() => closeRef.current(), 220); }
      else setDrag({ y: 0, on: false });
    };
    el.addEventListener("touchstart", startDrag, { passive: true });
    el.addEventListener("touchmove", move, { passive: false });
    el.addEventListener("touchend", end);
    el.addEventListener("touchcancel", end);
    return () => {
      el.removeEventListener("touchstart", startDrag); el.removeEventListener("touchmove", move);
      el.removeEventListener("touchend", end); el.removeEventListener("touchcancel", end);
    };
  }, [swipeToClose]);
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
  const storm = levelFor(stormPct ?? whatIf.scenario.severity_percentile);   // 0 Typical .. 3 Record
  const showConfirmed = confirmed && !fallback;
  const confirmedNote = (
    <span className={`confirmed-note${restoration.outage_confirmed ? " yes" : ""}`}>
      {restoration.outage_confirmed
        ? <><strong>✓ {t.confirmedYes}</strong> {restoration.confirmed_etr ?? ""}</>
        : <><strong>{t.confirmedNo}</strong> {t.confirmedNoMore}</>}</span>);
  const actionItem = (a, i) => (
    <li key={i}>{a.is_safety && <strong>{t.safetyMessage} </strong>}{a.text}
      {a.reason && <span className="muted action-reason"> {a.reason}</span>}</li>);
  // "What changed": `key` changes with each update so the flash animation replays.
  const flash = (on) => (on ? " changed" : "");
  const k = changes?.stamp ?? 0;
  // Phone layout (decided once per home; App remounts this component for each home).
  const [narrow] = useState(() => window.matchMedia?.("(max-width: 760px)").matches ?? false);

  // The three cards, built by position i (sets the slide-in stagger). Order: on a phone the estimate comes first,
  // since only one card is visible at a time in the swipeable row.
  const sc = whatIf.scenario;
  const roadsBlocked = sc.road_access === "blocked";
  const moreCrews = sc.crews_available > whatIf.baseCrews;
  // The three cards, built by position i (sets the slide-in stagger). On a phone the risk card comes first, since only
  // one card is visible at a time in the swipeable row.
  const cards = {
    // Card 1: how long, if you lose power: the range, "What if...?" changes, the drivers, the timeline, the limits.
    howlong: (i) => (
        <article key="howlong" className="card card-howlong" style={{ "--i": i }} tabIndex={0}><h2>{t.howLong}</h2>
          <p key={`r${k}`} className={flash(changes?.range).trim()}><strong>{t.tr(restoration.range_text)}</strong>
            {changes?.range && <span className="was"> {t.was} <s>{fmtRange(changes.range, t)}</s></span>}</p>
          {/* The planner bridge: one line connecting this estimate to how a similar REAL storm was restored
              (AEP crews + days-to-back). Only present for storms close to a real one; backend sentence, so t.tr. */}
          {!fallback && restoration.storm_context && (
            <p className="storm-context">{t.tr(restoration.storm_context)}</p>)}
          {!fallback && (<>
            {/* What if...? The forecast storm is the starting point; these try a different storm, roads, or crews. */}
            <div className="whatif" role="group" aria-labelledby="whatif-title">
              <h3 id="whatif-title">{t.whatIfTitle}</h3>
              <p className="muted" id="whatif-storm">{t.whatIfStorm}</p>
              <StormToggle t={t} scenario={sc} onScenario={whatIf.onScenario} labelledBy="whatif-storm" />
              <div className="whatif-chips">
                <button type="button" className="whatif-chip" aria-pressed={roadsBlocked}
                  onClick={() => whatIf.onScenario({ ...sc, road_access: roadsBlocked ? "normal" : "blocked" })}>{t.whatIfRoads}</button>
                <button type="button" className="whatif-chip" aria-pressed={moreCrews}
                  onClick={() => whatIf.onScenario({ ...sc, crews_available: moreCrews ? whatIf.baseCrews : whatIf.moreCrews })}>{t.whatIfCrews}</button>
              </div>
            </div>
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

    // Card 2: the outage risk line (its colored bar) at the very top, then what you can do, then why.
    risk: (i) => (
        <article key="risk" className="card card-risk" style={{ "--i": i }} aria-label={t.estimateTitle} tabIndex={0}>
          {fallback ? (
            <p><strong>{t.fallback}</strong> {t.fallbackMore} {risk.trust.could_change_if.map(t.tr).join(" ")}</p>
          ) : (
            <h2 key={`b${k}`} className={`band${flash(changes?.band)}`} style={{ borderColor: BAND_COLORS[risk.band] ?? "#888" }}>
              {t.bandLine(t.bands[risk.band] ?? risk.band, t.conf[risk.trust.confidence] ?? risk.trust.confidence)}
              {changes?.band && <span className="was"> {t.was} <s>{t.bands[changes.band] ?? changes.band}</s></span>}</h2>)}
          {/* What you can do (first, right under the risk line): curated, sourced advice picked by rules (risk,
              expected duration, declared needs), never AI-written; already in the customer's language. The first few
              show, the rest fold away. */}
          {guidance.actions.length > 0 && (<>
            <h3>{t.canDo}</h3>
            <ul className="actions">{guidance.actions.slice(0, ACTIONS_SHOWN).map(actionItem)}</ul>
            {guidance.actions.length > ACTIONS_SHOWN && (
              <details><summary>{t.moreActions(guidance.actions.length - ACTIONS_SHOWN)}</summary>
                <ul className="actions">{guidance.actions.slice(ACTIONS_SHOWN).map(actionItem)}</ul></details>)}
          </>)}
          {/* Then why the risk is what it is. */}
          {!fallback && (<>
            <h3>{t.why}</h3>
            <ul>{risk.factors.map((f, i) => <li key={i}>{t.tr(f.plain_language)}</li>)}</ul>
          </>)}
        </article>),

    // Card 3: alerts (eligibility, follow-ups, the messages and "send as a text").
    alerts: (i) => (
        <article key="alerts" className="card" style={{ "--i": i }} tabIndex={0}><h2>{t.alerts}</h2>
          <p>{alerts.eligible ? t.eligibleYes : t.eligibleNo}</p>
          <ul className="muted">{alerts.reasons.map((r, i) => <li key={i}>{t.tr(r)}</li>)}</ul>
          {activeEsc.length > 0 && (
            <div className="escalation"><strong>{t.followUp}</strong>
              <ul>{activeEsc.map((e, i) => <li key={i}>{t.tr(e.action)}</li>)}</ul></div>)}
          <details open><summary>{t.messagesTitle}</summary>
            {Object.entries(alerts.messages).map(([key, m]) => (
              <figure key={key}><figcaption>{t.messageLabels[key] ?? key}</figcaption><blockquote>{m}</blockquote>
                {/* Remount when the message text changes, so an old "Sent" status never sits under new text. */}
                {notifyRequest && <SendButton key={m} t={t} messageKey={key} request={notifyRequest} eligible={alerts.eligible} />}
              </figure>))}
          </details>
        </article>),
  };
  const order = narrow ? ["risk", "howlong", "alerts"] : ["howlong", "risk", "alerts"];

  return (
    // tabIndex -1: App moves focus here after a keyboard lookup, so screen readers start at the answer.
    <section className={`results dock${drag.y ? " dragging" : ""}`} id="results" tabIndex={-1} aria-label={t.resultsAria}
      style={drag.y ? { transform: `translateY(${drag.y}px)`, transition: drag.on ? "none" : undefined } : undefined}
      ref={dockRef}>
      {swipeToClose && <div className="dock-grabber" aria-hidden="true" />}
      <button type="button" className="dock-close" onClick={onClose} aria-label={t.closeResults} title={t.closeResults}>×</button>
      {/* Safety first, visually separate, announced to screen readers via role="alert". The web app also says here, in
          small print, whether AEP has confirmed an outage (only ever from the utility's status, never the model), so
          the cards below read as our estimate. */}
      {guidance.safety.length > 0 && (
        <div className={`safety ${fallback ? BAND_CLASS.Unknown : STORM_CLASS[storm]}`} role="alert">
          {/* Title = the home's risk + the storm it's for (its colored dot, as in the What-if buttons; the strip has
              the storm's color too); then one message for that storm: what it means and what to do. */}
          {/* The risk band alone can match for two storms (Very High in both a severe and a record storm), so the
              title also gives the engine's outage length for this storm, e.g. "17-32 hours" vs "2-3 days". */}
          <details><summary><strong>⚠ {sb.title}{!fallback && restoration.range_short
              && <span className="safety-range"> · {t.safetyIfOut(restoration.range_short)}</span>}</strong>
            {!fallback && <span className={`safety-storm lvl-${storm}`}>{t.stormLevels[storm].label}</span>}{" "}
            <span className="safety-intro">{fallback ? sb.text : t.safetyStorm[storm]}</span>
            {showConfirmed && confirmedNote}</summary>
            <ul>{guidance.safety.map((s, i) => <li key={i}>{s.text}</li>)}</ul></details></div>)}
      {showConfirmed && guidance.safety.length === 0 && <p className="confirmed-line">{confirmedNote}</p>}

      {t.engineNote && <p className="muted engine-note">{t.engineNote}</p>}

      <div className="cols">{order.map((name, i) => cards[name](i))}
      </div>
    </section>
  );
}
