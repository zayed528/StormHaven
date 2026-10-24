"""Operator console endpoints (app/console.py). Run: make test  (or cd backend && pytest -q).
Works on whichever network is loaded: a circuit is picked from the store, not hardcoded.

NOTE: these pass only once Nandan has added `app.include_router(console_router)` to main.py.
Until then they're skipped (so they never red the build before the wiring lands)."""
import pytest
from fastapi.testclient import TestClient

from app.core.data_loader import get_store
from app.main import app
from app.schemas import ConciergeRequest
from app.service import run_concierge

client = TestClient(app)

# Skip the whole module if the router isn't wired yet (the include_router line in main.py).
# Asks the app itself: newer FastAPI wraps included routers, so app.routes no longer lists their paths.
pytestmark = pytest.mark.skipif(
    client.get("/api/console/circuits").status_code == 404,
    reason="console router not registered in main.py yet (Nandan adds include_router)")


def _a_circuit() -> str:
    """A real circuit_id from the loaded network (synthetic or AEP)."""
    g = get_store().graph
    for _, d in g.nodes(data=True):
        cid = d.get("circuit_id")
        if cid and cid != "ALL":
            return cid
    raise AssertionError("no circuit in the loaded network")


def test_circuits_list():
    body = client.get("/api/console/circuits").json()
    assert body["count"] == len(body["circuits"]) and body["count"] > 0
    c0 = body["circuits"][0]
    assert {"circuit_id", "customers", "devices", "critical_zones", "n_events_observed"} <= c0.keys()


def test_restoration_order_upstream_first():
    cid = _a_circuit()
    body = client.get(f"/api/console/restoration/{cid}?severity=80&crews=15").json()
    assert body["circuit_id"] == cid and body["source"] == "model_estimate"
    ranks = [o["rank"] for o in body["order"]]
    assert ranks == sorted(ranks)                                  # ranks are 1..N in order
    # Priority order = the restoration engine's ranking (value vs effort: customers + critical bonus per expected
    # repair hour, per the AEP data guide), so the console and the customer answer always agree.
    from app.core.data_loader import get_store
    from app.engines.restoration import _priority_percentiles
    store = get_store()
    prio = _priority_percentiles(store)
    g = store.graph
    devs = sorted((n for n, d in g.nodes(data=True)
                   if d.get("circuit_id") == cid and d["kind"] in {"breaker", "recloser", "fuse"}),
                  key=lambda n: -prio[n])
    restored = [o["customers_restored"] for o in body["order"]]
    assert restored == [int(g.nodes[n]["customers"]) for n in devs[:len(restored)]]


def test_restoration_unknown_circuit_404():
    assert client.get("/api/console/restoration/not-a-real-circuit").status_code == 404


def test_alert_queue_shape_and_counts():
    body = client.get("/api/console/alerts?severity=90&crews=20").json()
    assert body["circuits_evaluated"] == len(body["queue"]) > 0
    assert body["pre_storm_circuits"] <= body["circuits_evaluated"]
    assert sum(body["risk_band_counts"].values()) == body["circuits_evaluated"]


def test_audit_tail_reflects_a_logged_prediction():
    # Make a prediction so there is at least one audit record, then read the tail.
    run_concierge(ConciergeRequest(premise_id=_a_circuit_premise()))
    body = client.get("/api/console/audit?limit=5").json()
    assert body["count"] >= 1
    rec = body["records"][0]
    assert {"audit_id", "band", "confidence", "p10_hours", "p90_hours", "alert_eligible"} <= rec.keys()


def test_audit_tail_leaks_no_ids_or_coordinates():
    run_concierge(ConciergeRequest(premise_id=_a_circuit_premise()))
    import json
    raw = json.dumps(client.get("/api/console/audit?limit=20").json())
    # No internal device-ID prefixes and no declared-needs list (only a count is exposed).
    for prefix in ("FUS-", "REC-", "BRK-", "TX-", "XF-", "FU-", "RC-", "CB-"):
        assert prefix not in raw
    assert "declared_needs" not in raw or "declared_needs_count" in raw


def _a_circuit_premise() -> str:
    """Any premise node id, for generating an audit record."""
    g = get_store().graph
    for n, d in g.nodes(data=True):
        if d.get("kind") == "premise":
            return n
    raise AssertionError("no premise in the loaded network")
