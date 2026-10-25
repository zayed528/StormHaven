// Utility operator console: READ-ONLY dashboard for AEP staff.   Owner: Abby (was Jaid)
// Self-contained on purpose: its own fetch helpers and styles, so it never touches Abby's files.
// Abby wires it in with ONE button in App.jsx:
//     import Console from "./console/Console.jsx";
//     {tab === "console" && <Console />}
// Data comes from app/console.py (GET /api/console/*). Everything here is a model estimate or a
// scenario what-if; it is never a confirmed restoration time and shows no premise-level locations.
import React, { useEffect, useState } from "react";
import PlannerPanel from "./PlannerPanel.jsx";       // storm restoration plan (GET /api/planner/*)
import "./console.css";

// Local fetch helper (kept here so we don't import from Abby's src/api/client.js).
const get = (url) => fetch(url).then((r) => {
  if (!r.ok) throw new Error(`${url} failed: ${r.status}`);
  return r.json();
});

// Same 4 storm levels as the customer view (ScenarioControls.jsx), so both screens talk about the same storm.
const STORM_LEVELS = [[50, "Low risk"], [95, "Moderate risk"], [97, "High risk"], [99, "Extremely high risk"]];
const BAND_ORDER = ["Very High", "High", "Moderate", "Low"];

const BAND_COLOR = { Low: "#2E7D32", Moderate: "#E3B23C", High: "#E8743B", "Very High": "#A4243B", Unknown: "#5B6B7A" };

export default function Console() {
  const [level, setLevel] = useState(2);           // index into STORM_LEVELS (starts at High risk, like the customer view)
  const severity = STORM_LEVELS[level][0];
  const [crews, setCrews] = useState(20);
  const [circuits, setCircuits] = useState(null);
  const [selected, setSelected] = useState(null);
  const [order, setOrder] = useState(null);
  const [alerts, setAlerts] = useState(null);
  const [audit, setAudit] = useState(null);
  const [error, setError] = useState(null);

  // Circuit list is static (doesn't depend on the scenario), so fetch it once.
  useEffect(() => { get("/api/console/circuits").then(setCircuits).catch((e) => setError(e.message)); }, []);
  // Audit tail: refresh every 10 s so predictions made in the customer view show up without a reload.
  useEffect(() => {
    const load = () => get("/api/console/audit?limit=15").then(setAudit).catch(() => {});
    load();
    const timer = setInterval(load, 10000);
    return () => clearInterval(timer);
  }, []);

  // Alert queue + escalations recompute when the scenario changes (debounced for slider drags).
  useEffect(() => {
    const t = setTimeout(() => {
      get(`/api/console/alerts?severity=${severity}&crews=${crews}`).then(setAlerts).catch((e) => setError(e.message));
    }, 250);
    return () => clearTimeout(t);
  }, [severity, crews]);

  // Restoration order for the selected circuit.
  useEffect(() => {
    if (!selected) { setOrder(null); return; }
    get(`/api/console/restoration/${encodeURIComponent(selected)}?severity=${severity}&crews=${crews}`)
      .then(setOrder).catch((e) => setError(e.message));
  }, [selected, severity, crews]);

  return (
    <section className="console" aria-label="Utility operator console">
      <header className="console-head">
        <h2>Operator console</h2>
        <div className="console-knobs">
          <label>Storm level: <strong>{STORM_LEVELS[level][1]}</strong>
            <input type="range" min="0" max={STORM_LEVELS.length - 1} step="1" value={level}
              onChange={(e) => setLevel(+e.target.value)} aria-valuetext={STORM_LEVELS[level][1]} />
          </label>
          <label>Crews: {crews}
            <input type="range" min="1" max="200" value={crews} onChange={(e) => setCrews(+e.target.value)} />
          </label>
        </div>
      </header>

      {error && <p className="console-error" role="alert">Couldn't reach the console API: {error}</p>}

      {/* Storm restoration plan: replay a real storm, size the crews, see the restoration curve. */}
      <PlannerPanel />

      <div className="console-grid">
        {/* Alert queue summary + active escalations */}
        <article>
          <h3>Alert queue</h3>
          {!alerts ? <p className="console-muted">Loading…</p> : (<>
            <p><strong>{alerts.homes_pre_storm.toLocaleString()}</strong> of {alerts.homes_total.toLocaleString()} homes
              ({alerts.pre_storm_circuits} of {alerts.circuits_evaluated} circuits) get a pre-storm alert
              (risk {alerts.pre_storm_threshold} or higher).</p>
            <h4>Homes by risk band</h4>
            <ul className="console-bands">
              {BAND_ORDER.filter((b) => alerts.homes_by_band[b]).map((band) => (
                <li key={band}><span className="dot" style={{ background: BAND_COLOR[band] ?? "#888" }} />
                  {band}: {alerts.homes_by_band[band].toLocaleString()} homes
                  <span className="console-muted"> · {alerts.risk_band_counts[band] ?? 0} circuits at worst</span></li>
              ))}
            </ul>
            <h4>Active escalations <span className="console-muted">(circuits; medical = if a customer there declared one)</span></h4>
            {alerts.active_escalations.length === 0 ? <p className="console-muted">None under this scenario.</p> : (
              <ul>{alerts.active_escalations.map((e, i) => (
                <li key={i}>{e.trigger} <strong>({e.circuits})</strong></li>))}</ul>)}
          </>)}
        </article>

        {/* Circuit picker + restoration order */}
        <article>
          <h3>Restoration order</h3>
          <label className="console-muted">Circuit
            <select value={selected ?? ""} onChange={(e) => setSelected(e.target.value || null)}>
              <option value="">Select a circuit…</option>
              {circuits?.circuits.map((c) => (
                <option key={c.circuit_id} value={c.circuit_id}>
                  {c.circuit_id} — {c.customers} customers{c.critical_zones ? ` · ${c.critical_zones} critical` : ""}
                </option>))}
            </select>
          </label>
          {order && (<>
            <p className="console-muted">Typical home on this circuit: {Math.round(order.p10_hours)}–{Math.round(order.p90_hours)} h
              (best guess {Math.round(order.p50_hours)} h). Showing the first {order.order.length} of {order.total_devices} devices.</p>
            <ol className="console-order">
              {order.order.map((o) => (
                <li key={o.rank} className={o.feeds_critical ? "critical" : ""}>
                  {o.equipment} — {o.customers_restored} customers{o.feeds_critical ? " · feeds a critical facility" : ""}
                </li>))}
            </ol>
          </>)}
        </article>

        {/* Audit log tail */}
        <article>
          <h3>Audit log (latest predictions)</h3>
          {!audit ? <p className="console-muted">Loading…</p> : audit.count === 0 ? (
            <p className="console-muted">No predictions logged yet.</p>
          ) : (
            <table className="console-audit">
              <thead><tr><th>ID</th><th>Band</th><th>Conf.</th><th>P10–P90 h</th><th>Alert</th></tr></thead>
              <tbody>
                {audit.records.map((r) => (
                  <tr key={r.audit_id}>
                    <td>{r.audit_id?.slice(0, 6)}</td>
                    <td><span className="dot" style={{ background: BAND_COLOR[r.band] ?? "#888" }} />{r.band}</td>
                    <td>{r.confidence}</td>
                    <td>{r.p10_hours}–{r.p90_hours}</td>
                    <td>{r.alert_eligible ? "yes" : "no"}</td>
                  </tr>))}
              </tbody>
            </table>
          )}
          <p className="console-muted">Model version {audit?.records?.[0]?.model_version ?? "—"}. IDs truncated; no customer data shown.</p>
        </article>
      </div>
    </section>
  );
}
