"""
ENGINE 2 — "How long could restoration take?"   Owner: Akshat (math) + Jaid (sequencing)

Monte Carlo over damage on YOUR upline path:
  time_to_restore = assessment + max over damaged devices on path of
                    (queue_wait(priority) + repair_labor)
  repair_labor   = (qty * labor_hours[type] + access_adder) * indirect_multiplier / crew_size * access * noise
                   labor_hours = AEP compatible-unit person-hours summed over a repair recipe (pipelines/04)
  queue_wait     = storm-wide backlog of higher-priority work / crews
Priority = customers restored by that repair (+ bonus if it feeds a critical facility).
That's step restoration: main-line fixes go first because they bring back the most people.
"""
from __future__ import annotations
import warnings

import numpy as np

from app.config import ASSUMPTIONS
from app.core.data_loader import DataStore
from app.core.privacy import friendly_name
from app.engines.risk import PathRisk, severity_multiplier
from app.schemas import AccessLevel, Driver, RestorationResponse, RestorationStep, StormScenario, TrustInfo

CFG = ASSUMPTIONS["restoration"]
# Priority ranking depends only on the network, not the scenario, so compute it once per DataStore.
# Keyed by id(store) because DataStore (a dataclass) isn't hashable.
_PRIORITY_CACHE: dict[int, dict[str, float]] = {}


def _priority_percentiles(store: DataStore) -> dict[str, float]:
    """Rank every device by restoration priority -> percentile in [0,1] (1 = first)."""
    if id(store) in _PRIORITY_CACHE:
        return _PRIORITY_CACHE[id(store)]
    g = store.graph
    bonus = CFG["critical_facility_priority_bonus"]
    devs = [n for n, d in g.nodes(data=True) if d["kind"] != "premise"]
    # Score = customers this device brings back, plus a large bonus if a hospital/fire/EMS sits downstream.
    score = {n: g.nodes[n]["customers"] + (bonus if g.nodes[n]["critical_downstream"] else 0) for n in devs}
    order = sorted(devs, key=lambda n: score[n])          # ascending: last = highest priority
    _PRIORITY_CACHE[id(store)] = {n: (i + 1) / len(order) for i, n in enumerate(order)}
    return _PRIORITY_CACHE[id(store)]


