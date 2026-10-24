"""
HOUR (Jaid): per-device ZONE features -> data/processed/device_features.csv
  python pipelines/08_features.py
Needs 02 (edges.csv, nodes_base.csv) and the AEP GIS line + pole layers. Reads nodes.csv if 03 has run
(for fail_prob / n_events_observed), else falls back to nodes_base.csv.
After adding this, ask Nandan to add `python pipelines/08_features.py` to the Makefile `pipelines` target.

WHAT A "ZONE" IS
  A protective device (fuse, recloser, breaker) trips and cuts power to everything below it, down to the
  next protective device. That downstream subtree is the device's PROTECTIVE ZONE. Think of a house breaker:
  its zone is every outlet it controls, stopping where another breaker takes over.
  We emit one row per fuse / recloser / breaker (its protective zone) AND one row per transformer
  (its local zone = the transformer plus the premises/step-transformers hanging directly off it).

ASSIGNING LINES AND POLES TO A ZONE
  Line segments (Primary_ExportFeatures) and poles (Pole_Clip) carry no device ID. We attach each to a zone
  with the SAME rule 03_build_labels.py uses for line/pole damage, so zone geography is consistent with how
  damage was attributed:
    nearest transformer within LINE_MAX_DIST_M  ->  that transformer's first upstream protective device.
  Primary lines already carry circuit_id, so we only consider transformers on the same circuit (cheaper and
  avoids cross-circuit mis-matches). Poles have no circuit_id, so they match any nearby transformer.

OUTPUT CONTRACT (one row per zone-owning device)
  device_id            node_id of the zone owner (e.g. FU-..., RC-..., CB-..., XF-...)
  kind                 fuse | recloser | breaker | transformer
  circuit_id
  lat, lon             the device's own coordinates (may be blank for breakers/step transformers)
  n_customers          premises served by the zone (whole downstream subtree for protective devices)
  n_transformers       transformers in the zone
  n_downstream_devices protective devices strictly inside the zone (depth of nesting below this one)
  n_poles              poles assigned to the zone (hazard surface: more poles = more to inspect/repair)
  line_km              primary line length assigned to the zone, kilometres
  fail_prob            this device's per-median-storm failure probability (from 03; blank if 03 hasn't run)
  n_events_observed    storms that touched this device's circuit (from 03)
  critical             True if the zone feeds a hospital/fire/EMS transformer (from 06 priority_nodes.csv)

PRIVACY: aggregate counts and the device's own (already-published) coordinates only. No premise locations,
no customer attributes, no facility data. Safe to describe in docs/DATA_NOTES.md.
"""
import sys
from collections import defaultdict, deque
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW, OUT = ROOT / "data" / "raw", ROOT / "data" / "processed"

# ---- Names read from recon_report.md (same files 03 / 06 use) ----
PRIMARY = RAW / "Primary_ExportFeatures.shp"     # line segments, carry circuit_id
POLES = RAW / "Pole_Clip.shp"                    # pole points, no circuit_id
LINE_MAX_DIST_M = 1000                           # same as 03: line/pole -> nearest transformer within this
PROTECTIVE_KINDS = {"fuse", "recloser", "breaker"}
METRIC_CRS = 3857                                # metres, so "nearest" and lengths are real distances
# ------------------------------------------------------------------


def _require(*paths):
    """Exit cleanly (so `make pipelines` keeps going) when an input isn't there yet."""
    missing = [str(p.relative_to(ROOT)) for p in paths if not p.exists()]
    if missing:
        print(f"SKIP {Path(__file__).name}: missing {missing} (backend keeps using the synthetic fallback)")
        sys.exit(0)


_require(OUT / "nodes_base.csv", OUT / "edges.csv", PRIMARY, POLES)

# Prefer nodes.csv (has fail_prob / n_events_observed from 03); fall back to nodes_base.csv.
nodes_path = OUT / "nodes.csv" if (OUT / "nodes.csv").exists() else OUT / "nodes_base.csv"
nodes = pd.read_csv(nodes_path, dtype={"node_id": str, "circuit_id": str})
edges = pd.read_csv(OUT / "edges.csv", dtype=str)

