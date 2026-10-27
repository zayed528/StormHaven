from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest

import app.main as main


def test_production_cors_requires_explicit_origins(monkeypatch):
    monkeypatch.setenv("STORMHAVEN_PRODUCTION", "true")
    monkeypatch.delenv("STORMHAVEN_CORS_ORIGINS", raising=False)
    with pytest.raises(RuntimeError, match="explicit origins"):
        main._cors_origins()


def test_production_cors_rejects_wildcard(monkeypatch):
    monkeypatch.setenv("STORMHAVEN_PRODUCTION", "true")
    monkeypatch.setenv("STORMHAVEN_CORS_ORIGINS", "*")
    with pytest.raises(RuntimeError, match="explicit origins"):
        main._cors_origins()


def test_cors_supports_comma_separated_origins(monkeypatch):
    monkeypatch.delenv("STORMHAVEN_PRODUCTION", raising=False)
    monkeypatch.setenv("STORMHAVEN_CORS_ORIGINS", "https://stormhaven.vercel.app, https://preview.example")
    assert main._cors_origins() == ["https://stormhaven.vercel.app", "https://preview.example"]


def test_startup_preflight_rejects_synthetic_store(monkeypatch):
    from types import SimpleNamespace

    import app.startup as startup

    monkeypatch.setattr(startup, "get_store", lambda: SimpleNamespace(is_synthetic=True))
    with pytest.raises(RuntimeError, match="synthetic data"):
        startup.main()


def test_public_startup_accepts_only_explicit_synthetic_store(monkeypatch):
    from types import SimpleNamespace
    import app.startup as startup

    monkeypatch.setenv("STORMHAVEN_PUBLIC_DEMO", "true")
    monkeypatch.setenv("STORMHAVEN_DATA", "synthetic")
    monkeypatch.setenv("STORMHAVEN_S3_ENABLED", "false")
    monkeypatch.setattr(startup, "get_store", lambda: SimpleNamespace(is_synthetic=True))
    startup.main()

    monkeypatch.setattr(startup, "get_store", lambda: SimpleNamespace(is_synthetic=False))
    with pytest.raises(RuntimeError, match="non-synthetic"):
        startup.main()


def test_route_flag_defaults(monkeypatch):
    # Operator console: on unless explicitly turned off. Notify: off unless explicitly turned on.
    monkeypatch.delenv("STORMHAVEN_ENABLE_OPERATOR_ROUTES", raising=False)
    monkeypatch.delenv("STORMHAVEN_ENABLE_NOTIFY", raising=False)
    assert main._env_enabled_by_default("STORMHAVEN_ENABLE_OPERATOR_ROUTES") is True
    assert main._env_enabled("STORMHAVEN_ENABLE_NOTIFY") is False
    for off in ("false", "0", "no", "off"):
        monkeypatch.setenv("STORMHAVEN_ENABLE_OPERATOR_ROUTES", off)
        assert main._env_enabled_by_default("STORMHAVEN_ENABLE_OPERATOR_ROUTES") is False


def _routes_in_fresh_process(flags: dict, checks: str):
    root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env.pop("STORMHAVEN_ENABLE_OPERATOR_ROUTES", None)
    env.pop("STORMHAVEN_ENABLE_NOTIFY", None)
    env.update({"PYTHONPATH": str(root / "backend"), "STORMHAVEN_DATA": "synthetic",
                "STORMHAVEN_CORS_ORIGINS": "http://localhost:5173", **flags})
    command = [sys.executable, "-c",
               "from fastapi.testclient import TestClient; from app.main import app; c=TestClient(app); " + checks]
    subprocess.run(command, cwd=root, env=env, check=True, capture_output=True, text=True)


def test_console_on_and_notify_off_by_default_in_a_fresh_process():
    _routes_in_fresh_process({}, "assert c.get('/api/console/circuits').status_code != 404; "
                                 "assert c.get('/api/planner/storms').status_code != 404; "
                                 "assert c.post('/api/notify', json={'message_key': 'pre_storm'}).status_code == 404")


def test_console_can_be_turned_off_in_a_fresh_process():
    _routes_in_fresh_process({"STORMHAVEN_ENABLE_OPERATOR_ROUTES": "false"},
                             "assert c.get('/api/console/circuits').status_code == 404; "
                             "assert c.get('/api/planner/storms').status_code == 404")


def test_startup_and_container_configuration():
    root = Path(__file__).resolve().parents[2]
    dockerfile = (root / "Dockerfile").read_text()
    dockerignore = (root / ".dockerignore").read_text()
    assert "python -m app.startup" in dockerfile
    assert "uvicorn app.main:app --host 0.0.0.0" in dockerfile
    assert "USER stormhaven" in dockerfile
    for excluded in (".env", "AWS_ACCESS_KEY_ID", "data/processed", "data/raw", "logs"):
        assert excluded in dockerignore
