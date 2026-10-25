// Storm restoration PLAN panel (operator view).   Owner: Abby
// Backs GET /api/planner/storms + /api/planner/plan (contract in docs/API_CONTRACT.md; engine: engines/planner.py).
// Self-contained: own fetch helper + the shared console.css classes, so it touches no one else's files.
// Text: from t.console in i18n.js (Console passes t down); storm and equipment names go through t.tr.
// Everything here is a MODEL ESTIMATE for planning, never a confirmed restoration time. Real AEP data only:
// on the synthetic network both endpoints answer {available:false} and we show a clear "needs real data" note.
import React, { useEffect, useMemo, useState } from "react";
import createPlotlyComponent from "react-plotly.js/factory";
import Plotly from "plotly.js-dist-min";
import "./console.css";
import ThemedSelect from "../components/ThemedSelect.jsx";
import { STRINGS } from "../i18n.js";

// Same small prebuilt Plotly bundle the map uses (factory import keeps the build fast).
const Plot = createPlotlyComponent(Plotly);

// Local fetch helper (kept here, not imported from the customer client.js).
const get = (url) => fetch(url).then((r) => {
  if (!r.ok) throw new Error(`${url} failed: ${r.status}`);
  return r.json();
});

const ACCESS = ["normal", "limited", "blocked"];

// Read the live theme colors off the page so the Plotly chart matches light/dark. Without this the chart
// hard-coded one blue line and used Plotly's default near-black axis text, which is invisible on the dark
// panel. We pull the app's own CSS variables (set by App.jsx on <html data-theme>), so it always agrees
// with the rest of the UI and updates when the user flips the theme.
function chartColors() {
  const dark = document.documentElement.dataset.theme === "dark";
  const css = getComputedStyle(document.documentElement);
  const v = (name, fallback) => (css.getPropertyValue(name).trim() || fallback);
  return {
    line: v("--accent", dark ? "#8FB0FF" : "#1D4ED8"),   // the restoration curve
    text: v("--ink", dark ? "#E6EDF5" : "#14213D"),      // axis labels + ticks
    grid: v("--line", dark ? "#2F3D52" : "#D5DEE6"),     // gridlines
  };
}