kind = dict(zip(nodes.node_id, nodes.kind))
circuit = dict(zip(nodes.node_id, nodes.circuit_id))
parent = dict(zip(edges.child_id, edges.parent_id))
children = defaultdict(list)
for p, c in zip(edges.parent_id, edges.child_id):
    children[p].append(c)

fail_prob = dict(zip(nodes.node_id, nodes.fail_prob)) if "fail_prob" in nodes else {}
n_events = dict(zip(nodes.node_id, nodes.n_events_observed)) if "n_events_observed" in nodes else {}

# Critical transformers (06). The flag is only "a critical facility is downstream"; names/coords stay out.
prio_path = OUT / "priority_nodes.csv"
critical_xf = set(pd.read_csv(prio_path, dtype=str)["node_id"]) if prio_path.exists() else set()


def protective_zone(node_id):
    """First fuse/recloser/breaker at or upstream of a node: the device that opens for a fault there.
    Mirrors 03_build_labels.protective_zone so line/pole assignment matches damage attribution."""
    cur = node_id
    while cur is not None and kind.get(cur) not in PROTECTIVE_KINDS:
        cur = parent.get(cur)
    return cur


def zone_members(root):
    """Every node in root's protective zone: walk down, stopping the descent at the next protective device
    (that device starts its own zone, so it isn't counted here, but root itself always is)."""
    members, q = [], deque([root])
    while q:
        n = q.popleft()
        members.append(n)
        for c in children.get(n, ()):
            if c == root or kind.get(c) not in PROTECTIVE_KINDS:   # don't cross into a nested protective zone
                q.append(c)
    return members


# ---- Zone membership counts, computed once per zone owner ----
protective = [n for n in nodes.node_id if kind.get(n) in PROTECTIVE_KINDS]
transformers = [n for n in nodes.node_id if kind.get(n) == "transformer"]
zone_of = {}            # node_id -> the protective device whose zone it falls in (for line/pole assignment)
zone_stats = {}         # owner -> {customers, transformers, downstream_devices, members}

for owner in protective:
    members = zone_members(owner)
    n_cust = sum(1 for m in members if kind.get(m) == "premise")
    n_xf = sum(1 for m in members if kind.get(m) == "transformer")
    n_dev = sum(1 for m in members if m != owner and kind.get(m) in PROTECTIVE_KINDS)  # always 0 by construction
    zone_stats[owner] = {"customers": n_cust, "transformers": n_xf, "downstream_devices": n_dev}
    for m in members:
        zone_of.setdefault(m, owner)

# Transformer rows: a small local zone (the transformer + whatever hangs directly off it, minus premises' homes).
for xf in transformers:
    kids = children.get(xf, [])
    n_cust = sum(1 for c in kids if kind.get(c) == "premise")
    zone_stats[xf] = {"customers": n_cust, "transformers": 1, "downstream_devices": 0}

# nested protective devices: count how many protective devices sit strictly below each protective owner
for owner in protective:
    cur = parent.get(owner)
    while cur is not None:
        if cur in zone_stats and kind.get(cur) in PROTECTIVE_KINDS:
            zone_stats[cur]["downstream_devices"] += 1
            break      # only the immediate upstream protective zone "contains" this device directly
        cur = parent.get(cur)


# ---- Spatial: assign primary line length and poles to protective zones (03's rule) ----
def _xf_points(crs):
    """Transformers with coordinates, as a metric GeoDataFrame, for nearest-device joins."""
    xf = nodes[(nodes.kind == "transformer") & nodes.lat.notna()].copy()
    g = gpd.GeoDataFrame(xf[["node_id", "circuit_id"]],
                         geometry=gpd.points_from_xy(xf.lon, xf.lat), crs=4326).to_crs(crs)
    return g


xf_pts = _xf_points(METRIC_CRS)
line_km_by_zone = defaultdict(float)
poles_by_zone = defaultdict(int)

