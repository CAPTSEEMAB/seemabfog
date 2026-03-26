"""
Fog Node Service - FastAPI
Processes traffic sensor streams and dispatches to cloud.
"""

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Tuple, Union
from datetime import datetime, timedelta
from collections import deque, defaultdict
import json
import asyncio
import logging
import uuid
import os
import time
import random
import boto3
from enum import Enum

try:
    from botocore.exceptions import ClientError, EndpointConnectionError, ConnectionClosedError
except ImportError:
    ClientError = Exception
    EndpointConnectionError = Exception
    ConnectionClosedError = Exception

from fog.spool import LocalSpoolStore, SpoolFlushError
from fog.metrics_collector import FogMetrics

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Traffic Fog Node", version="1.0.0")

# CORS - allow dashboard to fetch from fog nodes
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============== DATA MODELS ==============

class SensorEvent(BaseModel):
    """Incoming sensor event."""
    eventId: str
    junctionId: str
    sensorType: str
    value: Union[float, str]
    unit: str
    timestamp: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class AggregateMetric(BaseModel):
    """10-second rolling aggregate."""
    junctionId: str
    timestamp: str
    vehicle_count_sum: int
    avg_speed: float
    congestion_index: float
    rain_intensity: Optional[str] = None
    avg_ambient_light: Optional[float] = None
    avg_pollution: Optional[float] = None
    metrics_count: int


class AlertEvent(BaseModel):
    """Alert/incident event."""
    alertId: str
    junctionId: str
    alertType: str  # "SPEEDING", "CONGESTION", "INCIDENT"
    severity: str  # "LOW", "MEDIUM", "HIGH"
    description: str
    triggered_value: float
    threshold: float
    timestamp: str


# ============== FOG CONFIGURATION ==============

class FogConfig:
    # Event detection thresholds (configurable via env vars)
    SPEED_THRESHOLD = float(os.getenv('SPEED_THRESHOLD', '80'))         # km/h for urban speeding
    CONGESTION_INDEX_THRESHOLD = float(os.getenv('CONGESTION_INDEX_THRESHOLD', '2.0'))
    SPEED_DROP_PERCENTAGE = float(os.getenv('SPEED_DROP_PERCENTAGE', '40'))  # % drop to trigger incident
    
    # Window configuration
    WINDOW_SIZE_SEC = int(os.getenv('WINDOW_SIZE_SEC', '10'))
    INCIDENT_TREND_WINDOW_SEC = int(os.getenv('INCIDENT_TREND_WINDOW_SEC', '20'))
    
    # Deduplication
    DEDUP_CACHE_TTL_SEC = int(os.getenv('DEDUP_CACHE_TTL_SEC', '10'))
    
    # Dispatch
    AGGREGATE_INTERVAL_SEC = int(os.getenv('AGGREGATE_INTERVAL_SEC', '10'))
    EVENT_DISPATCH_IMMEDIATE = True
    
    # AWS
    AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')
    AGGREGATES_QUEUE_URL = os.getenv('AGGREGATES_QUEUE_URL', '')
    EVENTS_QUEUE_URL = os.getenv('EVENTS_QUEUE_URL', '')
    DLQ_QUEUE_URL = os.getenv('DLQ_QUEUE_URL', '')
    
    # Sensor validation bounds (configurable via JSON env var)
    SENSOR_BOUNDS = json.loads(os.getenv('SENSOR_BOUNDS', '{"vehicle_speed":[0,160],"vehicle_count":[0,500],"pollution_pm25":[0,500],"ambient_light":[0,100000]}'))


# ============== FOG STATE ==============

