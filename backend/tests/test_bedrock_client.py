"""Bedrock client configuration tests. These never contact AWS."""
from __future__ import annotations

import app.ai.bedrock_client as bedrock_client


def test_unconfigured_model_stays_offline(monkeypatch):
    monkeypatch.delenv("BEDROCK_MODEL_ID", raising=False)
    monkeypatch.setattr(bedrock_client, "_client", None)
    assert bedrock_client.get_client() is None


def test_nova_client_uses_region_timeouts_and_standard_credential_chain(monkeypatch):
    sentinel = object()
    captured = {}

    def fake_client(service_name, **kwargs):
        captured["service_name"] = service_name
        captured.update(kwargs)
        return sentinel

    monkeypatch.setenv("BEDROCK_MODEL_ID", "amazon.nova-lite-v1:0")
    monkeypatch.setenv("AWS_REGION", "us-east-2")
    monkeypatch.setenv("BEDROCK_CONNECT_TIMEOUT_SECONDS", "4")
    monkeypatch.setenv("BEDROCK_READ_TIMEOUT_SECONDS", "15")
    monkeypatch.setenv("BEDROCK_MAX_ATTEMPTS", "3")
    monkeypatch.setattr(bedrock_client, "_client", None)

    import boto3
    monkeypatch.setattr(boto3, "client", fake_client)

    assert bedrock_client.get_client() is sentinel
    assert captured["service_name"] == "bedrock-runtime"
    assert captured["region_name"] == "us-east-2"
    assert not ({"aws_access_key_id", "aws_secret_access_key", "aws_session_token"} & captured.keys())
    config = captured["config"]
    assert config.connect_timeout == 4
    assert config.read_timeout == 15
    assert config.retries["max_attempts"] == 3
    assert config.retries["mode"] == "standard"


def test_region_falls_back_to_verified_nova_region(monkeypatch):
    sentinel = object()
    captured = {}
    monkeypatch.setenv("BEDROCK_MODEL_ID", "amazon.nova-lite-v1:0")
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    monkeypatch.setattr(bedrock_client, "_client", None)

    import boto3
    monkeypatch.setattr(boto3, "client", lambda service_name, **kwargs: captured.update(kwargs) or sentinel)

    assert bedrock_client.get_client() is sentinel
    assert captured["region_name"] == "us-east-2"


def test_guardrail_config_uses_verified_version_and_requires_identifier(monkeypatch):
    monkeypatch.setenv("BEDROCK_GUARDRAIL_ID", "vibbustudfu7")
    monkeypatch.setenv("BEDROCK_GUARDRAIL_VERSION", "1")
    assert bedrock_client.guardrail_config() == {
        "guardrailIdentifier": "vibbustudfu7",
        "guardrailVersion": "1",
    }

    monkeypatch.setenv("BEDROCK_GUARDRAIL_ID", " ")
    assert bedrock_client.guardrail_config() is None
