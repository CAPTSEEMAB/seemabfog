#!/usr/bin/env python3
"""
Traffic Sensor Simulator
Generates realistic temporal patterns for 5 sensor types across 2 junctions.
"""

import json
import math
import os
import random
import time
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
import yaml
import requests
import argparse


class TrafficPattern:
    """Generates temporal traffic patterns."""
    
    @staticmethod
    def sinusoidal_baseline(hour: float, min_val: float, max_val: float) -> float:
        """24-hour sinusoidal baseline."""
        # Peak at 12:00 (noon)
        amplitude = (max_val - min_val) / 2
        offset = (max_val + min_val) / 2
        return offset + amplitude * math.sin((hour - 6) * math.pi / 12)
    
    @staticmethod
    def rush_hour_multiplier(hour: float) -> float:
        """Apply rush hour multiplier."""
        # Morning rush: 7-9 AM
        if 7 <= hour < 9:
            return 1.0 + 2.5 * math.sin((hour - 7) * math.pi / 2)
        # Evening rush: 5-7 PM
        elif 17 <= hour < 19:
            return 1.0 + 3.0 * math.sin((hour - 17) * math.pi / 2)
        else:
            return 1.0
    
    @staticmethod
    def incident_wave(current_time: float, incident_start: float, 
                      incident_duration: float, max_reduction: float) -> float:
        """Sudden incident wave pattern."""
        elapsed = current_time - incident_start
        if elapsed < 0 or elapsed > incident_duration:
            return 0.0
        
        # Triangular wave: ramps up then down
        if elapsed < incident_duration / 2:
            return (elapsed / (incident_duration / 2)) * max_reduction
        else:
            return ((incident_duration - elapsed) / (incident_duration / 2)) * max_reduction


