"""
ENGINE 1 — "Will I lose power?"   Owner: Akshat

v0 (this file): topology-based probability, fully explainable.
  Each device i on the premise's upline path has a historical per-storm
  failure probability p_i (from ARCOS: share of past events with damage there).
  A storm of severity s scales it:  p_i' = 1 - (1 - p_i) ** m(s)
  Premise is out if ANY upline device fails:  P = 1 - prod(1 - p_i')

v1 (hook below): replace/blend with a calibrated ML model trained on
pipelines/03_build_labels.py output. Keep the same response shape.
"""
from __future__ import annotations
import math
from dataclasses import dataclass

import numpy as np

from app.config import ASSUMPTIONS
from app.core.data_loader import DataStore
from app.core.privacy import another_name, friendly_name
from app.core.topology import resolve_location, upline_path
from app.schemas import Factor, RiskResponse, StormScenario, TrustInfo

CFG = ASSUMPTIONS["risk"]


@dataclass
class PathRisk:
    """Internal (never sent to customer). Restoration engine reuses it."""
    level: str                 # "premise" | "circuit" | "none" (how precisely we matched the location)
    premise: str | None        # the premise actually used (a representative one for circuit-level matches)
    path: list[str]            # nearest first
    p_adj: np.ndarray          # storm-adjusted failure prob per path device
    probability: float         # P(at least one device on the path fails) = P(you lose power)


def severity_multiplier(pct: float, store: DataStore | None = None, for_risk: bool = True) -> float:
    """How many 'typical storms' this storm is worth: 1.0 for a median storm, >1 worse, <1 milder.
    Real data: read off the storm-size curve from ARCOS history (meta.json), interpolated in log space and
    held flat beyond the largest/smallest storm we've seen. For outage PROBABILITY (for_risk=True) it is damped
    by severity_damping (damage clusters, so fewer distinct customers go out than damage counts suggest);
    restoration WORKLOAD (for_risk=False) uses the undamped size. Synthetic: m(s) = exp(k*(s-50)/50)."""
    if store is not None and store.severity_curve:
        xs, ms = zip(*store.severity_curve)
        m = float(np.exp(np.interp(pct, xs, np.log(ms))))
        return m ** CFG["severity_damping"] if for_risk else m
    return math.exp(CFG["severity_k"] * (pct - 50) / 50)


def _base_prob(node: dict) -> float:
    """Per-typical-storm failure prob for a device; the config prior only if the value is missing/NaN.
    (A plain `or` would wrongly replace a legitimate 0.0 with the prior.)"""
    fp = node.get("fail_prob")
    return CFG["prior_failure_prob"] if fp is None or fp != fp else float(fp)


def _pct_text(p: float) -> str:
    """Probability -> plain-language percent that never says '0%' for a small but real risk."""
    if p < 0.01:
        return "less than 1%"
    return f"about {round(p * 100)}%"


def band_for(p: float) -> str:
    """Probability -> customer-facing band (Low/Moderate/High/Very High), cut-offs from assumptions.yaml."""
    for b in CFG["bands"]:
        if p < b["max"]:
            return b["name"]
    return CFG["bands"][-1]["name"]


def compute_path_risk(store: DataStore, premise_id, circuit_id, scenario: StormScenario) -> PathRisk:
    """The core math, no text. Also used by map_layers.py to color every premise on the map."""
    level, node = resolve_location(store, premise_id, circuit_id)
    if level == "none":
        return PathRisk("none", None, [], np.array([]), float("nan"))
    path = upline_path(store, node)
    g = store.graph
    # Historical per-storm failure prob for each device; devices with no history get the prior.
    base = np.array([_base_prob(g.nodes[n]) for n in path])
    m = severity_multiplier(scenario.severity_percentile, store)
    # Raising the survival prob (1-p) to the power m is like facing m "typical storms" at once.
    # Clip at 0.999 so a device with p=1 can't make the log in _factors blow up.
    p_adj = 1 - (1 - np.clip(base, 0, 0.999)) ** m
    # Power is lost if ANY upstream device fails (devices assumed independent).
    prob = float(1 - np.prod(1 - p_adj))
    # TODO v1: if models/risk_model.joblib exists -> prob = calibrated_model.predict_proba(features)[0,1]
    return PathRisk(level, node, path, p_adj, prob)


