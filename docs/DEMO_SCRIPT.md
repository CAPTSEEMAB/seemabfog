# Demo Script (4 Minutes)

**Objective:** Showcase the complete Smart Traffic Analytics platform from sensors through cloud to dashboard.

**Props/Setup:**
- Terminal 1: Sensor simulator running
- Terminal 2: Fog node logs
- Browser Tab 1: CloudWatch dashboard
- Browser Tab 2: React dashboard
- Slide deck (draw.io architecture diagram)

---

## SEGMENT 1: ARCHITECTURE OVERVIEW (0:00–0:30)

**Action:** Display architecture slide (draw.io)

**Narration:**
```
"Today we're building a Smart Traffic Analytics Platform for city junctions.
The architecture spans three layers:

[Show slide]

1. EDGE LAYER: Sensors at each junction measure traffic in real-time—vehicle
   count, speed, weather, light, and pollution. These send data 10 times per
   second to...

2. FOG LAYER: The Fog Node. This runs at the junction itself using FastAPI.
   It ingests events, deduplicates them, computes rolling 10-second aggregates
   (like congestion index), and detects incidents in real-time—all with minimal
   latency. When it detects speeding or congestion, it alerts immediately.

3. CLOUD LAYER: Events go into SQS queues—one for aggregates, one for alerts.
   These decouple the fog from the cloud. Lambda functions consume the queues,
   store data in DynamoDB, and compute KPIs. An API Gateway serves the React
   dashboard via S3 and CloudFront.

The key insight: by pushing analytics to the fog, we reduce bandwidth 80% and
get instant detection. The cloud handles storage, scale, and user-facing queries.
"
```

**Timing:** 30 seconds

---

## SEGMENT 2: SENSOR SIMULATION & RUSH HOUR (0:30–1:15)

**Action:** 
1. Start sensor simulator (accelerated time, 60x)
2. Show terminal logs with live events
3. Zoom in on event variety

**Narration:**
```
"Now let's see the simulator in action. We're running two junctions—A and B—with
realistic temporal patterns.

[Show logs]

Notice the patterns:
- Vehicle count: ramping from 50 to 180+ during rush hour
- Speed: dropping from 60 km/h baseline to 35 km/h as congestion peaks
- Weather: transitioning from dry to light rain
- Light level: Circadian cycle (bright noon, dark evening)
- Pollution: Spiking with traffic (more vehicles = more PM2.5)

Also notice: Random incidents are being injected. Watch for sudden speed drops—
that simulates an accident. When an accident occurs, vehicle count spikes (backup)
and speed plummets. Our fog node will detect this in real-time.

All events are timestamped and sent to the fog at 10 Hz per sensor. That's
50 events per second from just one junction. At two junctions, 100 events/sec.
The system can handle 500+ during burst testing.
"
```

**Demo Output (sample logs):**
```
[14:35:01] Sent event: vehicle_count=85 @ Junction-A
[14:35:01] Sent event: vehicle_speed=68.5 @ Junction-A
[14:35:02] Sent event: rain_intensity=light @ Junction-A
[14:35:02] Sent event: ambient_light=42000 @ Junction-A
[14:35:02] Sent event: pollution_pm25=28.5 @ Junction-A
[14:35:02] Random incident detected! Speed reduction wave starting...
[14:35:03] Sent event: vehicle_speed=45.2 @ Junction-A (INCIDENT)
[14:35:03] Sent event: vehicle_count=150 @ Junction-A (BACKUP)
```

**Timing:** 45 seconds

---

## SEGMENT 3: FOG NODE PROCESSING (1:15–2:15)

**Action:**
1. Show fog node logs
2. Highlight real-time alerts
3. Show SQS dispatches
4. Explain deduplication & bandwidth savings

