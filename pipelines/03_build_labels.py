"""
HOUR 4-8 (Jaid + Akshat): ARCOS damage + topology -> per-device history and training labels.

Outputs:
  nodes.csv          nodes_base + fail_prob + n_events_observed   (risk engine v0 reads this)
  damage_mix.json    {kind: {damage_type: share}}                  (restoration engine)
  premise_event_labels.csv  premise_id, event_id, out(0/1)         (ML risk model v1)
  durations.csv      damage_id, event_id, node_id, damage_type, hours (backtesting)
  meta.json          {"n_events": N}

KEY IDEA: a premise was "out" in event E if ANY damage in E sits on its upline path.
That gives real positive AND negative labels from damage-only data.
STATUS: ARCOS shapefile not received yet -> every name below is a GUESS (TODO).
"""
import json
import sys
from pathlib import Path
import geopandas as gpd
import networkx as nx
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW, OUT = ROOT / "data" / "raw", ROOT / "data" / "processed"


def _require(*paths):
    """Exit cleanly (so `make pipelines` keeps going) when an input isn't there yet."""
    missing = [str(p.relative_to(ROOT)) for p in paths if not p.exists()]
    if missing:
        print(f"SKIP {Path(__file__).name}: missing {missing} (backend keeps using the synthetic fallback)")
        sys.exit(0)


ARCOS = RAW / "arcos_damage.shp"
# ---- TODO: set from recon_report.md ----
A = {"event": "EVENT_ID", "circuit": "CIRCUIT_ID", "damage_type": "DAMAGE_TYPE", "qty": "QUANTITY",
     "reported": "REPORT_TIME", "repaired": "REPAIR_DATE", "equipment": None}   # equipment col if ARCOS has one
# ARCOS damage-type text -> our damage_type keys. These MUST match config/assumptions.yaml
# restoration.repair_recipes / non_cu_hours (that's what labor_hours.csv is keyed on).
# e.g. {"POLE BROKEN": "broken_pole", "XFMR FAILED": "transformer_failed"}. Unmapped types keep their raw name
# and fall back to restoration.unknown_damage_type_hours.
DAMAGE_NAME_MAP = {}
# ----------------------------------------
_require(ARCOS, OUT / "nodes_base.csv", OUT / "edges.csv")

nodes = pd.read_csv(OUT / "nodes_base.csv", dtype={"node_id": str, "circuit_id": str})
edges = pd.read_csv(OUT / "edges.csv", dtype=str)
g = nx.DiGraph(); g.add_edges_from(edges.itertuples(index=False, name=None))
dmg = gpd.read_file(ARCOS).to_crs(4326)
dmg["event_id"] = dmg[A["event"]].astype(str)
dmg[A["damage_type"]] = dmg[A["damage_type"]].map(lambda x: DAMAGE_NAME_MAP.get(x, x))
n_events = dmg["event_id"].nunique()     # number of historical storms in the data

# 1) Attach each damage record to a device
if A["equipment"]:
    dmg["node_id"] = dmg[A["equipment"]].astype(str)
else:  # nearest device ON THE SAME CIRCUIT (masked coords -> approximate; document this assumption)
    # EPSG:3857 is in metres, so "nearest" means nearest on the ground (lat/lon degrees aren't equal distances).
    devs = nodes[nodes.kind != "premise"].dropna(subset=["lat", "lon"])
    dev_gdf = gpd.GeoDataFrame(devs, geometry=gpd.points_from_xy(devs.lon, devs.lat), crs=4326).to_crs(3857)
    parts = []
    for cid, grp in dmg.to_crs(3857).groupby(A["circuit"]):
        cand = dev_gdf[dev_gdf.circuit_id == str(cid)]
        if cand.empty:
            continue
        parts.append(gpd.sjoin_nearest(grp, cand[["node_id", "geometry"]], how="left"))
    dmg = pd.concat(parts).drop(columns="index_right", errors="ignore")
print(f"damage records matched to devices: {dmg.node_id.notna().mean():.0%}")

# 2) Per-device storm history
hit = dmg.dropna(subset=["node_id"]).groupby("node_id")["event_id"].nunique()
# hit = in how many distinct storms each device had at least one damage record
nodes["n_events_observed"] = n_events                        # every device "experienced" every event in the data
# NOTE (Akshat): this makes confidence identical for every premise; consider per-circuit event coverage.
nodes["fail_prob"] = nodes.node_id.map(hit).fillna(0) / n_events
# Smooth zeros toward a small prior so no device is "never fails" (empirical Bayes-lite)
# = (hits + 0.5 pseudo-storms at a 2% prior) / (storms + 0.5). TODO: read the prior from assumptions.yaml.
nodes["fail_prob"] = (nodes.fail_prob * n_events + 0.5 * 0.02) / (n_events + 0.5)
nodes.to_csv(OUT / "nodes.csv", index=False)

# 3) Damage-type mix by device kind
kind = nodes.set_index("node_id").kind
dmg["kind"] = dmg.node_id.map(kind)
# share of each damage type within each device kind, e.g. {"fuse": {"fuse_blown": 0.4, ...}}
mix = (dmg.groupby(["kind", A["damage_type"]]).size() / dmg.groupby("kind").size()).round(3)
(OUT / "damage_mix.json").write_text(json.dumps(
    {k: mix.loc[k].to_dict() for k in mix.index.get_level_values(0).unique()}, indent=1))

# 4) Premise x event labels via upline paths
damaged_by_event = dmg.dropna(subset=["node_id"]).groupby("event_id")["node_id"].apply(set).to_dict()
premises = nodes[nodes.kind == "premise"].node_id
rows = []
# premises x events rows: fine for a few thousand premises; vectorize if it gets slow.
for p in premises:
    path = set(nx.ancestors(g, p)) if p in g else set()      # every device upstream of this premise
    for ev, dset in damaged_by_event.items():
        rows.append((p, ev, int(bool(path & dset))))
pd.DataFrame(rows, columns=["premise_id", "event_id", "out"]).to_csv(OUT / "premise_event_labels.csv", index=False)

# 5) Actual durations for backtesting restoration ranges
# Report -> repair time per damage record (hours). Bad or missing timestamps become NaN; drop them in 05.
dmg["hours"] = (pd.to_datetime(dmg[A["repaired"]]) - pd.to_datetime(dmg[A["reported"]])).dt.total_seconds() / 3600
dmg[["event_id", "node_id", A["damage_type"], "hours"]].to_csv(OUT / "durations.csv", index=False)
(OUT / "meta.json").write_text(json.dumps({"n_events": int(n_events)}))
print(f"events={n_events}  label rows={len(rows)}  positive rate={pd.Series([r[2] for r in rows]).mean():.1%}")
