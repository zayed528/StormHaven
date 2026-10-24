// Live weather context from /api/weather: 3-day forecast for the service area + active NWS alerts.   Owner: Abby
// Context only: the forecast never changes the risk or restoration numbers (see docs/ASSUMPTIONS.md).
import React from "react";

const pct = (x) => (x == null ? null : `${Math.round(x * 100)}%`);
const day = (iso) => new Date(`${iso}T12:00:00`).toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });

export default function WeatherCard({ weather }) {
  const fc = weather?.forecast;
  if (!fc?.available) return null;                 // synthetic network, offline, or service down: show nothing
  const alerts = fc.nws_alerts ?? [];
  const worst = fc.days.reduce((a, b) => (b.median_gust_mph > (a?.median_gust_mph ?? -1) ? b : a), null);

  return (
    <section className="weather" aria-label="Weather forecast for the service area">
      <h2>Forecast for the area <span className="tag">live</span></h2>
      {alerts.length > 0 && (
        <div className="nws" role="alert">
          <strong>National Weather Service:</strong>
          <ul>{alerts.map((a, i) => <li key={i}>{a.headline || a.event}</li>)}</ul>
        </div>)}
      <ul className="days">
        {fc.days.map((d) => (
          <li key={d.date}><strong>{day(d.date)}</strong> gusts up to {d.peak_gust_mph} mph
            {d.rain_mm > 0 ? `, ${d.rain_mm} mm rain` : ""}{d.snow_cm > 0 ? `, ${d.snow_cm} cm snow` : ""}</li>))}
      </ul>
      {worst?.share_past_days_with_damage != null && (
        <p className="muted">On past days this windy, storm damage was reported somewhere in the area about{" "}
          {pct(worst.share_past_days_with_damage)} of the time. Use the storm-strength control below to explore what a
          bigger storm would mean for you.</p>)}
      <p className="credit">{weather.credit}</p>
    </section>
  );
}
