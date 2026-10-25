// First-run onboarding (customer view).   Owner: Abby
// Self-contained: own CSS (uses the app's var(--…) theme colors, so dark mode just works), no app state,
// no shared files. Nandan mounts it in App.jsx as the first screen and feeds the result into existing state.
//
// Props:
//   t          current-language strings (i18n.js). New keys live under t.onboarding.
//   onComplete({ premise_id, declared_needs, alerts_enrolled, channels, language, center, zoom })
//
// One clean screen (phone-first, reads well on camera): premise ID -> alerts sign-up. Declared needs are not asked
// here (the chat handles preparation advice), so declared_needs is always [].
// The ID is validated against GET /api/locate, which also returns the neighborhood center/zoom for the map.
// There is NO address entry: the only address<->premise link is the customer file, which we never read.
import React, { useState } from "react";
import "./onboarding.css";

export default function Onboarding({ t, onComplete, publicDemo = false, demoLocations = [] }) {
  const o = t.onboarding;
  const [premiseId, setPremiseId] = useState("");
  const [enrolled, setEnrolled] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);         // friendly message when the ID doesn't resolve
  const [locating, setLocating] = useState(false);  // "use my location" in progress

  // Shared finish step: given a validated /api/locate result, hand everything back to the app.
  const finish = (loc) => onComplete({
    premise_id: loc.map_point_id ? premiseId.trim() || loc.map_point_id : premiseId.trim(),
    declared_needs: [],
    alerts_enrolled: enrolled,
    channels: enrolled ? ["sms"] : [],            // sms is the wired demo channel
    language: t.locale?.startsWith("es") ? "es" : "en",
    center: loc.center,
    zoom: loc.zoom,
  });

  // Validate the typed premise ID, then complete. Keeps the customer on this screen with a friendly
  // message if the ID isn't found, rather than dropping them into a broken map.
  const submitPremise = async (e) => {
    e.preventDefault();
    const id = premiseId.trim();
    if (!id || busy) return;
    setBusy(true); setError(null);
    try {
      const loc = await fetch(`/api/locate?premise_id=${encodeURIComponent(id)}`).then((r) => r.json());
      if (!loc.valid) { setError(loc.reason || o.notFound); return; }
      finish(loc);
    } catch {
      setError(o.offline);
    } finally { setBusy(false); }
  };

  // "Use my location": browser geolocation -> backend snaps to the nearest neighborhood transformer.
  const useMyLocation = () => {
    if (!navigator.geolocation) { setError(o.noGeolocation); return; }
    setLocating(true); setError(null);
    navigator.geolocation.getCurrentPosition(
      async (pos) => {
        try {
          const { latitude, longitude } = pos.coords;
          const loc = await fetch(`/api/locate?lat=${latitude}&lon=${longitude}`).then((r) => r.json());
          if (!loc.valid) { setError(loc.reason || o.outOfArea); return; }
          finish(loc);     // premise_id falls back to the snapped dot id inside finish()
        } catch {
          setError(o.offline);
        } finally { setLocating(false); }
      },
      () => { setLocating(false); setError(o.geolocationDenied); },
      { timeout: 10000 },
    );
  };

  if (publicDemo) {
    return (
      <section className="onboarding" aria-label={o.demoTitle}>
        <div className="ob-card">
          <h1>{o.demoTitle}</h1>
          <p className="ob-lede">{o.demoLede}</p>
          <div className="ob-actions">
            {demoLocations.map((place, index) => (
              <button key={place.id} type="button" className="ob-primary" onClick={() => onComplete({
                premise_id: place.id, declared_needs: [], alerts_enrolled: false, channels: [],
                language: t.locale?.startsWith("es") ? "es" : "en",
                center: { lat: place.lat, lon: place.lon }, zoom: 14,
              })}>{o.demoArea(index + 1)}</button>
            ))}
          </div>
          <p className="ob-privacy">{o.demoPrivacy}</p>
        </div>
      </section>
    );
  }

  return (
    <section className="onboarding" aria-label={o.title}>
      <div className="ob-card">
        <h1>{o.title}</h1>
        <p className="ob-lede">{o.lede}</p>

        <form onSubmit={submitPremise}>
          <label className="ob-field" htmlFor="ob-premise">{o.premiseLabel}
            <input id="ob-premise" inputMode="numeric" autoComplete="off" value={premiseId}
              onChange={(e) => setPremiseId(e.target.value)} placeholder={o.premisePlaceholder} />
            <span className="ob-hint">{o.premiseHint}</span>
          </label>

          {/* "Where's my Premise ID?" helper: a GENERIC sample statement (no AEP branding) showing a FAKE
              9-digit number, so users know what to look for. Collapsed by default to keep the screen clean.
              The sample id is made up (123456789) — never a real premise id.
              NOTE: strings fall back to English inline until Nandan adds them to i18n.js (o.helpSummary etc.),
              so the box reads correctly before the i18n keys land. */}
          <details className="ob-help">
            <summary>{o.helpSummary ?? "Where's my Premise ID?"}</summary>
            <div className="ob-bill" role="img" aria-label={o.billAria ?? "Example statement showing where the Premise ID appears"}>
              <div className="ob-bill-head">
                <span className="ob-bill-logo" aria-hidden="true">⚡</span>
                <span className="ob-bill-title">{o.billTitle ?? "Sample statement"}</span>
              </div>
              <div className="ob-bill-rows">
                <div><span>{o.billName ?? "Name"}</span><b>Jane Doe</b></div>
                <div><span>{o.billService ?? "Service address"}</span><b>123 Example St</b></div>
                <div className="ob-bill-highlight"><span>{o.premiseLabel ?? "Premise ID"}</span><b>123456789</b></div>
                <div><span>{o.billAmount ?? "Amount due"}</span><b>$84.20</b></div>
              </div>
              <p className="ob-bill-note">{o.helpNote
                ?? "Look for the 9-digit number labeled \u201cPremise ID\u201d on your statement. This is a made-up example."}</p>
            </div>
          </details>

          <label className="check ob-enroll">
            <input type="checkbox" checked={enrolled} onChange={() => setEnrolled(!enrolled)} />{o.enroll}</label>

          {error && <p className="ob-error" role="alert">{error}</p>}

          <div className="ob-actions">
            <button type="submit" className="ob-primary" disabled={busy || !premiseId.trim()}>
              {busy ? o.checking : o.continue}</button>
            <button type="button" className="ob-secondary" onClick={useMyLocation} disabled={locating}>
              {locating ? o.locating : o.useLocation}</button>
          </div>
        </form>

        <p className="ob-privacy">{o.privacy}</p>
      </div>
    </section>
  );
}
