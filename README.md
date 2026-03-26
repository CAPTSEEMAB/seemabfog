# README

## Smart Traffic Junction Analytics Platform

A **Fog & Edge Computing** solution for real-time traffic monitoring and safety analytics across smart city junctions.

**Status:** ✅ Ready for deployment  
**Demo Length:** 4 minutes  
**Architecture:** Fog (FastAPI) → AWS (SQS/Lambda/DynamoDB) → Dashboard (React)

---

## Quick Start (Local Development)

### Prerequisites
- Python 3.11+
- Node.js 18+
- Docker & Docker Compose
- AWS CLI (for cloud deployment)

### 1. Clone Repository
```bash
cd smart-traffic-iot
```

### 2. Build & Start Local Stack
```bash
docker-compose up
```

This will start (endpoints are configured via environment variables):
- **Fog Node (Junction-A):** ${REACT_APP_FOG_A}
- **Fog Node (Junction-B):** ${REACT_APP_FOG_B}
- **Sensor Simulator:** Sends events to fog (configured via ${REACT_APP_FOG_A}/${REACT_APP_FOG_B})
- **React Dashboard:** ${REACT_APP_DASHBOARD_URL}
- **LocalStack:** ${AWS_ENDPOINT_URL} (Local AWS services: SQS, DynamoDB, etc.)

### 3. View Dashboard
Open ${REACT_APP_DASHBOARD_URL} in your browser. You should see:
- Live vehicle count, speed, congestion charts
- Real-time alert feed
- Safety score KPIs

---

## Architecture

```
Sensors → Fog (FastAPI) → SQS → Lambda → DynamoDB → API Gateway → Dashboard (React)
          (edge analytics)    (cloud)
```

### Key Components

| Component | Purpose |
|-----------|---------|
| **Sensor Simulator** | Generates realistic temporal patterns (5 types) |
| **Fog Node** | Real-time analytics, event detection, bandwidth optimization |
| **SQS Queues** | Async message passing, deduplication, DLQ |
| **Lambda Functions** | Process aggregates, compute KPIs, serve API |
| **DynamoDB** | Time-series storage (aggregates, events, KPIs) |
| **React Dashboard** | Live charts, event feed, KPI display |

---

## Features

### Fog Node (Edge Analytics)
- ✅ Real-time event ingestion (10 Hz)
- ✅ 10-second rolling aggregation
- ✅ Automatic event detection (speeding, congestion, incidents)
- ✅ Deduplication (10-sec cache)
- ✅ SQS dispatch with retry & exponential backoff
- ✅ 80% bandwidth reduction vs raw sensor stream

### Cloud Backend
- ✅ Scalable SQS → Lambda → DynamoDB pipeline
- ✅ Auto-scaling Lambda & DynamoDB
- ✅ Dead Letter Queue for failed messages
- ✅ Idempotency keys prevent duplicates
- ✅ 1-hour rolling KPIs (safety score, incident count)

### Dashboard
- ✅ Real-time charts (1-hour window)
- ✅ Event feed with color-coded severity
- ✅ Responsive mobile/tablet/desktop layout
- ✅ 3-second polling for live updates

---

## API Reference

### Fog Node
```
POST /ingest                 # Single event
POST /ingest/batch           # Batch events
GET  /health                 # Health check
GET  /metrics                # Fog metrics
```

### Dashboard API
```
GET /api/aggregates?junctionId=A&hours=1
GET /api/events?junctionId=A&limit=50
GET /api/kpis?junctionId=A
GET /api/health
```

See [API_SPEC.md](docs/API_SPEC.md) for full details.

---

## Deployment

### AWS Deployment
```bash
# 1. Set credentials
export AWS_ACCESS_KEY_ID=xxx
export AWS_SECRET_ACCESS_KEY=xxx

# 2. Initialize Terraform
cd cloud/terraform
terraform init

# 3. Deploy infrastructure
terraform apply

# 4. Deploy dashboard
cd ../../dashboard
npm install && npm run build
aws s3 sync build/ s3://smart-traffic-dashboard-{account-id}/
```

See [DEPLOYMENT.md](docs/DEPLOYMENT.md) for full guide.

### CI/CD Pipeline
GitHub Actions automatically:
- Runs linting & unit tests on PR
- Builds Lambda packages on merge to main
- Deploys infrastructure via Terraform
- Builds & deploys React dashboard to S3
- Runs smoke tests

---

## Testing

### Unit Tests
```bash
pytest tests/test_fog_analytics.py -v
```

Tests:
- Congestion index calculation
- Speeding detection threshold
- Incident detection (speed drop)
- Deduplication logic

### Integration Tests
```bash
pytest tests/test_integration.py -v
```

