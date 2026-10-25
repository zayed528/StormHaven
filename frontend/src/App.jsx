// StormHaven: map-first storm outage concierge. State lives here; components render.   Owner: Nandan
// Layout (customer view): a full-screen map; a frosted header (title, tabs, language, theme) with the storm-level
// toggles under it; first visit = a translucent premise-ID panel over the map; choosing a home zooms in and slides
// three answer cards in from the left along the bottom; chat robot bottom-left.
import React, { useEffect, useRef, useState } from "react";
import { flushSync } from "react-dom";
import OutageMap from "./components/OutageMap.jsx";
import { FORECAST_PCT, STORM_PCTS, StormBanner } from "./components/ScenarioControls.jsx";
import ResultsPanel from "./components/ResultsPanel.jsx";
import ChatPanel from "./components/ChatPanel.jsx";
import Console from "./console/Console.jsx";          // Abby's utility console (fetches its own data)
import OnboardingStandIn from "./components/OnboardingStandIn.jsx";
import { getConcierge, getHealth, getMap, getWeather, mapCached } from "./api/client.js";
import { STRINGS, fmtRange } from "./i18n.js";

// Onboarding (first screen): Abby's onboarding/Onboarding.jsx as soon as that file exists, else the stand-in.
// import.meta.glob finds nothing (instead of failing the build) while her file isn't merged yet.
const ONBOARDING = import.meta.glob("./onboarding/Onboarding.jsx", { eager: true });
const Onboarding = ONBOARDING["./onboarding/Onboarding.jsx"]?.default ?? OnboardingStandIn;
// "What if...? 50% more crews": the same comparison the engine's own driver line makes (int(20 x 1.5) + 1).
const BASE_CREWS = 20, MORE_CREWS = 31;
// Utility console tab: ON by default (team decision, 2026-10-25). Build with VITE_ENABLE_OPERATOR_CONSOLE=0 to hide it.
// (The public demo never shows it either way.)
const ENABLE_OPERATOR_CONSOLE = import.meta.env.VITE_ENABLE_OPERATOR_CONSOLE !== "0";