# Primary lines: match each segment to the nearest transformer ON THE SAME CIRCUIT, then to its zone.
lines = gpd.read_file(PRIMARY, columns=["circuit_id"]).to_crs(METRIC_CRS)
lines["seg_km"] = lines.geometry.length / 1000.0
lines["rep"] = lines.geometry.representative_point()      # a point guaranteed to lie on the segment
lines_pt = lines.set_geometry("rep")
for cid, grp in lines_pt.groupby(lines_pt["circuit_id"].astype(str)):
    cand = xf_pts[xf_pts.circuit_id == cid][["node_id", "geometry"]]
    if cand.empty:
        continue
    j = gpd.sjoin_nearest(grp[["seg_km", "rep"]].set_geometry("rep"), cand,
                          max_distance=LINE_MAX_DIST_M, distance_col="dist_m")
    j = j[~j.index.duplicated()]
    for xf_id, km in zip(j.node_id, j.seg_km):
        z = zone_of.get(protective_zone(xf_id))
        if z is not None:
            line_km_by_zone[z] += float(km)

# Poles: no circuit_id, so match to the nearest transformer anywhere within LINE_MAX_DIST_M, then its zone.
poles = gpd.read_file(POLES, columns=[])[["geometry"]].to_crs(METRIC_CRS)
jp = gpd.sjoin_nearest(poles, xf_pts[["node_id", "geometry"]],
                       max_distance=LINE_MAX_DIST_M, distance_col="dist_m")
jp = jp[~jp.index.duplicated()]
for xf_id in jp.node_id:
    z = zone_of.get(protective_zone(xf_id))
    if z is not None:
        poles_by_zone[z] += 1

# ---- Assemble the one-row-per-zone table ----
ll = nodes.set_index("node_id")[["lat", "lon", "circuit_id"]]
rows = []
for owner, st in zone_stats.items():
    is_protective = kind.get(owner) in PROTECTIVE_KINDS
    members = None
    # `critical` = any critical transformer inside this zone (protective) or this transformer itself.
    if is_protective:
        members = zone_members(owner)
        crit = any(m in critical_xf for m in members)
    else:
        crit = owner in critical_xf
    rows.append({
        "device_id": owner,
        "kind": kind.get(owner),
        "circuit_id": ll.circuit_id.get(owner, ""),
        "lat": ll.lat.get(owner, np.nan),
        "lon": ll.lon.get(owner, np.nan),
        "n_customers": st["customers"],
        "n_transformers": st["transformers"],
        "n_downstream_devices": st["downstream_devices"],
        "n_poles": int(poles_by_zone.get(owner, 0)),
        "line_km": round(line_km_by_zone.get(owner, 0.0), 3),
        "fail_prob": round(float(fail_prob[owner]), 6) if owner in fail_prob else np.nan,
        "n_events_observed": int(n_events[owner]) if owner in n_events else np.nan,
        "critical": bool(crit),
    })

feat = pd.DataFrame(rows).sort_values(["kind", "circuit_id", "device_id"]).reset_index(drop=True)
OUT.mkdir(parents=True, exist_ok=True)
feat.to_csv(OUT / "device_features.csv", index=False)

# ---- Report ----
assigned_km = sum(line_km_by_zone.values())
total_km = float(lines["seg_km"].sum())
assigned_poles = sum(poles_by_zone.values())
total_poles = len(poles)
by_kind = feat.kind.value_counts().to_dict()
print(f"zones={len(feat)} by kind={by_kind}")
print(f"primary line assigned {assigned_km:.0f}/{total_km:.0f} km ({assigned_km / total_km:.0%}); "
      f"poles assigned {assigned_poles}/{total_poles} ({assigned_poles / total_poles:.0%})")
print(f"critical zones={int(feat.critical.sum())}  "
      f"median customers/zone (protective)="
      f"{int(feat[feat.kind.isin(PROTECTIVE_KINDS)].n_customers.median())}")
print(f"-> {OUT}/device_features.csv")
