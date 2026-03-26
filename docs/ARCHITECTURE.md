# Smart Traffic Junction Analytics Platform
## Fog & Edge Computing - NCI College Assignment

**Date:** February 2025  
**Domain:** Smart City - Traffic Junction Monitoring & Safety Analytics  
**Platform:** AWS (default) with optional Azure mappings  

---

## EXECUTIVE SUMMARY

This project implements a **Smart Traffic Junction Analytics Platform** using a Fog & Edge Computing architecture. The system monitors 2 simulated junctions (Junction-A, Junction-B) with 5 sensor types, processes data at the edge (fog node), and dispatches aggregated metrics to AWS for real-time dashboarding and KPI computation.

### Key Features
- **Real-time Sensor Simulation:** 5 sensor types with realistic temporal patterns
- **Edge Analytics:** Fog node with rolling window aggregation, event detection
- **Scalable Cloud Backend:** SQS → Lambda → DynamoDB pipeline
- **Interactive Dashboard:** React-based live charts and event feed
- **Resilience & Deduplication:** DLQ, retry logic, idempotency keys
- **Full IaC:** Terraform provisioning for AWS infrastructure
- **CI/CD Pipeline:** GitHub Actions for automated testing and deployment

---

## ARCHITECTURE OVERVIEW

```
┌─────────────────────────────────────────────────────────────────────┐
│                    TRAFFIC JUNCTION SENSORS                         │
│  (5 types: vehicle_count, speed, rain, light, pollution)           │
└────────────────┬────────────────────────────────────────────────────┘
                 │ Real-time events (10 Hz per sensor)
                 ▼
┌────────────────────────────────────────────────────────────────────┐
│                       FOG NODE (FastAPI)                            │
│  - Event ingestion & validation                                     │
│  - 10-sec rolling aggregation (congestion index, avg speed)         │
│  - Real-time event detection (speeding, incidents)                  │
│  - Deduplication (10-sec TTL cache)                                 │
│  - SQS dispatch with retry & backoff                                │
└────────────────┬─────────────────────────────────────────────────────┘
                 │
         ┌───────┴────────┐
         ▼                ▼
    ┌─────────┐      ┌──────────┐
    │ SQS     │      │ SQS      │
    │Aggreg.  │      │Events    │
    │ Queue   │      │ Queue    │
    └────┬────┘      └────┬─────┘
         │                │
         ▼                ▼
    ┌─────────┐      ┌──────────┐      ┌─────────┐
    │Lambda   │      │Lambda    │      │DLQ      │
    │Process- │      │Process-  │─────▶│Queue    │
    │Aggreg.  │      │Events    │      │         │
    └────┬────┘      └────┬─────┘      └─────────┘
         │                │
         └─────┬──────────┘
               ▼
        ┌──────────────┐
        │  DynamoDB    │
        │  (3 tables)  │
        └──────┬───────┘
               │
               ▼
        ┌──────────────┐
        │ API Gateway  │
        │   Lambda     │
        └──────┬───────┘
               │
               ▼
        ┌──────────────┐
        │React         │
        │Dashboard     │
        └──────────────┘
```

---

## REPO STRUCTURE

