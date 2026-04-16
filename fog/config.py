import json
import os


class FogConfig:

    WATER_LEVEL_LOW = float(os.getenv("WATER_LEVEL_LOW", "2.1"))
    WATER_LEVEL_MEDIUM = float(os.getenv("WATER_LEVEL_MEDIUM", "2.5"))
    WATER_LEVEL_THRESHOLD = float(os.getenv("WATER_LEVEL_THRESHOLD", "3.2"))
    WATER_LEVEL_CRITICAL = float(os.getenv("WATER_LEVEL_CRITICAL", "5.25"))

    FLOOD_RISK_LOW = float(os.getenv("FLOOD_RISK_LOW", "1.5"))
    FLOOD_RISK_MEDIUM = float(os.getenv("FLOOD_RISK_MEDIUM", "2.2"))
    FLOOD_RISK_THRESHOLD = float(os.getenv("FLOOD_RISK_THRESHOLD", "3.0"))
    FLOOD_RISK_CRITICAL = float(os.getenv("FLOOD_RISK_CRITICAL", "4.0"))

    FLOW_RATE_SPIKE_PERCENTAGE = float(os.getenv("FLOW_RATE_SPIKE_PERCENTAGE", "40"))

    WINDOW_SIZE_SEC = int(os.getenv("WINDOW_SIZE_SEC", "10"))
    DEDUP_CACHE_TTL_SEC = int(os.getenv("DEDUP_CACHE_TTL_SEC", "10"))
    AGGREGATE_INTERVAL_SEC = int(os.getenv("AGGREGATE_INTERVAL_SEC", "10"))

    AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
    AGGREGATES_QUEUE_URL = os.getenv("AGGREGATES_QUEUE_URL", "")
    EVENTS_QUEUE_URL = os.getenv("EVENTS_QUEUE_URL", "")

    SENSOR_BOUNDS = json.loads(
        os.getenv(
            "SENSOR_BOUNDS",
            '{"water_level":[0,15],"flow_rate":[0,500],'
            '"river_turbidity":[0,1000],"soil_moisture":[0,100]}',
        )
    )