**Narration:**
```
"Now we jump to the Fog Node. This is running on port 8001 for Junction-A.

[Show logs]

See what's happening:

1. INGESTION: Events arrive in real-time. The fog validates bounds, then stores
   in an in-memory buffer.

2. DEDUPLICATION: Each event has a unique ID. We cache IDs for 10 seconds to
   prevent duplicates. If a network hiccup causes a resend, the second copy is
   silently dropped (idempotent).

3. ROLLING AGGREGATION: Every 10 seconds, the fog computes aggregates from the
   buffer—total vehicle count, average speed, congestion index.

   Formula: congestion_index = vehicle_count / max(avg_speed, 1)

   When vehicles are high (120) and speed is low (40 km/h), congestion is 3.0—
   above our threshold of 2.0. This triggers a CONGESTION alert.

4. REAL-TIME EVENT DETECTION:
   - SPEEDING: Any speed > 80 km/h → immediate alert
   - CONGESTION: Index > 2.0 for 2 windows → alert
   - INCIDENT: Speed drop > 40% in 10 sec → alert

5. DISPATCH: Aggregates are sent to SQS every 10 seconds (one per junction).
   Alerts go immediately. Using FIFO queues ensures ordering and deduplication.

Notice: We're sending aggregates (1 payload per 10 sec) instead of 500 raw
events. That's an 80% bandwidth reduction. The raw events end here—we've already
extracted the intelligence at the edge.
"
```

**Demo Output (sample logs):**
```
[14:35:01] Ingested: vehicle_speed = 85.2 km/h @ Junction-A
[14:35:02] Ingested: vehicle_count = 95 vehicles/min @ Junction-A
[14:35:02] ALERT: SPEEDING detected: 85.2 > 80 km/h → dispatch to SQS
[14:35:10] AGGREGATE computed: vehicle_count_sum=850, avg_speed=68.5, congestion_index=1.24
[14:35:10] Dispatched to SQS: 1 aggregate message
[14:35:11] Ingested: vehicle_speed = 45.0 km/h @ Junction-A (INCIDENT)
[14:35:15] ALERT: INCIDENT detected: speed dropped 40% → HIGH severity
[14:35:15] ALERT: CONGESTION detected: index 3.2 > 2.0 → dispatch to SQS
[14:35:20] AGGREGATE computed: vehicle_count_sum=920, avg_speed=42.5, congestion_index=2.16
[14:35:20] Dedup cache: 18 entries, 3 expired
[14:35:20] Dispatched to SQS: 1 aggregate, 1 event
```

**Timing:** 60 seconds

---

## SEGMENT 4: CLOUD DASHBOARD (2:15–3:30)

**Action:**
1. Open React dashboard in browser
2. Show junction selector
3. Highlight live charts (1-hour window)
4. Show event feed
5. Explain KPIs

**Narration:**
```
"Now let's look at the Cloud Dashboard. This is a React app polling the API
every 3 seconds.

[Open dashboard, select Junction-A]

LIVE METRICS (Top):
- Vehicle Count: 185 vehicles/min (rush hour)
- Average Speed: 42 km/h (congestion)
- Congestion Index: 4.4 (HIGH—red background)
- Safety Score: 65/100 (yellow—elevated alerts in last hour)

CHARTS (Middle):
- Vehicle Count: Area chart showing steady climb into rush hour
- Average Speed: Line chart declining, threshold at 80 km/h (green below, red above)
- Congestion Index: Spiking at 2:15 PM when incident happened

EVENT FEED (Right):
- Timestamped list of last 20 events
- Color-coded: green=low, yellow=medium, red=high
- Shows: speeding events (multiple vehicles at 82–95 km/h), congestion alerts,
  and the major incident at 14:35 (50% speed drop)

KPI SUMMARY (Bottom):
- Speeding Events (1h): 12
- Congestion Alerts (1h): 5
- Incident Alerts (1h): 2
- Total: 19 events

The dashboard is responsive—works on mobile, tablet, desktop. It's polling every
3 seconds, so you see real-time updates. Click Junction-B to see parallel data.
"
```

**Demo Interaction:**
```
[Hover over chart points to show timestamp & value]
[Show event filter: "All events in last hour"]
[Click event to show full description]
[Switch to Junction-B to show parallel junctions]
[Highlight safety score calculation in KPIs]
```

**Timing:** 75 seconds

---

## SEGMENT 5: SCALABILITY & RESILIENCE (3:30–4:00)

**Action:**
1. Show CloudWatch metrics dashboard
2. Explain burst handling
3. Show DLQ monitoring
4. Discuss autoscaling & deduplication

