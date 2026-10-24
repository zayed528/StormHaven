"""Run: make test  (or cd backend && pytest -q). Works on the synthetic network from minute one."""
from fastapi.testclient import TestClient
from app.main import app
from app.notify.sns_sender import send_message
from app.schemas import (ConciergeRequest, CustomerProfile, DamageItem, SimulatedUtilityStatus,
                         StormScenario)
from app.service import run_concierge

client = TestClient(app)    # calls the FastAPI app in-process; no server needed

# Each test pins one promise we make to judges/customers. If a change breaks one, the promise broke.
CKT3 = "P-31111"     # synthetic rural circuit (CKT-3)


def test_health():
    assert client.get("/api/health").json()["ok"]


# Basic shape: probability valid, range ordered, every section filled.
def test_full_pipeline():
    r = run_concierge(ConciergeRequest(premise_id=CKT3))
    assert 0 <= r.risk.probability <= 1
    assert r.restoration.p10_hours <= r.restoration.p50_hours <= r.restoration.p90_hours
    assert r.restoration.source == "model_estimate"
    assert r.guidance.safety and r.alerts.messages


# Scenario inputs must move the answer in the sensible direction (judges will try this).
def test_severity_raises_risk():
    lo = run_concierge(ConciergeRequest(premise_id=CKT3, scenario=StormScenario(severity_percentile=20)))
    hi = run_concierge(ConciergeRequest(premise_id=CKT3, scenario=StormScenario(severity_percentile=90)))
    assert hi.risk.probability > lo.risk.probability


def test_more_crews_faster():
    few = run_concierge(ConciergeRequest(premise_id=CKT3, scenario=StormScenario(crews_available=5)))
    many = run_concierge(ConciergeRequest(premise_id=CKT3, scenario=StormScenario(crews_available=60)))
    assert many.restoration.p50_hours < few.restoration.p50_hours


def test_blocked_roads_and_extra_damage_slower():
    base = run_concierge(ConciergeRequest(premise_id=CKT3))
    blocked = run_concierge(ConciergeRequest(premise_id=CKT3, scenario=StormScenario(road_access="blocked")))
    poles = run_concierge(ConciergeRequest(premise_id=CKT3, scenario=StormScenario(
        extra_damage=[DamageItem(damage_type="broken_pole", quantity=3)])))
    assert blocked.restoration.p50_hours > base.restoration.p50_hours
    assert poles.restoration.p50_hours > base.restoration.p50_hours


# Step restoration: you can't be restored before the equipment upstream of you.
def test_step_etas_non_decreasing():
    steps = run_concierge(ConciergeRequest(premise_id=CKT3)).restoration.steps
    assert steps and steps[-1].restores_your_power
    assert all(a.eta_hours <= b.eta_hours for a, b in zip(steps, steps[1:]))


# Never guess silently: unknown locations get an explicit fallback.
def test_unknown_location_falls_back():
    r = run_concierge(ConciergeRequest(premise_id="does-not-exist"))
    assert r.risk.source == "fallback" and r.risk.trust.confidence == "Low"
    assert r.restoration.source == "fallback"


# Declared needs change guidance + escalation; with no declared needs, no need-specific advice appears.
def test_declared_medical_need_changes_guidance_and_escalates():
    prof = CustomerProfile(declared_needs=["medical_device"], alerts_enrolled=True, channels=["sms"])
    r = run_concierge(ConciergeRequest(premise_id=CKT3, scenario=StormScenario(severity_percentile=85), profile=prof))
    assert any("medical" in a.text.lower() for a in r.guidance.actions)
    assert any(e.active for e in r.alerts.escalations if "medical" in e.trigger.lower())


def test_no_needs_means_no_need_specific_guidance():
    r = run_concierge(ConciergeRequest(premise_id=CKT3, scenario=StormScenario(severity_percentile=85)))
    assert not any(a.reason.startswith("You told us") for a in r.guidance.actions)


def test_declared_needs_are_included_even_at_low_risk():
    profile = CustomerProfile(declared_needs=["mobility", "infants"])
    r = run_concierge(ConciergeRequest(premise_id=CKT3, scenario=StormScenario(severity_percentile=0),
                                       profile=profile))
    text = " ".join(a.text for a in r.guidance.actions)
    assert "check on you" in text
    assert "formula" in text


# Documented rule: eligible = enrolled AND has a channel; all 4 message types are generated.
def test_alert_eligibility_rule():
    off = run_concierge(ConciergeRequest(premise_id=CKT3))
    on = run_concierge(ConciergeRequest(premise_id=CKT3, profile=CustomerProfile(alerts_enrolled=True, channels=["sms"])))
    assert not off.alerts.eligible and on.alerts.eligible
    assert set(on.alerts.messages) == {"pre_storm", "outage_confirmed", "estimate_updated", "restoration_complete"}


