"""
ENGINE 5 — Storm restoration planner (utility view).   Owner: Akshat
Answers the AEP data guide's four questions for a whole storm, by REPLAYING a real ARCOS storm:
  1. What is damaged?           every damaged device in that storm (pipelines/03 attribution)
  2. Which customers depend?    premises downstream of each damaged device (matched_upstream topology)
  3. What work fixes it?        person-hours per record (pipelines/04: pole size, phases, structure drawings,
                                AEP CU hours x 4.5 indirect multiplier, access adder where ARCOS flags access issues)
  4. What first, how long?      crews dispatched by VALUE / EFFORT, step restoration, crews needed for 2 d / 3 d / 1 wk

Step restoration: a customer is back as soon as every damaged device on THEIR path is repaired, not when the
whole circuit is done. Each free crew takes the job with the highest value per crew-hour, where
  value = customers that come back the moment it's finished (+ a bonus if it feeds a hospital/fire/EMS)
and a job behind an unrepaired upstream device is worth nothing yet (fix upstream first).
One crew per job; travel/setup are inside the 4.5 multiplier. Deterministic run for the plan + Monte Carlo
on job durations (lognormal, restoration.labor_noise_sigma) for the ranges.
"""
from __future__ import annotations
import heapq
import json
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
import pandas as pd

from app.config import ASSUMPTIONS, DATA_PROCESSED
from app.core.data_loader import DataStore, get_store
from app.core.privacy import SHORT

CFG = ASSUMPTIONS["restoration"]
PCFG = ASSUMPTIONS["planner"]


@dataclass
class _Storm:
    """One storm's repair work, prepared once (topology only; no scenario applied).
    Devices = damaged equipment; jobs = individual damage records (a zone hit 40 times is 40 jobs that several
    crews can work at once). A device is repaired when all its jobs are done."""
    devices: list[str]                 # damaged node ids
    kinds: list[str]
    owned: np.ndarray                  # customers whose LOWEST damaged device is this one
    downstream: np.ndarray             # owned + everything behind further damaged devices (tie-breaker)
    critical: np.ndarray               # device feeds a critical facility
    blockers: list[list[int]]          # damaged devices upstream of each device
    below: list[list[int]]             # damaged devices that list this device as a blocker
    job_device: np.ndarray             # device index per job
    job_person_hours: np.ndarray       # per job, at normal access, workload 1
    customers_out: int


@lru_cache(maxsize=1)
def _work() -> pd.DataFrame | None:
    path = DATA_PROCESSED / "damage_work.csv"
    if get_store().is_synthetic or not path.exists():
        return None
    return pd.read_csv(path, dtype={"node_id": str, "event_id": str})


@lru_cache(maxsize=1)
def _events() -> dict:
    meta = DATA_PROCESSED / "meta.json"
    return json.loads(meta.read_text()).get("events", {}) if meta.exists() else {}


def available() -> bool:
    return _work() is not None


def storms() -> list[dict]:
    """Storms big enough to plan for, largest first (labels use the month; no IDs of equipment or customers)."""
    w = _work()
    if w is None:
        return []
    ev = _events()
    out = []
    for e, g in w.groupby("event_id"):
        if len(g) < PCFG["min_records"]:
            continue
        start = ev.get(e, {}).get("start", "")
        label = pd.Timestamp(start).strftime("%b %Y") if start else e
        out.append({"storm_id": e, "label": f"{label} storm", "start": start, "end": ev.get(e, {}).get("end", ""),
                    "damage_records": int(len(g)), "damaged_devices": int(g.node_id.nunique()),
                    "person_hours": round(float(g.person_hours.sum()))})
    return sorted(out, key=lambda s: -s["damage_records"])


