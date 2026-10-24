"""Smoke tests on the REAL AEP network. Skipped automatically when data/processed/nodes.csv doesn't exist
(teammates without the data package still get a green `make test`). Engines are called with an explicitly
loaded real store, because the app-level store is forced to synthetic for the main suite (conftest.py)."""
import json
import re

import pytest

from app.config import DATA_PROCESSED

pytestmark = pytest.mark.skipif(not (DATA_PROCESSED / "nodes.csv").exists(), reason="no processed AEP data")

# Formats that must never appear in customer-facing output: internal node IDs, 9-digit premise numbers,
# 7-digit circuit codes, AEP location numbers (e.g. 37800343D00129).
LEAK = re.compile(r"\b(XF|ST|FU|RC|SC|CB)-\d+\b|\b\d{7,}\b|\b\d{5,}[A-Z]\d{3,}\b")


@pytest.fixture(scope="module")
def real():
    from app.core.data_loader import _load_processed
    store = _load_processed()
    prem = sorted(n for n, d in store.graph.nodes(data=True) if d["kind"] == "premise")
    return store, prem


def _answer(store, pid, sev):
    from app.core.privacy import scrub_response
    from app.engines.restoration import estimate_restoration
    from app.engines.risk import assess_risk
    from app.schemas import StormScenario
    sc = StormScenario(severity_percentile=sev)
    risk, pr = assess_risk(store, pid, None, sc)
    rest = estimate_restoration(store, pr, sc, risk.trust.confidence)
    return scrub_response(risk), scrub_response(rest)


def test_real_store_loaded(real):
    store, prem = real
    assert not store.is_synthetic and len(prem) > 100_000
    assert store.severity_curve and store.median_event_records


def test_every_premise_reaches_a_breaker(real):
    from app.core.topology import upline_path
    store, prem = real
    for pid in prem[::997]:                                   # sample across the network
        path = upline_path(store, pid)
        assert path and store.graph.nodes[path[0]]["kind"] == "transformer"
        assert store.graph.nodes[path[-1]]["kind"] == "breaker"


def test_severity_monotonic_and_ranges_ordered(real):
    store, prem = real
    for pid in prem[::20011]:
        lo, _ = _answer(store, pid, 50)
        hi, rest = _answer(store, pid, 99)
        assert hi.probability >= lo.probability
        assert rest.p10_hours <= rest.p50_hours <= rest.p90_hours


def test_no_internal_ids_in_real_answers(real):
    store, prem = real
    risk, rest = _answer(store, prem[0], 98)
    assert not LEAK.search(json.dumps([risk.model_dump(), rest.model_dump()]))


def test_unknown_premise_falls_back(real):
    store, _ = real
    risk, rest = _answer(store, "000000000", 80)
    assert risk.source == "fallback" and rest.source == "fallback"