def _simulate(store: DataStore, pr: PathRisk, sc: StormScenario, n: int, seed: int = 42):
    """Returns (totals[n], per_device_completion[n, len(path)] with nan where undamaged).

    Rows = simulated storms (n of them), columns = devices on the customer's upline path (k).
    A fixed seed means the same scenario always gives the same answer (reproducible + auditable),
    and the "what if" drivers compare scenarios on the same random draws (common random numbers).
    """
    rng = np.random.default_rng(seed)
    g, path = store.graph, pr.path
    k = len(path)
    prio = _priority_percentiles(store)
    to_clock_hours = store.indirect_multiplier / CFG["crew_size_persons"]   # person-hours -> crew clock hours
    unknown_hrs = CFG["unknown_damage_type_hours"]
    access = CFG["access_multipliers"][sc.road_access.value]
    # Total storm-wide work ahead of everyone, in crew clock-hours; grows with storm severity.
    m = severity_multiplier(sc.severity_percentile, store, for_risk=False)   # workload: undamped storm size
    if store.median_event_records and store.damage_type_shares:
        # Real data: expected damage records in a storm this size x average crew hours per record.
        avg_person_hrs = sum(share * store.labor_hours.get(t, unknown_hrs)
                             for t, share in store.damage_type_shares.items())
        backlog = store.median_event_records * m * avg_person_hrs * to_clock_hours
    else:
        # Synthetic network: assumed backlog per crew at a median storm, scaled by severity.
        backlog = CFG["base_backlog_hours_per_crew"] * CFG["default_crews"] * m

    # 1) Which devices fail in each simulated storm: independent Bernoulli draws with the storm-adjusted probs.
    damaged = rng.random((n, k)) < pr.p_adj
    # Condition on "you lost power": force at least one damaged device, weighted by p_adj
    # (the question is "how long IF you lose power", so storms where nothing on your path breaks don't count).
    none = ~damaged.any(axis=1)
    if none.any():
        w = pr.p_adj / pr.p_adj.sum()
        damaged[np.where(none)[0], rng.choice(k, size=none.sum(), p=w)] = True

    # 2) Repair labor per device (person-hours): draw a damage type from that device kind's historical mix
    #    (ARCOS damage_mix.json), look up its labor hours, and multiply by a quantity of 1 or 2.
    labor = np.zeros((n, k))
    for j, node in enumerate(path):
        kind = g.nodes[node]["kind"]
        mix = store.damage_mix.get(kind) or {"wire_down": 1.0}       # no history for this kind -> assume a wire down
        types, shares = list(mix), np.array(list(mix.values()), dtype=float)
        picked = rng.choice(len(types), size=n, p=shares / shares.sum())
        hrs = np.array([store.labor_hours.get(t, unknown_hrs) for t in types])[picked]
        qty = rng.integers(1, 3, size=n)                              # 1 or 2 units of damage
        labor[:, j] = qty * hrs

    # Judge-added damage: attach to named device, else the highest-hazard device on path.
    # It is damaged in EVERY simulated storm, so the range visibly moves in the demo.
    for item in sc.extra_damage:
        j = path.index(item.equipment_id) if item.equipment_id in path else int(np.argmax(pr.p_adj))
        damaged[:, j] = True
        labor[:, j] += item.quantity * store.labor_hours.get(item.damage_type, unknown_hrs)

    # 3) Person-hours -> crew clock hours, with road access and lognormal noise (real jobs vary).
    labor += store.access_adders.get(sc.road_access.value, 0.0)     # AEP per-job access adder
    labor *= to_clock_hours * access * rng.lognormal(0, CFG["labor_noise_sigma"], size=(n, k))
    # 4) Queue wait: the share of the backlog ranked ahead of this device, split across available crews.
    #    Highest-priority device (percentile 1.0) waits ~0; low-priority ones wait for most of the backlog.
    wait = np.array([backlog * (1 - prio[node]) for node in path]) / sc.crews_available * access
    # 5) Each damaged device is done at assessment + wait + labor; undamaged ones are nan (ignored).
    completion = np.where(damaged, CFG["assessment_hours"] + wait + labor, np.nan)
    # Your power is back only when EVERY damaged device on your path is fixed -> take the max.
    totals = np.nanmax(completion, axis=1)
    return totals, completion


def _hrs(h: float) -> str:
    """Whole hours with correct plural, for driver text ("About 3 hours sooner...")."""
    n = max(1, round(h))
    return f"{n} hour" if n == 1 else f"{n} hours"


def _fmt(h: float) -> str:
    """Customer-facing duration: switch to days at 48 h so long outages aren't shown as '73 hours'."""
    return f"{h / 24:.1f} days" if h >= 48 else f"{h:.0f} hours"


