"""
Send one alert message through AWS SNS (live demo texts).   Owner: Nandan
Dry-run (nothing sent, result logged) when SNS_TOPIC_ARN is unset, so dev and tests never text anyone.

Demo setup: SNS SMS sandbox -> verify each team phone -> subscribe them to the topic -> set SNS_TOPIC_ARN.
TODO (Nandan, hour 14-18): expose via an endpoint (announce the schema change) and add an audit record per send.
"""
from __future__ import annotations
import logging
import os

from app.config import ASSUMPTIONS
from app.core.privacy import scrub_text

log = logging.getLogger("stormhaven.notify")
_client = None     # created lazily so tests/dev never need AWS credentials


def _sns():
    """Shared boto3 SNS client (credentials from the standard AWS chain, never from code)."""
    global _client
    if _client is None:
        import boto3
        _client = boto3.client("sns", region_name=os.getenv("AWS_REGION", "us-east-1"))
    return _client


def send_message(text: str, trigger: str = "manual") -> dict:
    """Scrub + cap length, then publish to the topic. Returns {"sent", "dry_run", "message_id", "text"}."""
    # Scrub BEFORE truncating, so a cut can't leave half a phone number or coordinate behind.
    body = scrub_text(text)[: ASSUMPTIONS["alerts"]["sms_max_chars"]]
    topic = os.getenv("SNS_TOPIC_ARN")
    if not topic:     # no topic configured -> log what WOULD be sent, send nothing
        log.info("SNS dry-run (%s): %s", trigger, body)
        return {"sent": False, "dry_run": True, "message_id": None, "text": body}
    # Publishing to a topic fans out to every subscribed (sandbox-verified) phone.
    # "Transactional" = time-critical delivery, as opposed to "Promotional".
    resp = _sns().publish(TopicArn=topic, Message=body,
                          MessageAttributes={"AWS.SNS.SMS.SMSType": {"DataType": "String",
                                                                     "StringValue": "Transactional"}})
    return {"sent": True, "dry_run": False, "message_id": resp.get("MessageId"), "text": body}
