"""Storm restoration planner, crew size, and repair-work pricing (owner: Akshat).
Synthetic tests always run; real-data tests skip when the AEP data isn't built."""
import json

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.config import DATA_PROCESSED
from app.main import app
from app.schemas import ConciergeRequest, StormScenario
from app.service import run_concierge

client = TestClient(app)
CKT3 = "P-31111"
REAL = (DATA_PROCESSED / "damage_work.csv").exists() and (DATA_PROCESSED / "nodes.csv").exists()


# Bigger crews (more people) restore faster; the answer states the crew size it used (AEP guide: 2-8, stated).
def test_crew_size_is_a_stated_input_that_moves_the_range():
    small = run_concierge(ConciergeRequest(premise_id=CKT3, scenario=StormScenario(crew_size=2)))
    big = run_concierge(ConciergeRequest(premise_id=CKT3, scenario=StormScenario(crew_size=8)))
    assert big.restoration.p50_hours < small.restoration.p50_hours
    assert any("8 people" in a for a in big.restoration.trust.assumptions)


def test_crew_size_bounds_are_enforced():
    r = client.post("/api/concierge", json={"premise_id": CKT3, "scenario": {"crew_size": 12}})
    assert r.status_code == 422


# Planner needs real storms; on the synthetic network it says so instead of inventing one.
def test_planner_unavailable_on_synthetic_network():
    assert client.get("/api/planner/storms").json()["available"] is False


# ---------------------------------------------------------------- real data
real = pytest.mark.skipif(not REAL, reason="real AEP data / damage_work.csv not built")


@pytest.fixture(scope="module")
def _real_store():
    """The real AEP store, loaded once per test module (it takes ~1.5 s)."""
    from app.core import data_loader
    return data_loader._load_processed()


@pytest.fixture
def planner_real(_real_store):
    """The planner module bound to the REAL store for ONE test (the app-level store is synthetic during tests);
    restored afterwards so later synthetic tests aren't affected."""
    from app.core import data_loader
    from app.engines import planner
    real_store = _real_store
    saved = data_loader.get_store
    caches = [planner._work, planner._storm, planner.plan, planner.match_storm, planner.customer_context]
    for c in caches:
        c.cache_clear()
    planner.get_store = lambda: real_store
    yield planner
    planner.get_store = saved
    for c in caches:
        c.cache_clear()


@real
def test_repair_work_follows_the_data_guide():
    w = pd.read_csv(DATA_PROCESSED / "damage_work.csv")
    mult = json.loads((DATA_PROCESSED / "multipliers.json").read_text())["indirect_labor_multiplier"]
    # person-hours = (direct + access adder) x indirect multiplier, for every record
    assert ((w.direct_hours + w.access_hours) * mult - w.person_hours).abs().max() < 0.01
    poles = w[w.damage_type == "broken_pole"]
    three = poles[poles.work.str.contains("3-phase")].direct_hours.mean()
    one = poles[poles.work.str.contains("1-phase")].direct_hours.mean()
    assert three > one > 0                       # three-phase framing (crossarm, 3 pins/insulators) costs more


@real
def test_plan_is_consistent_and_crews_help(planner_real):
    storm = planner_real.storms()[0]["storm_id"]
    slow = planner_real.plan(storm, 20, 3)
    fast = planner_real.plan(storm, 60, 3)
    assert slow["available"] and slow["source"] == "model_estimate"
    h = slow["hours_to_restore"]
    assert h["half"] <= h["ninety_pct"] <= h["all"]
    assert fast["hours_to_restore"]["all"] < slow["hours_to_restore"]["all"]
    pcts = [p["pct_restored"] for p in slow["restore_curve"]]
    assert pcts == sorted(pcts) and pcts[-1] == 100.0
    # Crews needed for a shorter target is never smaller, and meeting it is checked by the same engine
    need = [t["crews_needed"] for t in slow["targets"] if t["crews_needed"]]
    assert need == sorted(need, reverse=True)
    json.dumps(slow)                             # API-serialisable (no numpy types)


@real
def test_plan_reveals_no_ids(planner_real):
    import re
    p = planner_real.plan(planner_real.storms()[0]["storm_id"], 20, 3)
    assert not re.search(r"\b(XF|FU|RC|CB|ST|SC)-\d+|\b\d{9}\b", json.dumps(p))


# The on-screen range and every SMS use one rounding rule, so they always show the same numbers.
def test_screen_range_matches_sms_range():
    import re
    from app.schemas import CustomerProfile
    prof = CustomerProfile(alerts_enrolled=True, channels=["sms"])
    for sc in [StormScenario(), StormScenario(severity_percentile=95, crews_available=3, road_access="blocked")]:
        r = run_concierge(ConciergeRequest(premise_id=CKT3, scenario=sc, profile=prof))
        screen = re.findall(r"\d+", r.restoration.range_text.split("(")[0])
        sms = re.findall(r"\d+", r.restoration.range_short)
        assert screen == sms and r.restoration.range_short in r.alerts.messages["pre_storm"]


