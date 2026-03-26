# API Specification

## FOG NODE ENDPOINTS

### Base URL (Local Development)
-- Junction-A: `${REACT_APP_FOG_A}`
-- Junction-B: `${REACT_APP_FOG_B}`

### Base URL (AWS)
- Deployed via VPC or ECS, accessed via internal endpoint

---

## 1. POST /ingest

**Description:** Receive a single sensor event

**Request:**
```json
POST /ingest
Content-Type: application/json

{
  "eventId": "550e8400-e29b-41d4-a716-446655440000",
  "junctionId": "Junction-A",
  "sensorType": "vehicle_speed",
  "value": 75.5,
  "unit": "km/h",
  "timestamp": "2025-02-18T14:30:45.123Z",
  "latitude": 53.3426,
  "longitude": -6.2543
}
```

**Response (202 Accepted):**
```json
{
  "status": "accepted",
  "eventId": "550e8400-e29b-41d4-a716-446655440000"
}
```

**Response (202 Duplicate):**
```json
{
  "status": "duplicate"
}
```

**Response (400 Bad Request):**
```json
{
  "detail": "Invalid vehicle_speed: value must be 0-160 km/h"
}
```

**Status Codes:**
- `202`: Event accepted for processing
- `400`: Validation error (out-of-range, missing field)
- `500`: Server error (SQS, internal exception)

**Validation Rules:**
- `vehicle_speed`: 0 ≤ value ≤ 160 km/h
- `vehicle_count`: 0 ≤ value ≤ 500
- `pollution_pm25`: 0 ≤ value ≤ 500 µg/m³
- `ambient_light`: 0 ≤ value ≤ 100,000 lux
- `rain_intensity`: "none" | "light" | "heavy"
- `timestamp`: Within ±5 minutes of server time
- `junctionId`: "Junction-A" or "Junction-B"

---

## 2. POST /ingest/batch

**Description:** Receive multiple sensor events (batch ingestion)

**Request:**
```json
POST /ingest/batch
Content-Type: application/json

[
  {
    "eventId": "550e8400-e29b-41d4-a716-446655440000",
    "junctionId": "Junction-A",
    "sensorType": "vehicle_count",
    "value": 85,
    "unit": "vehicles/min",
    "timestamp": "2025-02-18T14:30:45.123Z"
  },
  {
    "eventId": "660e8400-e29b-41d4-a716-446655440001",
    "junctionId": "Junction-A",
    "sensorType": "vehicle_speed",
    "value": 65.0,
    "unit": "km/h",
    "timestamp": "2025-02-18T14:30:45.456Z"
  }
]
```

**Response (202 Accepted):**
```json
{
  "status": "accepted",
  "count": 2
}
```

**Status Codes:**
- `202`: All/partial events accepted
- `400`: Invalid format (not array)
- `500`: Server error

**Notes:**
- Duplicate events are silently skipped (count reflects only accepted)
- Individual validation errors don't block batch (fail-fast per event)

---

## 3. GET /health

**Description:** Health check endpoint

**Request:**
```
GET /health
```

**Response (200 OK):**
```json
{
  "status": "ok",
  "timestamp": "2025-02-18T14:30:45.123Z"
}
```

---

## 4. GET /metrics

**Description:** Return current fog node metrics

**Request:**
```
GET /metrics
```

**Response (200 OK):**
```json
{
  "Junction-A": {
    "buffered_events": 42,
    "dedup_cache_size": 15,
    "last_aggregate_timestamp": "2025-02-18T14:30:40Z"
  },
  "Junction-B": {
    "buffered_events": 38,
    "dedup_cache_size": 12,
    "last_aggregate_timestamp": "2025-02-18T14:30:40Z"
  }
}
```

---

## DASHBOARD API ENDPOINTS

### Base URL
- AWS: `https://{api-id}.execute-api.us-east-1.amazonaws.com/dev`
- Local: `http://localhost:8000`

---

## 1. GET /api/aggregates

**Description:** Retrieve rolling aggregates for a junction

**Request:**
```
GET /api/aggregates?junctionId=Junction-A&hours=1
```

**Query Parameters:**
- `junctionId` (required): "Junction-A" or "Junction-B"
- `hours` (optional): 1–24, default 1

**Response (200 OK):**
```json
{
  "junctionId": "Junction-A",
  "aggregates": [
    {
      "junctionId": "Junction-A",
      "timestamp": "2025-02-18T14:30:40Z",
      "vehicle_count_sum": 120,
      "avg_speed": 48.5,
      "congestion_index": 2.47,
      "rain_intensity": "none",
      "avg_ambient_light": 45000.0,
      "avg_pollution": 28.5,
      "metrics_count": 12
    },
    {
      "junctionId": "Junction-A",
      "timestamp": "2025-02-18T14:30:50Z",
      "vehicle_count_sum": 130,
      "avg_speed": 45.2,
      "congestion_index": 2.87,
      "rain_intensity": "none",
      "avg_ambient_light": 45100.0,
      "avg_pollution": 29.2,
      "metrics_count": 13
    }
  ],
  "count": 2
}
```

**Status Codes:**
- `200`: Success
- `400`: Missing junctionId
- `404`: Junction not found

**Notes:**
- Aggregates are 10-second windows
- 1 hour = ~360 aggregates
- Sorted ascending by timestamp

---

## 2. GET /api/events

**Description:** Retrieve recent alert events for a junction

**Request:**
```
GET /api/events?junctionId=Junction-A&limit=50
```

**Query Parameters:**
- `junctionId` (required): "Junction-A" or "Junction-B"
- `limit` (optional): 1–100, default 50

