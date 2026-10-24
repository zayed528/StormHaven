"""
StormHaven chat agent: the LLM orchestrates, the engines compute.   Owner: Nandan
Bedrock Converse API with one tool that calls the full engine pipeline.
Emergency keywords get a fixed 911 safety message first, with or without Bedrock.
"""
from __future__ import annotations
import json
import logging
import os
import re

from app.ai.bedrock_client import get_client, guardrail_config
from app.ai.prompts import SAFETY_911, SYSTEM_PROMPT
from app.core.data_loader import get_store
from app.core.privacy import llm_payload, sanitize_chat_history, scrub_text
from app.schemas import (ConciergeRequest, CustomerProfile, SimulatedUtilityStatus,
                         StormScenario)
from app.service import run_concierge

logger = logging.getLogger(__name__)
_TOOL_NAME = "get_outage_outlook"
_ALLOWED_TOOL_ARGS = {"severity_percentile", "crews_available", "road_access"}
_ANSWER_TYPES = {"overview", "risk", "restoration", "why", "preparation", "alerts"}

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
        "additionalProperties": False,
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


def _flatten_for_llm(resp, profile: CustomerProfile, data_mode: str) -> dict:
    """Derived, allowlisted fields only. No IDs, no coordinates."""
    d = {
        "risk_source": resp.risk.source,
        "restoration_source": resp.restoration.source,
        "data_mode": data_mode,
        "outage_confirmed": resp.restoration.outage_confirmed,
        "confirmation_mode": "simulated_demo" if resp.restoration.outage_confirmed else "none",
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
        "declared_needs": [n.value for n in profile.declared_needs],
        "guidance": [g.text for g in resp.guidance.safety + resp.guidance.actions],   # curated library text
    }
    return llm_payload(d)


def chat(history: list[dict], premise_id: str | None, circuit_id: str | None,
         base_scenario: StormScenario, profile: CustomerProfile,
         utility_status: SimulatedUtilityStatus | None = None) -> str:
    """history: [{"role": "user"|"assistant", "content": [{"text": "..."}]}, ...]
    The 911 message is prepended in code, not by the LLM, so it appears even if Bedrock is down or misbehaves."""
    emergency = _is_emergency(history)
    safe_history = sanitize_chat_history(history)
    if not emergency and not _is_outage_question(history):
        try:
            return _conversational_answer(safe_history, profile.language)
        except Exception as exc:
            logger.warning("Bedrock conversation fell back safely (%s)", type(exc).__name__)
            return _conversation_fallback(profile.language)
    current = run_concierge(ConciergeRequest(premise_id=premise_id, circuit_id=circuit_id,
                                             scenario=base_scenario, profile=profile,
                                             utility_status=utility_status))
    data_mode = "synthetic" if get_store().is_synthetic else "real"
    current_payload = _flatten_for_llm(current, profile, data_mode)
    try:
        reply = _answer(safe_history, premise_id, circuit_id, base_scenario, profile,
                        utility_status, current, current_payload, data_mode)
    except Exception as exc:  # Bedrock, malformed output, and validation failures all fail closed.
        logger.warning("Bedrock chat fell back safely (%s)", type(exc).__name__)
        reply = _offline_reply(current, data_mode)
    return f"{SAFETY_911}\n\n{reply}" if emergency else reply


def _is_outage_question(history: list[dict]) -> bool:
    """Keep outage facts on the grounded engine path; everything else is conversational."""
    last_user = next((m for m in reversed(history) if m.get("role") == "user"), None)
    text = " ".join(c.get("text", "") for c in (last_user or {}).get("content", [])
                    if isinstance(c, dict)).lower()
    terms = ("outage", "power", "electric", "risk", "restor", "crew", "storm", "road", "damage",
             "prepare", "alert", "utility", "line", "wire", "transformer", "fuse", "recloser",
             "medical", "medication", "mobility", "infant", "baby", "pet", "critical facility",
             "life support")
    return any(term in text for term in terms)


