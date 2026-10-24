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

// Props: layers = GET /api/map response, selectedId = chosen premise, onSelect(id) = click handler, t = UI text (i18n.js).
export default function OutageMap({ t, layers, selectedId, onSelect }) {
  // Rebuild traces only when data or selection changes (Plotly redraws are expensive).
  const traces = useMemo(() => {
    if (!layers) return [];
    // 1) Circuit lines: one trace per circuit, segments separated by null
    const lines = layers.circuits.map((c) => ({
      type: "scattermap", mode: "lines", lat: c.lat, lon: c.lon,
      line: { width: 2, color: "#5B6B7A" }, hoverinfo: "skip", showlegend: false,
    }));
    // 2a) Dark halo under every dot: scattermap markers have no outline option, and the yellow/green dots alone
    //     are too faint against the light basemap (needs 3:1 contrast). Drawn first, so it sits underneath.
    const halo = [{
      type: "scattermap", mode: "markers", lat: layers.premises.map((p) => p.lat), lon: layers.premises.map((p) => p.lon),
      marker: { size: 10, color: "#14213D" }, hoverinfo: "skip", showlegend: false,
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
        marker: { size: 7, color: BAND_COLORS[band] },
      };
    });
    // 3) Selected premise ring
    const sel = layers.premises.find((p) => p.id === selectedId);
    const ring = sel ? [{
      type: "scattermap", mode: "markers", lat: [sel.lat], lon: [sel.lon], hoverinfo: "skip",
      marker: { size: 22, color: "rgba(0,0,0,0)", line: { width: 3, color: "#14213D" } }, showlegend: false,
    }] : [];
    return [...lines, ...halo, ...byBand, ...ring];
  }, [layers, selectedId, t]);

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

  return (
    <Plot
      data={traces}
      layout={{
        map: { style: "carto-positron", center: view.center, zoom: view.zoom },
        margin: { l: 0, r: 0, t: 0, b: 0 },
        legend: { x: 0.01, y: 0.99, bgcolor: "rgba(255,255,255,0.85)", title: { text: t.mapLegend } },
        uirevision: "keep",                                   // don't reset zoom on every update
      }}
      config={{ displayModeBar: false, scrollZoom: true, responsive: true }}
      style={{ width: "100%", height: "100%" }}
      // Clicking a premise marker reports its id (stored in customdata); lines carry no customdata.
      onClick={(e) => { const id = e.points?.[0]?.customdata; if (id) onSelect(id); }}
    />
  );
}