class FogNodeState:
    """Manages fog node state."""
    
    def __init__(self):
        self.event_buffers: Dict[str, deque] = defaultdict(lambda: deque(maxlen=1000))
        self.dedup_cache: Dict[str, datetime] = {}
        self.last_aggregates: Dict[str, Dict] = {}
        self.speed_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=100))
        self.sqs_client = None
        if FogConfig.AGGREGATES_QUEUE_URL:
            try:
                endpoint_url = os.getenv('AWS_ENDPOINT_URL')
                kwargs = {'region_name': FogConfig.AWS_REGION}
                if endpoint_url:
                    kwargs['endpoint_url'] = endpoint_url
                self.sqs_client = boto3.client('sqs', **kwargs)
            except Exception as e:
                logger.warning(f"SQS client init failed: {e}")
        self.idle = False
    
    def add_event(self, event: SensorEvent) -> bool:
        """Add event to buffer. Returns True if not duplicate."""
        # Deduplication
        if event.eventId in self.dedup_cache:
            return False  # Duplicate
        
        self.dedup_cache[event.eventId] = datetime.utcnow()
        self.event_buffers[event.junctionId].append(event)
        return True
    
    def cleanup_dedup_cache(self):
        """Remove expired dedup entries."""
        now = datetime.utcnow()
        expired = [k for k, v in self.dedup_cache.items() 
                   if (now - v).total_seconds() > FogConfig.DEDUP_CACHE_TTL_SEC]
        for k in expired:
            del self.dedup_cache[k]


fog_state = FogNodeState()

# ============== SPOOL & METRICS ==============

spool_dir = os.getenv('SPOOL_DIR', os.path.join(os.path.dirname(__file__), 'spool_data'))
spool_store = LocalSpoolStore(spool_dir=spool_dir)
fog_metrics = FogMetrics()
app_start_time = datetime.utcnow()
sqs_last_success_time: Optional[datetime] = None


# ============== FOG ALGORITHMS ==============

class FogAnalytics:
    """Rolling window analytics."""
    
    @staticmethod
    def parse_timestamp(ts_str: str) -> datetime:
        """Parse ISO timestamp (returns naive UTC)."""
        # Strip timezone info to always return naive UTC datetime
        dt = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
        return dt.replace(tzinfo=None)
    
    @staticmethod
    def compute_aggregates(events: List[SensorEvent], 
                          window_start: datetime) -> Optional[AggregateMetric]:
        """Compute 10-second rolling aggregate."""
        if not events:
            return None
        
        vehicle_counts = []
        speeds = []
        rain_intensities = []
        light_levels = []
        pollution_levels = []
        
        for event in events:
            if event.sensorType == 'vehicle_count':
                vehicle_counts.append(event.value)
            elif event.sensorType == 'vehicle_speed':
                speeds.append(event.value)
                fog_state.speed_history[event.junctionId].append(event.value)
            elif event.sensorType == 'rain_intensity':
                rain_intensities.append(str(event.value))
            elif event.sensorType == 'ambient_light':
                light_levels.append(event.value)
            elif event.sensorType == 'pollution_pm25':
                pollution_levels.append(event.value)
        
        vehicle_count_sum = sum(vehicle_counts)
        avg_speed = sum(speeds) / len(speeds) if speeds else 0
        
        # Congestion index: vehicle_count / max(avg_speed, 1)
        congestion_index = vehicle_count_sum / max(avg_speed, 1.0)
        
        return AggregateMetric(
            junctionId=events[0].junctionId,
            timestamp=window_start.isoformat() + 'Z',
            vehicle_count_sum=vehicle_count_sum,
            avg_speed=round(avg_speed, 2),
            congestion_index=round(congestion_index, 2),
            rain_intensity=rain_intensities[0] if rain_intensities else None,
            avg_ambient_light=round(sum(light_levels) / len(light_levels), 1) if light_levels else None,
            avg_pollution=round(sum(pollution_levels) / len(pollution_levels), 2) if pollution_levels else None,
            metrics_count=len(events)
        )
    
    @staticmethod
    def detect_speeding(event: SensorEvent) -> Optional[AlertEvent]:
        """Detect speeding in real-time."""
        if event.sensorType != 'vehicle_speed':
            return None
        
        if event.value > FogConfig.SPEED_THRESHOLD:
            return AlertEvent(
                alertId=str(uuid.uuid4()),
                junctionId=event.junctionId,
                alertType='SPEEDING',
                severity='MEDIUM',
                description=f'Vehicle speed {event.value} km/h exceeds threshold {FogConfig.SPEED_THRESHOLD}',
                triggered_value=event.value,
                threshold=FogConfig.SPEED_THRESHOLD,
                timestamp=event.timestamp
            )
        return None
    
    @staticmethod
    def detect_congestion(aggregate: AggregateMetric) -> Optional[AlertEvent]:
        """Detect congestion from rolling aggregate."""
        if aggregate.congestion_index > FogConfig.CONGESTION_INDEX_THRESHOLD:
            return AlertEvent(
                alertId=str(uuid.uuid4()),
                junctionId=aggregate.junctionId,
                alertType='CONGESTION',
                severity='HIGH',
                description=f'Congestion index {aggregate.congestion_index} exceeds threshold {FogConfig.CONGESTION_INDEX_THRESHOLD}',
                triggered_value=aggregate.congestion_index,
                threshold=FogConfig.CONGESTION_INDEX_THRESHOLD,
                timestamp=aggregate.timestamp
            )
        return None
    
    @staticmethod
    def detect_incident(speeds: deque) -> Optional[AlertEvent]:
        """Detect sudden slowdown indicating incident."""
        if len(speeds) < 2:
            return None
        
        recent_speeds = list(speeds)[-5:]  # Last 5 readings
        if len(recent_speeds) < 2:
            return None
        
        avg_recent = sum(recent_speeds) / len(recent_speeds)
        avg_previous = sum(list(speeds)[-10:-5]) / 5 if len(speeds) >= 10 else avg_recent
        
        if avg_previous > 0:
            drop_pct = ((avg_previous - avg_recent) / avg_previous) * 100
            
            if drop_pct > FogConfig.SPEED_DROP_PERCENTAGE:
                return AlertEvent(
                    alertId=str(uuid.uuid4()),
                    junctionId='',  # Will be filled from context
                    alertType='INCIDENT',
                    severity='HIGH',
                    description=f'Sudden speed drop of {drop_pct:.1f}% detected - possible incident',
                    triggered_value=avg_recent,
                    threshold=avg_previous * 0.6,  # 40% drop threshold
                    timestamp=datetime.utcnow().isoformat() + 'Z'
                )
        
        return None