// Which real storm the customer's answer was compared with (the planner replay behind the "In our replay of the
// ... storm" sentence). The console replays the same storm. TEMPORARY: the answer doesn't name the storm by ID yet,
// so the label is read from the backend's English sentence. When the answer carries restoration.replay_storm_id
// (Akshat + Jaid), stormId is used and the label parsing is no longer needed.
function replayFrom(result) {
  const r = result?.restoration;
  if (!r) return { stormId: null, label: null };
  const m = /In our replay of the (.+? storm) with \d+ crews/.exec(r.storm_context ?? "");
  return { stormId: r.replay_storm_id ?? null, label: m ? m[1] : null };
}
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
  const [weather, setWeather] = useState(null);       // reference storms: "similar to the Sep 2024 storm..."
  const [premise, setPremise] = useState(null);
  // Starts at the forecast storm (demo: fixed; production: AEP's storm forecast), 20 crews, normal roads. The
  // "What if...?" controls in the answer change it from there.
  const [scenario, setScenario] = useState({ severity_percentile: FORECAST_PCT, crews_available: BASE_CREWS, road_access: "normal", extra_damage: [] });
  const [needs, setNeeds] = useState([]);
  const [enrolled, setEnrolled] = useState(true);
  const [utilityConfirmed, setUtilityConfirmed] = useState(false);
  const [lang, setLang] = useState("en");          // UI language; also profile.language (localized SMS messages)
  const [view, setView] = useState("customer");    // "customer" | "console"
  const [theme, setTheme] = useState(initialTheme); // "light" | "dark"
  const [result, setResult] = useState(null);
  const [resultPct, setResultPct] = useState(null);   // the storm strength `result` was computed for
  const [changes, setChanges] = useState(null);    // what moved vs. the previous answer, for the highlight
  const [error, setError] = useState(null);
  const [onboarding, setOnboarding] = useState(true);   // first screen until the customer finishes (or skips) it
  const [focus, setFocus] = useState(null);            // {lat, lon, zoom, offsetPx, key}: zoom to the customer's area
  const [dockOpen, setDockOpen] = useState(true);      // the answer cards (closed with x / Esc; a new home reopens them)
  const headerRef = useRef(null);
  const stormRef = useRef(null);                     // the storm banner floating under the header
  const t = STRINGS[lang];
  const publicDemo = health?.mode === "public_demo";
  const demoLocations = publicDemo ? (layers?.premises ?? []).slice(0, 3) : [];
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
  // Only the NEWEST answer / map is shown. Quick "What if" taps send several requests; on a slow connection an older
  // one can finish last and would otherwise put the previous storm's risk (text and color) back on screen.
  const answerReq = useRef(0), mapReq = useRef(0);

  // Only declared needs and channel TYPES are sent; no names, phone numbers, or addresses.
  const profile = { declared_needs: needs, alerts_enrolled: enrolled, channels: enrolled ? ["sms"] : [], language: lang };
  const utilityStatus = utilityConfirmed ? { outage_confirmed: true, confirmed_etr: t.demoEtr } : null;

  // Theme: stamp it on <html> (styles.css switches every color on data-theme) and remember the choice.
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem(THEME_KEY, theme); } catch { /* blocked: the choice just lasts this visit */ }
  }, [theme]);

  // Switching views: the page slides sideways, the console coming in from the right and the customer view back from
  // the left (View Transitions API; data-vt picks the direction in styles.css). Instant without it or with reduced motion.
  const switchView = (next) => {
    if (next === view) return;
    const apply = () => flushSync(() => setView(next));
    if (!document.startViewTransition || window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) { apply(); return; }
    const root = document.documentElement;
    root.dataset.vt = next === "console" ? "to-console" : "to-customer";
    document.startViewTransition(apply).finished.finally(() => { delete root.dataset.vt; });
  };

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
  // Weather reference storms describe the forecast storm in the banner. Optional: failures are ignored.
  useEffect(() => { getWeather().then(setWeather).catch(() => {}); }, []);

  // Language switch: tell screen readers / the browser, and forget the last answer. range_short is localized
  // ("6-24 hours" vs "6-24 horas"), so comparing across languages would fake an "estimate updated" message.
  useEffect(() => {
    document.documentElement.lang = lang;
    last.current = { premise: null, range: null, scenario: null, result: null };
    setChanges(null);
  }, [lang]);

  // Plotly measures its box while hidden as 0 px; nudge it to re-measure when the customer view comes back.
  useEffect(() => { if (view === "customer") setTimeout(() => window.dispatchEvent(new Event("resize")), 50); }, [view]);

  // How far down the top chrome reaches (header, plus the floating storm toggles in the customer view). Published as
  // --chrome-h so the map tools, onboarding panel and error toast sit below it.
  const chromeBottom = () => Math.ceil(Math.max(headerRef.current?.getBoundingClientRect().bottom ?? 0,
                                                stormRef.current?.getBoundingClientRect().bottom ?? 0));
  useEffect(() => {
    if (!window.ResizeObserver) return;
    const update = () => {
      // --header-h first: the storm toggles are placed by it, and chromeBottom() then measures where they end.
      document.documentElement.style.setProperty("--header-h", `${headerRef.current?.offsetHeight ?? 0}px`);
      const h = chromeBottom();
      document.documentElement.style.setProperty("--chrome-h", `${h}px`);
    };
    const ro = new ResizeObserver(update);
    [headerRef.current, stormRef.current].forEach((el) => el && ro.observe(el));
    update();
    return () => ro.disconnect();
  }, [view]);

  // Where to aim the map so the customer's home lands in the visible gap between the header and the answer cards
  // (pixels to shift the home up from the screen's middle). The cards take roughly the bottom half.
  const homeOffsetPx = () => {
    const h = window.innerHeight, chrome = chromeBottom();
    const cards = window.innerWidth <= 760 ? h * 0.45 : Math.min(h * 0.5, 600);
    return Math.max(0, (cards - chrome) / 2);
  };
  const zoomTo = (lat, lon, zoom) => setFocus({ lat, lon, zoom, offsetPx: homeOffsetPx(), key: Date.now() });

  // A home was chosen (map click or onboarding): show its answer cards again if they were closed.
  const selectHome = (id) => { setPremise(id); setDockOpen(true); };

  // Zoom to the customer's neighborhood once their answer names the map dot (when no zoom target was given).
  useEffect(() => {
    if (!zoomToResult.current || !result?.map_point_id || !layers) return;
    const dot = layers.premises.find((p) => p.id === result.map_point_id);
    zoomToResult.current = false;
    if (dot) zoomTo(dot.lat, dot.lon, NEIGHBORHOOD_ZOOM);
  }, [result, layers]);

  // Onboarding finished (contract: onboarding/Onboarding.jsx). Feed it into the state the app already has.
  const onboarded = (p) => {
    if (p.language === "en" || p.language === "es") setLang(p.language);
    setNeeds(p.declared_needs ?? []);
    setEnrolled(!!p.alerts_enrolled);
    selectHome(p.premise_id);
    if (p.center) zoomTo(p.center.lat, p.center.lon, p.zoom ?? NEIGHBORHOOD_ZOOM);
    else zoomToResult.current = true;
    focusResults.current = true;
    setOnboarding(false);
  };
  // "Change home": back to the premise-ID panel with a clean slate and the whole-territory map.
  const restart = () => {
    setPremise(null); setResult(null); setChanges(null); setFocus(null);
    last.current = { premise: null, range: null, scenario: null, result: null };
    setOnboarding(true);
  };

  // Map colors depend only on storm strength, so refetch the map only when severity changes. A map already downloaded
  // (api/client.js keeps them) shows at once; a new one waits 300 ms, so quick taps don't each start a ~5 MB download.
  useEffect(() => {
    const sev = scenario.severity_percentile;
    const tm = setTimeout(() => {
      const id = ++mapReq.current;
      getMap(sev).then((l) => { if (id === mapReq.current) { setLayers(l); setError(null); } })
        .catch((e) => { if (id === mapReq.current) setError(e.message); });
    }, mapCached(sev) ? 0 : 300);
    return () => clearTimeout(tm);
  }, [scenario.severity_percentile]);
  // Once the first map is on screen, quietly download the other storm strengths one after another, so the What-if
  // storm buttons don't wait ~2 s for a map. (Web app only: on a phone that would be ~15 MB of mobile data.)
  const prefetched = useRef(false);
  useEffect(() => {
    if (!layers || prefetched.current) return;
    prefetched.current = true;
    STORM_PCTS.filter((p) => !mapCached(p)).reduce((chain, p) => chain.then(() => getMap(p)).catch(() => {}), Promise.resolve());
  }, [layers]);

  // Re-ask the backend whenever the location or any input changes. All numbers come from the API;
  // the frontend never computes risk or times itself.
  useEffect(() => {
    if (!premise) return;
    const tm = setTimeout(() => {   // debounce slider drags
      const prev = last.current.premise === premise ? last.current : { range: null, scenario: null, result: null };
      const id = ++answerReq.current;
      getConcierge({
        premise_id: premise, scenario, profile,
        previous_range_text: prev.range, previous_scenario: prev.scenario,
        utility_status: utilityStatus,
      }).then((r) => {
        if (id !== answerReq.current) return;   // an older request finished late: drop it
        setChanges(diff(prev.result, r));
        setResult(r); setResultPct(scenario.severity_percentile); setError(null);
        shownPrev.current = { range: prev.range, scenario: prev.scenario };
        last.current = { premise, range: r.restoration.range_short, scenario, result: r };
        if (focusResults.current) {
          focusResults.current = false;
          setTimeout(() => document.getElementById("results")?.focus(), 0);
        }
      }).catch((e) => { if (id === answerReq.current) setError(e.message); });
    }, 80);   // short: the What-if controls are taps, not sliders
    return () => clearTimeout(tm);      // cancel the pending call if inputs change again within 200 ms
  }, [premise, scenario, needs, enrolled, utilityConfirmed, lang]);   // eslint-disable-line react-hooks/exhaustive-deps

  const toggleNeed = (n) => setNeeds(needs.includes(n) ? needs.filter((x) => x !== n) : [...needs, n]);

  // One short sentence for screen readers when the estimate moves (the panel itself isn't a live region).
  const summary = changes ? t.changedSummary([
    changes.band && t.changedBand(t.bands[changes.band], t.bands[result.risk.band]),
    changes.range && t.changedRange(fmtRange(changes.range, t), fmtRange(result.restoration, t)),
  ].filter(Boolean).join("; ")) : "";

  const showDock = !onboarding && !!result && dockOpen;
  // Publish the answer cards' height (--dock-h): on phones the chat robot sits just above them.
  useEffect(() => {
    const el = showDock && document.getElementById("results");
    if (!el || !window.ResizeObserver) return;
    const ro = new ResizeObserver(() => document.documentElement.style.setProperty("--dock-h", `${el.offsetHeight}px`));
    ro.observe(el);
    return () => ro.disconnect();
  }, [showDock, premise]);

  return (
    <div className={`app${view === "customer" ? " full-map" : " console-mode"}${showDock ? " has-dock" : ""}`}>
      {/* First Tab stop when the answer is showing: the map can't be used from a keyboard, so jump to the answer. */}
      {showDock && <a className="skip-link" href="#results">{t.skipToResults}</a>}
      <header className="topbar" ref={headerRef}>
        <div className="header-row">
          <h1>StormHaven</h1>
          <nav className="view-tabs" aria-label={t.viewsAria}>
            <button type="button" aria-pressed={view === "customer"} onClick={() => switchView("customer")}>{t.tabCustomer}</button>
            {health && !publicDemo && ENABLE_OPERATOR_CONSOLE && (
              <button type="button" aria-pressed={view === "console"} onClick={() => switchView("console")}>{t.tabConsole}</button>
            )}
          </nav>
          <div className="header-actions">
            {view === "customer" && !onboarding && (
              <button type="button" className="toolbar-btn" onClick={restart}>{t.changeHome}</button>)}
            {/* Both options always visible; the current one is filled in (and aria-pressed for screen readers). */}
            <div className="lang-switch" role="group" aria-label={t.languageAria}>
              {[["en", "English"], ["es", "Español"]].map(([code, label]) => (
                <button key={code} type="button" lang={code} aria-pressed={lang === code} onClick={() => setLang(code)}>
                  {lang === code && <span aria-hidden="true">✓ </span>}{label}</button>))}
            </div>
            {/* Light/Dark: icons only on screen; aria-label + aria-pressed tell screen readers which is which and which is on. */}
            <div className="theme-switch" role="group" aria-label={t.themeAria}>
              {[["light", <SunIcon />, t.themeLight], ["dark", <MoonIcon />, t.themeDark]].map(([code, icon, label]) => (
                <button key={code} type="button" aria-pressed={theme === code} aria-label={label} title={label}
                  onClick={(e) => switchTheme(code, e)}>{icon}</button>))}
            </div>
          </div>
        </div>
        {(health?.synthetic_data || publicDemo) && <p className="banner">{t.synthetic}</p>}
      </header>

      {/* Storm level: a liquid-glass pill floating centered just under the header (customer view only). */}
      {view === "customer" && (
        <div className="storm-float" ref={stormRef} role="region" aria-label={t.stormForecastAria}>
          <StormBanner t={t} scenario={scenario} referenceStorms={weather?.reference_storms ?? []}
            onReset={() => setScenario({ ...scenario, severity_percentile: FORECAST_PCT })} />
        </div>)}

      {/* Customer view stays mounted while the console is open, so the map, selection and chat survive the trip. */}
      <div className="customer" hidden={view !== "customer"}>
        <div className="map map-full" role="region" aria-label={t.mapAria}>
          <OutageMap t={t} dark={theme === "dark"} layers={layers} focus={focus}
            selectedId={result?.map_point_id ?? premise} onSelect={selectHome} />
        </div>

        {/* First visit: a translucent premise-ID panel over the whole-territory map. */}
        {onboarding && (
          <div className="onboard-overlay">
            {/* Abby's component needs t.onboarding; if that's ever missing, the stand-in shows instead of a blank page. */}
            {!health ? <p className="muted">{t.console.loading}</p>
              : t.onboarding ? <Onboarding t={t} onComplete={onboarded} publicDemo={publicDemo}
                  demoLocations={demoLocations} /> : <OnboardingStandIn t={t} onComplete={onboarded} />}
            {health && !publicDemo && <button type="button" className="link-button" onClick={() => setOnboarding(false)}>{t.onboardSkip}</button>}
          </div>)}

        {error && <p role="alert" className="error toast">{t.apiError(error)}</p>}

        {/* Always mounted so screen readers announce each change once. */}
        <p className="sr-only" aria-live="polite">{summary}</p>

        {/* key = the home: a new home remounts the cards, so they slide in again; storm changes just update them. */}
        {showDock && <ResultsPanel key={premise} t={t} result={result} changes={changes} onClose={() => setDockOpen(false)}
          stormPct={resultPct}
          whatIf={{ scenario, onScenario: setScenario, baseCrews: BASE_CREWS, moreCrews: MORE_CREWS }}
          notifyRequest={publicDemo ? null : { premise_id: premise, scenario, profile,
                           previous_range_text: shownPrev.current.range, previous_scenario: shownPrev.current.scenario }} />}

        {/* Needs ticked in the chat become the app's needs too, so the cards, alerts and texts follow them. */}
        <ChatPanel t={t} premiseId={premise} scenario={scenario} profile={profile} utilityStatus={utilityStatus}
          onNeeds={setNeeds} />
      </div>

      {/* One-way link: the console plans against the customer view's scenario (storm, crews, roads) and the same
          real storm the answer was compared with. Nothing in the console changes the customer view. */}
      {view === "console" && <main className="view"><Console t={t} replay={replayFrom(result)}
        customer={{ severity: scenario.severity_percentile, crews: scenario.crews_available, roads: scenario.road_access,
                    whatIf: scenario.severity_percentile !== FORECAST_PCT }} /></main>}
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
