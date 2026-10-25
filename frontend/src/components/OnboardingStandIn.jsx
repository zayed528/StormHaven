// TEMPORARY stand-in for Abby's onboarding (frontend/src/onboarding/Onboarding.jsx).   Owner: Nandan
// App.jsx mounts Abby's component automatically as soon as that file exists; this file can then be deleted.
// Same contract as hers: props { t, onComplete }, and onComplete({ premise_id, declared_needs, alerts_enrolled,
// channels, language, center, zoom }). center/zoom come from GET /api/locate; until that endpoint is wired they're
// null and App zooms to the customer's dot from the concierge answer instead.
import React, { useState } from "react";

const NEEDS = ["refrigerated_medication", "mobility", "infants", "pets", "critical_facility"];

export default function OnboardingStandIn({ t, onComplete }) {
  const [premiseId, setPremiseId] = useState("");
  const [needs, setNeeds] = useState([]);
  const [enrolled, setEnrolled] = useState(true);
  const [busy, setBusy] = useState(false);
  const [notFound, setNotFound] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    const id = premiseId.trim();
    if (!id || busy) return;
    setBusy(true); setNotFound(false);
    let place = { center: null, zoom: null };
    try {
      const r = await fetch(`/api/locate?premise_id=${encodeURIComponent(id)}`);
      if (r.ok) {
        const loc = await r.json();
        if (loc.valid === false) { setNotFound(true); setBusy(false); return; }
        place = { center: loc.center ?? null, zoom: loc.zoom ?? null };
      }
    } catch { /* endpoint not reachable: App zooms from the concierge answer instead */ }
    setBusy(false);
    onComplete({ premise_id: id, declared_needs: needs, alerts_enrolled: enrolled, channels: enrolled ? ["sms"] : [],
                 language: t.locale.startsWith("es") ? "es" : "en", ...place });
  };

  return (
    <form className="onboard" onSubmit={submit} aria-labelledby="onboard-title">
      <h2 id="onboard-title">{t.onboardTitle}</h2>
      <p className="muted">{t.onboardIntro}</p>
      <label className="onboard-field">{t.onboardPremise}
        <input value={premiseId} onChange={(e) => setPremiseId(e.target.value)} placeholder={t.locatePlaceholder}
          inputMode="numeric" autoComplete="off" aria-invalid={notFound} aria-describedby={notFound ? "onboard-error" : undefined} />
      </label>
      {notFound && <p id="onboard-error" className="error" role="alert">{t.onboardNotFound}</p>}
      <fieldset><legend>{t.needsLegend}</legend>
        {NEEDS.map((k) => (
          <label key={k} className="check">
            <input type="checkbox" checked={needs.includes(k)}
              onChange={() => setNeeds(needs.includes(k) ? needs.filter((x) => x !== k) : [...needs, k])} />{t.needs[k]}</label>))}
      </fieldset>
      <label className="check"><input type="checkbox" checked={enrolled} onChange={() => setEnrolled(!enrolled)} />{t.enrolled}</label>
      <button type="submit" className="onboard-go" disabled={!premiseId.trim() || busy}>{busy ? t.sending : t.onboardContinue}</button>
    </form>
  );
}