# ============== AWS SQS DISPATCH ==============

class SQSDispatcher:
    """Dispatch aggregates and events to AWS SQS with retry + spool."""

    # Backoff config (configurable via env vars)
    MAX_RETRIES = int(os.getenv('MAX_RETRIES', '3'))
    BACKOFF_BASE = float(os.getenv('BACKOFF_BASE', '0.5'))     # seconds
    BACKOFF_MAX = float(os.getenv('BACKOFF_MAX', '10'))        # seconds
    BACKOFF_JITTER = float(os.getenv('BACKOFF_JITTER', '0.25'))  # ±25%

    @staticmethod
    async def _send_with_retry(queue_url: str, msg_body: str,
                               group_id: str, dedup_id: str,
                               message_type: str) -> bool:
        """Try to send to SQS with exponential backoff.
        Returns True on success, False if spooled."""
        global sqs_last_success_time

        if not fog_state.sqs_client or not queue_url:
            logger.info(f"{message_type.capitalize()} (local): {msg_body[:200]}")
            return True  # no SQS configured, local-only mode

        for attempt in range(1, SQSDispatcher.MAX_RETRIES + 1):
            try:
                fog_state.sqs_client.send_message(
                    QueueUrl=queue_url,
                    MessageBody=msg_body,
                    MessageGroupId=group_id,
                    MessageDeduplicationId=dedup_id
                )
                fog_metrics.record_dispatch(1)
                sqs_last_success_time = datetime.utcnow()
                logger.info(f"Sent {message_type}: {group_id} (attempt {attempt})")
                return True
            except (ClientError, EndpointConnectionError, ConnectionClosedError, Exception) as e:
                if attempt < SQSDispatcher.MAX_RETRIES:
                    delay = min(
                        SQSDispatcher.BACKOFF_MAX,
                        SQSDispatcher.BACKOFF_BASE * (2 ** attempt)
                    ) * random.uniform(
                        1 - SQSDispatcher.BACKOFF_JITTER,
                        1 + SQSDispatcher.BACKOFF_JITTER
                    )
                    logger.warning(
                        f"SQS attempt {attempt}/{SQSDispatcher.MAX_RETRIES} failed ({type(e).__name__}): {e}. "
                        f"Retrying in {delay:.1f}s"
                    )
                    await asyncio.sleep(delay)
                else:
                    # All retries exhausted → spool to disk
                    logger.warning(
                        f"SQS unreachable after {SQSDispatcher.MAX_RETRIES} attempts ({type(e).__name__}). "
                        f"Spooling {message_type} (key={dedup_id})"
                    )
                    # Extract junction_id for spool record
                    try:
                        _payload_obj = json.loads(msg_body)
                        _junction = _payload_obj.get("junctionId", "unknown")
                    except (json.JSONDecodeError, TypeError):
                        _junction = "unknown"
                    spool_store.enqueue(message_type, msg_body, dedup_id,
                                        junction_id=_junction)
                    fog_metrics.record_spool_write()
                    return False
        return False

    @staticmethod
    async def send_aggregate(aggregate: AggregateMetric):
        """Send aggregate to SQS with retry + spool fallback."""
        msg_body = aggregate.model_dump_json()
        idempotency_key = f"{aggregate.junctionId}#{aggregate.timestamp}"
        await SQSDispatcher._send_with_retry(
            FogConfig.AGGREGATES_QUEUE_URL, msg_body,
            aggregate.junctionId, idempotency_key, "aggregate"
        )

    @staticmethod
    async def send_event(alert: AlertEvent):
        """Send alert event to SQS with retry + spool fallback."""
        msg_body = alert.model_dump_json()
        idempotency_key = alert.alertId
        fog_metrics.record_alert()
        await SQSDispatcher._send_with_retry(
            FogConfig.EVENTS_QUEUE_URL, msg_body,
            alert.junctionId, idempotency_key, "event"
        )


