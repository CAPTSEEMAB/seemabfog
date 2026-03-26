# Required Screenshots for Evidence Pack

Capture these during or after a load test run.

## 1. `01_fog_status_during_load.png`
- **Source:** `curl localhost:8001/status | python3 -m json.tool` during peak load
- **Shows:** incoming_rate ~500 eps, outgoing_rate ~1 mps, bandwidth_reduction ~99%

## 2. `02_sqs_queue_depth.png`
- **Source:** AWS Console → SQS → aggregates queue → Monitoring tab
- **Shows:** ApproximateNumberOfMessagesVisible over test window

## 3. `03_lambda_invocations.png`
- **Source:** AWS Console → Lambda → process-aggregates → Monitoring → Invocations
- **Shows:** Invocation count ramping during test

## 4. `04_cloudwatch_dashboard.png`
- **Source:** AWS Console → CloudWatch → Dashboards → smart-traffic-ops
- **Shows:** All 6 widgets with data populated

## 5. `05_bandwidth_reduction.png`
- **Source:** Graph from metrics_timeseries.csv (matplotlib or Excel)
- **Shows:** incoming_rate vs outgoing_rate on dual-axis chart

## 6. `06_dlq_empty.png`
- **Source:** AWS Console → SQS → DLQ → Messages Available = 0
- **Shows:** No failed messages
