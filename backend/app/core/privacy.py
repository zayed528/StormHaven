"""
Privacy controls.   Owner: Nandan
 1. Customers never see internal IDs / coordinates / contacts / critical-facility locations.
    scrub_text runs on EVERY customer-facing string; scrub_response applies it to a whole response.
 2. The LLM only ever receives allowlisted, derived fields (llm_payload).
"""
from __future__ import annotations
import re
from typing import TypeVar

from pydantic import BaseModel

from app.config import ASSUMPTIONS

# Internal device kind -> what a customer reads. Engines must use friendly_name(), never raw IDs.
FRIENDLY = {
    "substation": "the substation serving your area",
    "breaker": "the main circuit breaker for your area",
    "recloser": "an automatic switch on the main line",
    "fuse": "the fuse protecting your street",
    "transformer": "the transformer serving your home",
    "step_transformer": "a voltage transformer on the line serving your area",
}

# Patterns for things that must never reach a customer or an SMS:
_COORD = re.compile(r"-?\d{1,3}\.\d{3,}\s*,\s*-?\d{1,3}\.\d{3,}")
# Internal node IDs: synthetic (SUB-1, FUS-311, ...) and real-data prefixes from pipelines/02 (XF-, FU-, RC-, ...).
_INTERNAL_ID = re.compile(r"\b(SUB|BRK|REC|FUS|TX|P|CKT|XF|ST|FU|RC|SC|CB)-\d+\b")
# Bare long digit runs: AEP premise numbers (9 digits), circuit codes (7), device/location numbers.
_LONG_NUMBER = re.compile(r"\b\d{7,}\b")
# AEP device location numbers mix digits and a letter, e.g. 37800343D00129.
_LOCATION_CODE = re.compile(r"\b\d{5,}[A-Z]\d{3,}\b")
_PHONE = re.compile(r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b")
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b")

# Response fields that are machine identifiers, not customer text: left untouched.
_NOT_TEXT = {"audit_id", "map_point_id", "name", "source", "band", "confidence", "phase", "channel",
             "resolved_level"}

M = TypeVar("M", bound=BaseModel)


# Short noun per kind, for "another fuse further up the line" when a path has two of the same kind.
SHORT = {"substation": "substation", "breaker": "circuit breaker", "recloser": "automatic switch",
         "fuse": "fuse", "transformer": "transformer", "step_transformer": "voltage transformer"}


def friendly_name(kind: str) -> str:
    return FRIENDLY.get(kind, "equipment upstream of you")


def another_name(kind: str) -> str:
    """Name for the 2nd device of a kind already mentioned, e.g. 'another automatic switch further up the line'."""
    return f"another {SHORT.get(kind, 'piece of equipment')} further up the line"


def scrub_text(text: str) -> str:
    """Run on EVERY customer-facing string, especially LLM output."""
    # Coordinates first, so a "lat, lon" pair isn't half-matched by the phone pattern.
    text = _COORD.sub("[location hidden]", text)
    text = _INTERNAL_ID.sub("[equipment]", text)
    text = _PHONE.sub("[contact hidden]", text)
    text = _EMAIL.sub("[contact hidden]", text)
    text = _LOCATION_CODE.sub("[equipment]", text)
    text = _LONG_NUMBER.sub("[id hidden]", text)    # after phones, so 10-digit phones read as contacts
    return text


def _scrub(obj, key: str | None = None):
    """Walk a dumped model (dicts/lists/strings) and scrub every string except machine-identifier fields."""
    if isinstance(obj, str):
        return obj if key in _NOT_TEXT else scrub_text(obj)
    if isinstance(obj, dict):
        return {k: _scrub(v, k) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_scrub(v, key) for v in obj]
    return obj


def scrub_response(model: M) -> M:
    """Scrub every string field of a response model (last line of defense before it leaves the API)."""
    return type(model).model_validate(_scrub(model.model_dump()))


def llm_payload(d: dict) -> dict:
    """Strip anything not on the allowlist before sending to Bedrock.
    Allowlist (not blocklist): a new field is excluded until someone deliberately adds it in assumptions.yaml."""
    allow = set(ASSUMPTIONS["privacy"]["llm_field_allowlist"])
    return {k: v for k, v in d.items() if k in allow}
