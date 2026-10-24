"""Test setup: the main suite always runs on the synthetic network, even when real AEP data is present,
so results are deterministic and nobody needs the data package to run `make test`.
Real-data checks live in test_real_data.py and are skipped when data/processed is empty."""
import os

os.environ.setdefault("STORMHAVEN_DATA", "synthetic")
os.environ.setdefault("STORMHAVEN_OFFLINE", "1")        # no live weather calls from tests