```
smart-traffic-iot/
│
├── sensors/
│   ├── config.yaml              # Sensor configuration (frequency, scenarios)
│   ├── simulator.py             # Sensor simulation engine
│   ├── requirements.txt
│   └── .gitignore
│
├── fog/
│   ├── fog_node.py              # FastAPI fog node service
│   ├── requirements.txt
│   ├── start.sh                 # Startup script
│   └── Dockerfile               # Container image
│
├── cloud/
│   ├── lambdas/
│   │   ├── process_aggregates.py
│   │   ├── process_events.py
│   │   ├── dashboard_api.py
│   │   └── requirements.txt
│   │
│   └── terraform/
│       ├── main.tf              # Infrastructure as code
│       ├── variables.tf         # Variable definitions
│       ├── outputs.tf           # Output definitions
│       └── .terraform/
│
├── dashboard/
│   ├── src/
│   │   ├── Dashboard.jsx        # React main component
│   │   ├── Dashboard.css
│   │   └── index.jsx
│   ├── public/
│   ├── package.json
│   └── .env.example
│
├── tests/
│   ├── test_fog_analytics.py    # Unit tests (congestion, events)
│   ├── test_integration.py      # Integration tests
│   ├── test_lambda.py           # Lambda function tests
│   ├── load_test.sh             # Burst load test (500 evt/sec)
│   └── dlq_test.sh              # DLQ failure scenario test
│
├── docs/
│   ├── ARCHITECTURE.md          # This file
│   ├── API_SPEC.md              # Endpoint specifications
│   ├── DEPLOYMENT.md            # AWS deployment guide
│   ├── DEMO_SCRIPT.md           # 4-minute demo walkthrough
│   └── MARKING_RUBRIC.md        # Alignment to assessment criteria
│
├── .github/workflows/
│   └── deploy.yml               # GitHub Actions CI/CD
│
├── docker-compose.yml           # Local dev environment
├── .gitignore
├── README.md
└── LICENSE
```

---

## SENSOR TYPES & SIMULATION

### 1. Vehicle Count
- **Unit:** vehicles/minute
- **Range:** 0–500
- **Pattern:** Sinusoidal baseline + rush hour multipliers (3.5x–4x at 7–9 AM, 5–7 PM)
- **Incidents:** Random speed-drop waves that increase vehicle backlog

### 2. Vehicle Speed
- **Unit:** km/h  
- **Range:** 0–160
- **Pattern:** Gaussian (mean ~45–50 km/h, std ~12–15 km/h) with rush hour degradation
- **Incidents:** Sudden drops (40–50% reduction) indicating congestion/accidents

### 3. Rain Intensity
- **Unit:** mm/h (categorical)
- **Categories:** `none`, `light`, `heavy`
- **Distribution:** 70% none, 20% light, 10% heavy
- **Pattern:** Random weather events

### 4. Ambient Light Level
- **Unit:** lux
- **Range:** ~100 (night) to 50,000 (day)
- **Pattern:** Circadian cycle (day 6 AM–6 PM, night 6 PM–6 AM)

### 5. Air Pollution (PM2.5)
- **Unit:** µg/m³
- **Range:** 5–200
- **Pattern:** Baseline + traffic correlation (higher during rush hours)
- **Multiplier:** +50% PM2.5 during congestion events

### Temporal Patterns
- **Morning Rush:** 7–9 AM, vehicle count 3–4x baseline, speed -30%
- **Evening Rush:** 5–7 PM, vehicle count 3–4x baseline, speed -25%
- **Incidents:** Random 5-minute events with speed drops and vehicle backups
- **Acceleration Factor:** Configurable (1.0 = real-time, 60 = 1 hour per minute)

---

## FOG NODE SERVICE (FastAPI)

**Port:** 8001 (Junction-A), 8002 (Junction-B)  
**Language:** Python 3.11

### Core Responsibilities

#### 1. Event Ingestion & Validation
```
POST /ingest
Body: { eventId, junctionId, sensorType, value, unit, timestamp, latitude, longitude }
Returns: 202 (async processing)

Validation:
  - vehicle_speed: 0–160 km/h
  - vehicle_count: 0–500
  - pollution_pm25: 0–500 µg/m³
  - ambient_light: 0–100,000 lux
  - Timestamp sanity: ±5 minutes from server time
```

#### 2. Deduplication
- **Mechanism:** In-memory cache (TTL 10 sec)
- **Key:** eventId
- **Handling:** Duplicate events return `{"status": "duplicate"}` (no error, idempotent)

#### 3. Rolling Window Analytics (10-second windows)
Every 10 seconds:
- **Vehicle Count Sum:** Total vehicles in window
- **Avg Speed:** Mean speed across all speed readings
- **Congestion Index:** `vehicle_count_sum / max(avg_speed, 1.0)`
- **Rain/Light/Pollution Averages:** Running means

#### 4. Event Detection (Real-time)
**Speeding Event:**
- Trigger: `vehicle_speed > 80 km/h`
- Response: Immediately emit alert to SQS events queue
- Severity: MEDIUM

