"""
Lambda: Process Traffic Events (Alerts)
Consumes events from SQS, stores in DynamoDB, computes KPIs.
"""

import json
import boto3
import os
from datetime import datetime, timedelta
from decimal import Decimal

dynamodb = boto3.resource('dynamodb')
events_table = dynamodb.Table(os.environ['EVENTS_TABLE_NAME'])
kpis_table = dynamodb.Table(os.environ['KPIS_TABLE_NAME'])

# Safety score weights (configurable via env vars)
SAFETY_SPEEDING_WEIGHT = int(os.environ.get('SAFETY_SPEEDING_WEIGHT', '5'))
SAFETY_INCIDENT_WEIGHT = int(os.environ.get('SAFETY_INCIDENT_WEIGHT', '10'))
SAFETY_MAX_PENALTY = int(os.environ.get('SAFETY_MAX_PENALTY', '100'))
SAFETY_MAX_SCORE = int(os.environ.get('SAFETY_MAX_SCORE', '100'))


def compute_kpis(alert_type: str, junction_id: str):
    """Compute KPIs for this event type."""
    # Query recent events (last hour)
    one_hour_ago = (datetime.utcnow() - timedelta(hours=1)).isoformat()
    
    try:
        response = events_table.query(
            KeyConditionExpression='PK = :pk AND SK > :sk',
            ExpressionAttributeValues={
                ':pk': junction_id,
                ':sk': one_hour_ago
            }
        )
        
        events = response.get('Items', [])
        
        # Count by type
        speeding_count = sum(1 for e in events if e.get('alertType') == 'SPEEDING')
        congestion_count = sum(1 for e in events if e.get('alertType') == 'CONGESTION')
        incident_count = sum(1 for e in events if e.get('alertType') == 'INCIDENT')
        
        kpi_item = {
            'PK': f"{junction_id}#kpis",
            'SK': datetime.utcnow().isoformat(),
            'speeding_events_1h': speeding_count,
            'congestion_events_1h': congestion_count,
            'incident_events_1h': incident_count,
            'total_events_1h': len(events),
            'safety_score': compute_safety_score(speeding_count, incident_count)
        }
        
        kpis_table.put_item(Item=kpi_item)
        
    except Exception as e:
        print(f"Error computing KPIs: {e}")


def compute_safety_score(speeding_count: int, incident_count: int) -> int:
    """Compute 0-100 safety score."""
    penalty = min(SAFETY_MAX_PENALTY, speeding_count * SAFETY_SPEEDING_WEIGHT + incident_count * SAFETY_INCIDENT_WEIGHT)
    return max(0, SAFETY_MAX_SCORE - penalty)


def lambda_handler(event, context):
    """Process SQS event message batch."""
    
    for record in event['Records']:
        try:
            message_body = json.loads(record['body'])
            
            junction_id = message_body['junctionId']
            alert_id = message_body['alertId']
            alert_type = message_body['alertType']
            timestamp = message_body['timestamp']
            
            # Store event
            item = {
                'PK': junction_id,
                'SK': f"{timestamp}#{alert_type}#{alert_id}",
                'alertId': alert_id,
                'junctionId': junction_id,
                'alertType': alert_type,
                'severity': message_body['severity'],
                'description': message_body['description'],
                'triggered_value': Decimal(str(message_body['triggered_value'])),
                'threshold': Decimal(str(message_body['threshold'])),
                'timestamp': timestamp,
                'processed_at': datetime.utcnow().isoformat()
            }
            
            # Conditional write: skip if PK+SK already exists (idempotent)
            try:
                events_table.put_item(
                    Item=item,
                    ConditionExpression="attribute_not_exists(PK) AND attribute_not_exists(SK)"
                )
                print(f"Stored event: {alert_type} @ {junction_id}")
            except dynamodb.meta.client.exceptions.ConditionalCheckFailedException:
                print(f"Duplicate event skipped: {alert_id}")
            
            # Compute KPIs
            compute_kpis(alert_type, junction_id)
            
        except Exception as e:
            print(f"Error processing record: {e}")
            raise
    
    return {
        'statusCode': 200,
        'body': json.dumps('Events processed')
    }
