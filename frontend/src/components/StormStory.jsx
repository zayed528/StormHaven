// "Play the storm": one tap plays this home's storm as the texts the customer would get, in order:
// pre-storm alert -> outage confirmed (simulated utility status) -> estimate updated (crews find a broken pole on the
// line) -> restored.
// Every message is the REAL engine text for this home (alerts.messages), re-computed at each step, so the
// "estimate updated" text shows the real old -> new range and reason. Demo only: nothing is sent.   Owner: Nandan
import React, { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

const STEPS = ["pre_storm", "outage_confirmed", "estimate_updated", "restoration_complete"];
const STEP_MS = 5000;

const POLE = [{ damage_type: "broken_pole", quantity: 1 }];

export default function StormStory({ t, messages, scenario, onScenario, setConfirmed }) {
  const [step, setStep] = useState(-1);            // -1 = idle
  const timers = useRef([]);
  const base = useRef(null);

  const clear = () => { timers.current.forEach(clearTimeout); timers.current = []; };
  useEffect(() => clear, []);                       // stop timers if the card unmounts

  const stop = () => {
    clear();
    setStep(-1);
    if (base.current) { onScenario(base.current); base.current = null; }
    setConfirmed(false);
  };
  const play = () => {
    clear();
    base.current = scenario;
    setConfirmed(false);
    setStep(0);
    const at = (ms, fn) => timers.current.push(setTimeout(fn, ms));
    at(STEP_MS, () => { setConfirmed(true); setStep(1); });
    at(2 * STEP_MS, () => { onScenario({ ...base.current, extra_damage: POLE }); setStep(2); });
    at(3 * STEP_MS, () => setStep(3));
    at(4 * STEP_MS + 1500, stop);
  };

  const key = STEPS[step];
  return (
    <>
      <button type="button" className="story-button" onClick={step < 0 ? play : stop} aria-pressed={step >= 0}>
        {step < 0 ? `▶ ${t.storyPlay}` : `■ ${t.storyStop}`}</button>
      {/* Portal: the cards sit in a frosted (backdrop-filter) dock, which would trap a position:fixed toast inside
          the off-screen card. Rendering into <body> puts it at the top of the screen like a real notification. */}
      {step >= 0 && messages[key] && createPortal(
        <div className="story-toast" role="status" aria-live="polite" key={key}>
          <div className="story-head"><strong>StormHaven</strong> · {t.storyNow}
            <span className="story-step">{step + 1}/{STEPS.length} · {t.messageLabels[key] ?? key}</span></div>
          <p>{messages[key]}</p>
        </div>, document.body)}
    </>
  );
}