**Congestion Alert:**
- Trigger: `congestion_index > 2.0` for 2 consecutive windows
- Response: Emit alert to SQS
- Severity: HIGH

**Incident Alert:**
- Trigger: Sudden speed drop > 40% within 10 seconds
- Response: Emit alert immediately
- Severity: HIGH

#### 5. Bandwidth Optimization
- **Aggregates:** Dispatch every 10 sec (1 per junction)
- **Events:** Dispatch immediately (speeding/congestion/incident)
- **Compression:** JSON with minimal field redundancy
- **Payload Reduction:** ~80% vs raw sensor stream

#### 6. Reliable Dispatch to AWS SQS
```python
# Retry logic
- Max retries: 3
- Backoff: Exponential (1s, 2s, 4s)
- On failure: Send to DLQ
- Idempotency key: {junctionId}#{timestamp}
```

### API Endpoints

#### POST /ingest
```json
Request:
{
  "eventId": "uuid",
  "junctionId": "Junction-A",
  "sensorType": "vehicle_speed",
  "value": 75.5,
  "unit": "km/h",
  "timestamp": "2025-02-18T14:30:45Z",
  "latitude": 53.3426,
  "longitude": -6.2543
}

Response (202):
{ "status": "accepted", "eventId": "uuid" }
```

#### POST /ingest/batch
```json
Request:
[
  { event1 },
  { event2 },
  ...
]

Response (202):
{ "status": "accepted", "count": 10 }
```

#### GET /health
```json
Response (200):
{ "status": "ok", "timestamp": "2025-02-18T14:30:45Z" }
```

#### GET /metrics
```json
Response (200):
{
  "Junction-A": {
    "buffered_events": 42,
    "dedup_cache_size": 15
  },
  "Junction-B": {
    "buffered_events": 38,
    "dedup_cache_size": 12
  }
}
```

---

## AWS CLOUD BACKEND

### SQS Queues

#### Traffic Aggregates Queue
- **Name:** `smart-traffic-aggregates-queue.fifo`
- **Type:** FIFO (ordering guaranteed)
- **Message Deduplication:** Content-based
- **Retention:** 4 days
- **Visibility Timeout:** 60 sec
- **DLQ:** `smart-traffic-aggregates-dlq.fifo` (max 3 receive attempts)

#### Traffic Events Queue
- **Name:** `smart-traffic-events-queue.fifo`
- **Type:** FIFO
- **Message Deduplication:** Content-based
- **Retention:** 4 days
- **Visibility Timeout:** 60 sec
- **DLQ:** `smart-traffic-events-dlq.fifo`

### Lambda Functions

#### process_aggregates_lambda
- **Trigger:** SQS aggregates queue (batch 10)
- **Runtime:** Python 3.11, 30 sec timeout
- **Environment:** `AGGREGATES_TABLE_NAME`
- **Logic:**
  - Parse JSON from SQS
  - Store in DynamoDB aggregates table
  - Idempotency: Use messageId + dedup key
- **Error:** Failures → DLQ after 3 retries

#### process_events_lambda
- **Trigger:** SQS events queue (batch 10)
- **Runtime:** Python 3.11, 30 sec timeout
- **Environment:** `EVENTS_TABLE_NAME`, `KPIS_TABLE_NAME`
- **Logic:**
  - Parse alert from SQS
  - Store in DynamoDB events table
  - Compute KPIs (1-hour rolling):
    - speeding_events_1h
    - congestion_events_1h
    - incident_events_1h
    - safety_score = 100 - (speeding*5 + incidents*10)
  - Store KPIs in KPIs table
- **Error:** Failures → DLQ

#### dashboard_api_lambda
- **Trigger:** API Gateway (HTTP GET)
- **Runtime:** Python 3.11, 30 sec timeout
- **Environment:** Table names
- **Routes:**
  - `GET /api/aggregates?junctionId=X&hours=1` → Return time-series aggregates
  - `GET /api/events?junctionId=X&limit=50` → Return recent events
  - `GET /api/kpis?junctionId=X` → Return latest KPIs
  - `GET /api/health` → Return `{"status": "ok"}`