def estimate_restoration(store: DataStore, pr: PathRisk, sc: StormScenario,
                         risk_confidence: str) -> RestorationResponse:
    """Public entry point (called by service.py). Reuses the PathRisk from the risk engine so both
    engines reason about the same path and the same storm-adjusted failure probabilities."""
    # Fallback: location not matched -> say so plainly, never return made-up numbers.
    if pr.level == "none":
        return RestorationResponse(
            source="fallback", p10_hours=0, p50_hours=0, p90_hours=0,
            range_text="We can't estimate restoration for this location yet.",
            steps=[], drivers=[],
            trust=TrustInfo(confidence="Low", missing_data=["Location not matched to network."],
                            could_change_if=["Select your area on the map."]))

    totals, completion = _simulate(store, pr, sc, CFG["n_simulations"])
    # The answer is a RANGE: P10 = optimistic, P50 = best guess, P90 = pessimistic.
    p10, p50, p90 = np.percentile(totals, [10, 50, 90])

    # ---- step restoration: substation-side first, using median completion when damaged
    g = store.graph
    steps = []
    # Only show steps that are plausible (>= 3% failure chance), judge-added, or the single most likely failure.
    likely = {j for j in range(len(pr.path)) if pr.p_adj[j] >= 0.03 or
              any(d.equipment_id == pr.path[j] for d in sc.extra_damage)}
    likely.add(int(np.argmax(pr.p_adj)))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)      # all-nan columns = never damaged
        med = np.nanmedian(completion, axis=0)
    # "Your area" = everything under your circuit breaker; used to say "serves about X% of your area".
    area_root = next((n for n in pr.path if g.nodes[n]["kind"] == "breaker"), pr.path[-1])
    area_customers = max(g.nodes[area_root]["customers"], 1)
    running = 0.0
    # path is nearest-first, so reverse index order = substation side first
    for order, j in enumerate(sorted(likely, reverse=True), start=1):
        node = pr.path[j]
        share = max(1, round(100 * g.nodes[node]["customers"] / area_customers))
        running = max(running, float(np.nan_to_num(med[j], nan=p50)))   # you can't be back before upstream is
        steps.append(RestorationStep(
            order=order, eta_hours=round(running, 1), restores_your_power=False,
            description=f"If damaged, crews repair {friendly_name(g.nodes[node]['kind'])} "
                        f"(serves about {share}% of your area)."))
    if steps:
        steps[-1].restores_your_power = True      # the step nearest your home is the one that brings you back

    # ---- what moves the estimate (common random numbers via same seed)
    # Re-run a smaller simulation under three "what if" changes and report the shift in P50.
    # The baseline is re-run at the same size (300) so the comparison is like-for-like.
    def p50_for(s: StormScenario) -> float:
        t, _ = _simulate(store, pr, s, 300)
        return float(np.percentile(t, 50))
    base = p50_for(sc)
    drivers = []
    for name, alt, text in [   # (machine name, altered scenario, customer-facing phrase)
        ("more_crews", sc.model_copy(update={"crews_available": int(sc.crews_available * 1.5) + 1}),
         "if 50% more crews are available"),
        ("roads_blocked", sc.model_copy(update={"road_access": AccessLevel.blocked}),
         "if fallen trees block roads"),
        ("stronger_storm", sc.model_copy(update={"severity_percentile": min(100, sc.severity_percentile + 20)}),
         "if the storm is stronger than forecast"),
    ]:
        delta = p50_for(alt) - base
        if abs(delta) >= 0.5:      # hide drivers that barely matter (e.g. "roads blocked" when already blocked)
            drivers.append(Driver(name=name, delta_p50_hours=round(delta, 1),
                                  plain_language=f"About {_hrs(abs(delta))} {'sooner' if delta < 0 else 'later'} {text}."))

    return RestorationResponse(
        p10_hours=round(float(p10), 1), p50_hours=round(float(p50), 1), p90_hours=round(float(p90), 1),
        range_text=f"If you lose power, most likely {_fmt(p10)} to {_fmt(p90)} (best guess about {_fmt(p50)}).",
        steps=steps, drivers=drivers,
        trust=TrustInfo(
            confidence=risk_confidence,       # restoration inherits the risk engine's confidence (same path data)
            # Assumptions are stated in plain language so the customer sees what the range depends on.
            assumptions=[f"{sc.crews_available} crews available storm-wide.",
                         f"Road access: {sc.road_access.value}.",
                         f"Each repair crew has {CFG['crew_size_persons']} people.",
                         ("Repair times use AEP's standard labor hours plus travel and setup time."
                          if store.labor_from_aep else
                          "Repair times use placeholder labor hours until AEP's labor sheet is loaded."),
                         "Crews restore the repairs that bring back the most customers first."],
            could_change_if=[d.plain_language for d in drivers]),
        confirmed_etr=None)   # never set by the model; service.py fills it from utility_status only
