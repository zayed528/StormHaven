"""
STEP 0 (everyone): unpack the committed data archives so the pipelines can run.
  make data            (unpacks, then runs every pipeline)
  python pipelines/00_unpack_data.py      (unpack only; works on Windows without make/unzip)

data/archives/ (committed, compressed) -> data/raw/ and data/processed/weather_cache/ (both git-ignored):
  aep_gis_shapefiles.zip   AEP GIS layers + ARCOS damage (Customer_Clip deliberately NOT included:
                           street addresses + life-support flags, and no pipeline uses it)
  aep_topology.zip         matched_upstream.txt (premise -> upstream equipment)
  *.xlsx, *.pdf            labor workbook, structure drawings
  weather_cache.zip        cached Open-Meteo responses, so 07_weather.py doesn't call the API again
Existing files are left alone, so re-running is safe.
"""
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARCHIVES, RAW, PROCESSED = ROOT / "data" / "archives", ROOT / "data" / "raw", ROOT / "data" / "processed"
# archive name -> folder it unpacks into
TARGETS = {"aep_gis_shapefiles.zip": RAW, "aep_topology.zip": RAW, "weather_cache.zip": PROCESSED}

if not ARCHIVES.exists():
    sys.exit("ERROR: data/archives/ not found. Run `git pull` first.")
RAW.mkdir(parents=True, exist_ok=True)
PROCESSED.mkdir(parents=True, exist_ok=True)

written = skipped = 0
for name, dest in TARGETS.items():
    path = ARCHIVES / name
    if not path.exists():
        print(f"  (missing {name}, skipped)")
        continue
    with zipfile.ZipFile(path) as z:
        for member in z.infolist():
            target = (dest / member.filename).resolve()
            if not target.is_relative_to(dest.resolve()):           # never write outside the target folder
                sys.exit(f"ERROR: unsafe path in {name}: {member.filename}")
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if target.exists():
                skipped += 1
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(member) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)
            written += 1

for f in list(ARCHIVES.glob("*.xlsx")) + list(ARCHIVES.glob("*.pdf")):
    if not (RAW / f.name).exists():
        shutil.copy2(f, RAW / f.name)
        written += 1
    else:
        skipped += 1

print(f"unpacked {written} files ({skipped} already present) -> data/raw/, data/processed/weather_cache/")
print("next: make pipelines   (or run pipelines/01..07 in order)")
