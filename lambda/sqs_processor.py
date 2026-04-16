import json
import os
import logging

import boto3

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from common.dynamo_helpers import store_aggregate, store_event, compute_kpis
from common.email_alerts import send_critical_email

logger = logging.getLogger()
logger.setLevel(logging.INFO)

REGION = os.getenv("AWS_REGION", "us-east-1")
AGGREGATES_TABLE = os.getenv("AGGREGATES_TABLE_NAME", "flood-aggregates")
EVENTS_TABLE = os.getenv("EVENTS_TABLE_NAME", "flood-events")
KPIS_TABLE = os.getenv("KPIS_TABLE_NAME", "flood-kpis")
ALERT_EMAIL = os.getenv("ALERT_EMAIL", "seemab.mudassir@gmail.com")
SENDER_EMAIL = os.getenv("SENDER_EMAIL", "seemab.mudassir@gmail.com")
SEND_EMAILS = os.getenv("SEND_EMAIL_ALERTS", "true").lower() == "true"

dynamodb = boto3.resource("dynamodb", region_name=REGION)
ses = boto3.client("ses", region_name=REGION) if SEND_EMAILS else None

agg_table = dynamodb.Table(AGGREGATES_TABLE)
events_table = dynamodb.Table(EVENTS_TABLE)
kpis_table = dynamodb.Table(KPIS_TABLE)

ses_config = {
    "client": ses,
    "sender": SENDER_EMAIL,
    "recipient": ALERT_EMAIL,
} if ses else None


def handler(event, _context):
    records = event.get("Records", [])
    logger.info(f"Processing {len(records)} SQS records")

    for record in records:
        try:
            body = json.loads(record.get("body", "{}"))
            message_id = record.get("messageId", "unknown")
            msg_type = body.get("type", "unknown")

            if msg_type == "aggregate":
                store_aggregate(agg_table, body, message_id)
                station = body.get("stationId", body.get("station_id", "unknown"))
                compute_kpis(station, events_table, kpis_table)

            elif msg_type in ("alert", "event"):
                store_event(events_table, body, message_id)
                _maybe_send_alert(body)

            else:
                logger.warning(f"Unknown message type: {msg_type}")

        except Exception as exc:
            logger.error(f"Error processing record: {exc}", exc_info=True)

    return {"statusCode": 200, "body": f"Processed {len(records)} records"}


def _maybe_send_alert(body: dict):
    severity = body.get("severity", "").upper()
    if severity != "CRITICAL" or not ses_config:
        return
    station = body.get("stationId", body.get("station_id", "unknown"))
    send_critical_email(
        ses_config=ses_config,
        station=station,
        alert_type=body.get("alertType", "alert"),
        severity=severity,
        description=body.get("description", ""),
        value=body.get("triggered_value", 0),
        threshold=body.get("threshold", 0),
        timestamp=body.get("timestamp", ""),
    )
