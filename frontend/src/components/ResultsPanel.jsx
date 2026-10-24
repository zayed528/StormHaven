// Safety banner + the three columns the challenge asks for:
// Confirmed facts (utility only) / Our estimate (model) / What you can do (+ alerts).   Owner: Abby
import React from "react";
import { BAND_COLORS } from "./OutageMap.jsx";
import StepTimeline from "./StepTimeline.jsx";

// Alert message keys from the API -> human labels.
const MESSAGE_LABELS = {
  pre_storm: "Before the storm", outage_confirmed: "Outage confirmed",
  estimate_updated: "Estimate updated", restoration_complete: "Power restored",
};

// Safety banner look + intro per risk band (colors match the map dots). Unknown = location not matched.
const BAND_SAFETY = {
  Low: { cls: "low", title: "Low outage risk",
    text: "An outage is unlikely, but storms can change quickly. Keep these safety rules in mind." },
  Moderate: { cls: "moderate", title: "Moderate outage risk",
    text: "An outage is possible. Get ready now and keep these safety rules in mind." },
  High: { cls: "high", title: "High outage risk",
    text: "An outage is likely. Prepare now, and follow these safety rules if your power goes out." },
  "Very High": { cls: "very-high", title: "Very high outage risk",
    text: "An outage is very likely and could last a while. Prepare now and follow these safety rules." },
  Unknown: { cls: "unknown", title: "Safety",
    text: "We couldn't estimate your risk, but these safety rules apply to every storm." },
};

export default function ResultsPanel({ result }) {
  const { risk, restoration, guidance, alerts } = result;
  const fallback = risk.source === "fallback";     // location not matched: show the fallback, never numbers
  const trust = [...risk.trust.assumptions, ...restoration.trust.assumptions];
  const missing = [...risk.trust.missing_data, ...restoration.trust.missing_data];
  const activeEsc = alerts.escalations.filter((e) => e.active);
  const sb = BAND_SAFETY[risk.band] ?? BAND_SAFETY.Unknown;

  return (
    <section className="results" aria-live="polite">
      {/* Safety first, visually separate, announced to screen readers via role="alert". */}
      {guidance.safety.length > 0 && (
        <div className={`safety ${sb.cls}`} role="alert"><strong>⚠ {sb.title}</strong>
          <p className="safety-intro">{sb.text}</p>
          <ul>{guidance.safety.map((s, i) => <li key={i}>{s.text}</li>)}</ul></div>)}

      <div className="cols">
        {/* Column 1: only utility-confirmed facts (from utility_status), never model output. */}
        <article><h2>Confirmed by AEP</h2>
          {restoration.outage_confirmed ? (
            <><p><strong>Outage confirmed at your location.</strong></p>
              {restoration.confirmed_etr && <p>{restoration.confirmed_etr}</p>}
              <p className="muted">Source: utility status feed (simulated for this demo).</p></>
          ) : <p>No outage confirmed at your location yet.</p>}
        </article>

        {/* Column 2: everything the model estimated, labeled as such, with its assumptions and limits. */}
        <article><h2>Our estimate <span className="tag">model estimate</span></h2>
          {fallback ? (
            <p><strong>We can't make a reliable prediction for this location.</strong> Please check AEP's official outage
              map or contact AEP. {risk.trust.could_change_if.join(" ")}</p>
          ) : (<>
            <p className="band" style={{ borderColor: BAND_COLORS[risk.band] ?? "#888" }}>
              {risk.band} outage risk · {risk.trust.confidence} confidence</p>
            <h3>Why</h3>
            <ul>{risk.factors.map((f, i) => <li key={i}>{f.plain_language}</li>)}</ul>
            <h3>How long, if you lose power</h3>
            <p><strong>{restoration.range_text}</strong></p>
            <ul>{restoration.drivers.map((d, i) => <li key={i}>{d.plain_language}</li>)}</ul>
            <StepTimeline restoration={restoration} />
          </>)}
          <details><summary>Assumptions, missing data, and limits</summary>
            <ul>{trust.map((a, i) => <li key={`a${i}`}>{a}</li>)}</ul>
            {missing.length > 0 && <><h4>What we don't know</h4><ul>{missing.map((m, i) => <li key={`m${i}`}>{m}</li>)}</ul></>}
            <h4>This could change if</h4>
            <ul>{risk.trust.could_change_if.map((c, i) => <li key={`c${i}`}>{c}</li>)}</ul>
          </details>
        </article>

        {/* Column 3: what the customer can do, plus alerts. */}
        <article><h2>What you can do</h2>
          <ul>{guidance.actions.map((a, i) => (
            <li key={i}>{a.text}{a.reason && <span className="muted"> ({a.reason})</span>}</li>))}</ul>
          <h3>Alerts</h3>
          <p>{alerts.eligible ? "You'll receive outage alerts." : "You're not set up for alerts yet."}</p>
          <ul className="muted">{alerts.reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>
          {activeEsc.length > 0 && (
            <div className="escalation"><strong>We'll follow up personally:</strong>
              <ul>{activeEsc.map((e, i) => <li key={i}>{e.action}</li>)}</ul></div>)}
          <details open><summary>Messages you'd get</summary>
            {Object.entries(alerts.messages).map(([k, m]) => (
              <figure key={k}><figcaption>{MESSAGE_LABELS[k] ?? k}</figcaption><blockquote>{m}</blockquote></figure>))}
          </details>
        </article>
      </div>
    </section>
  );
}
