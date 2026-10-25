"""Fail-closed policy helpers for the internet-facing synthetic demo."""
from __future__ import annotations

import os

from fastapi import HTTPException


def enabled() -> bool:
    return os.getenv("STORMHAVEN_PUBLIC_DEMO", "").strip().lower() in {"1", "true", "yes"}


def validate_environment() -> None:
    """Reject any public-demo configuration that could select private data."""
    if not enabled():
        return
    if os.getenv("STORMHAVEN_DATA", "").strip().lower() != "synthetic":
        raise RuntimeError("Public demo requires STORMHAVEN_DATA=synthetic")
    if os.getenv("STORMHAVEN_S3_ENABLED", "").strip().lower() in {"1", "true", "yes"}:
        raise RuntimeError("Public demo prohibits S3 data loading")


def require_demo_location(store, premise_id: str | None, circuit_id: str | None) -> None:
    """Only an existing opaque map token from the synthetic store is public input."""
    if not enabled():
        return
    from app.core.topology import transformer_for_token

    if not store.is_synthetic:
        raise RuntimeError("Public demo loaded a non-synthetic store")
    if circuit_id or not premise_id or transformer_for_token(store, premise_id) is None:
        raise HTTPException(status_code=400, detail="Select a location from the synthetic demo map.")
