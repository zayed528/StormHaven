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

export default function Onboarding({ t, onComplete }) {
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
