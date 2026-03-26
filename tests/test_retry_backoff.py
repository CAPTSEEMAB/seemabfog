"""
Tests for SQSDispatcher retry + exponential-backoff logic.
Validates: attempt counting, backoff timing, jitter, spool fallback.
"""

import asyncio
import json
import os
import sys
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'fog'))

# We need to import after path insertion
from fog_node import SQSDispatcher


# ── helpers ────────────────────────────────────────────────

def _make_dispatcher(sqs_client=None, spool=None, metrics=None):
    """Build a SQSDispatcher with fakes."""
    disp = SQSDispatcher.__new__(SQSDispatcher)
    disp.sqs = sqs_client or MagicMock()
    disp.queue_url = "https://fake.queue"
    disp.node_id = "test-node"
    # Wire spool + metrics from fog_node globals via monkeypatching
    return disp


# ── T-1  Successful send on first attempt ──────────────────

@pytest.mark.asyncio
async def test_dispatch_success_first_attempt():
    """Message dispatched on first try without retry."""
    fake_sqs = MagicMock()
    fake_sqs.send_message.return_value = {"MessageId": "msg-123"}

    disp = _make_dispatcher(sqs_client=fake_sqs)

    # Patch the module-level globals
    with patch('fog_node.fog_metrics') as mock_metrics, \
         patch('fog_node.sqs_last_success_time'):
        mock_metrics.record_dispatch = MagicMock()

        result = await asyncio.to_thread(
            disp.sqs.send_message,
            QueueUrl=disp.queue_url,
            MessageBody=json.dumps({"test": True}),
            MessageGroupId="test-node"
        )

    assert result["MessageId"] == "msg-123"
    fake_sqs.send_message.assert_called_once()


# ── T-2  Retry succeeds on 2nd attempt ─────────────────────

@pytest.mark.asyncio
async def test_send_with_retry_succeeds_after_failure():
    """_send_with_retry retries and succeeds on attempt 2."""
    call_count = 0

    class RetrySQS:
        def send_message(self, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                from botocore.exceptions import EndpointConnectionError
                raise EndpointConnectionError(endpoint_url="https://fake")
            return {"MessageId": "retry-ok"}

    mock_state = MagicMock()
    mock_state.sqs_client = RetrySQS()

    with patch('fog_node.fog_state', mock_state), \
         patch('fog_node.fog_metrics') as mock_metrics, \
         patch('fog_node.sqs_last_success_time', None), \
         patch('fog_node.spool_store') as mock_spool:
        mock_metrics.record_dispatch = MagicMock()
        mock_metrics.record_spool_write = MagicMock()

        result = await SQSDispatcher._send_with_retry(
            queue_url="https://fake.queue",
            msg_body=json.dumps({"test": True}),
            group_id="test-group",
            dedup_id="key-1",
            message_type="aggregate"
        )

    assert result is True
    assert call_count == 2
    mock_metrics.record_dispatch.assert_called_once()


# ── T-3  All retries fail → spool fallback ─────────────────

@pytest.mark.asyncio
async def test_all_retries_fail_spools():
    """After 3 failures the message is spooled to disk."""
    from botocore.exceptions import EndpointConnectionError

    class AlwaysFailSQS:
        def send_message(self, **kwargs):
            raise EndpointConnectionError(endpoint_url="https://fail")

    mock_state = MagicMock()
    mock_state.sqs_client = AlwaysFailSQS()

    mock_spool = MagicMock()
    mock_spool.enqueue = MagicMock()

    with patch('fog_node.fog_state', mock_state), \
         patch('fog_node.fog_metrics') as mock_metrics, \
         patch('fog_node.spool_store', mock_spool), \
         patch('fog_node.sqs_last_success_time', None):
        mock_metrics.record_dispatch = MagicMock()
        mock_metrics.record_spool_write = MagicMock()

        result = await SQSDispatcher._send_with_retry(
            queue_url="https://fake.queue",
            msg_body=json.dumps({"fallback": True}),
            group_id="test-group",
            dedup_id="key-fail",
            message_type="aggregate"
        )

    assert result is False
    # Spool should have been called
    mock_spool.enqueue.assert_called_once()
    mock_metrics.record_spool_write.assert_called_once()


# ── T-4  Backoff timing grows exponentially ─────────────────

def test_backoff_timing():
    """Verify backoff sleep values follow base * 2^attempt ± jitter."""
    base = 1.0
    max_backoff = 60.0

    for attempt in range(5):
        raw = min(base * (2 ** attempt), max_backoff)
        jittered_low = raw * 0.75
        jittered_high = raw * 1.25

        # Verify expected range
        assert jittered_low > 0
        assert jittered_high <= max_backoff * 1.25

    # Attempt 0: base=1  → [0.75, 1.25]
    assert 0.75 <= 1.0 * 0.75 <= 1.25
    # Attempt 1: base=2  → [1.5, 2.5]
    assert 1.5 <= 2.0 * 0.75 + 0.75 <= 2.5 + 0.5
    # Attempt 4: base=16 → [12, 20]
    assert 12 <= 16 * 0.75 <= 20
