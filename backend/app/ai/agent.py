"""
StormHaven chat agent: the LLM orchestrates, the engines compute.   Owner: Nandan
Bedrock Converse API with one tool that calls the full engine pipeline.
Emergency keywords get a fixed 911 safety message first, with or without Bedrock.
"""
from __future__ import annotations
import os
import re

from app.ai.bedrock_client import get_client, guardrail_config
from app.ai.prompts import SAFETY_911, SYSTEM_PROMPT
from app.core.privacy import llm_payload, scrub_text
from app.schemas import ConciergeRequest, CustomerProfile, StormScenario
from app.service import run_concierge

# The ONE tool the LLM can call. It may only change the scenario knobs below; location and profile
# come from the request, so the model can't look up someone else's premise.
TOOLS = {"tools": [{"toolSpec": {
    "name": "get_outage_outlook",
    "description": "Outage risk, restoration range, preparation guidance, and alert eligibility for the customer's location under a storm scenario.",
    "inputSchema": {"json": {
        "type": "object",
        "properties": {
            "severity_percentile": {"type": "number", "description": "0-100, storm strength vs. history"},
            "crews_available": {"type": "integer"},
            "road_access": {"type": "string", "enum": ["normal", "limited", "blocked"]},
        },
    }},
}}]}

# Deliberately broad: a false alarm costs one extra safety line, a miss could cost a life.
_EMERGENCY = re.compile(r"\b(down(ed)?|fallen)\s+(power\s+)?(line|wire)s?\b|\bspark|\bfire\b|\bsmoke\b|"
                        r"\bshock|\bemergency\b|\b911\b|can'?t breathe", re.I)


def _is_emergency(history: list[dict]) -> bool:
    """True if the customer's LATEST message looks like an emergency (downed line, fire, medical...)."""
    last_user = next((m for m in reversed(history) if m.get("role") == "user"), None)
    text = " ".join(c.get("text", "") for c in (last_user or {}).get("content", []) if isinstance(c, dict))
    return bool(_EMERGENCY.search(text))


def _flatten_for_llm(resp) -> dict:
    """Derived, allowlisted fields only. No IDs, no coordinates."""
    d = {
        "band": resp.risk.band, "probability": resp.risk.probability,
        "confidence": resp.risk.trust.confidence,
        "factors": [f.plain_language for f in resp.risk.factors],
        "p10_hours": resp.restoration.p10_hours, "p50_hours": resp.restoration.p50_hours,
        "p90_hours": resp.restoration.p90_hours,
        "drivers": [d.plain_language for d in resp.restoration.drivers],
        "steps": [s.description for s in resp.restoration.steps],
        "eligible": resp.alerts.eligible,
        "assumptions": resp.risk.trust.assumptions + resp.restoration.trust.assumptions,
        "missing_data": resp.risk.trust.missing_data,
        "declared_needs": [],  # filled below
        "guidance": [g.text for g in resp.guidance.safety + resp.guidance.actions],   # curated library text
    }
    return llm_payload(d)


def chat(history: list[dict], premise_id: str | None, circuit_id: str | None,
         base_scenario: StormScenario, profile: CustomerProfile) -> str:
    """history: [{"role": "user"|"assistant", "content": [{"text": "..."}]}, ...]
    The 911 message is prepended in code, not by the LLM, so it appears even if Bedrock is down or misbehaves."""
    reply = _answer(history, premise_id, circuit_id, base_scenario, profile)
    return f"{SAFETY_911}\n\n{reply}" if _is_emergency(history) else reply


def _answer(history, premise_id, circuit_id, base_scenario, profile) -> str:
    """Bedrock tool-use loop: model asks for the tool -> we run the engines -> model explains the result."""
    client = get_client()
    if client is None:
        return _offline_reply(premise_id, circuit_id, base_scenario, profile)

    messages = list(history)
    # Low temperature: we want consistent, factual explanations, not creativity.
    kwargs = {"modelId": os.environ["BEDROCK_MODEL_ID"], "system": [{"text": SYSTEM_PROMPT}],
              "toolConfig": TOOLS, "inferenceConfig": {"maxTokens": 600, "temperature": 0.2}}
    if (gr := guardrail_config()):
        kwargs["guardrailConfig"] = gr

    for _ in range(4):                                  # max tool rounds (stops runaway loops)
        out = client.converse(messages=messages, **kwargs)
        msg = out["output"]["message"]
        messages.append(msg)
        if out.get("stopReason") != "tool_use":          # model is done -> scrub its text and return it
            text = "".join(c.get("text", "") for c in msg["content"])
            return scrub_text(text)
        # Model asked for the tool: run the real engines for each call and hand back the results.
        results = []
        for c in msg["content"]:
            if "toolUse" not in c:
                continue
            args = c["toolUse"].get("input", {}) or {}
            sc = StormScenario.model_validate({**base_scenario.model_dump(),
                                               **{k: v for k, v in args.items() if v is not None}})  # validates LLM input
            resp = run_concierge(ConciergeRequest(premise_id=premise_id, circuit_id=circuit_id,
                                                  scenario=sc, profile=profile))
            # Only allowlisted, derived fields go back to the model (no IDs, coordinates, or facility data).
            payload = _flatten_for_llm(resp)
            payload["declared_needs"] = [n.value for n in profile.declared_needs]
            results.append({"toolResult": {"toolUseId": c["toolUse"]["toolUseId"],
                                           "content": [{"json": payload}]}})
        messages.append({"role": "user", "content": results})   # Converse API: tool results go in a user turn
    # Out of rounds: fail safe with a pointer to official channels instead of a half answer.
    return "I'm having trouble answering right now. Please check AEP's outage map or contact AEP directly."


def _offline_reply(premise_id, circuit_id, sc, profile) -> str:
    """Deterministic answer when Bedrock isn't available — the demo never dies."""
    r = run_concierge(ConciergeRequest(premise_id=premise_id, circuit_id=circuit_id, scenario=sc, profile=profile))
    if r.risk.source == "fallback":
        return "I couldn't match your location to our data, so I can't make a reliable prediction. Please check AEP's official outage map."
    # Same facts the LLM would get, stitched into a fixed sentence template.
    top = r.risk.factors[0].plain_language if r.risk.factors else ""
    return scrub_text(f"Your outage risk is {r.risk.band} ({r.risk.trust.confidence} confidence). {top} "
                      f"{r.restoration.range_text} This is an estimate, not a confirmed AEP restoration time.")
