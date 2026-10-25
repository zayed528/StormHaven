// Storm strength: the forecast banner and the "what if" controls.   Owner: Nandan
// The engines answer "if a storm of THIS strength hits, what happens to your home?". Storm strength is an input
// (in production it comes from AEP's storm forecast; for the demo it's a fixed scenario), measured against AEP's real
// storm history: Typical = median storm, Record = about the Feb 2025 storm. So it is shown as:
//  - StormBanner: "Storm approaching: planning for a severe storm (similar to ...)" at the top, i.e. the forecast,
//    not something the customer picks;
//  - StormToggle: inside "What if...?" in the answer, to see the same home under a stronger or weaker storm.
// Crews and road access are "what if" toggles too (see ResultsPanel); the API defaults are 20 crews, normal roads.
// Visible text comes from i18n.js (t); the values sent to the API stay English.
import React, { useLayoutEffect, useRef, useState } from "react";

// Storm strengths as the severity_percentile sent to the API (the storm's rank among AEP's 36 recorded storms):
// 50 = typical, 95 = strong, 97 = severe, 99 = record (about Feb 2025). Labels: t.stormLevels[i].
export const STORM_PCTS = [50, 95, 97, 99];
// The demo's forecast storm (in production: AEP's storm forecast).
export const FORECAST_PCT = 97;
// Index of the level closest to a percentile.
export const levelFor = (pct) => STORM_PCTS.reduce((best, p, i) =>
  (Math.abs(p - pct) < Math.abs(STORM_PCTS[best] - pct) ? i : best), 0);

// The real past storm closest to a severity percentile, so the strength reads as weather people remember.
export function similarStorm(pct, storms, t) {
  if (!storms?.length) return null;
  if (pct < storms[0].percentile - 5) return t.milderThanAll;
  const s = storms.reduce((a, b) => (Math.abs(b.percentile - pct) < Math.abs(a.percentile - pct) ? b : a));
  const extra = [s.rain_mm >= 1 ? t.rainMm(Math.round(s.rain_mm)) : null, s.snow_cm >= 1 ? t.snowCm(Math.round(s.snow_cm)) : null]
    .filter(Boolean).join(", ");
  return t.similarStorm(t.tr(s.label), Math.round(s.peak_gust_mph), extra);   // t.tr: "Sep 2024" -> "sept. 2024" in Spanish
}

// The incoming storm, at the top of the map: what we're planning for, and what it resembles. If the customer is
// looking at a "what if" storm instead, it says so and offers a way back to the forecast.
export function StormBanner({ t, scenario, referenceStorms, onReset }) {
  const forecast = levelFor(FORECAST_PCT);
  const shown = levelFor(scenario.severity_percentile);
  const similar = similarStorm(FORECAST_PCT, referenceStorms, t);
  return (
    <div className="storm-banner" role="status">
      <svg className="storm-banner-icon" viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" fill="none"
        stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M7 16a4.5 4.5 0 1 1 .9-8.9A5.5 5.5 0 0 1 18.5 9 3.5 3.5 0 0 1 18 16" /><path d="M12.5 13l-2 4h3l-2 4" />
      </svg>
      <span>
        <strong>{t.stormBanner(t.stormLevels[forecast].banner)}</strong>
        {similar && <span className="storm-banner-similar"> {similar}</span>}
        {shown !== forecast && (
          <span className="storm-banner-whatif"> · {t.whatIfShowing(t.stormLevels[shown].label)}{" "}
            <button type="button" className="link-button" onClick={onReset}>{t.backToForecast}</button></span>)}
      </span>
    </div>
  );
}

// Storm strength as four toggle buttons (one is always on). A glass "thumb" sits behind the chosen one and glides to
// the next when it changes; its position comes from the chosen button's box, re-measured on resize and language change.
export default function StormToggle({ t, scenario, onScenario, labelledBy }) {
  const level = levelFor(scenario.severity_percentile);
  const forecast = levelFor(FORECAST_PCT);
  const group = useRef(null);
  const [thumb, setThumb] = useState(null);          // { left, width } in px, relative to the group

  useLayoutEffect(() => {
    const g = group.current;
    if (!g) return;
    const measure = () => {
      const b = g.querySelectorAll("button")[level];
      if (b) setThumb({ left: b.offsetLeft, width: b.offsetWidth });
    };
    measure();
    const ro = window.ResizeObserver ? new ResizeObserver(measure) : null;
    ro?.observe(g);
    return () => ro?.disconnect();
  }, [level, t]);

  return (
    <div className="storm-bar storm-bar-inline">
      <div className="storm-toggles" role="group" aria-labelledby={labelledBy} ref={group}>
        {thumb && <span className="storm-thumb" aria-hidden="true"
          style={{ transform: `translateX(${thumb.left}px)`, width: `${thumb.width}px` }} />}
        {t.stormLevels.map((l, i) => (
          <button key={l.label} type="button" aria-pressed={i === level} className={`lvl-${i}`} title={l.note}
            aria-description={i === forecast ? `${l.note} (${t.forecastTag})` : l.note}
            onClick={() => onScenario({ ...scenario, severity_percentile: STORM_PCTS[i] })}>
            {l.short}{i === forecast && <span className="forecast-mark" aria-hidden="true"> •</span>}</button>))}
      </div>
    </div>
  );
}
