"""
HOUR 4-8 (Jaid + Akshat): ARCOS damage + topology -> per-device storm history, damage mix, labels.
  python pipelines/03_build_labels.py

Outputs (contract: backend/app/core/data_loader.py):
  nodes.csv                 nodes_base + fail_prob + n_events_observed        (risk engine)
  damage_mix.json           {kind: {damage_type: share}}                       (restoration engine)
  meta.json                 n_events, severity curve, storm sizes, damage shares (risk + restoration)
  premise_event_labels.csv  premise_id, event_id  -- POSITIVES ONLY: a premise was out in an event if any
                            attributed damage sat on its upline path. Every other premise x event pair is 0.
  damage_attributed.csv     one row per ARCOS record: event, node, damage_type, match method + distance (QA, 05)
  durations.csv             event_id, node_id, damage_type, hours            (report -> repair, day resolution)

What the real ARCOS file forced (see docs/DATA_NOTES.md):
  * No storm IDs (Event = "Default" everywhere) -> storms = runs of report days with gaps <= event_gap_days.
  * No device ID column -> spatial attribution:
      - Fuse Bank / Recloser Bank / Transformer damage -> the nearest device of that type (records sit ~0 m away)
      - secondary wire -> the nearest transformer (secondary hangs off it)
      - primary wire / pole / switch / anything unmatched -> the nearest transformer's first upstream
        protective device (fuse, recloser, or breaker): the device that would open and cut those customers.
  * Storm sizes vary ~1,000x -> each device's damage RATE per typical (median) storm is estimated with a
    Gamma-Poisson empirical-Bayes model, weighting every storm by its size:
        rate_i = (records_i + mu_kind * beta_kind) / (sum of storm sizes in median-storm units + beta_kind)
        fail_prob_i = 1 - exp(-rate_i)            (chance of >= 1 damage in a median storm)
    mu_kind and beta_kind come from the data (method of moments per device kind), so sparse devices are pulled
    toward their kind's average. This is exactly consistent with the engine's  p' = 1 - (1-p)^m(s).
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import yaml

from _rates import fit_rates, storm_exposure      # shared with 05 so the backtest tests the served model

ROOT = Path(__file__).resolve().parents[1]
RAW, OUT = ROOT / "data" / "raw", ROOT / "data" / "processed"
CFG = yaml.safe_load((ROOT / "config" / "assumptions.yaml").read_text())["risk"]


def _require(*paths):
    """Exit cleanly (so `make pipelines` keeps going) when an input isn't there yet."""
    missing = [str(p.relative_to(ROOT)) for p in paths if not p.exists()]
    if missing:
        print(f"SKIP {Path(__file__).name}: missing {missing} (backend keeps using the synthetic fallback)")
        sys.exit(0)


# ---- Names read from recon_report.md (arcos_prod_damage_09_28_Clip) ----
ARCOS = RAW / "arcos_prod_damage_09_28_Clip.shp"
A = {"reported": "Report_Tim", "repaired_flag": "Repaired", "repaired": "Repaired_D",
     "asset": "Asset_Type", "damage": "Inform_Wor", "access": "Access_Iss"}
# Assets that don't interrupt customers' power (streetlights, capacitor banks) are dropped. Team decision.
EXCLUDED_ASSETS = {"Light", "Capacitor Bank"}
# (Asset_Type, Inform_Wor) -> our damage_type key. Keys MUST exist in assumptions.yaml repair_recipes / non_cu_hours.
DAMAGE_NAME_MAP = {
    ("Pole", "Damaged Pole"): "broken_pole",
    ("primary", "Damaged Wire"): "wire_down",
    ("secondary", "Damaged Wire"): "wire_down",
    ("Fuse Bank", "Damaged Switch"): "fuse_cutout_damaged",
    ("Recloser Bank", "Damaged Switch"): "recloser_damaged",
    ("Switch", "Damaged Switch"): "switch_damaged",
    ("Transformer", "Damaged Equipment"): "transformer_failed",
    ("Step Transformer", "Damaged Equipment"): "transformer_failed",
}
# Asset types matched to a device of their own kind: Asset_Type -> (node kind, max distance in metres)
OWN_DEVICE = {"Fuse Bank": ("fuse", 100), "Recloser Bank": ("recloser", 150), "Transformer": ("transformer", 100)}
SECONDARY_ASSETS = {"secondary"}            # -> nearest transformer
LINE_MAX_DIST_M = 1000                      # line/pole damage -> nearest transformer within this distance
PROTECTIVE_KINDS = {"fuse", "recloser", "breaker"}
# --------------------------------------------------------------------------
_require(ARCOS, OUT / "nodes_base.csv", OUT / "edges.csv")

