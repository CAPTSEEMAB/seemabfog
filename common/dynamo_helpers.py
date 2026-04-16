import json
import logging
from datetime import datetime, timedelta
from decimal import Decimal

from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


def decimal_default(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def to_json_safe(items):
    return json.loads(json.dumps(items, default=decimal_default))


def store_aggregate(table, body: dict, message_id: str) -> bool:
    station_id = body["stationId"]
    timestamp = body["timestamp"]
    item = {
        "PK": f"{station_id}#aggregates",
        "SK": timestamp,
        "stationId": station_id,
        "timestamp": timestamp,
        "max_water_level": Decimal(str(body["max_water_level"])),
        "avg_flow_rate": Decimal(str(body["avg_flow_rate"])),
        "flood_risk_index": Decimal(str(body["flood_risk_index"])),
        "rainfall_intensity": body.get("rainfall_intensity"),
        "avg_soil_moisture": (
            Decimal(str(body["avg_soil_moisture"]))
            if body.get("avg_soil_moisture") is not None else None
        ),
        "avg_turbidity": (
            Decimal(str(body["avg_turbidity"]))
            if body.get("avg_turbidity") is not None else None
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
        logger.info(f"Stored aggregate: {station_id} @ {timestamp}")
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            logger.debug(f"Duplicate aggregate skipped: {station_id} @ {timestamp}")
            return False
        raise


def store_event(table, body: dict, message_id: str) -> bool:
    station_id = body["stationId"]
    alert_id = body["alertId"]
    alert_type = body["alertType"]
    severity = body.get("severity", "MEDIUM")
    timestamp = body["timestamp"]
    item = {
        "PK": station_id,
        "SK": f"{timestamp}#{alert_type}#{alert_id}",
        "alertId": alert_id,
        "stationId": station_id,
        "alertType": alert_type,
        "severity": severity,
        "description": body["description"],
        "triggered_value": Decimal(str(body["triggered_value"])),
        "threshold": Decimal(str(body["threshold"])),
        "timestamp": timestamp,
        "processed_at": datetime.utcnow().isoformat(),
    }
    try:
        table.put_item(
            Item=item,
            ConditionExpression="attribute_not_exists(PK) AND attribute_not_exists(SK)",
        )
        logger.info(f"Stored event: {alert_type} @ {station_id}")
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            logger.debug(f"Duplicate event skipped: {alert_id}")
            return False
        raise


def compute_kpis(station_id: str, events_table, kpis_table, kpi_weights: dict = None):
    w = kpi_weights or {}
    hw_weight = w.get("high_water", 5)
    fw_weight = w.get("flood_warning", 10)
    ff_weight = w.get("flash_flood", 15)
    max_penalty = w.get("max_penalty", 100)
    max_score = w.get("max_score", 100)

    one_hour_ago = (datetime.utcnow() - timedelta(hours=1)).isoformat()
    try:
        response = events_table.query(
            KeyConditionExpression="PK = :pk AND SK > :sk",
            ExpressionAttributeValues={":pk": station_id, ":sk": one_hour_ago},
        )
        events = response.get("Items", [])
        hw = sum(1 for e in events if e.get("alertType") == "HIGH_WATER")
        fw = sum(1 for e in events if e.get("alertType") == "FLOOD_WARNING")
        ff = sum(1 for e in events if e.get("alertType") == "FLASH_FLOOD")
        penalty = min(max_penalty, hw * hw_weight + ff * ff_weight + fw * fw_weight)
        score = max(0, max_score - penalty)
        kpis_table.put_item(Item={
            "PK": f"{station_id}#kpis",
            "SK": datetime.utcnow().isoformat(),
            "high_water_events_1h": hw,
            "flood_warning_events_1h": fw,
            "flash_flood_events_1h": ff,
            "total_events_1h": len(events),
            "flood_resilience_score": score,
        })
        return score
    except Exception as e:
        logger.warning(f"KPI computation failed for {station_id}: {e}")
        return None


def query_aggregates(table, station_id: str, time_threshold: str, limit: int = 360):
    response = table.query(
        KeyConditionExpression="PK = :pk AND SK > :sk",
        ExpressionAttributeValues={
            ":pk": f"{station_id}#aggregates",
            ":sk": time_threshold,
        },
        ScanIndexForward=True,
        Limit=limit,
    )
    return response.get("Items", [])


def query_events(table, station_id: str, limit: int = 50):
    response = table.query(
        KeyConditionExpression="PK = :pk",
        ExpressionAttributeValues={":pk": station_id},
        ScanIndexForward=False,
        Limit=limit,
    )
    return response.get("Items", [])


def query_latest_kpis(table, station_id: str):
    response = table.query(
        KeyConditionExpression="PK = :pk",
        ExpressionAttributeValues={":pk": f"{station_id}#kpis"},
        ScanIndexForward=False,
        Limit=1,
    )
    items = response.get("Items", [])
    return items[0] if items else {}
