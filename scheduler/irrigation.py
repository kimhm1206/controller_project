from config.loader import load_config
from relay.controller import tcpcontrol_multi,emergency_shutdown
from datetime import datetime
from sensor.logger import save_time_log, save_sensor_log,log_exists_for_today,load_existing_log
import pandas as pd
import asyncio
from websocket.wsnotify import send_logupdate

async def handle_manual_irrigation(ch):
    config = load_config()
    test_mode = config.get("test_mode", False)
    now_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    today_str = datetime.now().strftime("%Y%m%d")

    if ch == "all":
        irrigation_channels = config.get("irrigation_channels", {})
        control_modes = config["irrigationpanel"].get("control_mode", {})
        time_map = config["irrigationpanel"].get("irrigation_time", {})

        on_dict = {"irrigation": {}}
        duration_groups = {}  # duration별 채널 그룹화

        for ch_key, is_active in irrigation_channels.items():
            if is_active:
                mode = control_modes.get(ch_key, "timer")
                duration = time_map.get(ch_key, 10)
                on_dict["irrigation"][f"ch{ch_key}"] = "on"
                duration_groups.setdefault(duration, []).append(ch_key)

                # 로그 저장 (채널별로)
                log_path = f"../telofarmer_django/data/log/{ch_key}/{ch_key}ch_sensor_log_{today_str}.csv"
                if mode == "timer":
                    save_time_log(ch_key, "수동", "관수")
                elif mode == "sensor":
                    if log_exists_for_today(ch_key):
                        df = load_existing_log(ch_key)
                        prev_dailysumx = df.iloc[-1]["dailysumx"] if "dailysumx" in df.columns else 0
                        new_row = {
                            "realTime": now_time,
                            "Time": now_time,
                            "svalue": 0,
                            "sumx": 0,
                            "dailysumx": prev_dailysumx,
                            "action": "수동관수",
                            "goal": 0
                        }
                        df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
                        save_sensor_log(df, ch_key)
                    else:
                        init_time = datetime.now().strftime("%Y-%m-%d 00:01:00")
                        df = pd.DataFrame([{
                            "realTime": now_time,
                            "Time": init_time,
                            "svalue": 0,
                            "sumx": 0,
                            "dailysumx": 0,
                            "action": f"{datetime.now().strftime('%H:%M')} 수동관수",
                            "goal": 0
                        }])
                        save_sensor_log(df, ch_key)
                        print(f"[LOG] 초기 수동 로그 생성됨 → {log_path}", flush=True)

        print(f"🛠 [수동 관수] 전체 채널 관수 시작 → {list(on_dict['irrigation'].keys())}")
        tcpcontrol_multi(on_dict, test_mode)

        # duration 그룹별로 OFF 처리
        for duration, ch_list in duration_groups.items():
            def end_group(chs):
                off_dict = {"irrigation": {f"ch{c}": "off" for c in chs}}
                print(f"🛑 [수동 관수 종료] 채널들: {chs}")
                tcpcontrol_multi(off_dict, test_mode)

            asyncio.get_event_loop().call_later(duration, end_group, ch_list)

    else:
        duration = config["irrigationpanel"]["irrigation_time"].get(ch, 10)
        mode = config["irrigationpanel"]["control_mode"].get(ch, "timer")

        print(f"🛠 [수동 관수] CH{ch} / {duration}s / 모드:{mode}")

        tcpcontrol_multi({"irrigation": {f"ch{ch}": "on"}}, test_mode)

        def end_irrigation():
            print(f"🛑 [수동 관수 종료] CH{ch}")
            tcpcontrol_multi({"irrigation": {f"ch{ch}": "off"}}, test_mode)

        asyncio.get_event_loop().call_later(duration, end_irrigation)

        if mode == "timer":
            save_time_log(ch, "수동", "관수")

        elif mode == "sensor":
            if log_exists_for_today(ch):
                df = load_existing_log(ch)
                prev_dailysumx = df.iloc[-1]["dailysumx"] if "dailysumx" in df.columns else 0
                new_row = {
                    "realTime": now_time,
                    "Time": now_time,
                    "svalue": 0,
                    "sumx": 0,
                    "dailysumx": prev_dailysumx,
                    "action": "수동관수",
                    "goal": 0
                }
                df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
                save_sensor_log(df, ch)
            else:
                init_time = datetime.now().strftime("%Y-%m-%d 00:01:00")
                df = pd.DataFrame([{
                    "realTime": now_time,
                    "Time": init_time,
                    "svalue": 0,
                    "sumx": 0,
                    "dailysumx": 0,
                    "action": f"{datetime.now().strftime('%H:%M')} 수동관수",
                    "goal": 0
                }])
                save_sensor_log(df, ch)
                
    await send_logupdate()



async def handle_emergency_stop():
    config = load_config()
    test_mode = config.get("test_mode", False)

    print("🛑 [긴급 정지] 모든 릴레이 OFF 수행 중...", flush=True)

    # 관수 + LED 전체 OFF
    emergency_shutdown("irrigation", test_mode=test_mode)

    print(f"🛑 [{datetime.now().strftime('%H:%M:%S')}] 긴급 정지 명령 처리 완료", flush=True)
    
    
    

def irrigate(ch, duration, test_mode=True):

    print(f"🌱 [관수 시작] 채널 {ch} / {duration}초 / Test = {test_mode}")

    # 관수 ON
    tcpcontrol_multi({"irrigation": {f"ch{ch}": "on"}}, test_mode)

    # duration 후 자동 OFF
    def end_irrigation():
        print(f"🛑 [관수 종료] 채널 {ch}")
        tcpcontrol_multi({"irrigation": {f"ch{ch}": "off"}}, test_mode)

    asyncio.get_event_loop().call_later(duration, end_irrigation)