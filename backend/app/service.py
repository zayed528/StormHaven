"""Orchestrates the 4 engines in order. One call = the whole customer answer.
Shared file: announce in team chat before changing it."""
from __future__ import annotations
from app.core.audit import log_prediction
from app.core.data_loader import get_store
from app.core.privacy import scrub_response
from app.core.topology import map_point_for
from app.engines.alerts import build_alerts, short_range
from app.engines.guidance import build_guidance
from app.engines.restoration import estimate_restoration
from app.engines.risk import assess_risk
from app.schemas import ConciergeRequest, ConciergeResponse


def run_concierge(req: ConciergeRequest) -> ConciergeResponse:
    """Order matters: risk feeds restoration (same path), and both feed guidance and alerts."""
    store = get_store()
    risk, path_risk = assess_risk(store, req.premise_id, req.circuit_id, req.scenario)
    confirmed = bool(req.utility_status and req.utility_status.outage_confirmed)
    rest = estimate_restoration(store, path_risk, req.scenario, risk.trust.confidence, outage_confirmed=confirmed)
    # Confirmed facts come ONLY from the utility feed (simulated in the demo), never from the model.
    rest.outage_confirmed = confirmed
    rest.confirmed_etr = req.utility_status.confirmed_etr if confirmed else None
    rest.range_short = short_range(rest, req.profile.language)   # the UI echoes this back as previous_range_text
    guide = build_guidance(risk, rest, req.profile)
    alerts = build_alerts(risk, rest, req.profile, req.previous_range_text, req.scenario, req.previous_scenario)
    body = {"risk": risk, "restoration": rest, "guidance": guide, "alerts": alerts}
    # Which map dot is this? The dot is the premise's transformer (its ID is already public on the map).
    map_point = map_point_for(store, path_risk.path[0]) if path_risk.path else None
    # Log the full request and a summary of the answer, so any prediction can be reproduced later.
    audit_id = log_prediction(req.model_dump(mode="json"),
                              {"band": risk.band, "p": risk.probability,
                               "p10": rest.p10_hours, "p90": rest.p90_hours,
                               "confidence": risk.trust.confidence, "eligible": alerts.eligible})
    # Final privacy pass over every string in the response, whichever engine produced it.
    return scrub_response(ConciergeResponse(**body, audit_id=audit_id, map_point_id=map_point))
