"""
Builds map data in a Plotly-friendly shape.   Owner: Jaid
- lines: one list of lat/lon with None separators per circuit (fast to render as ONE trace)
- premises: points with band for coloring + premise_id in customdata for click selection
Critical facilities are NEVER included.
If data/processed/circuits.geojson exists (from pipelines/06), use real GIS lines instead.
"""
from __future__ import annotations
import json
from functools import lru_cache

from app.config import DATA_PROCESSED
from app.core.data_loader import get_store
from app.engines.risk import band_for, compute_path_risk
from app.schemas import StormScenario


@lru_cache(maxsize=1)
def _lines() -> dict[str, dict]:
    """Circuit polylines keyed by circuit_id. Cached: lines don't depend on the storm scenario."""
    gj = DATA_PROCESSED / "circuits.geojson"
    out: dict[str, dict] = {}
    # Real GIS lines (pipelines/06). A None between segments tells Plotly to lift the pen,
    # so one trace can draw many disconnected pieces.
    if gj.exists():
        for feat in json.loads(gj.read_text())["features"]:
            cid = str(feat["properties"].get("circuit_id", "unknown"))
            geom = feat["geometry"]
            parts = geom["coordinates"] if geom["type"] == "MultiLineString" else [geom["coordinates"]]
            o = out.setdefault(cid, {"lat": [], "lon": []})
            for part in parts:
                o["lon"] += [c[0] for c in part] + [None]
                o["lat"] += [c[1] for c in part] + [None]
        return out
    g = get_store().graph   # synthetic: draw edges between devices
    for u, v in g.edges:
        if g.nodes[v]["kind"] == "premise":        # skip service drops: premises are drawn as points
            continue
        cid = g.nodes[v]["circuit_id"]
        o = out.setdefault(cid, {"lat": [], "lon": []})
        o["lat"] += [g.nodes[u]["lat"], g.nodes[v]["lat"], None]
        o["lon"] += [g.nodes[u]["lon"], g.nodes[v]["lon"], None]
    return out


def map_layers(severity: float) -> dict:
    """Premise points colored by risk at this severity, plus circuit lines. Called on every slider move."""
    store = get_store()
    sc = StormScenario(severity_percentile=severity)
    prem = []
    for n, d in store.graph.nodes(data=True):
        if d["kind"] != "premise" or d.get("lat") != d.get("lat"):   # skip non-premises and NaN coords
            continue
        p = compute_path_risk(store, n, None, sc).probability    # same math as the concierge answer
        prem.append({"id": n, "lat": round(d["lat"], 4), "lon": round(d["lon"], 4),   # masked precision
                     "circuit_id": d["circuit_id"], "p": round(p, 3), "band": band_for(p)})
    return {"circuits": [{"circuit_id": k, **v} for k, v in _lines().items()], "premises": prem}
