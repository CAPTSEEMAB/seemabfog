"""
Tests for LocalSpoolStore – disk-backed store-and-forward.
Covers: enqueue, flush, rotation, size limits, concurrency.
"""

import asyncio
import json
import os
import shutil
import tempfile
import pytest

# Ensure project root on path
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'fog'))

from spool import LocalSpoolStore, SpoolFlushError


@pytest.fixture
def spool_dir(tmp_path):
    """Provide a temp spool directory that is cleaned up after test."""
    d = tmp_path / "spool_test"
    d.mkdir()
    return str(d)


@pytest.fixture
def spool(spool_dir):
    """Return a LocalSpoolStore wired to the temp directory with small limits."""
    store = LocalSpoolStore(spool_dir=spool_dir)
    # Override class constants for testability
    store.MAX_LINES_PER_FILE = 5
    store.ROTATION_INTERVAL_SEC = 9999
    store.MAX_SPOOL_FILES = 3
    return store


# ── T-1  Basic enqueue + spool_size ────────────────────────

def test_enqueue_creates_file_and_counts(spool, spool_dir):
    """Enqueue writes JSONL and spool_size reflects count."""
    spool.enqueue("aggregate", '{"a": 1}', "key-1")
    spool.enqueue("aggregate", '{"b": 2}', "key-2")
    assert spool.spool_size() == 2

    # Verify actual file on disk
    files = [f for f in os.listdir(spool_dir) if f.endswith(".jsonl")]
    assert len(files) >= 1

    # Read first line and verify JSON structure
    with open(os.path.join(spool_dir, files[0])) as f:
        line = json.loads(f.readline())
    assert line["type"] == "aggregate"
    assert line["idempotency_key"] == "key-1"


# ── T-2  Line-based rotation ───────────────────────────────

def test_rotation_after_max_lines(spool, spool_dir):
    """After max_lines_per_file (5) a new file is created."""
    for i in range(7):
        spool.enqueue("aggregate", json.dumps({"i": i}), f"key-{i}")

    files = sorted(f for f in os.listdir(spool_dir) if f.endswith(".jsonl"))
    assert len(files) == 2, f"Expected 2 files, got {files}"
    assert spool.spool_size() == 7


# ── T-3  Max-files enforcement ─────────────────────────────

def test_max_files_enforced(spool, spool_dir):
    """Oldest file is deleted when max_files (3) exceeded."""
    # Each file = 5 lines; write 20 lines → should force rotation + purge
    for i in range(20):
        spool.enqueue("aggregate", json.dumps({"i": i}), f"key-{i}")

    files = [f for f in os.listdir(spool_dir) if f.endswith(".jsonl")]
    assert len(files) <= 3, f"Expected <=3 files, got {len(files)}"


# ── T-4  flush_to_sqs success path ─────────────────────────

@pytest.mark.asyncio
async def test_flush_success(spool, spool_dir):
    """Flush calls SQS, removes files, returns count."""
    for i in range(8):
        spool.enqueue("aggregate", json.dumps({"i": i}), f"key-{i}")

    sent = []

    class FakeSQS:
        def send_message(self, **kwargs):
            sent.append(json.loads(kwargs["MessageBody"]))
            return {"MessageId": "ok"}

    flushed = await spool.flush_to_sqs(
        sqs_client=FakeSQS(),
        agg_queue_url="https://fake.agg.queue",
        evt_queue_url="https://fake.evt.queue"
    )

    assert flushed == 8
    assert spool.spool_size() == 0
    assert len(sent) == 8


# ── T-5  flush_to_sqs failure → SpoolFlushError ────────────

@pytest.mark.asyncio
async def test_flush_failure_raises(spool):
    """Flush raises SpoolFlushError when SQS fails."""
    spool.enqueue("aggregate", '{"x": 1}', "key-fail")

    class BrokenSQS:
        def send_message(self, **kwargs):
            raise Exception("SQS down")

    with pytest.raises(SpoolFlushError):
        await spool.flush_to_sqs(
            sqs_client=BrokenSQS(),
            agg_queue_url="https://fake.agg.queue",
            evt_queue_url="https://fake.evt.queue"
        )

    # Data should still be on disk
    assert spool.spool_size() >= 1


# ── T-6  Empty spool flush is a no-op ──────────────────────

@pytest.mark.asyncio
async def test_flush_empty_is_noop(spool):
    """Flushing an empty spool returns 0 without calling SQS."""
    class FakeSQS:
        def send_message(self, **kwargs):
            raise AssertionError("should not be called")

    flushed = await spool.flush_to_sqs(
        sqs_client=FakeSQS(),
        agg_queue_url="https://fake.agg.queue",
        evt_queue_url="https://fake.evt.queue"
    )
    assert flushed == 0
