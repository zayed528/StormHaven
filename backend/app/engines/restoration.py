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
import math
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


def crew_size(sc: StormScenario) -> int:
    """People per crew for this scenario: the scenario's choice, else the config default."""
    return sc.crew_size or CFG["crew_size_persons"]


def _expected_person_hours(store: DataStore, kind: str) -> float:
    """Average direct labor hours to repair a device of this kind, from its historical damage-type mix."""
    mix = store.damage_mix.get(kind) or {"wire_down": 1.0}
    total = sum(mix.values()) or 1.0
    return sum(share * store.labor_hours.get(t, CFG["unknown_damage_type_hours"]) for t, share in mix.items()) / total


def _priority_percentiles(store: DataStore) -> dict[str, float]:
    """Rank every device by restoration priority -> percentile in [0,1] (1 = first).
    Value vs effort (AEP data guide): (customers restored + critical bonus) / expected repair hours."""
    if id(store) in _PRIORITY_CACHE:
        return _PRIORITY_CACHE[id(store)]
    g = store.graph
    bonus = CFG["critical_facility_priority_bonus"]
    devs = [n for n, d in g.nodes(data=True) if d["kind"] != "premise"]
    # Value = customers this device brings back, plus a large bonus if a hospital/fire/EMS sits downstream.
    # Effort = expected repair hours for this kind of device. Highest value per hour goes first.
    effort = {k: max(_expected_person_hours(store, k), 0.1) for k in {g.nodes[n]["kind"] for n in devs}}
    score = {n: (g.nodes[n]["customers"] + (bonus if g.nodes[n]["critical_downstream"] else 0))
             / effort[g.nodes[n]["kind"]] for n in devs}
    order = sorted(devs, key=lambda n: score[n])          # ascending: last = highest priority
    _PRIORITY_CACHE[id(store)] = {n: (i + 1) / len(order) for i, n in enumerate(order)}
    return _PRIORITY_CACHE[id(store)]


_QUEUE_CACHE: dict[int, tuple[np.ndarray, np.ndarray] | None] = {}


def _queue_curve(store: DataStore) -> tuple[np.ndarray, np.ndarray] | None:
    """Share of the storm's repair work done BEFORE crews reach a device, as a function of the device's
    restoration-priority percentile, learned from replaying real storms in the planner (engines/planner.py).
    Calibrates the customer engine against the storm replay so both tell the same story.
    Real data only (None on the synthetic network -> the simple rule 1 - priority is used)."""
    if id(store) in _QUEUE_CACHE:
        return _QUEUE_CACHE[id(store)]
    curve = None
    if not store.is_synthetic:
        from app.engines import planner                     # local import: planner is optional (needs real data)
        if planner.available():
            qc = ASSUMPTIONS["restoration"]["queue_calibration"]
            prio = _priority_percentiles(store)
            xs, ys = [], []
            for s in planner.storms()[:qc["storms"]]:
                st = planner._storm(s["storm_id"])
                hrs = planner._hours(st, CFG["crew_size_persons"], "normal", 1.0)
                _, _, order = planner._simulate(st, hrs, qc["crews"], CFG["assessment_hours"], record=True)
                per_crew = hrs.sum() / qc["crews"]              # storm work per crew = backlog / crews
                for d, t0 in order:
                    xs.append(prio[st.devices[d]])
                    ys.append((t0 - CFG["assessment_hours"]) / per_crew)
            if xs:
                edges = np.array(qc["bin_edges"])
                idx = np.clip(np.digitize(xs, edges) - 1, 0, len(edges) - 2)
                mids, means = [], []
                for b in range(len(edges) - 1):
                    sel = idx == b
                    if sel.any():
                        mids.append((edges[b] + edges[b + 1]) / 2)
                        means.append(float(np.mean(np.array(ys)[sel])))
                # higher priority never waits longer (monotone), anchored at 1 (nothing ahead) for the very top
                means = list(np.minimum.accumulate(means))
                curve = (np.array(mids + [1.0]), np.clip(np.array(means + [0.0]), 0, 1))
    _QUEUE_CACHE[id(store)] = curve
    return curve


def _work_ahead(store: DataStore, p: float) -> float:
    """Share of storm work ahead of a device with priority percentile p."""
    curve = _queue_curve(store)
    return float(np.interp(p, *curve)) if curve else 1 - p


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
    to_clock_hours = store.indirect_multiplier / crew_size(sc)             # person-hours -> crew clock hours
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
    wait = np.array([backlog * _work_ahead(store, prio[node]) for node in path]) / sc.crews_available * access
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
    """Customer-facing single duration (the 'best guess'): days at 48 h+ so long outages aren't '73 hours'."""
    if h >= 48:
        return f"{h / 24:.1f} days"
    n = round(h)
    return f"{n} hour" if n == 1 else f"{n} hours"


