"""
Storm restoration planner API (utility view).   Owner: Akshat (engine) / Abby (console UI)
  GET /api/planner/storms          real storms that can be replayed, largest first
  GET /api/planner/plan?storm_id=&crews=&crew_size=&road_access=&workload=
Every number is a model estimate for planning (labelled source: model_estimate). No equipment IDs, customer
IDs, coordinates, or facility identities are returned: equipment kind, counts and hours only.
Real AEP data only; on the synthetic network both endpoints answer {"available": false}.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.engines import planner
from app.schemas import AccessLevel

router = APIRouter(prefix="/api/planner", tags=["planner"])


@router.get("/storms")
def planner_storms():
    if not planner.available():
        return {"available": False, "storms": [],
                "reason": "Storm replay needs the real AEP data (run `make data`)."}
    return {"available": True, "storms": planner.storms()}


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
