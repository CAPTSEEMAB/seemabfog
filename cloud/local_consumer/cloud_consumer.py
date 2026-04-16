


import json
import os
import sys
import time
import threading
import logging
from datetime import datetime, timedelta
from collections import deque
from typing import Optional

import boto3
from botocore.exceptions import ClientError, EndpointConnectionError
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# Shared helpers
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from common.dynamo_helpers import (
    store_aggregate,
    store_event,
    compute_kpis,
    query_aggregates,
    query_events,
    query_latest_kpis,
    to_json_safe,
)
from common.email_alerts import send_critical_email

# ── Configuration ─────────────────────────────────

AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
AWS_ENDPOINT_URL = os.getenv("AWS_ENDPOINT_URL", "")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "")

AGGREGATES_QUEUE_URL = os.getenv("AGGREGATES_QUEUE_URL", "")
EVENTS_QUEUE_URL = os.getenv("EVENTS_QUEUE_URL", "")
AGGREGATES_TABLE = os.getenv("AGGREGATES_TABLE_NAME", "flood-aggregates")
EVENTS_TABLE = os.getenv("EVENTS_TABLE_NAME", "flood-events")
KPIS_TABLE = os.getenv("KPIS_TABLE_NAME", "flood-kpis")

AGGREGATES_QUEUE_NAME = os.getenv(
    "AGGREGATES_QUEUE_NAME",
    AGGREGATES_QUEUE_URL.rstrip("/").split("/")[-1],
)
EVENTS_QUEUE_NAME = os.getenv(
    "EVENTS_QUEUE_NAME",
    EVENTS_QUEUE_URL.rstrip("/").split("/")[-1],
)

POLL_INTERVAL_SEC = int(os.getenv("POLL_INTERVAL_SEC", "2"))
SQS_BATCH_SIZE = int(os.getenv("SQS_BATCH_SIZE", "10"))
SQS_LONG_POLL_SEC = int(os.getenv("SQS_LONG_POLL_SEC", "10"))
MESSAGE_RETENTION_PERIOD = os.getenv("MESSAGE_RETENTION_PERIOD", "345600")
API_PORT = int(os.getenv("API_PORT", "5000"))

ALERT_EMAIL_TO = os.getenv("ALERT_EMAIL_TO", "shaikhseemab10@gmail.com")
ALERT_EMAIL_FROM = os.getenv("ALERT_EMAIL_FROM", "shaikhseemab10@gmail.com")
EMAIL_ENABLED = os.getenv("EMAIL_ENABLED", "true").lower() == "true"

KPI_WEIGHTS = {
    "high_water": int(os.getenv("HIGH_WATER_WEIGHT", "5")),
    "flood_warning": int(os.getenv("FLOOD_WARNING_WEIGHT", "10")),
    "flash_flood": int(os.getenv("FLASH_FLOOD_WEIGHT", "15")),
    "max_penalty": int(os.getenv("RESILIENCE_MAX_PENALTY", "100")),
    "max_score": int(os.getenv("RESILIENCE_MAX_SCORE", "100")),
}

# ── Logging ───────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("cloud-consumer")

# ── AWS Clients ───────────────────────────────────

boto_kwargs = {"region_name": AWS_REGION}
if AWS_ENDPOINT_URL:
    boto_kwargs["endpoint_url"] = AWS_ENDPOINT_URL
if AWS_ACCESS_KEY_ID:
    boto_kwargs["aws_access_key_id"] = AWS_ACCESS_KEY_ID
if AWS_SECRET_ACCESS_KEY:
    boto_kwargs["aws_secret_access_key"] = AWS_SECRET_ACCESS_KEY

sqs_client = boto3.client("sqs", **boto_kwargs)
dynamodb = boto3.resource("dynamodb", **boto_kwargs)
ses_client = boto3.client("ses", region_name=AWS_REGION) if EMAIL_ENABLED else None

ses_config = {
    "client": ses_client,
    "sender": ALERT_EMAIL_FROM,
    "recipient": ALERT_EMAIL_TO,
} if ses_client else None

# ── Runtime State ─────────────────────────────────