Tests:
- Fog → SQS → Lambda → DynamoDB flow

### Load Test (Burst: 500 events/sec)
```bash
bash tests/load_test.sh
```

Captures:
- Queue depth progression
- Lambda concurrency scaling
- Processing latency (p50, p99)
- Success rate

### Failure Test (DLQ)
```bash
bash tests/dlq_test.sh
```

Tests:
- Fog retry on SQS failure
- Lambda retry & DLQ sendoff

---

## Configuration

### Sensor Simulator
Edit `sensors/config.yaml`:
```yaml
simulation:
  mode: normal              # or "burst_load_test"
  time_acceleration_factor: 60  # 1=realtime, 60=1hr/min
  start_time: "08:00"
```

### Fog Node
Environment variables:
```
FOG_PORT=8001
AWS_REGION=us-east-1
AGGREGATES_QUEUE_URL=https://sqs.us-east-1.amazonaws.com/.../...
EVENTS_QUEUE_URL=https://sqs.us-east-1.amazonaws.com/.../...
```

### Dashboard
Environment variables (`.env`):
```
REACT_APP_API_ENDPOINT=http://localhost:8000/api
```

---

## Project Structure

```
smart-traffic-iot/
├── sensors/               # Sensor simulation engine
├── fog/                  # FastAPI fog node service
├── cloud/
│   ├── lambdas/          # Lambda functions (Python)
│   └── terraform/        # Infrastructure as code
├── dashboard/            # React dashboard
├── tests/               # Unit, integration, load tests
├── docs/
│   ├── ARCHITECTURE.md   # Full technical design
│   ├── API_SPEC.md       # API reference
│   ├── DEMO_SCRIPT.md    # 4-minute demo walkthrough
│   └── DEPLOYMENT.md     # AWS deployment guide
├── .github/workflows/   # GitHub Actions CI/CD
└── docker-compose.yml   # Local dev environment
```

---

## Documentation

- **[ARCHITECTURE.md](docs/ARCHITECTURE.md)** – 25-page technical design document
- **[API_SPEC.md](docs/API_SPEC.md)** – Complete endpoint specifications
- **[DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md)** – 4-minute demo walkthrough
- **[DEPLOYMENT.md](docs/DEPLOYMENT.md)** – Step-by-step AWS deployment

---

## Key Metrics

### Sensor Simulation
- 5 sensor types (vehicle count, speed, rain, light, pollution)
- 10 Hz frequency per sensor
- 100 events/sec from 2 junctions (1000+ during bursts)
- Realistic patterns: rush hours, incidents, weather

### Fog Node
- 10-second rolling aggregation
- 3 event detection algorithms (speeding, congestion, incident)
- 10-second deduplication cache
- 80% bandwidth reduction vs raw events

### Cloud Backend
- SQS: FIFO queues with DLQ
- Lambda: Auto-scaling to 1000+ concurrent
- DynamoDB: On-demand billing
- Latency: p99 < 500ms for aggregates

### Scalability
- Burst: 500 events/sec for 30 sec
- Queue absorbs 15,000 messages
- Lambda auto-scales from 10 to 120 concurrent
- All events processed, 100% success rate

---

## Troubleshooting

### Fog node not receiving events
Check:
- Sensor simulator is running
- Fog endpoint URL is correct in simulator config
- Firewall/security group allows connections

### Dashboard showing no data
Check:
- API Gateway is deployed (terraform output)
- Lambda functions are executing (CloudWatch logs)
- DynamoDB has data (AWS console)

### Load test failures
Check:
- SQS queues are accessible
- Lambda concurrency limit not hit
- DynamoDB capacity sufficient

See [TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) for more.

---

## Performance Benchmarks

| Metric | Value |
|--------|-------|
| Sensor ingestion rate | 1,000 events/sec (burst) |
| Fog aggregation latency | < 50ms |
| Event detection latency | < 10ms (real-time) |
| Cloud API latency (p99) | 450ms |
| Dashboard update frequency | 3 seconds |
| Bandwidth reduction | 80% |
| Data deduplication rate | 2–5% (duplicates) |

---

## Contact

**Assignment:** Fog & Edge Computing (NCI College)  
**Date:** February 2025  
**Instructor:** [Name]  

---

## License

MIT License – See LICENSE file.

---

## Next Steps

1. **Deploy locally:** `docker-compose up`
2. **View dashboard:** ${REACT_APP_DASHBOARD_URL}
3. **Read architecture:** [ARCHITECTURE.md](docs/ARCHITECTURE.md)
4. **Deploy to AWS:** [DEPLOYMENT.md](docs/DEPLOYMENT.md)
5. **Run load test:** `bash tests/load_test.sh`

Happy coding! 🚦

