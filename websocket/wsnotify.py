# wsnotify.py

import asyncio
import json
import websockets
import socket

uri = "ws://localhost:8000/ws/control/notify/"
async def send_logupdate():
    message = {"cmd": "logupdate"}
    try:
        async with websockets.connect(uri) as websocket:
            await websocket.send(json.dumps(message))
            print("[WebSocket] 로그 업데이트 신호 전송 완료", flush=True)
    except Exception as e:
        print(f"[WebSocket] 로그 업데이트 전송 실패: {e}", flush=True)
        
        
async def send_scheduleupdate():
    message = {"cmd": "schedule"}
    try:
        async with websockets.connect(uri) as websocket:
            await websocket.send(json.dumps(message))
            print("[WebSocket] 스케쥴 업데이트 신호 전송 완료", flush=True)
    except Exception as e:
        print(f"[WebSocket] 스케쥴 업데이트 전송 실패: {e}", flush=True)
        
async def send_message(message):
    message = {"cmd": "message","text":message}
    try:
        async with websockets.connect(uri) as websocket:
            await websocket.send(json.dumps(message))
            print("[WebSocket] 메시지 전송 완료", flush=True)
    except Exception as e:
        print(f"[WebSocket] 메시지 전송 실패: {e}", flush=True)
        
async def send_data(data):
    message = {"cmd": "data","data":data}
    try:
        async with websockets.connect(uri) as websocket:
            await websocket.send(json.dumps(message))
            print("[WebSocket] 데이터 전송 완료", flush=True)
    except Exception as e:
        print(f"[WebSocket] 데이터 전송 실패: {e}", flush=True)
        
async def send_keepalive():
    message = {"cmd": "running","internet":is_connected()}
    try:
        async with websockets.connect(uri) as websocket:
            await websocket.send(json.dumps(message))
            print("[WebSocket] 생존 신호 전송 완료", flush=True)
    except Exception as e:
        print(f"[WebSocket] 생존 신호 전송 실패: {e}", flush=True)
        
def is_connected(hostname="8.8.8.8"):  # Google DNS
    try:
        # host에 연결 시도 (timeout은 적절히 조절)
        socket.create_connection((hostname, 53), timeout=3)
        return True
    except OSError:
        return False