def _conversational_answer(history: list[dict], language: str) -> str:
    """Use Nova like the Bedrock console for non-outage chat, with no added system prompt."""
    client = get_client()
    if client is None:
        return _conversation_fallback(language)
    kwargs = {
        "modelId": os.environ["BEDROCK_MODEL_ID"],
        "messages": history,
        "inferenceConfig": {"maxTokens": 300, "temperature": 0.2},
    }
    if (gr := guardrail_config()):
        kwargs["guardrailConfig"] = gr
    out = client.converse(**kwargs)
    stop_reason = out.get("stopReason")
    if stop_reason not in {"end_turn", "stop_sequence", "guardrail_intervened"}:
        raise ValueError("unsupported conversational stop reason")
    msg = _validated_message(out)
    text = "".join(c.get("text", "") for c in msg["content"] if isinstance(c, dict)).strip()
    if not text:
        return _privacy_refusal(language) if stop_reason == "guardrail_intervened" else _conversation_fallback(language)
    return scrub_text(text)


def _conversation_fallback(language: str) -> str:
    if language == "es":
        return "Puedo ayudar con el riesgo de apagón, la restauración, la preparación y las alertas."
    return "I can help with outage risk, restoration, preparation, and alerts."


def _small_talk_reply(history: list[dict], language: str) -> str | None:
    """Handle simple social turns in code so a greeting never dumps a full outage forecast."""
    last_user = next((m for m in reversed(history) if m.get("role") == "user"), None)
    text = " ".join(c.get("text", "") for c in (last_user or {}).get("content", [])
                    if isinstance(c, dict)).strip().lower()
    greeting = re.fullmatch(r"(?:hi|hello|hey|good (?:morning|afternoon|evening)|hola|buenos d[ií]as)[!. ]*", text)
    thanks = re.fullmatch(r"(?:thanks|thank you|gracias)[!. ]*", text)
    help_request = re.fullmatch(r"(?:help|what can you do|how can you help)[?!. ]*", text)
    if not (greeting or thanks or help_request):
        return None
    if language == "es":
        if thanks:
            return "Con gusto. Puedo explicar su riesgo de apagón, el tiempo de restauración, cómo prepararse y sus alertas."
        return "¡Hola! Puedo explicar su riesgo de apagón, el tiempo de restauración, cómo prepararse y sus alertas."
    if thanks:
        return "You're welcome. I can explain your outage risk, restoration range, preparation steps, or alert eligibility."
    return "Hi! I can explain your outage risk, restoration range, preparation steps, or alert eligibility."


def _requests_private_contact(history: list[dict]) -> bool:
    """Recognize direct requests for private phone/contact details before any model call."""
    last_user = next((m for m in reversed(history) if m.get("role") == "user"), None)
    text = " ".join(c.get("text", "") for c in (last_user or {}).get("content", [])
                    if isinstance(c, dict)).strip().lower()
    return bool(re.search(
        r"\b(?:show|give|tell|share|provide|what(?:'s| is))\b.{0,30}"
        r"\b(?:mobile|phone|telephone|contact)\b(?:\s+number)?",
        text,
    ))


def _privacy_refusal(language: str) -> str:
    if language == "es":
        return ("No puedo proporcionar ni recopilar números de teléfono personales. StormHaven solo usa "
                "si está inscrito y el tipo de canal de alerta que eligió.")
    return ("I can't provide or collect personal phone numbers. StormHaven only uses whether you're enrolled "
            "and the alert channel type you selected.")


def _contains_personal_disclosure(history: list[dict]) -> bool:
    """Catch explicit personal-data disclosures and respond without sending them to Bedrock."""
    last_user = next((m for m in reversed(history) if m.get("role") == "user"), None)
    text = " ".join(c.get("text", "") for c in (last_user or {}).get("content", [])
                    if isinstance(c, dict)).strip()
    return bool(re.search(
        r"\b(?:my name is|i['’]?m called|my (?:phone|mobile|email|address|account number) is)\b",
        text,
        re.I,
    ))


def _privacy_notice(language: str) -> str:
    if language == "es":
        return ("Por su privacidad, no comparta nombres, direcciones, números de teléfono, números de cuenta ni "
                "detalles médicos. Puede preguntarme sobre el riesgo, la restauración, la preparación o las alertas.")
    return ("For your privacy, please don't share names, addresses, phone numbers, account numbers, or medical "
            "details. You can ask me about outage risk, restoration, preparation, or alerts.")


