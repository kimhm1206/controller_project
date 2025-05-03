from scheduler.manager import get_scheduler
from config.loader import get_config
import threading
from websocket.wsnotify import send_logupdate
from relay.controller import tcpcontrol_multi, relay_state, set_relay_state ,emergency_shutdown
from datetime import datetime
import asyncio
from sensor.logger import save_time_log
   
    
def initialize_relay_state(config):
    state = {"irrigation": {}, "led": {}}

    for ch, enabled in config["irrigation_channels"].items():
        if enabled:
            port = config["irrigationpanel"]["relay_port_mapping"].get(ch)
            state["irrigation"][f"ch{ch}"] = {"port": port, "state": 0}

    for ch, enabled in config["led_channels"].items():
        if enabled:
            port = config["ledpanel"]["led_port_mapping"].get(ch)
            state["led"][f"ch{ch}"] = {"port": port, "state": 0}

    return state

def execute_combined_job(job_list, test_mode=False):
    print("🧩 [복합 스케줄 실행]", flush=True)
    port_dict = {"irrigation": {}, "led": {}}
    irrigation_groups = {}

    logbool = False
    for job in job_list:
        if job[0] == "led":
            _, ch, mode = job  # mode: "on" or "off"
            print(f"💡 [LED {mode.upper()}] CH{ch}", flush=True)
            port_dict["led"][f"ch{ch}"] = mode

        elif job[0] == "irrigation":
            logbool = True
            _, ch, duration = job
            print(f"🌱 [관수] CH{ch} → {duration}s", flush=True)
            port_dict["irrigation"][f"ch{ch}"] = "on"
            irrigation_groups.setdefault(duration, []).append(f"ch{ch}")
            save_time_log(ch, "자동", "관수")
            
    if logbool:
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:  # 쓰레드에 루프가 없을 경우
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        if loop.is_running():
            loop.create_task(send_logupdate())
        else:
            loop.run_until_complete(send_logupdate())
            
    tcpcontrol_multi(port_dict, test_mode)
    
    for duration, ch_list in irrigation_groups.items():
        def end_group(chs):
            off_dict = {"irrigation": {ch: "off" for ch in chs}}
            print(f"🛑 [관수 종료] 채널들: {chs}", flush=True)
            tcpcontrol_multi(off_dict, test_mode)

        threading.Timer(duration, end_group, args=[ch_list]).start()


def setup_combined_schedules():
    global relay_state
    config = get_config()
    state = initialize_relay_state(config)
    set_relay_state(state)  # relay_state 공유 통일!
    relay_state = initialize_relay_state(config)
    scheduler = get_scheduler()
    
    now = datetime.now()
    test_mode = config.get("test_mode", False)
    job_group = {}
    immediate_led_on_dict = {}

    irrigation_channels = config.get("irrigation_channels", {})
    mode_map = config["irrigationpanel"].get("control_mode", {})
    time_table = config.get("time_control", {})
    time_map = config["irrigationpanel"].get("irrigation_time", {})

    for ch, is_active in irrigation_channels.items():
        ch_str = str(ch)
        if not is_active or mode_map.get(ch_str) != "timer":
            continue

        duration = time_map.get(ch_str, 10)

        for t in time_table.get(ch_str, []):
            try:
                hour, minute = map(int, t.split(":"))
            except:
                continue

            if now.hour > hour or (now.hour == hour and now.minute >= minute):
                continue

            job_group.setdefault(t, []).append(("irrigation", ch_str, duration))

    led_channels = config.get("led_channels", {})
    led_time = config["ledpanel"].get("led_time", {})

    ledbool = False
    for ch, is_active in led_channels.items():
        ch_str = str(ch)
        if not is_active:
            continue

        times = led_time.get(ch_str)
        if not times:
            continue

        on_time = times.get("on")
        off_time = times.get("off")

        try:
            on_hour, on_min = map(int, on_time.split(":"))
            off_hour, off_min = map(int, off_time.split(":"))
        except:
            continue

        # 현재 시각 기준 즉시 ON 필요한 경우 모아두기
        on_total = on_hour * 60 + on_min
        off_total = off_hour * 60 + off_min
        now_total = now.hour * 60 + now.minute
        ledbool = True
        if on_total <= now_total < off_total:
            immediate_led_on_dict[f"ch{ch_str}"] = "on"
        elif on_total > now_total:
            job_group.setdefault(on_time, []).append(("led", ch_str, "on"))

        if off_total > now_total:
            job_group.setdefault(off_time, []).append(("led", ch_str, "off"))

    # 한 번만 LED 즉시 제어
    if immediate_led_on_dict:
        tcpcontrol_multi({"led": immediate_led_on_dict}, test_mode)
        on_list = ", ".join(immediate_led_on_dict.keys())
        print(f"🕓 [스케줄 등록]💡현재 시간 기준 → {on_list} 켜짐", flush=True)
        
    if not ledbool:
        emergency_shutdown("led",test_mode)

    for time_str, job_list in job_group.items():
        try:
            hour, minute = map(int, time_str.split(":"))
            scheduler.add_job(
                execute_combined_job,
                'cron',
                hour=hour,
                minute=minute,
                args=[job_list, test_mode],
                id=f"combined_{time_str}"
            )
            lines = [f"🕓 [스케줄 등록] {time_str}"]
            for job in job_list:
                if job[0] == "led":
                    _, ch, mode = job
                    lines.append(f" - LED ch{ch} → {mode.upper()}")
                elif job[0] == "irrigation":
                    _, ch, duration = job
                    lines.append(f" - 관수 ch{ch} → ON ({duration}초)")

            print("\n".join(lines), flush=True)

        except Exception as e:
            print(f"❌ [스케줄 실패] {time_str}: {e}", flush=True)