@real
def test_customer_range_agrees_with_storm_replay(planner_real):
    """The customer's P50 for homes that lost power in the biggest storm is close to the replay's 50%-restored time
    (the customer engine's queue curve is calibrated on the replay)."""
    import numpy as np
    from app.engines import restoration
    from app.engines.risk import assess_risk
    store = planner_real.get_store()
    restoration._QUEUE_CACHE.clear(); restoration._PRIORITY_CACHE.clear()
    storm = planner_real.storms()[0]["storm_id"]
    curve = planner_real.plan(storm, 20, 3)["restore_curve"]
    half = next(c["hour"] for c in curve if c["pct_restored"] >= 50)
    meta = json.loads((DATA_PROCESSED / "meta.json").read_text())
    sizes = pd.Series(meta["event_sizes"])
    sev = float((sizes.rank()[storm] - 0.5) / len(sizes) * 100)
    labels = pd.read_csv(DATA_PROCESSED / "premise_event_labels.csv", dtype=str)
    homes = labels[labels.event_id == storm].premise_id.sample(150, random_state=3)
    p50 = []
    for pid in homes:
        sc = StormScenario(severity_percentile=sev, crews_available=20)
        risk, pr = assess_risk(store, pid, None, sc)
        p50.append(restoration.estimate_restoration(store, pr, sc, risk.trust.confidence).p50_hours)
    restoration._QUEUE_CACHE.clear(); restoration._PRIORITY_CACHE.clear()
    assert 0.6 * half <= float(np.median(p50)) <= 1.4 * half


def test_storm_context_absent_on_synthetic_network():
    from app.core.data_loader import get_store
    from app.engines.restoration import storm_context
    assert storm_context(get_store(), StormScenario(severity_percentile=99)) is None


@real
def test_storm_context_sentence_moves_with_crews(planner_real):
    from app.engines.restoration import storm_context
    store = planner_real.get_store()
    planner_real.customer_context.cache_clear()
    few = storm_context(store, StormScenario(severity_percentile=99, crews_available=20))
    many = storm_context(store, StormScenario(severity_percentile=99, crews_available=60))
    mild = storm_context(store, StormScenario(severity_percentile=50))
    planner_real.customer_context.cache_clear()
    assert few and many and few != many and "9 in 10" in few and "replay" in few
    assert mild is None


# ---------------------------------------------------------------- one source of truth for "which storm is this like?"
def test_replay_storm_none_on_synthetic_network():
    from app.core.data_loader import get_store
    from app.engines.restoration import replay_storm_id
    assert replay_storm_id(get_store(), StormScenario(severity_percentile=99)) is None
    assert client.get("/api/planner/match", params={"severity": 99}).json() == {"storm_id": None, "label": None}
    r = run_concierge(ConciergeRequest(premise_id=CKT3, scenario=StormScenario(severity_percentile=99)))
    assert getattr(r.restoration, "replay_storm_id", None) is None


@real
def test_replay_storm_id_matches_storm_list_sentence_and_match_endpoint(planner_real):
    from app.engines.restoration import replay_storm_id, storm_context
    store = planner_real.get_store()
    known = {s["storm_id"]: s["label"] for s in planner_real.storms()}
    for sev in (97, 99):
        sc = StormScenario(severity_percentile=sev)
        sid = replay_storm_id(store, sc)
        assert sid in known                                         # same ids as /api/planner/storms
        assert known[sid] in storm_context(store, sc)               # the sentence is about the same storm
        m = client.get("/api/planner/match", params={"severity": sev}).json()
        assert m == {"storm_id": sid, "label": known[sid]}          # banner/console match == customer answer
    assert replay_storm_id(store, StormScenario(severity_percentile=50)) is None
    assert client.get("/api/planner/match", params={"severity": 50}).json() == {"storm_id": None, "label": None}
    assert replay_storm_id(store, StormScenario(severity_percentile=99)) != replay_storm_id(
        store, StormScenario(severity_percentile=97))              # Record (Feb 2025) vs Severe (Sep 2024)


def test_match_endpoint_validates_severity():
    assert client.get("/api/planner/match", params={"severity": 150}).status_code == 422


@pytest.mark.filterwarnings("ignore::DeprecationWarning")      # reloading main re-runs its startup-hook setup
def test_match_endpoint_is_on_even_without_operator_routes(monkeypatch):
    """The banner needs /api/planner/match on the public server, where operator routes are switched off."""
    import importlib
    import app.main as main
    monkeypatch.delenv("STORMHAVEN_ENABLE_OPERATOR_ROUTES", raising=False)
    fresh = importlib.reload(main)
    try:
        c = TestClient(fresh.app)
        assert c.get("/api/planner/match", params={"severity": 99}).status_code == 200
        assert c.get("/api/planner/storms").status_code == 404          # the full planner stays operator-only
    finally:
        monkeypatch.setenv("STORMHAVEN_ENABLE_OPERATOR_ROUTES", "true")
        importlib.reload(main)
