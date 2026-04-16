#!/usr/bin/env python3

import json
import math
import os
import random
import time
import uuid
import argparse
import threading
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import yaml
import requests


EA_API_BASE = "https://environment.data.gov.uk/flood-monitoring"

EA_STATION_MAP = {
    "River-Station-A": {
        "level_station": "1490TH",
        "level_measure": "1490TH-level-stage-i-15_min-mASD",
        "flow_station": "1490TH",
        "flow_measure": "1490TH-flow--Mean-15_min-m3_s",
        "rainfall_station": "256230TP",
        "rainfall_measure": "256230TP-rainfall-tipping_bucket_raingauge-t-15_min-mm",
        "label": "Oxford Botanical Gardens (River Cherwell)",
    },
    "River-Station-B": {
        "level_station": "1491TH",
        "level_measure": "1491TH-level-stage-i-15_min-mASD",
        "flow_station": "1490TH",
        "flow_measure": "1490TH-flow--Mean-15_min-m3_s",
        "rainfall_station": "256230TP",
        "rainfall_measure": "256230TP-rainfall-tipping_bucket_raingauge-t-15_min-mm",
        "label": "Kings Mill (River Cherwell)",
    },
}

REFRESH_INTERVAL = 120


class RealDataCache:

    def __init__(self):
        self._cache: Dict[str, Dict[str, Optional[float]]] = {}
        self._last_fetch: float = 0
        self._lock = threading.Lock()
        self._enabled = os.getenv("USE_REAL_DATA", "true").lower() == "true"

    @property
    def enabled(self) -> bool:
        return self._enabled

    def get(self, station_id: str, sensor_type: str) -> Optional[float]:
        with self._lock:
            entry = self._cache.get(station_id, {})
            return entry.get(sensor_type)

    def refresh_if_stale(self):
        if not self._enabled:
            return
        now = time.time()
        if now - self._last_fetch < REFRESH_INTERVAL:
            return
        self._last_fetch = now
        threading.Thread(target=self._fetch_all, daemon=True).start()

    def _fetch_reading(self, measure_id: str) -> Optional[float]:
        url = f"{EA_API_BASE}/id/measures/{measure_id}/readings?_sorted&_limit=1"
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                items = resp.json().get("items", [])
                if items:
                    val = items[0].get("value")
                    return float(val) if val is not None else None
        except Exception as e:
            print(f"  [RealData] fetch failed {measure_id}: {e}")
        return None

    def _fetch_all(self):
        print("[RealData] Fetching latest UK Environment Agency readings...")
        new_cache: Dict[str, Dict[str, Optional[float]]] = {}
        for station_id, mapping in EA_STATION_MAP.items():
            readings: Dict[str, Optional[float]] = {}

            wl = self._fetch_reading(mapping["level_measure"])
            if wl is not None:
                readings["water_level"] = wl

            fl = self._fetch_reading(mapping["flow_measure"])
            if fl is not None:
                readings["flow_rate"] = fl

            rf = self._fetch_reading(mapping["rainfall_measure"])
            if rf is not None:
                readings["rainfall_mm"] = rf

            new_cache[station_id] = readings
            src = mapping["label"]
            print(f"  [RealData] {station_id} ({src}): water_level={readings.get('water_level')}m, "
                  f"flow_rate={readings.get('flow_rate')}m³/s, rainfall={readings.get('rainfall_mm')}mm")

        with self._lock:
            self._cache = new_cache
        print("[RealData] Cache updated successfully")


real_data = RealDataCache()


class FloodPattern:

    @staticmethod
    def sinusoidal_baseline(hour: float, min_val: float, max_val: float) -> float:
        amp = (max_val - min_val) / 2
        mid = (max_val + min_val) / 2
        return mid + amp * math.sin((hour - 6) * math.pi / 12)

    @staticmethod
    def storm_multiplier(hour: float) -> float:
        if 14 <= hour < 18:
            return 1.0 + 2.0 * math.sin((hour - 14) * math.pi / 4)
        if 2 <= hour < 5:
            return 1.0 + 1.5 * math.sin((hour - 2) * math.pi / 3)
        return 1.0

    @staticmethod
    def flood_surge(elapsed: float, duration: float, max_increase: float) -> float:
        if elapsed < 0 or elapsed > duration:
            return 0.0
        rise = duration * 0.3
        if elapsed < rise:
            return (elapsed / rise) * max_increase
        return ((duration - elapsed) / (duration - rise)) * max_increase


GENERATOR_MAP = {}


def _register(name):
    def decorator(fn):
        GENERATOR_MAP[name] = fn
        return fn
    return decorator


