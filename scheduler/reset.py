from scheduler.manager import get_scheduler
from scheduler.scheduler_setup import setup_combined_schedules
from websocket.wsnotify import send_scheduleupdate

async def reset_daily_state():
    try:
        scheduler = get_scheduler()
        print("🔁 스케줄 초기화 중...")
        scheduler.remove_all_jobs()

        setup_combined_schedules()
        await send_scheduleupdate()
        print("✅ 시스템 리셋 완료 (새로운 날짜 기준)")
    except Exception as e:
        print(f"❌ 시스템 리셋 중 오류 발생: {e}")
