import asyncio
import websockets
import json

from config.loader import reload_config
from scheduler.manager import clear_scheduler
from scheduler.irrigation import handle_manual_irrigation, handle_emergency_stop
from websocket.wsnotify import send_scheduleupdate,is_connected,send_data
from relay.controller import relay_state
from scheduler.scheduler_setup import setup_combined_schedules
from sensor.monitor import get_test_data


async def connect_and_listen():
    uri = "ws://localhost:8000/ws/control/"
    print(f"🌐 WebSocket 연결 시도 중: {uri}", flush=True)
    global relay_state
    while True:
        try:
            async with websockets.connect(uri) as websocket:
                print("🟢 WebSocket 연결 성공 (controller)", flush=True)
                await websocket.send(json.dumps({"cmd": "running","internet":is_connected()}))
                await send_data(relay_state)
                while True:
                    message = await websocket.recv()
                    
                    print(f"📨 메시지 수신됨: {message}", flush=True)

                    try:
                        data = json.loads(message)
                        cmd = data.get("cmd")

                        if cmd == "refresh":
                            print("🔁 'refresh' 명령 수신됨 → 설정 리로드 및 스케줄 재설정", flush=True)
                            reload_config()
                            clear_scheduler()
                            setup_combined_schedules()
                            await send_scheduleupdate()
                            print("✅ 재설정 완료", flush=True)
                            
                        if cmd == "manual":
                            ch = data.get("ch")
                            if ch is not None:
                                await handle_manual_irrigation(ch)
                                
                        if cmd == "emergency":
                            await handle_emergency_stop()
                                
                        if cmd == "testdata":
                            await get_test_data(data)

                    except Exception as e:
                        print(f"⚠ 메시지 처리 중 오류 발생: {e}", flush=True)

        except Exception as e:
            print(f"❌ WebSocket 연결 실패 또는 연결 종료됨: {e}", flush=True)
            print("⏳ 5초 후 재연결 시도 중...", flush=True)
            await asyncio.sleep(5)