class SensorSimulator:

    def __init__(self, config_path: str):
        with open(config_path, "r") as f:
            self.config = yaml.safe_load(f)
        self.sim_start_time = datetime.utcnow()
        self.acceleration_factor = self.config["simulation"]["time_acceleration_factor"]
        self.sim_real_start = time.time()
        self.active_surges: Dict[str, dict] = {}
        self._flood_surge: Optional[dict] = None
        self._endpoint_map: Optional[Dict[str, str]] = None


    def get_simulated_time(self) -> datetime:
        elapsed = (time.time() - self.sim_real_start) * self.acceleration_factor
        return self.sim_start_time + timedelta(seconds=elapsed)

    def _hour_fraction(self) -> float:
        now = self.get_simulated_time()
        return now.hour + now.minute / 60.0


    @_register("water_level")
    def generate_water_level(self, station_id: str, cfg: Dict) -> float:
        real_val = real_data.get(station_id, "water_level")
        if real_val is not None:
            baseline = real_val
        else:
            hour = self._hour_fraction()
            baseline = FloodPattern.sinusoidal_baseline(hour, cfg["baseline_min"], cfg["baseline_max"])
            baseline = baseline * (0.7 + 0.3 * FloodPattern.storm_multiplier(hour))

        level = baseline
        now = self.get_simulated_time()
        self.active_surges = {
            k: v for k, v in self.active_surges.items()
            if (now - v["start"]).total_seconds() < v["duration"]
        }

        n_station = sum(1 for k in self.active_surges if k.startswith(station_id))
        if random.random() < 0.001 and n_station < 2:
            self.active_surges[f"{station_id}_surge_{uuid.uuid4()}"] = {
                "start": now, "duration": 180, "type": "flood_surge",
            }

        for surge in self.active_surges.values():
            elapsed = (now - surge["start"]).total_seconds()
            if 0 <= elapsed < surge["duration"]:
                level += FloodPattern.flood_surge(elapsed, surge["duration"], cfg.get("surge_max", 2.0))

        level += random.gauss(0, 0.05)
        return round(max(cfg["min_bound"], min(level, cfg["max_bound"])), 2)

    @_register("flow_rate")
    def generate_flow_rate(self, station_id: str, cfg: Dict) -> float:
        real_val = real_data.get(station_id, "flow_rate")
        if real_val is not None:
            baseline = real_val
        else:
            hour = self._hour_fraction()
            baseline = cfg["baseline_mean"] * (0.6 + 0.4 * FloodPattern.storm_multiplier(hour))

        now = self.get_simulated_time()
        flow = random.gauss(baseline, cfg["baseline_std"] * 0.3)

        for surge in self.active_surges.values():
            elapsed = (now - surge["start"]).total_seconds()
            if 0 <= elapsed < surge["duration"]:
                flow += FloodPattern.flood_surge(elapsed, surge["duration"], cfg.get("surge_max", 50.0))

        return round(max(cfg["min_bound"], min(flow, cfg["max_bound"])), 2)

    @_register("rainfall_intensity")
    def generate_rainfall_intensity(self, station_id: str, cfg: Dict) -> str:
        real_mm = real_data.get(station_id, "rainfall_mm")
        if real_mm is not None:
            if real_mm >= 4.0:
                return "heavy"
            elif real_mm >= 1.0:
                return "moderate"
            elif real_mm > 0.0:
                return "light"
            else:
                return "none"
        storm = FloodPattern.storm_multiplier(self._hour_fraction())
        if storm > 1.5:
            dist = [0.2, 0.25, 0.3, 0.25]
        elif storm > 1.2:
            dist = [0.35, 0.3, 0.2, 0.15]
        else:
            dist = cfg["baseline_distribution"]
        return random.choices(cfg["categories"], weights=dist)[0]

    @_register("soil_moisture")
    def generate_soil_moisture(self, _station_id: str, cfg: Dict) -> float:
        real_rain = real_data.get(_station_id, "rainfall_mm")
        if real_rain is not None:
            rain_boost = min(real_rain * 5.0, 30.0)
            val = cfg["baseline_mean"] + rain_boost + random.gauss(0, cfg["baseline_std"] * 0.3)
        else:
            storm = FloodPattern.storm_multiplier(self._hour_fraction())
            val = random.gauss(cfg["baseline_mean"] * (0.7 + 0.3 * storm), cfg["baseline_std"])
        return round(max(cfg["min_bound"], min(val, cfg["max_bound"])), 1)

    @_register("river_turbidity")
    def generate_turbidity(self, station_id: str, cfg: Dict) -> float:
        real_wl = real_data.get(station_id, "water_level")
        real_fl = real_data.get(station_id, "flow_rate")
        if real_wl is not None and real_fl is not None:
            val = (real_wl * 5.0 + real_fl * 2.0) + random.gauss(0, cfg["baseline_std"] * 0.3)
        else:
            storm = FloodPattern.storm_multiplier(self._hour_fraction())
            val = random.gauss(cfg["baseline_mean"] * (0.5 + 0.5 * storm), cfg["baseline_std"])
        return round(max(cfg["min_bound"], min(val, cfg["max_bound"])), 2)


    def generate_event(self, station: Dict, sensor_config: Dict = None) -> Dict[str, Any]:
        if sensor_config is None:
            sensor_config = random.choice(station["sensors"])
        name = sensor_config["name"]
        gen = GENERATOR_MAP.get(name)
        value = gen(self, station["id"], sensor_config) if gen else None

        now = self.get_simulated_time()
        return {
            "eventId": str(uuid.uuid4()),
            "stationId": station["id"],
            "sensorType": name,
            "value": value,
            "unit": sensor_config["unit"],
            "timestamp": now.isoformat() + "Z",
            "latitude": station["latitude"],
            "longitude": station["longitude"],
        }


    SURGE_CURVE = [
        (0.00, 1.5), (0.10, 2.0), (0.20, 2.6), (0.30, 3.0),
        (0.40, 3.5), (0.50, 6.0), (0.60, 3.5), (0.70, 3.0),
        (0.80, 2.6), (0.90, 2.0), (1.00, 1.5),
    ]

    def _start_flood_surge(self, station: Dict):
        self._flood_surge = {
            "station_id": station["id"],
            "station": station,
            "start_time": time.time(),
            "duration": 40,
        }
        print(f"  >> FLOOD SURGE @ {station['id']} — 40s ramp through all severity zones")

    def _get_surge_water_level(self) -> Optional[float]:
        if self._flood_surge is None:
            return None
        frac = (time.time() - self._flood_surge["start_time"]) / self._flood_surge["duration"]
        if frac > 1.0:
            self._flood_surge = None
            return None
        for i in range(len(self.SURGE_CURVE) - 1):
            t0, v0 = self.SURGE_CURVE[i]
            t1, v1 = self.SURGE_CURVE[i + 1]
            if t0 <= frac <= t1:
                seg = (frac - t0) / (t1 - t0) if (t1 - t0) > 0 else 0
                return v0 + seg * (v1 - v0)
        return self.SURGE_CURVE[-1][1]

    def _generate_surge_event(self, water_level: float) -> Optional[Dict[str, Any]]:
        if self._flood_surge is None:
            return None
        station = self._flood_surge["station"]
        water_cfg = next(s for s in station["sensors"] if s["name"] == "water_level")
        val = round(max(0, water_level + random.gauss(0, 0.05)), 2)
        now = self.get_simulated_time()
        return {
            "eventId": str(uuid.uuid4()),
            "stationId": station["id"],
            "sensorType": "water_level",
            "value": val,
            "unit": water_cfg["unit"],
            "timestamp": now.isoformat() + "Z",
            "latitude": station["latitude"],
            "longitude": station["longitude"],
        }


    def _resolve_endpoints(self):
        if self._endpoint_map is not None:
            return
        ids = [s["id"] for s in self.config["stations"]]
        endpoints = [
            os.getenv("FOG_ENDPOINT_A", self.config["output"].get("fog_endpoint_a", "")),
            os.getenv("FOG_ENDPOINT_B", self.config["output"].get("fog_endpoint_b", "")),
        ]
        self._endpoint_map = dict(zip(ids, endpoints))

    def _send_event(self, event: Dict, station: Dict):
        self._resolve_endpoints()
        endpoint = self._endpoint_map.get(station["id"])
        if not endpoint:
            print(f"No endpoint for {station['id']}")
            return
        try:
            resp = requests.post(endpoint, json=event, timeout=2)
            if resp.status_code != 202:
                print(f"Fog returned {resp.status_code}: {resp.text}")
        except requests.exceptions.RequestException as e:
            print(f"Send failed to {endpoint}: {e}")


    def run_stream(self, duration_minutes: int = 60):
        if real_data.enabled:
            print(f"[RealData] Mode ENABLED — using UK Environment Agency live readings as baseline")
            labels = ", ".join(k + " -> " + v["label"] for k, v in EA_STATION_MAP.items())
            print(f"[RealData] Stations: {labels}")
            real_data.refresh_if_stale()
            time.sleep(3)
        else:
            print("[RealData] Mode DISABLED — using synthetic patterns only")

        print(f"Simulation: {duration_minutes}min, 1 evt/s, surge every 60s")
        schedule = [
            (station, sensor)
            for station in self.config["stations"]
            for sensor in station["sensors"]
        ]
        start = time.time()
        idx = 0
        last_surge = 0.0
        SURGE_INTERVAL = 60

        try:
            while time.time() - start < duration_minutes * 60:
                real_data.refresh_if_stale()

                elapsed = time.time() - start
                if elapsed - last_surge >= SURGE_INTERVAL:
                    self._start_flood_surge(random.choice(self.config["stations"]))
                    last_surge = elapsed

                wl = self._get_surge_water_level()
                if wl is not None:
                    evt = self._generate_surge_event(wl)
                    if evt:
                        self._send_event(evt, self._flood_surge["station"])

                station, sensor = schedule[idx % len(schedule)]
                idx += 1
                self._send_event(self.generate_event(station, sensor), station)
                time.sleep(1.0)
        except KeyboardInterrupt:
            print(f"\nStopped after {idx} events.")


def main():
    parser = argparse.ArgumentParser(description="Flood Sensor Simulator")
    parser.add_argument("--config", default="config.yaml", help="Config file path")
    parser.add_argument("--duration", type=int, default=60, help="Duration (minutes)")
    args = parser.parse_args()
    SensorSimulator(args.config).run_stream(args.duration)


if __name__ == "__main__":
    main()
