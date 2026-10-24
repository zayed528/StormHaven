// Restoration steps as a visual timeline, plus the same steps as a text list (the list is what screen readers use).
// Data: restoration.steps = [{order, description, eta_hours, restores_your_power}], upstream first, ETA non-decreasing,
// and p10/p50/p90 for the shaded "likely range" band. Everything here is a model estimate.   Owner: Nandan
import React from "react";

// Hours -> short label. Switches to days at 48 h, like the backend's range text.
const fmt = (h) => (h >= 48 ? `${(h / 24).toFixed(1)} days` : `${Math.round(h)} h`);

export default function StepTimeline({ restoration }) {
  const { steps, p10_hours: p10, p50_hours: p50, p90_hours: p90 } = restoration;
  if (!steps?.length) return null;

  // Horizontal scale: 0 h on the left, a little past the latest mark on the right.
  const max = Math.max(p90, ...steps.map((s) => s.eta_hours), 1) * 1.1;
  const pct = (h) => (100 * h) / max;
  const at = (h) => `${pct(h)}%`;
  // P10 and P90 axis labels would collide when the range is narrow: show one combined label instead.
  const narrow = pct(p90) - pct(p10) < 14;

  return (
    <figure className="tl">
      <figcaption>When repairs could happen, if you lose power</figcaption>

      {/* Chart: shaded likely range, dashed best guess, one row per repair step (numbered like the list). */}
      <div className="tl-plot" aria-hidden="true">
        <div className="tl-band" style={{ left: at(p10), width: at(p90 - p10) }} />
        <div className="tl-p50" style={{ left: at(p50) }} />
        {steps.map((s) => (
          <div key={s.order} className="tl-row">
            <span className={`tl-dot${s.restores_your_power ? " yours" : ""}`} style={{ left: at(s.eta_hours) }}>{s.order}</span>
            {s.restores_your_power && (
              // Label sits right of the marker, or left of it when the marker is near the right edge.
              <span className={`tl-yours${pct(s.eta_hours) > 55 ? " flip" : ""}`} style={{ left: at(s.eta_hours) }}>
                your power returns · ~{fmt(s.eta_hours)}</span>)}
          </div>))}
      </div>
      <div className="tl-axis" aria-hidden="true">
        {pct(p10) > 12 && <span className="start" style={{ left: 0 }}>0 h</span>}
        {narrow
          ? <span style={{ left: at((p10 + p90) / 2) }}>{fmt(p10)}–{fmt(p90)}</span>
          : <><span style={{ left: at(p10) }}>{fmt(p10)}</span><span style={{ left: at(p90) }}>{fmt(p90)}</span></>}
      </div>
      <p className="tl-legend muted" aria-hidden="true">
        <span><i className="sw band" />Likely range</span>
        <span><i className="sw p50" />Best guess ~{fmt(p50)}</span>
        <span><i className="sw dot" />Repair step (numbered as below)</span>
      </p>

      {/* Text version: same steps in order, upstream first. */}
      <ol className="timeline" aria-label="Likely restoration order">
        {steps.map((s) => (
          <li key={s.order} className={s.restores_your_power ? "yours" : ""}>
            <span className="eta">~{fmt(s.eta_hours)}</span> {s.description}
            {s.restores_your_power && <strong> ← your power returns</strong>}
          </li>))}
      </ol>
    </figure>
  );
}
