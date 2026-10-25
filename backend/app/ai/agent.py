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
from difflib import SequenceMatcher

from app.ai.bedrock_client import get_client, guardrail_config
from app.ai.prompts import SAFETY_911, SYSTEM_PROMPT
from app.core.data_loader import get_store
from app.core.privacy import llm_payload, sanitize_chat_history, scrub_text
from app.schemas import (ConciergeRequest, CustomerProfile, SimulatedUtilityStatus,
                         DeclaredNeed, StormScenario)
from app.service import run_concierge

logger = logging.getLogger(__name__)
_TOOL_NAME = "get_outage_outlook"
_ALLOWED_TOOL_ARGS = {"severity_percentile", "crews_available", "road_access"}
_ANSWER_TYPES = {"overview", "risk", "restoration", "why", "preparation", "alerts"}
_CONVERSATIONAL_SYSTEM = """You are Jed, StormHaven's customer assistant.
Stay focused on outage risk, restoration estimates, storm preparation, alerts, and safe utility information.
If the message is unrelated, insulting, or unclear, respond briefly and politely invite the customer to ask
about one of those topics. Do not provide medical, legal, mental-health, or emergency advice beyond the fixed
StormHaven safety response. Never ask for or repeat names, addresses, phone numbers, account numbers, or medical
details. Do not invent outage facts, restoration times, utility confirmations, or alert eligibility."""

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
    if _EMERGENCY.search(text):
        return True
    lower = text.lower()
    return _contains_intent_term(lower, ("spark", "smoke", "shock", "emergency")) or any(
        len(word) >= 4 and SequenceMatcher(None, word, "fire").ratio() >= 0.78
        for word in re.findall(r"[a-z]+", lower)
    )


def _flatten_for_llm(resp, profile: CustomerProfile, data_mode: str,
                     contextual_needs: set[str] | None = None) -> dict:
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
        "contextual_needs": sorted(contextual_needs or set()),
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
    if _requests_private_contact(history):
        return _privacy_refusal(profile.language)
    if _contains_personal_disclosure(history):
        return _privacy_notice(profile.language)
    if not emergency:
        if (small_talk := _small_talk_reply(history, profile.language)):
            return small_talk
    # This is a location-based outage concierge, not a general-purpose chatbot.
    # Keep vague location questions on the grounded path, but redirect unrelated
    # requests instead of spending a model call outside the MVP.
    if not emergency and not _is_outage_question(history):
        return _out_of_scope_reply(profile.language)
    question = _latest_question(history)
    contextual_needs = _contextual_needs(question, profile)
    effective_profile = CustomerProfile.model_validate({
        **profile.model_dump(),
        "declared_needs": list({*profile.declared_needs,
                                *(DeclaredNeed(need) for need in contextual_needs)})
    })
    current = run_concierge(ConciergeRequest(premise_id=premise_id, circuit_id=circuit_id,
                                             scenario=base_scenario, profile=effective_profile,
                                             utility_status=utility_status))
    data_mode = "synthetic" if get_store().is_synthetic else "real"
    current_payload = _flatten_for_llm(current, profile, data_mode, contextual_needs)
    try:
        reply = _answer(safe_history, premise_id, circuit_id, base_scenario, effective_profile,
                        utility_status, current, current_payload, data_mode)
    except Exception as exc:  # Bedrock, malformed output, and validation failures all fail closed.
        logger.warning("Bedrock chat fell back safely (%s)", type(exc).__name__)
        reply = _offline_reply(current, data_mode, profile=effective_profile)
    return f"{SAFETY_911}\n\n{reply}" if emergency else reply


