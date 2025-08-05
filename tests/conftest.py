import pytest
import os
import sys
import boto3
from moto import mock_aws
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

TABLE_NAME = "bpl_room_dev"


@pytest.fixture(scope="function")
def setup_dynamodb():
    os.environ['APP_AWS_REGION'] = 'ap-northeast-1'
    os.environ['TABLE_NAME'] = TABLE_NAME
    os.environ['MAX_CONNECTIONS'] = "10"

    with mock_aws():
        dynamodb = boto3.resource('dynamodb', region_name='ap-northeast-1')
        table = dynamodb.create_table(
            TableName=TABLE_NAME,
            KeySchema=[{'AttributeName': 'connection_id', 'KeyType': 'HASH'}],
            AttributeDefinitions=[
                {'AttributeName': 'connection_id', 'AttributeType': 'S'},
                {'AttributeName': 'room_id', 'AttributeType': 'S'},
                {'AttributeName': 'mode', 'AttributeType': 'N'}
            ],
            GlobalSecondaryIndexes=[{
                'IndexName': 'room_mode-index',
                'KeySchema': [
                    {'AttributeName': 'room_id', 'KeyType': 'HASH'},
                    {'AttributeName': 'mode', 'KeyType': 'RANGE'}
                ],
                'Projection': {'ProjectionType': 'ALL'},
                'ProvisionedThroughput': {'ReadCapacityUnits': 5, 'WriteCapacityUnits': 5}
            }],
            ProvisionedThroughput={'ReadCapacityUnits': 5, 'WriteCapacityUnits': 5}
        )
        table.meta.client.get_waiter('table_exists').wait(TableName=TABLE_NAME)
        yield