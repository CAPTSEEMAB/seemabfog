"""
Fog Node Metrics Collector
Tracks incoming/outgoing rates, bandwidth reduction, and operational counters.
"""

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
    """Thread-safe (single event-loop) fog node metrics collector."""

    def __init__(self):
        # Counters (monotonically increasing)
        self.incoming_events_total: int = 0
        self.outgoing_messages_total: int = 0
        self.duplicates_dropped: int = 0
        self.alerts_generated: int = 0
        self.spool_writes_total: int = 0
        self.spool_flushes_total: int = 0
        self.last_flush_time_iso: Optional[str] = None

        # Sliding windows for rate computation (timestamp, count)
        self._incoming_window: deque = deque()
        self._outgoing_window: deque = deque()

        # Start time for uptime
        self.start_time = time.monotonic()

    # ── Counter Methods ─────────────────────────────────────────

    def record_ingest(self) -> None:
        """Called on every accepted (non-duplicate) event."""
        self.incoming_events_total += 1
        self._incoming_window.append((time.monotonic(), 1))

    def record_duplicate(self) -> None:
        """Called when an event is rejected as duplicate."""
        self.duplicates_dropped += 1

    def record_dispatch(self, count: int = 1) -> None:
        """Called on every successful SQS send."""
        self.outgoing_messages_total += count
        self._outgoing_window.append((time.monotonic(), count))

    def record_alert(self) -> None:
        """Called when an alert is generated."""
        self.alerts_generated += 1

    def record_spool_write(self) -> None:
        """Called when a message is written to local spool."""
        self.spool_writes_total += 1

    def record_spool_flush(self, count: int) -> None:
        """Called after successful spool flush."""
        self.spool_flushes_total += count
        self.last_flush_time_iso = datetime.utcnow().isoformat() + "Z"

    # ── Rate Computation ────────────────────────────────────────

    def incoming_rate(self) -> float:
        """Events/sec averaged over last 10 seconds."""
        return self._compute_rate(self._incoming_window, 10.0)

    def outgoing_rate(self) -> float:
        """Messages/sec averaged over last 10 seconds."""
        return self._compute_rate(self._outgoing_window, 10.0)

    def bandwidth_reduction(self) -> float:
        """
        Percentage reduction: (1 - outgoing/incoming) * 100.
        Represents how much raw data the fog absorbs.
        """
        if self.incoming_events_total == 0:
            return 0.0
        return round(
            (1 - self.outgoing_messages_total / self.incoming_events_total) * 100, 1
        )

    def uptime_sec(self) -> float:
        """Seconds since metrics collector was initialized."""
        return round(time.monotonic() - self.start_time, 1)

    # ── Export ──────────────────────────────────────────────────

    def snapshot_dict(self) -> dict:
        """Return all metrics as a flat dict (for CSV/JSON export)."""
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
        """Append current snapshot as one CSV row."""
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
        """Log metrics snapshot as structured JSON."""
        logger.info(f"METRICS: {json.dumps(self.snapshot_dict())}")

    # ── Internal ───────────────────────────────────────────────

    def _compute_rate(self, window: deque, span_sec: float) -> float:
        """Sliding window rate: sum counts where ts > now - span_sec."""
        cutoff = time.monotonic() - span_sec
        # Trim old entries
        while window and window[0][0] < cutoff:
            window.popleft()
        total = sum(c for _, c in window)
        return round(total / span_sec, 1)
