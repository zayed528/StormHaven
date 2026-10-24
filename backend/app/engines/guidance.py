"""
ENGINE 3 — "What should I do to prepare?"   Owner: Abby

Rules, not generation: risk band x duration bucket x DECLARED needs -> curated items.
Safety items are always included and flagged is_safety=True (UI shows them in a red banner).
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
    return yaml.safe_load((CONTENT_DIR / "guidance_library.yaml").read_text())


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

    # Safety items: always shown, except need-specific ones (e.g. medical) which need a DECLARED need.
    safety = [GuidanceItem(text=s["text"], phase=s["phase"], is_safety=True, reason="Safety")
              for s in lib["safety"] if not s.get("needs") or set(s["needs"]) & needs]

    # Action items: an item applies only if it passes all three gates (band, duration bucket, declared need).
    actions = []
    for a in lib["actions"]:
        if band_rank < BAND_ORDER[a.get("min_band", "Low")]:           # risk too low for this item
            continue
        if a.get("buckets") and bucket not in a["buckets"]:            # wrong expected duration
            continue
        if a.get("needs") and not (set(a["needs"]) & needs):          # need not declared -> never shown
            continue
        actions.append(GuidanceItem(text=a["text"], phase=a["phase"], reason=a.get("reason", "")))

    # need-specific items first (their reason starts with "You told us..."), then before -> during -> after
    phase_order = {"before": 0, "during": 1, "after": 2}
    actions.sort(key=lambda x: (not x.reason.startswith("You "), phase_order[x.phase]))
    return GuidanceResponse(safety=safety, actions=actions, duration_bucket=bucket)
