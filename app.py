import os
from chalice import Chalice, WebsocketDisconnectedError, BadRequestError
import boto3
import json
import re
import traceback
from boto3.dynamodb.conditions import Key

app = Chalice(app_name='sdvx_battle_server')
app.experimental_feature_flags.update(['WEBSOCKETS'])
app.websocket_api.session = boto3.session.Session(region_name=os.environ['APP_AWS_REGION'])

# 接続制限
MAX_CONNECTIONS = int(os.environ['MAX_CONNECTIONS'])
# 複合GSI名（room_id + mode）
ROOM_MODE_INDEX = 'room_mode-index'

def get_table():
    dynamodb = boto3.resource('dynamodb', region_name=os.environ['APP_AWS_REGION'])
    return dynamodb.Table(os.environ['TABLE_NAME'])

# ---------------------------
# WebSocket接続開始（ユーザ登録API）
# ---------------------------
@app.on_ws_connect()
def register_user(event):
    try:
        params = event.to_dict().get('queryStringParameters') or {}
        room_id = params.get('roomId')
        mode = params.get('mode')

        if not mode or mode not in ['1', '2', '3', '4', '5', '6']:
            app.log.error("接続エラー: モード形式不正")
            return {
                'statusCode': 500,
                'body': '接続できませんでした：モードの形式が違います'
            }

        if not room_id or not re.match(r'^[a-zA-Z0-9_-]{4,32}$', room_id):
            app.log.error("接続エラー: ルームID形式不正")
            return {
                'statusCode': 500,
                'body': '接続できませんでした：ルームIDの形式が違います'
            }

        # 現在の接続数確認
        active_connections = get_table().scan(Select="COUNT")["Count"]
        if active_connections >= MAX_CONNECTIONS:
            return {"statusCode": 403, "body": "Too many connections"}
        mode_int = int(mode)

        # 定員チェック（複合GSI使用）
        response = get_table().query(
            IndexName=ROOM_MODE_INDEX,
            KeyConditionExpression=Key('room_id').eq(room_id) & Key('mode').eq(mode_int),
            ProjectionExpression="connection_id"
        )

        current_count = len(response.get('Items', []))

        if mode in ['1', '2', '4', '5'] and current_count >= 4:
            app.log.error(f"接続エラー: アリーナモード定員オーバー (current={current_count})")
            return {
                'statusCode': 500,
                'body': '接続できませんでした：定員オーバーです'
            }

        if mode in ['3', '6'] and current_count >= 2:
            app.log.error(f"接続エラー: BPLバトルモード定員オーバー (current={current_count})")
            return {
                'statusCode': 500,
                'body': '接続できませんでした：定員オーバーです'
            }

        connection_id = event.connection_id

        get_table().put_item(
            Item={
                'connection_id': connection_id,
                'room_id': room_id,
                'mode': mode_int
            }
        )

        app.log.info(f"接続成功: connection_id={connection_id}, room_id={room_id}, mode={mode}")
        return {'statusCode': 200, 'body': ''}

    except Exception as e:
        app.log.error(f"接続登録失敗: {str(e)}")
        return {
            'statusCode': 500,
            'body': '接続できませんでした：ルームの接続に失敗しました'
        }

# ---------------------------
# 情報連携API（メッセージ送信）
# ---------------------------
@app.on_ws_message()
def broadcast_result(event):
    try:
        body = json.loads(event.body)
        room_id = body.get('roomId')
        user_id = body.get('userId')
        name = body.get('name')
        result_token = body.get('resultToken') or ""
        operation = body.get('operation') or "register"
        result = body.get('result')
        mode = body.get('mode')

        if not all([room_id, user_id, name, result, mode]):
            raise BadRequestError("必須パラメータ不足")

        mode_int = int(mode)

        response = get_table().query(
            IndexName=ROOM_MODE_INDEX,
            KeyConditionExpression=Key('room_id').eq(room_id) & Key('mode').eq(mode_int),
            ProjectionExpression="connection_id"
        )

        connection_ids = [item['connection_id'] for item in response.get('Items', [])]

        if not connection_ids:
            raise Exception("接続先が見つかりませんでした")

        ws_client = app.websocket_api

        message = json.dumps({
            'userId': user_id,
            'name': name,
            'operation': operation,
            'resultToken': result_token,
            'result': result
        })

        for conn_id in connection_ids:
            try:
                ws_client.send(conn_id, message)
                app.log.info(f"送信成功: to connection_id={conn_id}")
            except WebsocketDisconnectedError:
                app.log.info(f"切断検出: connection_id={conn_id} を削除")
                get_table().delete_item(Key={'connection_id': conn_id})
            except Exception as e:
                app.log.error(f"送信エラー: {str(e)}")

        return {'statusCode': 200, 'body': ''}

    except Exception as e:
        app.log.error(f"送信処理失敗: {traceback.format_exc()}")
        return {'statusCode': 500, 'body': '接続できませんでした：送信処理が失敗しました'}

# ---------------------------
# WebSocket切断時（ユーザ削除API）
# ---------------------------
@app.on_ws_disconnect()
def unregister_user(event):
    try:
        connection_id = event.connection_id
        get_table().delete_item(Key={'connection_id': connection_id})
        app.log.info(f"切断成功: connection_id={connection_id}")
        return {'statusCode': 200, 'body': ''}

    except Exception as e:
        app.log.error(f"切断失敗: {str(e)}")
        return {
            'statusCode': 500,
            'body': '接続できませんでした：ルームの接続に失敗しました'
        }
