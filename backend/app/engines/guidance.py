"""
ENGINE 3 — "What should I do to prepare?"   Owner: Nandan (was Abby)

Rules, not generation: risk band x duration bucket x DECLARED needs -> curated items.
Safety items are always included and flagged is_safety=True (UI shows them in a red banner).
Text comes back in profile.language: the library's text_es / reason_es for Spanish, English if one is missing.
"""
from __future__ import annotations
from functools import lru_cache
import yaml

from app.config import ASSUMPTIONS, CONTENT_DIR
from app.schemas import CustomerProfile, GuidanceItem, GuidanceResponse, RestorationResponse, RiskResponse

BAND_ORDER = {"Unknown": 1, "Low": 0, "Moderate": 1, "High": 2, "Very High": 3}  # Unknown -> cautious default


@lru_cache(maxsize=1)
def _library() -> dict:
    """Curated guidance items (content/guidance_library.yaml), loaded once. Restart the API after editing."""
    # utf-8 explicitly: the Spanish text has accents, and Windows would otherwise read it as cp1252.
    return yaml.safe_load((CONTENT_DIR / "guidance_library.yaml").read_text(encoding="utf-8"))


def _pick(item: dict, key: str, lang: str) -> str:
    """item[key] in the customer's language (e.g. text_es), falling back to English so a line is never blank."""
    return (lang != "en" and item.get(f"{key}_{lang}")) or item.get(key, "")


def duration_bucket(p90_hours: float) -> str:
    """Bucket the PESSIMISTIC end (P90) of the range, so advice prepares for the long case."""
    for b in ASSUMPTIONS["guidance"]["duration_buckets"]:
        if p90_hours < b["max"]:
            return b["name"]
    return "extended"


def build_guidance(risk: RiskResponse, rest: RestorationResponse, profile: CustomerProfile) -> GuidanceResponse:
    """Public entry point (called by service.py). Pure filtering of the library: no text is generated here."""
    lib = _library()
    needs = {n.value for n in profile.declared_needs}
    # Fallback: unknown location -> assume a day-long outage so advice errs safe
    bucket = duration_bucket(rest.p90_hours if rest.source != "fallback" else 24)
    band_rank = BAND_ORDER.get(risk.band, 1)
    lang = profile.language

    # Safety items: always shown, except need-specific ones (e.g. medical) which need a DECLARED need.
    safety = [GuidanceItem(text=_pick(s, "text", lang), phase=s["phase"], is_safety=True,
                           reason="Seguridad" if lang == "es" else "Safety")
              for s in lib["safety"] if not s.get("needs") or set(s["needs"]) & needs]

    # Action items: an item applies only if it passes all three gates (band, duration bucket, declared need).
    actions = []          # (is need-specific, item)
    for a in lib["actions"]:
        if band_rank < BAND_ORDER[a.get("min_band", "Low")]:           # risk too low for this item
            continue
        if a.get("buckets") and bucket not in a["buckets"]:            # wrong expected duration
            continue
        if a.get("needs") and not (set(a["needs"]) & needs):          # need not declared -> never shown
            continue
        actions.append((bool(a.get("needs")), GuidanceItem(text=_pick(a, "text", lang), phase=a["phase"],
                                                            reason=_pick(a, "reason", lang))))

    # need-specific items first, then before -> during -> after (sorted on the flag, so it works in any language)
    phase_order = {"before": 0, "during": 1, "after": 2}
    actions.sort(key=lambda x: (not x[0], phase_order[x[1].phase]))
    return GuidanceResponse(safety=safety, actions=[a for _, a in actions], duration_bucket=bucket)
