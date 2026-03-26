#!/bin/bash
# Load test script
# Sends 500 events/sec for 30s to simulate burst traffic

echo "Starting burst load test..."
echo "Target: 500 events/sec for 30 seconds"

if [ -f "../.env" ]; then
    set -a
    . "../.env"
    set +a
fi

FOG_URL="${REACT_APP_FOG_A%/}/ingest/batch"

if [ -z "$REACT_APP_FOG_A" ]; then
    echo "REACT_APP_FOG_A not set in .env; please define it." >&2
    exit 1
fi
DURATION=30
RATE=500
BATCH_SIZE=50

python3 - << 'EOF'
import time
import requests
import json
import random
from datetime import datetime

import os
FOG_URL = os.environ.get('REACT_APP_FOG_A').rstrip('/') + '/ingest/batch'
DURATION = 30
RATE = 500
BATCH_SIZE = 50

junctions = ["Junction-A", "Junction-B"]
sensor_types = ["vehicle_count", "vehicle_speed", "rain_intensity", "ambient_light", "pollution_pm25"]

def generate_event(junction):
    import uuid
    sensor_type = random.choice(sensor_types)
    
    if sensor_type == "vehicle_count":
        value = random.randint(10, 100)
    elif sensor_type == "vehicle_speed":
        value = random.gauss(50, 15)
    elif sensor_type == "rain_intensity":
        value = random.choice(["none", "light", "heavy"])
    elif sensor_type == "ambient_light":
        value = random.randint(100, 50000)
    else:
        value = random.gauss(25, 10)
    
    return {
        "eventId": str(uuid.uuid4()),
        "junctionId": junction,
        "sensorType": sensor_type,
        "value": value,
        "unit": "varies",
        "timestamp": datetime.utcnow().isoformat() + 'Z'
    }

def send_batch(events):
    try:
        resp = requests.post(FOG_URL, json=events, timeout=5)
        return resp.status_code == 202
    except Exception as e:
        print(f"Error: {e}")
        return False

# Metrics
start_time = time.time()
sent_count = 0
batch_count = 0
success_count = 0

print(f"Load test starting: {RATE} events/sec for {DURATION} sec")
print(f"Total events: {RATE * DURATION}")
print()

while time.time() - start_time < DURATION:
    batch = [generate_event(random.choice(junctions)) for _ in range(BATCH_SIZE)]
    
    if send_batch(batch):
        success_count += BATCH_SIZE
    
    sent_count += BATCH_SIZE
    batch_count += 1
    
    # Rate control
    elapsed = time.time() - start_time
    expected_count = (elapsed / DURATION) * RATE * DURATION
    if sent_count > expected_count:
        sleep_time = (sent_count - expected_count) / RATE
        time.sleep(sleep_time)

elapsed_time = time.time() - start_time
print(f"\n=== LOAD TEST RESULTS ===")
print(f"Duration: {elapsed_time:.1f} sec")
print(f"Total events sent: {sent_count}")
print(f"Successful: {success_count}")
print(f"Failed: {sent_count - success_count}")
print(f"Actual rate: {sent_count / elapsed_time:.0f} events/sec")
print(f"Success rate: {100 * success_count / sent_count:.1f}%")

EOF