nodes = pd.read_csv(OUT / "nodes_base.csv", dtype={"node_id": str, "circuit_id": str})
edges = pd.read_csv(OUT / "edges.csv", dtype=str)
parent = dict(zip(edges.child_id, edges.parent_id))
children = defaultdict(list)
for p, c in zip(edges.parent_id, edges.child_id):
    children[p].append(c)
kind = dict(zip(nodes.node_id, nodes.kind))
circuit = dict(zip(nodes.node_id, nodes.circuit_id))

# 1) Load ARCOS, drop non-interrupting assets, map damage types
dmg = gpd.read_file(ARCOS).to_crs(3857)                # metres, so "nearest" is a real distance
n_raw = len(dmg)
dmg = dmg[~dmg[A["asset"]].isin(EXCLUDED_ASSETS)].copy()
dmg["damage_type"] = [DAMAGE_NAME_MAP.get((a, d)) for a, d in zip(dmg[A["asset"]], dmg[A["damage"]])]
unmapped = dmg[dmg.damage_type.isna()][[A["asset"], A["damage"]]].value_counts()
if len(unmapped):
    sys.exit(f"ERROR: unmapped ARCOS (asset, damage) pairs, add them to DAMAGE_NAME_MAP:\n{unmapped}")

# 2) Storms: report days separated by more than event_gap_days start a new event
day = pd.to_datetime(dmg[A["reported"]]).dt.normalize()
days = pd.Series(sorted(day.unique()))
event_of_day = dict(zip(days, (days.diff().dt.days.fillna(np.inf) > CFG["event_gap_days"]).cumsum()))
dmg["event_id"] = day.map(event_of_day).map(lambda e: f"E{e:03d}")
dmg["report_day"] = day.dt.strftime("%Y-%m-%d")

# 3) Attribute every record to a node in our graph
dev = nodes[(nodes.kind != "premise") & nodes.lat.notna()]
dev = gpd.GeoDataFrame(dev, geometry=gpd.points_from_xy(dev.lon, dev.lat), crs=4326).to_crs(3857)


def nearest(sub, node_kind, max_m):
    cand = dev[dev.kind == node_kind][["node_id", "geometry"]]
    j = gpd.sjoin_nearest(sub[["geometry"]], cand, max_distance=max_m, distance_col="dist_m")
    return j[~j.index.duplicated()][["node_id", "dist_m"]]     # equidistant ties: keep the first


def protective_zone(xf):
    """First fuse/recloser/breaker upstream of a transformer: the device that opens for a line fault there."""
    cur = parent.get(xf)
    while cur is not None and kind[cur] not in PROTECTIVE_KINDS:
        cur = parent.get(cur)
    return cur


dmg["node_id"], dmg["method"], dmg["dist_m"] = None, None, np.nan
for asset, (node_kind, max_m) in OWN_DEVICE.items():
    sub = dmg[dmg[A["asset"]] == asset]
    j = nearest(sub, node_kind, max_m)
    dmg.loc[j.index, ["node_id", "dist_m"]] = j[["node_id", "dist_m"]].values
    dmg.loc[j.index, "method"] = "own_device"
rest = dmg[dmg.node_id.isna()]
j = nearest(rest, "transformer", LINE_MAX_DIST_M)
is_sec = rest.loc[j.index, A["asset"]].isin(SECONDARY_ASSETS)
dmg.loc[j.index, "node_id"] = [xf if s else protective_zone(xf) for xf, s in zip(j.node_id, is_sec)]
dmg.loc[j.index, "method"] = np.where(is_sec, "secondary_to_transformer", "line_to_protective_zone")
dmg.loc[j.index, "dist_m"] = j.dist_m.values
dmg = dmg.drop(columns="geometry")
att = dmg[dmg.node_id.notna()].copy()
print(f"ARCOS records: {n_raw} raw, {len(dmg)} after excluding {sorted(EXCLUDED_ASSETS)}, "
      f"{len(att)} attributed ({len(att) / len(dmg):.1%})")
print("  by method:", att.method.value_counts().to_dict())
print("  distance (m) by method, median/max:",
      att.groupby("method").dist_m.agg(["median", "max"]).round(1).to_dict("index"))

