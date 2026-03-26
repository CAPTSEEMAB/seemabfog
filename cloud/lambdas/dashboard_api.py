"""
Lambda: Dashboard API
Query aggregates and events for front-end.
"""

import json
import boto3
import os
from datetime import datetime, timedelta
from decimal import Decimal

dynamodb = boto3.resource('dynamodb')
agg_table = dynamodb.Table(os.environ['AGGREGATES_TABLE_NAME'])
events_table = dynamodb.Table(os.environ['EVENTS_TABLE_NAME'])
kpis_table = dynamodb.Table(os.environ['KPIS_TABLE_NAME'])


def decimal_default(obj):
    """JSON encoder for Decimal."""
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError


def get_recent_aggregates(junction_id: str, hours: int = 1):
    """Get aggregates for last N hours."""
    time_threshold = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
    
    response = agg_table.query(
        KeyConditionExpression='PK = :pk AND SK > :sk',
        ExpressionAttributeValues={
            ':pk': f"{junction_id}#aggregates",
            ':sk': time_threshold
        },
        ScanIndexForward=True,  # Ascending order
        Limit=360  # ~10 minutes at 10-sec intervals * 6
    )
    
    return response.get('Items', [])


def get_recent_events(junction_id: str, limit: int = 50):
    """Get recent events."""
    response = events_table.query(
        KeyConditionExpression='PK = :pk',
        ExpressionAttributeValues={':pk': junction_id},
        ScanIndexForward=False,  # Descending
        Limit=limit
    )
    
    return response.get('Items', [])


def get_current_kpis(junction_id: str):
    """Get latest KPIs."""
    response = kpis_table.query(
        KeyConditionExpression='PK = :pk',
        ExpressionAttributeValues={':pk': f"{junction_id}#kpis"},
        ScanIndexForward=False,
        Limit=1
    )
    
    items = response.get('Items', [])
    return items[0] if items else {}


def get_summary(junction_id: str, minutes: int = 10, since: str = None):
    """Single-call aggregation for dashboard efficiency.
    Returns: latest KPI + latest aggregate + last N aggregates + recent events.
    """
    time_threshold = since or (
        datetime.utcnow() - timedelta(minutes=minutes)
    ).isoformat()

    # 1. Latest KPI
    kpis = get_current_kpis(junction_id)

    # 2. Aggregates since threshold
    aggregates = get_recent_aggregates_since(junction_id, time_threshold)

    # 3. Recent events (last 20)
    events = get_recent_events(junction_id, limit=20)

    return {
        'junctionId': junction_id,
        'kpis': kpis,
        'latest_aggregate': aggregates[-1] if aggregates else {},
        'aggregates': aggregates,
        'aggregates_count': len(aggregates),
        'events': events,
        'events_count': len(events),
        'since': time_threshold
    }


def get_recent_aggregates_since(junction_id: str, time_threshold: str):
    """Get aggregates since a given ISO timestamp."""
    response = agg_table.query(
        KeyConditionExpression='PK = :pk AND SK > :sk',
        ExpressionAttributeValues={
            ':pk': f"{junction_id}#aggregates",
            ':sk': time_threshold
        },
        ScanIndexForward=True,
        Limit=360
    )
    return response.get('Items', [])


def lambda_handler(event, context):
    """API Gateway handler."""
    
    try:
        path = event.get('path', '')
        query_params = event.get('queryStringParameters', {}) or {}
        
        # Route: GET /api/aggregates?junctionId=Junction-A&hours=1
        if path == '/api/aggregates':
            junction_id = query_params.get('junctionId')
            hours = int(query_params.get('hours', 1))
            
            if not junction_id:
                return error_response(400, 'junctionId required')
            
            aggregates = get_recent_aggregates(junction_id, hours)
            
            return success_response({
                'junctionId': junction_id,
                'aggregates': aggregates,
                'count': len(aggregates)
            })
        
        # Route: GET /api/events?junctionId=Junction-A&limit=50
        elif path == '/api/events':
            junction_id = query_params.get('junctionId')
            limit = int(query_params.get('limit', 50))
            
            if not junction_id:
                return error_response(400, 'junctionId required')
            
            events = get_recent_events(junction_id, limit)
            
            return success_response({
                'junctionId': junction_id,
                'events': events,
                'count': len(events)
            })
        
        # Route: GET /api/kpis?junctionId=Junction-A
        elif path == '/api/kpis':
            junction_id = query_params.get('junctionId')
            
            if not junction_id:
                return error_response(400, 'junctionId required')
            
            kpis = get_current_kpis(junction_id)
            
            return success_response({
                'junctionId': junction_id,
                'kpis': kpis
            })
        
        # Route: GET /api/summary?junctionId=Junction-A&minutes=10&since=...
        elif path == '/api/summary':
            junction_id = query_params.get('junctionId')
            minutes = int(query_params.get('minutes', 10))
            since = query_params.get('since')  # Optional ISO timestamp
            
            if not junction_id:
                return error_response(400, 'junctionId required')
            
            summary = get_summary(junction_id, minutes, since)
            return success_response(summary)
        
        # Route: GET /api/health
        elif path == '/api/health':
            return success_response({'status': 'ok'})
        
        else:
            return error_response(404, 'Not found')
    
    except Exception as e:
        print(f"Error: {e}")
        return error_response(500, str(e))


def success_response(data):
    """Build success response."""
    return {
        'statusCode': 200,
        'headers': {'Content-Type': 'application/json'},
        'body': json.dumps(data, default=decimal_default)
    }


def error_response(code, message):
    """Build error response."""
    return {
        'statusCode': code,
        'headers': {'Content-Type': 'application/json'},
        'body': json.dumps({'error': message})
    }