def _is_outage_question(history: list[dict]) -> bool:
    """Keep outage facts on the grounded engine path; everything else is conversational."""
    last_user = next((m for m in reversed(history) if m.get("role") == "user"), None)
    text = " ".join(c.get("text", "") for c in (last_user or {}).get("content", [])
                    if isinstance(c, dict)).lower()
    terms = ("outage", "power", "electric", "risk", "restor", "crew", "storm", "road", "damage",
             "prepare", "alert", "utility", "line", "wire", "transformer", "fuse", "recloser",
             "medical", "medication", "refrigerated", "refrigeration", "equipment", "device",
             "mobility", "wheelchair", "oxygen", "insulin", "infant", "baby", "babies",
             "child", "children", "kid", "kids", "formula", "diaper", "pet", "pets",
             "critical facility", "facility", "hospital", "senior", "elderly", "generator",
             "cooler", "freezer",
             "life support", "here", "over here", "around here", "this area", "my area",
             "near me", "nearby", "location", "situation", "happening", "baby", "babies",
             "family", "reveal", "private",
             "contact", "system prompt", "ignore the system",
             # Spanish (profile.language = "es")
             "luz", "apagón", "apagon", "electricidad", "corriente", "restaur", "tormenta", "cuadrilla",
             "preparar", "prepararme", "alerta", "alertas", "riesgo", "cuánto", "cuanto", "medicina",
             "equipo médico", "bebé", "mascota", "generador")
    if _contains_intent_term(text, terms):
        return True
    # Short follow-ups in the chat are still about the displayed outage outlook.
    # Keep these grounded instead of treating them as unrelated general-chat prompts.
    preparation_phrases = (
        "what would i do", "what should i do", "what can i do", "what do i do",
        "what do i need", "should i", "do i need to", "how do i prepare",
        "what now", "do now",
    )
    reassurance_phrases = (
        "will i be fine", "will i be okay", "will i be safe", "am i safe",
        "is it safe", "is everything okay", "is everything fine", "can i stay",
    )
    return (any(_matches_phrase(text, phrase) for phrase in preparation_phrases) or
            any(_matches_phrase(text, phrase) for phrase in reassurance_phrases))


def _latest_question(history: list[dict]) -> str:
    last_user = next((m for m in reversed(history) if m.get("role") == "user"), None)
    return " ".join(c.get("text", "") for c in (last_user or {}).get("content", [])
                    if isinstance(c, dict))


def _contextual_needs(question: str, profile: CustomerProfile) -> set[str]:
    """Use needs stated in the current message for this reply, without changing the saved profile."""
    lower = question.lower()
    candidates = {
        "medical_device": ("medical", "equipment", "device", "oxygen", "cpap", "ventilator"),
        "refrigerated_medication": ("refrigerated", "refrigeration", "insulin", "medication", "medicine"),
        "mobility": ("mobility", "wheelchair", "walker", "elevator", "powered door"),
        "infants": ("infant", "baby", "babies", "child", "children", "kid", "kids", "formula", "diaper"),
        "pets": ("pet", "pets", "dog", "cat", "animal"),
        "critical_facility": ("critical facility", "hospital", "care home", "nursing home", "facility"),
    }
    declared = {getattr(need, "value", need) for need in profile.declared_needs}
    return {need for need, terms in candidates.items()
            if need not in declared and _contains_intent_term(lower, terms)}


def _contains_intent_term(text: str, terms: tuple[str, ...]) -> bool:
    """Accept small spelling mistakes without turning the router into general chat."""
    if any(term in text for term in terms):
        return True
    words = re.findall(r"[a-z]+", text)
    single_terms = [term for term in terms if " " not in term and len(term) >= 5]
    return any(
        len(word) >= 4 and
        max(SequenceMatcher(None, word, term).ratio() for term in single_terms) >= 0.78
        for word in words
    )


def _matches_phrase(text: str, phrase: str) -> bool:
    """Match a short conversational phrase while allowing one typo per long word."""
    text_words = re.findall(r"[a-z]+", text)
    phrase_words = phrase.split()
    if len(text_words) < len(phrase_words):
        return False
    for start in range(len(text_words) - len(phrase_words) + 1):
        window = text_words[start:start + len(phrase_words)]
        if all(word == expected or (
                len(expected) >= 4 and SequenceMatcher(None, word, expected).ratio() >= 0.72
        ) for word, expected in zip(window, phrase_words)):
            return True
    return False


