// Utility operator console: READ-ONLY dashboard for AEP staff.   Owner: Abby (was Jaid)
// Self-contained on purpose: its own fetch helpers and styles, so it never touches Abby's files.
// Abby wires it in with ONE button in App.jsx:
//     import Console from "./console/Console.jsx";
//     {tab === "console" && <Console />}
// Text: from t.console in i18n.js (App passes the current language's t); backend phrases go through t.tr.
// Scenario: ONE-WAY from the customer view (App passes `customer` = {severity, crews, roads, whatIf} and `replay` =
// {stormId, label} for the real storm the customer's answer was compared with). The storm is shown, not chosen,
// here; the operator can try other crews / crew size / roads locally, and any change to the customer's scenario
// resets those back to the customer's values.
// Data comes from app/console.py (GET /api/console/*). Everything here is a model estimate or a
// scenario what-if; it is never a confirmed restoration time and shows no premise-level locations.
import React, { useEffect, useRef, useState } from "react";
import PlannerPanel from "./PlannerPanel.jsx";       // storm restoration plan (GET /api/planner/*)
import "./console.css";
import { STRINGS } from "../i18n.js";
import ThemedSelect from "../components/ThemedSelect.jsx";

// Local fetch helper (kept here so we don't import from Abby's src/api/client.js).
const get = (url) => fetch(url).then((r) => {
  if (!r.ok) throw new Error(`${url} failed: ${r.status}`);
  return r.json();
});

// Same 4 storm strengths as the customer view (ScenarioControls.jsx). Labels: t.stormLevels[i].label.
const STORM_LEVELS = [50, 95, 97, 99];
const levelFor = (pct) => STORM_LEVELS.reduce((best, p, i) =>
  (Math.abs(p - pct) < Math.abs(STORM_LEVELS[best] - pct) ? i : best), 0);
const DEFAULT_CREW_SIZE = 3;                      // config restoration.crew_size_persons
const BAND_ORDER = ["Very High", "High", "Moderate", "Low"];

const BAND_COLOR = { Low: "#2E7D32", Moderate: "#E3B23C", High: "#E8743B", "Very High": "#A4243B", Unknown: "#5B6B7A" };