# Confirmed facts come only from the (simulated) utility feed, never from the model.
def test_confirmed_etr_only_from_utility_status():
    est = run_concierge(ConciergeRequest(premise_id=CKT3))
    assert est.restoration.confirmed_etr is None and not est.restoration.outage_confirmed
    conf = run_concierge(ConciergeRequest(premise_id=CKT3, utility_status=SimulatedUtilityStatus(
        outage_confirmed=True, confirmed_etr="Crews assigned. Expected by 9 PM.")))
    assert conf.restoration.outage_confirmed and conf.restoration.confirmed_etr.startswith("Crews assigned")


# Privacy: no internal IDs, phones, emails, or coordinates in anything a customer sees or receives by SMS.
def test_no_internal_ids_leak():
    r = run_concierge(ConciergeRequest(premise_id=CKT3))
    customer_text = " ".join([f.plain_language for f in r.risk.factors] +
                             [s.description for s in r.restoration.steps] + list(r.alerts.messages.values()))
    for prefix in ("FUS-", "REC-", "BRK-", "TX-", "SUB-"):
        assert prefix not in customer_text


def test_scrubber_catches_injected_pii():
    r = run_concierge(ConciergeRequest(premise_id=CKT3, utility_status=SimulatedUtilityStatus(
        outage_confirmed=True, confirmed_etr="Call 614-555-0100 or ops@example.com about FUS-311")))
    etr = r.restoration.confirmed_etr
    assert "614" not in etr and "@" not in etr and "FUS-311" not in etr


def test_sms_sender_dry_run_without_topic(monkeypatch):
    monkeypatch.delenv("SNS_TOPIC_ARN", raising=False)
    out = send_message("Test 40.12345, -83.12345 " + "x" * 500)
    assert out["dry_run"] and not out["sent"]
    assert "40.12345" not in out["text"] and len(out["text"]) <= 320


# Safety: emergency words always get the fixed 911 message first (tested offline, no Bedrock).
def test_chat_offline_and_emergency_preamble(monkeypatch):
    monkeypatch.delenv("BEDROCK_MODEL_ID", raising=False)
    hist = [{"role": "user", "content": [{"text": "There's a downed line in my yard"}]}]
    reply = client.post("/api/chat", json={"history": hist, "premise_id": CKT3}).json()["reply"]
    assert reply.startswith("SAFETY:") and "911" in reply
    calm = [{"role": "user", "content": [{"text": "Will I lose power?"}]}]
    assert not client.post("/api/chat", json={"history": calm, "premise_id": CKT3}).json()["reply"].startswith("SAFETY:")


def test_map_endpoint():
    m = client.get("/api/map?severity=70").json()
    assert m["premises"] and m["circuits"]


# "Estimate updated": never "changed from X to X"; the reason names what actually changed.
def test_estimate_update_message_uses_real_change():
    prof = CustomerProfile(alerts_enrolled=True, channels=["sms"])
    first = run_concierge(ConciergeRequest(premise_id=CKT3, profile=prof))
    assert "changed from" not in first.alerts.messages["estimate_updated"]
    before = StormScenario()
    after = StormScenario(crews_available=3)
    second = run_concierge(ConciergeRequest(premise_id=CKT3, profile=prof, scenario=after, previous_scenario=before,
                                            previous_range_text=first.restoration.range_short))
    msg = second.alerts.messages["estimate_updated"]
    assert first.restoration.range_short in msg and second.restoration.range_short in msg
    assert "fewer repair crews" in msg


# Spanish SMS contain no English risk words or range words.
def test_spanish_messages_are_localized():
    prof = CustomerProfile(alerts_enrolled=True, channels=["sms"], language="es")
    r = run_concierge(ConciergeRequest(premise_id=CKT3, scenario=StormScenario(severity_percentile=90), profile=prof))
    text = " ".join(r.alerts.messages.values())
    assert "hours" not in text and "days" not in text
    assert not any(b in r.alerts.messages["pre_storm"] for b in ("Low", "Moderate", "High"))


# Once the utility confirms an outage, the range is no longer phrased "if you lose power".
def test_confirmed_outage_changes_range_wording():
    conf = run_concierge(ConciergeRequest(premise_id=CKT3, utility_status=SimulatedUtilityStatus(outage_confirmed=True)))
    assert conf.restoration.range_text.startswith("Our estimate: power back")
    assert "model estimate" in conf.restoration.range_text


# The concierge reports which map dot represents the location, and that dot is on the map.
def test_map_point_id_is_a_map_dot():
    r = run_concierge(ConciergeRequest(premise_id="P-31112"))      # not the first home on its transformer
    ids = {p["id"] for p in client.get("/api/map?severity=50").json()["premises"]}
    assert r.map_point_id in ids


# Weather endpoint degrades gracefully: synthetic network -> no reference, no live calls.
def test_weather_endpoint_offline_synthetic():
    w = client.get("/api/weather").json()
    assert w["reference_storms"] == [] and w["forecast"]["available"] is False and "Open-Meteo" in w["credit"]
