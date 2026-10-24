"""
StormHaven API contracts. FREEZE THESE AT HOUR 1 — frontend and backend build against them.
Any change here gets announced in the team chat and reflected in docs/API_CONTRACT.md.
Pydantic validates every request against these models, so bad input is rejected with a 422 before any engine runs.
"""
from __future__ import annotations
from enum import Enum
from typing import Literal, Optional
from pydantic import BaseModel, Field


# ---------- shared inputs ----------
class AccessLevel(str, Enum):
    """How easily crews can reach damage. Scales repair labor and queue wait (assumptions.yaml)."""
    normal = "normal"
    limited = "limited"
    blocked = "blocked"


class DamageItem(BaseModel):
    """Damage a judge (or the utility) says is on the line; forced into every simulated storm."""
    damage_type: str = Field(..., examples=["broken_pole"])    # a key in labor_hours.csv / repair_recipes
    quantity: int = Field(1, ge=1, le=50)
    equipment_id: Optional[str] = None   # anonymized; None = "somewhere on my path"


class StormScenario(BaseModel):
    """The knobs the customer/judge can turn. Bounds here stop nonsense input (including from the LLM tool call)."""
    severity_percentile: float = Field(50, ge=0, le=100,
        description="How bad vs. historical events (50 = median storm)")
    crews_available: int = Field(20, ge=1, le=500)     # storm-wide crews; divides the queue wait
    road_access: AccessLevel = AccessLevel.normal
    extra_damage: list[DamageItem] = []


class DeclaredNeed(str, Enum):
    """Opt-in ONLY. We never infer these."""
    medical_device = "medical_device"
    refrigerated_medication = "refrigerated_medication"
    mobility = "mobility"
    infants = "infants"
    pets = "pets"
    critical_facility = "critical_facility"
    works_from_home = "works_from_home"


class Channel(str, Enum):
    """Where alerts go. Only sms is wired for the demo (notify/sns_sender.py)."""
    sms = "sms"
    email = "email"
    push = "push"
    voice = "voice"


class CustomerProfile(BaseModel):
    """What the customer chose to tell us. No names, addresses, or contact details ever enter the API."""
    declared_needs: list[DeclaredNeed] = []
    alerts_enrolled: bool = False
    channels: list[Channel] = []        # channel TYPES only, never the phone number/email itself
    language: Literal["en", "es"] = "en"   # picks the message template set


class SimulatedUtilityStatus(BaseModel):
    """Stand-in for the utility's outage-management feed (demo toggle).
    The ONLY way restoration.confirmed_etr gets set; the model never fills it."""
    outage_confirmed: bool = False
    confirmed_etr: Optional[str] = Field(None, max_length=120, examples=["Crews assigned. Expected by 9 PM."])


class ConciergeRequest(BaseModel):
    """Body of POST /api/concierge. Give premise_id (preferred) or circuit_id; neither -> fallback answer."""
    premise_id: Optional[str] = None
    circuit_id: Optional[str] = None
    scenario: StormScenario = StormScenario()
    profile: CustomerProfile = CustomerProfile()
    previous_range_text: Optional[str] = None   # last ETR shown -> drives "estimate updated" message
    utility_status: Optional[SimulatedUtilityStatus] = None   # None = no utility info yet


# ---------- shared outputs ----------
# Every answer says where it came from: our model, the utility (confirmed), or a fallback (we couldn't predict).
SourceTag = Literal["model_estimate", "confirmed", "fallback"]


class Factor(BaseModel):
    """One reason behind the risk estimate."""
    name: str                         # machine name, e.g. "history:fuse", "storm_severity"
    direction: Literal["raises", "lowers"]
    weight: float                     # relative importance, 0-1
    plain_language: str               # what the customer reads


class TrustInfo(BaseModel):
    """The responsible-AI block attached to each estimate."""
    confidence: Literal["High", "Medium", "Low"]
    assumptions: list[str] = []       # what we assumed to get this answer
    missing_data: list[str] = []      # what we don't know
    could_change_if: list[str] = []   # conditions that would move the answer


class RiskResponse(BaseModel):
    """Answer to "Will I lose power?"."""
    source: SourceTag = "model_estimate"
    probability: float                # P(outage) in [0,1]; 0.0 with band "Unknown" on fallback
    band: str                         # Low | Moderate | High | Very High | Unknown (fallback)
    factors: list[Factor]
    trust: TrustInfo
    resolved_level: Literal["premise", "circuit", "none"]   # how precisely the location was matched


class RestorationStep(BaseModel):
    """One repair in the likely restoration order (upstream first)."""
    order: int
    description: str                  # friendly equipment name + share of the area it serves
    eta_hours: float                  # median hours from outage; never decreases from one step to the next
    restores_your_power: bool         # True on the last step (the repair nearest your home)


class Driver(BaseModel):
    """A "what if" that moves the estimate, e.g. more crews or blocked roads."""
    name: str                         # more_crews | roads_blocked | stronger_storm
    delta_p50_hours: float            # negative = faster
    plain_language: str


class RestorationResponse(BaseModel):
    """Answer to "How long could restoration take?". Always a range, never one promised time."""
    source: SourceTag = "model_estimate"
    p10_hours: float                  # optimistic end
    p50_hours: float                  # best guess
    p90_hours: float                  # pessimistic end
    range_text: str                   # customer-facing sentence built from the three numbers
    steps: list[RestorationStep]
    drivers: list[Driver]
    trust: TrustInfo
    outage_confirmed: bool = False        # from utility_status only
    confirmed_etr: Optional[str] = None   # from utility_status only (simulated in demo)


class GuidanceItem(BaseModel):
    """One piece of curated advice from content/guidance_library.yaml."""
    text: str
    phase: Literal["before", "during", "after"]
    is_safety: bool = False           # True -> shown in the red Safety banner
    reason: str = ""                  # why this applies to YOU


class GuidanceResponse(BaseModel):
    """Answer to "What should I do to prepare?"."""
    safety: list[GuidanceItem]
    actions: list[GuidanceItem]
    duration_bucket: str              # short | day | multi_day | extended (from P90)


class ScheduledAlert(BaseModel):
    """One alert we would send, and when."""
    trigger: str                      # pre_storm | outage_confirmed | estimate_updated | restoration_complete
    timing: str
    channel: Channel


class Escalation(BaseModel):
    """A situation where a human (or 911) takes over from automation."""
    trigger: str
    action: str
    active: bool                      # True = triggered for this customer right now


class AlertsResponse(BaseModel):
    """Answer to "Do I qualify for outage alerts?"."""
    eligible: bool
    rule_applied: str                 # the documented rule, in words
    reasons: list[str]                # why this customer is or isn't eligible
    schedule: list[ScheduledAlert]
    escalations: list[Escalation]
    messages: dict[str, str]          # scenario -> message text


class ConciergeResponse(BaseModel):
    """Body returned by POST /api/concierge: all four answers plus an ID for the audit log."""
    risk: RiskResponse
    restoration: RestorationResponse
    guidance: GuidanceResponse
    alerts: AlertsResponse
    audit_id: str
