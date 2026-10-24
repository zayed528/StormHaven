"""
DataStore: the single in-memory view of the network that every engine reads.   Owner: Jaid

Loads data/processed/* (produced by pipelines/). Network and labor load independently:
  - network (nodes/edges/damage_mix/priority) is real if nodes.csv exists, else SYNTHETIC
  - labor (labor_hours/multipliers/access_adders) is AEP if pipelines/04 ran, else placeholders
So everyone can develop from hour 1, and restarting the API after a pipeline run picks up real data.
Set STORMHAVEN_DATA=synthetic to force the synthetic network even when real data exists (tests do this).

Processed file contract (pipelines must output exactly this):
  nodes.csv          node_id, kind, circuit_id, lat, lon, fail_prob, n_events_observed       (02 + 03)
                     kind in {substation, breaker, recloser, fuse, transformer, premise}
  edges.csv          parent_id, child_id          (power flows parent -> child)                (02)
  damage_mix.json    {kind: {damage_type: share}}                                              (03)
  meta.json          {"n_events": N, "severity_curve": [[percentile, size_multiplier], ...],
                      "median_event_records": r, "damage_type_shares": {type: share}, ...}       (03)
  priority_nodes.csv node_id    (devices feeding a critical facility; never exposed)           (06)
  labor_hours.csv    damage_type, hours [, source]   PERSON-hours per unit of damage           (04)
  multipliers.json   {"indirect_labor_multiplier": x}                                          (04)
                     (legacy shape {"travel": a, "nonproductive": b} also accepted -> 1 + a + b)
  access_adders.json {"limited": h, "blocked": h}   person-hours added per job                 (04)
"""
from __future__ import annotations
import json
import os
import random
from dataclasses import dataclass, field
from functools import lru_cache

import networkx as nx
import pandas as pd

from app.config import ASSUMPTIONS, DATA_PROCESSED

RCFG = ASSUMPTIONS["restoration"]


@dataclass
class DataStore:
    """Everything the engines read, loaded once at startup (see get_store)."""
    # Directed graph, edges parent -> child (power flow). Node attrs: kind, circuit_id, lat, lon, fail_prob,
    # n_events_observed, critical, plus derived customers + critical_downstream (_annotate_customers).
    graph: nx.DiGraph
    labor_hours: dict[str, float]          # person-hours per unit of damage
    indirect_multiplier: float             # travel + safety + setup, applied to labor hours
    access_adders: dict[str, float]        # road_access level -> person-hours added per job
    damage_mix: dict[str, dict[str, float]]   # device kind -> {damage_type: share of past damage}
    n_events: int                          # number of historical storms behind fail_prob
    is_synthetic: bool                     # True = synthetic network (shown as a banner in the UI)
    labor_from_aep: bool = False           # True = labor hours came from the AEP workbook
    notes: list[str] = field(default_factory=list)   # human-readable data status, shown by /api/health
    # Real data only (from meta.json); None on the synthetic network, where the engines fall back to config.
    severity_curve: list[tuple[float, float]] | None = None   # (percentile, storm size / median storm size)
    median_event_records: float | None = None                 # damage records in a typical (median) storm
    damage_type_shares: dict[str, float] | None = None        # share of each damage type across all storms


# ---------------------------------------------------------------- labor (pipelines/04)
def _load_labor() -> tuple[dict[str, float], float, dict[str, float], bool, str]:
    """Returns (labor_hours, indirect_multiplier, access_adders, from_aep, note). Placeholders if 04 hasn't run."""
    lh_path, mult_path = DATA_PROCESSED / "labor_hours.csv", DATA_PROCESSED / "multipliers.json"
    if not (lh_path.exists() and mult_path.exists()):
        return (dict(RCFG["placeholder_labor_hours"]), RCFG["default_indirect_labor_multiplier"], {}, False,
                "Labor hours: placeholders (run pipelines/04_load_labor.py for AEP values).")
    labor = pd.read_csv(lh_path)
    mult = json.loads(mult_path.read_text())
    # New shape (one AEP multiplier) preferred; old {travel, nonproductive} shape still works.
    ilm = mult.get("indirect_labor_multiplier") or 1 + mult.get("travel", 0) + mult.get("nonproductive", 0)
    adders_path = DATA_PROCESSED / "access_adders.json"
    adders = json.loads(adders_path.read_text()) if adders_path.exists() else {}
    return (dict(zip(labor.damage_type, labor.hours.astype(float))), float(ilm), adders, True,
            "Labor hours: AEP compatible-unit sheet + indirect labor multiplier.")


# ---------------------------------------------------------------- real network
def _load_processed() -> DataStore:
    """Build the DataStore from pipeline outputs (02/03/06). Missing optional files just skip a feature."""
    nodes = pd.read_csv(DATA_PROCESSED / "nodes.csv", dtype={"node_id": str, "circuit_id": str})
    edges = pd.read_csv(DATA_PROCESSED / "edges.csv", dtype=str)
    mix = json.loads((DATA_PROCESSED / "damage_mix.json").read_text())

    g = nx.DiGraph()
    for r in nodes.itertuples(index=False):      # lat/lon may be NaN (breakers, step transformers)
        g.add_node(r.node_id, kind=r.kind, circuit_id=r.circuit_id, lat=r.lat, lon=r.lon,
                   fail_prob=float(r.fail_prob), n_events_observed=int(r.n_events_observed),
                   critical=False)
    g.add_edges_from(edges[["parent_id", "child_id"]].itertuples(index=False, name=None))

    # Flag devices that feed hospitals/fire/EMS. Only the flag is kept; facility locations stay in the pipeline.
    prio_path = DATA_PROCESSED / "priority_nodes.csv"
    if prio_path.exists():
        for nid in pd.read_csv(prio_path, dtype=str)["node_id"]:
            if nid in g:
                g.nodes[nid]["critical"] = True

    _annotate_customers(g)
    meta_path = DATA_PROCESSED / "meta.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    labor, ilm, adders, labor_aep, labor_note = _load_labor()
    curve = [tuple(x) for x in meta["severity_curve"]] if meta.get("severity_curve") else None
    return DataStore(g, labor, ilm, adders, mix, meta.get("n_events", 10), False, labor_aep,
                     notes=["Network: AEP data (data/processed).", labor_note],
                     severity_curve=curve, median_event_records=meta.get("median_event_records"),
                     damage_type_shares=meta.get("damage_type_shares"))


