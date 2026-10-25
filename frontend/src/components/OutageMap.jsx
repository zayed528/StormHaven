// Interactive Plotly map (owner: Abby UI, Jaid layers). No API key: "scattermap" traces render with MapLibre
// and the free "carto-positron" (light theme) / "carto-darkmatter" (dark theme) basemaps.
// Two views (toggle in the map's top-right corner): risk dots, or risk dots over a heatmap of where homes are
// likely to lose power. The dots stay visible and clickable in both, so you always see where the homes are.
import React, { useMemo, useState } from "react";
import createPlotlyComponent from "react-plotly.js/factory";
import Plotly from "plotly.js-dist-min";

// Factory import: we hand react-plotly the small prebuilt bundle (plotly.js-dist-min)
// instead of letting it import the full plotly.js source, which is much larger and slower to build.
const Plot = createPlotlyComponent(Plotly);

// Risk band -> marker color. Also used by ResultsPanel for the band's left border.
export const BAND_COLORS = { Low: "#4C9F70", Moderate: "#E3B23C", High: "#D9682B", "Very High": "#A4243B" };

// Heatmap: each dot adds (outage chance x homes it serves) = homes likely to lose power there.
// FIXED scale (not auto), so a calm storm stays faint and only the worst storm turns broadly red. Values add up
// within the radius, so at the zoomed-out starting view many dots overlap: the scale is set for that view.
// Transparent at 0 so the basemap shows through.
const HEAT_MAX = 14;
// Colors that change with the theme: lines, the outline under each dot, the selected-home ring, the legend box.
// On the dark map the dot outline turns light, so dots (the dark-red ones especially) still stand out.
const MAP_THEME = {
  light: { style: "carto-positron", line: "#5B6B7A", faintLine: "rgba(91,107,122,0.25)", halo: "#14213D",
           ring: "#14213D", legendBg: "rgba(255,255,255,0.85)", text: "#14213D", paper: "#FFFFFF" },
  dark: { style: "carto-darkmatter", line: "#7D8EA3", faintLine: "rgba(163,177,194,0.22)", halo: "#DCE4EE",
          ring: "#FFFFFF", legendBg: "rgba(23,33,49,0.88)", text: "#E6EDF5", paper: "#0F1623" },
};
const HEAT_COLORS = [[0, "rgba(76,159,112,0)"], [0.08, "rgba(76,159,112,0.45)"], [0.3, "rgba(227,178,60,0.75)"],
                     [0.6, "rgba(217,104,43,0.85)"], [1, "rgba(164,36,59,0.95)"]];