- **Error:** 400/404/500 with descriptive messages

### DynamoDB Tables

#### AggregatesTable
- **PK:** `junction#{metric}` (e.g., `Junction-A#aggregates`)
- **SK:** ISO timestamp (e.g., `2025-02-18T14:30:45Z`)
- **Attributes:**
  - `junctionId` (string)
  - `timestamp` (string)
  - `vehicle_count_sum` (number)
  - `avg_speed` (number)
  - `congestion_index` (number)
  - `rain_intensity` (string, optional)
  - `avg_ambient_light` (number, optional)
  - `avg_pollution` (number, optional)
  - `metrics_count` (number)
  - `idempotency_key` (string)
  - `processed_at` (string)
- **TTL:** 30 days

#### EventsTable
- **PK:** `junctionId` (e.g., `Junction-A`)
- **SK:** `timestamp#alertType#alertId` (e.g., `2025-02-18T14:30:45Z#SPEEDING#uuid`)
- **Attributes:**
  - `alertId` (string)
  - `alertType` (string: SPEEDING, CONGESTION, INCIDENT)
  - `severity` (string: LOW, MEDIUM, HIGH)
  - `description` (string)
  - `triggered_value` (number)
  - `threshold` (number)
  - `processed_at` (string)
- **TTL:** 7 days

#### KPIsTable
- **PK:** `junction#kpis`
- **SK:** ISO timestamp (latest)
- **Attributes:**
  - `speeding_events_1h` (number)
  - `congestion_events_1h` (number)
  - `incident_events_1h` (number)
  - `total_events_1h` (number)
  - `safety_score` (number 0–100)
- **TTL:** 30 days

### API Gateway
- **REST API:** `smart-traffic-dashboard-api`
- **Base:** `/api`
- **CORS:** Enabled for dashboard
- **Deployment:** `dev` stage
- **Endpoint:** `https://{api-id}.execute-api.us-east-1.amazonaws.com/dev`

### S3 + CloudFront
- **S3 Bucket:** `smart-traffic-dashboard-{account-id}`
- **CloudFront:** CDN distribution for dashboard UI
- **Caching:** 1 hour
- **Invalidation:** On dashboard deployment

### CloudWatch
- **Metrics Collected:**
  - SQS queue depth (aggregates, events)
  - Lambda invocation count & duration
  - Lambda error rate
  - DynamoDB write/read capacity consumed
  - DLQ message count
- **Alarms:** Queue depth > 1000, Lambda error rate > 5%
- **Logs:** All Lambda functions (10-day retention)

---

## DASHBOARD (React)

### Features

**Top Controls:**
- Junction selector (A/B)
- Refresh status indicator

**Metrics Cards (4):**
1. Vehicle Count (vehicles/min)
2. Average Speed (km/h)
3. Congestion Index (ratio)
4. Safety Score (0–100, color-coded)

**Live Charts (1-hour rolling):**
1. **Vehicle Count:** Area chart (vehicle_count_sum over time)
2. **Average Speed:** Line chart (avg_speed over time, threshold line at 80 km/h)
3. **Congestion Index:** Line chart (congestion_index, threshold at 2.0)

**Event Feed:**
- Last 20 events displayed
- Color-coded by severity (green/yellow/red)
- Timestamp, event type, description
- Auto-scroll

**KPI Summary:**
- Speeding events (1h)
- Congestion alerts (1h)
- Incident alerts (1h)

**Responsive Design:**
- Mobile: Single column
- Tablet: 2 columns
- Desktop: 3+ columns

**Real-time Updates:**
- Poll API every 3 seconds
- Auto-refresh charts & event feed

---

## AWS SERVICE MAPPING & OPTIONAL AZURE EQUIVALENTS

| AWS Service | Purpose | Azure Equivalent |
|---|---|---|
| **SQS (FIFO)** | Event queuing, dedupling | Service Bus (Topic + Subscription) |
| **Lambda** | Serverless compute | Azure Functions |
| **DynamoDB** | NoSQL time-series storage | Cosmos DB (SQL/JSON) |
| **API Gateway** | HTTP endpoint, routing | API Management |
| **S3 + CloudFront** | Static hosting + CDN | Blob Storage + Azure CDN |
| **CloudWatch** | Monitoring, logs, alarms | Azure Monitor + Application Insights |
| **IAM** | Identity & access control | Azure RBAC + Managed Identity |