export default function Console({ t = STRINGS.en, customer = { severity: 97, crews: 20, roads: "normal", whatIf: false },
  replay = { stormId: null, label: null } }) {
  const c = t.console;
  const severity = customer.severity;               // from the customer view; not changeable here
  const level = levelFor(severity);
  const typical = level === 0;                      // milder than any storm the planner can replay
  // The operator's planning knobs start at the customer's values; one set drives everything in the console.
  const [crews, setCrews] = useState(customer.crews);
  const [crewSize, setCrewSize] = useState(DEFAULT_CREW_SIZE);
  const [roads, setRoads] = useState(customer.roads);
  const resetToCustomer = () => { setCrews(customer.crews); setCrewSize(DEFAULT_CREW_SIZE); setRoads(customer.roads); };
  // The customer changed their scenario: start again from it (the operator's tweaks are dropped).
  useEffect(resetToCustomer, [customer.severity, customer.crews, customer.roads]);   // eslint-disable-line react-hooks/exhaustive-deps
  const differs = crews !== customer.crews || crewSize !== DEFAULT_CREW_SIZE || roads !== customer.roads;
  const [circuits, setCircuits] = useState(null);
  const [selected, setSelected] = useState(null);
  const [order, setOrder] = useState(null);
  const [alerts, setAlerts] = useState(null);
  const [audit, setAudit] = useState(null);
  const [error, setError] = useState(null);
  const [panel, setPanel] = useState(null);        // open popup: "alerts" | "order" | "audit" | null
  const opener = useRef(null);                     // the button that opened it (focus returns there)
  const drawer = useRef(null);

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
      get(`/api/console/alerts?severity=${severity}&crews=${crews}&road_access=${roads}`).then(setAlerts).catch((e) => setError(e.message));
    }, 250);
    return () => clearTimeout(t);
  }, [severity, crews, roads]);

  // Popup: focus moves into it when it opens; Esc closes it and focus goes back to its button.
  useEffect(() => {
    if (!panel) return;
    drawer.current?.focus();
    const onKey = (e) => { if (e.key === "Escape" && !e.defaultPrevented) closePanel(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [panel]);   // eslint-disable-line react-hooks/exhaustive-deps
  const openPanel = (name, e) => { opener.current = e.currentTarget; setPanel(name); };
  const closePanel = () => { setPanel(null); opener.current?.focus(); };

  // Restoration order for the selected circuit.
  useEffect(() => {
    if (!selected) { setOrder(null); return; }
    get(`/api/console/restoration/${encodeURIComponent(selected)}?severity=${severity}&crews=${crews}`)
      .then(setOrder).catch((e) => setError(e.message));
  }, [selected, severity, crews]);

  // The three detail panels (shown one at a time, in the popup).
  const panels = {
    alerts: { title: c.alertQueue, badge: alerts ? alerts.homes_pre_storm.toLocaleString(t.locale) : null, body: (
      !alerts ? <p className="console-muted">{c.loading}</p> : (<>
        <p><strong>{alerts.homes_pre_storm.toLocaleString(t.locale)}</strong>{c.preStorm(alerts.homes_total.toLocaleString(t.locale),
          alerts.pre_storm_circuits, alerts.circuits_evaluated, (t.bands[alerts.pre_storm_threshold] ?? alerts.pre_storm_threshold).toLowerCase())}</p>
        <h4>{c.homesByBand}</h4>
        <ul className="console-bands">
          {BAND_ORDER.filter((b) => alerts.homes_by_band[b]).map((band) => (
            <li key={band}><span className="dot" style={{ background: BAND_COLOR[band] ?? "#888" }} />
              {c.bandHomes(t.bands[band] ?? band, alerts.homes_by_band[band].toLocaleString(t.locale))}
              <span className="console-muted">{c.worst(alerts.risk_band_counts[band] ?? 0)}</span></li>
          ))}
        </ul>
        <h4>{c.escalations} <span className="console-muted">{c.escalationsNote}</span></h4>
        {alerts.active_escalations.length === 0 ? <p className="console-muted">{c.noEscalations}</p> : (
          <ul>{alerts.active_escalations.map((e, i) => (
            <li key={i}>{t.tr(e.trigger)} <strong>({e.circuits})</strong></li>))}</ul>)}
      </>)) },
    order: { title: c.restorationOrder, badge: order ? order.total_devices : null, body: (<>
      <ThemedSelect label={c.circuit} value={selected} placeholder={c.selectCircuit} onChange={setSelected}
        options={(circuits?.circuits ?? []).map((cc) => ({ value: cc.circuit_id, label: c.circuitOption(cc.circuit_id, cc.customers, cc.critical_zones) }))} />
      {order && (<>
        <p className="console-muted">{c.typicalHome(Math.round(order.p10_hours), Math.round(order.p90_hours),
          Math.round(order.p50_hours), order.order.length, order.total_devices)}</p>
        <ol className="console-order">
          {order.order.map((o) => (
            <li key={o.rank} className={o.feeds_critical ? "critical" : ""}>
              {t.tr(o.equipment)}{c.restored(o.customers_restored)}{o.feeds_critical ? c.feedsCritical : ""}
            </li>))}
        </ol>
      </>)}
    </>) },
    audit: { title: c.auditShort, badge: audit ? audit.count : null, body: (<>
      {!audit ? <p className="console-muted">{c.loading}</p> : audit.count === 0 ? (
        <p className="console-muted">{c.noPredictions}</p>
      ) : (
        <table className="console-audit">
          <thead><tr>{c.auditCols.map((h) => <th key={h}>{h}</th>)}</tr></thead>
          <tbody>
            {audit.records.map((r) => (
              <tr key={r.audit_id}>
                <td>{r.audit_id?.slice(0, 6)}</td>
                <td><span className="dot" style={{ background: BAND_COLOR[r.band] ?? "#888" }} />{t.bands[r.band] ?? r.band}</td>
                <td>{t.conf[r.confidence] ?? r.confidence}</td>
                <td>{r.p10_hours}–{r.p90_hours}</td>
                <td>{r.alert_eligible ? c.yes : c.no}</td>
              </tr>))}
          </tbody>
        </table>
      )}
      <p className="console-muted">{c.modelVersion(audit?.records?.[0]?.model_version ?? "—")}</p>
    </>) },
  };

  // Buttons that open the popups; they sit at the top of the planner's right-hand column.
  const popupButtons = (
    <div className="console-popups" role="group" aria-label={c.detailsAria}>
      {Object.entries(panels).map(([name, p]) => (
        <button key={name} type="button" aria-haspopup="dialog" aria-expanded={panel === name}
          onClick={(e) => openPanel(name, e)}>
          <span>{p.title}</span>{p.badge != null && <span className="console-badge">{p.badge}</span>}
        </button>))}
    </div>
  );

  return (
    <section className="console console-fit" aria-label={c.aria}>
      <header className="console-head">
        <h2>{c.title}</h2>
        {/* The scenario comes from the customer view (read-only here), plus a note when the operator is testing
            different crews / crew size / roads, with a way back. */}
        <div className="console-scenario" role="status">
          {/* The storm type is the point of this chip: big, bold, with its color dot; where it came from is small. */}
          <span className="console-scenario-chip">
            <span className="chip-label">{c.scenarioFromLabel}</span>
            <span className={`chip-storm lvl-${level}`}>{t.stormLevels[level].label}</span>
            <span className={`chip-src${customer.whatIf ? " is-whatif" : ""}`}>{customer.whatIf ? c.sourceWhatIf : c.sourceForecast}</span>
          </span>
          {differs && (
            <span className="console-muted">{c.customerAssumes(customer.crews, c.roads[customer.roads])}{" "}
              <button type="button" className="link-button" onClick={resetToCustomer}>{c.resetToCustomer}</button></span>)}
        </div>
      </header>

      {error && <p className="console-error" role="alert">{c.apiError(error)}</p>}

      {/* Storm restoration plan: replay a real storm, size the crews, see the restoration curve. */}
      <PlannerPanel t={t} aside={popupButtons} replay={replay} typical={typical}
        crews={crews} setCrews={setCrews} crewSize={crewSize} setCrewSize={setCrewSize} roads={roads} setRoads={setRoads} />

      {/* Popup: slides in from the right over the console; click outside, x, or Esc closes it. */}
      {panel && (<>
        <div className="console-backdrop" onClick={closePanel} aria-hidden="true" />
        <div className="console-drawer" role="dialog" aria-modal="true" aria-labelledby="console-drawer-title"
          tabIndex={-1} ref={drawer}>
          <div className="console-drawer-head">
            <h3 id="console-drawer-title">{panels[panel].title}</h3>
            <button type="button" className="console-drawer-close" onClick={closePanel} aria-label={t.closeResults}>×</button>
          </div>
          <div className="console-drawer-body">{panels[panel].body}</div>
        </div>
      </>)}
    </section>
  );
}
