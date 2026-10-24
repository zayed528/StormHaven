// Interactive Plotly map (owner: Abby UI, Jaid layers). No API key: "scattermap" traces render with MapLibre
// and the free "carto-positron" / "open-street-map" basemaps.
import React, { useMemo } from "react";
import createPlotlyComponent from "react-plotly.js/factory";
import Plotly from "plotly.js-dist-min";

// Factory import: we hand react-plotly the small prebuilt bundle (plotly.js-dist-min)
// instead of letting it import the full plotly.js source, which is much larger and slower to build.
const Plot = createPlotlyComponent(Plotly);

// Risk band -> marker color. Also used by ResultsPanel for the band's left border.
export const BAND_COLORS = { Low: "#4C9F70", Moderate: "#E3B23C", High: "#D9682B", "Very High": "#A4243B" };

// Props: layers = GET /api/map response, selectedId = chosen premise, onSelect(id) = click handler.
export default function OutageMap({ layers, selectedId, onSelect }) {
  // Rebuild traces only when data or selection changes (Plotly redraws are expensive).
  const traces = useMemo(() => {
    if (!layers) return [];
    // 1) Circuit lines: one trace per circuit, segments separated by null
    const lines = layers.circuits.map((c) => ({
      type: "scattermap", mode: "lines", lat: c.lat, lon: c.lon,
      line: { width: 2, color: "#5B6B7A" }, hoverinfo: "skip", showlegend: false,
    }));
    // 2) Premises: one trace per band so the legend explains the colors
    const byBand = Object.keys(BAND_COLORS).map((band) => {
      const pts = layers.premises.filter((p) => p.band === band);
      return {
        type: "scattermap", mode: "markers", name: band,
        lat: pts.map((p) => p.lat), lon: pts.map((p) => p.lon),
        customdata: pts.map((p) => p.id),                    // click -> premise id
        text: pts.map((p) => `${band} risk`), hovertemplate: "%{text}<extra></extra>",
        marker: { size: 9, color: BAND_COLORS[band] },
      };
    });
    // 3) Selected premise ring
    const sel = layers.premises.find((p) => p.id === selectedId);
    const ring = sel ? [{
      type: "scattermap", mode: "markers", lat: [sel.lat], lon: [sel.lon], hoverinfo: "skip",
      marker: { size: 22, color: "rgba(0,0,0,0)", line: { width: 3, color: "#14213D" } }, showlegend: false,
    }] : [];
    return [...lines, ...byBand, ...ring];
  }, [layers, selectedId]);

  // Center the map on the average premise location (recomputed when the data changes).
  const center = useMemo(() => {
    const p = layers?.premises ?? [];
    if (!p.length) return { lat: 40, lon: -83 };
    return { lat: p.reduce((s, x) => s + x.lat, 0) / p.length, lon: p.reduce((s, x) => s + x.lon, 0) / p.length };
  }, [layers]);

  return (
    <Plot
      data={traces}
      layout={{
        map: { style: "carto-positron", center, zoom: 11 },
        margin: { l: 0, r: 0, t: 0, b: 0 },
        legend: { x: 0.01, y: 0.99, bgcolor: "rgba(255,255,255,0.85)", title: { text: "Outage risk" } },
        uirevision: "keep",                                   // don't reset zoom on every update
      }}
      config={{ displayModeBar: false, scrollZoom: true, responsive: true }}
      style={{ width: "100%", height: "100%" }}
      // Clicking a premise marker reports its id (stored in customdata); lines carry no customdata.
      onClick={(e) => { const id = e.points?.[0]?.customdata; if (id) onSelect(id); }}
    />
  );
}
