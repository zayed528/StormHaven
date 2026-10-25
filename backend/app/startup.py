"""Production startup preflight for the ECS container."""
from __future__ import annotations

from app.core.data_loader import get_store
from app.public_demo import enabled as public_demo_enabled, validate_environment


def main() -> None:
    validate_environment()
    store = get_store()
    if public_demo_enabled():
        if not store.is_synthetic:
            raise RuntimeError("Public demo startup failed: non-synthetic data is loaded")
    elif store.is_synthetic:
        raise RuntimeError("Real-data startup preflight failed: synthetic data is loaded")


if __name__ == "__main__":
    main()
