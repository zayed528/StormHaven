"""
POST /api/notify — send one proactive alert as an SMS.   Owner: Abby

Backs the "Send this alert as a text" buttons in the results panel. The customer never types the message:
the button names a message_key (pre_storm | outage_confirmed | estimate_updated | restoration_complete)
and the server REGENERATES that message from the engines, so the text sent is byte-identical to the text
on screen (and already privacy-scrubbed by the engine). We never send caller-supplied free text.

Flow: request -> run_concierge() -> pick alerts.messages[message_key] -> sns_sender.send_message()
      -> audit record for EVERY attempt (sent and dry-run) -> {sent, dry_run, text}.

Wiring (one line for Jaid in main.py, next to the other routers):
    from app.notify.router import router as notify_router   # noqa: E402
    app.include_router(notify_router)
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.core.audit import log_prediction
from app.notify.sns_sender import send_message
from app.schemas import CustomerProfile, SimulatedUtilityStatus, StormScenario
from app.service import run_concierge
from app.schemas import ConciergeRequest

router = APIRouter(prefix="/api", tags=["notify"])

# The only messages a button may send. Must match AlertsResponse.messages keys (build_alerts).
VALID_KEYS = {"pre_storm", "outage_confirmed", "estimate_updated", "restoration_complete"}


class NotifyRequest(BaseModel):
    """Mirror of the concierge request plus which message to send. Same fields the 'Send as text' button
    already passes (see frontend/src/api/client.js), so the server can rebuild the exact answer on screen."""
    message_key: str = Field(..., examples=["pre_storm"])
    premise_id: Optional[str] = None
    circuit_id: Optional[str] = None
    scenario: StormScenario = StormScenario()
    profile: CustomerProfile = CustomerProfile()
    previous_range_text: Optional[str] = None
    previous_scenario: Optional[StormScenario] = None
    utility_status: Optional[SimulatedUtilityStatus] = None


class NotifyResponse(BaseModel):
    """What the button renders. `sent`/`dry_run` come straight from sns_sender; `reason` explains a no-send."""
    sent: bool
    dry_run: bool
    text: Optional[str] = None       # the message actually sent (or that WOULD be sent in a dry run); None if refused
    reason: Optional[str] = None     # set when we deliberately don't send (bad key / not eligible)
    audit_id: Optional[str] = None


@router.post("/notify", response_model=NotifyResponse)
def notify(req: NotifyRequest) -> NotifyResponse:
    # Reject unknown message keys up front, so a typo can't silently send nothing (and can't be probed).
    if req.message_key not in VALID_KEYS:
        return NotifyResponse(sent=False, dry_run=False, reason=f"Unknown message_key '{req.message_key}'.")

    # Rebuild the full answer from the SAME engine the UI used. This regenerates alerts.messages, so the
    # text we send equals the text shown and is already scrubbed — we never trust client-supplied text.
    answer = run_concierge(ConciergeRequest(
        premise_id=req.premise_id, circuit_id=req.circuit_id, scenario=req.scenario, profile=req.profile,
        previous_range_text=req.previous_range_text, previous_scenario=req.previous_scenario,
        utility_status=req.utility_status))

    # Responsible-AI gate: only text customers who opted in (enrolled + have a channel). We don't message
    # someone who never asked to be messaged, even on a demo button.
    if not answer.alerts.eligible:
        return NotifyResponse(sent=False, dry_run=False,
                              reason="Customer isn't signed up for alerts (enroll + add a channel first).")

    text = answer.alerts.messages.get(req.message_key)
    if not text:
        # Eligible, but this particular message isn't available for the scenario (shouldn't normally happen).
        return NotifyResponse(sent=False, dry_run=False,
                              reason=f"No '{req.message_key}' message available for this scenario.")

    # Hand the ALREADY-scrubbed engine text to SNS. send_message scrubs + length-caps again (defense in depth)
    # and returns {sent, dry_run, message_id, text}. No topic configured -> dry run, nothing actually sent.
    result = send_message(text, trigger=req.message_key)

    # Audit EVERY attempt (sent and dry-run) so there's a record of what went to whom under what scenario.
    # Reuse the prediction audit log; the request carries declared needs, so treat the log as sensitive.
    audit_id = log_prediction(
        {"endpoint": "notify", "message_key": req.message_key, **req.model_dump(mode="json")},
        {"sent": result["sent"], "dry_run": result["dry_run"],
         "message_id": result.get("message_id"), "eligible": True})

    return NotifyResponse(sent=result["sent"], dry_run=result["dry_run"],
                          text=result["text"], audit_id=audit_id)
