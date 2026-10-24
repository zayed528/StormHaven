// StormHaven: map-first storm outage concierge. State lives here; components render.   Owner: Abby
import React, { useEffect, useRef, useState } from "react";
import OutageMap from "./components/OutageMap.jsx";
import ScenarioControls from "./components/ScenarioControls.jsx";
import ResultsPanel from "./components/ResultsPanel.jsx";
import ChatPanel from "./components/ChatPanel.jsx";
import { getConcierge, getHealth, getMap } from "./api/client.js";

// Text the simulated utility feed "confirms" when the demo toggle is on. Never produced by the model.
const DEMO_ETR = "Crews are assigned to your area. Utility-confirmed restoration time: by 9:00 PM tonight.";

export default function App() {
  const [layers, setLayers] = useState(null);
  const [health, setHealth] = useState(null);
  const [premise, setPremise] = useState(null);
  const [typed, setTyped] = useState("");
  const [scenario, setScenario] = useState({ severity_percentile: 60, crews_available: 20, road_access: "normal", extra_damage: [] });
  const [needs, setNeeds] = useState([]);
  const [enrolled, setEnrolled] = useState(true);
  const [utilityConfirmed, setUtilityConfirmed] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  // Last range shown, sent back as previous_range_text so the "estimate updated" message can say old -> new.
  // A ref (not state) because changing it must not trigger another request.
  const lastRange = useRef(null);

  // Only declared needs and channel TYPES are sent; no names, phone numbers, or addresses.
  const profile = { declared_needs: needs, alerts_enrolled: enrolled, channels: enrolled ? ["sms"] : [], language: "en" };

  // Once on load: find out whether we're on synthetic data (shows the banner).
  useEffect(() => { getHealth().then(setHealth).catch(() => {}); }, []);

  // Map colors depend only on storm strength, so refetch the map only when severity changes.
  useEffect(() => {
    getMap(scenario.severity_percentile).then((l) => { setLayers(l); setError(null); }).catch((e) => setError(e.message));
  }, [scenario.severity_percentile]);

  // Re-ask the backend whenever the location or any input changes. All numbers come from the API;
  // the frontend never computes risk or times itself.
  useEffect(() => {
    if (!premise) return;
    const t = setTimeout(() => {   // debounce slider drags
      getConcierge({
        premise_id: premise, scenario, profile,
        previous_range_text: lastRange.current,
        utility_status: utilityConfirmed ? { outage_confirmed: true, confirmed_etr: DEMO_ETR } : null,
      }).then((r) => {
        setResult(r); setError(null);
        lastRange.current = `${Math.round(r.restoration.p10_hours)}-${Math.round(r.restoration.p90_hours)} hours`;
      }).catch((e) => setError(e.message));
    }, 200);
    return () => clearTimeout(t);      // cancel the pending call if inputs change again within 200 ms
  }, [premise, scenario, needs, enrolled, utilityConfirmed]);   // eslint-disable-line react-hooks/exhaustive-deps

  const toggleNeed = (n) => setNeeds(needs.includes(n) ? needs.filter((x) => x !== n) : [...needs, n]);

  return (
    <div className="app">
      <header>
        <h1>StormHaven</h1>
        <p>Select your home on the map to see your storm outlook: outage risk, how long it could last, how to prepare, and alerts.</p>
        {health?.synthetic_data && <p className="banner">Demo network: synthetic data, not real AEP locations.</p>}
      </header>

      <ScenarioControls scenario={scenario} onScenario={setScenario} needs={needs} onToggleNeed={toggleNeed}
        enrolled={enrolled} onEnrolled={setEnrolled} utilityConfirmed={utilityConfirmed} onUtilityConfirmed={setUtilityConfirmed} />

      <form className="locate" onSubmit={(e) => { e.preventDefault(); if (typed.trim()) setPremise(typed.trim()); }}>
        <label htmlFor="premise-id">Or enter your premise ID</label>
        <input id="premise-id" value={typed} onChange={(e) => setTyped(e.target.value)} placeholder="e.g. P-31111" />
        <button type="submit">Look up</button>
      </form>

      <div className="map"><OutageMap layers={layers} selectedId={premise} onSelect={setPremise} /></div>

      {error && <p role="alert" className="error">Couldn't reach the outage service: {error}. Check that the API is running (make api).</p>}

      {result && <ResultsPanel result={result} />}

      <ChatPanel premiseId={premise} scenario={scenario} profile={profile} />
    </div>
  );
}
