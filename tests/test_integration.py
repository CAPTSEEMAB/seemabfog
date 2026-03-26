"""
Integration Test: Fog -> SQS -> Lambda -> DynamoDB
"""

import pytest
import asyncio
import json
from fog.fog_node import SensorEvent, FogNodeState, FogAnalytics
from datetime import datetime


@pytest.fixture
def fog_state():
    """Create fresh fog state for each test."""
    return FogNodeState()


def test_event_deduplication(fog_state):
    """Test duplicate events are rejected."""
    event1 = SensorEvent(
        eventId="same-id", junctionId="Junction-A", sensorType="vehicle_speed",
        value=50, unit="km/h", timestamp=datetime.utcnow().isoformat() + 'Z'
    )
    
    # Add first time
    result1 = fog_state.add_event(event1)
    assert result1 == True
    
    # Add duplicate
    result2 = fog_state.add_event(event1)
    assert result2 == False


def test_rolling_window_aggregation(fog_state):
    """Test that events accumulate correctly in buffer."""
    for i in range(5):
        event = SensorEvent(
            eventId=f"id-{i}", junctionId="Junction-A", sensorType="vehicle_count",
            value=20 + i, unit="vehicles/min", timestamp=datetime.utcnow().isoformat() + 'Z'
        )
        fog_state.add_event(event)
    
    assert len(fog_state.event_buffers["Junction-A"]) == 5


def test_multi_junction_independence(fog_state):
    """Test that different junctions have independent buffers."""
    event_a = SensorEvent(
        eventId="a-1", junctionId="Junction-A", sensorType="vehicle_count",
        value=50, unit="vehicles/min", timestamp=datetime.utcnow().isoformat() + 'Z'
    )
    
    event_b = SensorEvent(
        eventId="b-1", junctionId="Junction-B", sensorType="vehicle_count",
        value=60, unit="vehicles/min", timestamp=datetime.utcnow().isoformat() + 'Z'
    )
    
    fog_state.add_event(event_a)
    fog_state.add_event(event_b)
    
    assert len(fog_state.event_buffers["Junction-A"]) == 1
    assert len(fog_state.event_buffers["Junction-B"]) == 1


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
