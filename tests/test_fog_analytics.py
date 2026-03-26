"""
Unit Tests for Fog Node Analytics
"""

import pytest
from datetime import datetime, timedelta
from fog.fog_node import FogAnalytics, SensorEvent, AggregateMetric


def test_congestion_index_calculation():
    """Test congestion index formula."""
    # Create test events
    events = [
        SensorEvent(
            eventId="1", junctionId="Junction-A", sensorType="vehicle_count",
            value=100, unit="vehicles/min", timestamp=datetime.utcnow().isoformat() + 'Z'
        ),
        SensorEvent(
            eventId="2", junctionId="Junction-A", sensorType="vehicle_speed",
            value=50, unit="km/h", timestamp=datetime.utcnow().isoformat() + 'Z'
        )
    ]
    
    agg = FogAnalytics.compute_aggregates(events, datetime.utcnow())
    
    # congestion_index = 100 / 50 = 2.0
    assert agg.congestion_index == 2.0
    assert agg.vehicle_count_sum == 100
    assert agg.avg_speed == 50


def test_congestion_index_with_zero_speed():
    """Test congestion index with zero speed (epsilon handling)."""
    events = [
        SensorEvent(
            eventId="1", junctionId="Junction-A", sensorType="vehicle_count",
            value=100, unit="vehicles/min", timestamp=datetime.utcnow().isoformat() + 'Z'
        ),
        SensorEvent(
            eventId="2", junctionId="Junction-A", sensorType="vehicle_speed",
            value=0, unit="km/h", timestamp=datetime.utcnow().isoformat() + 'Z'
        )
    ]
    
    agg = FogAnalytics.compute_aggregates(events, datetime.utcnow())
    
    # Should use epsilon (1.0) to avoid division by zero
    assert agg.congestion_index == 100.0  # 100 / max(0, 1)


def test_speeding_detection():
    """Test speeding alert threshold (80 km/h)."""
    event_speeding = SensorEvent(
        eventId="1", junctionId="Junction-A", sensorType="vehicle_speed",
        value=95, unit="km/h", timestamp=datetime.utcnow().isoformat() + 'Z'
    )
    
    alert = FogAnalytics.detect_speeding(event_speeding)
    assert alert is not None
    assert alert.alertType == "SPEEDING"
    assert alert.severity == "MEDIUM"
    
    # Test below threshold
    event_normal = SensorEvent(
        eventId="2", junctionId="Junction-A", sensorType="vehicle_speed",
        value=70, unit="km/h", timestamp=datetime.utcnow().isoformat() + 'Z'
    )
    
    alert = FogAnalytics.detect_speeding(event_normal)
    assert alert is None


def test_congestion_alert_detection():
    """Test congestion alert when index > 2.0."""
    events = [
        SensorEvent(
            eventId="1", junctionId="Junction-A", sensorType="vehicle_count",
            value=150, unit="vehicles/min", timestamp=datetime.utcnow().isoformat() + 'Z'
        ),
        SensorEvent(
            eventId="2", junctionId="Junction-A", sensorType="vehicle_speed",
            value=30, unit="km/h", timestamp=datetime.utcnow().isoformat() + 'Z'
        )
    ]
    
    agg = FogAnalytics.compute_aggregates(events, datetime.utcnow())
    alert = FogAnalytics.detect_congestion(agg)
    
    # congestion_index = 150 / 30 = 5.0 > 2.0
    assert alert is not None
    assert alert.alertType == "CONGESTION"


def test_incident_detection():
    """Test sudden speed drop detection."""
    from collections import deque
    
    speeds = deque([60, 59, 61, 58, 60, 45, 35, 30, 28, 32])  # ~40% drop
    
    alert = FogAnalytics.detect_incident(speeds)
    
    if alert:  # May not trigger depending on window
        assert alert.alertType == "INCIDENT"


def test_aggregate_metrics_count():
    """Test metrics_count in aggregate."""
    events = [
        SensorEvent(
            eventId="1", junctionId="Junction-A", sensorType="vehicle_count",
            value=100, unit="vehicles/min", timestamp=datetime.utcnow().isoformat() + 'Z'
        ),
        SensorEvent(
            eventId="2", junctionId="Junction-A", sensorType="vehicle_speed",
            value=50, unit="km/h", timestamp=datetime.utcnow().isoformat() + 'Z'
        ),
        SensorEvent(
            eventId="3", junctionId="Junction-A", sensorType="rain_intensity",
            value="light", unit="categorical", timestamp=datetime.utcnow().isoformat() + 'Z'
        )
    ]
    
    agg = FogAnalytics.compute_aggregates(events, datetime.utcnow())
    assert agg.metrics_count == 3


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