### Azure Mapping (Optional)
```
Fog Node → Service Bus Queue → Azure Function → Cosmos DB → API Management → Static Web App
```

---

## CI/CD PIPELINE (GitHub Actions)

### Workflow: `.github/workflows/deploy.yml`

**Triggers:** `push` to `main` or `develop`, pull requests

**Jobs:**

1. **lint-test**
   - Lint Python code (flake8)
   - Run unit tests (pytest)
   - Run integration tests
   - **Status:** Blocks merge if failed

2. **build-lambdas**
   - Package each Lambda function + dependencies
   - Create .zip artifacts
   - **Artifact:** `lambda-packages`

3. **deploy-infrastructure** (main only)
   - Download Lambda packages
   - Run Terraform init/plan/apply
   - Provision SQS, DynamoDB, Lambda, API Gateway, S3, CloudFront

4. **build-dashboard**
   - Install npm dependencies
   - Build React app (`npm run build`)
   - **Artifact:** `dashboard-build`

5. **deploy-dashboard** (main only)
   - Sync build to S3
   - Invalidate CloudFront cache

6. **smoke-test** (main only)
   - Query API endpoints
   - Verify 200 responses
   - **Status:** Blocks prod if failed

---

## TESTING STRATEGY

### Unit Tests (`tests/test_fog_analytics.py`)
- **Congestion Index Calculation:** 100 vehicles, 50 km/h → 2.0
- **Zero Speed Handling:** Epsilon (1.0) prevents division by zero
- **Speeding Detection:** > 80 km/h → alert
- **Congestion Detection:** Index > 2.0 → alert
- **Incident Detection:** 40% speed drop → alert
- **Metrics Count:** Correct aggregation of mixed sensor types

### Integration Tests (`tests/test_integration.py`)
- **Deduplication:** Duplicate eventId rejected
- **Rolling Window:** Events accumulate in buffer (5 events → buffer size 5)
- **Multi-Junction:** Junction-A and Junction-B have independent buffers

### Load Tests (`tests/load_test.sh`)
- **Scenario:** 500 events/sec for 30 seconds (15,000 total)
- **Metrics Captured:**
  - Total events sent
  - Success/failure rate
  - Actual throughput (events/sec)
  - Queue depth progression
  - Lambda processing time percentiles
- **Acceptance:** > 95% success rate, < 2 sec p95 latency

### Failure Tests
- **DLQ Verification:** Disable SQS endpoint, verify Fog retries 3x then sends to DLQ
- **Fog Resilience:** Kill Fog service, restart, verify no data loss (using dedup cache)
- **Lambda Timeout:** Set duration to 5 sec, verify timeout handling

---

## SCALABILITY & RELIABILITY

### Horizontal Scalability
- **Multiple Fog Nodes:** One per junction (or partitioned)
- **SQS Buffering:** Absorbs bursts (500 evt/sec for 30 sec = 15,000 events queued)
- **Lambda Concurrency:** Auto-scales with queue depth (default 1000 concurrent)
- **DynamoDB:** Pay-per-request billing (auto-scales)

### Resilience
1. **Deduplication:** Idempotency keys prevent duplicate processing
2. **Retry Logic:**
   - Fog: Exponential backoff (1s, 2s, 4s)
   - Lambda: 3 attempts, then DLQ
3. **Dead Letter Queue:** Failed messages quarantined for investigation
4. **Monitoring:** CloudWatch alarms on queue depth, error rate

### Observability
- **Metrics:** Queue depth, Lambda duration, error rate
- **Logs:** All Lambda invocations (CloudWatch Logs)
- **Dashboards:** CloudWatch dashboard for ops

---

## DEPLOYMENT INSTRUCTIONS

### Prerequisites
- AWS account with credentials
- Docker & Docker Compose (local testing)
- Terraform >= 1.0
- Node.js >= 18
- Python >= 3.11

