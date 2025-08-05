import pytest
import json
from unittest.mock import patch, MagicMock
from chalice.app import WebsocketDisconnectedError
from app import app, register_user, broadcast_result, unregister_user

TABLE_NAME = "bpl_room_dev"

# イベント生成ヘルパー
def make_event(connection_id, event_type, params=None, body=None):
    return {
        "requestContext": {
            "connectionId": connection_id,
            "eventType": event_type,
            "domainName": "dummy.execute-api.ap-northeast-1.amazonaws.com",
            "stage": "dev",
            "apiId": "dummyApiId"
        },
        "queryStringParameters": params or {},
        "body": body
    }


@pytest.mark.usefixtures("setup_dynamodb")
def test_register_user():
    event = make_event("test-conn-1", "CONNECT", params={"roomId": "1234-5678", "mode": "1"})
    response = register_user(event, context={})
    assert response['statusCode'] == 200


@pytest.mark.usefixtures("setup_dynamodb")
def test_register_user_over_capacity_1():
    for i in range(4):
        event = make_event(f"conn-{i}", "CONNECT", params={"roomId": "1111-2222", "mode": "1"})
        response = register_user(event, context={})
        assert response['statusCode'] == 200

    event_over = make_event("conn-5", "CONNECT", params={"roomId": "1111-2222", "mode": "1"})
    response = register_user(event_over, context={})
    assert response['statusCode'] == 500
    assert "定員オーバー" in response['body']

@pytest.mark.usefixtures("setup_dynamodb")
def test_register_user_over_capacity_2():
    for i in range(2):
        event = make_event(f"conn-{i}", "CONNECT", params={"roomId": "1111-2222", "mode": "2"})
        response = register_user(event, context={})
        assert response['statusCode'] == 200

    event_over = make_event("conn-5", "CONNECT", params={"roomId": "1111-2222", "mode": "2"})
    response = register_user(event_over, context={})
    assert response['statusCode'] == 500
    assert "定員オーバー" in response['body']


@pytest.mark.usefixtures("setup_dynamodb")
def test_broadcast_result():
    connect_event = make_event("test-conn-2", "CONNECT", params={"roomId": "3333-4444", "mode": "2"})
    register_user(connect_event, context={})

    message_body = json.dumps({
        "roomId": "3333-4444",
        "mode": 2,
        "userId": "user123",
        "name": "テストユーザー",
        "result": "<result>test</result>"
    })

    message_event = make_event("test-conn-2", "MESSAGE", body=message_body)

    with patch.object(app, 'websocket_api') as mock_ws_api:
        mock_ws_api.send = MagicMock(return_value=None)
        response = broadcast_result(message_event, context={})
        assert response['statusCode'] == 200


@pytest.mark.usefixtures("setup_dynamodb")
def test_unregister_user():
    connect_event = make_event("test-conn-3", "CONNECT", params={"roomId": "5555-6666", "mode": "2"})
    register_user(connect_event, context={})

    disconnect_event = make_event("test-conn-3", "DISCONNECT")
    response = unregister_user(disconnect_event, context={})
    assert response['statusCode'] == 200


@pytest.mark.usefixtures("setup_dynamodb")
def test_register_user_invalid_mode():
    event = make_event("test-conn-invalid-mode", "CONNECT", params={"roomId": "1234-5678", "mode": "99"})
    response = register_user(event, context={})
    assert response['statusCode'] == 500
    assert "モードの形式が違います" in response['body']


@pytest.mark.usefixtures("setup_dynamodb")
def test_register_user_invalid_room_id():
    event = make_event("test-conn-invalid-room", "CONNECT", params={"roomId": "あいうえお", "mode": "1"})
    response = register_user(event, context={})
    assert response['statusCode'] == 500
    assert "ルームIDの形式が違います" in response['body']


@pytest.mark.usefixtures("setup_dynamodb")
def test_register_user_dynamodb_error():
    event = make_event("test-conn-dynamo-error", "CONNECT", params={"roomId": "1234-5678", "mode": "1"})

    with patch('app.get_table') as mock_get_table:
        mock_table = MagicMock()
        mock_table.put_item.side_effect = Exception("DynamoDB error")
        mock_get_table.return_value = mock_table

        response = register_user(event, context={})

    assert response['statusCode'] == 500
    assert "ルームの接続に失敗しました" in response['body']


@pytest.mark.usefixtures("setup_dynamodb")
def test_register_user_query_exception():
    event = make_event("test-conn-query-error", "CONNECT", params={"roomId": "1234-5678", "mode": "1"})

    with patch('app.get_table') as mock_get_table:
        mock_table = MagicMock()
        mock_table.query.side_effect = Exception("DynamoDB query error")
        mock_get_table.return_value = mock_table

        response = register_user(event, context={})

    assert response['statusCode'] == 500
    assert "ルームの接続に失敗しました" in response['body']


@pytest.mark.usefixtures("setup_dynamodb")
def test_broadcast_result_query_exception():
    message_body = json.dumps({
        "roomId": "3333-4444",
        "mode": 2,
        "userId": "user123",
        "name": "テストユーザー",
        "result": "<result>test</result>"
    })

    message_event = make_event("test-conn-query-error", "MESSAGE", body=message_body)

    with patch('app.get_table') as mock_get_table:
        mock_table = MagicMock()
        mock_table.query.side_effect = Exception("DynamoDB query error")
        mock_get_table.return_value = mock_table

        response = broadcast_result(message_event, context={})

    assert response['statusCode'] == 500
    print(response['body'])
    assert "送信処理が失敗しました" in response['body']


@pytest.mark.usefixtures("setup_dynamodb")
def test_unregister_user_delete_exception():
    disconnect_event = make_event("test-conn-del-error", "DISCONNECT")

    with patch('app.get_table') as mock_get_table:
        mock_table = MagicMock()
        mock_table.delete_item.side_effect = Exception("DynamoDB delete error")
        mock_get_table.return_value = mock_table

        response = unregister_user(disconnect_event, context={})

    assert response['statusCode'] == 500
    assert "ルームの接続に失敗しました" in response['body']


@pytest.mark.usefixtures("setup_dynamodb")
def test_broadcast_result_disconnected():
    connect_event = make_event("test-conn-disconnect", "CONNECT", params={"roomId": "9999-8888", "mode": "2"})
    register_user(connect_event, context={})

    message_body = json.dumps({
        "roomId": "9999-8888",
        "mode": 2,
        "userId": "user999",
        "name": "切断テスト",
        "result": "<result>test</result>"
    })

    message_event = make_event("test-conn-disconnect", "MESSAGE", body=message_body)

    with patch.object(app, 'websocket_api') as mock_ws_api:
        mock_ws_api.send = MagicMock(side_effect=WebsocketDisconnectedError(connection_id="test-conn-disconnect"))
        response = broadcast_result(message_event, context={})
        assert response['statusCode'] == 200

    # DynamoDBから削除されているか確認
    import boto3
    dynamodb = boto3.resource('dynamodb', region_name='ap-northeast-1')
    table = dynamodb.Table(TABLE_NAME)
    result = table.get_item(Key={'connection_id': "test-conn-disconnect"})
    assert 'Item' not in result
