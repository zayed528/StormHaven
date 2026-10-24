"""Loads config/assumptions.yaml once. Import ASSUMPTIONS anywhere.   Owner: Nandan"""
from pathlib import Path
import yaml

# All paths are absolute (from this file's location), so the API works no matter where it's launched from.
ROOT = Path(__file__).resolve().parents[2]          # repo root
DATA_PROCESSED = ROOT / "data" / "processed"        # pipeline outputs (git-ignored)
LOG_DIR = ROOT / "logs"                             # audit.jsonl (git-ignored)
CONTENT_DIR = Path(__file__).resolve().parent / "content"   # guidance library + message templates

# Read once at import. Editing assumptions.yaml requires restarting the API (uvicorn --reload watches .py only).
with open(ROOT / "config" / "assumptions.yaml") as f:
    ASSUMPTIONS = yaml.safe_load(f)