def _confidence(store: DataStore, pr: PathRisk, scenario: StormScenario) -> tuple[str, list[str]]:
    """Confidence = how much history backs this answer, downgraded one level for each extra caveat.
    Also returns the plain-language 'missing data' list shown to the customer."""
    g = store.graph
    # Start from the median number of past storms observed for the devices on this path.
    obs = [g.nodes[n].get("n_events_observed", 0) for n in pr.path]
    med = float(np.median(obs)) if obs else 0
    cc = CFG["confidence"]
    level = "High" if med >= cc["high_min_events"] else "Medium" if med >= cc["medium_min_events"] else "Low"
    missing = []
    # Each block below adds a disclosure and (for the first two) knocks confidence down one level.
    if med < cc["medium_min_events"]:
        missing.append("Little storm history for the equipment that serves you.")
    if scenario.severity_percentile > 95 or scenario.severity_percentile < 5:
        extreme = "severe" if scenario.severity_percentile > 95 else "mild"
        missing.append(f"Only a few past storms were this {extreme}, so this estimate rests on very little history.")
        level = {"High": "Medium", "Medium": "Low", "Low": "Low"}[level]
    if pr.level == "circuit":
        missing.append("We matched your area, not your exact address.")
        level = {"High": "Medium", "Medium": "Low", "Low": "Low"}[level]
    if store.is_synthetic:
        missing.append("Demo network: synthetic data.")
    return level, missing


def _factors(store: DataStore, pr: PathRisk, scenario: StormScenario) -> list[Factor]:
    """Top contributing factors in plain language: the 2 riskiest devices, storm strength, path length."""
    g = store.graph
    # -log(1-p) turns "probability of no failure" products into sums, so each device's hazard is its
    # additive share of the total risk. weight = that share (0-1).
    hazard = -np.log(1 - pr.p_adj)                 # additive contributions
    total = hazard.sum() or 1.0
    factors: list[Factor] = []
    named: set[str] = set()
    for i in np.argsort(-hazard)[:2]:              # two largest contributors; friendly names only, never IDs
        n = pr.path[i]
        k = g.nodes[n]["kind"]
        who = another_name(k) if k in named else friendly_name(k)   # don't repeat the same sentence twice
        named.add(k)
        # Storm-adjusted chance for THIS scenario, learned from how often this equipment was damaged before.
        factors.append(Factor(
            name=f"history:{g.nodes[n]['kind']}", direction="raises", weight=round(float(hazard[i] / total), 2),
            plain_language=f"Based on past storms, the chance that {who} is "
                           f"damaged in a storm like this one is {_pct_text(float(pr.p_adj[i]))}."))
    # Storm strength: weight grows with distance from a median storm.
    sev = scenario.severity_percentile
    factors.append(Factor(
        name="storm_severity", direction="raises" if sev >= 50 else "lowers",
        weight=round(min(1.0, abs(sev - 50) / 50), 2),
        plain_language=("This storm is forecast to be stronger than a typical storm."
                        if sev >= 50 else "This storm is forecast to be milder than a typical storm.")))
    # Exposure: more equipment between you and the substation = more places to fail (8+ devices = max weight).
    factors.append(Factor(
        name="path_exposure", direction="raises" if len(pr.path) >= 4 else "lowers",
        weight=round(min(1.0, len(pr.path) / 8), 2),
        plain_language=f"Your power passes through {len(pr.path)} pieces of equipment; "
                       "each is a place a storm can cause damage."))
    return factors


def assess_risk(store: DataStore, premise_id, circuit_id, scenario: StormScenario) -> tuple[RiskResponse, PathRisk]:
    """Public entry point (called by service.py). Returns the customer-facing RiskResponse plus the
    internal PathRisk, which the restoration engine needs and which never leaves the backend."""
    pr = compute_path_risk(store, premise_id, circuit_id, scenario)

    if pr.level == "none":   # ---------- FALLBACK: never guess silently
        return RiskResponse(
            source="fallback", probability=0.0, band="Unknown", factors=[], resolved_level="none",
            trust=TrustInfo(confidence="Low",
                            missing_data=["We couldn't match this location to our network data."],
                            assumptions=["No prediction made."],
                            could_change_if=["You enter your premise ID or select your area on the map."]),
        ), pr

    conf, missing = _confidence(store, pr, scenario)
    # Every answer carries its trust info: confidence, assumptions, missing data, what could change it.
    resp = RiskResponse(
        probability=round(pr.probability, 3), band=band_for(pr.probability),
        factors=_factors(store, pr, scenario), resolved_level=pr.level,
        trust=TrustInfo(
            confidence=conf, missing_data=missing,
            assumptions=["Storm strength is a scenario input, not a live forecast.",
                         "Equipment damage rates come from past storms in this area."],
            could_change_if=["The storm track or strength changes.",
                             "Crews pre-position or reconfigure the network before the storm."]),
    )
    return resp, pr
