// STUB (Abby, hour 14-18): restoration steps as a visual timeline.
// Data: restoration.steps = [{order, description, eta_hours, restores_your_power}], upstream first, ETA non-decreasing.
// TODO: horizontal timeline scaled to p90, P10-P90 band behind it, highlight the step that restores the customer.
import React from "react";

export default function StepTimeline({ steps }) {
  if (!steps?.length) return null;
  return (
    <ol className="timeline" aria-label="Likely restoration order">
      {steps.map((s) => (
        <li key={s.order} className={s.restores_your_power ? "yours" : ""}>
          <span className="eta">~{Math.round(s.eta_hours)} h</span> {s.description}
          {s.restores_your_power && <strong> ← your power returns</strong>}
        </li>))}
    </ol>
  );
}
