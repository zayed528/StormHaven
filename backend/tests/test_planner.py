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
def planner_real():
    """The planner module bound to the REAL store (the app-level store is synthetic during tests)."""
    from app.core import data_loader
    from app.engines import planner
    real_store = data_loader._load_processed()
    saved = data_loader.get_store
    planner._work.cache_clear(); planner._storm.cache_clear(); planner.plan.cache_clear()
    planner.get_store = lambda: real_store
    yield planner
    planner.get_store = saved
    planner._work.cache_clear(); planner._storm.cache_clear(); planner.plan.cache_clear()


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