# 4) Storm sizes in "median storm" units -> severity curve (percentile -> size multiplier)
sizes = att.groupby("event_id").size()
med, M = storm_exposure(sizes)                          # typical storm size; total exposure in typical storms
m_e = sizes / med                                       # each storm's size relative to a typical storm
pct_e = (sizes.rank(method="average") - 0.5) / len(sizes) * 100
curve = (pd.DataFrame({"pct": pct_e, "m": m_e}).groupby("pct").m.mean().sort_index())
print(f"events={len(sizes)}  median records/event={med:g}  largest={int(sizes.max())} "
      f"(~{sizes.max() / med:.0f}x median)  exposure M={M:.1f} median-storms")

# 5) Damage rate per device: Gamma-Poisson empirical Bayes, prior per device kind (shared with 05)
rates, fit = fit_rates(nodes, att.groupby("node_id").size(), M)
nodes["fail_prob"] = (1 - np.exp(-nodes.node_id.map(rates))).fillna(0.0)    # premises: 0 (never on a path)
for k, v in fit.items():
    print(f"  {k:16s} devices={v['devices']:6d} records={v['records']:5d} "
          f"mu={v['mu']:.2e}/median-storm prior strength={v['beta']:.0f} storms"
          + (f" (borrowed from {v['borrowed_from']})" if "borrowed_from" in v else ""))

# 6) History depth for confidence: storms that touched the node's circuit
ev_per_circuit = att.assign(c=att.node_id.map(circuit)).groupby("c").event_id.nunique()
nodes["n_events_observed"] = nodes.circuit_id.map(ev_per_circuit).fillna(0).astype(int)
nodes.to_csv(OUT / "nodes.csv", index=False)

# 7) Damage-type mix by the kind of node damage was attributed to
att["kind"] = att.node_id.map(kind)
mix = att.groupby(["kind", "damage_type"]).size()
mix = (mix / mix.groupby(level=0).transform("sum")).round(4)
(OUT / "damage_mix.json").write_text(json.dumps({k: mix.loc[k].to_dict() for k in mix.index.levels[0]
                                                 if k in mix.index.get_level_values(0)}, indent=1))

# 8) Labels: premises downstream of any damaged node, per event (positives only)
rows = []
for ev, grp in att.groupby("event_id"):
    out, stack = set(), list(set(grp.node_id))
    while stack:
        n = stack.pop()
        for c in children.get(n, ()):
            if kind[c] == "premise":
                out.add(c)
            else:
                stack.append(c)
    rows += [(p, ev) for p in out]
labels = pd.DataFrame(rows, columns=["premise_id", "event_id"])
labels.to_csv(OUT / "premise_event_labels.csv", index=False)
n_prem = int((nodes.kind == "premise").sum())
share_out = (labels.groupby("event_id").size() / n_prem).reindex(sizes.index).fillna(0)

# 9) Attributed records (QA + backtest) and durations (day resolution; unrepaired records excluded)
att[["event_id", "report_day", "node_id", "kind", "damage_type", "method", "dist_m", A["asset"], A["access"]]] \
    .rename(columns={A["asset"]: "asset_type", A["access"]: "access_issue"}) \
    .to_csv(OUT / "damage_attributed.csv", index=False)
rep = att[att[A["repaired_flag"]] == "Yes"].copy()
rep["hours"] = (pd.to_datetime(rep[A["repaired"]]) - pd.to_datetime(rep[A["reported"]])).dt.total_seconds() / 3600
rep[["event_id", "node_id", "damage_type", "hours"]].to_csv(OUT / "durations.csv", index=False)

shares = att.damage_type.value_counts(normalize=True).round(4).to_dict()
meta = {
    "n_events": int(len(sizes)),
    "event_gap_days": CFG["event_gap_days"],
    "median_event_records": med,
    "severity_curve": [[round(float(p), 3), round(float(m), 4)] for p, m in curve.items()],
    "event_sizes": {e: int(s) for e, s in sizes.items()},
    "events": {e: {"start": g.report_day.min(), "end": g.report_day.max(), "records": int(len(g))}
               for e, g in att.groupby("event_id")},
    "event_share_premises_out": {e: round(float(s), 4) for e, s in share_out.items()},
    "damage_type_shares": shares,
    "kind_priors": fit,
    "date_range": [str(day.min().date()), str(day.max().date())],
}
(OUT / "meta.json").write_text(json.dumps(meta, indent=1))
print(f"labels: {len(labels)} positive premise-event pairs; share of premises out in the 3 largest storms: "
      f"{ {e: round(float(share_out[e]), 3) for e in sizes.sort_values(ascending=False).index[:3]} }")
print(f"circuits with no damage history: {int((ev_per_circuit.reindex(nodes.circuit_id.unique()).isna()).sum())}")
print(f"-> {OUT}/nodes.csv, damage_mix.json, meta.json, premise_event_labels.csv, damage_attributed.csv, durations.csv")
