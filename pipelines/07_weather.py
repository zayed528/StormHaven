"""
HOUR 9-14 (Akshat): open weather data -> storm weather features.
  python pipelines/07_weather.py
Source: Open-Meteo Historical Weather API (archive-api.open-meteo.com), free, no key, CC BY 4.0
-> credit "Weather data by Open-Meteo.com" on the slides.

Locations: the service area split into 0.1-degree cells (~10 km, about the weather model's resolution); each cell's
point is the mean location of the transformers in it. Only cell centres leave this machine (no AEP IDs).
Daily series per cell over the whole ARCOS period are cached in data/processed/weather_cache/ so re-runs don't
call the API again. First run takes ~5 minutes (requests are paced to respect Open-Meteo's per-minute limit).

Outputs:
  weather_cells.csv     cell_id, lat, lon, n_transformers
  weather_daily.csv     date, cell_id, gust_max_mph, wind_max_mph, precip_mm, snow_cm
  weather_events.csv    one row per ARCOS storm: dates, records, territory weather (peak gust etc.)
  weather_reference.json  served by /api/weather: notable storms with their severity percentile + weather
                        (labels the severity slider), and how often past days of a given wind brought damage.

What the data showed (see docs/ASSUMPTIONS.md): weather tells you WHETHER damage is likely (any damage on 2% of
days under 30 mph gusts, ~20% at 40-50 mph) but, with 36 storms, cannot predict HOW MUCH: a leave-one-storm-out
Poisson model on gusts barely beats "a typical storm" and predicts ~10-20 records for the Feb 2025 storm (actual
1,244). So weather labels and contextualizes the severity scenario; it does not set it.
"""
import json
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "processed"
CACHE = OUT / "weather_cache"


def _require(*paths):
    """Exit cleanly (so `make pipelines` keeps going) when an input isn't there yet."""
    missing = [str(p.relative_to(ROOT)) for p in paths if not p.exists()]
    if missing:
        print(f"SKIP {Path(__file__).name}: missing {missing} (backend keeps using the synthetic fallback)")
        sys.exit(0)


API = "https://archive-api.open-meteo.com/v1/archive"
DAILY = ["wind_gusts_10m_max", "wind_speed_10m_max", "precipitation_sum", "snowfall_sum"]
RENAME = {"wind_gusts_10m_max": "gust_max_mph", "wind_speed_10m_max": "wind_max_mph",
          "precipitation_sum": "precip_mm", "snowfall_sum": "snow_cm"}
CELL_DEG = 0.1
REFERENCE_MIN_RECORDS = 10       # storms big enough to label the slider with
REPORT_LAG_DAYS = 2              # ARCOS reports trail the weather by up to ~2 days
GUST_BINS = [0, 30, 40, 200]     # median-cell daily gust (mph) bins for the damage-odds table
PAD_DAYS = 7                      # pull a week either side of the ARCOS period (antecedent rain, margins)
PAUSE_S = 12                      # ~100 call-units per request; keeps us well under 600 units/minute
USER_AGENT = "StormHaven HackOHI/O 2026 student project"

_require(OUT / "nodes_base.csv", OUT / "meta.json", OUT / "damage_attributed.csv")
meta = json.loads((OUT / "meta.json").read_text())
if "events" not in meta:
    sys.exit("ERROR: meta.json has no 'events'; re-run pipelines/03_build_labels.py")

# 1) Weather cells over the service area
nodes = pd.read_csv(OUT / "nodes_base.csv", dtype={"node_id": str, "circuit_id": str})
xf = nodes[(nodes.kind == "transformer") & nodes.lat.notna()].copy()
xf["cell_id"] = ("C" + ((xf.lat / CELL_DEG).round().astype(int)).astype(str) + "_"
                 + ((xf.lon / CELL_DEG).round().astype(int)).astype(str))
cells = xf.groupby("cell_id").agg(lat=("lat", "mean"), lon=("lon", "mean"), n_transformers=("node_id", "size"))
cells = cells.round({"lat": 4, "lon": 4}).reset_index()
cells.to_csv(OUT / "weather_cells.csv", index=False)

start = (pd.Timestamp(meta["date_range"][0]) - pd.Timedelta(days=PAD_DAYS)).strftime("%Y-%m-%d")
end = (pd.Timestamp(meta["date_range"][1]) + pd.Timedelta(days=PAD_DAYS)).strftime("%Y-%m-%d")

