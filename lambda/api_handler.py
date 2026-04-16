import json
import os
import logging
from datetime import datetime, timedelta
from decimal import Decimal

import boto3

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from common.dynamo_helpers import (
    decimal_default,
    query_aggregates,
    query_events,
    query_latest_kpis,
)

logger = logging.getLogger()
logger.setLevel(logging.INFO)

REGION = os.getenv("AWS_REGION", "us-east-1")
AGGREGATES_TABLE = os.getenv("AGGREGATES_TABLE_NAME", "flood-aggregates")
EVENTS_TABLE = os.getenv("EVENTS_TABLE_NAME", "flood-events")
KPIS_TABLE = os.getenv("KPIS_TABLE_NAME", "flood-kpis")

dynamodb = boto3.resource("dynamodb", region_name=REGION)


class DecimalEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Decimal):
            return float(o)
        return super().default(o)


def ok(body, code=200):
    return {
        "statusCode": code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type",
            "Access-Control-Allow-Methods": "GET,OPTIONS",
        },
        "body": json.dumps(body, cls=DecimalEncoder),
    }


def err(msg, code=400):
    return ok({"error": msg}, code)


def qs(event, key, default=None):
    params = event.get("queryStringParameters") or {}
    return params.get(key, default)


def api_health(_event):
    return ok({"status": "ok", "timestamp": datetime.utcnow().isoformat()})


def api_aggregates(event):
    station = qs(event, "stationId")
    if not station:
        return err("stationId required")
    hours = int(qs(event, "hours", "1"))
    threshold = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
    items = query_aggregates(dynamodb.Table(AGGREGATES_TABLE), station, threshold)
    return ok({"stationId": station, "aggregates": items, "count": len(items)})


def api_events(event):
    station = qs(event, "stationId")
    if not station:
        return err("stationId required")
    limit = int(qs(event, "limit", "50"))
    items = query_events(dynamodb.Table(EVENTS_TABLE), station, limit)
    return ok({"stationId": station, "events": items, "count": len(items)})


def api_kpis(event):
    station = qs(event, "stationId")
    if not station:
        return err("stationId required")
    kpis = query_latest_kpis(dynamodb.Table(KPIS_TABLE), station)
    return ok({"stationId": station, "kpis": kpis})


def api_notifications(event):
    limit = int(qs(event, "limit", "30"))
    table = dynamodb.Table(EVENTS_TABLE)
    since = (datetime.utcnow() - timedelta(minutes=30)).isoformat()
    notifications = []
    for station in ["River-Station-A", "River-Station-B"]:
        resp = table.query(
            KeyConditionExpression="PK = :pk AND SK > :sk",
            ExpressionAttributeValues={":pk": station, ":sk": since},
            ScanIndexForward=False,
            Limit=limit,
        )
        for item in resp.get("Items", []):
            if item.get("severity") in ("HIGH", "CRITICAL"):
                notifications.append(_event_to_notification(item, station))
    notifications.sort(key=lambda n: n.get("timestamp", ""), reverse=True)
    return ok({
        "notifications": notifications[:limit],
        "count": min(len(notifications), limit),
        "timestamp": datetime.utcnow().isoformat(),
    })


def api_summary(event):
    station = qs(event, "stationId")
    if not station:
        return err("stationId required")
    minutes = int(qs(event, "minutes", "10"))
    since = qs(event, "since") or (datetime.utcnow() - timedelta(minutes=minutes)).isoformat()

    aggregates = query_aggregates(dynamodb.Table(AGGREGATES_TABLE), station, since)
    events = query_events(dynamodb.Table(EVENTS_TABLE), station, limit=20)
    kpis = query_latest_kpis(dynamodb.Table(KPIS_TABLE), station)

    return ok({
        "stationId": station,
        "kpis": kpis,
        "latest_aggregate": aggregates[-1] if aggregates else {},
        "aggregates": aggregates,
        "aggregates_count": len(aggregates),
        "events": events,
        "events_count": len(events),
        "since": since,
    })


def api_fog_status(event):
    node_id = qs(event, "nodeId")
    if not node_id:
        return err("nodeId required")
    table = dynamodb.Table(KPIS_TABLE)
    resp = table.query(
        KeyConditionExpression="PK = :pk",
        ExpressionAttributeValues={":pk": f"{node_id}#fog-status"},
        ScanIndexForward=False,
        Limit=1,
    )
    items = resp.get("Items", [])
    if items:
        return ok(items[0])
    return ok({
        "nodeId": node_id,
        "sqs_health": "unknown",
        "rates_10s": {"incoming_eps": 0, "outgoing_mps": 0, "reduction_pct": 0},
        "spool": {"pending_count": 0},
        "counters": {"incoming_total": 0, "outgoing_total": 0, "alerts_total": 0},
    })


def api_fog_notifications(event):
    node_id = qs(event, "nodeId")
    limit = int(qs(event, "limit", "50"))
    station_map = {"fog-a": "River-Station-A", "fog-b": "River-Station-B"}
    station = station_map.get(node_id, node_id)
    items = query_events(dynamodb.Table(EVENTS_TABLE), station, limit)
    notifications = [_event_to_notification(e, station) for e in items]
    return ok({
        "notifications": notifications,
        "count": len(notifications),
        "timestamp": datetime.utcnow().isoformat(),
    })


def _event_to_notification(item: dict, station: str) -> dict:
    return {
        "id": item.get("alertId", ""),
        "alert_id": item.get("alertId", ""),
        "station": station,
        "type": item.get("alertType", ""),
        "severity": item.get("severity", ""),
        "message": item.get("description", ""),
        "value": item.get("triggered_value", 0),
        "threshold": item.get("threshold", 0),
        "timestamp": item.get("timestamp", ""),
    }


ROUTES = {
    "GET /api/health": api_health,
    "GET /api/aggregates": api_aggregates,
    "GET /api/events": api_events,
    "GET /api/kpis": api_kpis,
    "GET /api/notifications": api_notifications,
    "GET /api/summary": api_summary,
    "GET /api/fog-status": api_fog_status,
    "GET /api/fog-notifications": api_fog_notifications,
}


def handler(event, context):
    if "routeKey" in event:
        route_key = event["routeKey"]
    else:
        method = event.get("httpMethod", "GET")
        path = event.get("path", "/")
        route_key = f"{method} {path}"

    logger.info(f"Route: {route_key}")

    if route_key.startswith("OPTIONS"):
        return ok({})

    fn = ROUTES.get(route_key)
    if fn:
        try:
            return fn(event)
        except Exception as e:
            logger.error(f"Handler error: {e}", exc_info=True)
            return err(f"Internal error: {str(e)}", 500)

    return err(f"Not found: {route_key}", 404)
