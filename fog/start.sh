#!/bin/bash
export AWS_REGION=${AWS_REGION:-us-east-1}
export AGGREGATES_QUEUE_URL=${AGGREGATES_QUEUE_URL:-}
export EVENTS_QUEUE_URL=${EVENTS_QUEUE_URL:-}
export FOG_PORT=${FOG_PORT:-8000}

python fog_node.py
