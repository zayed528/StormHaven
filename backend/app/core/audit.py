"""Append-only audit trail: every prediction is reproducible. JSONL locally; swap to DynamoDB later.   Owner: Nandan"""
from __future__ import annotations
import json
import logging
import uuid
from datetime import datetime, timezone
from app.config import LOG_DIR

logger = logging.getLogger(__name__)

# Bump when the risk/restoration logic changes, so old audit records can be told apart.
MODEL_VERSION = "v0-scorecard"


def log_prediction(request: dict, response: dict) -> str:
    """Append one record (full request + summary of the answer) to logs/audit.jsonl; return its ID.
    The ID is returned to the client as ConciergeResponse.audit_id so any answer can be traced later.
    logs/ is git-ignored. Note: requests include declared needs, so treat this file as sensitive."""
    audit_id = uuid.uuid4().hex[:12]           # short random ID, not derived from customer data
    rec = {"audit_id": audit_id, "ts": datetime.now(timezone.utc).isoformat(),
           "model_version": MODEL_VERSION, "request": request, "response": response}
    try:
        LOG_DIR.mkdir(exist_ok=True)
        with open(LOG_DIR / "audit.jsonl", "a") as f:     # append-only: never rewrite past records
            f.write(json.dumps(rec, default=str) + "\n")
    except OSError as exc:
        # Prediction delivery is more important than the local demo audit file. Log only the error type.
        logger.warning("Prediction audit unavailable (%s)", type(exc).__name__)
    return audit_id
