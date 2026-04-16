import uuid
from collections import deque
from datetime import datetime
from typing import List, Optional

from fog.config import FogConfig
from fog.models import SensorEvent, AggregateMetric, AlertEvent


class FogAnalytics:

    @staticmethod
    def parse_timestamp(ts_str: str) -> datetime:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        return dt.replace(tzinfo=None)

    @staticmethod
    def compute_aggregates(
        events: List[SensorEvent], window_start: datetime
    ) -> Optional[AggregateMetric]:
        if not events:
            return None

        water_levels, flow_rates = [], []
        rainfall_values, soil_moisture_values, turbidity_values = [], [], []

        for event in events:
            sensor = event.sensorType
            if sensor == "water_level":
                water_levels.append(event.value)
            elif sensor == "flow_rate":
                flow_rates.append(event.value)
            elif sensor == "rainfall_intensity":
                rainfall_values.append(str(event.value))
            elif sensor == "soil_moisture":
                soil_moisture_values.append(event.value)
            elif sensor == "river_turbidity":
                turbidity_values.append(event.value)

        max_water = max(water_levels) if water_levels else 0
        avg_flow = sum(flow_rates) / len(flow_rates) if flow_rates else 0

        flow_factor = avg_flow / max(avg_flow, 10.0) if avg_flow > 0 else 0.1
        flood_risk_index = max_water * (0.5 + flow_factor)

        return AggregateMetric(
            stationId=events[0].stationId,
            timestamp=window_start.isoformat() + "Z",
            max_water_level=round(max_water, 2),
            avg_flow_rate=round(avg_flow, 2),
            flood_risk_index=round(flood_risk_index, 2),
            rainfall_intensity=rainfall_values[0] if rainfall_values else None,
            avg_soil_moisture=(
                round(sum(soil_moisture_values) / len(soil_moisture_values), 1)
                if soil_moisture_values else None
            ),
            avg_turbidity=(
                round(sum(turbidity_values) / len(turbidity_values), 2)
                if turbidity_values else None
            ),
            metrics_count=len(events),
        )

    @staticmethod
    def detect_high_water(event: SensorEvent) -> Optional[AlertEvent]:
        if event.sensorType != "water_level":
            return None

        val = event.value
        thresholds = [
            (FogConfig.WATER_LEVEL_CRITICAL, "CRITICAL", "critical"),
            (FogConfig.WATER_LEVEL_THRESHOLD, "HIGH", "danger"),
            (FogConfig.WATER_LEVEL_MEDIUM, "MEDIUM", "elevated"),
            (FogConfig.WATER_LEVEL_LOW, "LOW", "watch"),
        ]
        for limit, severity, label in thresholds:
            if val > limit:
                return AlertEvent(
                    alertId=str(uuid.uuid4()),
                    stationId=event.stationId,
                    alertType="HIGH_WATER",
                    severity=severity,
                    description=f"Water level {val}m exceeds {label} threshold {limit}m",
                    triggered_value=val,
                    threshold=limit,
                    timestamp=event.timestamp,
                )
        return None

    @staticmethod
    def detect_flood_warning(aggregate: AggregateMetric) -> Optional[AlertEvent]:
        ri = aggregate.flood_risk_index
        thresholds = [
            (FogConfig.FLOOD_RISK_CRITICAL, "CRITICAL", "critical"),
            (FogConfig.FLOOD_RISK_THRESHOLD, "HIGH", "danger"),
            (FogConfig.FLOOD_RISK_MEDIUM, "MEDIUM", "elevated"),
            (FogConfig.FLOOD_RISK_LOW, "LOW", "watch"),
        ]
        for limit, severity, label in thresholds:
            if ri > limit:
                return AlertEvent(
                    alertId=str(uuid.uuid4()),
                    stationId=aggregate.stationId,
                    alertType="FLOOD_WARNING",
                    severity=severity,
                    description=f"Flood risk index {ri} exceeds {label} threshold {limit}",
                    triggered_value=ri,
                    threshold=limit,
                    timestamp=aggregate.timestamp,
                )
        return None

    @staticmethod
    def detect_flash_flood(flow_rates: deque) -> Optional[AlertEvent]:
        if len(flow_rates) < 10:
            return None

        recent = list(flow_rates)[-5:]
        previous = list(flow_rates)[-10:-5]
        avg_recent = sum(recent) / len(recent)
        avg_previous = sum(previous) / len(previous)

        if avg_previous <= 0:
            return None

        spike_pct = ((avg_recent - avg_previous) / avg_previous) * 100
        if spike_pct > FogConfig.FLOW_RATE_SPIKE_PERCENTAGE:
            return AlertEvent(
                alertId=str(uuid.uuid4()),
                stationId="",
                alertType="FLASH_FLOOD",
                severity="CRITICAL",
                description=(
                    f"Sudden flow rate spike of {spike_pct:.1f}% detected"
                    " — possible flash flood!"
                ),
                triggered_value=avg_recent,
                threshold=avg_previous * 1.4,
                timestamp=datetime.utcnow().isoformat() + "Z",
            )
        return None
