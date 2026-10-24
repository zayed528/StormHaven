"""
Utility operator console: READ-ONLY situational awareness for AEP staff.   Owner: Abby (was Jaid)

This is the internal view, not the customer view. Operators legitimately need circuit IDs and equipment
kinds, so those appear here; but it stays read-only and never exposes premise-level locations, customer
contact details, or critical-facility identities (only an anonymous count of critical zones affected).

Endpoints (all GET, no side effects):
  GET /api/console/circuits                        circuits with a damage-history summary, for the picker
  GET /api/console/restoration/{circuit_id}        likely restoration order for one circuit (upstream-first)
  GET /api/console/alerts?severity=&crews=         alert queue + active escalations under a storm scenario
  GET /api/console/audit?limit=                    tail of the prediction audit log (scrubbed)

Wired into main.py with app.include_router(console_router).
"""
from __future__ import annotations

import json
from collections import Counter
from functools import lru_cache

import numpy as np

from fastapi import APIRouter, HTTPException

from app.config import LOG_DIR
from app.core.data_loader import get_store
from app.core.privacy import SHORT, scrub_text
from app.core.topology import premises_on_circuit, resolve_location, upline_path
from app.engines.alerts import BAND_RANK, CFG as ALERT_CFG, build_alerts
from app.engines.restoration import _priority_percentiles, estimate_restoration
from app.engines.risk import assess_risk, band_for, severity_multiplier
from app.map_layers import _points
from app.schemas import AccessLevel, CustomerProfile, StormScenario

router = APIRouter(prefix="/api/console", tags=["console"])


@lru_cache(maxsize=None)
def _typical_home(circuit_id: str) -> str | None:
    """Median-depth premise on a circuit (topology only, so it never changes): cached, because finding it
    walks every premise's path and the alert queue needs one per circuit on every slider move."""
    return resolve_location(get_store(), None, circuit_id)[1]


@router.get("/circuits")
def circuits():
    """Every circuit in the network with how much storm history it carries, for the circuit picker.
    n_events_observed = storms that damaged this circuit (0 = no recorded history)."""
    store = get_store()
    g = store.graph
    rows: dict[str, dict] = {}
    for n, d in g.nodes(data=True):
        cid = d.get("circuit_id")
        if not cid or cid == "ALL":
            continue
        r = rows.setdefault(cid, {"circuit_id": cid, "customers": 0, "devices": 0,
                                  "critical_zones": 0, "n_events_observed": 0})
        if d["kind"] == "premise":
            r["customers"] += 1
        else:
            r["devices"] += 1
            r["n_events_observed"] = max(r["n_events_observed"], int(d.get("n_events_observed", 0)))
            if d.get("critical"):
                r["critical_zones"] += 1
    out = sorted(rows.values(), key=lambda r: (-r["customers"], r["circuit_id"]))
    return {"count": len(out), "circuits": out}


@router.get("/restoration/{circuit_id}")
def restoration_order(circuit_id: str, severity: float = 70, crews: int = 20, limit: int = 15):
    """Likely restoration order for a circuit: its protective devices ranked highest-priority-first
    (main-line devices that bring back the most customers come first), with a model ETA for a
    representative premise. Model estimate only — never a confirmed restoration time.
    Only the first `limit` devices are listed (big circuits have hundreds of fuses); total_devices says how many."""
    limit = max(1, min(limit, 100))
    store = get_store()
    if not premises_on_circuit(store, circuit_id):
        raise HTTPException(status_code=404, detail="Unknown circuit.")
    g = store.graph
    sc = StormScenario(severity_percentile=severity, crews_available=crews)
    # Representative premise + its restoration run (reuses the same engine the customer answer uses).
    risk, pr = assess_risk(store, None, circuit_id, sc)
    rest = estimate_restoration(store, pr, sc, risk.trust.confidence)

    prio = _priority_percentiles(store)
    # Rank every protective device on this circuit by restoration priority (1.0 = first).
    devs = [(n, d) for n, d in g.nodes(data=True)
            if d.get("circuit_id") == circuit_id and d["kind"] in {"breaker", "recloser", "fuse"}]
    ranked = sorted(devs, key=lambda nd: prio.get(nd[0], 0.0), reverse=True)
    order = [{
        "rank": i + 1,
        # Operator label ("Fuse", "Automatic switch"), not the customer phrasing ("the fuse protecting your street").
        "equipment": SHORT.get(d["kind"], d["kind"]).capitalize(),   # never the raw device ID
        "kind": d["kind"],
        "customers_restored": int(d.get("customers", 0)),
        "feeds_critical": bool(d.get("critical_downstream", False)),
    } for i, (n, d) in enumerate(ranked[:limit])]
    return {
        "circuit_id": circuit_id,
        "source": "model_estimate",
        "representative_range": rest.range_text,
        "p10_hours": rest.p10_hours,
        "p50_hours": rest.p50_hours,
        "p90_hours": rest.p90_hours,
        "total_devices": len(ranked),
        "order": order,
    }