def _answer(history, premise_id, circuit_id, base_scenario, profile, utility_status,
            current, current_payload: dict, data_mode: str) -> str:
    """Bedrock may request one what-if, then selects which deterministic answer section to render."""
    client = get_client()
    if client is None:
        return _offline_reply(current, data_mode)

    messages = list(history)
    selected = current
    tool_used = False
    context = ("CURRENT_OUTAGE_OUTLOOK (computed by StormHaven; use as the source of truth):\n" +
               json.dumps(current_payload, separators=(",", ":"), ensure_ascii=True))
    # Low temperature: we want consistent, factual explanations, not creativity.
    kwargs = {"modelId": os.environ["BEDROCK_MODEL_ID"],
              "system": [{"text": SYSTEM_PROMPT}, {"text": context}],
              "toolConfig": TOOLS, "inferenceConfig": {"maxTokens": 600, "temperature": 0.2}}
    if (gr := guardrail_config()):
        kwargs["guardrailConfig"] = gr

    for _ in range(2):                                  # at most one tool request plus one final decision
        # Scope input assessment to the sanitized customer question. Without guardContent,
        # Bedrock evaluates every message block and can falsely block deterministic context.
        out = client.converse(messages=_guarded_user_messages(messages), **kwargs)
        stop_reason = out.get("stopReason")
        if stop_reason == "guardrail_intervened":
            msg = _validated_message(out)
            guarded_text = "".join(c.get("text", "") for c in msg["content"] if isinstance(c, dict)).strip()
            return scrub_text(guarded_text) if guarded_text else _conversation_fallback(profile.language)
        if stop_reason not in {"tool_use", "end_turn", "stop_sequence"}:
            return _offline_reply(current, data_mode)
        msg = _validated_message(out)
        messages.append(msg)
        if stop_reason != "tool_use":                    # model is done -> parse intent, render facts in code
            text = "".join(c.get("text", "") for c in msg["content"] if isinstance(c, dict)).strip()
            answer_type = _parse_answer_type(text)
            # Nova can occasionally return a valid but overly generic "overview" for an explicit
            # challenge question. Keep obvious UI intents deterministic; the model still routes
            # ambiguous questions and requests validated what-if calculations.
            answer_type = _explicit_answer_type(history[-1]["content"][0]["text"]) or answer_type
            return _render_response(selected, data_mode, answer_type, what_if=(selected is not current))
        # Exactly one approved what-if is allowed. Multiple calls or another round fail closed.
        tool_blocks = [c["toolUse"] for c in msg["content"]
                       if isinstance(c, dict) and "toolUse" in c]
        if tool_used or len(tool_blocks) != 1:
            raise ValueError("exactly one tool call is allowed")
        tool = tool_blocks[0]
        if not isinstance(tool, dict) or tool.get("name") != _TOOL_NAME or not tool.get("toolUseId"):
            raise ValueError("unsupported or malformed tool call")
        raw_args = tool.get("input", {}) or {}
        if not isinstance(raw_args, dict):
            raise ValueError("tool input must be an object")
        if set(raw_args) - _ALLOWED_TOOL_ARGS:
            raise ValueError("tool input contained an unapproved field")
        args = {k: v for k, v in raw_args.items() if k in _ALLOWED_TOOL_ARGS and v is not None}
        if not args or not _tool_args_match_question(args, history[-1]["content"][0]["text"]):
            raise ValueError("tool input was not explicitly requested by the user")
        sc = StormScenario.model_validate({**base_scenario.model_dump(), **args})
        selected = run_concierge(ConciergeRequest(
            premise_id=premise_id, circuit_id=circuit_id, scenario=sc, profile=profile,
            utility_status=utility_status,
        ))
        payload = _flatten_for_llm(selected, profile, data_mode)
        messages.append({"role": "user", "content": [{"toolResult": {
            "toolUseId": tool["toolUseId"], "content": [{"json": payload}],
        }}]})
        tool_used = True
    # Out of rounds: return the already-computed deterministic answer instead of a partial model answer.
    return _offline_reply(current, data_mode)


def _guarded_user_messages(messages: list[dict]) -> list[dict]:
    """Mark customer text as guard content while leaving tool results and engine context untouched."""
    guarded = []
    for message in messages:
        content = []
        for block in message.get("content", []):
            if message.get("role") == "user" and isinstance(block, dict) and set(block) == {"text"}:
                content.append({"guardContent": {"text": {"text": block["text"]}}})
            else:
                content.append(block)
        guarded.append({**message, "content": content})
    return guarded


def _validated_message(out: dict) -> dict:
    """Validate the small part of a Converse response that the chat loop consumes."""
    if not isinstance(out, dict):
        raise ValueError("Bedrock response must be an object")
    message = (out.get("output") or {}).get("message")
    if not isinstance(message, dict) or message.get("role") != "assistant":
        raise ValueError("Bedrock response is missing an assistant message")
    if not isinstance(message.get("content"), list) or not message["content"]:
        raise ValueError("Bedrock response has no content")
    return message


