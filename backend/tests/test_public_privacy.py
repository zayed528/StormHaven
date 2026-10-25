from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest

from app import public_demo


def test_public_environment_fails_closed(monkeypatch):
    monkeypatch.setenv("STORMHAVEN_PUBLIC_DEMO", "true")
    monkeypatch.delenv("STORMHAVEN_DATA", raising=False)
    with pytest.raises(RuntimeError, match="requires STORMHAVEN_DATA=synthetic"):
        public_demo.validate_environment()

    monkeypatch.setenv("STORMHAVEN_DATA", "synthetic")
    monkeypatch.setenv("STORMHAVEN_S3_ENABLED", "true")
    with pytest.raises(RuntimeError, match="prohibits S3"):
        public_demo.validate_environment()


def test_private_environment_policy_is_unchanged(monkeypatch):
    monkeypatch.delenv("STORMHAVEN_PUBLIC_DEMO", raising=False)
    monkeypatch.setenv("STORMHAVEN_DATA", "real")
    monkeypatch.setenv("STORMHAVEN_S3_ENABLED", "true")
    public_demo.validate_environment()


def test_public_api_exposes_only_synthetic_demo_locations(tmp_path):
    root = Path(__file__).resolve().parents[2]
    script = r'''
from pathlib import Path
from fastapi.testclient import TestClient
import app.core.audit as audit
from app.main import app

audit.LOG_DIR = Path(os.environ["PUBLIC_AUDIT_DIR"])
c = TestClient(app)

assert c.get("/docs").status_code == 404
assert c.get("/openapi.json").status_code == 404
assert c.get("/api/weather").status_code == 404
assert c.get("/api/console/circuits").status_code == 404
assert c.post("/api/notify", json={}).status_code == 404
assert c.get("/api/health").json() == {"ok": True, "mode": "public_demo"}

layers = c.get("/api/map?severity=50").json()
assert layers["premises"]
assert all(set(p) == {"id", "lat", "lon", "n", "p", "band"} for p in layers["premises"])
assert all(p["id"].startswith("N-") for p in layers["premises"])
assert not any("circuit_id" in p for p in layers["premises"])

token = layers["premises"][0]["id"]
assert c.get("/api/locate", params={"premise_id": token}).status_code == 200
assert c.get("/api/locate", params={"premise_id": "123456789"}).status_code == 400
assert c.get("/api/locate", params={"lat": 1, "lon": 2}).status_code == 400

base = {"scenario": {}, "profile": {}}
assert c.post("/api/concierge", json={**base, "premise_id": "123456789"}).status_code == 400
assert c.post("/api/concierge", json={**base, "circuit_id": "anything"}).status_code == 400
answer = c.post("/api/concierge", json={**base, "premise_id": token})
assert answer.status_code == 200
assert answer.json()["audit_id"].startswith("demo-")

chat = {**base, "premise_id": token,
        "history": [{"role": "user", "content": [{"text": "What is my outage risk?"}]}]}
assert c.post("/api/chat", json=chat).status_code == 200
assert c.post("/api/chat", json={**chat, "premise_id": "123456789"}).status_code == 400
assert not (audit.LOG_DIR / "audit.jsonl").exists()
'''
    env = os.environ.copy()
    env.update({
        "PYTHONPATH": str(root / "backend"),
        "STORMHAVEN_PUBLIC_DEMO": "true",
        "STORMHAVEN_DATA": "synthetic",
        "STORMHAVEN_S3_ENABLED": "false",
        "BEDROCK_MODEL_ID": "",
        "PUBLIC_AUDIT_DIR": str(tmp_path),
    })
    subprocess.run([sys.executable, "-c", "import os\n" + script], cwd=root, env=env,
                   check=True, capture_output=True, text=True)
