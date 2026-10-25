"""
Builds map data in a Plotly-friendly shape.   Owner: Jaid
- lines: one list of lat/lon with None separators per circuit (fast to render as ONE trace)
- premises: ONE POINT PER TRANSFORMER (the homes it serves), colored by risk band. Every home behind a
  transformer shares the same upline path, so it shares the same risk; showing transformers instead of homes
  loses nothing for the model and means no home-level location is ever sent to the browser.
  `id` is one premise behind that transformer (click -> concierge request); `n` = homes it serves.
Critical facilities are NEVER included.
Real GIS lines (circuits.geojson from pipelines/06) are used when the store holds real data.
"""
from __future__ import annotations
import json
from functools import lru_cache

import numpy as np

from app.config import DATA_PROCESSED
from app.core.data_loader import get_store
from app.core.topology import map_point_for, upline_path
from app.engines.risk import _base_prob, band_for, severity_multiplier

_COORD_DECIMALS = 5          # ~1 m; plenty for drawing lines, roughly halves the payload


@lru_cache(maxsize=1)
def _lines() -> dict[str, dict]:
    """Circuit polylines keyed by circuit_id. Cached: lines don't depend on the storm scenario."""
    store = get_store()
    gj = DATA_PROCESSED / "circuits.geojson"
    out: dict[str, dict] = {}
    # Real GIS lines (pipelines/06). A None between segments tells Plotly to lift the pen,
    # so one trace can draw many disconnected pieces.
    if gj.exists() and not store.is_synthetic:
        for feat in json.loads(gj.read_text())["features"]:
            cid = str(feat["properties"].get("circuit_id", "unknown"))
            geom = feat["geometry"]
            parts = geom["coordinates"] if geom["type"] == "MultiLineString" else [geom["coordinates"]]
            o = out.setdefault(cid, {"lat": [], "lon": []})
            for part in parts:
                o["lon"] += [round(c[0], _COORD_DECIMALS) for c in part] + [None]
                o["lat"] += [round(c[1], _COORD_DECIMALS) for c in part] + [None]
        return out
    g = store.graph   # synthetic: draw edges between devices
    for u, v in g.edges:
        if g.nodes[v]["kind"] == "premise":        # skip service drops: homes are shown via their transformer
            continue
        cid = g.nodes[v]["circuit_id"]
        o = out.setdefault(cid, {"lat": [], "lon": []})
        o["lat"] += [g.nodes[u]["lat"], g.nodes[v]["lat"], None]
        o["lon"] += [g.nodes[u]["lon"], g.nodes[v]["lon"], None]
    return out


@lru_cache(maxsize=1)
def _points() -> tuple[list[dict], np.ndarray]:
    """Per transformer: static fields + path hazard H = sum over its path of -log(1 - p_i).
    Then P(out) at any severity is 1 - exp(-m * H): the same number compute_path_risk gives a premise
    (its path is this transformer + everything upstream), computed for all transformers at once."""
    store = get_store()
    g = store.graph
    pts, hazard = [], []
    for n, d in g.nodes(data=True):
        if d["kind"] != "transformer" or d.get("lat") != d.get("lat"):   # NaN coords -> can't draw
            continue
        token = map_point_for(store, n)        # anonymous dot id (not a premise number); None if no homes
        if token is None:
            continue
        n_homes = sum(1 for c in g.successors(n) if g.nodes[c]["kind"] == "premise")
        # Hazard is computed from the TRANSFORMER's upline path (its own path to the substation). The path
        # doesn't depend on which home we pick, so we walk up from the transformer directly.
        path = [n] + upline_path(store, n)
        base = np.clip([_base_prob(g.nodes[x]) for x in path], 0, 0.999)
        hazard.append(float(-np.log1p(-base).sum()))
        # Privacy: a dot serving < 3 homes can pinpoint one house, so coarsen its coordinates to ~100 m
        # (3 decimals ≈ 110 m). Dots serving 3+ homes keep ~11 m (4 decimals).
        decimals = 3 if n_homes < 3 else 4
        # circuit_id is kept here for INTERNAL callers (the operator console groups dots by circuit); it is
        # stripped from the public /api/map payload in map_layers() below, so customers never receive it.
        pts.append({"id": token, "lat": round(d["lat"], decimals), "lon": round(d["lon"], decimals),
                    "n": n_homes, "circuit_id": d["circuit_id"]})
    return pts, np.array(hazard)


def map_layers(severity: float) -> dict:
    """Transformer points colored by risk at this severity, plus circuit lines. Called on every slider move.
    PUBLIC/customer-facing: each dot carries only an anonymous token + blurred coords + home count + risk.
    circuit_id (internal-only) is dropped here even though _points() keeps it for the console."""
    pts, hazard = _points()
    p = 1 - np.exp(-severity_multiplier(severity, get_store()) * hazard)
    premises = [{"id": pt["id"], "lat": pt["lat"], "lon": pt["lon"], "n": pt["n"],
                 "p": round(float(pi), 3), "band": band_for(float(pi))} for pt, pi in zip(pts, p)]
    return {"circuits": [{"circuit_id": k, **v} for k, v in _lines().items()], "premises": premises}
