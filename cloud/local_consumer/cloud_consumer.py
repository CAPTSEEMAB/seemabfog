"""
Local Cloud Consumer
Bridges the gap between fog layer and cloud layer for local development.
Replaces: SQS Lambda triggers + DynamoDB Lambdas + API Gateway + Dashboard API Lambda.

This service:
  1. Creates DynamoDB tables in LocalStack on startup
  2. Polls SQS FIFO queues (aggregates + events)
  3. Processes messages exactly like the real Lambda functions
  4. Serves a REST API identical to the production API Gateway
"""

import json
import os
import sys
import time
import threading
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

import boto3
from botocore.exceptions import ClientError, EndpointConnectionError
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# ─────────────────── Configuration ───────────────────

AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
AWS_ENDPOINT_URL = os.getenv("AWS_ENDPOINT_URL", "http://localstack:4566")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "test")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "test")

AGGREGATES_QUEUE_URL = os.getenv(
    "AGGREGATES_QUEUE_URL",
    "http://localstack:4566/000000000000/smart-traffic-aggregates-queue.fifo",
)
EVENTS_QUEUE_URL = os.getenv(
    "EVENTS_QUEUE_URL",
    "http://localstack:4566/000000000000/smart-traffic-events-queue.fifo",
)

AGGREGATES_TABLE = os.getenv("AGGREGATES_TABLE_NAME", "smart-traffic-aggregates")
EVENTS_TABLE = os.getenv("EVENTS_TABLE_NAME", "smart-traffic-events")
KPIS_TABLE = os.getenv("KPIS_TABLE_NAME", "smart-traffic-kpis")

# Queue names (for creation) — derived from URL or explicit env var
AGGREGATES_QUEUE_NAME = os.getenv("AGGREGATES_QUEUE_NAME", AGGREGATES_QUEUE_URL.rstrip("/").split("/")[-1])
EVENTS_QUEUE_NAME = os.getenv("EVENTS_QUEUE_NAME", EVENTS_QUEUE_URL.rstrip("/").split("/")[-1])

POLL_INTERVAL_SEC = int(os.getenv("POLL_INTERVAL_SEC", "2"))
SQS_BATCH_SIZE = int(os.getenv("SQS_BATCH_SIZE", "10"))
SQS_LONG_POLL_SEC = int(os.getenv("SQS_LONG_POLL_SEC", "10"))
MESSAGE_RETENTION_PERIOD = os.getenv("MESSAGE_RETENTION_PERIOD", "345600")
API_PORT = int(os.getenv("API_PORT", "5000"))

# Safety score weights (shared with Lambda — keep in sync via env vars)
SAFETY_SPEEDING_WEIGHT = int(os.getenv("SAFETY_SPEEDING_WEIGHT", "5"))
SAFETY_INCIDENT_WEIGHT = int(os.getenv("SAFETY_INCIDENT_WEIGHT", "10"))
SAFETY_MAX_PENALTY = int(os.getenv("SAFETY_MAX_PENALTY", "100"))
SAFETY_MAX_SCORE = int(os.getenv("SAFETY_MAX_SCORE", "100"))

# ─────────────────── Logging ───────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("cloud-consumer")

# ─────────────────── AWS Clients ───────────────────

boto_kwargs = {
    "region_name": AWS_REGION,
    "endpoint_url": AWS_ENDPOINT_URL,
    "aws_access_key_id": AWS_ACCESS_KEY_ID,
    "aws_secret_access_key": AWS_SECRET_ACCESS_KEY,
}

sqs_client = boto3.client("sqs", **boto_kwargs)
dynamodb = boto3.resource("dynamodb", **boto_kwargs)

# ─────────────────── Counters ───────────────────

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


# ═══════════════════════════════════════════════════
# PART 1 — DynamoDB Table Initialisation
# ═══════════════════════════════════════════════════

