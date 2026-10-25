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
from app.schemas import (BackupCheck, CustomerProfile, GuidanceItem, GuidanceResponse, RestorationResponse,
                         RiskResponse)

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


def _hours_text(h: float, lang: str) -> str:
    """'8 hours' / '2.5 days' (es: '8 horas' / '2.5 días') for the backup-check sentence."""
    if h >= 48:
        return f"{h / 24:.1f} {'días' if lang == 'es' else 'days'}"
    n = max(1, round(h))
    return f"{n} {('hora' if n == 1 else 'horas') if lang == 'es' else ('hour' if n == 1 else 'hours')}"


def backup_check(rest: RestorationResponse, profile: CustomerProfile) -> BackupCheck | None:
    """Declared medical device + stated backup hours: compare the backup with THIS home's restoration estimate.
    short: backup < best guess (P50); tight: < pessimistic end (P90); ok: outlasts P90. None otherwise
    (no declared device, no hours given, or no estimate for this location)."""
    needs = {n.value for n in profile.declared_needs}
    if "medical_device" not in needs or profile.backup_power_hours is None or rest.source == "fallback":
        return None
    b, p50, p90 = profile.backup_power_hours, rest.p50_hours, rest.p90_hours
    status = "short" if b < p50 else "tight" if b < p90 else "ok"
    lang = profile.language
    tpl = _library()["backup_check"][status]
    msg = _pick(tpl, "text", lang).format(backup=_hours_text(b, lang), p50=_hours_text(p50, lang),
                                          p90=_hours_text(p90, lang))
    return BackupCheck(status=status, backup_hours=b, p50_hours=p50, p90_hours=p90, message=msg)


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
        is_declared_need = bool(a.get("needs") and set(a["needs"]) & needs)
        if a.get("needs") and not is_declared_need:                    # need not declared -> never shown
            continue
        # Explicitly selected needs are always relevant, even when the general risk or
        # duration bucket is low. The customer asked us to consider this need.
        if not is_declared_need:
            if band_rank < BAND_ORDER[a.get("min_band", "Low")]:       # risk too low for this item
                continue
            if a.get("buckets") and bucket not in a["buckets"]:        # wrong expected duration
                continue
        actions.append((bool(a.get("needs")), GuidanceItem(text=_pick(a, "text", lang), phase=a["phase"],
                                                            reason=_pick(a, "reason", lang))))

    # need-specific items first, then before -> during -> after (sorted on the flag, so it works in any language)
    phase_order = {"before": 0, "during": 1, "after": 2}
    actions.sort(key=lambda x: (not x[0], phase_order[x[1].phase]))
    items = [a for _, a in actions]
    # The backup check goes first when the battery may not last: it's the most important thing to act on.
    check = backup_check(rest, profile)
    if check and check.status != "ok":
        items.insert(0, GuidanceItem(text=check.message, phase="before",
                                     reason=_pick(_library()["backup_check"], "reason", lang)))
    return GuidanceResponse(safety=safety, actions=items, duration_bucket=bucket, backup_check=check)
