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

export default function ScenarioControls({ scenario, onScenario, needs, onToggleNeed, enrolled, onEnrolled,
  utilityConfirmed, onUtilityConfirmed }) {
  // Returns an onChange handler that updates one scenario field (sliders need Number(), selects don't).
  const set = (k, num = false) => (e) => onScenario({ ...scenario, [k]: num ? Number(e.target.value) : e.target.value });
  // The UI offers one reported damage item; the API accepts a list.
  const damage = scenario.extra_damage?.[0]?.damage_type ?? "";
  const setDamage = (e) => onScenario({
    ...scenario, extra_damage: e.target.value ? [{ damage_type: e.target.value, quantity: 1 }] : [],
  });

  return (
    <section className="controls" aria-label="Storm scenario">
      <label>Storm strength vs. past storms: <strong>{scenario.severity_percentile}th percentile</strong>
        <input type="range" min="0" max="100" value={scenario.severity_percentile} onChange={set("severity_percentile", true)} /></label>
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