def range_endpoints(lo: float, hi: float) -> tuple[int, str, int, str]:
    """The ONE rounding rule for a restoration range, shared by the on-screen sentence and every SMS
    (alerts.short_range): low end rounds down, high end rounds up (the range never looks narrower than it is);
    hours while the range ends under 48 h, then days. Returns (lo, lo_unit, hi, hi_unit), units 'hours'|'days'."""
    if hi < 48:
        return max(0, math.floor(lo)), "hours", max(1, math.ceil(hi)), "hours"
    if lo < 24:
        return math.floor(lo), "hours", math.ceil(hi / 24), "days"
    return math.floor(lo / 24), "days", math.ceil(hi / 24), "days"


def _range_words(lo: float, hi: float) -> str:
    """'6 to 24 hours', '20 hours to 3 days', '2 to 4 days' (English sentence form of range_endpoints)."""
    a, ua, b, ub = range_endpoints(lo, hi)
    unit = lambda n, u: f"{n} {u[:-1]}" if n == 1 else f"{n} {u}"      # noqa: E731  (1 hour / 1 day)
    return f"{a} to {unit(b, ub)}" if ua == ub else f"{unit(a, ua)} to {unit(b, ub)}"


def storm_context(store: DataStore, sc: StormScenario) -> str | None:
    """One customer sentence from the storm replay (engines/planner.py): how fast homes came back in the closest
    real storm, with this scenario's crews. None on the synthetic network or for mild storms."""
    if store.is_synthetic:
        return None
    from app.engines import planner                         # local import: planner needs real data
    ctx = planner.customer_context(round(sc.severity_percentile, 1), sc.crews_available, crew_size(sc),
                                   sc.road_access.value)
    if not ctx:
        return None
    h = ctx["hours_to_90pct"]
    when = f"about {max(1, round(h))} hours" if h < 48 else f"about {round(h / 24)} days"
    return (f"In our replay of the {ctx['label']} with {ctx['crews']} crews, 9 in 10 affected homes "
            f"had power back within {when}.")


def replay_storm_id(store: DataStore, sc: StormScenario) -> str | None:
    """storm_id of the real storm this scenario is matched to (planner.match_storm), the same storm the
    storm_context sentence describes. Values match GET /api/planner/storms -> storm_id. None when there's no match."""
    if store.is_synthetic:
        return None
    from app.engines import planner                         # local import: planner needs real data
    ref = planner.match_storm(round(sc.severity_percentile, 1))
    return ref["storm_id"] if ref else None


def estimate_restoration(store: DataStore, pr: PathRisk, sc: StormScenario,
                         risk_confidence: str, outage_confirmed: bool = False) -> RestorationResponse:
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
        # Before an outage it's conditional ("if you lose power"); once the utility confirms one it isn't.
        range_text=(f"Our estimate: power back in about {_range_words(p10, p90)} (best guess about {_fmt(p50)}). "
                    "This is a model estimate, not a confirmed restoration time." if outage_confirmed else
                    f"If you lose power, most likely {_range_words(p10, p90)} (best guess about {_fmt(p50)})."),
        steps=steps, drivers=drivers,
        trust=TrustInfo(
            confidence=risk_confidence,       # restoration inherits the risk engine's confidence (same path data)
            # Assumptions are stated in plain language so the customer sees what the range depends on.
            assumptions=[f"{sc.crews_available} crews available storm-wide.",
                         f"Road access: {sc.road_access.value}.",
                         f"Each repair crew has {crew_size(sc)} people.",
                         ("Repair times use AEP's standard labor hours plus travel and setup time."
                          if store.labor_from_aep else
                          "Repair times use placeholder labor hours until AEP's labor sheet is loaded."),
                         "Crews restore the repairs that bring back the most customers first."],
            could_change_if=[d.plain_language for d in drivers]),
        confirmed_etr=None,   # never set by the model; service.py fills it from utility_status only
        # Customer sentence from the storm replay. Sent only once schemas.py has the field (Jaid), so this
        # file never breaks the response contract.
        **({"storm_context": storm_context(store, sc)} if "storm_context" in RestorationResponse.model_fields else {}),
        # Which real storm that sentence is about (Nandan's console/banner select by it). Sent once schemas.py has
        # the field (Jaid).
        **({"replay_storm_id": replay_storm_id(store, sc)}
           if "replay_storm_id" in RestorationResponse.model_fields else {}))
