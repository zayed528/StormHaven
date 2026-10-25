// StormHaven PHONE APP (opened at /app.html; installs as its own home-screen app).   Owner: Nandan
// A separate copy of the customer view, so phone-app changes never touch the web app (src/App.jsx) and vice versa.
// Shares the engines' answer components (map, cards, chat, onboarding) and the strings with the web app; its own
// layout lives in app.css. Differences from the web app:
//  - header: just the title and a menu button (language, theme, change home open in a small panel);
//  - no utility console (a customer app; operators use the web app);
//  - the map legend is a side tab on the right edge (RiskLegendTab.jsx), not on the map;
//  - the answer cards close with a swipe down (no x), and there's no "Confirmed by AEP" note;
//  - the chat opens as a full-screen sheet that stays above the on-screen keyboard (app.css + ChatPanel).
import React, { useEffect, useRef, useState } from "react";
import { flushSync } from "react-dom";
import OutageMap from "../components/OutageMap.jsx";
import { FORECAST_PCT, StormBanner } from "../components/ScenarioControls.jsx";
import ResultsPanel from "../components/ResultsPanel.jsx";
import ChatPanel from "../components/ChatPanel.jsx";
import OnboardingStandIn from "../components/OnboardingStandIn.jsx";
import RiskLegendTab from "./RiskLegendTab.jsx";
import { getConcierge, getHealth, getMap, getWeather } from "../api/client.js";
import { STRINGS, fmtRange } from "../i18n.js";

// Onboarding: Abby's onboarding/Onboarding.jsx when it exists, else the stand-in (same as the web app).
const ONBOARDING = import.meta.glob("../onboarding/Onboarding.jsx", { eager: true });
const Onboarding = ONBOARDING["../onboarding/Onboarding.jsx"]?.default ?? OnboardingStandIn;
// "What if...? 50% more crews": the same comparison the engine's own driver line makes (int(20 x 1.5) + 1).
const BASE_CREWS = 20, MORE_CREWS = 31;
const NEIGHBORHOOD_ZOOM = 14;   // map zoom for "your neighborhood" (same as /api/locate's hint)

