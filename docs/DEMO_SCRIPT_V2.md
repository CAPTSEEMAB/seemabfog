# Demo Script V2 – Smart Traffic Junction Analytics

> **Purpose:** Step-by-step live demo for NCI Fog & Edge Computing assignment.  
> **Duration:** ~8 minutes  
> **Prerequisites:** Docker Desktop running, terminal open in project root.

---

## Act 1: Platform Boot (1 min)

```bash
# Start all services
docker-compose up -d

# Verify services are healthy
docker-compose ps
curl ${REACT_APP_FOG_A}/health
curl ${REACT_APP_FOG_B}/health
```

**Talking point:** "Two fog nodes simulating edge computing at traffic junctions."

---

## Act 2: Live Data Ingestion (2 min)

```bash
# Open dashboard in browser
open ${REACT_APP_DASHBOARD_URL}

# Start sensor simulator (120 seconds)
python3 sensors/simulator.py --duration 120
```

**Show in dashboard:**
- Vehicle count chart updating in real-time
- Congestion index rising during simulated rush hour
- Safety score responding to events

**Talking point:** "Sensors → Fog → Cloud pipeline processes 20+ events/sec per junction."

---

## Act 3: Fog Node Intelligence (2 min)

### 3a. Check fog status endpoint
```bash
curl ${REACT_APP_FOG_A}/status | python3 -m json.tool
```

**Highlight:**
- `bandwidth_reduction_pct` — raw events vs dispatched aggregates
- `incoming_rate_eps` — events per second
- `spool_size` — should be 0 (healthy)

### 3b. Demonstrate deduplication
```bash
# Send the same event twice
EVENT='{"junction_id":"Junction-A","sensor_type":"speed","value":45.5,"timestamp":"2024-01-01T00:00:00Z"}'
curl -X POST ${REACT_APP_FOG_A}/ingest -H "Content-Type: application/json" -d "$EVENT"
curl -X POST ${REACT_APP_FOG_A}/ingest -H "Content-Type: application/json" -d "$EVENT"

# Check status — duplicates_dropped should increment
curl ${REACT_APP_FOG_A}/status | python3 -m json.tool | grep duplicates
```

**Talking point:** "Fog layer deduplicates at the edge, reducing cloud costs."

---

## Act 4: Store-and-Forward Resilience (2 min)

### 4a. Simulate SQS outage
```bash
# Stop LocalStack (SQS goes offline)
docker-compose stop localstack

# Send more events — they'll spool to disk
for i in $(seq 1 10); do
  curl -s -X POST ${REACT_APP_FOG_A}/ingest \
    -H "Content-Type: application/json" \
    -d "{\"junction_id\":\"Junction-A\",\"sensor_type\":\"speed\",\"value\":$((RANDOM%80)),\"timestamp\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}"
done

# Check spool has grown
curl ${REACT_APP_FOG_A}/status | python3 -m json.tool | grep spool
```

### 4b. Restore and watch auto-flush
```bash
# Bring SQS back
docker-compose start localstack

# Wait for aggregation cycle (10s) to trigger spool flush
sleep 12

# Verify spool is drained
curl ${REACT_APP_FOG_A}/status | python3 -m json.tool | grep spool
```

**Talking point:** "Zero data loss. Exponential backoff protects the cloud, disk spool protects the data."

---

## Act 5: Load Test Evidence (1 min)

```bash
# Run load test with metrics collection
chmod +x scripts/run_load_test_with_metrics.sh
./scripts/run_load_test_with_metrics.sh 60

# Review bandwidth reduction metrics
cat artifacts/load_test_*/fog_a_post.json | python3 -m json.tool
```

**Talking point:** "Under sustained load, fog nodes achieve ~85% bandwidth reduction via aggregation."

---

## Cleanup

```bash
docker-compose down -v
```

---

## Evidence Screenshots Checklist

| # | Screenshot | Location |
|---|-----------|----------|
| 1 | Dashboard with live data | `artifacts/screenshots/` |
| 2 | `/status` endpoint output | `artifacts/screenshots/` |
| 3 | Spool during outage | `artifacts/screenshots/` |
| 4 | Spool after recovery (0) | `artifacts/screenshots/` |
| 5 | Load test bandwidth stats | `artifacts/screenshots/` |
| 6 | All tests passing | `artifacts/screenshots/` |

---

## Key Metrics to Mention

| Metric | Expected Value | Why It Matters |
|--------|---------------|----------------|
| Bandwidth Reduction | 80-90% | Fog aggregation reduces cloud data transfer |
| Event Throughput | 20+ eps/node | Handles rush-hour traffic volumes |
| Spool Recovery | < 15 seconds | Near-instant data recovery after outage |
| Deduplication | ~5-10% savings | Eliminates redundant sensor readings |
| Lambda Idempotency | 0 duplicate writes | Conditional DynamoDB writes prevent data corruption |
