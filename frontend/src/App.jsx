// StormHaven: map-first storm outage concierge. State lives here; components render.   Owner: Nandan (was Abby)
import React, { useEffect, useRef, useState } from "react";
import { flushSync } from "react-dom";
import OutageMap from "./components/OutageMap.jsx";
import ScenarioControls from "./components/ScenarioControls.jsx";
import ResultsPanel from "./components/ResultsPanel.jsx";
import ChatPanel from "./components/ChatPanel.jsx";
import Console from "./console/Console.jsx";          // Abby's utility console (fetches its own data)
import OnboardingStandIn from "./components/OnboardingStandIn.jsx";
import { getConcierge, getHealth, getMap, getWeather } from "./api/client.js";
import { STRINGS, fmtRange } from "./i18n.js";

// Onboarding (first screen): Abby's onboarding/Onboarding.jsx as soon as that file exists, else the stand-in.
// import.meta.glob finds nothing (instead of failing the build) while her file isn't merged yet.
const ONBOARDING = import.meta.glob("./onboarding/Onboarding.jsx", { eager: true });
const Onboarding = ONBOARDING["./onboarding/Onboarding.jsx"]?.default ?? OnboardingStandIn;
const NEIGHBORHOOD_ZOOM = 14;   // map zoom for "your neighborhood" (same as /api/locate's hint)