# 2) Daily weather per cell (cached)
CACHE.mkdir(parents=True, exist_ok=True)
frames, fetched = [], 0
for c in cells.itertuples():
    f = CACHE / f"{c.cell_id}_{start}_{end}.json"
    if not f.exists():
        url = (f"{API}?latitude={c.lat}&longitude={c.lon}&start_date={start}&end_date={end}"
               f"&daily={','.join(DAILY)}&wind_speed_unit=mph&timezone=America%2FNew_York")
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    f.write_text(r.read().decode())
                break
            except Exception as e:                       # 429 / transient network: back off and retry
                if attempt == 3:
                    sys.exit(f"ERROR fetching weather for {c.cell_id}: {e}")
                time.sleep(30 * (attempt + 1))
        fetched += 1
        print(f"  fetched {c.cell_id} ({fetched} new)", flush=True)
        time.sleep(PAUSE_S)
    d = json.loads(f.read_text())["daily"]
    df = pd.DataFrame(d).rename(columns={"time": "date", **RENAME})
    df["cell_id"] = c.cell_id
    frames.append(df)
daily = pd.concat(frames, ignore_index=True)[["date", "cell_id", *RENAME.values()]]
daily.to_csv(OUT / "weather_daily.csv", index=False)

# 3) Territory weather per ARCOS storm: worst cell on the worst day, plus totals over the storm
w = daily.copy()
w["date"] = pd.to_datetime(w["date"])
rows = []
for ev, e in meta["events"].items():
    s, t = pd.Timestamp(e["start"]), pd.Timestamp(e["end"])
    win = w[(w.date >= s - pd.Timedelta(days=1)) & (w.date <= t)]      # include the day before the first report
    per_cell = win.groupby("cell_id").agg(gust=("gust_max_mph", "max"), precip=("precip_mm", "sum"),
                                         snow=("snow_cm", "sum"))
    prior = w[(w.date >= s - pd.Timedelta(days=4)) & (w.date < s - pd.Timedelta(days=1))]
    rows.append({"event_id": ev, "start": e["start"], "end": e["end"], "records": e["records"],
                 "peak_gust_mph": round(float(per_cell.gust.max()), 1),
                 "median_cell_gust_mph": round(float(per_cell.gust.median()), 1),
                 "precip_mm": round(float(per_cell.precip.mean()), 1),
                 "snow_cm": round(float(per_cell.snow.mean()), 1),
                 "prior3d_precip_mm": round(float(prior.groupby("cell_id").precip_mm.sum().mean()), 1)})
events = pd.DataFrame(rows).sort_values("records", ascending=False)
# Severity percentile of each storm, computed exactly as 03 does (rank of records among all storms)
events["percentile"] = ((events.records.rank(method="average") - 0.5) / len(events) * 100).round(1)
events.to_csv(OUT / "weather_events.csv", index=False)

# 4) Reference file for the app
ref = events[events.records >= REFERENCE_MIN_RECORDS].sort_values("percentile")
storms = [{"label": pd.Timestamp(r.start).strftime("%b %Y"), "start": r.start, "end": r.end,
           "percentile": float(r.percentile), "peak_gust_mph": float(r.peak_gust_mph),
           "rain_mm": float(r.precip_mm), "snow_cm": float(r.snow_cm)} for r in ref.itertuples()]
# How often a day with this much wind (median cell) was followed by ANY damage report within REPORT_LAG_DAYS
att = pd.read_csv(OUT / "damage_attributed.csv", parse_dates=["report_day"])
day = w.groupby("date").gust_max_mph.median().rename("gust").to_frame()
reported = att.groupby("report_day").size().reindex(day.index).fillna(0)
day["damage_soon"] = (reported[::-1].rolling(REPORT_LAG_DAYS + 1, min_periods=1).sum()[::-1] > 0)
day = day.loc[meta["date_range"][0]:meta["date_range"][1]]
odds = []
for lo, hi in zip(GUST_BINS, GUST_BINS[1:]):
    sub = day[(day.gust >= lo) & (day.gust < hi)]
    odds.append({"gust_from_mph": lo, "gust_to_mph": hi, "days": int(len(sub)),
                 "share_with_damage": round(float(sub.damage_soon.mean()), 3) if len(sub) else None})
(OUT / "weather_reference.json").write_text(json.dumps(
    {"source": "Open-Meteo historical weather (ERA5-based), daily, 0.1-degree cells",
     "credit": "Weather data by Open-Meteo.com", "reference_storms": storms, "damage_odds_by_gust": odds,
     "gust_definition": "median across the service area's cells of each cell's daily max gust"}, indent=1))
print(f"cells={len(cells)}  days={daily.date.nunique()}  storms={len(events)}")
print(events.head(10).to_string(index=False))
print("damage odds by median-cell daily gust:", odds)
print(f"-> {OUT}/weather_cells.csv, weather_daily.csv, weather_events.csv, weather_reference.json")
