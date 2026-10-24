"""Orchestrates the 4 engines in order. One call = the whole customer answer.
Shared file: announce in team chat before changing it."""
from __future__ import annotations
from app.core.audit import log_prediction
from app.core.data_loader import get_store
from app.core.privacy import scrub_response
from app.engines.alerts import build_alerts
from app.engines.guidance import build_guidance
from app.engines.restoration import estimate_restoration
from app.engines.risk import assess_risk
from app.schemas import ConciergeRequest, ConciergeResponse


def run_concierge(req: ConciergeRequest) -> ConciergeResponse:
    """Order matters: risk feeds restoration (same path), and both feed guidance and alerts."""
    store = get_store()
    risk, path_risk = assess_risk(store, req.premise_id, req.circuit_id, req.scenario)
    rest = estimate_restoration(store, path_risk, req.scenario, risk.trust.confidence)
    # Confirmed facts come ONLY from the utility feed (simulated in the demo), never from the model.
    if req.utility_status:
        rest.outage_confirmed = req.utility_status.outage_confirmed
        rest.confirmed_etr = req.utility_status.confirmed_etr if req.utility_status.outage_confirmed else None
    guide = build_guidance(risk, rest, req.profile)
    alerts = build_alerts(risk, rest, req.profile, req.previous_range_text)
    body = {"risk": risk, "restoration": rest, "guidance": guide, "alerts": alerts}
    # Log the full request and a summary of the answer, so any prediction can be reproduced later.
    audit_id = log_prediction(req.model_dump(mode="json"),
                              {"band": risk.band, "p": risk.probability,
                               "p10": rest.p10_hours, "p90": rest.p90_hours,
                               "confidence": risk.trust.confidence, "eligible": alerts.eligible})
    # Final privacy pass over every string in the response, whichever engine produced it.
    return scrub_response(ConciergeResponse(**body, audit_id=audit_id))