// Theme: the visitor's saved choice, else their computer's setting. index.html applies the same rule before the
// first paint, so there is no white flash; this keeps React in sync with it. Storage can be blocked: ignore errors.
const THEME_KEY = "stormhaven-theme";
function initialTheme() {
  try { const saved = localStorage.getItem(THEME_KEY); if (saved === "light" || saved === "dark") return saved; } catch { /* blocked */ }
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

// Theme switch icons (inline SVG, so they look the same on every computer, unlike emoji).
const SunIcon = () => (
  <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2"
    strokeLinecap="round">
    <circle cx="12" cy="12" r="4.5" />
    <path d="M12 2v2.5M12 19.5V22M2 12h2.5M19.5 12H22M4.9 4.9l1.8 1.8M17.3 17.3l1.8 1.8M4.9 19.1l1.8-1.8M17.3 6.7l1.8-1.8" />
  </svg>
);
const MoonIcon = () => (
  <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2"
    strokeLinecap="round" strokeLinejoin="round">
    <path d="M20.5 14.5A8.5 8.5 0 0 1 9.5 3.5a8.5 8.5 0 1 0 11 11z" />
  </svg>
);

export default function App() {
  const [layers, setLayers] = useState(null);
  const [health, setHealth] = useState(null);
  const [weather, setWeather] = useState(null);
  const [premise, setPremise] = useState(null);
  const [typed, setTyped] = useState("");
  const [scenario, setScenario] = useState({ severity_percentile: 97, crews_available: 20, road_access: "normal", extra_damage: [] });
  const [needs, setNeeds] = useState([]);
  const [enrolled, setEnrolled] = useState(true);
  const [utilityConfirmed, setUtilityConfirmed] = useState(false);
  const [lang, setLang] = useState("en");          // UI language; also profile.language (localized SMS messages)
  const [view, setView] = useState("customer");    // "customer" | "console"
  const [theme, setTheme] = useState(initialTheme); // "light" | "dark"
  const [result, setResult] = useState(null);
  const [changes, setChanges] = useState(null);    // what moved vs. the previous answer, for the highlight
  const [error, setError] = useState(null);
  const [onboarding, setOnboarding] = useState(true);   // first screen until the customer finishes (or skips) it
  const [focus, setFocus] = useState(null);            // {lat, lon, zoom, key}: zoom the map to the customer's area
  const t = STRINGS[lang];
  // The last answer shown for THIS location: its range + the scenario behind it. Sent back so the
  // "estimate updated" message can say old -> new and give the real reason. Refs (not state) because
  // updating them must not trigger another request. Reset when the location or language changes.
  const last = useRef({ premise: null, range: null, scenario: null, result: null });
  // The previous_* values behind the answer on screen, so "Send as text" can send the same comparison.
  const shownPrev = useRef({ range: null, scenario: null });
  // Set when a location is chosen with the keyboard (premise ID form): move focus to the answer when it arrives.
  const focusResults = useRef(false);
  // Set when a location is ENTERED (onboarding or premise ID box) without a zoom target: when the answer arrives,
  // zoom to the dot it names (map_point_id). Clicking a dot doesn't zoom: the customer is already looking at it.
  const zoomToResult = useRef(false);

  // Only declared needs and channel TYPES are sent; no names, phone numbers, or addresses.
  const profile = { declared_needs: needs, alerts_enrolled: enrolled, channels: enrolled ? ["sms"] : [], language: lang };
  const utilityStatus = utilityConfirmed ? { outage_confirmed: true, confirmed_etr: t.demoEtr } : null;

  // Theme: stamp it on <html> (styles.css switches every color on data-theme) and remember the choice.
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem(THEME_KEY, theme); } catch { /* blocked: the choice just lasts this visit */ }
  }, [theme]);

  // Switching themes: the new theme spreads in a circle from the button that was clicked (View Transitions API).
  // Browsers without it, and people who turn off animations, get the instant switch.
  const switchTheme = (code, e) => {
    if (code === theme) return;
    const apply = () => {
      document.documentElement.dataset.theme = code;   // paint the new colors now, so the "after" snapshot has them
      flushSync(() => setTheme(code));
    };
    if (!document.startViewTransition || window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) { apply(); return; }
    const r = e.currentTarget.getBoundingClientRect();
    const x = r.left + r.width / 2, y = r.top + r.height / 2;
    const radius = Math.hypot(Math.max(x, window.innerWidth - x), Math.max(y, window.innerHeight - y));
    document.startViewTransition(apply).ready.then(() => {
      document.documentElement.animate(
        { clipPath: [`circle(0px at ${x}px ${y}px)`, `circle(${radius}px at ${x}px ${y}px)`] },
        { duration: 600, easing: "cubic-bezier(.4, 0, .2, 1)", pseudoElement: "::view-transition-new(root)" });
    }).catch(() => {});
  };

  // Once on load: find out whether we're on synthetic data (shows the banner).
  useEffect(() => { getHealth().then(setHealth).catch(() => {}); }, []);
  // Weather reference storms label the storm slider ("Similar to the Feb 2025 storm..."). Optional: failures are ignored.
  useEffect(() => { getWeather().then(setWeather).catch(() => {}); }, []);

  // Language switch: tell screen readers / the browser, and forget the last answer. range_short is localized
  // ("6-24 hours" vs "6-24 horas"), so comparing across languages would fake an "estimate updated" message.
  useEffect(() => {
    document.documentElement.lang = lang;
    last.current = { premise: null, range: null, scenario: null, result: null };
    setChanges(null);
  }, [lang]);

  // Plotly measures its box while hidden as 0 px; nudge it to re-measure when the customer view comes back.
  useEffect(() => {
    if (view === "customer" && !onboarding) setTimeout(() => window.dispatchEvent(new Event("resize")), 50);
  }, [view, onboarding]);

  // Zoom to the customer's neighborhood once their answer names the map dot (when no zoom target was given).
  useEffect(() => {
    if (!zoomToResult.current || !result?.map_point_id || !layers) return;
    const dot = layers.premises.find((p) => p.id === result.map_point_id);
    zoomToResult.current = false;
    if (dot) setFocus({ lat: dot.lat, lon: dot.lon, zoom: NEIGHBORHOOD_ZOOM, key: Date.now() });
  }, [result, layers]);

  // Onboarding finished (contract: onboarding/Onboarding.jsx). Feed it into the state the app already has.
  const onboarded = (p) => {
    if (p.language === "en" || p.language === "es") setLang(p.language);
    setNeeds(p.declared_needs ?? []);
    setEnrolled(!!p.alerts_enrolled);
    setTyped(p.premise_id);
    setPremise(p.premise_id);
    if (p.center) setFocus({ lat: p.center.lat, lon: p.center.lon, zoom: p.zoom ?? NEIGHBORHOOD_ZOOM, key: Date.now() });
    else zoomToResult.current = true;
    focusResults.current = true;
    setOnboarding(false);
  };
  // "Start over": back to onboarding with a clean slate and the whole-territory map.
  const restart = () => {
    setPremise(null); setResult(null); setChanges(null); setTyped(""); setFocus(null);
    last.current = { premise: null, range: null, scenario: null, result: null };
    setOnboarding(true);
  };

  // Map colors depend only on storm strength, so refetch the map only when severity changes.
  // Debounced: the real-data map is ~1 MB and takes ~1 s, so don't fire on every slider tick.
  useEffect(() => {
    const tm = setTimeout(() => {
      getMap(scenario.severity_percentile).then((l) => { setLayers(l); setError(null); }).catch((e) => setError(e.message));
    }, 300);
    return () => clearTimeout(tm);
  }, [scenario.severity_percentile]);

  // Re-ask the backend whenever the location or any input changes. All numbers come from the API;
  // the frontend never computes risk or times itself.
  useEffect(() => {
    if (!premise) return;
    const tm = setTimeout(() => {   // debounce slider drags
      const prev = last.current.premise === premise ? last.current : { range: null, scenario: null, result: null };
      getConcierge({
        premise_id: premise, scenario, profile,
        previous_range_text: prev.range, previous_scenario: prev.scenario,
        utility_status: utilityStatus,
      }).then((r) => {
        setChanges(diff(prev.result, r));
        setResult(r); setError(null);
        shownPrev.current = { range: prev.range, scenario: prev.scenario };
        last.current = { premise, range: r.restoration.range_short, scenario, result: r };
        if (focusResults.current) {
          focusResults.current = false;
          setTimeout(() => document.getElementById("results")?.focus(), 0);
        }
      }).catch((e) => setError(e.message));
    }, 200);
    return () => clearTimeout(tm);      // cancel the pending call if inputs change again within 200 ms
  }, [premise, scenario, needs, enrolled, utilityConfirmed, lang]);   // eslint-disable-line react-hooks/exhaustive-deps

  const toggleNeed = (n) => setNeeds(needs.includes(n) ? needs.filter((x) => x !== n) : [...needs, n]);

  // One short sentence for screen readers when the estimate moves (the panel itself isn't a live region).
  const summary = changes ? t.changedSummary([
    changes.band && t.changedBand(t.bands[changes.band], t.bands[result.risk.band]),
    changes.range && t.changedRange(fmtRange(changes.range, t), fmtRange(result.restoration, t)),
  ].filter(Boolean).join("; ")) : "";

  return (
    <div className="app">
      {/* First Tab stop: the map can't be used from a keyboard, so jump straight to the premise ID box. */}
      {!onboarding && <a className="skip-link" href="#premise-id">{t.skipToLookup}</a>}
      <header>
        <div className="header-row">
          <h1>StormHaven</h1>
          <div className="header-actions">
            {/* Both options always visible; the current one is filled in (and aria-pressed for screen readers). */}
            <div className="lang-switch" role="group" aria-label={t.languageAria}>
              {[["en", "English"], ["es", "Español"]].map(([code, label]) => (
                <button key={code} type="button" lang={code} aria-pressed={lang === code} onClick={() => setLang(code)}>
                  {lang === code && <span aria-hidden="true">✓ </span>}{label}</button>))}
            </div>
          </div>
        </div>
        {/* Light/Dark switch: floats in the bottom-left corner (the chat robot has the bottom-right). Icons only on
            screen; aria-label + aria-pressed tell screen readers which is which and which is on. */}
        <div className="theme-switch" role="group" aria-label={t.themeAria}>
          {[["light", <SunIcon />, t.themeLight], ["dark", <MoonIcon />, t.themeDark]].map(([code, icon, label]) => (
            <button key={code} type="button" aria-pressed={theme === code} aria-label={label} title={label}
              onClick={(e) => switchTheme(code, e)}>{icon}</button>))}
        </div>
        <nav className="view-tabs" aria-label={t.viewsAria}>
          <button type="button" aria-pressed={view === "customer"} onClick={() => setView("customer")}>{t.tabCustomer}</button>
          <button type="button" aria-pressed={view === "console"} onClick={() => setView("console")}>{t.tabConsole}</button>
        </nav>
        {view === "customer" && !onboarding && (
          <p>{t.intro} <button type="button" className="link-button" onClick={restart}>{t.onboardRestart}</button></p>)}
        {health?.synthetic_data && <p className="banner">{t.synthetic}</p>}
      </header>

      {view === "customer" && onboarding && (
        <main className="view onboard-view">
          <Onboarding t={t} onComplete={onboarded} />
          <button type="button" className="link-button" onClick={() => setOnboarding(false)}>{t.onboardSkip}</button>
        </main>)}

      {/* Customer view stays mounted while hidden (behind onboarding or the console), so the map has loaded by the
          time it's shown and the selection and chat survive a trip to the console. */}
      <main className="view" hidden={view !== "customer" || onboarding}>
        <ScenarioControls t={t} scenario={scenario} onScenario={setScenario} needs={needs} onToggleNeed={toggleNeed}
          referenceStorms={weather?.reference_storms ?? []}
          enrolled={enrolled} onEnrolled={setEnrolled} utilityConfirmed={utilityConfirmed} onUtilityConfirmed={setUtilityConfirmed} />

        <form className="locate" onSubmit={(e) => {
          e.preventDefault();
          if (typed.trim()) { focusResults.current = true; zoomToResult.current = true; setPremise(typed.trim()); }
        }}>
          <label htmlFor="premise-id">{t.locateLabel}</label>
          <input id="premise-id" value={typed} onChange={(e) => setTyped(e.target.value)} placeholder={t.locatePlaceholder} />
          <button type="submit">{t.lookUp}</button>
        </form>

        {/* Ring the dot the backend says represents this location (works for typed premise IDs too). */}
        <div className="map" role="region" aria-label={t.mapAria}>
          <OutageMap t={t} dark={theme === "dark"} layers={layers} focus={focus}
            selectedId={result?.map_point_id ?? premise} onSelect={setPremise} />
        </div>

        {error && <p role="alert" className="error">{t.apiError(error)}</p>}

        {/* Always mounted so screen readers announce each change once. */}
        <p className="sr-only" aria-live="polite">{summary}</p>

        {result && <ResultsPanel t={t} result={result} changes={changes}
          notifyRequest={{ premise_id: premise, scenario, profile,
                           previous_range_text: shownPrev.current.range, previous_scenario: shownPrev.current.scenario }} />}

        <ChatPanel t={t} premiseId={premise} scenario={scenario} profile={profile} utilityStatus={utilityStatus} />
      </main>

      {view === "console" && <main className="view"><Console /></main>}
    </div>
  );
}

// What moved between two answers for the same location: the old band and/or the old restoration numbers.
// null when there's no earlier answer, either one is a fallback, or nothing visible changed.
function diff(before, now) {
  if (!before || before.risk.source === "fallback" || now.risk.source === "fallback") return null;
  const band = before.risk.band !== now.risk.band ? before.risk.band : null;
  const a = before.restoration, b = now.restoration;
  // Half an hour is the smallest move the range text can show.
  const moved = ["p10_hours", "p50_hours", "p90_hours"].some((k) => Math.abs(a[k] - b[k]) >= 0.5);
  return band || moved ? { band, range: moved ? a : null, stamp: Date.now() } : null;
}