// Props: layers = GET /api/map response, selectedId = chosen premise, onSelect(id) = click handler, t = UI text (i18n.js),
// focus = {lat, lon, zoom, key} to zoom to the customer's neighborhood (null = whole territory).
export default function OutageMap({ t, dark = false, layers, focus = null, selectedId, onSelect }) {
  const c = dark ? MAP_THEME.dark : MAP_THEME.light;
  const [mode, setMode] = useState("dots");        // "dots" | "heat"
  const heat = mode === "heat";
  // All circuits' line coordinates joined into one list (null between circuits). Only changes with new map data.
  const lineCoords = useMemo(() => ({
    lat: layers ? layers.circuits.flatMap((k) => [...k.lat, null]) : [],
    lon: layers ? layers.circuits.flatMap((k) => [...k.lon, null]) : [],
  }), [layers]);
  // Rebuild traces only when data or selection changes (Plotly redraws are expensive).
  const traces = useMemo(() => {
    if (!layers) return [];
    // 1) Circuit lines: ONE trace for every circuit (they share a color; null lifts the pen between pieces).
    //    110 separate traces meant 110 map layers, and redrawing them froze the page for over a second on each
    //    storm-level change, long enough to hide the "what changed" highlight.
    const lines = [{
      type: "scattermap", mode: "lines", lat: lineCoords.lat, lon: lineCoords.lon,
      // Heatmap view: thin and faint, or the dense line network paints the town dark over the heat.
      line: heat ? { width: 1, color: c.faintLine } : { width: 2, color: c.line },
      hoverinfo: "skip", showlegend: false,
    }];
    // Heatmap view: a glowing surface of homes likely to lose power (drawn under the dots, never clickable).
    const heatLayer = heat ? [{
      type: "densitymap", lat: layers.premises.map((p) => p.lat), lon: layers.premises.map((p) => p.lon),
      z: layers.premises.map((p) => p.p * p.n), radius: 14, zmin: 0, zmax: HEAT_MAX,
      colorscale: HEAT_COLORS, showscale: false, hoverinfo: "skip",
    }] : [];
    // 2a) Dark halo under every dot: scattermap markers have no outline option, and the yellow/green dots alone
    //     are too faint against the light basemap (needs 3:1 contrast). Drawn first, so it sits underneath.
    const halo = heat ? [] : [{                    // dots view only; over the heatmap the dots go without it
      type: "scattermap", mode: "markers", lat: layers.premises.map((p) => p.lat), lon: layers.premises.map((p) => p.lon),
      marker: { size: 10, color: c.halo }, hoverinfo: "skip", showlegend: false,
    }];
    // 2b) Premises: one trace per band so the legend explains the colors
    const byBand = Object.keys(BAND_COLORS).map((band) => {
      const pts = layers.premises.filter((p) => p.band === band);
      return {
        type: "scattermap", mode: "markers", name: t.bands[band],
        lat: pts.map((p) => p.lat), lon: pts.map((p) => p.lon),
        customdata: pts.map((p) => p.id),                    // click -> premise id
        // Each point is one transformer; n = homes it serves (no home-level locations are sent).
        text: pts.map((p) => t.mapHover(t.bands[band], p.n)),
        hovertemplate: "%{text}<extra></extra>",
        // Heatmap view: smaller and without the dark halo, so the heat still shows between the homes.
        marker: { size: heat ? 4 : 7, color: BAND_COLORS[band] },
      };
    });
    // 3) The customer's home: a glowing target drawn UNDER its dot (a soft outer glow + a solid disc; the colored
    //    dot sits in the middle). scattermap ignores marker outlines, so a hollow ring would be invisible.
    const sel = layers.premises.find((p) => p.id === selectedId);
    const target = sel ? [30, 17].map((size, i) => ({
      type: "scattermap", mode: "markers", lat: [sel.lat], lon: [sel.lon], hoverinfo: "skip", showlegend: false,
      marker: { size, color: c.ring, opacity: i === 0 ? 0.3 : 1 },
    })) : [];
    return [...lines, ...heatLayer, ...halo, ...target, ...byBand];
  }, [layers, lineCoords, selectedId, t, heat, c]);

  // Fit the view to the data: center on the middle of the points' bounding box, zoom so it all fits.
  // (Synthetic demo network ~0.1 degrees wide -> zoom ~11; AEP service area ~0.6 degrees -> zoom ~8.)
  const view = useMemo(() => {
    const p = layers?.premises ?? [];
    if (!p.length) return { center: { lat: 40, lon: -83 }, zoom: 9 };
    let [minLat, maxLat, minLon, maxLon] = [Infinity, -Infinity, Infinity, -Infinity];
    for (const x of p) {
      if (x.lat < minLat) minLat = x.lat; if (x.lat > maxLat) maxLat = x.lat;
      if (x.lon < minLon) minLon = x.lon; if (x.lon > maxLon) maxLon = x.lon;
    }
    const span = Math.max(maxLon - minLon, (maxLat - minLat) * 1.3, 0.005);
    const zoom = Math.min(13, Math.max(3, Math.log2(360 / span) - 1));
    return { center: { lat: (minLat + maxLat) / 2, lon: (minLon + maxLon) / 2 }, zoom };
  }, [layers]);

  return (<>
    <Plot
      data={traces}
      layout={{
        map: { style: c.style, center: focus ? { lat: focus.lat, lon: focus.lon } : view.center,
               zoom: focus ? focus.zoom : view.zoom },
        paper_bgcolor: c.paper,
        margin: { l: 0, r: 0, t: 0, b: 0 },
        legend: { x: 0.01, y: 0.99, bgcolor: c.legendBg, font: { color: c.text }, title: { text: t.mapLegend, font: { color: c.text } } },
        // Keep the user's pan/zoom across updates; a new focus (a new key) re-centers the map on purpose.
        uirevision: focus?.key ?? "overview",
      }}
      config={{ displayModeBar: false, scrollZoom: true, responsive: true }}
      style={{ width: "100%", height: "100%" }}
      // Clicking a premise marker reports its id (stored in customdata); lines carry no customdata.
      onClick={(e) => { const id = e.points?.[0]?.customdata; if (id) onSelect(id); }}
    />
    {/* View switch, over the map's top-right corner. Visual only: the answer and its text don't change. */}
    <div className="map-tools">
      <div className="map-mode" role="group" aria-label={t.mapView}>
        <button type="button" aria-pressed={!heat} onClick={() => setMode("dots")}>{t.mapDots}</button>
        <button type="button" aria-pressed={heat} onClick={() => setMode("heat")}>{t.mapHeat}</button>
      </div>
      {heat && <p className="heat-legend"><span className="heat-ramp" aria-hidden="true" />{t.heatLegend}</p>}
    </div>
  </>);
}
