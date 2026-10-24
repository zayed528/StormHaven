"""
HOUR 6-9 (Jaid): GIS -> lightweight GeoJSON for the Plotly map.
 - Reproject to EPSG:4326 (Plotly needs lat/lon)
 - Simplify geometry so the browser stays fast
 - Priority locations: map each to the device that serves it -> priority_nodes.csv
   (used ONLY for restoration priority; coordinates never leave the backend)
STATUS: circuit + priority-location shapefiles not received yet -> names below are GUESSES (TODO).
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


CIRCUITS = RAW / "circuits.shp"; C_ID = "CIRCUIT_ID"             # TODO
PRIORITY = RAW / "priority_locations.shp"                        # TODO
_require(CIRCUITS, PRIORITY, OUT / "nodes.csv")

lines = gpd.read_file(CIRCUITS).to_crs(4326)
# Simplify: drop vertices within ~10 m of the line. Much smaller payload, no visible change at street zoom.
lines["geometry"] = lines.geometry.simplify(0.0001, preserve_topology=True)   # ~10 m
lines[[C_ID, "geometry"]].rename(columns={C_ID: "circuit_id"}).to_file(OUT / "circuits.geojson", driver="GeoJSON")

nodes = pd.read_csv(OUT / "nodes.csv", dtype=str)
# Facilities are served by local equipment, so match them to the nearest transformer or fuse.
dev = nodes[nodes.kind.isin(["transformer", "fuse"])].dropna(subset=["lat", "lon"])
dev = gpd.GeoDataFrame(dev, geometry=gpd.points_from_xy(dev.lon.astype(float), dev.lat.astype(float)), crs=4326)
prio = gpd.read_file(PRIORITY).to_crs(3857)
# Metres (EPSG:3857); facilities with no device within 500 m are left unmatched.
hit = gpd.sjoin_nearest(prio, dev.to_crs(3857)[["node_id", "geometry"]], max_distance=500)
# Write device IDs ONLY: facility names, types, and coordinates never leave this script.
hit[["node_id"]].drop_duplicates().to_csv(OUT / "priority_nodes.csv", index=False)
print(f"circuits={len(lines)}  priority facilities matched to devices={len(hit)}/{len(prio)}")
