// Customer inputs.   Owner: Nandan (was Abby)
//  - default export: the storm-level toggles, floating centered under the header ("liquid glass" pill with a thumb that
//    glides to the chosen level). The one scenario input customers set.
//  - NeedsPicker: opt-in declared needs + alert sign-up (shown in the "What you can do" card)
//  - DemoToggle: demo-only "the utility confirms an outage" switch (shown in the confirmed-status card)
// Crews, road access and reported damage are not customer inputs: the API keeps its defaults for them (20 crews, normal
// roads, no reported damage), and the "what if" lines in the results still explain them.
// Visible text comes from i18n.js (t); the values sent to the API stay English.
import React, { useLayoutEffect, useRef, useState } from "react";

// Schema values (DeclaredNeed in backend/app/schemas.py). Labels: t.needs[value].
const NEEDS = ["refrigerated_medication", "mobility", "infants", "pets", "critical_facility"];

// Storm levels: pct = the severity_percentile sent to the API (the storm's rank among past storms). Picked from the
// real network's map: 50 = typical storm (all green), 95 = first yellow/orange areas, 97 = mixed, 99 = worst on record.
// Labels: t.stormLevels[i].label; the description (t.stormLevels[i].note) is read to screen readers.
const STORM_PCTS = [50, 95, 97, 99];
// Index of the level closest to a percentile (the app's default 97 -> "High risk").
const levelFor = (pct) => STORM_PCTS.reduce((best, p, i) =>
  (Math.abs(p - pct) < Math.abs(STORM_PCTS[best] - pct) ? i : best), 0);

// Storm level as four toggle buttons (one is always on). A glass "thumb" sits behind the chosen one and glides to the
// next when it changes; its position comes from the chosen button's box, re-measured on resize and language change.
export default function ScenarioControls({ t, scenario, onScenario }) {
  const level = levelFor(scenario.severity_percentile);
  const group = useRef(null);
  const [thumb, setThumb] = useState(null);          // { left, width } in px, relative to the group

  useLayoutEffect(() => {
    const g = group.current;
    if (!g) return;
    const measure = () => {
      const b = g.querySelectorAll("button")[level];
      if (b) setThumb({ left: b.offsetLeft, width: b.offsetWidth });
    };
    measure();
    const ro = window.ResizeObserver ? new ResizeObserver(measure) : null;
    ro?.observe(g);
    return () => ro?.disconnect();
  }, [level, t]);

  return (
    <div className="storm-bar">
      <span className="storm-bar-label" id="storm-label">{t.stormLevel}</span>
      <div className="storm-toggles" role="group" aria-labelledby="storm-label" ref={group}>
        {thumb && <span className="storm-thumb" aria-hidden="true"
          style={{ transform: `translateX(${thumb.left}px)`, width: `${thumb.width}px` }} />}
        {t.stormLevels.map((l, i) => (
          <button key={l.label} type="button" aria-pressed={i === level} className={`lvl-${i}`} title={l.note}
            aria-description={l.note} onClick={() => onScenario({ ...scenario, severity_percentile: STORM_PCTS[i] })}>
            {l.label}</button>))}
      </div>
    </div>
  );
}

// Opt-in needs + alert sign-up, collapsed until the customer opens it (the summary shows how many are declared).
export function NeedsPicker({ t, needs, onToggleNeed, enrolled, onEnrolled }) {
  return (
    <details className="needs-picker">
      <summary>{t.needsLegend}{needs.length > 0 && <span className="needs-count"> ({needs.length})</span>}</summary>
      <div className="needs-list">
        {NEEDS.map((k) => (
          <label key={k} className="check">
            <input type="checkbox" checked={needs.includes(k)} onChange={() => onToggleNeed(k)} />{t.needs[k]}</label>))}
        <label className="check">
          <input type="checkbox" checked={enrolled} onChange={() => onEnrolled(!enrolled)} />{t.enrolled}</label>
      </div>
    </details>
  );
}

// Demo-only switch standing in for the utility's outage feed. Never represented as live AEP data.
export function DemoToggle({ t, utilityConfirmed, onUtilityConfirmed }) {
  return (
    <label className="check demo-toggle">
      <input type="checkbox" checked={utilityConfirmed} onChange={() => onUtilityConfirmed(!utilityConfirmed)} />
      <span><span className="tag">{t.demoLegend}</span> {t.demoToggle}</span></label>
  );
}