@router.get("/alerts")
def alert_queue(severity: float = 70, crews: int = 20, road_access: AccessLevel = AccessLevel.normal):
    """Alert queue + active escalations under a storm scenario, aggregated across circuits.
    A what-if overview of who would be alerted, not a record of real sends (those are logged by /api/notify).

    Risk comes from EVERY neighborhood (transformer) on the circuit, with the same numbers the customer map
    uses, so the console and the map always agree. A circuit's band = its riskiest neighborhood, and it is
    in the pre-storm queue if any neighborhood reaches the alert threshold (alerts.eligibility.min_risk_band).
    Escalations are checked for a typical home on each circuit: confidence as that home would see it, and
    'medical need' = what WOULD trigger if a customer there had declared one (we never assume who has)."""
    store = get_store()
    g = store.graph
    sc = StormScenario(severity_percentile=severity, crews_available=crews, road_access=road_access)
    threshold = BAND_RANK[ALERT_CFG["eligibility"]["min_risk_band"]]

    # 1) Neighborhood risk at this severity: P(out) = 1 - exp(-m * H), exactly as map_layers computes it.
    pts, hazard = _points()
    p_out = 1 - np.exp(-severity_multiplier(severity, store) * hazard)
    worst: dict[str, str] = {}                       # circuit -> riskiest neighborhood band
    homes_by_band: Counter = Counter()
    homes_pre_storm = 0
    for pt, p in zip(pts, p_out):
        band = band_for(float(p))
        homes_by_band[band] += pt["n"]
        homes_pre_storm += pt["n"] if BAND_RANK[band] >= threshold else 0
        cid = pt["circuit_id"]
        if cid not in worst or BAND_RANK[band] > BAND_RANK[worst[cid]]:
            worst[cid] = band

    # 2) Escalations for a typical home per circuit (premise-level, so confidence isn't marked down for
    #    "we only matched your area"), with a medical need declared hypothetically.
    medical = CustomerProfile(alerts_enrolled=True, channels=["sms"], declared_needs=["medical_device"])
    active_escalations: Counter = Counter()
    rows = []
    circuits = sorted({d.get("circuit_id") for _, d in g.nodes(data=True)
                       if d.get("circuit_id") and d.get("circuit_id") != "ALL"})
    for cid in circuits:
        home = _typical_home(cid)
        risk, pr = assess_risk(store, home, None, sc)
        rest = estimate_restoration(store, pr, sc, risk.trust.confidence)
        alerts = build_alerts(risk, rest, medical, previous_range_text=None)
        on = [e for e in alerts.escalations if e.active]
        for e in on:
            active_escalations[scrub_text(e.trigger)] += 1
        band = worst.get(cid, risk.band)
        rows.append({"circuit_id": cid, "band": band,
                     "pre_storm_alert": BAND_RANK.get(band, 1) >= threshold,
                     "typical_p50_hours": rest.p50_hours,
                     "active_escalations": len(on)})
    rows.sort(key=lambda r: (not r["pre_storm_alert"], -BAND_RANK.get(r["band"], 1), r["circuit_id"]))
    return {
        "scenario": {"severity_percentile": severity, "crews_available": crews,
                     "road_access": road_access.value},
        "circuits_evaluated": len(circuits),
        "pre_storm_circuits": sum(r["pre_storm_alert"] for r in rows),
        "pre_storm_threshold": ALERT_CFG["eligibility"]["min_risk_band"],
        "risk_band_counts": dict(Counter(r["band"] for r in rows)),   # circuits by their riskiest neighborhood
        "homes_by_band": dict(homes_by_band),
        "homes_total": sum(homes_by_band.values()),
        "homes_pre_storm": homes_pre_storm,
        "active_escalations": [{"trigger": t, "circuits": c} for t, c in active_escalations.most_common()],
        "queue": rows,
    }


@router.get("/audit")
def audit_tail(limit: int = 20):
    """Last N prediction records from logs/audit.jsonl (newest first). Every string is scrubbed, so no
    coordinates, device IDs or contacts leak even though this is the internal view. Declared needs are
    summarized to a count rather than listed, so the tail can't profile an individual."""
    limit = max(1, min(limit, 200))
    path = LOG_DIR / "audit.jsonl"
    if not path.exists():
        return {"count": 0, "records": []}
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()[-limit:]
    records = []
    for line in reversed(lines):                       # newest first
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        req = rec.get("request", {}) or {}
        resp = rec.get("response", {}) or {}
        profile = req.get("profile", {}) or {}
        scenario = req.get("scenario", {}) or {}
        records.append({
            "audit_id": rec.get("audit_id"),
            "ts": rec.get("ts"),
            "model_version": rec.get("model_version"),
            "resolved_to": "premise" if req.get("premise_id") else "circuit" if req.get("circuit_id") else "none",
            "severity_percentile": scenario.get("severity_percentile"),
            "crews_available": scenario.get("crews_available"),
            "declared_needs_count": len(profile.get("declared_needs", []) or []),
            "band": resp.get("band"),
            "confidence": resp.get("confidence"),
            "p10_hours": resp.get("p10"),
            "p90_hours": resp.get("p90"),
            "alert_eligible": resp.get("eligible"),
        })
    return {"count": len(records), "records": records}