### Local Development (Docker Compose)
```bash
docker-compose up
# Fog runs on ports 8001, 8002
# Sensor simulator connects to fog
# Dashboard: ${REACT_APP_DASHBOARD_URL}
```

### AWS Deployment
```bash
# 1. Set AWS credentials
export AWS_ACCESS_KEY_ID=xxx
export AWS_SECRET_ACCESS_KEY=xxx

# 2. Initialize Terraform
cd cloud/terraform
terraform init

# 3. Deploy infrastructure
terraform apply

# 4. Build & deploy lambdas
cd ../lambdas
# (GitHub Actions handles this in CI/CD)

# 5. Deploy dashboard
cd ../../dashboard
npm run build
aws s3 sync build/ s3://smart-traffic-dashboard-{account-id}/
```

---

## DEMO SCRIPT (4 minutes)

**Objective:** Showcase architecture, live data flow, burst handling, reliability

### Segment 1: Architecture (0:00–0:30)
- **Slide:** Draw.io architecture diagram
- **Narration:** "Smart Traffic Analytics uses Fog + Cloud:
  - Sensors stream 5 types of data in real-time
  - Fog node at each junction does rolling analytics & event detection
  - SQS queues buffer traffic; Lambda processes at scale
  - DynamoDB stores time-series; API Gateway serves React dashboard"

### Segment 2: Sensor Simulation (0:30–1:15)
- **Live:** Run sensor simulator with time acceleration (60x)
- **Show:** Terminal logs of incoming events
  - Vehicle count: 50–200 vehicles/min (rush hour peaks)
  - Speed: 45–80 km/h (drops during incidents)
  - Weather: Rain transitions from none → light → heavy
- **Narration:** "Simulator generates realistic patterns: rush hours, random incidents, weather changes. All 5 sensor types active."

### Segment 3: Fog Node Processing (1:15–2:15)
- **Live:** Show Fog node logs
  - "Ingested: vehicle_speed = 95 km/h → SPEEDING alert emitted"
  - "10-sec aggregate: junction-A, vehicle_count=150, avg_speed=35, congestion_index=4.2 → CONGESTION"
  - "Dedup cache: 12 entries TTL 10s"
  - "Dispatch: 1 aggregate to SQS every 10s; immediate events on detection"
- **Narration:** "Fog node reduces bandwidth 80% by aggregating. Real-time detection triggers speeding & incident alerts instantly. Deduplication prevents duplicate processing."