// aside = extra content for the top of the right-hand column (the console's popup buttons).
// crews / crewSize / roads (+ setters) belong to the Console, so one set of knobs drives the whole console.
// replay = {stormId, label}: the real storm the customer's answer was compared with; it's selected automatically
// (by ID when the answer carries one, else by label). typical = milder than any replayable storm: no replay shown.
export default function PlannerPanel({ t = STRINGS.en, aside = null, replay = { stormId: null, label: null }, typical = false,
  crews = 20, setCrews = () => {}, crewSize = 3, setCrewSize = () => {}, roads = "normal", setRoads = () => {} }) {
  const c = t.console;
  // --- controls (the knobs an operator turns) ---
  const [stormId, setStormId] = useState(null);
  const roadAccess = roads;
  // --- data ---
  const [storms, setStorms] = useState(null);           // null = loading; [] = none / not available
  const [available, setAvailable] = useState(true);     // false on the synthetic network
  const [plan, setPlan] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // 1) Load the replayable storms once. If the backend is on synthetic data it returns available:false.
  useEffect(() => {
    get("/api/planner/storms").then((r) => {
      setAvailable(r.available);
      setStorms(r.storms ?? []);
      if (r.available && r.storms?.length) setStormId(r.storms[0].storm_id);   // default to the first (largest) storm
    }).catch((e) => setError(e.message));
  }, []);

  // 1b) Follow the customer's storm: select the replay storm the answer was compared with, when we can tell which.
  useEffect(() => {
    if (!storms?.length) return;
    const match = storms.find((x) => (replay.stormId && x.storm_id === replay.stormId) || (replay.label && x.label === replay.label));
    if (match) setStormId(match.storm_id);
  }, [replay.stormId, replay.label, storms]);

  // 2) Re-plan whenever a control changes. Debounced so dragging a slider doesn't spam the engine.
  useEffect(() => {
    if (!stormId || typical) return;
    setLoading(true);
    const t = setTimeout(() => {
      const q = `storm_id=${encodeURIComponent(stormId)}&crews=${crews}&crew_size=${crewSize}&road_access=${roadAccess}`;
      get(`/api/planner/plan?${q}`)
        .then((p) => { setPlan(p); setError(null); })
        .catch((e) => setError(e.message))
        .finally(() => setLoading(false));
    }, 250);
    return () => clearTimeout(t);
  }, [stormId, crews, crewSize, roadAccess, typical]);

  // Theme colors for the chart (recomputed each render, so flipping light/dark re-themes the curve).
  const ck = chartColors();

  // Restoration curve as one Plotly line trace (hour -> % of customers back).
  const curve = useMemo(() => {
    if (!plan?.restore_curve?.length) return null;
    return [{
      x: plan.restore_curve.map((d) => d.hour),
      y: plan.restore_curve.map((d) => d.pct_restored),
      type: "scatter", mode: "lines", line: { color: ck.line, width: 2 },
      hovertemplate: c.curveHover,
    }];
  }, [plan, ck.line, c]);

  // --- render ---
  if (available === false) {
    return (
      <section className="planner" aria-label={c.planTitle}>
        <h3>{c.planTitle}</h3>
        <p className="console-muted">{c.needsData} <code>make data</code> {c.needsData2}</p>
      </section>
    );
  }

  const fmtH = (h) => (h == null ? "—" : h >= 48 ? `${(h / 24).toFixed(1)} ${c.dayUnit}` : `${Math.round(h)} h`);

  return (
    <section className="planner" aria-label={c.planTitle}>
      <header className="console-head planner-head">
        <h3>{c.planTitle}</h3>
        <div className="console-knobs">
          {/* No replay storm to pick for a typical storm (milder than any replayable one). */}
          {!typical && <ThemedSelect label={c.storm} value={stormId} placeholder={c.loading} onChange={setStormId}
            options={(storms ?? []).map((s) => ({ value: s.storm_id, label: t.tr(s.label ?? s.storm_id) }))} />}
          <label>{c.crews(crews)}
            <input type="range" min="1" max="200" value={crews} onChange={(e) => setCrews(+e.target.value)} />
          </label>
          <label>{c.crewSize(crewSize)}
            <input type="range" min="2" max="8" value={crewSize} onChange={(e) => setCrewSize(+e.target.value)} />
          </label>
          <ThemedSelect label={c.roadAccess} value={roadAccess} onChange={setRoads}
            options={ACCESS.map((a) => ({ value: a, label: c.roads[a] }))} />
        </div>
      </header>

      {error && <p className="console-error" role="alert">{c.planError(error)}</p>}
      {/* Two columns that fit the screen: the restoration curve (left, large) and the details (right, scrolls
          on its own if it has to). */}
      <div className={`planner-split${loading ? " loading" : ""}`} aria-busy={loading}>
        <div className="planner-left">
          {typical ? <p className="planner-typical">{c.typicalNoReplay}</p> : !plan ? <p className="console-muted">{c.loadingPlan}</p> : (<>
            {/* Headline numbers: the scale of the storm and how long to full restoration. */}
            <div className="planner-headline">
              <div><span className="big">{plan.customers_out?.toLocaleString(t.locale)}</span><span>{c.customersOut}</span></div>
              <div><span className="big">{Math.round(plan.total_person_hours).toLocaleString(t.locale)}</span><span>{c.personHours}</span></div>
              <div><span className="big">{fmtH(plan.hours_to_restore?.all)}</span><span>{c.untilAll}</span></div>
              <div><span className="big">{plan.critical_devices}</span><span>{c.criticalAffected}</span></div>
            </div>
            {/* Restoration curve: % of customers restored over time. Fills the rest of the column. */}
            <div className="planner-curve">
              <h4>{c.curveTitle} <span className="console-muted">{c.curveNote}</span></h4>
              <div className="planner-plot">
                {curve && (
                  <Plot data={curve} useResizeHandler
                    layout={{
                      autosize: true, margin: { l: 44, r: 12, t: 8, b: 40 },
                      // Theme-aware: axis labels/ticks use --ink and gridlines use --line, so text stays readable
                      // on the dark panel (previously it defaulted to near-black and vanished in dark mode).
                      font: { color: ck.text },
                      xaxis: { title: c.hoursAxis, zeroline: false, color: ck.text, gridcolor: ck.grid },
                      yaxis: { range: [0, 100], ticksuffix: "%", color: ck.text, gridcolor: ck.grid },
                      paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
                    }}
                    config={{ displayModeBar: false, responsive: true }}
                    style={{ width: "100%", height: "100%" }} />)}
              </div>
            </div>
          </>)}
        </div>

        <div className="planner-right">
          {aside}
          {plan && !typical && (<>
            {/* Crews-needed to hit each target. crews_needed === null => target can't be met. */}
            <div className="planner-targets">
              <h4>{c.crewsNeeded}</h4>
              <table className="console-audit">
                <thead><tr>{c.targetCols.map((h) => <th key={h}>{h}</th>)}</tr></thead>
                <tbody>
                  {plan.targets?.map((tg) => (
                    <tr key={tg.days}>
                      <td>{c.target(tg.days)}</td>
                      <td>{tg.crews_needed ?? c.cantMeet}</td>
                      <td>{tg.people_needed ?? "—"}</td>
                      <td>{tg.crews_needed == null ? "—" : tg.met_with_current_crews ? c.metYes : c.metNo}</td>
                    </tr>))}
                </tbody>
              </table>
            </div>
            {/* First repairs the plan schedules, highest value first; critical facilities flagged. */}
            <div className="planner-jobs">
              <h4>{c.firstRepairs} <span className="console-muted">{c.firstRepairsNote}</span></h4>
              <ol className="console-order">
                {plan.first_jobs?.map((j) => (
                  <li key={j.order} className={j.feeds_critical_facility ? "critical" : ""}>
                    <strong>{t.tr(j.equipment)}</strong>{c.job(j.customers_behind_it?.toLocaleString(t.locale), j.person_hours, Math.round(j.first_crew_hour))}
                    {j.feeds_critical_facility && <span className="planner-crit">{c.critFlag}</span>}
                  </li>))}
              </ol>
            </div>
          </>)}
        </div>
      </div>
    </section>
  );
}
