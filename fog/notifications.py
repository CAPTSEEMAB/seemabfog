import uuid
import logging
from collections import deque
from datetime import datetime

from fog.models import AlertEvent

logger = logging.getLogger(__name__)


class NotificationManager:

    _recent: deque = deque(maxlen=100)

    @classmethod
    def send(cls, alert: AlertEvent) -> dict:
        notification = {
            "id": str(uuid.uuid4()),
            "alert_id": alert.alertId,
            "station": alert.stationId,
            "type": alert.alertType,
            "severity": alert.severity,
            "message": alert.description,
            "value": alert.triggered_value,
            "threshold": alert.threshold,
            "timestamp": alert.timestamp,
            "notified_at": datetime.utcnow().isoformat() + "Z",
        }
        cls._recent.append(notification)

        if alert.severity in ("HIGH", "CRITICAL"):
            logger.critical(
                f"FLOOD WARNING [{alert.severity}] {alert.alertType}"
                f" at {alert.stationId}: {alert.description}"
            )
        else:
            logger.warning(
                f"FLOOD ALERT [{alert.severity}] {alert.alertType}"
                f" at {alert.stationId}: {alert.description}"
            )
        return notification

    @classmethod
    def get_recent(cls, limit: int = 20) -> list:
        return list(cls._recent)[-limit:][::-1]
