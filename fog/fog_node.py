from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from collections import deque, defaultdict
import asyncio
import logging
import os

import boto3
from decimal import Decimal

try:
    from botocore.exceptions import ClientError, EndpointConnectionError, ConnectionClosedError
except ImportError:
    ClientError = Exception
    EndpointConnectionError = Exception
    ConnectionClosedError = Exception

from fog.config import FogConfig
from fog.models import SensorEvent, AggregateMetric, AlertEvent
from fog.analytics import FogAnalytics
from fog.notifications import NotificationManager
from fog.dispatcher import SQSDispatcher
from fog.spool import LocalSpoolStore, SpoolFlushError
from fog.metrics_collector import FogMetrics

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Flood Early Warning Fog Node", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)


class FogNodeState:

    def __init__(self):
        self.event_buffers: Dict[str, deque] = defaultdict(lambda: deque(maxlen=1000))
        self.dedup_cache: Dict[str, datetime] = {}
        self.last_aggregates: Dict[str, Dict] = {}
        self.flow_rate_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=100))
        self.sqs_client = self._init_sqs()
        self.dynamodb = self._init_dynamodb()

    def add_event(self, event: SensorEvent) -> bool:
        if event.eventId in self.dedup_cache:
            return False
        self.dedup_cache[event.eventId] = datetime.utcnow()
        self.event_buffers[event.stationId].append(event)
        return True

    def cleanup_dedup_cache(self):
        now = datetime.utcnow()
        expired = [
            k for k, v in self.dedup_cache.items()
            if (now - v).total_seconds() > FogConfig.DEDUP_CACHE_TTL_SEC
        ]
        for k in expired:
            del self.dedup_cache[k]

    @staticmethod
    def _init_sqs():
        try:
            kwargs = {"region_name": FogConfig.AWS_REGION}
            endpoint_url = os.getenv("AWS_ENDPOINT_URL")
            if endpoint_url:
                kwargs["endpoint_url"] = endpoint_url
            client = boto3.client("sqs", **kwargs)
            _discover_queue_urls(client)
            return client
        except Exception as e:
            logger.warning(f"SQS client init failed: {e}")
            return None

    @staticmethod
    def _init_dynamodb():
        try:
            kwargs = {"region_name": FogConfig.AWS_REGION}
            endpoint_url = os.getenv("AWS_ENDPOINT_URL")
            if endpoint_url:
                kwargs["endpoint_url"] = endpoint_url
            return boto3.resource("dynamodb", **kwargs)
        except Exception as e:
            logger.warning(f"DynamoDB init failed: {e}")
            return None


def _discover_queue_urls(client):
    queue_map = {
        "AGGREGATES_QUEUE_URL": os.getenv("AGGREGATES_QUEUE_NAME", "flood-aggregates-queue.fifo"),
        "EVENTS_QUEUE_URL": os.getenv("EVENTS_QUEUE_NAME", "flood-events-queue.fifo"),
    }
    for attr, queue_name in queue_map.items():
        if not getattr(FogConfig, attr):
            try:
                resp = client.get_queue_url(QueueName=queue_name)
                setattr(FogConfig, attr, resp["QueueUrl"])
                logger.info(f"Discovered {attr}: {resp['QueueUrl']}")
            except Exception as e:
                logger.warning(f"Could not discover {attr}: {e}")


fog_state = FogNodeState()
spool_store = LocalSpoolStore(
    spool_dir=os.getenv("SPOOL_DIR", os.path.join(os.path.dirname(__file__), "spool_data"))
)
fog_metrics = FogMetrics()
sqs_last_success_time: Optional[datetime] = None


@app.post("/ingest", status_code=202)
async def ingest_event(event: SensorEvent):
    _validate_sensor_value(event)
    if not fog_state.add_event(event):
        fog_metrics.record_duplicate()
        return {"status": "duplicate"}

    fog_metrics.record_ingest()
    alert = FogAnalytics.detect_high_water(event)
    if alert:
        await SQSDispatcher.send_event(alert)

    logger.info(f"Ingested: {event.sensorType}={event.value} {event.unit} @ {event.stationId}")
    return {"status": "accepted", "eventId": event.eventId}


@app.post("/ingest/batch", status_code=202)
async def ingest_batch(events: List[SensorEvent]):
    accepted = 0
    for event in events:
        if fog_state.add_event(event):
            accepted += 1
            fog_metrics.record_ingest()
            alert = FogAnalytics.detect_high_water(event)
            if alert:
                await SQSDispatcher.send_event(alert)
        else:
            fog_metrics.record_duplicate()
    logger.info(f"Batch ingested: {accepted}/{len(events)} events")
    return {"status": "accepted", "count": accepted}


@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@app.get("/metrics")
async def metrics():
    return {
        station_id: {
            "buffered_events": len(events),
            "dedup_cache_size": len(fog_state.dedup_cache),
        }
        for station_id, events in fog_state.event_buffers.items()
    }


