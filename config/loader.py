import json
import os

# 📁 경로 정의 (C:\Users\{user}\Documents\telofarm\telofarmer\...)
USER_DOCS = os.path.join(os.path.expanduser("~"), "Documents", "telofarm", "telofarmer")
DATA_DIR = os.path.join(USER_DOCS, "data")
LOG_DIR = os.path.join(USER_DOCS, "log")
SYSLOG_DIR = os.path.join(USER_DOCS, "systemlog")

# 🔧 setting.json 경로
SETTING_PATH = os.path.join(DATA_DIR, "setting.json")

# 📂 폴더 생성 (최초 실행 시)
for path in [DATA_DIR, LOG_DIR, SYSLOG_DIR]:
    if not os.path.exists(path):
        os.makedirs(path)
        print(f"📂 폴더 생성됨: {path}")

# 📦 내부 캐시 설정값
_cached_config = {}

def load_config():
    """setting.json을 읽어서 파싱된 dict 반환"""
    global _cached_config

    if not os.path.exists(SETTING_PATH):
        print(f"⚠️ 설정파일 없음 → 새로 생성: {SETTING_PATH}")
        save_config({})  # 빈 설정 저장

    try:
        with open(SETTING_PATH, "r", encoding="utf-8") as f:
            _cached_config = json.load(f)
            print(_cached_config)
    except Exception as e:
        print(f"❌ 설정 로드 실패: {e}")
        _cached_config = {}

    return _cached_config


def get_config():
    """캐싱된 설정값 반환"""
    return _cached_config


def reload_config():
    """설정 재로딩"""
    print("🔁 setting.json 리로드됨")
    return load_config()


def save_config(config):
    """_cached_config의 값을 setting.json에 덮어쓰기"""
    global _cached_config

    if config is not None:
        try:
            with open(SETTING_PATH, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            print(f"💾 설정 저장됨: {SETTING_PATH}")
            _cached_config = config
        except Exception as e:
            print(f"❌ 설정 저장 실패: {e}")
    else:
        print("❗ Error: 저장할 설정값이 없습니다.")
