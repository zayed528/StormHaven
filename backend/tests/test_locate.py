"""GET /api/locate (app/locate.py) — onboarding location lookup. Run: make test.
Works on whichever network is loaded: a premise is picked from the store, not hardcoded.

Skips until Jaid adds `app.include_router(locate_router)` to main.py, so it never reds the build early."""
import pytest
from fastapi.testclient import TestClient

from app.core.data_loader import get_store
from app.main import app

client = TestClient(app)

# Probe the endpoint: a missing route 404s, a wired one returns 200. (Enumerating app.routes is unreliable
# for prefixed sub-routers in this FastAPI version.)
pytestmark = pytest.mark.skipif(
    client.get("/api/locate?premise_id=x").status_code == 404,
    reason="locate router not registered in main.py yet (add include_router(locate_router))")


def _a_premise_and_coords():
    g = get_store().graph
    for n, d in g.nodes(data=True):
        if d.get("kind") == "premise":
            xf = next(iter(g.predecessors(n)), None)
            if xf and g.nodes[xf].get("lat") == g.nodes[xf].get("lat"):   # transformer has coords
                return n, g.nodes[xf]["lat"], g.nodes[xf]["lon"]
    raise AssertionError("no premise with a located transformer")


def test_valid_premise_returns_center_and_zoom():
    prem, lat, lon = _a_premise_and_coords()
    r = client.get(f"/api/locate?premise_id={prem}").json()
    assert r["valid"] is True and r["map_point_id"]
    assert r["center"] and r["zoom"] and abs(r["center"]["lat"] - lat) < 0.01


def test_invalid_premise_is_friendly_fallback():
    r = client.get("/api/locate?premise_id=not-a-real-premise-123").json()
    assert r["valid"] is False and r["center"] is None and r["reason"]


def test_use_my_location_snaps_to_nearest_neighborhood():
    _, lat, lon = _a_premise_and_coords()
    r = client.get(f"/api/locate?lat={lat + 0.002}&lon={lon + 0.002}").json()
    assert r["valid"] is True and r["center"] and r["zoom"]


def test_location_out_of_area_is_refused():
    # Columbus OH, far from the Roanoke VA service area.
    r = client.get("/api/locate?lat=40.0&lon=-83.0").json()
    assert r["valid"] is False and "service area" in r["reason"].lower()


def test_nothing_given_prompts():
    r = client.get("/api/locate").json()
    assert r["valid"] is False and r["reason"]