@lru_cache(maxsize=16)
def _storm(storm_id: str) -> _Storm | None:
    w = _work()
    if w is None or storm_id not in set(w.event_id):
        return None
    g = get_store().graph
    recs = w[w.event_id == storm_id]
    devices = sorted(set(recs.node_id))
    damaged, idx = set(devices), {n: i for i, n in enumerate(devices)}
    blockers = []
    for n in devices:                                     # damaged devices upstream (walk parents)
        ups, cur = [], next(iter(g.predecessors(n)), None)
        while cur is not None:
            if cur in damaged:
                ups.append(idx[cur])
            cur = next(iter(g.predecessors(cur)), None)
        blockers.append(ups)
    below = [[] for _ in devices]
    for j, bl in enumerate(blockers):
        for i in bl:
            below[i].append(j)
    owned = np.zeros(len(devices), dtype=int)             # walk down, stopping at the next damaged device
    for i, n in enumerate(devices):
        stack = list(g.successors(n))
        while stack:
            c = stack.pop()
            if c in damaged:
                continue
            if g.nodes[c]["kind"] == "premise":
                owned[i] += 1
            else:
                stack.extend(g.successors(c))
    downstream = np.array([owned[i] + sum(owned[j] for j in below[i]) for i in range(len(devices))])
    return _Storm(devices=devices, kinds=[g.nodes[n]["kind"] for n in devices], owned=owned, downstream=downstream,
                  critical=np.array([bool(g.nodes[n].get("critical_downstream")) for n in devices]),
                  blockers=blockers, below=below, job_device=recs.node_id.map(idx).to_numpy(),
                  job_person_hours=recs.person_hours.to_numpy(float), customers_out=int(owned.sum()))


def _simulate(st: _Storm, job_hours: np.ndarray, crews: int, start_h: float, record: bool = False):
    """Value-per-crew-hour dispatch over individual jobs. Returns (last finish, restore curve, device order).
    Each free crew picks the DEVICE with the best (customers back on completion + critical bonus) per remaining
    crew-hour, then takes that device's longest unassigned job. A device behind an unstarted upstream device is
    worth nothing yet. Scores are cached and only recomputed for devices an event can affect."""
    D = len(st.devices)
    bonus = CFG["critical_facility_priority_bonus"]
    queues = [[] for _ in range(D)]                       # unassigned jobs per device, longest first
    for j in np.argsort(-job_hours, kind="stable"):
        queues[st.job_device[j]].append(int(j))
    rem_hours = np.zeros(D)
    np.add.at(rem_hours, st.job_device, job_hours)
    jobs_left = np.bincount(st.job_device, minlength=D)    # jobs not yet finished per device
    started = np.zeros(D, dtype=bool)
    done = np.zeros(D, dtype=bool)
    released = np.zeros(D, dtype=bool)
    undone_up = np.array([len(b) for b in st.blockers])
    score = np.full(D, -np.inf)

    def rescore(d: int):
        if not queues[d]:
            score[d] = -np.inf
            return
        if any(not started[b] for b in st.blockers[d]):
            v = 0.0
        else:
            v = st.owned[d] + sum(st.owned[j] for j in st.below[d] if done[j] and not released[j])
            v += bonus if st.critical[d] else 0
        score[d] = (v + 1e-6 * st.downstream[d]) / max(rem_hours[d], 1e-9)

    for d in range(D):
        rescore(d)
    free = [start_h] * crews
    heapq.heapify(free)
    running: list[tuple[float, int]] = []                 # (finish, job)
    restored, curve, order, last = 0, [(start_h, 0)], [], start_h
    while running or score.max() > -np.inf:
        while free and score.max() > -np.inf and (not running or free[0] <= running[0][0]):
            t = heapq.heappop(free)
            d = int(np.argmax(score))
            j = queues[d].pop(0)
            rem_hours[d] -= job_hours[j]
            if not started[d]:
                started[d] = True
                if record:
                    order.append((d, t))
                for k in st.below[d]:
                    rescore(k)
            rescore(d)
            heapq.heappush(running, (t + job_hours[j], j))
        t, j = heapq.heappop(running)
        last = t
        heapq.heappush(free, t)
        d = int(st.job_device[j])
        jobs_left[d] -= 1
        if jobs_left[d]:
            continue
        done[d] = True                                    # device repaired
        for k in st.below[d]:
            undone_up[k] -= 1
        stack = [d] + list(st.below[d])
        while stack:                                      # release customers whose whole path is now clear
            k = stack.pop()
            if done[k] and not released[k] and undone_up[k] == 0:
                released[k] = True
                restored += st.owned[k]
                stack.extend(st.below[k])
        for b in st.blockers[d]:
            rescore(b)
        if record:
            curve.append((t, restored))
    return float(last), curve, order


def _hours(st: _Storm, crew_size: int, road_access: str, workload: float) -> np.ndarray:
    """Crew clock-hours per job = person-hours x road access x workload / people per crew."""
    return st.job_person_hours * CFG["access_multipliers"][road_access] * workload / crew_size


