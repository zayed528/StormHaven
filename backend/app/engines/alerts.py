"""
ENGINE 4 — "Do I qualify for outage alerts?"   Owner: Nandan (rules + SNS) / Abby (copy)

Documented, deterministic rules (see config/assumptions.yaml -> alerts).
Messages come from templates; optional LLM polish happens in app/ai, then is re-scrubbed.
"""
from __future__ import annotations
from functools import lru_cache
import yaml

from app.config import ASSUMPTIONS, CONTENT_DIR
from app.core.privacy import scrub_text
from app.schemas import (AlertsResponse, Channel, CustomerProfile, Escalation, RestorationResponse,
                         RiskResponse, ScheduledAlert)

CFG = ASSUMPTIONS["alerts"]
# Band order for threshold checks; Unknown (fallback) counts as Moderate so we lean toward alerting.
BAND_RANK = {"Low": 0, "Moderate": 1, "High": 2, "Very High": 3, "Unknown": 1}


@lru_cache(maxsize=1)
def _templates() -> dict:
    """EN/ES message templates (content/message_templates.yaml), loaded once."""
    return yaml.safe_load((CONTENT_DIR / "message_templates.yaml").read_text())


def _short_range(rest: RestorationResponse) -> str:
    """SMS-length range: P10-P90 in hours, or in days once P90 reaches 48 h. Never a single time."""
    if rest.source == "fallback":
        return "unknown for now"
    lo, hi = rest.p10_hours, rest.p90_hours
    return f"{lo/24:.0f}-{hi/24:.0f} days" if hi >= 48 else f"{lo:.0f}-{hi:.0f} hours"


def build_alerts(risk: RiskResponse, rest: RestorationResponse, profile: CustomerProfile,
                 previous_range_text: str | None = None) -> AlertsResponse:
    """Public entry point (called by service.py): eligibility, schedule, escalations, and filled messages.
    previous_range_text = the range the customer saw last time; drives the 'estimate updated' message."""
    reasons, needs = [], {n.value for n in profile.declared_needs}
    priority_need = bool(needs & {"medical_device", "critical_facility"})
    # Each check can be switched off in assumptions.yaml (e.g. require_enrollment: false -> everyone counts).
    enrolled = profile.alerts_enrolled or not CFG["eligibility"]["require_enrollment"]
    has_channel = bool(profile.channels) or not CFG["eligibility"]["require_valid_channel"]
    risk_ok = BAND_RANK.get(risk.band, 1) >= BAND_RANK[CFG["eligibility"]["min_risk_band"]]

    # Plain-language reasons, shown to the customer so the eligibility decision is explainable.
    reasons.append("Enrolled in alerts." if enrolled else "Not enrolled in alerts yet — sign up to receive them.")
    reasons.append("Has a contact channel on file." if has_channel else "No phone or email on file.")
    reasons.append(f"Outage risk is {risk.band}"
                   + (" — meets the pre-storm alert threshold." if risk_ok else " — below the pre-storm threshold; you'll still get outage alerts."))
    if priority_need:
        reasons.append("Declared medical or critical-facility need: priority alerts and human follow-up.")

    eligible = enrolled and has_channel        # the documented rule; risk only affects WHICH alerts are sent
    rule = (f"Eligible if enrolled AND has a contact channel. Pre-storm alerts when risk ≥ "
            f"{CFG['eligibility']['min_risk_band']} or a medical/critical need is declared.")

    ch = profile.channels[0] if profile.channels else Channel.sms     # first channel the customer listed
    schedule = []
    # Pre-storm alerts only when risk is high enough OR a medical/critical need was declared.
    if eligible and (risk_ok or priority_need):
        for h in CFG["timing"]["pre_storm_hours_before"]:
            schedule.append(ScheduledAlert(trigger="pre_storm", timing=f"{h} hours before expected landfall", channel=ch))
    # Outage lifecycle alerts go to every eligible customer regardless of risk.
    if eligible:
        schedule += [
            ScheduledAlert(trigger="outage_confirmed",
                           timing=f"Within {CFG['timing']['outage_confirmed_within_minutes']} minutes of outage detection", channel=ch),
            ScheduledAlert(trigger="estimate_updated",
                           timing=f"When the estimate moves more than {CFG['timing']['estimate_update_threshold_hours']:.0f} hour", channel=ch),
            ScheduledAlert(trigger="restoration_complete", timing="When power is restored", channel=ch),
        ]

    # Escalations: situations where a human or 911 takes over. `active` = currently triggered.
    # ETR-missed and downed-line are listed but inactive here: they need live events (outage feed / chat).
    esc_cfg = CFG["escalation"]
    medical_long = "medical_device" in needs and rest.p50_hours > esc_cfg["medical_need_outage_hours"]
    escalations = [
        Escalation(trigger=f"Declared medical need and estimated outage > {esc_cfg['medical_need_outage_hours']} hrs",
                   action="Voice call + human agent follow-up; share nearest power/shelter options", active=medical_long),
        Escalation(trigger="Estimate missed by more than "
                           f"{esc_cfg['etr_missed_grace_hours']} hr", action="Proactive apology + new estimate + reason", active=False),
        Escalation(trigger="Customer reports a downed line", action="Show 911 + safety message immediately; route to emergency queue", active=False),
        Escalation(trigger="Model confidence Low or location unmatched", action="Fall back to area-level message; offer human contact",
                   active=risk.trust.confidence == "Low"),
    ]

    # Fill every template in the customer's language, scrub it, and hard-cap it at SMS length.
    t = _templates()[profile.language]
    fill = {"band": risk.band, "range_short": _short_range(rest),
            "old_range": previous_range_text or _short_range(rest),
            # TODO (Nandan/Abby, hour 14-18): use the actual input that changed, not the top hypothetical driver
            "reason": (rest.drivers[0].plain_language if rest.drivers else "updated field conditions").rstrip(".")}
    messages = {}
    for k, tpl in t.items():
        msg = scrub_text(tpl.format(**fill))
        messages[k] = msg[: CFG["sms_max_chars"]]
    return AlertsResponse(eligible=eligible, rule_applied=rule, reasons=reasons,
                          schedule=schedule, escalations=escalations, messages=messages)
