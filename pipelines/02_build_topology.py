"""
HOUR 3-6 (Jaid): AEP upline TXT + device shapefiles -> data/processed/edges.csv + nodes_base.csv
  python pipelines/02_build_topology.py
Output contract: backend/app/core/data_loader.py.

Upline file format (from recon, see docs/DATA_NOTES.md): tab-separated, no header, one line per premise:
  <premise_id> \\t <class>*<id>*<type>*<code> \\t <class>*<id>*<type>*<code> ...
ordered NEAREST FIRST: distribution transformer, then fuses / reclosers / step transformers, ending at the
circuit breaker. The breaker's <code> (e.g. "0000027") is the circuit_id used across the GIS layers.

Privacy: Customer_Clip (addresses, names of roads, life-support flags) is deliberately NOT read.
Premises are placed at their transformer's coordinates, so no home location is ever stored.
"""
import sys
from collections import Counter, defaultdict
from pathlib import Path
import geopandas as gpd
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW, OUT = ROOT / "data" / "raw", ROOT / "data" / "processed"


def _require(*paths):
    """Exit cleanly (so `make pipelines` keeps going) when an input isn't there yet."""
    missing = [str(p.relative_to(ROOT)) for p in paths if not p.exists()]
    if missing:
        print(f"SKIP {Path(__file__).name}: missing {missing} (backend keeps using the synthetic fallback)")
        sys.exit(0)


# ---- Names read from recon_report.md ----
UPLINE_FILE = RAW / "matched_upstream.txt"
UPLINE_SEP, ELEM_SEP = "\t", "*"
# <type> field in the upline file -> (our node kind, short ID prefix)
TYPE_MAP = {
    "Distribution": ("transformer", "XF"),
    "Step": ("step_transformer", "ST"),
    "Fuse": ("fuse", "FU"),
    "Recloser (Hydraulic)": ("recloser", "RC"),
    "Recloser (Electronic)": ("recloser", "RC"),
    "Sectionalizer": ("recloser", "SC"),      # automatic line device; behaves like a recloser for our purposes
    "Circuit Breaker": ("breaker", "CB"),
}
# Device coordinates: (prefix, shapefile, join column in shapefile, which upline field to join on)
COORD_SOURCES = [
    ("XF", RAW / "Transformer_Clip.shp", "id", "id"),            # 25,300 / 25,302 match on id
    ("FU", RAW / "Fuse_Bank_Clip.shp", "id", "id"),              # ~98.5% on id ...
    ("FU", RAW / "Fuse_Bank_Clip.shp", "location_n", "code"),    # ... rest on location number
    ("RC", RAW / "Recloser_Bank_Clip.shp", "location_n", "code"),  # reclosers only match on location number
]
# Step transformers, the sectionalizer, and breakers have no point in any shapefile -> lat/lon left empty.
# ------------------------------------------
_require(UPLINE_FILE, *{src for _, src, _, _ in COORD_SOURCES})

# 1) Parse every premise's chain. Count each (child, parent) pair so ties can be resolved by majority.
pair_counts = Counter()
node_info = {}                                # node_id -> (kind, raw id, raw code)
node_circuits = defaultdict(Counter)          # node_id -> circuit codes seen on its chains
n_lines = 0
with open(UPLINE_FILE) as f:
    for line in f:
        parts = line.rstrip("\n").split(UPLINE_SEP)
        if len(parts) < 2:
            continue
        n_lines += 1
        premise = parts[0].strip()
        chain = [premise]
        for el in parts[1:]:
            _cls, raw_id, typ, code = el.split(ELEM_SEP)
            if typ not in TYPE_MAP:
                sys.exit(f"ERROR: unknown upline element type {typ!r}. Add it to TYPE_MAP.")
            kind, prefix = TYPE_MAP[typ]
            nid = f"{prefix}-{raw_id}"
            node_info[nid] = (kind, raw_id, code)
            chain.append(nid)
        circuit = node_info[chain[-1]][2]     # the breaker's code = circuit_id
        node_info[premise] = ("premise", premise, "")
        for child, parent in zip(chain, chain[1:]):
            pair_counts[(child, parent)] += 1
        for nid in chain:
            node_circuits[nid][circuit] += 1

# 2) One parent per node (radial network). Keep the parent seen on the most premise chains.
best_parent = {}
for (child, parent), c in pair_counts.items():
    if child not in best_parent or c > pair_counts[(child, best_parent[child])]:
        best_parent[child] = parent
multi = Counter(ch for (ch, _p) in pair_counts)
n_multi = sum(1 for v in multi.values() if v > 1)
edges = pd.DataFrame([(p, c) for c, p in best_parent.items()], columns=["parent_id", "child_id"])

# Guard: following parents must always reach a breaker (no cycles introduced by the majority rule).
roots = {n for n in node_info if n not in best_parent}
for n in node_info:
    seen, cur = set(), n
    while cur in best_parent:
        if cur in seen:
            sys.exit(f"ERROR: cycle in topology at {cur}")
        seen.add(cur)
        cur = best_parent[cur]
bad_roots = [r for r in roots if node_info[r][0] != "breaker"]
if bad_roots:
    sys.exit(f"ERROR: {len(bad_roots)} chains end somewhere other than a circuit breaker, e.g. {bad_roots[:3]}")

# 3) Node table with coordinates
nodes = pd.DataFrame([{"node_id": n, "kind": k, "raw_id": rid, "code": code,
                       "circuit_id": node_circuits[n].most_common(1)[0][0]}
                      for n, (k, rid, code) in node_info.items()])
nodes["lat"], nodes["lon"] = float("nan"), float("nan")
for prefix, shp, shp_col, up_field in COORD_SOURCES:
    pts = gpd.read_file(shp, columns=[shp_col]).to_crs(4326)
    pts = pts.drop_duplicates(shp_col)
    lookup = dict(zip(pts[shp_col].astype(str), zip(pts.geometry.y, pts.geometry.x)))
    want = nodes.node_id.str.startswith(prefix + "-") & nodes.lat.isna()
    key = nodes.loc[want, "raw_id" if up_field == "id" else "code"]
    hits = key.map(lookup)
    found = hits.notna()
    nodes.loc[hits[found].index, "lat"] = [ll[0] for ll in hits[found]]
    nodes.loc[hits[found].index, "lon"] = [ll[1] for ll in hits[found]]
    print(f"coords {prefix} via {shp.name}.{shp_col}: {int(found.sum())} matched")

# Premises sit at their transformer (privacy blur: no home-level coordinates exist anywhere downstream).
xf_ll = nodes.set_index("node_id")[["lat", "lon"]]
prem = nodes.kind == "premise"
prem_parent = nodes.loc[prem, "node_id"].map(best_parent)
nodes.loc[prem, "lat"] = prem_parent.map(xf_ll.lat).values
nodes.loc[prem, "lon"] = prem_parent.map(xf_ll.lon).values

OUT.mkdir(parents=True, exist_ok=True)
edges.to_csv(OUT / "edges.csv", index=False)
nodes[["node_id", "kind", "circuit_id", "lat", "lon"]].to_csv(OUT / "nodes_base.csv", index=False)

# 4) Report
print(f"premise lines={n_lines}  nodes={len(nodes)}  edges={len(edges)}  circuits={len(roots)}")
print(f"nodes with >1 parent in the file (resolved by majority): {n_multi}")
print("nodes by kind:", nodes.kind.value_counts().to_dict())
no_xy = nodes[nodes.lat.isna()].kind.value_counts().to_dict()
print("nodes without coordinates by kind:", no_xy)
print(f"-> {OUT}/edges.csv, nodes_base.csv")
