"""
HOUR 6-9 (Jaid): GIS -> lightweight map layers + priority-facility flags.
  python pipelines/06_export_map_layers.py
 - circuits.geojson: primary lines merged per circuit, reprojected to EPSG:4326, simplified (~10 m)
   (secondary lines are skipped: 127k segments add weight but no meaning at map zoom)
 - priority_nodes.csv: transformers that serve a hospital, fire station, or ambulance service.
   Used ONLY to raise restoration priority; facility names and coordinates never leave this script.
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


# ---- Names read from recon_report.md ----
PRIMARY = RAW / "Primary_ExportFeatures.shp"; C_ID = "circuit_id"
PRIORITY = [RAW / "Hospitals_Medic_Pairwis_Clip.shp", RAW / "Fire_Stations_E_Pairwis_Clip.shp",
            RAW / "Ambulance_Servi_Pairwis_Clip.shp"]          # CRS: Web Mercator + NAVD88 height (compound)
SIMPLIFY_DEG = 0.0001                       # ~10 m: invisible at street zoom, much smaller payload
PRIORITY_MAX_M = 500                        # facility -> nearest transformer within this distance (assumed)
# ------------------------------------------
_require(PRIMARY, *PRIORITY, OUT / "nodes.csv")

# 1) Circuit lines: only circuits that exist in our topology, merged into one geometry per circuit
nodes = pd.read_csv(OUT / "nodes.csv", dtype={"node_id": str, "circuit_id": str})
known = set(nodes.circuit_id.dropna())
lines = gpd.read_file(PRIMARY, columns=[C_ID]).to_crs(4326)
lines = lines[lines[C_ID].astype(str).isin(known)]
merged = lines.dissolve(by=C_ID).reset_index()
merged["geometry"] = merged.geometry.simplify(SIMPLIFY_DEG, preserve_topology=True)
merged = merged.rename(columns={C_ID: "circuit_id"})[["circuit_id", "geometry"]]
merged.to_file(OUT / "circuits.geojson", driver="GeoJSON")
size_mb = (OUT / "circuits.geojson").stat().st_size / 1e6

# 2) Priority facilities -> the transformer that most likely serves each one
xf = nodes[(nodes.kind == "transformer") & nodes.lat.notna()]
xf = gpd.GeoDataFrame(xf[["node_id"]], geometry=gpd.points_from_xy(xf.lon, xf.lat), crs=4326).to_crs(3857)
hits, total = [], 0
for shp in PRIORITY:
    fac = gpd.read_file(shp)[["geometry"]].to_crs(3857)     # drop every attribute (names, addresses)
    fac = gpd.GeoDataFrame(geometry=gpd.points_from_xy(fac.geometry.x, fac.geometry.y), crs=3857)  # 2D only
    total += len(fac)
    j = gpd.sjoin_nearest(fac, xf, max_distance=PRIORITY_MAX_M)
    j = j[~j.index.duplicated()]
    hits.append(j[["node_id"]])
    print(f"  {shp.stem}: {len(j)}/{len(fac)} matched to a transformer within {PRIORITY_MAX_M} m")
prio = pd.concat(hits).drop_duplicates()
prio.to_csv(OUT / "priority_nodes.csv", index=False)       # device IDs only
print(f"circuits={len(merged)} ({size_mb:.1f} MB)  priority facilities matched={sum(len(h) for h in hits)}/{total}"
      f"  -> {len(prio)} flagged transformers")
print(f"-> {OUT}/circuits.geojson, priority_nodes.csv")