# ----------------------------------------------------------- synthetic network
def _build_synthetic(seed: int = 7) -> DataStore:
    """Small realistic-shaped network: 1 substation -> 3 circuits -> reclosers -> fuses -> transformers -> premises."""
    rng = random.Random(seed)
    g = nx.DiGraph()
    base_lat, base_lon = 40.00, -83.00     # arbitrary demo origin, NOT a real AEP location

    # fp = historical failure prob, n_obs = storms of history (drives confidence). Values are invented.
    def add(nid, kind, circuit, lat, lon, fp, n_obs, critical=False):
        g.add_node(nid, kind=kind, circuit_id=circuit, lat=lat, lon=lon,
                   fail_prob=fp, n_events_observed=n_obs, critical=critical)

    add("SUB-1", "substation", "ALL", base_lat, base_lon, 0.005, 12)
    for c in range(3):
        circ = f"CKT-{c+1}"
        b = f"BRK-{c+1}"
        ang_lat, ang_lon = [(0.04, 0.0), (-0.03, 0.04), (-0.03, -0.04)][c]
        add(b, "breaker", circ, base_lat + ang_lat * 0.2, base_lon + ang_lon * 0.2, 0.01, 12)
        g.add_edge("SUB-1", b)
        rural = c == 2                                   # circuit 3 is long, wooded, rural
        for r in range(2):
            rc = f"REC-{c+1}{r+1}"
            add(rc, "recloser", circ, base_lat + ang_lat * (0.5 + r * 0.5), base_lon + ang_lon * (0.5 + r * 0.5),
                0.06 if rural else 0.03, rng.choice([2, 5, 9, 12]), critical=(c == 0 and r == 0))
            g.add_edge(b, rc)
            for fu in range(4):
                f = f"FUS-{c+1}{r+1}{fu+1}"
                flat = g.nodes[rc]["lat"] + rng.uniform(-0.012, 0.012)
                flon = g.nodes[rc]["lon"] + rng.uniform(-0.012, 0.012)
                add(f, "fuse", circ, flat, flon, rng.uniform(0.08, 0.22) if rural else rng.uniform(0.02, 0.10),
                    rng.choice([1, 3, 6, 10]))
                g.add_edge(rc, f)
                for t in range(3):
                    tx = f"TX-{c+1}{r+1}{fu+1}{t+1}"
                    add(tx, "transformer", circ, flat + rng.uniform(-0.004, 0.004), flon + rng.uniform(-0.004, 0.004),
                        rng.uniform(0.01, 0.05), rng.choice([1, 3, 6]))
                    g.add_edge(f, tx)
                    for p in range(5):
                        pid = f"P-{c+1}{r+1}{fu+1}{t+1}{p+1}"
                        add(pid, "premise", circ, g.nodes[tx]["lat"] + rng.uniform(-0.0015, 0.0015),
                            g.nodes[tx]["lon"] + rng.uniform(-0.0015, 0.0015), 0.0, 0)
                        g.add_edge(tx, pid)

    _annotate_customers(g)
    # Invented damage-type mix per device kind (real version comes from ARCOS via pipelines/03).
    # Keys must match labor_hours names so every draw has a labor estimate.
    mix = {
        "recloser": {"recloser_damaged": 0.4, "tree_on_line": 0.4, "broken_pole": 0.2},
        "fuse": {"fuse_blown": 0.4, "tree_on_line": 0.3, "wire_down": 0.2, "broken_crossarm": 0.1},
        "transformer": {"transformer_failed": 0.6, "wire_down": 0.4},
        "breaker": {"tree_on_line": 0.5, "broken_pole": 0.5},
        "substation": {"recloser_damaged": 1.0},
    }
    labor, ilm, adders, labor_aep, labor_note = _load_labor()
    return DataStore(g, labor, ilm, adders, mix, n_events=12, is_synthetic=True, labor_from_aep=labor_aep,
                     notes=["Network: SYNTHETIC demo network, not AEP data.", labor_note])


def _annotate_customers(g: nx.DiGraph) -> None:
    """customers = premises downstream; critical_downstream = feeds a critical node."""
    # Reverse topological order = leaves (premises) first, so children are always counted before parents.
    for n in reversed(list(nx.topological_sort(g))):
        d = g.nodes[n]
        kids = list(g.successors(n))
        d["customers"] = 1 if d["kind"] == "premise" else sum(g.nodes[k]["customers"] for k in kids)
        d["critical_downstream"] = d.get("critical", False) or any(g.nodes[k]["critical_downstream"] for k in kids)


@lru_cache(maxsize=1)
def get_store() -> DataStore:
    """Singleton: built on first call, reused for every request. Restart the API to pick up new pipeline output."""
    if os.getenv("STORMHAVEN_DATA", "").lower() != "synthetic" and (DATA_PROCESSED / "nodes.csv").exists():
        return _load_processed()
    return _build_synthetic()