# ============== API ENDPOINTS ==============

@app.post("/ingest", status_code=202)
async def ingest_event(event: SensorEvent):
    """Receive single sensor event."""
    
    # Validation
    if event.value is None and event.sensorType != 'rain_intensity':
        raise HTTPException(status_code=400, detail="value required")
    
    bounds = FogConfig.SENSOR_BOUNDS
    
    if event.sensorType in bounds:
        min_v, max_v = bounds[event.sensorType]
        if isinstance(event.value, (int, float)) and not (min_v <= event.value <= max_v):
            raise HTTPException(status_code=400, detail=f"Invalid {event.sensorType}")
    
    # Deduplication
    if not fog_state.add_event(event):
        fog_metrics.record_duplicate()
        return {"status": "duplicate"}
    
    fog_metrics.record_ingest()
    
    # Real-time speeding detection
    alert = FogAnalytics.detect_speeding(event)
    if alert:
        await SQSDispatcher.send_event(alert)
    
    logger.info(f"Ingested: {event.sensorType} = {event.value} {event.unit} @ {event.junctionId}")
    
    return {"status": "accepted", "eventId": event.eventId}


@app.post("/ingest/batch", status_code=202)
async def ingest_batch(events: List[SensorEvent]):
    """Receive batch of sensor events."""
    accepted = 0
    for event in events:
        if fog_state.add_event(event):
            accepted += 1
            fog_metrics.record_ingest()
            alert = FogAnalytics.detect_speeding(event)
            if alert:
                await SQSDispatcher.send_event(alert)
        else:
            fog_metrics.record_duplicate()
    
    logger.info(f"Batch ingested: {accepted}/{len(events)} events")
    return {"status": "accepted", "count": accepted}


@app.get("/health")
async def health():
    """Health check."""
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@app.get("/metrics")
async def metrics():
    """Return current metrics."""
    metrics_data = {}
    for junction_id, events in fog_state.event_buffers.items():
        metrics_data[junction_id] = {
            "buffered_events": len(events),
            "dedup_cache_size": len(fog_state.dedup_cache)
        }
    return metrics_data


@app.get("/status")
async def node_status():
    """Comprehensive status: spool, rates, counters (spec-compliant schema)."""
    now = datetime.utcnow()
    sqs_healthy = False
    if sqs_last_success_time:
        sqs_healthy = (now - sqs_last_success_time).total_seconds() < 30
    elif not FogConfig.AGGREGATES_QUEUE_URL:
        sqs_healthy = True  # local-only mode, no SQS configured

    return {
        "nodeId": os.getenv("FOG_NODE_ID", f"fog-port-{os.getenv('FOG_PORT', '8000')}"),
        "sqs_health": "up" if sqs_healthy else "down",
        "last_flush_time": fog_metrics.last_flush_time_iso,
        "spool": {
            "pending_count": spool_store.spool_size(),
            "bytes": spool_store.spool_bytes(),
            "oldest_created_at": spool_store.oldest_created_at()
        },
        "rates_10s": {
            "incoming_eps": fog_metrics.incoming_rate(),
            "outgoing_mps": fog_metrics.outgoing_rate(),
            "reduction_pct": fog_metrics.bandwidth_reduction()
        },
        "counters": {
            "incoming_total": fog_metrics.incoming_events_total,
            "outgoing_total": fog_metrics.outgoing_messages_total,
            "duplicates_total": fog_metrics.duplicates_dropped,
            "alerts_total": fog_metrics.alerts_generated
        }
    }


