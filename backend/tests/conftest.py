"""Test setup: the main suite always runs on the synthetic network, even when real AEP data is present,
so results are deterministic and nobody needs the data package to run `make test`.
Real-data checks live in test_real_data.py and are skipped when data/processed is empty."""
import os

os.environ.setdefault("STORMHAVEN_DATA", "synthetic")
os.environ.setdefault("STORMHAVEN_OFFLINE", "1")        # no live weather calls from tests

import shutil
import tempfile
from pathlib import Path

import app.console
import app.core.audit

# Tests write predictions to a throwaway audit log, never the real logs/audit.jsonl that the console shows.
# Done at import time (not in a fixture) because some test files call the API while they're being collected.
_TEST_LOG_DIR = tempfile.mkdtemp(prefix="stormhaven-test-logs-")
app.core.audit.LOG_DIR = app.console.LOG_DIR = Path(_TEST_LOG_DIR)


def pytest_unconfigure(config):
    shutil.rmtree(_TEST_LOG_DIR, ignore_errors=True)
