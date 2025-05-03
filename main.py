import logger_override# 📄 로그 리디렉션 (가장 먼저)
import sys
import os
import atexit
from datetime import datetime
from config.loader import SYSLOG_DIR
import atexit
from log_manager import RotatingLogger

logger = RotatingLogger(SYSLOG_DIR)
logger.start()
atexit.register(logger.close)


# ---------------------------------------------------------
# 👇 본래 메인 로직 시작

import asyncio
from datetime import datetime, timedelta
from config.loader import load_config, SYSLOG_DIR
from scheduler.manager import init_scheduler
from scheduler.scheduler_setup import setup_combined_schedules
from sensor.monitor import schedule_next_cycle
from websocket.client import connect_and_listen
from websocket.wsnotify import send_scheduleupdate
from scheduler.reset import reset_daily_state

last_checked_date = datetime.now().date()

async def daily_check_loop():
    global last_checked_date  # ← 반드시 필요
    while True:
        now = datetime.now().date()
        if now != last_checked_date:
            print(f"📆 날짜 변경 감지 → 시스템 초기화: {now}")
            logger.check_rotation()
            await reset_daily_state()
            last_checked_date = now
            delete_old_logs(SYSLOG_DIR, days=7)

        await asyncio.sleep(60)

def delete_old_logs(log_dir, days=7):
    cutoff_date = datetime.now() - timedelta(days=days)

    try:
        for filename in os.listdir(log_dir):
            if filename.startswith("log_") and filename.endswith(".txt"):
                path = os.path.join(log_dir, filename)
                date_str = filename[4:12]

                try:
                    file_date = datetime.strptime(date_str, "%Y%m%d")
                    if file_date < cutoff_date:
                        os.remove(path)
                        print(f"🧹 오래된 로그 삭제됨: {filename}")
                except Exception as e:
                    print(f"[WARN] 로그 파일 날짜 파싱 실패: {filename} / {e}")
    except Exception as e:
        print(f"[ERROR] 로그 정리 실패: {e}")

async def main():
    try:
        load_config()
        init_scheduler()
        setup_combined_schedules()
        await send_scheduleupdate()
    except Exception as e:
        print(f"❌ 초기화 중 오류 발생: {e}", flush=True)

    print("🌀 controller 시작됨", flush=True)

    try:
        asyncio.create_task(schedule_next_cycle())
        asyncio.create_task(connect_and_listen())
        asyncio.create_task(daily_check_loop())
    except Exception as e:
        print(f"❌ 백그라운드 태스크 등록 오류: {e}", flush=True)

    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
