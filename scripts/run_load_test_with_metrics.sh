#!/usr/bin/env bash
# ============================================================
# Smart Traffic – Load Test with Metrics Collection
# ============================================================
# Usage:  ./scripts/run_load_test_with_metrics.sh [DURATION_SEC] [FOG_URL]
#
# Generates high-throughput sensor traffic while collecting
# fog-node metrics for bandwidth-reduction evidence.
# ============================================================
set -euo pipefail

DURATION=${1:-120}
# Load local env if present so scripts use the same config as the compose setup.
if [ -f "$(dirname "$0")/../.env" ]; then
    set -a
    . "$(dirname "$0")/../.env"
    set +a
fi

# Allow positional overrides, otherwise use REACT_APP_FOG_A/REACT_APP_FOG_B from .env
FOG_A=${2:-${REACT_APP_FOG_A}}
FOG_B=${3:-${REACT_APP_FOG_B}}

if [ -z "$FOG_A" ] || [ -z "$FOG_B" ]; then
    echo "FOG_A or FOG_B not set. Define REACT_APP_FOG_A and REACT_APP_FOG_B in .env or pass as args." >&2
    exit 1
fi
RESULTS_DIR="artifacts/load_test_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$RESULTS_DIR"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Smart Traffic Load Test"
echo "  Duration : ${DURATION}s"
echo "  Fog A    : ${FOG_A}"
echo "  Fog B    : ${FOG_B}"
echo "  Results  : ${RESULTS_DIR}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ── 1. Pre-test: capture starting metrics ──────────────────
echo "[$(date +%T)] Capturing pre-test metrics..."
curl -sf "${FOG_A}/status" | python3 -m json.tool > "${RESULTS_DIR}/fog_a_pre.json" 2>/dev/null || echo "{}" > "${RESULTS_DIR}/fog_a_pre.json"
curl -sf "${FOG_B}/status" | python3 -m json.tool > "${RESULTS_DIR}/fog_b_pre.json" 2>/dev/null || echo "{}" > "${RESULTS_DIR}/fog_b_pre.json"

# ── 2. Start metrics polling in background ─────────────────
echo "[$(date +%T)] Starting metrics poller (5s interval)..."
(
  while true; do
    TS=$(date +%s)
    A=$(curl -sf "${FOG_A}/status" 2>/dev/null || echo '{}')
    B=$(curl -sf "${FOG_B}/status" 2>/dev/null || echo '{}')
    echo "${TS},A,${A}" >> "${RESULTS_DIR}/metrics_timeline.csv"
    echo "${TS},B,${B}" >> "${RESULTS_DIR}/metrics_timeline.csv"
    sleep 5
  done
) &
POLLER_PID=$!
trap "kill $POLLER_PID 2>/dev/null; exit" INT TERM EXIT

# ── 3. Run sensor simulator ────────────────────────────────
echo "[$(date +%T)] Starting sensor simulator for ${DURATION}s..."
if [ -f "sensors/simulator.py" ]; then
    python3 sensors/simulator.py \
        --duration "$DURATION" \
        --fog-endpoints "${FOG_A}/ingest,${FOG_B}/ingest" \
        2>&1 | tee "${RESULTS_DIR}/simulator.log" || true
else
    # Inline high-throughput generator
    echo "[$(date +%T)] Using inline event generator..."
    END=$(($(date +%s) + DURATION))
    COUNT=0
    while [ "$(date +%s)" -lt "$END" ]; do
        for JUNCTION in "Junction-A" "Junction-B"; do
            for SENSOR in "vehicle_speed" "vehicle_count" "pollution_pm25"; do
                VALUE=$(( RANDOM % 100 ))
                PAYLOAD="{\"junction_id\":\"${JUNCTION}\",\"sensor_type\":\"${SENSOR}\",\"value\":${VALUE},\"timestamp\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}"
                # Alternate between fog nodes
                TARGET=$( [ $(( COUNT % 2 )) -eq 0 ] && echo "$FOG_A" || echo "$FOG_B" )
                curl -sf -X POST "${TARGET}/ingest" \
                    -H "Content-Type: application/json" \
                    -d "$PAYLOAD" > /dev/null 2>&1 &
                COUNT=$((COUNT + 1))
            done
        done
        # ~18 events/sec (6 per loop, small sleep)
        sleep 0.3
    done
    wait
    echo "[$(date +%T)] Generated ${COUNT} events"
fi

# ── 4. Post-test: capture ending metrics ───────────────────
echo "[$(date +%T)] Capturing post-test metrics..."
sleep 3  # Wait for final aggregation cycle
curl -sf "${FOG_A}/status" | python3 -m json.tool > "${RESULTS_DIR}/fog_a_post.json" 2>/dev/null || echo "{}" > "${RESULTS_DIR}/fog_a_post.json"
curl -sf "${FOG_B}/status" | python3 -m json.tool > "${RESULTS_DIR}/fog_b_post.json" 2>/dev/null || echo "{}" > "${RESULTS_DIR}/fog_b_post.json"

# ── 5. Stop poller ─────────────────────────────────────────
kill $POLLER_PID 2>/dev/null || true
trap - INT TERM EXIT

# ── 6. Generate summary ───────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Load Test Complete"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

python3 -c "
import json, sys, os

results = '${RESULTS_DIR}'
for node in ['a', 'b']:
    pre_f = os.path.join(results, f'fog_{node}_pre.json')
    post_f = os.path.join(results, f'fog_{node}_post.json')
    try:
        pre = json.load(open(pre_f))
        post = json.load(open(post_f))
        ingested = post.get('events_ingested', 0) - pre.get('events_ingested', 0)
        dispatched = post.get('messages_dispatched', 0) - pre.get('messages_dispatched', 0)
        dupes = post.get('duplicates_dropped', 0) - pre.get('duplicates_dropped', 0)
        reduction = post.get('bandwidth_reduction_pct', 0)
        print(f'  Fog {node.upper()}:')
        print(f'    Events ingested   : {ingested}')
        print(f'    Messages dispatched: {dispatched}')
        print(f'    Duplicates dropped : {dupes}')
        print(f'    Bandwidth reduction: {reduction:.1f}%')
        print()
    except Exception as e:
        print(f'  Fog {node.upper()}: no metrics available ({e})')
" 2>/dev/null || echo "  (metrics parsing skipped)"

echo "  Full results saved to: ${RESULTS_DIR}/"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
