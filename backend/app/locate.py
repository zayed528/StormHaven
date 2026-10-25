"""
Location lookup for onboarding (customer view).   Owner: Abby
  GET /api/locate?premise_id=...       validate a premise ID -> the neighborhood dot + map center/zoom
  GET /api/locate?lat=...&lon=...      "use my location" -> snap to the nearest neighborhood transformer

Returns exactly what OutageMap needs to zoom in: {valid, map_point_id, center:{lat,lon}, zoom}.
`map_point_id` is the same dot id the /api/map layer draws and the concierge answer rings, so the frontend
just centers on it. Invalid IDs / out-of-area coordinates get a friendly, non-crashing fallback.

Privacy: a premise is placed at its TRANSFORMER's (already-published, map-level) coordinates, never a home
location. We return a neighborhood dot id and a map view, nothing else — no address, no device IDs.
"""
from __future__ import annotations

import math
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.core.data_loader import get_store
from app.core.topology import map_point_for, resolve_location, transformer_for_token
from app.public_demo import enabled as public_demo_enabled, require_demo_location

router = APIRouter(prefix="/api", tags=["locate"])

# Neighborhood zoom level (Plotly map zoom). ~14 shows a few blocks; matches "zoom to my neighborhood".
NEIGHBORHOOD_ZOOM = 14.0
# "Use my location" only snaps to a transformer within this many km, else the point is outside our coverage.
MAX_SNAP_KM = 15.0


def _transformer_of(store, premise_id: str) -> Optional[str]:
    """The transformer feeding a premise = its parent in the graph (edges point parent -> child)."""
    g = store.graph
    parents = list(g.predecessors(premise_id))
    return parents[0] if parents else None


def _coords(store, node_id: str):
    """(lat, lon) for a node, or None if it has no coordinate (some breakers/step transformers don't).
    Privacy: a transformer serving < 3 homes can pinpoint one house, so its map center is coarsened to
    ~100 m (3 decimals); 3+ homes keep ~11 m (4 decimals). Matches the blur in map_layers.py so the zoom
    target never lands more precisely than the dot on the map."""
    g = store.graph
    d = g.nodes[node_id]
    lat, lon = d.get("lat"), d.get("lon")
    if lat is None or lon is None or lat != lat or lon != lon:   # None or NaN
        return None
    n_homes = sum(1 for c in g.successors(node_id) if g.nodes[c]["kind"] == "premise")
    decimals = 3 if n_homes < 3 else 4
    return round(float(lat), decimals), round(float(lon), decimals)


def _fallback(reason: str) -> dict:
    """Shape the frontend can always read: not valid, no dot, no view to jump to."""
    return {"valid": False, "map_point_id": None, "center": None, "zoom": None, "reason": reason}


@router.get("/locate")
def locate(premise_id: Optional[str] = None,
           lat: Optional[float] = Query(None, ge=-90, le=90),
           lon: Optional[float] = Query(None, ge=-180, le=180)):
    """Two modes: a premise ID from the bill, or a browser lat/lon ('use my location')."""
    store = get_store()

    if public_demo_enabled():
        if lat is not None or lon is not None:
            raise HTTPException(status_code=400, detail="Browser location is disabled in the public demo.")
        require_demo_location(store, premise_id, None)
        transformer = transformer_for_token(store, premise_id)
        xy = _coords(store, transformer)
        return {"valid": True, "map_point_id": premise_id,
                "center": {"lat": xy[0], "lon": xy[1]} if xy else None,
                "zoom": NEIGHBORHOOD_ZOOM}

    # --- Mode A: premise ID from the bill ---
    if premise_id:
        premise_id = premise_id.strip()
        level, node = resolve_location(store, premise_id, None)
        if level != "premise":
            return _fallback("We couldn't find that premise ID. Check your bill, or tap your neighborhood on the map.")
        # Zoom to the premise's transformer (where its map dot lives).
        xf = _transformer_of(store, node)
        xy = _coords(store, xf) if xf else None
        dot = map_point_for(store, xf) if xf else None
        if xy is None or dot is None:
            # Valid premise, but its transformer has no coordinate -> can't zoom. Still "valid"; UI just won't jump.
            return {"valid": True, "map_point_id": dot, "center": None, "zoom": None,
                    "reason": "Found your service area, but there's no map location to zoom to."}
        return {"valid": True, "map_point_id": dot,
                "center": {"lat": round(xy[0], 5), "lon": round(xy[1], 5)}, "zoom": NEIGHBORHOOD_ZOOM}

    # --- Mode B: "use my location" (browser coordinates) -> nearest neighborhood transformer ---
    if lat is not None and lon is not None:
        nearest, best_km = _nearest_transformer(store, lat, lon)
        if nearest is None or best_km > MAX_SNAP_KM:
            return _fallback("StormHaven covers the AEP service area. Enter your premise ID to continue.")
        xy = _coords(store, nearest)
        dot = map_point_for(store, nearest)
        if xy is None or dot is None:
            return _fallback("Couldn't match your location to a neighborhood. Enter your premise ID instead.")
        return {"valid": True, "map_point_id": dot,
                "center": {"lat": round(xy[0], 5), "lon": round(xy[1], 5)}, "zoom": NEIGHBORHOOD_ZOOM}

    return _fallback("Enter your premise ID, or share your location.")


def _nearest_transformer(store, lat: float, lon: float):
    """Nearest transformer (with coordinates) to a point, and the distance in km. Linear scan: fine at
    ~25k transformers for a one-off onboarding call. Equirectangular distance is plenty at neighborhood scale."""
    g = store.graph
    best, best_km = None, math.inf
    cos_lat = math.cos(math.radians(lat))
    for n, d in g.nodes(data=True):
        if d.get("kind") != "transformer":
            continue
        tlat, tlon = d.get("lat"), d.get("lon")
        if tlat is None or tlon is None or tlat != tlat or tlon != tlon:
            continue
        dx = (tlon - lon) * cos_lat
        dy = (tlat - lat)
        km = 111.0 * math.hypot(dx, dy)          # ~111 km per degree
        if km < best_km:
            best, best_km = n, km
    return best, best_km
