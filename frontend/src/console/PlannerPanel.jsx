// Storm restoration PLAN panel (operator view).   Owner: Abby
// Backs GET /api/planner/storms + /api/planner/plan (contract in docs/API_CONTRACT.md; engine: engines/planner.py).
// Self-contained: own fetch helper + the shared console.css classes, so it touches no one else's files.
// Everything here is a MODEL ESTIMATE for planning, never a confirmed restoration time. Real AEP data only:
// on the synthetic network both endpoints answer {available:false} and we show a clear "needs real data" note.
import React, { useEffect, useMemo, useState } from "react";
import createPlotlyComponent from "react-plotly.js/factory";
import Plotly from "plotly.js-dist-min";
import "./console.css";

// Same small prebuilt Plotly bundle the map uses (factory import keeps the build fast).
const Plot = createPlotlyComponent(Plotly);

// Local fetch helper (kept here, not imported from the customer client.js).
const get = (url) => fetch(url).then((r) => {
  if (!r.ok) throw new Error(`${url} failed: ${r.status}`);
  return r.json();
});

const ACCESS = ["normal", "limited", "blocked"];

export default function PlannerPanel() {
  // --- controls (the knobs an operator turns) ---
  const [stormId, setStormId] = useState(null);
  const [crews, setCrews] = useState(20);
  const [crewSize, setCrewSize] = useState(3);          // AEP guide: 2-8 people per crew
  const [roadAccess, setRoadAccess] = useState("normal");
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

  // 2) Re-plan whenever a control changes. Debounced so dragging a slider doesn't spam the engine.
  useEffect(() => {
    if (!stormId) return;
    setLoading(true);
    const t = setTimeout(() => {
      const q = `storm_id=${encodeURIComponent(stormId)}&crews=${crews}&crew_size=${crewSize}&road_access=${roadAccess}`;
      get(`/api/planner/plan?${q}`)
        .then((p) => { setPlan(p); setError(null); })
        .catch((e) => setError(e.message))
        .finally(() => setLoading(false));
    }, 250);
    return () => clearTimeout(t);
  }, [stormId, crews, crewSize, roadAccess]);

  // Restoration curve as one Plotly line trace (hour -> % of customers back).
  const curve = useMemo(() => {
    if (!plan?.restore_curve?.length) return null;
    return [{
      x: plan.restore_curve.map((d) => d.hour),
      y: plan.restore_curve.map((d) => d.pct_restored),
      type: "scatter", mode: "lines", line: { color: "#1D4ED8", width: 2 },
      hovertemplate: "%{y:.0f}% back by hour %{x:.0f}<extra></extra>",
    }];
  }, [plan]);

  // --- render ---
  if (available === false) {
    return (
      <section className="planner" aria-label="Storm restoration plan">
        <h3>Storm restoration plan</h3>
        <p className="console-muted">Storm replay needs the real AEP network. Run <code>make data</code> and
          restart the API, then reload.</p>
      </section>
    );
  }

  const fmtH = (h) => (h == null ? "—" : h >= 48 ? `${(h / 24).toFixed(1)} d` : `${Math.round(h)} h`);

  return (
    <section className="planner" aria-label="Storm restoration plan">
      <header className="console-head">
        <h3>Storm restoration plan <span className="console-tag">read-only · model estimate</span></h3>
        <div className="console-knobs">
          <label>Storm
            <select value={stormId ?? ""} onChange={(e) => setStormId(e.target.value || null)}>
              {storms === null && <option>Loading…</option>}
              {storms?.map((s) => (
                <option key={s.storm_id} value={s.storm_id}>{s.label ?? s.storm_id}</option>))}
            </select>
          </label>
          <label>Crews: {crews}
            <input type="range" min="1" max="200" value={crews} onChange={(e) => setCrews(+e.target.value)} />
          </label>
          <label>Crew size: {crewSize}
            <input type="range" min="2" max="8" value={crewSize} onChange={(e) => setCrewSize(+e.target.value)} />
          </label>
          <label>Road access
            <select value={roadAccess} onChange={(e) => setRoadAccess(e.target.value)}>
              {ACCESS.map((a) => <option key={a} value={a}>{a}</option>)}
            </select>
          </label>
        </div>
      </header>

      {error && <p className="console-error" role="alert">Couldn't reach the planner: {error}</p>}
      {!plan ? <p className="console-muted">Loading plan…</p> : (
        <div className={loading ? "planner-body loading" : "planner-body"} aria-busy={loading}>
          {/* Headline numbers: the scale of the storm and how long to full restoration. */}
          <div className="planner-headline">
            <div><span className="big">{plan.customers_out?.toLocaleString()}</span><span>customers out</span></div>
            <div><span className="big">{Math.round(plan.total_person_hours).toLocaleString()}</span><span>person-hours of work</span></div>
            <div><span className="big">{fmtH(plan.hours_to_restore?.all)}</span><span>until everyone is back</span></div>
            <div><span className="big">{plan.critical_devices}</span><span>critical facilities affected</span></div>
          </div>

          {/* Restoration curve: % of customers restored over time. */}
          <div className="planner-curve">
            <h4>Restoration over time <span className="console-muted">(% of customers back)</span></h4>
            {curve && (
              <Plot data={curve}
                layout={{
                  height: 220, margin: { l: 40, r: 10, t: 6, b: 34 },
                  xaxis: { title: "hours", zeroline: false }, yaxis: { range: [0, 100], ticksuffix: "%" },
                  paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
                }}
                config={{ displayModeBar: false, responsive: true }}
                style={{ width: "100%" }} />)}
          </div>

          {/* Crews-needed to hit each target. crews_needed === null => target can't be met. */}
          <div className="planner-targets">
            <h4>Crews needed to restore everyone by…</h4>
            <table className="console-audit">
              <thead><tr><th>Target</th><th>Crews</th><th>People</th><th>With current crews?</th></tr></thead>
              <tbody>
                {plan.targets?.map((t) => (
                  <tr key={t.days}>
                    <td>{t.days === 7 ? "1 week" : `${t.days} days`}</td>
                    <td>{t.crews_needed ?? "can't be met"}</td>
                    <td>{t.people_needed ?? "—"}</td>
                    <td>{t.crews_needed == null ? "—" : t.met_with_current_crews ? "✅ yes" : "❌ need more"}</td>
                  </tr>))}
              </tbody>
            </table>
          </div>

          {/* First repairs the plan schedules, highest value first; critical facilities flagged. */}
          <div className="planner-jobs">
            <h4>First repairs <span className="console-muted">(most customers restored first)</span></h4>
            <ol className="console-order">
              {plan.first_jobs?.map((j) => (
                <li key={j.order} className={j.feeds_critical_facility ? "critical" : ""}>
                  <strong>{j.equipment}</strong> — {j.customers_behind_it?.toLocaleString()} customers · {j.person_hours} person-h
                  · crews start ~h{Math.round(j.first_crew_hour)}
                  {j.feeds_critical_facility && <span className="planner-crit"> ⚑ feeds a critical facility</span>}
                </li>))}
            </ol>
          </div>
        </div>
      )}
    </section>
  );
}
