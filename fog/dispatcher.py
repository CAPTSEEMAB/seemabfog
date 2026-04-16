import json
import asyncio
import random
import logging
import os
from datetime import datetime
from typing import Optional

from fog.models import AggregateMetric, AlertEvent
from fog.notifications import NotificationManager

logger = logging.getLogger(__name__)


class SQSDispatcher:

    MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
    BACKOFF_BASE = float(os.getenv("BACKOFF_BASE", "0.5"))
    BACKOFF_MAX = float(os.getenv("BACKOFF_MAX", "10"))
    BACKOFF_JITTER = float(os.getenv("BACKOFF_JITTER", "0.25"))

    @staticmethod
    async def _send_with_retry(
        queue_url: str,
        msg_body: str,
        group_id: str,
        dedup_id: str,
        message_type: str,
    ) -> bool:
        import sys
        _mod = sys.modules.get("fog_node") or sys.modules.get("fog.fog_node")
        fog_state = getattr(_mod, "fog_state", None)
        fog_metrics = getattr(_mod, "fog_metrics", None)
        spool_store = getattr(_mod, "spool_store", None)

        if not fog_state or not fog_state.sqs_client or not queue_url:
            logger.info(f"{message_type} (local-only): {msg_body[:200]}")
            return True

        for attempt in range(1, SQSDispatcher.MAX_RETRIES + 1):
            try:
                fog_state.sqs_client.send_message(
                    QueueUrl=queue_url,
                    MessageBody=msg_body,
                    MessageGroupId=group_id,
                    MessageDeduplicationId=dedup_id,
                )
                fog_metrics.record_dispatch(1)
                _mod.sqs_last_success_time = datetime.utcnow()
                logger.info(f"Sent {message_type}: {group_id} (attempt {attempt})")
                return True
            except Exception as e:
                if attempt < SQSDispatcher.MAX_RETRIES:
                    delay = min(
                        SQSDispatcher.BACKOFF_MAX,
                        SQSDispatcher.BACKOFF_BASE * (2 ** attempt),
                    ) * random.uniform(
                        1 - SQSDispatcher.BACKOFF_JITTER,
                        1 + SQSDispatcher.BACKOFF_JITTER,
                    )
                    logger.warning(
                        f"SQS attempt {attempt}/{SQSDispatcher.MAX_RETRIES}"
                        f" failed: {e}. Retrying in {delay:.1f}s"
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.warning(
                        f"SQS unreachable after {SQSDispatcher.MAX_RETRIES}"
                        f" attempts. Spooling {message_type}"
                    )
                    station = _extract_station(msg_body)
                    spool_store.enqueue(
                        message_type, msg_body, dedup_id, junction_id=station
                    )
                    fog_metrics.record_spool_write()
                    return False
        return False

    @staticmethod
    async def send_aggregate(aggregate: AggregateMetric):
        from fog.config import FogConfig

        msg_body = aggregate.model_dump_json()
        idempotency_key = f"{aggregate.stationId}#{aggregate.timestamp}"
        await SQSDispatcher._send_with_retry(
            FogConfig.AGGREGATES_QUEUE_URL,
            msg_body,
            aggregate.stationId,
            idempotency_key,
            "aggregate",
        )

    @staticmethod
    async def send_event(alert: AlertEvent):
        import sys
        from fog.config import FogConfig
        _mod = sys.modules.get("fog_node") or sys.modules.get("fog.fog_node")
        fog_metrics = getattr(_mod, "fog_metrics", None)

        fog_metrics.record_alert()
        NotificationManager.send(alert)
        await SQSDispatcher._send_with_retry(
            FogConfig.EVENTS_QUEUE_URL,
            alert.model_dump_json(),
            alert.stationId,
            alert.alertId,
            "event",
        )


def _extract_station(msg_body: str) -> str:
    try:
        return json.loads(msg_body).get("stationId", "unknown")
    except (json.JSONDecodeError, TypeError):
        return "unknown"