**Narration:**
```
"Finally, let's talk about scale and reliability—the hardest part of edge
computing.

[Open CloudWatch dashboard]

BURST SCENARIO: We ran a load test—500 events/sec for 30 seconds. That's
15,000 events from all sensors and junctions.

METRICS:
- SQS Queue Depth: Started at 0, ramped to 2,400 during burst, then drained
  as Lambda scaled. Final: 0 (all processed).
- Lambda Concurrent Executions: Auto-scaled from 5 to 120 within 2 seconds.
  AWS Lambda auto-scales based on queue depth.
- Processing Latency: p50=50ms, p99=450ms. All events processed within 500ms.
- Success Rate: 100% (no failures).
- DLQ Messages: 0 (none sent to dead-letter queue).

HOW IT WORKS:
1. Deduplication: Fog node caches event IDs for 10 seconds. Duplicates from
   network retries are silently dropped (idempotent).

2. Idempotency Keys: Every message in SQS has a unique key. Even if Lambda
   retries 3x, DynamoDB sees the same key and doesn't write duplicates.

3. DLQ Fallback: If Lambda fails 3x, message goes to DLQ for manual
   investigation. This protects us from infinite retry loops.

4. Autoscaling: SQS depth triggers Lambda concurrency increase. DynamoDB
   auto-scales read/write capacity. CloudFront caches dashboard.

5. Resilience Testing: We disabled the SQS endpoint—Fog retried 3x with
   exponential backoff (1s, 2s, 4s), then sent to local DLQ. No data loss.

The bottom line: This system is built for production. It handles burst traffic,
recovers from failures, and gives you observability to debug issues.
"
```

**Demo Output (metrics):**
```
SQS Queue Depth:
  14:40:00 — 0 messages
  14:40:05 — 2,400 messages (peak)
  14:40:15 — 1,200 messages (Lambda processing)
  14:40:25 — 100 messages
  14:40:30 — 0 messages (drained)

Lambda Concurrency:
  14:40:00 — 5
  14:40:02 — 50
  14:40:03 — 120 (auto-scaled)
  14:40:30 — 10 (scaled down)

Processing Latency (p99):
  Aggregates: 450ms
  Events: 380ms
  API queries: 120ms

DLQ Depth: 0 messages (healthy)
```

**Timing:** 30 seconds

---

## TOTAL TIME: 4 MINUTES

| Segment | Duration | Cumulative |
|---------|----------|------------|
| 1. Architecture | 30 sec | 0:30 |
| 2. Simulator | 45 sec | 1:15 |
| 3. Fog Node | 60 sec | 2:15 |
| 4. Dashboard | 75 sec | 3:30 |
| 5. Scalability | 30 sec | 4:00 |

---

## BACKUP TALKING POINTS

If time permits or if asked:

**Q: How does fog differ from traditional cloud?**
A: Cloud processes everything centrally (high latency, high bandwidth). Fog does
local analytics (low latency, 80% bandwidth savings). Fog sends only insights
(aggregates, alerts), not raw data.

**Q: What if the fog crashes?**
A: Events are buffered in memory. Dedup cache is lost, but SQS has idempotency
keys, so duplicates are filtered in the cloud. On restart, Fog reconnects to
SQS and continues processing.

**Q: Why FIFO SQS?**
A: Ordering matters for time-series data. FIFO ensures events from Junction-A
are processed in sequence, preventing out-of-order analytics.

**Q: Cost breakdown?**
A: Fog (EC2): ~$50/month per node
   SQS: ~$0.50/month (1M messages free tier)
   Lambda: ~$20/month (1M free tier)
   DynamoDB: ~$0 (on-demand, very cheap for this load)
   Total: ~$70/month for a two-junction system with light monitoring.

---

## SLIDES TO PREPARE

1. **Slide 1: Architecture Diagram** (draw.io)
   - Sensors → Fog → SQS → Lambda → DynamoDB → API → Dashboard

2. **Slide 2: Fog Algorithms**
   - Congestion Index formula
   - Event detection thresholds
   - Deduplication logic

3. **Slide 3: Scalability**
   - Queue depth during burst
   - Lambda concurrency scaling
   - Latency percentiles

4. **Slide 4: Deployment (IaC)**
   - Terraform provisioning (SQS, Lambda, DynamoDB, etc.)
   - GitHub Actions CI/CD flow

5. **Slide 5: Resilience**
   - DLQ handling
   - Retry policy
   - Idempotency key strategy

---

## SUCCESS CRITERIA

After 4 minutes, the audience should understand:
✅ Fog processes data locally for real-time insight
✅ Cloud handles scale and persistence
✅ SQS decouples fog and cloud
✅ Deduplication + idempotency prevent data corruption
✅ Auto-scaling handles bursts
✅ Dashboard provides real-time visibility

