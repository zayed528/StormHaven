// Phone app: the map legend as a side tab on the right edge. Closed, only a small "Outage risk" tab shows; tap it and
// the legend slides out (the four risk colors + the heatmap key); swipe it right (or tap the tab again / Esc) and it
// tucks back in.   Owner: Nandan
import React, { useEffect, useRef, useState } from "react";
import { BAND_COLORS } from "../components/OutageMap.jsx";

export default function RiskLegendTab({ t }) {
  const [open, setOpen] = useState(false);
  const startX = useRef(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (e) => { if (e.key === "Escape") setOpen(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  // Swipe right (40px+, more sideways than up/down) closes it.
  const onTouchStart = (e) => { startX.current = { x: e.touches[0].clientX, y: e.touches[0].clientY }; };
  const onTouchEnd = (e) => {
    const s = startX.current;
    startX.current = null;
    if (!s || !open) return;
    const dx = e.changedTouches[0].clientX - s.x, dy = e.changedTouches[0].clientY - s.y;
    if (dx > 40 && dx > Math.abs(dy)) setOpen(false);
  };

  return (
    <div className={`risk-side${open ? " open" : ""}`} role="region" aria-label={t.mapLegend}
      onTouchStart={onTouchStart} onTouchEnd={onTouchEnd}>
      <button type="button" className="risk-side-tab" aria-expanded={open} aria-controls="risk-side-panel"
        onClick={() => setOpen(!open)}>{t.mapLegend}</button>
      <div id="risk-side-panel" className="risk-side-panel" aria-hidden={!open}>
        <ul>
          {Object.entries(BAND_COLORS).map(([band, color]) => (
            <li key={band}><span className="risk-dot" style={{ background: color }} aria-hidden="true" />{t.bands[band]}</li>))}
        </ul>
        <p className="risk-heat"><span className="heat-ramp" aria-hidden="true" />{t.heatLegend}</p>
      </div>
    </div>
  );
}