def _conversational_answer(history: list[dict], language: str) -> str:
    """Use Nova like the Bedrock console for non-outage chat, with no added system prompt."""
    client = get_client()
    if client is None:
        return _conversation_fallback(language)
    kwargs = {
        "modelId": os.environ["BEDROCK_MODEL_ID"],
        "system": [{"text": _CONVERSATIONAL_SYSTEM}],
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


def _out_of_scope_reply(language: str) -> str:
    if language == "es":
        return ("Puedo ayudar con el pronóstico de apagones de esta zona: riesgo, restauración, preparación y "
                "alertas. Pregúnteme sobre uno de esos temas.")
    return ("I can help with this area's outage outlook: risk, restoration, preparation, and alerts. "
            "Please ask me about one of those topics.")


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
            return "Con gusto. Soy Jed. Puedo explicar su riesgo de apagón, el tiempo de restauración, cómo prepararse y sus alertas."
        return "¡Hola! Soy Jed. Puedo explicar su riesgo de apagón, el tiempo de restauración, cómo prepararse y sus alertas."
    if thanks:
        return "You're welcome. I'm Jed. I can explain your outage risk, restoration range, preparation steps, or alert eligibility."
    return "Hi! I'm Jed. I can explain your outage risk, restoration range, preparation steps, or alert eligibility."


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
    if client is None:                       # offline: route by the question's wording
        return _offline_reply(current, data_mode, _latest_question(history), profile)

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
            return _offline_reply(current, data_mode, profile=profile)
        msg = _validated_message(out)
        messages.append(msg)
        if stop_reason != "tool_use":                    # model is done -> parse intent, render facts in code
            text = "".join(c.get("text", "") for c in msg["content"] if isinstance(c, dict)).strip()
            answer_type = _parse_answer_type(text)
            # Nova can occasionally return a valid but overly generic "overview" for an explicit
            # challenge question. Keep obvious UI intents deterministic; the model still routes
            # ambiguous questions and requests validated what-if calculations.
            answer_type = _explicit_answer_type(history[-1]["content"][0]["text"]) or answer_type
            return _render_response(selected, data_mode, answer_type, what_if=(selected is not current),
                                    profile=profile, question=history[-1]["content"][0]["text"])
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
    return _offline_reply(current, data_mode, profile=profile)


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
    if _contains_intent_term(lower, ("alert", "eligible", "qualify", "alerta", "alertas", "califico", "califica")):
        return "alerts"
    # Spanish: "¿Cuánto podría tardar…?", "¿Qué debo hacer para prepararme?", "¿Por qué…?", "¿Me quedaré sin luz?"
    if any(w in lower for w in ("cuánto", "cuanto", "tardar", "restaur", "volver la luz", "vuelva la luz")):
        return "restoration"
    if any(w in lower for w in ("preparar", "prepararme", "qué debo hacer", "que debo hacer")):
        return "preparation"
    if "por qué" in lower or "por que" in lower:
        return "why"
    if any(w in lower for w in ("sin luz", "apagón", "apagon", "quedaré sin", "quedare sin", "riesgo")):
        return "risk"
    if any(phrase in lower for phrase in ("how long", "power return")) or _contains_intent_term(
            lower, ("restoration", "restore")):
        return "restoration"
    if _contains_intent_term(lower, ("prepare", "preparation")) or _matches_phrase(
            lower, "what should i do"):
        return "preparation"
    if _contains_intent_term(lower, ("baby", "babies", "infant", "child", "children", "medical",
                                     "medication", "refrigerated", "equipment", "device",
                                     "mobility", "wheelchair", "oxygen", "insulin", "formula",
                                     "diaper", "pet", "pets", "critical", "facility", "generator")):
        return "preparation"
    if "why" in lower:
        return "why"
    if (any(phrase in lower for phrase in
            ("lose power", "outage risk", "risk level", "will i be fine", "will i be okay",
             "will i be safe", "am i safe", "is it safe", "everything okay", "everything fine")) or
            _contains_intent_term(lower, ("outage", "power", "risk"))):
        return "risk"
    return None


def _render_response(r, data_mode: str, answer_type: str = "overview", what_if: bool = False,
                     profile: CustomerProfile | None = None, question: str = "") -> str:
    """Render customer facts only from the typed deterministic engine response."""
    if r.risk.source == "fallback":
        return ("I couldn't match your location to our network data, so StormHaven did not make an outage "
                "prediction. Please check AEP's official outage map or contact AEP directly.")

    es = profile is not None and profile.language == "es"
    band = {"Low": "bajo", "Moderate": "moderado", "High": "alto", "Very High": "muy alto"}.get(r.risk.band, r.risk.band) \
        if es else r.risk.band
    conf = {"High": "alta", "Medium": "media", "Low": "baja"}.get(r.risk.trust.confidence) if es \
        else r.risk.trust.confidence
    pct = round(r.risk.probability * 100)
    if es:
        prefix = "Para ese escenario hipotético, " if what_if else ""
        risk = f"{prefix}El modelo de StormHaven estima un riesgo de apagón {band} ({pct}%, confianza {conf})."
    else:
        prefix = "For that what-if scenario, " if what_if else ""
        risk = f"{prefix}StormHaven's model estimates a {band} outage risk ({pct}%, {conf} confidence)."
    restoration = r.restoration.range_text
    # Only the synthetic network needs a disclaimer; on real data the answer simply stands.
    mode = (("Esto usa la red de demostración sintética, no ubicaciones reales de AEP." if es else
             "This uses the synthetic demo network, not real AEP locations.") if data_mode == "synthetic" else "")
    if r.restoration.outage_confirmed:
        confirmation = ("Simulación de demostración: el estado de confirmación de la empresa marca esta ubicación "
                        "sin luz; no es una fuente en vivo de AEP." if es else
                        "Demo simulation: the utility-confirmation toggle marks this location as out; "
                        "this is not a live AEP feed.")
    else:
        confirmation = ("AEP aún no ha confirmado un apagón en su ubicación; esto es una estimación." if es else
                        "No outage confirmation from a live utility feed is available.")

    if answer_type == "risk":
        parts = [risk]
    elif answer_type == "why":
        parts = [risk] + [factor.plain_language for factor in r.risk.factors[:3]]
    elif answer_type == "restoration":
        parts = [risk, restoration, r.restoration.storm_context] + \
            [driver.plain_language for driver in r.restoration.drivers[:2]]
    elif answer_type == "preparation":
        guidance = r.guidance.safety[:2] + r.guidance.actions[:3]
        parts = [risk] + [item.text for item in guidance]
    elif answer_type == "alerts":
        status = (("Usted califica para las alertas de apagón configuradas." if r.alerts.eligible else
                   "Por ahora no califica para las alertas de apagón configuradas.") if es else
                  ("You are eligible for the configured outage alerts." if r.alerts.eligible else
                   "You are not currently eligible for the configured outage alerts."))
        parts = [status] + r.alerts.reasons[:3]
    else:
        actions = [item.text for item in r.guidance.actions[:1]]
        parts = [risk, restoration, *actions]
    # A confirmed outage is always worth saying; "no confirmation yet" only belongs with timing answers.
    if not r.restoration.outage_confirmed and answer_type not in ("overview", "restoration"):
        confirmation = ""

    parts.extend([confirmation, mode])
    return scrub_text(" ".join(part for part in parts if part))


def _offline_reply(r, data_mode: str, question: str = "", profile: CustomerProfile | None = None) -> str:
    """Deterministic answer when Bedrock isn't available — the demo never dies. Routed by the question's
    wording (EN/ES), so "How long?" gets the restoration answer, not the same overview every time."""
    return _render_response(r, data_mode, _explicit_answer_type(question) or "overview",
                            profile=profile, question=question)