consumer_stats = {
    "aggregates_processed": 0,
    "events_processed": 0,
    "kpis_computed": 0,
    "errors": 0,
    "started_at": None,
    "last_poll": None,
    "sqs_healthy": False,
    "dynamodb_healthy": False,
}

critical_notifications = deque(maxlen=200)


# ── DynamoDB Table Initialisation ─────────────────

TABLE_SCHEMAS = [
    {
        "TableName": name,
        "KeySchema": [
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        "AttributeDefinitions": [
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
        ],
    }
    for name in (AGGREGATES_TABLE, EVENTS_TABLE, KPIS_TABLE)
]


def create_tables():
    """Create DynamoDB tables (idempotent)."""
    client = boto3.client("dynamodb", **boto_kwargs)
    existing = []
    try:
        existing = client.list_tables().get("TableNames", [])
    except Exception as e:
        logger.warning(f"Cannot list tables: {e}")

    for schema in TABLE_SCHEMAS:
        name = schema["TableName"]
        if name in existing:
            logger.info(f"Table {name} exists — skipping")
            continue
        try:
            client.create_table(**schema, BillingMode="PAY_PER_REQUEST")
            logger.info(f"Created table: {name}")
        except ClientError as e:
            if e.response["Error"]["Code"] != "ResourceInUseException":
                raise
    consumer_stats["dynamodb_healthy"] = True


def create_sqs_queues():
    """Create SQS FIFO queues and discover their URLs (idempotent)."""
    global AGGREGATES_QUEUE_URL, EVENTS_QUEUE_URL
    pairs = [
        (AGGREGATES_QUEUE_NAME, "aggregates"),
        (EVENTS_QUEUE_NAME, "events"),
    ]
    for name, label in pairs:
        try:
            resp = sqs_client.create_queue(
                QueueName=name,
                Attributes={
                    "FifoQueue": "true",
                    "ContentBasedDeduplication": "true",
                    "MessageRetentionPeriod": MESSAGE_RETENTION_PERIOD,
                },
            )
            url = resp["QueueUrl"]
        except ClientError as e:
            if e.response["Error"]["Code"] == "QueueAlreadyExists":
                try:
                    url = sqs_client.get_queue_url(QueueName=name)["QueueUrl"]
                except Exception:
                    continue
            else:
                logger.warning(f"SQS create failed for {name}: {e}")
                continue

        logger.info(f"SQS ready: {name} -> {url}")
        if label == "aggregates" and not AGGREGATES_QUEUE_URL:
            AGGREGATES_QUEUE_URL = url
        elif label == "events" and not EVENTS_QUEUE_URL:
            EVENTS_QUEUE_URL = url

    consumer_stats["sqs_healthy"] = True


# ── SQS Message Processors ───────────────────────

def process_aggregate_message(body: dict, message_id: str):
    """Store aggregate via shared helper, then recompute KPIs."""
    agg_table = dynamodb.Table(AGGREGATES_TABLE)
    store_aggregate(agg_table, body, message_id)
    consumer_stats["aggregates_processed"] += 1

    station = body.get("stationId", body.get("station_id", "unknown"))
    compute_kpis(station, dynamodb.Table(EVENTS_TABLE), dynamodb.Table(KPIS_TABLE), KPI_WEIGHTS)
    consumer_stats["kpis_computed"] += 1


def process_event_message(body: dict, message_id: str):
    """Store event via shared helper, track notifications, and email CRITICAL."""
    evt_table = dynamodb.Table(EVENTS_TABLE)
    store_event(evt_table, body, message_id)
    consumer_stats["events_processed"] += 1

    severity = body.get("severity", "MEDIUM")
    station = body.get("stationId", body.get("station_id", "unknown"))

    if severity in ("HIGH", "CRITICAL"):
        critical_notifications.append({
            "id": body.get("alertId"),
            "station": station,
            "type": body.get("alertType"),
            "severity": severity,
            "message": body.get("description"),
            "value": float(body.get("triggered_value", 0)),
            "threshold": float(body.get("threshold", 0)),
            "timestamp": body.get("timestamp"),
            "stored_at": datetime.utcnow().isoformat(),
        })

    if severity == "CRITICAL" and ses_config:
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

    compute_kpis(station, dynamodb.Table(EVENTS_TABLE), dynamodb.Table(KPIS_TABLE), KPI_WEIGHTS)
    consumer_stats["kpis_computed"] += 1


# ── SQS Polling ──────────────────────────────────

def poll_queue(queue_url: str, processor_fn, label: str) -> int:
    """Long-poll one SQS queue, process messages, return count."""
    try:
        resp = sqs_client.receive_message(
            QueueUrl=queue_url,
            MaxNumberOfMessages=SQS_BATCH_SIZE,
            WaitTimeSeconds=SQS_LONG_POLL_SEC,
            AttributeNames=["All"],
        )
        messages = resp.get("Messages", [])
        if not messages:
            return 0

        for msg in messages:
            try:
                body = json.loads(msg["Body"])
                processor_fn(body, msg["MessageId"])
                sqs_client.delete_message(
                    QueueUrl=queue_url,
                    ReceiptHandle=msg["ReceiptHandle"],
                )
            except Exception as e:
                logger.error(f"Error processing {label} message: {e}")
                consumer_stats["errors"] += 1

        return len(messages)

    except (EndpointConnectionError, ClientError) as e:
        logger.warning(f"SQS poll failed ({label}): {e}")
        consumer_stats["sqs_healthy"] = False
        return 0


def sqs_consumer_loop():
    """Background thread: continuously poll both SQS queues."""
    logger.info("SQS consumer loop started")
    consumer_stats["started_at"] = datetime.utcnow().isoformat()

    for attempt in range(1, 31):
        try:
            sqs_client.list_queues()
            logger.info(f"SQS connected (attempt {attempt})")
            consumer_stats["sqs_healthy"] = True
            break
        except Exception:
            logger.info(f"Waiting for SQS... ({attempt}/30)")
            time.sleep(2)

    while True:
        try:
            agg_n = poll_queue(AGGREGATES_QUEUE_URL, process_aggregate_message, "aggregates")
            evt_n = poll_queue(EVENTS_QUEUE_URL, process_event_message, "events")

            if agg_n or evt_n:
                logger.info(
                    f"Batch: {agg_n} agg, {evt_n} evt | "
                    f"Totals: {consumer_stats['aggregates_processed']} agg, "
                    f"{consumer_stats['events_processed']} evt"
                )
            consumer_stats["last_poll"] = datetime.utcnow().isoformat()
            consumer_stats["sqs_healthy"] = True
        except Exception as e:
            logger.error(f"Consumer loop error: {e}")
            consumer_stats["sqs_healthy"] = False

        time.sleep(POLL_INTERVAL_SEC)


# ── FastAPI Dashboard API ─────────────────────────

app = FastAPI(title="Flood Early Warning — Cloud Consumer", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def _station_from_node(node_id: str) -> str:
    """Map fog node ID to station ID."""
    lower = (node_id or "fog-a").lower()
    if lower.startswith("fog-a") or lower.startswith("fog-node-a"):
        return "River-Station-A"
    return "River-Station-B"


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "sqs": "up" if consumer_stats["sqs_healthy"] else "down",
        "dynamodb": "up" if consumer_stats["dynamodb_healthy"] else "down",
        "consumer": consumer_stats,
    }


@app.get("/api/aggregates")
async def get_aggregates(
    stationId: str = Query(..., description="Station ID"),
    hours: int = Query(1, description="Lookback hours"),
):
    threshold = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
    items = query_aggregates(dynamodb.Table(AGGREGATES_TABLE), stationId, threshold)
    return to_json_safe({"stationId": stationId, "aggregates": items, "count": len(items)})


@app.get("/api/events")
async def get_events(
    stationId: str = Query(..., description="Station ID"),
    limit: int = Query(50, description="Max events"),
):
    items = query_events(dynamodb.Table(EVENTS_TABLE), stationId, limit)
    return to_json_safe({"stationId": stationId, "events": items, "count": len(items)})


@app.get("/api/kpis")
async def get_kpis(stationId: str = Query(..., description="Station ID")):
    kpis = query_latest_kpis(dynamodb.Table(KPIS_TABLE), stationId)
    return to_json_safe({"stationId": stationId, "kpis": kpis})


@app.get("/api/notifications")
async def get_notifications(limit: int = Query(30)):
    recent = list(critical_notifications)[-limit:][::-1]
    return {"notifications": recent, "count": len(recent), "timestamp": datetime.utcnow().isoformat()}


@app.get("/api/summary")
async def get_summary(
    stationId: str = Query(..., description="Station ID"),
    minutes: int = Query(10, description="Lookback minutes"),
    since: Optional[str] = Query(None, description="ISO timestamp"),
):
    threshold = since or (datetime.utcnow() - timedelta(minutes=minutes)).isoformat()
    aggregates = query_aggregates(dynamodb.Table(AGGREGATES_TABLE), stationId, threshold)
    events = query_events(dynamodb.Table(EVENTS_TABLE), stationId, limit=20)
    kpis = query_latest_kpis(dynamodb.Table(KPIS_TABLE), stationId)
    station_notifs = [n for n in list(critical_notifications)[-20:] if n.get("station") == stationId][::-1]

    return to_json_safe({
        "stationId": stationId,
        "kpis": kpis,
        "latest_aggregate": aggregates[-1] if aggregates else {},
        "aggregates": aggregates,
        "aggregates_count": len(aggregates),
        "events": events,
        "events_count": len(events),
        "notifications": station_notifs,
        "since": threshold,
    })


@app.get("/api/fog-status")
async def fog_status(nodeId: str = Query(..., description="Fog node ID")):
    station = _station_from_node(nodeId)
    status = {
        "nodeId": nodeId,
        "stationId": station,
        "lastSeen": consumer_stats.get("last_poll") or datetime.utcnow().isoformat(),
        "rates_10s": {"incoming_eps": 0, "outgoing_mps": 0, "reduction_pct": 0},
        "spool": {"pending_count": 0},
        "counters": {"alerts_total": consumer_stats.get("events_processed", 0)},
    }
    try:
        agg_table = dynamodb.Table(AGGREGATES_TABLE)
        resp = agg_table.query(
            KeyConditionExpression="PK = :pk",
            ExpressionAttributeValues={":pk": f"{station}#aggregates"},
            ScanIndexForward=False, Limit=1,
        )
        items = resp.get("Items", [])
        if items:
            latest = items[0]
            status["latest_aggregate"] = latest
            status["rates_10s"]["incoming_eps"] = latest.get("metrics_count", 0) / 10.0
            status["rates_10s"]["outgoing_mps"] = 1.0
            status["rates_10s"]["reduction_pct"] = latest.get("bandwidth_reduction_pct", 0) or 0
    except Exception:
        pass
    return to_json_safe(status)


@app.get("/api/fog-notifications")
async def fog_notifications(nodeId: str = Query(...), limit: int = Query(50)):
    station = _station_from_node(nodeId)
    items = query_events(dynamodb.Table(EVENTS_TABLE), station, limit)
    notifs = [
        {
            "id": it.get("alertId"),
            "alert_id": it.get("alertId"),
            "station": it.get("stationId"),
            "type": it.get("alertType"),
            "severity": it.get("severity"),
            "message": it.get("description"),
            "value": float(it["triggered_value"]) if it.get("triggered_value") is not None else None,
            "threshold": float(it["threshold"]) if it.get("threshold") is not None else None,
            "timestamp": it.get("timestamp"),
        }
        for it in items
    ]
    return {"notifications": notifs, "count": len(notifs)}


# ── Startup ───────────────────────────────────────

@app.on_event("startup")
async def startup():
    for attempt in range(1, 31):
        try:
            create_tables()
            break
        except Exception as e:
            logger.info(f"Waiting for DynamoDB... ({attempt}/30): {e}")
            time.sleep(2)

    for attempt in range(1, 31):
        try:
            create_sqs_queues()
            break
        except Exception as e:
            logger.info(f"Waiting for SQS... ({attempt}/30): {e}")
            time.sleep(2)

    logger.info(f"Queue URLs: agg={AGGREGATES_QUEUE_URL}, evt={EVENTS_QUEUE_URL}")
    thread = threading.Thread(target=sqs_consumer_loop, daemon=True)
    thread.start()
    logger.info(f"Cloud consumer started on port {API_PORT}")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=API_PORT)
