import time
import json
import os
import csv
import logging
from collections import deque
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


class FogMetrics:

    def __init__(self):
        self.incoming_events_total: int = 0
        self.outgoing_messages_total: int = 0
        self.duplicates_dropped: int = 0
        self.alerts_generated: int = 0
        self.spool_writes_total: int = 0
        self.spool_flushes_total: int = 0
        self.last_flush_time_iso: Optional[str] = None

        self._incoming_window: deque = deque()
        self._outgoing_window: deque = deque()

        self.start_time = time.monotonic()


    def record_ingest(self) -> None:
        self.incoming_events_total += 1
        self._incoming_window.append((time.monotonic(), 1))

    def record_duplicate(self) -> None:
        self.duplicates_dropped += 1

    def record_dispatch(self, count: int = 1) -> None:
        self.outgoing_messages_total += count
        self._outgoing_window.append((time.monotonic(), count))

    def record_alert(self) -> None:
        self.alerts_generated += 1

    def record_spool_write(self) -> None:
        self.spool_writes_total += 1

    def record_spool_flush(self, count: int) -> None:
        self.spool_flushes_total += count
        self.last_flush_time_iso = datetime.utcnow().isoformat() + "Z"


    def incoming_rate(self) -> float:
        return self._compute_rate(self._incoming_window, 10.0)

    def outgoing_rate(self) -> float:
        return self._compute_rate(self._outgoing_window, 10.0)

    def bandwidth_reduction(self) -> float:
        if self.incoming_events_total == 0:
            return 0.0
        return round(
            (1 - self.outgoing_messages_total / self.incoming_events_total) * 100, 1
        )

    def uptime_sec(self) -> float:
        return round(time.monotonic() - self.start_time, 1)


    def snapshot_dict(self) -> dict:
        return {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "incoming_events_total": self.incoming_events_total,
            "outgoing_messages_total": self.outgoing_messages_total,
            "duplicates_dropped": self.duplicates_dropped,
            "alerts_generated": self.alerts_generated,
            "incoming_rate_eps": self.incoming_rate(),
            "outgoing_rate_mps": self.outgoing_rate(),
            "bandwidth_reduction_pct": self.bandwidth_reduction(),
            "spool_writes_total": self.spool_writes_total,
            "spool_flushes_total": self.spool_flushes_total,
        }

    def append_csv(self, csv_path: str, extra_fields: Optional[dict] = None) -> None:
        row = self.snapshot_dict()
        if extra_fields:
            row.update(extra_fields)

        os.makedirs(os.path.dirname(csv_path) or ".", exist_ok=True)
        file_exists = os.path.exists(csv_path)
        try:
            with open(csv_path, "a", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=row.keys())
                if not file_exists:
                    writer.writeheader()
                writer.writerow(row)
        except OSError as e:
            logger.warning(f"CSV export failed: {e}")

    def log_snapshot(self) -> None:
        logger.info(f"METRICS: {json.dumps(self.snapshot_dict())}")


    def _compute_rate(self, window: deque, span_sec: float) -> float:
        cutoff = time.monotonic() - span_sec
        while window and window[0][0] < cutoff:
            window.popleft()
        total = sum(c for _, c in window)
        return round(total / span_sec, 1)