def create_tables():
    """Create DynamoDB tables in LocalStack (idempotent)."""
    client = boto3.client("dynamodb", **boto_kwargs)
    existing = []
    try:
        existing = client.list_tables().get("TableNames", [])
    except Exception as e:
        logger.warning(f"Cannot list tables yet: {e}")

    tables = [
        {
            "TableName": AGGREGATES_TABLE,
            "KeySchema": [
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            "AttributeDefinitions": [
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
            ],
        },
        {
            "TableName": EVENTS_TABLE,
            "KeySchema": [
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            "AttributeDefinitions": [
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
            ],
        },
        {
            "TableName": KPIS_TABLE,
            "KeySchema": [
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            "AttributeDefinitions": [
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
            ],
        },
    ]

    for tbl in tables:
        if tbl["TableName"] in existing:
            logger.info(f"Table {tbl['TableName']} already exists — skipping")
            continue
        try:
            client.create_table(
                **tbl,
                BillingMode="PAY_PER_REQUEST",
            )
            logger.info(f"✅ Created table: {tbl['TableName']}")
        except ClientError as e:
            if e.response["Error"]["Code"] == "ResourceInUseException":
                logger.info(f"Table {tbl['TableName']} already exists")
            else:
                raise

    consumer_stats["dynamodb_healthy"] = True


def create_sqs_queues():
    """Create SQS FIFO queues in LocalStack (idempotent)."""
    queue_names = [AGGREGATES_QUEUE_NAME, EVENTS_QUEUE_NAME]
    for name in queue_names:
        try:
            sqs_client.create_queue(
                QueueName=name,
                Attributes={
                    "FifoQueue": "true",
                    "ContentBasedDeduplication": "true",
                    "MessageRetentionPeriod": MESSAGE_RETENTION_PERIOD,
                },
            )
            logger.info(f"✅ Created SQS queue: {name}")
        except ClientError as e:
            if e.response["Error"]["Code"] == "QueueAlreadyExists":
                logger.info(f"SQS queue {name} already exists")
            else:
                logger.warning(f"SQS queue creation warning for {name}: {e}")

    consumer_stats["sqs_healthy"] = True


# ═══════════════════════════════════════════════════
# PART 2 — SQS → DynamoDB Processors (Lambda Logic)
# ═══════════════════════════════════════════════════

def process_aggregate_message(body: dict, message_id: str):
    """Mirrors process_aggregates.lambda_handler for a single record."""
    table = dynamodb.Table(AGGREGATES_TABLE)
    junction_id = body["junctionId"]
    timestamp = body["timestamp"]

    item = {
        "PK": f"{junction_id}#aggregates",
        "SK": timestamp,
        "junctionId": junction_id,
        "timestamp": timestamp,
        "vehicle_count_sum": int(body["vehicle_count_sum"]),
        "avg_speed": Decimal(str(body["avg_speed"])),
        "congestion_index": Decimal(str(body["congestion_index"])),
        "rain_intensity": body.get("rain_intensity"),
        "avg_ambient_light": (
            Decimal(str(body["avg_ambient_light"]))
            if body.get("avg_ambient_light") is not None
            else None
        ),
        "avg_pollution": (
            Decimal(str(body["avg_pollution"]))
            if body.get("avg_pollution") is not None
            else None
        ),
        "metrics_count": int(body["metrics_count"]),
        "processed_at": datetime.utcnow().isoformat(),
        "idempotency_key": message_id,
    }

    try:
        table.put_item(
            Item=item,
            ConditionExpression="attribute_not_exists(PK) AND attribute_not_exists(SK)",
        )
        logger.info(f"Stored aggregate: {junction_id} @ {timestamp}")
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            logger.debug(f"Duplicate aggregate skipped: {junction_id} @ {timestamp}")
        else:
            raise

    consumer_stats["aggregates_processed"] += 1


def process_event_message(body: dict, message_id: str):
    """Mirrors process_events.lambda_handler for a single record."""
    events_table = dynamodb.Table(EVENTS_TABLE)

    junction_id = body["junctionId"]
    alert_id = body["alertId"]
    alert_type = body["alertType"]
    timestamp = body["timestamp"]

    item = {
        "PK": junction_id,
        "SK": f"{timestamp}#{alert_type}#{alert_id}",
        "alertId": alert_id,
        "junctionId": junction_id,
        "alertType": alert_type,
        "severity": body["severity"],
        "description": body["description"],
        "triggered_value": Decimal(str(body["triggered_value"])),
        "threshold": Decimal(str(body["threshold"])),
        "timestamp": timestamp,
        "processed_at": datetime.utcnow().isoformat(),
    }

    try:
        events_table.put_item(
            Item=item,
            ConditionExpression="attribute_not_exists(PK) AND attribute_not_exists(SK)",
        )
        logger.info(f"Stored event: {alert_type} @ {junction_id}")
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            logger.debug(f"Duplicate event skipped: {alert_id}")
        else:
            raise

    consumer_stats["events_processed"] += 1

    # Compute KPIs (mirrors compute_kpis in process_events.py)
    compute_kpis(junction_id)


def compute_kpis(junction_id: str):
    """Compute hourly KPIs — mirrors process_events.compute_kpis."""
    events_table = dynamodb.Table(EVENTS_TABLE)
    kpis_table = dynamodb.Table(KPIS_TABLE)

    one_hour_ago = (datetime.utcnow() - timedelta(hours=1)).isoformat()

    try:
        response = events_table.query(
            KeyConditionExpression="PK = :pk AND SK > :sk",
            ExpressionAttributeValues={":pk": junction_id, ":sk": one_hour_ago},
        )
        events = response.get("Items", [])

        speeding = sum(1 for e in events if e.get("alertType") == "SPEEDING")
        congestion = sum(1 for e in events if e.get("alertType") == "CONGESTION")
        incident = sum(1 for e in events if e.get("alertType") == "INCIDENT")

        penalty = min(SAFETY_MAX_PENALTY, speeding * SAFETY_SPEEDING_WEIGHT + incident * SAFETY_INCIDENT_WEIGHT)
        safety_score = max(0, SAFETY_MAX_SCORE - penalty)

        kpis_table.put_item(
            Item={
                "PK": f"{junction_id}#kpis",
                "SK": datetime.utcnow().isoformat(),
                "speeding_events_1h": speeding,
                "congestion_events_1h": congestion,
                "incident_events_1h": incident,
                "total_events_1h": len(events),
                "safety_score": safety_score,
            }
        )
        consumer_stats["kpis_computed"] += 1
    except Exception as e:
        logger.warning(f"KPI computation failed: {e}")


# ═══════════════════════════════════════════════════
# PART 3 — SQS Polling Loop
# ═══════════════════════════════════════════════════

def poll_queue(queue_url: str, processor_fn, queue_label: str):
    """Long-poll one SQS queue and process messages."""
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
                logger.error(f"Error processing {queue_label} message: {e}")
                consumer_stats["errors"] += 1

        return len(messages)

    except (EndpointConnectionError, ClientError) as e:
        logger.warning(f"SQS poll failed ({queue_label}): {e}")
        consumer_stats["sqs_healthy"] = False
        return 0


def sqs_consumer_loop():
    """Background thread: continuously poll both SQS queues."""
    logger.info("SQS consumer loop started")
    consumer_stats["started_at"] = datetime.utcnow().isoformat()

    # Wait for LocalStack to be ready
    for attempt in range(1, 31):
        try:
            sqs_client.list_queues()
            logger.info(f"SQS connected (attempt {attempt})")
            consumer_stats["sqs_healthy"] = True
            break
        except Exception:
            logger.info(f"Waiting for SQS... (attempt {attempt}/30)")
            time.sleep(2)
    else:
        logger.error("SQS not reachable after 30 attempts — consumer will retry")

    while True:
        try:
            agg_count = poll_queue(
                AGGREGATES_QUEUE_URL, process_aggregate_message, "aggregates"
            )
            evt_count = poll_queue(
                EVENTS_QUEUE_URL, process_event_message, "events"
            )

            if agg_count or evt_count:
                logger.info(
                    f"Processed: {agg_count} aggregates, {evt_count} events | "
                    f"Totals: {consumer_stats['aggregates_processed']} agg, "
                    f"{consumer_stats['events_processed']} evt, "
                    f"{consumer_stats['kpis_computed']} kpis"
                )

            consumer_stats["last_poll"] = datetime.utcnow().isoformat()
            consumer_stats["sqs_healthy"] = True

        except Exception as e:
            logger.error(f"Consumer loop error: {e}")
            consumer_stats["sqs_healthy"] = False

        time.sleep(POLL_INTERVAL_SEC)


# ═══════════════════════════════════════════════════
# PART 4 — Dashboard REST API (mirrors dashboard_api Lambda)
# ═══════════════════════════════════════════════════

app = FastAPI(title="Cloud Consumer — Local Dashboard API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def decimal_default(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError


def to_json_safe(items):
    """Convert DynamoDB Decimal items to JSON-safe dicts."""
    return json.loads(json.dumps(items, default=decimal_default))


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
    junctionId: str = Query(..., description="Junction ID"),
    hours: int = Query(1, description="Lookback hours"),
):
    """Get recent aggregates — mirrors dashboard_api.get_recent_aggregates."""
    table = dynamodb.Table(AGGREGATES_TABLE)
    threshold = (datetime.utcnow() - timedelta(hours=hours)).isoformat()

    response = table.query(
        KeyConditionExpression="PK = :pk AND SK > :sk",
        ExpressionAttributeValues={
            ":pk": f"{junctionId}#aggregates",
            ":sk": threshold,
        },
        ScanIndexForward=True,
        Limit=360,
    )
    items = response.get("Items", [])
    return to_json_safe({"junctionId": junctionId, "aggregates": items, "count": len(items)})


@app.get("/api/events")
async def get_events(
    junctionId: str = Query(..., description="Junction ID"),
    limit: int = Query(50, description="Max events"),
):
    """Get recent events — mirrors dashboard_api.get_recent_events."""
    table = dynamodb.Table(EVENTS_TABLE)

    response = table.query(
        KeyConditionExpression="PK = :pk",
        ExpressionAttributeValues={":pk": junctionId},
        ScanIndexForward=False,
        Limit=limit,
    )
    items = response.get("Items", [])
    return to_json_safe({"junctionId": junctionId, "events": items, "count": len(items)})


@app.get("/api/kpis")
async def get_kpis(
    junctionId: str = Query(..., description="Junction ID"),
):
    """Get latest KPIs — mirrors dashboard_api.get_current_kpis."""
    table = dynamodb.Table(KPIS_TABLE)

    response = table.query(
        KeyConditionExpression="PK = :pk",
        ExpressionAttributeValues={":pk": f"{junctionId}#kpis"},
        ScanIndexForward=False,
        Limit=1,
    )
    items = response.get("Items", [])
    kpis = items[0] if items else {}
    return to_json_safe({"junctionId": junctionId, "kpis": kpis})


@app.get("/api/summary")
async def get_summary(
    junctionId: str = Query(..., description="Junction ID"),
    minutes: int = Query(10, description="Lookback minutes"),
    since: Optional[str] = Query(None, description="ISO timestamp"),
):
    """Single-call dashboard endpoint — mirrors dashboard_api.get_summary."""
    threshold = since or (datetime.utcnow() - timedelta(minutes=minutes)).isoformat()

    agg_table = dynamodb.Table(AGGREGATES_TABLE)
    evt_table = dynamodb.Table(EVENTS_TABLE)
    kpi_table = dynamodb.Table(KPIS_TABLE)

    # Aggregates since threshold
    agg_resp = agg_table.query(
        KeyConditionExpression="PK = :pk AND SK > :sk",
        ExpressionAttributeValues={
            ":pk": f"{junctionId}#aggregates",
            ":sk": threshold,
        },
        ScanIndexForward=True,
        Limit=360,
    )
    aggregates = agg_resp.get("Items", [])

    # Recent events
    evt_resp = evt_table.query(
        KeyConditionExpression="PK = :pk",
        ExpressionAttributeValues={":pk": junctionId},
        ScanIndexForward=False,
        Limit=20,
    )
    events = evt_resp.get("Items", [])

    # Latest KPI
    kpi_resp = kpi_table.query(
        KeyConditionExpression="PK = :pk",
        ExpressionAttributeValues={":pk": f"{junctionId}#kpis"},
        ScanIndexForward=False,
        Limit=1,
    )
    kpi_items = kpi_resp.get("Items", [])
    kpis = kpi_items[0] if kpi_items else {}

    result = {
        "junctionId": junctionId,
        "kpis": kpis,
        "latest_aggregate": aggregates[-1] if aggregates else {},
        "aggregates": aggregates,
        "aggregates_count": len(aggregates),
        "events": events,
        "events_count": len(events),
        "since": threshold,
    }
    return to_json_safe(result)


# ═══════════════════════════════════════════════════
# PART 5 — Startup
# ═══════════════════════════════════════════════════

@app.on_event("startup")
async def startup():
    """Create tables, SQS queues, and start the SQS consumer background thread."""
    # Wait for LocalStack DynamoDB
    for attempt in range(1, 31):
        try:
            create_tables()
            break
        except Exception as e:
            logger.info(f"Waiting for DynamoDB... ({attempt}/30): {e}")
            time.sleep(2)
    else:
        logger.error("DynamoDB not reachable after 30 attempts")

    # Create SQS FIFO queues in LocalStack
    for attempt in range(1, 31):
        try:
            create_sqs_queues()
            break
        except Exception as e:
            logger.info(f"Waiting for SQS... ({attempt}/30): {e}")
            time.sleep(2)
    else:
        logger.error("SQS not reachable after 30 attempts")

    # Start SQS consumer in background thread
    thread = threading.Thread(target=sqs_consumer_loop, daemon=True)
    thread.start()
    logger.info(f"☁️  Cloud consumer started — API on port {API_PORT}")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=API_PORT)