### Segment 4: Cloud Dashboard (2:15–3:30)
- **Live:** Open dashboard (http://dashboard-url)
  - **Metrics:** Vehicle count 180, speed 42 km/h, congestion 4.3, safety 65/100
  - **Charts:** Vehicle count trending up (rush hour), speed trending down (congestion), congestion index spiking
  - **Event feed:** Last 15 events showing speeding, congestion, incident alerts
  - **KPIs:** Speeding events 12 (1h), Congestion 5, Incident 2
- **Narration:** "Dashboard polls every 3 seconds. Charts show live 1-hour rolling window. Color coding: green speed OK, yellow cautionary, red critical. KPI safety score: 65/100 (lower due to incident)"

### Segment 5: Scalability & Reliability (3:30–4:00)
- **Show:** CloudWatch dashboard
  - SQS queue depth progression (burst handling)
  - Lambda concurrent execution (auto-scaling)
  - DLQ monitoring (0 messages = healthy)
  - Aggregate latency p99 < 500ms
- **Narration:** "Burst test: 500 events/sec for 30 sec. SQS absorbed 15,000 events. Lambda auto-scaled from 10 to 100 concurrent. No errors. DLQ empty = 100% success. Deduplication + idempotency keys ensure exactly-once processing."

**Timing:**
- Slides: 30s
- Simulator logs: 45s
- Fog logs: 60s
- Dashboard: 75s
- CloudWatch: 30s
- **Total: 240s (4 minutes)**

---

## MARKING RUBRIC ALIGNMENT

### 1. Architecture & Design (25%)
✅ **Fog & Edge Computing Pattern:**
- Fog node at junction with local analytics
- Cloud backend for centralized storage & dashboarding
- Event-driven using SQS

✅ **Scalability:**
- Stateless Lambda functions
- Auto-scaling SQS + DynamoDB
- CloudFront CDN for dashboard

✅ **Resilience:**
- DLQ for failed messages
- Deduplication with idempotency keys
- Retry logic with exponential backoff

### 2. Implementation (30%)
✅ **Sensor Simulation:**
- 5 sensor types with configurable frequency
- Realistic temporal patterns (rush hours, incidents)
- YAML configuration for scenarios

✅ **Fog Node:**
- FastAPI service with /ingest endpoints
- 10-sec rolling aggregation
- Real-time event detection (speeding, congestion, incidents)
- SQS dispatch with retry

✅ **Cloud Backend:**
- 3 Lambda functions (aggregates, events, API)
- 3 DynamoDB tables with proper schema
- API Gateway with CORS
- S3 + CloudFront

✅ **Dashboard:**
- React component with live charts
- Real-time polling (3-sec interval)
- KPI display + event feed
- Responsive layout

### 3. Testing & Validation (20%)
✅ **Unit Tests:**
- Congestion index calculation
- Event detection thresholds
- Deduplication logic

✅ **Integration Tests:**
- Fog → SQS → Lambda → DynamoDB

✅ **Load Testing:**
- 500 events/sec burst
- Metrics capture (queue depth, latency)
- Success rate validation

✅ **Failure Testing:**
- DLQ verification
- Fog resilience (retry)

### 4. Deployment & CI/CD (15%)
✅ **GitHub Actions:**
- Lint + unit tests
- Lambda packaging
- Terraform infrastructure deployment
- Dashboard build & S3 deployment
- Smoke tests

✅ **Infrastructure as Code:**
- Terraform main.tf with SQS, Lambda, DynamoDB, API Gateway, S3, CloudFront
- IAM roles with least-privilege
- Outputs for dashboard URL

✅ **Documentation:**
- This architecture document
- API specifications
- Deployment guide
- Demo script

### 5. Code Quality (10%)
✅ **Python:**
- Type hints (Pydantic models)
- Error handling (try-except)
- Logging (structured)
- Follows PEP 8

✅ **React:**
- Functional components
- Hooks (useState, useEffect)
- Responsive CSS
- Error boundaries

✅ **Terraform:**
- Modular design
- Variable parameterization
- Comments
- Outputs for cross-stack reference

---

## KEY ALGORITHMS

### 1. Congestion Index
```
congestion_index = vehicle_count_sum / max(avg_speed, 1.0)
```
- High vehicle count + low speed = high congestion
- Threshold: > 2.0 triggers CONGESTION alert

### 2. Safety Score
```
safety_score = 100 - min(100, speeding_events*5 + incident_events*10)
```
- Range: 0–100
- Updated hourly from event KPIs

### 3. Incident Detection (Speed Drop Wave)
```
recent_avg = mean(speeds[-5:])
previous_avg = mean(speeds[-10:-5])
drop_pct = (previous_avg - recent_avg) / previous_avg * 100

if drop_pct > 40:
    emit INCIDENT alert
```

### 4. Deduplication
```
if eventId in cache:
    return DUPLICATE
else:
    cache[eventId] = now
    process_event()
    cleanup_cache(ttl=10s)
```

---

## CONCLUSION

This Smart Traffic Junction Analytics Platform demonstrates a complete Fog & Edge Computing solution:
- **Fog:** Real-time processing, reduced bandwidth
- **Cloud:** Scalable, cost-efficient, reliable
- **Resilience:** Deduplication, retries, DLQ
- **Observability:** CloudWatch metrics, logs, dashboards
- **Demo:** Shows live sensors → fog analytics → cloud storage → dashboard

**Total Components:** ~2,500 lines of code across simulator, fog, lambdas, dashboard, tests, and infrastructure.

---

## CONTACT & SUPPORT

**Instructor:** [NCI College]  
**Student:** [Your Name]  
**Date:** February 2025  
**Repository:** [GitHub Repo Link]