**Response (200 OK):**
```json
{
  "junctionId": "Junction-A",
  "events": [
    {
      "alertId": "550e8400-e29b-41d4-a716-446655440000",
      "junctionId": "Junction-A",
      "alertType": "SPEEDING",
      "severity": "MEDIUM",
      "description": "Vehicle speed 95 km/h exceeds threshold 80 km/h",
      "triggered_value": 95.0,
      "threshold": 80.0,
      "timestamp": "2025-02-18T14:35:10Z"
    },
    {
      "alertId": "660e8400-e29b-41d4-a716-446655440001",
      "junctionId": "Junction-A",
      "alertType": "CONGESTION",
      "severity": "HIGH",
      "description": "Congestion index 3.2 exceeds threshold 2.0",
      "triggered_value": 3.2,
      "threshold": 2.0,
      "timestamp": "2025-02-18T14:34:50Z"
    }
  ],
  "count": 2
}
```

**Event Types:**
- `SPEEDING`: Speed > 80 km/h
- `CONGESTION`: Congestion index > 2.0
- `INCIDENT`: Sudden speed drop > 40%

**Severity Levels:**
- `LOW`: Informational
- `MEDIUM`: SPEEDING events
- `HIGH`: CONGESTION, INCIDENT events

---

## 3. GET /api/kpis

**Description:** Retrieve current KPIs for a junction

**Request:**
```
GET /api/kpis?junctionId=Junction-A
```

**Query Parameters:**
- `junctionId` (required): "Junction-A" or "Junction-B"

**Response (200 OK):**
```json
{
  "junctionId": "Junction-A",
  "kpis": {
    "PK": "Junction-A#kpis",
    "SK": "2025-02-18T14:35:00Z",
    "speeding_events_1h": 12,
    "congestion_events_1h": 5,
    "incident_events_1h": 2,
    "total_events_1h": 19,
    "safety_score": 65
  }
}
```

**KPI Descriptions:**
- `speeding_events_1h`: Count of SPEEDING events in last hour
- `congestion_events_1h`: Count of CONGESTION events in last hour
- `incident_events_1h`: Count of INCIDENT events in last hour
- `safety_score`: 0–100, computed as `100 - (speeding*5 + incident*10)`

---

## 4. GET /api/health

**Description:** API health check

**Request:**
```
GET /api/health
```

**Response (200 OK):**
```json
{
  "status": "ok"
}
```

---

## SQS MESSAGE FORMAT

### Aggregates Queue Message

```json
{
  "junctionId": "Junction-A",
  "timestamp": "2025-02-18T14:30:40Z",
  "vehicle_count_sum": 120,
  "avg_speed": 48.5,
  "congestion_index": 2.47,
  "rain_intensity": "none",
  "avg_ambient_light": 45000.0,
  "avg_pollution": 28.5,
  "metrics_count": 12
}
```

**SQS Attributes:**
- `MessageGroupId`: junctionId (FIFO ordering)
- `MessageDeduplicationId`: `{junctionId}#{timestamp}`

### Events Queue Message

```json
{
  "alertId": "550e8400-e29b-41d4-a716-446655440000",
  "junctionId": "Junction-A",
  "alertType": "SPEEDING",
  "severity": "MEDIUM",
  "description": "Vehicle speed 95 km/h exceeds threshold 80 km/h",
  "triggered_value": 95.0,
  "threshold": 80.0,
  "timestamp": "2025-02-18T14:35:10Z"
}
```

**SQS Attributes:**
- `MessageGroupId`: junctionId (FIFO ordering)
- `MessageDeduplicationId`: alertId

---

## ERROR RESPONSES

### 400 Bad Request
```json
{
  "detail": "Invalid vehicle_speed: value must be 0-160 km/h"
}
```

### 404 Not Found
```json
{
  "error": "Junction not found"
}
```

### 500 Internal Server Error
```json
{
  "error": "DynamoDB connection failed"
}
```

---

## RATE LIMITS & THROTTLING

- **Fog Node:** No hard limit (designed for burst handling)
- **API Gateway:** 10,000 requests/sec per account
- **Lambda:** 1,000 concurrent executions per account
- **DynamoDB:** On-demand (auto-scaling)

---

## AUTHENTICATION

- **Fog Node:** None (internal VPC)
- **Dashboard API:** Optional API key or IAM (future)
- **CORS:** Enabled for `*` (adjust for production)

---

## VERSIONING

- **Current API Version:** 1.0.0
- **Breaking Changes:** Will be versioned as /api/v2

---

## EXAMPLES

### Example 1: Send Single Speed Event
```bash
curl -X POST ${REACT_APP_FOG_A}/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "eventId": "evt-001",
    "junctionId": "Junction-A",
    "sensorType": "vehicle_speed",
    "value": 75.5,
    "unit": "km/h",
    "timestamp": "2025-02-18T14:30:45Z"
  }'
```

### Example 2: Get Last Hour Aggregates
```bash
curl "http://localhost:8000/api/aggregates?junctionId=Junction-A&hours=1"
```

### Example 3: Get Recent Speeding Events
```bash
curl "http://localhost:8000/api/events?junctionId=Junction-A&limit=10" | jq '.events[] | select(.alertType=="SPEEDING")'
```

### Example 4: Monitor Safety Score
```bash
curl "http://localhost:8000/api/kpis?junctionId=Junction-A" | jq '.kpis.safety_score'
```

---

## POLLING RECOMMENDATIONS

- **Dashboard:** 2–3 seconds (real-time feel without overloading API)
- **Monitoring:** 10–30 seconds (operational dashboards)
- **Batch Ingestion:** As fast as network allows, rate-limited by fog node buffer

