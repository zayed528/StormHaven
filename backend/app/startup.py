"""Production startup preflight for the ECS container."""
from __future__ import annotations

from app.core.data_loader import get_store


def main() -> None:
    store = get_store()
    if store.is_synthetic:
        raise RuntimeError("Real-data startup preflight failed: synthetic data is loaded")


if __name__ == "__main__":
    main()
