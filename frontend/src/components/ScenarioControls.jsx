// Scenario inputs judges can change + opt-in declared needs + demo-only utility toggle.   Owner: Nandan (was Abby)
// Visible text comes from i18n.js (t); the values sent to the API stay English.
import React from "react";

// Schema values (DeclaredNeed in backend/app/schemas.py). Labels: t.needs[value].
const NEEDS = ["medical_device", "refrigerated_medication", "mobility", "infants", "pets", "critical_facility"];

// damage_type values (keys in labor_hours: assumptions.yaml repair_recipes / non_cu_hours). Labels: t.damage[value].
const DAMAGE = ["", "tree_on_line", "wire_down", "broken_pole", "transformer_failed"];

// Storm slider: 4 levels instead of a raw percentile. pct = the severity_percentile sent to the API
// (the storm's rank among past storms). Picked from the real network's map:
// 50 = typical storm (all green), 95 = first yellow/orange areas, 97 = mixed, 99 = worst on record (Feb 2025).
// Labels + descriptions: t.stormLevels[i].
const STORM_PCTS = [50, 95, 97, 99];
// Index of the level closest to a percentile (the app's default 97 -> "High risk").
const levelFor = (pct) => STORM_PCTS.reduce((best, p, i) =>
  (Math.abs(p - pct) < Math.abs(STORM_PCTS[best] - pct) ? i : best), 0);

// The real past storm closest to a severity percentile, so the slider reads as weather people remember.
function similarStorm(pct, storms, t) {
  if (!storms.length) return null;
  if (pct < storms[0].percentile - 5) return t.milderThanAll;
  const s = storms.reduce((a, b) => (Math.abs(b.percentile - pct) < Math.abs(a.percentile - pct) ? b : a));
  const extra = [s.rain_mm >= 1 ? t.rainMm(Math.round(s.rain_mm)) : null, s.snow_cm >= 1 ? t.snowCm(Math.round(s.snow_cm)) : null]
    .filter(Boolean).join(", ");
  return t.similarStorm(s.label, Math.round(s.peak_gust_mph), extra);
}

export default function ScenarioControls({ t, scenario, onScenario, needs, onToggleNeed, enrolled, onEnrolled,
  utilityConfirmed, onUtilityConfirmed, referenceStorms = [] }) {
  const similar = similarStorm(scenario.severity_percentile, referenceStorms, t);
  const level = levelFor(scenario.severity_percentile);
  const lv = t.stormLevels[level];
  const setLevel = (e) => onScenario({ ...scenario, severity_percentile: STORM_PCTS[Number(e.target.value)] });
  // Returns an onChange handler that updates one scenario field (sliders need Number(), selects don't).
  const set = (k, num = false) => (e) => onScenario({ ...scenario, [k]: num ? Number(e.target.value) : e.target.value });
  // The UI offers one reported damage item; the API accepts a list.
  const damage = scenario.extra_damage?.[0]?.damage_type ?? "";
  const setDamage = (e) => onScenario({
    ...scenario, extra_damage: e.target.value ? [{ damage_type: e.target.value, quantity: 1 }] : [],
  });

  return (
    <section className="controls" aria-label={t.scenarioAria}>
      <label>{t.stormLevel}: <strong>{lv.label}</strong>
        <input type="range" min="0" max={STORM_PCTS.length - 1} step="1" value={level} onChange={setLevel}
          aria-valuetext={`${lv.label}. ${lv.note}`} />
        <span className="storm-ticks" aria-hidden="true">{t.stormLevels.map((l) => <span key={l.label}>{l.label}</span>)}</span>
        <span className="muted">{lv.note}{similar ? ` ${similar}` : ""}</span></label>
      <label>{t.crews}: <strong>{scenario.crews_available}</strong>
        <input type="range" min="2" max="80" value={scenario.crews_available} onChange={set("crews_available", true)} /></label>
      <label>{t.roadAccess}
        <select value={scenario.road_access} onChange={set("road_access")}>
          {["normal", "limited", "blocked"].map((r) => <option key={r} value={r}>{t.roads[r]}</option>)}
        </select></label>
      <label>{t.damageLabel}
        <select value={damage} onChange={setDamage}>
          {DAMAGE.map((k) => <option key={k} value={k}>{t.damage[k]}</option>)}
        </select></label>

      <fieldset><legend>{t.needsLegend}</legend>
        {NEEDS.map((k) => (
          <label key={k} className="check">
            <input type="checkbox" checked={needs.includes(k)} onChange={() => onToggleNeed(k)} />{t.needs[k]}</label>))}
        <label className="check">
          <input type="checkbox" checked={enrolled} onChange={() => onEnrolled(!enrolled)} />{t.enrolled}</label>
      </fieldset>

      <fieldset className="demo"><legend>{t.demoLegend}</legend>
        <label className="check">
          <input type="checkbox" checked={utilityConfirmed} onChange={() => onUtilityConfirmed(!utilityConfirmed)} />
          {t.demoToggle}</label>
      </fieldset>
    </section>
  );
}