# ============== BACKGROUND TASKS ==============

async def aggregation_task():
    """Periodically compute and dispatch aggregates + flush spool."""
    while True:
        try:
            await asyncio.sleep(FogConfig.AGGREGATE_INTERVAL_SEC)
            
            fog_state.cleanup_dedup_cache()
            
            now = datetime.utcnow()
            window_start = now - timedelta(seconds=FogConfig.WINDOW_SIZE_SEC)
            
            for junction_id, events_deque in fog_state.event_buffers.items():
                # Filter events in window
                window_events = [e for e in events_deque 
                                if FogAnalytics.parse_timestamp(e.timestamp) >= window_start]
                
                if window_events:
                    aggregate = FogAnalytics.compute_aggregates(window_events, window_start)
                    
                    if aggregate:
                        fog_state.last_aggregates[junction_id] = aggregate
                        await SQSDispatcher.send_aggregate(aggregate)
                        
                        # Check for congestion
                        congestion_alert = FogAnalytics.detect_congestion(aggregate)
                        if congestion_alert:
                            congestion_alert.junctionId = junction_id
                            await SQSDispatcher.send_event(congestion_alert)
                        
                        # Check for incidents
                        if junction_id in fog_state.speed_history:
                            incident_alert = FogAnalytics.detect_incident(
                                fog_state.speed_history[junction_id]
                            )
                            if incident_alert:
                                incident_alert.junctionId = junction_id
                                await SQSDispatcher.send_event(incident_alert)
            
            # ── Spool flush: replay any spooled messages if SQS is back ──
            if spool_store.spool_size() > 0 and fog_state.sqs_client:
                try:
                    flushed = await spool_store.flush_to_sqs(
                        fog_state.sqs_client,
                        FogConfig.AGGREGATES_QUEUE_URL,
                        FogConfig.EVENTS_QUEUE_URL
                    )
                    if flushed > 0:
                        fog_metrics.record_spool_flush(flushed)
                        logger.info(f"Flushed {flushed} spooled messages to SQS")
                except SpoolFlushError as e:
                    logger.warning(f"Spool flush incomplete: {e}")
            
            # ── Metrics export ──
            fog_metrics.log_snapshot()
            csv_path = os.getenv(
                "METRICS_CSV_PATH",
                os.path.join(os.path.dirname(__file__), "..", "artifacts", "metrics_timeseries.csv")
            )
            fog_metrics.append_csv(csv_path, {"spool_size": spool_store.spool_size()})
        except Exception as e:
            logger.error(f"AGGREGATION TASK ERROR: {type(e).__name__}: {str(e)[:200]}", exc_info=True)


@app.on_event("startup")
async def startup_event():
    """Start background tasks and flush any leftover spool."""
    # Drain any spool from a previous crash
    if spool_store.spool_size() > 0 and fog_state.sqs_client:
        try:
            flushed = await spool_store.flush_to_sqs(
                fog_state.sqs_client,
                FogConfig.AGGREGATES_QUEUE_URL,
                FogConfig.EVENTS_QUEUE_URL
            )
            if flushed > 0:
                fog_metrics.record_spool_flush(flushed)
                logger.info(f"Startup: flushed {flushed} spooled messages")
        except SpoolFlushError as e:
            logger.warning(f"Startup spool flush incomplete: {e}")
    
    asyncio.create_task(aggregation_task())
    logger.info("Fog node started")


if __name__ == '__main__':
    import uvicorn
    port = int(os.getenv('FOG_PORT', 8000))
    uvicorn.run(app, host='0.0.0.0', port=port)