def _crews_needed(st: _Storm, hours: np.ndarray, target_h: float, start_h: float) -> int | None:
    """Fewest crews that restore everyone within target_h (search on the deterministic plan)."""
    if start_h + hours.max() > target_h:
        return None                                       # the single longest job can't fit
    lo = max(1, int(np.ceil(hours.sum() / max(target_h - start_h, 1e-9))))
    hi = lo
    while _simulate(st, hours, hi, start_h)[0] > target_h:
        lo, hi = hi + 1, hi * 2
        if hi > PCFG["max_crews"]:
            return None
    while lo < hi:
        mid = (lo + hi) // 2
        if _simulate(st, hours, mid, start_h)[0] <= target_h:
            hi = mid
        else:
            lo = mid + 1
    return lo


def _time_to(curve, share: float, total: int) -> float | None:
    goal = share * total
    for t, r in curve:
        if r >= goal - 1e-9:
            return round(float(t), 1)
    return None


@lru_cache(maxsize=64)
def plan(storm_id: str, crews: int, crew_size: int, road_access: str = "normal", workload: float = 1.0) -> dict:
    """The whole storm plan for one scenario. Model estimate: every number is a planning range, not a promise."""
    st = _storm(storm_id)
    if st is None:
        return {"available": False, "reason": "Storm not found or real data not built."}
    start_h = CFG["assessment_hours"]
    hrs = _hours(st, crew_size, road_access, workload)
    scale = CFG["access_multipliers"][road_access] * workload            # person-hours under this scenario
    end, curve, order = _simulate(st, hrs, crews, start_h, record=True)
    dev_person_hours = np.bincount(st.job_device, weights=st.job_person_hours, minlength=len(st.devices)) * scale
    total = st.customers_out

    # Ranges: re-run with lognormal job-duration noise (same seed every time -> reproducible)
    rng = np.random.default_rng(PCFG["seed"])
    ends, t90 = [], []
    for _ in range(PCFG["n_simulations"]):
        e, c, _ = _simulate(st, hrs * rng.lognormal(0, CFG["labor_noise_sigma"], len(hrs)), crews, start_h, record=True)
        ends.append(e)
        t90.append(_time_to(c, 0.9, total) or round(e, 1))
    pct = lambda x: [round(float(v), 1) for v in np.percentile(x, [10, 50, 90])]      # noqa: E731

    targets = []
    for days in PCFG["target_days"]:
        need = _crews_needed(st, hrs, days * 24, start_h)
        targets.append({"days": days, "crews_needed": need,
                        "people_needed": need * crew_size if need else None,
                        "met_with_current_crews": bool(end <= days * 24)})

    first = []
    for d, t0 in order[:PCFG["top_jobs"]]:
        first.append({"order": len(first) + 1, "equipment": SHORT.get(st.kinds[d], st.kinds[d]).capitalize(),
                      "customers_behind_it": int(st.owned[d]), "feeds_critical_facility": bool(st.critical[d]),
                      "repair_jobs": int((st.job_device == d).sum()),
                      "person_hours": round(float(dev_person_hours[d]), 1), "first_crew_hour": round(float(t0), 1)})
    # Curve thinned to <= 60 points for the chart, always including the last
    step = max(1, len(curve) // 60)
    pts = curve[::step] + ([curve[-1]] if (len(curve) - 1) % step else [])
    return {
        "available": True, "source": "model_estimate", "storm_id": storm_id,
        "scenario": {"crews": crews, "crew_size": crew_size, "people": crews * crew_size,
                     "road_access": road_access, "workload": workload},
        "damaged_devices": len(st.devices), "repair_jobs": len(st.job_device), "customers_out": total,
        "critical_devices": int(st.critical.sum()),
        "total_person_hours": round(float(st.job_person_hours.sum() * scale)),
        "hours_to_restore": {"half": _time_to(curve, 0.5, total), "ninety_pct": _time_to(curve, 0.9, total),
                             "all": round(end, 1)},
        "ranges_p10_p50_p90": {"ninety_pct_hours": pct(t90), "all_hours": pct(ends)},
        "restore_curve": [{"hour": round(float(t), 1), "pct_restored": round(100.0 * r / max(total, 1), 1)}
                          for t, r in pts],
        "targets": targets,
        "first_jobs": first,
        "assumptions": [
            f"{crews} crews of {crew_size} people; each crew works one repair at a time, around the clock.",
            f"Damage assessment takes {start_h:g} hours before the first crew is dispatched.",
            "Repair hours: AEP labor sheet x structure drawings (pole size, phases) x 4.5 indirect multiplier.",
            "Jobs are chosen by customers restored per crew-hour, with a bonus for hospitals, fire and EMS.",
            "A customer is back when every damaged device on their path is repaired (step restoration).",
            "Replays the damage recorded in ARCOS for this storm; no switching or back-feed.",
        ],
    }
