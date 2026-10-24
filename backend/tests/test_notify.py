"""POST /api/notify (app/notify/router.py). Run: make test  (or cd backend && pytest -q).
Works on whichever network is loaded: a premise is picked from the store, not hardcoded.

NOTE: these pass only once Jaid has added `app.include_router(notify_router)` to main.py.
Until then they skip, so they never red the build before the wiring lands.

Safety: no SNS topic is configured under test, so sns_sender dry-runs and NOTHING is ever actually texted."""
import pytest
from fastapi.testclient import TestClient

from app.core.data_loader import get_store
from app.main import app

client = TestClient(app)

# Is /api/notify wired into main.py? Enumerating app.routes is unreliable for prefixed sub-routers in this
# FastAPI version, so probe the endpoint directly: a missing route 404s, a wired one returns 200/422.
def _notify_wired() -> bool:
    return client.post("/api/notify", json={"message_key": "pre_storm"}).status_code != 404


pytestmark = pytest.mark.skipif(
    not _notify_wired(),
    reason="notify router not registered in main.py yet (add include_router(notify_router))")

ELIGIBLE = {"alerts_enrolled": True, "channels": ["sms"], "declared_needs": [], "language": "en"}
KEYS = ["pre_storm", "outage_confirmed", "estimate_updated", "restoration_complete"]


def _a_premise() -> str:
    for n, d in get_store().graph.nodes(data=True):
        if d.get("kind") == "premise":
            return n
    raise AssertionError("no premise in the loaded network")


def _post(**kw):
    return client.post("/api/notify", json=kw).json()


def test_eligible_valid_key_dry_runs():
    # No SNS topic in tests -> dry run: not sent, but a real message + audit id come back.
    r = _post(message_key="pre_storm", premise_id=_a_premise(),
              scenario={"severity_percentile": 90}, profile=ELIGIBLE)
    assert r["dry_run"] is True and r["sent"] is False
    assert r["text"] and r["audit_id"]


def test_all_four_message_keys_work():
    prem = _a_premise()
    for k in KEYS:
        r = _post(message_key=k, premise_id=prem, scenario={"severity_percentile": 90}, profile=ELIGIBLE)
        assert r["text"], f"no text for {k}"


def test_not_eligible_is_refused_not_sent():
    r = _post(message_key="pre_storm", premise_id=_a_premise(),
              profile={"alerts_enrolled": False, "channels": []})
    assert r["sent"] is False and r["dry_run"] is False
    assert r["text"] is None and "sign" in (r["reason"] or "").lower()


def test_unknown_message_key_refused():
    r = _post(message_key="bogus", premise_id=_a_premise(), profile=ELIGIBLE)
    assert r["sent"] is False and r["text"] is None and "bogus" in r["reason"]


def test_sent_text_matches_the_concierge_answer():
    # The text we would send must equal exactly what the UI shows (no drift, no second rounding rule).
    from app.schemas import ConciergeRequest, CustomerProfile
    from app.service import run_concierge
    prem = _a_premise()
    ans = run_concierge(ConciergeRequest(premise_id=prem, scenario={"severity_percentile": 90},
                                         profile=CustomerProfile(**ELIGIBLE)))
    r = _post(message_key="pre_storm", premise_id=prem,
              scenario={"severity_percentile": 90}, profile=ELIGIBLE)
    assert r["text"] == ans.alerts.messages["pre_storm"]
