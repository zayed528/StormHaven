"""Thin Bedrock wrapper. Returns None if Bedrock isn't configured so the app degrades gracefully."""
from __future__ import annotations
import os

_client = None     # created lazily on first use and then reused


def get_client():
    """bedrock-runtime client, or None when BEDROCK_MODEL_ID is blank (offline mode -> deterministic replies).
    Credentials come from the standard AWS chain (env vars, ~/.aws, or the instance role), never from code."""
    global _client
    if _client is None and os.getenv("BEDROCK_MODEL_ID"):
        import boto3          # imported here so offline dev doesn't need AWS set up
        from botocore.config import Config
        config = Config(
            connect_timeout=float(os.getenv("BEDROCK_CONNECT_TIMEOUT_SECONDS", "3")),
            read_timeout=float(os.getenv("BEDROCK_READ_TIMEOUT_SECONDS", "12")),
            retries={"max_attempts": int(os.getenv("BEDROCK_MAX_ATTEMPTS", "2")), "mode": "standard"},
        )
        _client = boto3.client("bedrock-runtime", region_name=os.getenv("AWS_REGION", "us-east-1"), config=config)
    return _client


def guardrail_config() -> dict | None:
    """Bedrock Guardrail settings for converse(), or None if no guardrail is configured."""
    gid = os.getenv("BEDROCK_GUARDRAIL_ID")
    return {"guardrailIdentifier": gid, "guardrailVersion": os.getenv("BEDROCK_GUARDRAIL_VERSION", "DRAFT")} if gid else None
