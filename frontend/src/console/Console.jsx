// Utility operator console: READ-ONLY dashboard for AEP staff.   Owner: Jaid
// Self-contained on purpose: its own fetch helpers and styles, so it never touches Abby's files.
// Abby wires it in with ONE button in App.jsx:
//     import Console from "./console/Console.jsx";
//     {tab === "console" && <Console />}
// Data comes from app/console.py (GET /api/console/*). Everything here is a model estimate or a
// scenario what-if; it is never a confirmed restoration time and shows no premise-level locations.
import React, { useEffect, useState } from "react";
import "./console.css";

// Local fetch helper (kept here so we don't import from Abby's src/api/client.js).
const get = (url) => fetch(url).then((r) => {
  if (!r.ok) throw new Error(`${url} failed: ${r.status}`);
  return r.json();
});

const BAND_COLOR = { Low: "#2E7D32", Moderate: "#E3B23C", High: "#E8743B", "Very High": "#A4243B", Unknown: "#5B6B7A" };

export default function Console() {
  const [severity, setSeverity] = useState(85);
  const [crews, setCrews] = useState(20);
  const [circuits, setCircuits] = useState(null);
  const [selected, setSelected] = useState(null);
  const [order, setOrder] = useState(null);
  const [alerts, setAlerts] = useState(null);
  const [audit, setAudit] = useState(null);
  const [error, setError] = useState(null);

  // Circuit list is static (doesn't depend on the scenario), so fetch it once.
  useEffect(() => { get("/api/console/circuits").then(setCircuits).catch((e) => setError(e.message)); }, []);
  // Audit tail is independent of the scenario too.
  useEffect(() => { get("/api/console/audit?limit=15").then(setAudit).catch(() => {}); }, []);

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
        <h2>Operator console <span className="console-tag">read-only · model estimates</span></h2>
        <div className="console-knobs">
          <label>Storm severity: {severity}
            <input type="range" min="0" max="100" value={severity} onChange={(e) => setSeverity(+e.target.value)} />
          </label>
          <label>Crews: {crews}
            <input type="range" min="1" max="200" value={crews} onChange={(e) => setCrews(+e.target.value)} />
          </label>
        </div>
      </header>

      {error && <p className="console-error" role="alert">Couldn't reach the console API: {error}</p>}

      <div className="console-grid">
        {/* Alert queue summary + active escalations */}
        <article>
          <h3>Alert queue</h3>
          {!alerts ? <p className="console-muted">Loading…</p> : (<>
            <p>{alerts.pre_storm_circuits} of {alerts.circuits_evaluated} circuits meet the pre-storm alert threshold.</p>
            <ul className="console-bands">
              {Object.entries(alerts.risk_band_counts).map(([band, n]) => (
                <li key={band}><span className="dot" style={{ background: BAND_COLOR[band] ?? "#888" }} />{band}: {n}</li>
              ))}
            </ul>
            <h4>Active escalations</h4>
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
            <p className="console-muted">{order.representative_range}</p>
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
