import asyncio
from config.loader import load_config,save_config,LOG_DIR
from datetime import datetime, timedelta
from websocket.wsnotify import send_keepalive,send_logupdate,is_connected,send_message


def get_next_schedule_time():
    now = datetime.now()
    base_minutes = [1, 16, 31, 46]
    for m in base_minutes:
        scheduled = now.replace(minute=m, second=0, microsecond=0)
        if scheduled > now:
            return scheduled
    # 다음 시간으로 이월
    return (now + timedelta(hours=1)).replace(minute=1, second=0, microsecond=0)


async def schedule_next_cycle():
    while True:
        await send_keepalive()
        next_time = get_next_schedule_time()
        wait_sec = (next_time - datetime.now() + timedelta(seconds=1)).total_seconds()
        wait_sec = max(wait_sec, 0)
        # print(f"⏳ 다음 센서 주기 예약: {next_time.strftime('%H:%M:%S')} (in {int(wait_sec)}초)")

        await asyncio.sleep(wait_sec)

        try:
            await run_sensor_cycle()
        except Exception as e:
            print(f"❌ 센서 루프 예외 발생, 다음 주기는 계속 예약됨: {e}", flush=True)


from datetime import datetime
from scheduler.irrigation import irrigate
from sensor.api import fetch_raw_sensor_data
from sensor.sensor import process_raw_sensor_data,calculate_sumx,read_weather_sensor_packet
from sensor.logger import log_exists_for_today, save_sensor_log,load_existing_log,save_weather_csv
from scheduler.reset import reset_daily_state
import pandas as pd


async def run_sensor_cycle():
    print(f"⏱️ 센서 루프 시작 - {datetime.now().strftime('%H:%M:%S')}")
    config = load_config()
    master = config.get("master", {})
    if not master.get("external_sensor_enabled", True):
        print("⏸️ 외부 센서 사용 안함 - 센서 루프 건너뜀", flush=True)
        return

    if not is_connected():      
        config["irrigationpanel"]["control_mode"]["1"] = "timer"
        config["irrigationpanel"]["control_mode"]["2"] = "timer"
        config["irrigationpanel"]["control_mode"]["3"] = "timer"
        config["irrigationpanel"]["control_mode"]["4"] = "timer"
        save_config(config)
        print(f"🟡 인터넷 연결이 안되어있음 (제어 타입 Timer 강제 변경)")
        await send_message(f"🟡 인터넷 연결이 안되어있음 (제어 타입 Timer 강제 변경)")
        await reset_daily_state()
        
        return


    sensor_settings = config.get("sensor_settings", {})
    irrigation_channels = config.get("irrigation_channels", {})
    control_modes = config["irrigationpanel"].get("control_mode", {})
    test_mode = config.get("test_mode", False)
    runbool = False
    
    for ch, setting in sensor_settings.items():
        ch = str(ch)
        if not irrigation_channels.get(ch, False):
            continue
        if control_modes.get(ch) != "sensor":
            continue

        now = datetime.now()
        nowtime = now.time()
        start_time = datetime.strptime(setting["start_time"], "%H:%M").time()
        end_time = datetime.strptime(setting["end_time"], "%H:%M").time()
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        
        
        if not (start_time <= nowtime <= end_time):
            continue

        # 로그 존재 여부 판단
        if not log_exists_for_today(ch):
            
            fetch_start = start_of_day
            fetch_end = now
            
            raw_module_data = await fetch_raw_sensor_data(setting, fetch_start, fetch_end)
            if not raw_module_data:
                config["irrigationpanel"]["control_mode"][ch] = "timer"
                save_config(config)
                print(f"🟡 해당 채널의 모듈 데이터 없음 (제어 타입 Timer 강제 변경)")
                await reset_daily_state()
                await send_message(f"Ch{ch}의 수신된 데이터가 없습니다. Timer 강제 변경")
                continue
            
            sfdata = process_raw_sensor_data(raw_module_data,setting)
            sfdata = calculate_sumx(sfdata, setting,start=start_time,end=end_time)
            # sfdata = apply_conditional_filter(sfdata)
            
            nowT = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            sfdata["realTime"] = nowT
            # 컬럼 순서 변경: realTime을 맨 앞에
            cols = sfdata.columns.tolist()
            cols.insert(0, cols.pop(cols.index("realTime")))
            sfdata = sfdata[cols]
            
            save_sensor_log(sfdata, ch)  # ✅ 로그 저장
            runbool = True
            
        else:
            
            fetch_end = now
            # 1. 기존 로그 불러오기
            old_log = load_existing_log(ch)
            if old_log.empty:
                print("❗ 예상치 못한 오류: 로그가 존재한다고 했는데 내용이 없음")
                continue
            
            last_time = pd.to_datetime(old_log["Time"]).max()
            # one_hour_ago = last_time - timedelta(hours=1)
            # fetch_start = max(start_of_day,one_hour_ago)
            fetch_start = start_of_day
            
            raw_module_data = await fetch_raw_sensor_data(setting, fetch_start, fetch_end)      
            
            if not raw_module_data:
                config["irrigationpanel"]["control_mode"][ch] = "timer"
                save_config(config)
                print(f"🟡 해당 채널의 모듈 데이터 없음 (제어 타입 Timer 강제 변경)")
                await reset_daily_state()
                await send_message(f"Ch{ch}의 수신된 데이터가 없습니다. Timer 강제 변경")
                continue
             
            new_df = process_raw_sensor_data(raw_module_data, setting)
            new_df = new_df[new_df["Time"] > last_time]
            
            if new_df.empty:
                
                continue
            
            last_row = old_log.iloc[-1]  # Series 타입
            sfdata = calculate_sumx(new_df,setting,start=start_time,end=end_time,last_state=last_row)
            # sfdata = apply_conditional_filter(sfdata)
            
            nowT = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            sfdata["realTime"] = nowT
            # 컬럼 순서 변경: realTime을 맨 앞에
            cols = sfdata.columns.tolist()
            cols.insert(0, cols.pop(cols.index("realTime")))
            sfdata = sfdata[cols]
            
            if not sfdata.empty:
                
                last_row = sfdata.iloc[-1]
                last_time = pd.to_datetime(last_row["Time"])
                now = datetime.now()

                if (
                    last_row.get("action") == "관수"
                    and (now - last_time) <= timedelta(minutes=20)
                ):

                    duration = config["irrigationpanel"]["irrigation_time"].get(ch, 10)

                    irrigate(ch, duration, test_mode)
                    
            # 👉 병합 및 저장
            merged_log = pd.concat([old_log, sfdata], ignore_index=True)
            merged_log = merged_log.sort_values("Time").reset_index(drop=True)

            save_sensor_log(merged_log, ch)  # ✅ 로그 저장
            
            runbool = True
            
    port = config.get("sensor_ports")  # 예: "COM3"
    weather_data = read_weather_sensor_packet(port)
    save_weather_csv(weather_data)
        
    if runbool:
        await send_logupdate()
    
