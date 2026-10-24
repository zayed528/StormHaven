// Scenario inputs judges can change + opt-in declared needs + demo-only utility toggle.   Owner: Abby
import React from "react";

// [schema value, label]. Values must match DeclaredNeed in backend/app/schemas.py.
const NEEDS = [
  ["medical_device", "Powered medical equipment"], ["refrigerated_medication", "Refrigerated medication"],
  ["mobility", "Mobility needs"], ["infants", "Infants at home"], ["pets", "Pets"],
  ["critical_facility", "I manage a critical facility"],
];

// [damage_type, label]. Values must match keys in labor_hours (assumptions.yaml repair_recipes / non_cu_hours).
const DAMAGE = [
  ["", "None reported"], ["tree_on_line", "Tree on the line"], ["wire_down", "Wire down"],
  ["broken_pole", "Broken pole"], ["transformer_failed", "Transformer failed"],
];

// Storm slider: 4 levels instead of a raw percentile. pct = the severity_percentile sent to the API
// (the storm's rank among past storms). Picked from the real network's map:
// 50 = typical storm (all green), 95 = first yellow/orange areas, 97 = mixed, 99 = worst on record (Feb 2025).
const STORM_LEVELS = [
  { label: "Low risk", pct: 50, note: "A typical storm. Outages are rare." },
  { label: "Moderate risk", pct: 95, note: "A stronger-than-usual storm. Some neighborhoods may lose power." },
  { label: "High risk", pct: 97, note: "A severe storm. Many neighborhoods may lose power." },
  { label: "Extremely high risk", pct: 99, note: "One of the worst storms on record. Widespread outages likely." },
];
// Index of the level closest to a percentile (the app's default 97 -> "High risk").
const levelFor = (pct) => STORM_LEVELS.reduce((best, l, i) =>
  (Math.abs(l.pct - pct) < Math.abs(STORM_LEVELS[best].pct - pct) ? i : best), 0);

// The real past storm closest to a severity percentile, so the slider reads as weather people remember.
function similarStorm(pct, storms) {
  if (!storms.length) return null;
  if (pct < storms[0].percentile - 5) return "Milder than any storm that caused notable damage in our records.";
  const s = storms.reduce((a, b) => (Math.abs(b.percentile - pct) < Math.abs(a.percentile - pct) ? b : a));
  const extra = [s.rain_mm >= 1 ? `${Math.round(s.rain_mm)} mm rain` : null, s.snow_cm >= 1 ? `${Math.round(s.snow_cm)} cm snow` : null]
    .filter(Boolean).join(", ");
  return `Similar to the ${s.label} storm: gusts up to ${Math.round(s.peak_gust_mph)} mph${extra ? `, ${extra}` : ""}.`;
}

export default function ScenarioControls({ scenario, onScenario, needs, onToggleNeed, enrolled, onEnrolled,
  utilityConfirmed, onUtilityConfirmed, referenceStorms = [] }) {
  const similar = similarStorm(scenario.severity_percentile, referenceStorms);
  const level = levelFor(scenario.severity_percentile);
  const setLevel = (e) => onScenario({ ...scenario, severity_percentile: STORM_LEVELS[Number(e.target.value)].pct });
  // Returns an onChange handler that updates one scenario field (sliders need Number(), selects don't).
  const set = (k, num = false) => (e) => onScenario({ ...scenario, [k]: num ? Number(e.target.value) : e.target.value });
  // The UI offers one reported damage item; the API accepts a list.
  const damage = scenario.extra_damage?.[0]?.damage_type ?? "";
  const setDamage = (e) => onScenario({
    ...scenario, extra_damage: e.target.value ? [{ damage_type: e.target.value, quantity: 1 }] : [],
  });

  return (
    <section className="controls" aria-label="Storm scenario">
      <label>Storm level: <strong>{STORM_LEVELS[level].label}</strong>
        <input type="range" min="0" max={STORM_LEVELS.length - 1} step="1" value={level} onChange={setLevel}
          aria-valuetext={`${STORM_LEVELS[level].label}. ${STORM_LEVELS[level].note}`} />
        <span className="storm-ticks" aria-hidden="true">{STORM_LEVELS.map((l) => <span key={l.label}>{l.label}</span>)}</span>
        <span className="muted">{STORM_LEVELS[level].note}{similar ? ` ${similar}` : ""}</span></label>
      <label>Crews available: <strong>{scenario.crews_available}</strong>
        <input type="range" min="2" max="80" value={scenario.crews_available} onChange={set("crews_available", true)} /></label>
      <label>Road access
        <select value={scenario.road_access} onChange={set("road_access")}>
          <option value="normal">Normal</option><option value="limited">Limited</option><option value="blocked">Blocked</option>
        </select></label>
      <label>Damage reported on your line
        <select value={damage} onChange={setDamage}>
          {DAMAGE.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        </select></label>

      <fieldset><legend>Needs you'd like us to consider (optional, only what you choose to tell us)</legend>
        {NEEDS.map(([k, l]) => (
          <label key={k} className="check">
            <input type="checkbox" checked={needs.includes(k)} onChange={() => onToggleNeed(k)} />{l}</label>))}
        <label className="check">
          <input type="checkbox" checked={enrolled} onChange={() => onEnrolled(!enrolled)} />Signed up for text alerts</label>
      </fieldset>

      <fieldset className="demo"><legend>Demo only</legend>
        <label className="check">
          <input type="checkbox" checked={utilityConfirmed} onChange={() => onUtilityConfirmed(!utilityConfirmed)} />
          Simulate: the utility confirms an outage at this location</label>
      </fieldset>
    </section>
  );
}