// Theme: the saved choice (shared with the web app), else the phone's setting. app.html applies it before first paint.
const THEME_KEY = "stormhaven-theme";
function initialTheme() {
  try { const saved = localStorage.getItem(THEME_KEY); if (saved === "light" || saved === "dark") return saved; } catch { /* blocked */ }
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

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
const MenuIcon = () => (
  <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2"
    strokeLinecap="round"><path d="M4 7h16M4 12h16M4 17h16" /></svg>
);

export default function PhoneApp() {
  const [layers, setLayers] = useState(null);
  const [health, setHealth] = useState(null);
  const [weather, setWeather] = useState(null);       // reference storms: "similar to the Sep 2024 storm..."
  const [premise, setPremise] = useState(null);
  // Starts at the forecast storm, 20 crews, normal roads; the "What if...?" controls change it from there.
  const [scenario, setScenario] = useState({ severity_percentile: FORECAST_PCT, crews_available: BASE_CREWS, road_access: "normal", extra_damage: [] });
  const [needs, setNeeds] = useState([]);
  const [enrolled, setEnrolled] = useState(true);
  const [lang, setLang] = useState("en");          // UI language; also profile.language (localized SMS messages)
  const [menuOpen, setMenuOpen] = useState(false); // header menu (language, theme, change home)
  const [theme, setTheme] = useState(initialTheme); // "light" | "dark"
  const [result, setResult] = useState(null);
  const [resultPct, setResultPct] = useState(null);   // the storm strength `result` was computed for
  const [changes, setChanges] = useState(null);    // what moved vs. the previous answer, for the highlight
  const [error, setError] = useState(null);
  const [onboarding, setOnboarding] = useState(true);   // first screen until the customer finishes (or skips) it
  const [focus, setFocus] = useState(null);            // {lat, lon, zoom, offsetPx, key}: zoom to the customer's area
  const [dockOpen, setDockOpen] = useState(true);      // the answer cards (closed with x; a new home reopens them)
  const headerRef = useRef(null);
  const stormRef = useRef(null);                     // the storm banner floating under the header
  const t = STRINGS[lang];
  const publicDemo = health?.mode === "public_demo";
  const demoLocations = publicDemo ? (layers?.premises ?? []).slice(0, 3) : [];
  // The last answer for THIS location (range + scenario), sent back so "estimate updated" can say old -> new.
  const last = useRef({ premise: null, range: null, scenario: null, result: null });
  const shownPrev = useRef({ range: null, scenario: null });   // what "Send as text" compares against
  const focusResults = useRef(false);   // move focus to the answer when it arrives (after onboarding)
  const zoomToResult = useRef(false);   // zoom to the answer's map dot when onboarding gave no zoom target
  // Only the NEWEST answer / map is shown: on a slow connection an older request can finish last.
  const answerReq = useRef(0), mapReq = useRef(0);

  // Only declared needs and channel TYPES are sent; no names, phone numbers, or addresses.
  const profile = { declared_needs: needs, alerts_enrolled: enrolled, channels: enrolled ? ["sms"] : [], language: lang };

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem(THEME_KEY, theme); } catch { /* blocked */ }
  }, [theme]);

  // Theme switch: the new theme spreads in a circle from the tapped button (instant without View Transitions).
  const switchTheme = (code, e) => {
    if (code === theme) return;
    const apply = () => { document.documentElement.dataset.theme = code; flushSync(() => setTheme(code)); };
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

  // Header menu: closes on Esc or a tap outside the header.
  useEffect(() => {
    if (!menuOpen) return;
    const onKey = (e) => { if (e.key === "Escape") { setMenuOpen(false); document.querySelector(".menu-btn")?.focus(); } };
    const onDown = (e) => { if (!headerRef.current?.contains(e.target)) setMenuOpen(false); };
    window.addEventListener("keydown", onKey);
    window.addEventListener("pointerdown", onDown);
    return () => { window.removeEventListener("keydown", onKey); window.removeEventListener("pointerdown", onDown); };
  }, [menuOpen]);

  useEffect(() => { getHealth().then(setHealth).catch(() => {}); }, []);
  useEffect(() => { getWeather().then(setWeather).catch(() => {}); }, []);

  // Language switch: forget the last answer (range_short is localized, so comparing across languages would fake
  // an "estimate updated" message).
  useEffect(() => {
    document.documentElement.lang = lang;
    last.current = { premise: null, range: null, scenario: null, result: null };
    setChanges(null);
  }, [lang]);

  // How far down the header + storm banner reach, published as --header-h / --chrome-h (map tools, onboarding sit below).
  const chromeBottom = () => Math.ceil(Math.max(headerRef.current?.getBoundingClientRect().bottom ?? 0,
                                                stormRef.current?.getBoundingClientRect().bottom ?? 0));
  useEffect(() => {
    if (!window.ResizeObserver) return;
    const update = () => {
      document.documentElement.style.setProperty("--header-h", `${headerRef.current?.offsetHeight ?? 0}px`);
      const h = chromeBottom();
      document.documentElement.style.setProperty("--chrome-h", `${h}px`);
    };
    const ro = new ResizeObserver(update);
    [headerRef.current, stormRef.current].forEach((el) => el && ro.observe(el));
    update();
    return () => ro.disconnect();
  }, []);

  // Aim the map so the home lands in the gap between the header and the answer cards (bottom ~45% on a phone).
  const homeOffsetPx = () => {
    const h = window.innerHeight, chrome = chromeBottom();
    const cards = window.innerWidth <= 760 ? h * 0.45 : Math.min(h * 0.5, 600);
    return Math.max(0, (cards - chrome) / 2);
  };
  const zoomTo = (lat, lon, zoom) => setFocus({ lat, lon, zoom, offsetPx: homeOffsetPx(), key: Date.now() });
  const selectHome = (id) => { setPremise(id); setDockOpen(true); };

  useEffect(() => {
    if (!zoomToResult.current || !result?.map_point_id || !layers) return;
    const dot = layers.premises.find((p) => p.id === result.map_point_id);
    zoomToResult.current = false;
    if (dot) zoomTo(dot.lat, dot.lon, NEIGHBORHOOD_ZOOM);
  }, [result, layers]);

  // Onboarding finished (contract: onboarding/Onboarding.jsx).
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
  const restart = () => {
    setPremise(null); setResult(null); setChanges(null); setFocus(null);
    last.current = { premise: null, range: null, scenario: null, result: null };
    setOnboarding(true);
  };

  // Map colors depend only on storm strength (debounced: the real-data map is ~1 MB).
  useEffect(() => {
    const tm = setTimeout(() => {
      const id = ++mapReq.current;
      getMap(scenario.severity_percentile).then((l) => { if (id === mapReq.current) { setLayers(l); setError(null); } })
        .catch((e) => { if (id === mapReq.current) setError(e.message); });
    }, 300);
    return () => clearTimeout(tm);
  }, [scenario.severity_percentile]);

  // Re-ask the backend whenever the location or any input changes. All numbers come from the API.
  useEffect(() => {
    if (!premise) return;
    const tm = setTimeout(() => {
      const prev = last.current.premise === premise ? last.current : { range: null, scenario: null, result: null };
      const id = ++answerReq.current;
      getConcierge({
        premise_id: premise, scenario, profile,
        previous_range_text: prev.range, previous_scenario: prev.scenario,
        utility_status: null,
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
    }, 200);
    return () => clearTimeout(tm);
  }, [premise, scenario, needs, enrolled, lang]);   // eslint-disable-line react-hooks/exhaustive-deps

  // One short sentence for screen readers when the estimate moves.
  const summary = changes ? t.changedSummary([
    changes.band && t.changedBand(t.bands[changes.band], t.bands[result.risk.band]),
    changes.range && t.changedRange(fmtRange(changes.range, t), fmtRange(result.restoration, t)),
  ].filter(Boolean).join("; ")) : "";

  const showDock = !onboarding && !!result && dockOpen;
  // The answer cards' height (--dock-h): the chat robot sits just above them.
  useEffect(() => {
    const el = showDock && document.getElementById("results");
    if (!el || !window.ResizeObserver) return;
    const ro = new ResizeObserver(() => document.documentElement.style.setProperty("--dock-h", `${el.offsetHeight}px`));
    ro.observe(el);
    return () => ro.disconnect();
  }, [showDock, premise]);

  return (
    <div className={`app full-map phone-app${showDock ? " has-dock" : ""}`}>
      {showDock && <a className="skip-link" href="#results">{t.skipToResults}</a>}
      <header className="topbar" ref={headerRef}>
        <div className="header-row">
          <h1>StormHaven</h1>
          {/* One menu button; language, theme and "Change home" open under it as a small panel. */}
          <button type="button" className="menu-btn" aria-expanded={menuOpen} aria-controls="header-menu"
            aria-label={t.menu} title={t.menu} onClick={() => setMenuOpen(!menuOpen)}><MenuIcon /></button>
          <div id="header-menu" className={`header-actions${menuOpen ? " open" : ""}`}>
            {!onboarding && (
              <button type="button" className="toolbar-btn" onClick={() => { setMenuOpen(false); restart(); }}>{t.changeHome}</button>)}
            <div className="lang-switch" role="group" aria-label={t.languageAria}>
              {[["en", "English"], ["es", "Español"]].map(([code, label]) => (
                <button key={code} type="button" lang={code} aria-pressed={lang === code} onClick={() => setLang(code)}>
                  {lang === code && <span aria-hidden="true">✓ </span>}{label}</button>))}
            </div>
            <div className="theme-switch" role="group" aria-label={t.themeAria}>
              {[["light", <SunIcon />, t.themeLight], ["dark", <MoonIcon />, t.themeDark]].map(([code, icon, label]) => (
                <button key={code} type="button" aria-pressed={theme === code} aria-label={label} title={label}
                  onClick={(e) => switchTheme(code, e)}>{icon}</button>))}
            </div>
          </div>
        </div>
        {(health?.synthetic_data || publicDemo) && <p className="banner">{t.synthetic}</p>}
      </header>

      <div className="storm-float" ref={stormRef} role="region" aria-label={t.stormForecastAria}>
        <StormBanner t={t} scenario={scenario} referenceStorms={weather?.reference_storms ?? []}
          onReset={() => setScenario({ ...scenario, severity_percentile: FORECAST_PCT })} />
      </div>

      <div className="customer">
        <div className="map map-full" role="region" aria-label={t.mapAria}>
          <OutageMap t={t} dark={theme === "dark"} layers={layers} focus={focus}
            selectedId={result?.map_point_id ?? premise} onSelect={selectHome} legend={false} />
        </div>
        {/* The map legend lives in a side tab on the right edge instead of on the map. */}
        <RiskLegendTab t={t} />

        {onboarding && (
          <div className="onboard-overlay">
            {!health ? <p className="muted">{t.console.loading}</p>
              : t.onboarding ? <Onboarding t={t} onComplete={onboarded} publicDemo={publicDemo}
                  demoLocations={demoLocations} /> : <OnboardingStandIn t={t} onComplete={onboarded} />}
            {health && !publicDemo && <button type="button" className="link-button" onClick={() => setOnboarding(false)}>{t.onboardSkip}</button>}
          </div>)}

        {error && <p role="alert" className="error toast">{t.apiError(error)}</p>}
        <p className="sr-only" aria-live="polite">{summary}</p>

        {/* No "Confirmed by AEP" note here; swipe the cards down to close them (tap a home to bring them back). */}
        {showDock && <ResultsPanel key={premise} t={t} result={result} changes={changes} onClose={() => setDockOpen(false)}
          confirmed={false} swipeToClose
          stormPct={resultPct}
          whatIf={{ scenario, onScenario: setScenario, baseCrews: BASE_CREWS, moreCrews: MORE_CREWS }}
          notifyRequest={publicDemo ? null : { premise_id: premise, scenario, profile,
                           previous_range_text: shownPrev.current.range, previous_scenario: shownPrev.current.scenario }} />}

        {/* Needs ticked in the chat become the app's needs too, so the cards, alerts and texts follow them. */}
        <ChatPanel t={t} premiseId={premise} scenario={scenario} profile={profile} utilityStatus={null}
          onNeeds={setNeeds} />
      </div>
    </div>
  );
}

// What moved between two answers for the same location (same rule as the web app).
function diff(before, now) {
  if (!before || before.risk.source === "fallback" || now.risk.source === "fallback") return null;
  const band = before.risk.band !== now.risk.band ? before.risk.band : null;
  const a = before.restoration, b = now.restoration;
  const moved = ["p10_hours", "p50_hours", "p90_hours"].some((k) => Math.abs(a[k] - b[k]) >= 0.5);
  return band || moved ? { band, range: moved ? a : null, stamp: Date.now() } : null;
}
