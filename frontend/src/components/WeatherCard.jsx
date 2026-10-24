// Live weather context from /api/weather: 3-day forecast for the service area + active NWS alerts.   Owner: Abby
// Context only: the forecast never changes the risk or restoration numbers (see docs/ASSUMPTIONS.md).
import React from "react";

const pct = (x) => (x == null ? null : `${Math.round(x * 100)}%`);
const day = (iso, locale) => new Date(`${iso}T12:00:00`).toLocaleDateString(locale, { weekday: "short", month: "short", day: "numeric" });

export default function WeatherCard({ weather, t }) {
  const fc = weather?.forecast;
  if (!fc?.available) return null;                 // synthetic network, offline, or service down: show nothing
  const alerts = fc.nws_alerts ?? [];
  const worst = fc.days.reduce((a, b) => (b.median_gust_mph > (a?.median_gust_mph ?? -1) ? b : a), null);

  return (
    <section className="weather" aria-label={t.wxAria}>
      <h2>{t.wxTitle} <span className="tag">{t.live}</span></h2>
      {alerts.length > 0 && (
        <div className="nws" role="alert">
          <strong>{t.nws}</strong>
          <ul>{alerts.map((a, i) => <li key={i}>{a.headline || a.event}</li>)}</ul>
        </div>)}
      <ul className="days">
        {fc.days.map((d) => (
          <li key={d.date}><strong>{day(d.date, t.locale)}</strong> {t.wxDay(d.peak_gust_mph)}
            {d.rain_mm > 0 ? t.wxRain(d.rain_mm) : ""}{d.snow_cm > 0 ? t.wxSnow(d.snow_cm) : ""}</li>))}
      </ul>
      {worst?.share_past_days_with_damage != null && (
        <p className="muted">{t.wxOdds(pct(worst.share_past_days_with_damage))}</p>)}
      <p className="credit">{weather.credit}</p>
    </section>
  );
}
