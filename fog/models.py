from typing import Optional, Union
from pydantic import BaseModel


class SensorEvent(BaseModel):
    eventId: str
    stationId: str
    sensorType: str
    value: Union[float, str]
    unit: str
    timestamp: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class AggregateMetric(BaseModel):
    stationId: str
    timestamp: str
    max_water_level: float
    avg_flow_rate: float
    flood_risk_index: float
    rainfall_intensity: Optional[str] = None
    avg_soil_moisture: Optional[float] = None
    avg_turbidity: Optional[float] = None
    metrics_count: int


class AlertEvent(BaseModel):
    alertId: str
    stationId: str
    alertType: str
    severity: str
    description: str
    triggered_value: float
    threshold: float
    timestamp: str
