"""Customer-experience polish (owner: Akshat, branch feat/akshat-polish): medical backup check, offline chat routing,
Spanish chat. Runs on the synthetic network, offline (no Bedrock)."""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas import ConciergeRequest, CustomerProfile, StormScenario
from app.service import run_concierge

client = TestClient(app)
HOME = "P-31111"
MEDICAL = {"declared_needs": ["medical_device"], "alerts_enrolled": True, "channels": ["sms"]}


def _answer(backup=None, needs=("medical_device",), lang="en", severity=90):
    prof = CustomerProfile(declared_needs=list(needs), alerts_enrolled=True, channels=["sms"],
                           backup_power_hours=backup, language=lang)
    return run_concierge(ConciergeRequest(premise_id=HOME, scenario=StormScenario(severity_percentile=severity),
                                          profile=prof))


# ---------------------------------------------------------------- medical backup check
def test_backup_check_status_follows_the_restoration_range():
    base = _answer(backup=None)
    p50, p90 = base.restoration.p50_hours, base.restoration.p90_hours
    assert base.guidance.backup_check is None                      # no hours given -> no check
    short = _answer(backup=max(0.5, p50 / 2)).guidance.backup_check
    tight = _answer(backup=(p50 + p90) / 2).guidance.backup_check
    ok = _answer(backup=p90 * 2).guidance.backup_check
    assert (short.status, tight.status, ok.status) == ("short", "tight", "ok")
    assert "shorter than our best guess" in short.message


def test_backup_check_only_for_declared_medical_device():
    r = _answer(backup=1, needs=("pets",))
    assert r.guidance.backup_check is None                          # never inferred, never applied to other needs


def test_short_backup_goes_first_and_escalates_to_a_person():
    r = _answer(backup=0.5)
    assert r.guidance.actions[0].text == r.guidance.backup_check.message
    esc = {e.trigger: e.active for e in r.alerts.escalations}
    assert esc["Declared medical device whose backup may run out before power returns"] is True
    ok = _answer(backup=10_000 / 100)                               # 100 h: outlasts the range
    if ok.guidance.backup_check.status == "ok":
        assert not {e.trigger: e.active for e in ok.alerts.escalations}[
            "Declared medical device whose backup may run out before power returns"]


def test_backup_check_spanish():
    r = _answer(backup=0.5, lang="es")
    assert "respaldo" in r.guidance.backup_check.message


def test_backup_hours_are_bounded():
    assert client.post("/api/concierge", json={"premise_id": HOME, "profile": {**MEDICAL, "backup_power_hours": -1}}
                       ).status_code == 422


# ---------------------------------------------------------------- chat (offline)
def _chat(q, lang="en", monkeypatch=None):
    return client.post("/api/chat", json={"history": [{"role": "user", "content": [{"text": q}]}],
                                          "premise_id": HOME, "profile": {"language": lang}}).json()["reply"]


@pytest.fixture
def offline(monkeypatch):
    monkeypatch.delenv("BEDROCK_MODEL_ID", raising=False)
    import app.ai.bedrock_client as bc
    monkeypatch.setattr(bc, "_client", None, raising=False)


def test_offline_chat_answers_each_question_differently(offline):
    replies = {q: _chat(q) for q in ["Will I lose power?", "How long could restoration take?",
                                     "What should I do to prepare?", "Do I qualify for outage alerts?"]}
    assert len(set(replies.values())) == 4                          # no more identical answers
    assert "eligible" in replies["Do I qualify for outage alerts?"]
    assert "most likely" in replies["How long could restoration take?"]


def test_spanish_chat_is_on_topic_and_in_spanish(offline):
    reply = _chat("¿Me quedaré sin luz?", lang="es")
    assert "riesgo de apagón" in reply and "Pregúnteme" not in reply
    assert "califica" in _chat("¿Califico para las alertas de apagón?", lang="es")


def test_real_data_replies_do_not_sound_like_a_demo(offline):
    assert "challenge dataset" not in _chat("Will I lose power?")