def _tool_args_match_question(args: dict, question: str) -> bool:
    """Authorize what-if values only when the latest user question explicitly contains them."""
    lower = question.lower()

    def mentions_number(value) -> bool:
        number = float(value)
        forms = {f"{number:g}", str(value)}
        return any(re.search(rf"(?<!\d){re.escape(form)}(?!\d)", lower) for form in forms)

    if "crews_available" in args and not ("crew" in lower and mentions_number(args["crews_available"])):
        return False
    if "severity_percentile" in args:
        has_severity_word = any(word in lower for word in ("severity", "percentile", "storm strength"))
        if not has_severity_word or not mentions_number(args["severity_percentile"]):
            return False
    if "road_access" in args and str(args["road_access"]).lower() not in lower:
        return False
    return True


def _parse_answer_type(text: str) -> str:
    """Extract one tiny JSON decision; surrounding Nova reasoning is never displayed.

    Nova Lite can wrap its requested JSON in a ``<thinking>`` block or a Markdown
    fence even when instructed not to. Accepting exactly one allowlisted decision
    remains safe because all other model text is discarded and Python renders the
    customer-facing response from deterministic engine output.
    """
    pattern = r'\{\s*"answer_type"\s*:\s*"(?:overview|risk|restoration|why|preparation|alerts)"\s*\}'
    matches = re.findall(pattern, text)
    if len(matches) != 1:
        raise ValueError("Bedrock final response must contain exactly one answer_type decision")
    decision = json.loads(matches[0])
    answer_type = decision["answer_type"]
    if answer_type not in _ANSWER_TYPES:
        raise ValueError("unsupported answer type")
    return answer_type


def _explicit_answer_type(question: str) -> str | None:
    """Route only unmistakable challenge-question wording; leave ambiguous text to Nova."""
    lower = question.lower()
    if any(word in lower for word in ("alert", "eligible", "qualify")):
        return "alerts"
    if any(phrase in lower for phrase in ("how long", "restoration", "restore", "power return")):
        return "restoration"
    if any(word in lower for word in ("prepare", "preparation")) or "what should i do" in lower:
        return "preparation"
    if "why" in lower:
        return "why"
    if any(phrase in lower for phrase in ("lose power", "outage risk", "risk level")):
        return "risk"
    return None


def _render_response(r, data_mode: str, answer_type: str = "overview", what_if: bool = False) -> str:
    """Render customer facts only from the typed deterministic engine response."""
    if r.risk.source == "fallback":
        return ("I couldn't match your location to our network data, so StormHaven did not make an outage "
                "prediction. Please check AEP's official outage map or contact AEP directly.")

    prefix = "For that what-if scenario, " if what_if else ""
    risk = (f"{prefix}StormHaven's model estimates a {r.risk.band} outage risk "
            f"({round(r.risk.probability * 100)}%, {r.risk.trust.confidence} confidence).")
    restoration = r.restoration.range_text
    mode = ("This uses the synthetic demo network, not real AEP locations."
            if data_mode == "synthetic" else "This uses the processed AEP challenge dataset.")
    confirmation = ("Demo simulation: the utility-confirmation toggle marks this location as out; "
                    "this is not a live AEP feed."
                    if r.restoration.outage_confirmed else
                    "No outage confirmation from a live utility feed is available.")

    if answer_type == "risk":
        parts = [risk]
    elif answer_type == "why":
        parts = [risk] + [factor.plain_language for factor in r.risk.factors[:3]]
    elif answer_type == "restoration":
        parts = [risk, restoration] + [driver.plain_language for driver in r.restoration.drivers[:2]]
    elif answer_type == "preparation":
        guidance = r.guidance.safety[:2] + r.guidance.actions[:3]
        parts = [risk] + [item.text for item in guidance]
    elif answer_type == "alerts":
        status = ("You are eligible for the configured outage alerts."
                  if r.alerts.eligible else "You are not currently eligible for the configured outage alerts.")
        parts = [status] + r.alerts.reasons[:3]
    else:
        actions = [item.text for item in r.guidance.actions[:1]]
        parts = [risk, restoration, *actions]

    parts.extend([confirmation, mode])
    return scrub_text(" ".join(part for part in parts if part))


def _offline_reply(r, data_mode: str) -> str:
    """Deterministic answer when Bedrock isn't available — the demo never dies."""
    return _render_response(r, data_mode, "overview")