@app.get("/notifications")
async def get_notifications(limit: int = 20):
    notifications = NotificationManager.get_recent(limit)
    return {
        "notifications": notifications,
        "count": len(notifications),
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/status")
async def node_status():
    now = datetime.utcnow()
    sqs_healthy = _check_sqs_health(now)
    return {
        "nodeId": os.getenv("FOG_NODE_ID", f"fog-port-{os.getenv('FOG_PORT', '8000')}"),
        "sqs_health": "up" if sqs_healthy else "down",
        "last_flush_time": fog_metrics.last_flush_time_iso,
        "spool": {
            "pending_count": spool_store.spool_size(),
            "bytes": spool_store.spool_bytes(),
            "oldest_created_at": spool_store.oldest_created_at(),
        },
        "rates_10s": {
            "incoming_eps": fog_metrics.incoming_rate(),
            "outgoing_mps": fog_metrics.outgoing_rate(),
            "reduction_pct": fog_metrics.bandwidth_reduction(),
        },
        "counters": {
            "incoming_total": fog_metrics.incoming_events_total,
            "outgoing_total": fog_metrics.outgoing_messages_total,
            "duplicates_total": fog_metrics.duplicates_dropped,
            "alerts_total": fog_metrics.alerts_generated,
        },
    }


async def aggregation_task():
    while True:
        try:
            await asyncio.sleep(FogConfig.AGGREGATE_INTERVAL_SEC)
            fog_state.cleanup_dedup_cache()
            now = datetime.utcnow()
            window_start = now - timedelta(seconds=FogConfig.WINDOW_SIZE_SEC)

            for station_id, events_deque in fog_state.event_buffers.items():
                window_events = [
                    e for e in events_deque
                    if FogAnalytics.parse_timestamp(e.timestamp) >= window_start
                ]
                if not window_events:
                    continue

                aggregate = FogAnalytics.compute_aggregates(window_events, window_start)
                if not aggregate:
                    continue

                fog_state.last_aggregates[station_id] = aggregate
                await SQSDispatcher.send_aggregate(aggregate)

                flood_alert = FogAnalytics.detect_flood_warning(aggregate)
                if flood_alert:
                    flood_alert.stationId = station_id
                    await SQSDispatcher.send_event(flood_alert)

                if station_id in fog_state.flow_rate_history:
                    flash_alert = FogAnalytics.detect_flash_flood(
                        fog_state.flow_rate_history[station_id]
                    )
                    if flash_alert:
                        flash_alert.stationId = station_id
                        await SQSDispatcher.send_event(flash_alert)

            await _flush_spool_if_needed()
            _export_metrics()
            await _push_status_to_dynamodb()

        except Exception as e:
            logger.error(f"Aggregation error: {type(e).__name__}: {e}", exc_info=True)


async def _flush_spool_if_needed():
    if spool_store.spool_size() > 0 and fog_state.sqs_client:
        try:
            flushed = await spool_store.flush_to_sqs(
                fog_state.sqs_client,
                FogConfig.AGGREGATES_QUEUE_URL,
                FogConfig.EVENTS_QUEUE_URL,
            )
            if flushed > 0:
                fog_metrics.record_spool_flush(flushed)
                logger.info(f"Flushed {flushed} spooled messages")
        except SpoolFlushError as e:
            logger.warning(f"Spool flush incomplete: {e}")


def _export_metrics():
    fog_metrics.log_snapshot()
    csv_path = os.getenv(
        "METRICS_CSV_PATH",
        os.path.join(os.path.dirname(__file__), "..", "artifacts", "metrics_timeseries.csv"),
    )
    fog_metrics.append_csv(csv_path, {"spool_size": spool_store.spool_size()})


async def _push_status_to_dynamodb():
    if not fog_state.dynamodb:
        return
    try:
        table_name = os.getenv("KPIS_TABLE_NAME", "flood-kpis")
        table = fog_state.dynamodb.Table(table_name)
        node_id = os.getenv("FOG_NODE_ID", f"fog-port-{os.getenv('FOG_PORT', '8000')}")
        now_iso = datetime.utcnow().isoformat()
        sqs_healthy = _check_sqs_health(datetime.utcnow())
        table.put_item(Item={
            "PK": f"{node_id}#fog-status",
            "SK": now_iso,
            "nodeId": node_id,
            "sqs_health": "up" if sqs_healthy else "down",
            "last_flush_time": fog_metrics.last_flush_time_iso or "",
            "spool": {
                "pending_count": spool_store.spool_size(),
                "bytes": spool_store.spool_bytes(),
            },
            "rates_10s": {
                "incoming_eps": Decimal(str(round(fog_metrics.incoming_rate(), 2))),
                "outgoing_mps": Decimal(str(round(fog_metrics.outgoing_rate(), 2))),
                "reduction_pct": Decimal(str(round(fog_metrics.bandwidth_reduction(), 2))),
            },
            "counters": {
                "incoming_total": fog_metrics.incoming_events_total,
                "outgoing_total": fog_metrics.outgoing_messages_total,
                "duplicates_total": fog_metrics.duplicates_dropped,
                "alerts_total": fog_metrics.alerts_generated,
            },
            "notifications_count": len(NotificationManager.get_recent(50)),
            "updated_at": now_iso,
        })
    except Exception as e:
        logger.debug(f"Status push to DynamoDB failed: {e}")


def _validate_sensor_value(event: SensorEvent):
    if event.value is None and event.sensorType != "rainfall_intensity":
        raise HTTPException(status_code=400, detail="value required")
    bounds = FogConfig.SENSOR_BOUNDS
    if event.sensorType in bounds:
        lo, hi = bounds[event.sensorType]
        if isinstance(event.value, (int, float)) and not (lo <= event.value <= hi):
            raise HTTPException(status_code=400, detail=f"Invalid {event.sensorType}")


def _check_sqs_health(now: datetime) -> bool:
    if sqs_last_success_time:
        return (now - sqs_last_success_time).total_seconds() < 30
    return not FogConfig.AGGREGATES_QUEUE_URL


@app.on_event("startup")
async def startup_event():
    await _flush_spool_if_needed()
    asyncio.create_task(aggregation_task())
    logger.info("Flood Early Warning fog node started")


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("FOG_PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