class SensorSimulator:
    """Simulates traffic sensor readings."""
    
    def __init__(self, config_path: str):
        """Initialize simulator with config."""
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)
        
        # Use current UTC time as simulation start for real-time alignment
        self.sim_start_time = datetime.utcnow()
        self.acceleration_factor = self.config['simulation']['time_acceleration_factor']
        self.sim_real_start = time.time()
        
        # Track incidents
        self.active_incidents = {}
    
    def get_simulated_time(self) -> datetime:
        """Get current simulated time."""
        elapsed_real = time.time() - self.sim_real_start
        elapsed_sim = elapsed_real * self.acceleration_factor
        return self.sim_start_time + timedelta(seconds=elapsed_sim)
    
    def generate_vehicle_count(self, junction_id: str, config: Dict) -> int:
        """Generate vehicle count with rush hour patterns."""
        now = self.get_simulated_time()
        hour = now.hour + now.minute / 60.0
        
        # Baseline sinusoidal
        baseline = TrafficPattern.sinusoidal_baseline(
            hour,
            config['baseline_min'],
            config['baseline_max']
        )
        
        # Apply rush hour
        rush_multiplier = TrafficPattern.rush_hour_multiplier(hour)
        count = baseline * rush_multiplier
        
        # Add random incident
        if random.random() < 0.01:  # 1% per call
            incident_key = f"{junction_id}_speedwave_{uuid.uuid4()}"
            self.active_incidents[incident_key] = {
                'start': now,
                'duration': 5 * 60,  # 5 minutes
                'type': 'speedwave'
            }
        
        # Apply incident effect
        for incident in list(self.active_incidents.values()):
            elapsed_sec = (now - incident['start']).total_seconds()
            if 0 <= elapsed_sec < incident['duration']:
                incident_wave = TrafficPattern.incident_wave(
                    elapsed_sec, 0, incident['duration'], 150  # +150% vehicles
                )
                count += incident_wave
            elif elapsed_sec >= incident['duration']:
                # Remove old incidents
                pass
        
        # Add noise
        count += random.gauss(0, 5)
        return max(0, int(count))
    
    def generate_vehicle_speed(self, junction_id: str, config: Dict) -> float:
        """Generate vehicle speed with incident drops."""
        now = self.get_simulated_time()
        hour = now.hour + now.minute / 60.0
        
        # Baseline with circadian pattern
        rush_multiplier = TrafficPattern.rush_hour_multiplier(hour)
        baseline = config['baseline_mean'] - (rush_multiplier - 1.0) * 10
        
        speed = random.gauss(baseline, config['baseline_std'])
        
        # Apply incident drops
        for incident in self.active_incidents.values():
            elapsed_sec = (now - incident['start']).total_seconds()
            if 0 <= elapsed_sec < incident['duration']:
                incident_reduction = TrafficPattern.incident_wave(
                    elapsed_sec, 0, incident['duration'], 40  # 40% reduction
                )
                speed -= incident_reduction
        
        speed = max(config['min_bound'], min(speed, config['max_bound']))
        return round(speed, 2)
    
    def generate_rain_intensity(self, config: Dict) -> str:
        """Generate categorical rain intensity."""
        categories = config['categories']
        distribution = config['baseline_distribution']
        return random.choices(categories, weights=distribution)[0]
    
    def generate_ambient_light(self, config: Dict) -> float:
        """Generate ambient light with day/night cycle."""
        now = self.get_simulated_time()
        hour = now.hour + now.minute / 60.0
        
        # Sinusoidal day/night cycle (daylight 6 AM - 6 PM)
        if 6 <= hour < 18:
            day_cycle = math.sin((hour - 6) * math.pi / 12)
            light = config['baseline_day'] * day_cycle
        else:
            light = config['baseline_night']
        
        light += random.gauss(0, light * 0.1)  # 10% noise
        return round(max(0, light), 1)
    
    def generate_pollution(self, config: Dict) -> float:
        """Generate PM2.5 correlated with traffic."""
        now = self.get_simulated_time()
        hour = now.hour + now.minute / 60.0
        
        # Correlate with rush hours
        rush_mult = TrafficPattern.rush_hour_multiplier(hour)
        baseline = config['baseline_mean'] * (0.5 + rush_mult)
        
        pollution = random.gauss(baseline, config['baseline_std'])
        pollution = max(config['min_bound'], min(pollution, config['max_bound']))
        return round(pollution, 2)
    
    def generate_event(self, junction: Dict) -> Dict[str, Any]:
        """Generate one complete event for a junction."""
        junction_id = junction['id']
        
        # Pick random sensor
        sensor_config = random.choice(junction['sensors'])
        sensor_name = sensor_config['name']
        
        # Generate sensor value
        if sensor_name == 'vehicle_count':
            value = self.generate_vehicle_count(junction_id, sensor_config)
        elif sensor_name == 'vehicle_speed':
            value = self.generate_vehicle_speed(junction_id, sensor_config)
        elif sensor_name == 'rain_intensity':
            value = self.generate_rain_intensity(sensor_config)
        elif sensor_name == 'ambient_light':
            value = self.generate_ambient_light(sensor_config)
        elif sensor_name == 'pollution_pm25':
            value = self.generate_pollution(sensor_config)
        else:
            value = None
        
        now = self.get_simulated_time()
        
        return {
            'eventId': str(uuid.uuid4()),
            'junctionId': junction_id,
            'sensorType': sensor_name,
            'value': value,
            'unit': sensor_config['unit'],
            'timestamp': now.isoformat() + 'Z',
            'latitude': junction['latitude'],
            'longitude': junction['longitude']
        }
    
    def run_stream(self, duration_minutes: int = 60):
        """Run continuous sensor stream."""
        print(f"Starting simulation for {duration_minutes} minutes...")
        start_real = time.time()
        
        try:
            while True:
                elapsed_real = time.time() - start_real
                if elapsed_real > duration_minutes * 60:
                    print("Simulation duration completed.")
                    break
                
                # Generate event from random junction
                junction = random.choice(self.config['junctions'])
                event = self.generate_event(junction)
                
                # Send to fog
                self._send_event(event, junction)
                
                # Sleep based on sensor frequency
                time.sleep(0.1)
        
        except KeyboardInterrupt:
            print("\nSimulation stopped.")
    
    def _send_event(self, event: Dict, junction: Dict):
        """Send event to fog node via config-driven endpoint mapping."""
        junction_id = junction['id']
        # Build endpoint map from config: first junction → endpoint_a, second → endpoint_b, etc.
        if not hasattr(self, '_endpoint_map'):
            junction_ids = [j['id'] for j in self.config['junctions']]
            endpoints = [
                os.getenv('FOG_ENDPOINT_A', self.config['output'].get('fog_endpoint_a', '')),
                os.getenv('FOG_ENDPOINT_B', self.config['output'].get('fog_endpoint_b', '')),
            ]
            self._endpoint_map = dict(zip(junction_ids, endpoints))
        endpoint = self._endpoint_map.get(junction_id)
        if not endpoint:
            print(f"No endpoint configured for {junction_id}")
            return
        
        try:
            resp = requests.post(endpoint, json=event, timeout=2)
            if resp.status_code != 202:
                print(f"Fog returned {resp.status_code}: {resp.text}")
        except requests.exceptions.RequestException as e:
            print(f"Failed to send to {endpoint}: {e}")


def main():
    parser = argparse.ArgumentParser(description='Traffic Sensor Simulator')
    parser.add_argument('--config', default='config.yaml', help='Config file path')
    parser.add_argument('--duration', type=int, default=60, help='Duration in minutes')
    args = parser.parse_args()
    
    simulator = SensorSimulator(args.config)
    simulator.run_stream(args.duration)


if __name__ == '__main__':
    main()
