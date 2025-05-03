from apscheduler.schedulers.background import BackgroundScheduler

# 전역 scheduler 객체
_scheduler = None

def init_scheduler():
    """스케줄러를 새로 생성하고 시작"""
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)  # 기존 스케줄러 종료
    _scheduler = BackgroundScheduler()
    _scheduler.start()
    print("🕒 APScheduler 시작됨")

def get_scheduler():
    """현재 scheduler 객체 반환"""
    return _scheduler

def clear_scheduler():
    """모든 스케줄 제거 (초기화용)"""
    if _scheduler:
        _scheduler.remove_all_jobs()
        print("🔁 모든 스케줄 초기화됨")