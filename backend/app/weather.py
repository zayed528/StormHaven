"""
Weather context for the UI.   Owner: Nandan (live calls) / Akshat (reference data)
 - reference storms: real past storms with their severity percentile and weather (labels the severity slider)
 - live forecast: next 3 days for the service area (Open-Meteo) + active National Weather Service alerts
Weather NEVER changes a risk or restoration number: with 36 recorded storms it can't size a storm reliably
(pipelines/07 docstring, docs/ASSUMPTIONS.md). It tells the customer what the scenario looks like in real life.

Live calls: no API keys. Only coarse ~10 km cell centres are sent to Open-Meteo / NWS. Results are cached for
30 minutes; any failure returns {"available": false} so the app never breaks. STORMHAVEN_OFFLINE=1 disables
outbound calls (tests, offline demos).
"""
from __future__ import annotations
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from functools import lru_cache
from statistics import median

import pandas as pd

from app.config import DATA_PROCESSED
from app.core.data_loader import get_store
from app.core.privacy import scrub_text

FORECAST_API = "https://api.open-meteo.com/v1/forecast"
NWS_ALERTS_API = "https://api.weather.gov/alerts/active"
USER_AGENT = "StormHaven HackOHI/O 2026 student project"     # NWS requires an identifying User-Agent
CREDIT = "Weather data by Open-Meteo.com; alerts from the National Weather Service."
TTL_S, FAIL_TTL_S, TIMEOUT_S = 1800, 120, 6
_cache: dict = {"at": 0.0, "ttl": 0, "value": None}


@lru_cache(maxsize=1)
def _reference() -> dict | None:
    """Reference storms + damage odds from pipelines/07, or None (synthetic network / 07 not run)."""
    path = DATA_PROCESSED / "weather_reference.json"
    if get_store().is_synthetic or not path.exists():
        return None
    return json.loads(path.read_text())


@lru_cache(maxsize=1)
def _cells() -> list[tuple[float, float, int]]:
    """(lat, lon, transformers) for each ~10 km weather cell over the service area."""
    c = pd.read_csv(DATA_PROCESSED / "weather_cells.csv")
    return list(zip(c.lat, c.lon, c.n_transformers))


def _get_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/geo+json, application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
        return json.load(r)


def _odds(gust: float, table: list[dict]) -> float | None:
    """Share of past days with this much wind that brought any damage report (from pipelines/07)."""
    for row in table:
        if row["gust_from_mph"] <= gust < row["gust_to_mph"]:
            return row["share_with_damage"]
    return None


def _forecast(ref: dict) -> dict:
    cells = _cells()
    q = {"latitude": ",".join(f"{c[0]:.2f}" for c in cells), "longitude": ",".join(f"{c[1]:.2f}" for c in cells),
         "daily": "wind_gusts_10m_max,precipitation_sum,snowfall_sum", "wind_speed_unit": "mph",
         "timezone": "America/New_York", "forecast_days": 3}
    data = _get_json(f"{FORECAST_API}?{urllib.parse.urlencode(q)}")
    data = data if isinstance(data, list) else [data]           # one location -> dict, several -> list
    days = []
    for i, date in enumerate(data[0]["daily"]["time"]):
        col = lambda k: [x["daily"][k][i] for x in data if x["daily"][k][i] is not None]   # noqa: E731
        gusts, rain, snow = col("wind_gusts_10m_max"), col("precipitation_sum"), col("snowfall_sum")
        if not gusts:
            continue
        g = float(median(gusts))      # same definition as the history: median across cells of daily max gust
        days.append({"date": date, "median_gust_mph": round(g), "peak_gust_mph": round(max(gusts)),
                     "rain_mm": round(sum(rain) / len(rain), 1) if rain else None,
                     "snow_cm": round(sum(snow) / len(snow), 1) if snow else None,
                     "share_past_days_with_damage": _odds(g, ref["damage_odds_by_gust"])})
    # Active NWS alerts at the service area's centre (weighted by transformers)
    w = sum(c[2] for c in cells)
    lat, lon = sum(c[0] * c[2] for c in cells) / w, sum(c[1] * c[2] for c in cells) / w
    try:
        feats = _get_json(f"{NWS_ALERTS_API}?point={lat:.3f},{lon:.3f}").get("features", [])
        seen, alerts = set(), []
        for f in feats:
            p = f.get("properties", {})
            key = (p.get("event"), p.get("headline"))
            if key not in seen:
                seen.add(key)
                alerts.append({"event": p.get("event"), "severity": p.get("severity"),
                               "headline": scrub_text(p.get("headline") or ""), "ends": p.get("ends")})
    except Exception:
        alerts = None                 # NWS unreachable: forecast still useful on its own
    return {"available": True, "days": days, "nws_alerts": alerts,
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def weather_context() -> dict:
    """Everything /api/weather returns. Reference data is static; the forecast is cached for 30 minutes."""
    ref = _reference()
    if ref is None:
        return {"reference_storms": [], "damage_odds_by_gust": [], "credit": CREDIT,
                "forecast": {"available": False, "reason": "Weather reference not built (synthetic network or "
                                                           "pipelines/07_weather.py not run)."}}
    if os.getenv("STORMHAVEN_OFFLINE") == "1":
        fc = {"available": False, "reason": "Offline mode."}
    elif _cache["value"] is not None and time.time() - _cache["at"] < _cache["ttl"]:
        fc = _cache["value"]
    else:
        try:
            fc, ttl = _forecast(ref), TTL_S
        except Exception:
            fc, ttl = {"available": False, "reason": "Forecast service unreachable right now."}, FAIL_TTL_S
        _cache.update(at=time.time(), ttl=ttl, value=fc)
    return {"reference_storms": ref["reference_storms"], "damage_odds_by_gust": ref["damage_odds_by_gust"],
            "credit": CREDIT, "forecast": fc}
