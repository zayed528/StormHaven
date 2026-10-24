"""Model checks on the REAL data (owner: Akshat). Skipped when processed data or zone features are missing.
These protect the two promises behind the served numbers: v0 serving reproduces 03 exactly, and the v1 estimator
(pipelines/_rates.py) produces sane, finite rates for every protective zone."""
import sys

import numpy as np
import pandas as pd
import pytest

from app.config import DATA_PROCESSED, ROOT

NEEDED = ["nodes.csv", "damage_attributed.csv", "device_features.csv"]
pytestmark = pytest.mark.skipif(not all((DATA_PROCESSED / f).exists() for f in NEEDED),
                                reason="processed data / zone features not built")
sys.path.insert(0, str(ROOT / "pipelines"))


@pytest.fixture(scope="module")
def data():
    from _rates import storm_exposure
    nodes = pd.read_csv(DATA_PROCESSED / "nodes.csv", dtype={"node_id": str, "circuit_id": str})
    att = pd.read_csv(DATA_PROCESSED / "damage_attributed.csv", dtype={"node_id": str})
    feat = pd.read_csv(DATA_PROCESSED / "device_features.csv", dtype={"device_id": str, "circuit_id": str})
    _, M = storm_exposure(att.groupby("event_id").size())
    return nodes, att.groupby("node_id").size(), M, feat


def test_served_fail_prob_matches_v0_when_model_is_v0(data):
    import yaml
    nodes = data[0]
    if yaml.safe_load((ROOT / "config" / "assumptions.yaml").read_text())["risk"].get("model", "v0") != "v0":
        pytest.skip("serving v1")
    if "fail_prob_v0" not in nodes:
        pytest.skip("pipelines/09 not run")
    assert float((nodes.fail_prob - nodes.fail_prob_v0).abs().max()) < 1e-12


def test_v1_rates_are_finite_positive_and_keep_the_total(data):
    from _rates import fit_rates, fit_rates_v1, zone_design
    nodes, rec, M, feat = data
    r0, _ = fit_rates(nodes, rec, M)
    r1, fit = fit_rates_v1(nodes, rec, M, zone_design(feat))
    prot = nodes.node_id[nodes.kind.isin(["fuse", "recloser", "breaker"])]
    assert np.isfinite(r1[prot]).all() and (r1[prot] > 0).all()
    assert abs(r1[prot].sum() / r0[prot].sum() - 1) < 0.25          # spreads risk, doesn't invent it
    assert set(fit["v1_coefficients"]) == set(zone_design(feat).columns)
