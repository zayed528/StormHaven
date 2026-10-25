"""
Storm restoration planner API (utility view).   Owner: Akshat (engine) / Abby (console UI)
  GET /api/planner/storms          real storms that can be replayed, largest first
  GET /api/planner/plan?storm_id=&crews=&crew_size=&road_access=&workload=
  GET /api/planner/match?severity=   which real storm a severity percentile is like (no replay run: fast)
Every number is a model estimate for planning (labelled source: model_estimate). No equipment IDs, customer
IDs, coordinates, or facility identities are returned: equipment kind, counts and hours only.
Real AEP data only: on the synthetic network /storms and /plan answer {"available": false} and /match answers
{"storm_id": null, "label": null}.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.engines import planner
from app.schemas import AccessLevel

router = APIRouter(prefix="/api/planner", tags=["planner"])
# Customer-facing piece (the storm banner calls it before a home is chosen). Register it ALWAYS in main.py,
# not behind STORMHAVEN_ENABLE_OPERATOR_ROUTES: it returns only a storm id and month label.
customer_router = APIRouter(prefix="/api/planner", tags=["planner"])


@router.get("/storms")
def planner_storms():
    if not planner.available():
        return {"available": False, "storms": [],
                "reason": "Storm replay needs the real AEP data (run `make data`)."}
    return {"available": True, "storms": planner.storms()}


@customer_router.get("/match")
def planner_match(severity: float = Query(..., ge=0, le=100, description="storm severity percentile (0-100)")):
    """The real storm this severity is matched to: the same match the customer answer uses (replay_storm_id).
    {storm_id: null, label: null} for storms milder than any replayable one, and on the synthetic network."""
    ref = planner.match_storm(round(severity, 1))
    return {"storm_id": ref["storm_id"] if ref else None, "label": ref["label"] if ref else None}


@router.get("/plan")
def planner_plan(storm_id: str,
                 crews: int = Query(20, ge=1, le=500, description="line crews working the storm"),
                 crew_size: int = Query(3, ge=2, le=8, description="people per crew (AEP guide: 2-8)"),
                 road_access: AccessLevel = AccessLevel.normal,
                 workload: float = Query(1.0, ge=0.5, le=3.0, description="scale the storm's damage (1 = as recorded)")):
    if not planner.available():
        return {"available": False, "reason": "Storm replay needs the real AEP data (run `make data`)."}
    if storm_id not in {s["storm_id"] for s in planner.storms()}:
        raise HTTPException(status_code=404, detail="Unknown storm. See /api/planner/storms.")
    return planner.plan(storm_id, crews, crew_size, road_access.value, round(workload, 2))
