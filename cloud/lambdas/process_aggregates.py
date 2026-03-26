"""
Lambda: Process Traffic Aggregates
Consumes aggregates from SQS, stores in DynamoDB.
"""

import json
import boto3
import os
from datetime import datetime
from decimal import Decimal

dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table(os.environ['AGGREGATES_TABLE_NAME'])


def lambda_handler(event, context):
    """Process SQS message batch."""
    
    for record in event['Records']:
        try:
            # Parse message
            message_body = json.loads(record['body'])
            
            junction_id = message_body['junctionId']
            timestamp = message_body['timestamp']
            
            # Construct partition key: junctionId#metric
            # We'll store one aggregate per timestamp per junction
            
            item = {
                'PK': f"{junction_id}#aggregates",
                'SK': timestamp,  # ISO timestamp
                'junctionId': junction_id,
                'timestamp': timestamp,
                'vehicle_count_sum': int(message_body['vehicle_count_sum']),
                'avg_speed': Decimal(str(message_body['avg_speed'])),
                'congestion_index': Decimal(str(message_body['congestion_index'])),
                'rain_intensity': message_body.get('rain_intensity'),
                'avg_ambient_light': Decimal(str(message_body['avg_ambient_light'])) if message_body.get('avg_ambient_light') else None,
                'avg_pollution': Decimal(str(message_body['avg_pollution'])) if message_body.get('avg_pollution') else None,
                'metrics_count': int(message_body['metrics_count']),
                'processed_at': datetime.utcnow().isoformat()
            }
            
            # Deduplication: use MessageDeduplicationId from SQS FIFO
            item['idempotency_key'] = record.get('messageId')
            
            # Conditional write: skip if PK+SK already exists (idempotent)
            try:
                table.put_item(
                    Item=item,
                    ConditionExpression="attribute_not_exists(PK) AND attribute_not_exists(SK)"
                )
                print(f"Stored aggregate: {junction_id} @ {timestamp}")
            except dynamodb.meta.client.exceptions.ConditionalCheckFailedException:
                print(f"Duplicate aggregate skipped: {junction_id} @ {timestamp}")
            
        except Exception as e:
            print(f"Error processing record: {e}")
            raise
    
    return {
        'statusCode': 200,
        'body': json.dumps('Aggregates processed')
    }
