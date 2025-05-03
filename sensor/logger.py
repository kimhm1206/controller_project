import os
import pandas as pd
from datetime import datetime
from websocket.wsnotify import send_logupdate
import asyncio
import csv

from config.loader import LOG_DIR  # 📂 로그 경로: .../log


def log_exists_for_today(ch):
    ch = str(ch)
    date_str = datetime.now().strftime("%Y%m%d")
    log_dir = os.path.join(LOG_DIR, ch)
    file_path = os.path.join(log_dir, f"{ch}ch_sensor_log_{date_str}.csv")

    return os.path.exists(file_path)


def save_time_log(ch: str, mode: str, action: str):
    today = datetime.now().strftime("%Y%m%d")
    log_dir = os.path.join(LOG_DIR, ch)
    os.makedirs(log_dir, exist_ok=True)

    file_path = os.path.join(log_dir, f"{ch}_time_log_{today}.csv")
    now_time = datetime.now().strftime("%H:%M")

    row = [now_time, mode, action]

    write_header = not os.path.exists(file_path)
    with open(file_path, mode='a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(["Time", "mode", "action"])
        writer.writerow(row)

    print(f"💾 로그 저장 완료: {file_path}")


def save_sensor_log(df: pd.DataFrame, ch: str):
    date_str = datetime.now().strftime("%Y%m%d")
    log_dir = os.path.join(LOG_DIR, ch)
    os.makedirs(log_dir, exist_ok=True)

    file_path = os.path.join(log_dir, f"{ch}ch_sensor_log_{date_str}.csv")
    df.to_csv(file_path, index=False, encoding='utf-8-sig')
    print(f"💾 로그 저장 완료: {file_path}")


def load_existing_log(ch: str) -> pd.DataFrame:
    date_str = datetime.now().strftime("%Y%m%d")
    file_path = os.path.join(LOG_DIR, ch, f"{ch}ch_sensor_log_{date_str}.csv")
    if os.path.exists(file_path):
        return pd.read_csv(file_path, parse_dates=["Time"])
    else:
        return pd.DataFrame(columns=["Time", "svalue", "sumx", "dailysumx", "action", "goal"])
