"""
HOUR 3-6 (Jaid): upline TXT + GIS devices -> data/processed/edges.csv + nodes_base.csv
Fill COLS after reading recon_report.md. Output contract is in backend/app/core/data_loader.py.
STATUS: upline TXT and device shapefile not received yet -> every name below is a GUESS (TODO).
"""
import sys
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


# ---- TODO: set these from recon_report.md ----
UPLINE_FILE = RAW / "upline.txt"
UPLINE_SEP = "\t"                         # check: tab? comma? pipe?
COLS = {
    "premise": "PREMISE_ID",               # premise column in upline file
    "equipment": "EQUIP_ID",               # upline equipment column
    "order": "UPLINE_SEQ",                 # position on path (1 = nearest). None if file is parent->child pairs
    "equip_type": "EQUIP_TYPE",
    "circuit": "CIRCUIT_ID",
}
DEVICES_SHP = RAW / "protective_devices.shp"
DEV_COLS = {"id": "DEVICE_ID", "type": "DEVICE_TYPE", "circuit": "CIRCUIT_ID"}
KIND_MAP = {  # raw device type -> our kind
    "BREAKER": "breaker", "RECLOSER": "recloser", "FUSE": "fuse", "TRANSFORMER": "transformer",
    "SUBSTATION": "substation", "SECTIONALIZER": "recloser", "SWITCH": "recloser",
}
# ---------------------------------------------
_require(UPLINE_FILE, DEVICES_SHP)

# dtype=str keeps IDs like "00123" intact (no int conversion dropping leading zeros).
up = pd.read_csv(UPLINE_FILE, sep=UPLINE_SEP, dtype=str)
edges = []    # (parent_id, child_id) pairs, power flowing parent -> child
if COLS["order"]:
    # File lists each premise's full upline path with a sequence number -> chain consecutive items
    up["_seq"] = pd.to_numeric(up[COLS["order"]])
    for pid, grp in up.sort_values("_seq").groupby(COLS["premise"]):
        chain = [pid] + grp[COLS["equipment"]].tolist()          # premise, nearest, ..., substation
        edges += [(chain[i + 1], chain[i]) for i in range(len(chain) - 1)]   # parent -> child
else:
    # File is already parent -> child pairs (equipment feeds premise/equipment)
    edges = list(zip(up[COLS["equipment"]], up[COLS["premise"]]))
e = pd.DataFrame(edges, columns=["parent_id", "child_id"]).drop_duplicates()

# A radial network has ONE parent per node. Report violations rather than silently picking.
multi = e.groupby("child_id").size()
if (multi > 1).any():
    print(f"WARNING: {int((multi > 1).sum())} nodes have >1 parent (loops/ties). Keeping first; review!")
    e = e.drop_duplicates("child_id")
e.to_csv(OUT / "edges.csv", index=False)

# Node table: devices from GIS (kind + coords), premises from upline file
dev = gpd.read_file(DEVICES_SHP).to_crs(4326)       # EPSG:4326 = plain lat/lon, what Plotly needs
# Unknown device types default to "recloser" (a mid-line device). Check the recon report and extend KIND_MAP.
dev["kind"] = dev[DEV_COLS["type"]].str.upper().map(KIND_MAP).fillna("recloser")
nodes = pd.DataFrame({"node_id": dev[DEV_COLS["id"]].astype(str), "kind": dev["kind"],
                      "circuit_id": dev[DEV_COLS["circuit"]].astype(str),
                      "lat": dev.geometry.centroid.y, "lon": dev.geometry.centroid.x})
prem = up[[COLS["premise"], COLS["circuit"]]].drop_duplicates(COLS["premise"])
prem = pd.DataFrame({"node_id": prem[COLS["premise"]], "kind": "premise", "circuit_id": prem[COLS["circuit"]]})
# TODO: premise lat/lon — if not provided, place at its transformer's (masked) coordinate
nodes = pd.concat([nodes, prem], ignore_index=True).drop_duplicates("node_id")
# Sanity check: IDs used in edges but absent from the node table usually mean a join-key mismatch.
missing = (set(e.parent_id) | set(e.child_id)) - set(nodes.node_id)
print(f"edges={len(e)} nodes={len(nodes)} referenced-but-missing nodes={len(missing)}")
nodes.to_csv(OUT / "nodes_base.csv", index=False)
