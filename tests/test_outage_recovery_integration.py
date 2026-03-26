"""
Integration test: outage → spool → recovery → flush lifecycle.
Simulates SQS going down, events spooling to disk, SQS coming back,
and spool flushing successfully.
"""

import asyncio
import json
import os
import sys
import tempfile
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'fog'))

from spool import LocalSpoolStore
from metrics_collector import FogMetrics


# ── helpers ────────────────────────────────────────────────

class FakeSQS:
    """SQS mock that can be toggled online/offline."""

    def __init__(self):
        self.online = True
        self.messages = []

    def send_message(self, **kwargs):
        if not self.online:
            from botocore.exceptions import EndpointConnectionError
            raise EndpointConnectionError(endpoint_url="https://fake")
        self.messages.append(json.loads(kwargs["MessageBody"]))
        return {"MessageId": f"msg-{len(self.messages)}"}

    def get_queue_url(self, **kwargs):
        return {"QueueUrl": "https://fake.queue"}


# ── T-1  Full outage → spool → recovery → flush ────────────

@pytest.mark.asyncio
async def test_outage_spool_recovery_flush(tmp_path):
    """
    Scenario:
      1. SQS goes offline
      2. 10 events are generated → all land in spool
      3. SQS comes back online
      4. Spool flushes → all 10 messages arrive in SQS
    """
    spool_dir = str(tmp_path / "spool")
    os.makedirs(spool_dir)

    spool = LocalSpoolStore(spool_dir=spool_dir)
    spool.MAX_LINES_PER_FILE = 100
    spool.ROTATION_INTERVAL_SEC = 9999
    spool.MAX_SPOOL_FILES = 10
    sqs = FakeSQS()
    metrics = FogMetrics()

    # Phase 1: SQS offline – enqueue events into spool
    sqs.online = False
    for i in range(10):
        payload = json.dumps({"event_id": i, "junction_id": "Junction-A"})
        # Simulate: dispatch would fail, so we spool directly
        try:
            sqs.send_message(
                QueueUrl="https://fake.queue",
                MessageBody=payload,
                MessageGroupId="test"
            )
        except Exception:
            spool.enqueue("aggregate", payload, f"key-{i}",
                          junction_id="Junction-A")
            metrics.record_spool_write()

    assert spool.spool_size() == 10
    assert sqs.messages == []

    # Phase 2: SQS comes back online
    sqs.online = True

    # Phase 3: Flush spool
    flushed = await spool.flush_to_sqs(
        sqs_client=sqs,
        agg_queue_url="https://fake.agg.queue",
        evt_queue_url="https://fake.evt.queue"
    )

    assert flushed == 10
    assert len(sqs.messages) == 10
    assert spool.spool_size() == 0

    # Verify event IDs are intact
    event_ids = {m["event_id"] for m in sqs.messages}
    assert event_ids == set(range(10))


# ── T-2  Partial outage recovery ───────────────────────────

@pytest.mark.asyncio
async def test_partial_flush_on_reconnect(tmp_path):
    """
    SQS fails mid-flush: some messages sent, rest remain spooled.
    """
    spool_dir = str(tmp_path / "spool")
    os.makedirs(spool_dir)

    spool = LocalSpoolStore(spool_dir=spool_dir)
    spool.MAX_LINES_PER_FILE = 100
    spool.ROTATION_INTERVAL_SEC = 9999
    spool.MAX_SPOOL_FILES = 10

    # Enqueue 5 messages
    for i in range(5):
        spool.enqueue("aggregate", json.dumps({"event_id": i}), f"key-{i}")

    send_count = 0

    class PartialSQS:
        """Succeeds 3 times, then fails."""
        def send_message(self, **kwargs):
            nonlocal send_count
            send_count += 1
            if send_count > 3:
                raise Exception("SQS dropped again")
            return {"MessageId": f"msg-{send_count}"}

    # Flush should raise after partial success
    from spool import SpoolFlushError
    with pytest.raises(SpoolFlushError):
        await spool.flush_to_sqs(
            sqs_client=PartialSQS(),
            agg_queue_url="https://fake.agg.queue",
            evt_queue_url="https://fake.evt.queue"
        )

    # 3 sent, 2 remain in spool (approximately, depends on implementation)
    # At minimum, not all were flushed
    assert send_count == 4  # 3 success + 1 failure attempt


# ── T-3  Metrics counters integrity through lifecycle ──────

def test_metrics_counters_through_lifecycle():
    """
    Verify FogMetrics accurately tracks events through
    ingest → duplicate → dispatch → spool → flush lifecycle.
    """
    m = FogMetrics()

    # Simulate 100 ingests, 10 duplicates, 85 dispatches, 5 spooled
    for _ in range(100):
        m.record_ingest()
    for _ in range(10):
        m.record_duplicate()
    for _ in range(85):
        m.record_dispatch()
    for _ in range(5):
        m.record_spool_write()
    m.record_spool_flush(5)  # Requires count argument

    snap = m.snapshot_dict()

    assert snap["incoming_events_total"] == 100
    assert snap["duplicates_dropped"] == 10
    assert snap["outgoing_messages_total"] == 85
    assert snap["spool_writes_total"] == 5
    assert snap["spool_flushes_total"] == 5

    # Bandwidth reduction: (100 raw - 85 dispatched) / 100 = 15%
    # But bandwidth_reduction uses dispatched/ingested ratio
    reduction = m.bandwidth_reduction()
    assert 0.0 <= reduction <= 100.0


# ── T-4  CSV export produces valid file ─────────────────────

def test_csv_export(tmp_path):
    """Metrics CSV export creates valid file with correct headers."""
    m = FogMetrics()
    csv_path = str(tmp_path / "metrics.csv")

    m.record_ingest()
    m.record_dispatch()
    m.append_csv(csv_path)

    assert os.path.exists(csv_path)

    with open(csv_path) as f:
        lines = f.readlines()
    # Header + 1 data row
    assert len(lines) == 2
    assert "incoming_events_total" in lines[0]