import os
    
    
async def get_test_data(data):
    file_path = os.path.join(LOG_DIR, "test", f"{data['ch']}ch_test.csv")
    config = load_config()
    sensor_settings = config.get("sensor_settings", {})
    setting = sensor_settings.get(data['ch'], {})

    # 업데이트 값 적용
    setting['nf_value'] = data['nf']
    setting['target'] = data['goal']

    # 날짜 파싱
    fetch_start = datetime.strptime(data["start"], "%Y-%m-%d").replace(hour=0, minute=0, second=0)
    fetch_end = datetime.strptime(data["end"], "%Y-%m-%d").replace(hour=23, minute=59, second=0)
    
    start_time = datetime.strptime(setting["start_time"], "%H:%M").time()
    end_time = datetime.strptime(setting["end_time"], "%H:%M").time()

    # 데이터 가져오기
    raw_module_data = await fetch_raw_sensor_data(setting, fetch_start, fetch_end)
    
    # CSV 저장 경로
    

    # ✅ 데이터가 없을 경우 → status,nodata 저장
    if not raw_module_data or len(raw_module_data) == 0:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("status,nodata\n")
        return  # 더 이상 처리 안 함
    
    df = process_raw_sensor_data(raw_module_data, setting)

    # 2. 날짜별로 분리
    df["Time"] = pd.to_datetime(df["Time"])  # 혹시 datetime이 아닐 수도 있어서 확실히
    daily_dfs = split_by_date(df)

    # 3. 각 날짜에 대해 sumx 계산 실행
    combined_df = pd.DataFrame()
    for date, daily_df in daily_dfs.items():
        calculated = calculate_sumx(daily_df, setting, start=start_time, end=end_time)
        combined_df = pd.concat([combined_df, calculated])

    # 4. 정렬 및 저장
    combined_df = combined_df.sort_values("Time")
    # combined_df = apply_conditional_filter(combined_df)
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    combined_df.to_csv(file_path, index=False, encoding="utf-8-sig")
    
def split_by_date(df):
    """날짜별로 분리된 DataFrame 딕셔너리 반환"""
    df["Date"] = df["Time"].dt.date
    return {date: group.drop(columns="Date") for date, group in df.groupby("Date")}
