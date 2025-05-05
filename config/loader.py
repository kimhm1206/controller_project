import json
import os,platform

# 📁 경로 정의 (C:\Users\{user}\Documents\telofarm\telofarmer\...)
if platform.system() == "Windows":
    USER_DOCS = os.path.join(os.path.expanduser("~"), "Documents", "telofarm", "telofarmer")
else:
    USER_DOCS = "/home/telofarm/Documents/telofarm/telofarmer"

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

        default_config = {
            "relayboard_type": "8port",
            "sensor_ports": "com1",
            "test_mode": True,
            "irrigation_channels": {
                "1": True,
                "2": False,
                "3": False,
                "4": False
            },
            "led_channels": {
                "1": False,
                "2": False,
                "3": False,
                "4": False
            },
            "irrigationpanel": {
                "control_mode": {
                    "1": "timer",
                    "2": "timer",
                    "3": "timer",
                    "4": "timer"
                },
                "relay_port_mapping": {
                    "1": 0,
                    "2": 1,
                    "3": 2,
                    "4": 3
                },
                "irrigation_time": {
                    "1": 100,
                    "2": 100,
                    "3": 100,
                    "4": 100
                }
            },
            "ledpanel": {
                "led_port_mapping": {
                    "1": 4,
                    "2": 5,
                    "3": 6,
                    "4": 7
                },
                "led_time": {
                    "1": {"on": "08:00", "off": "17:00"},
                    "2": {"on": "08:00", "off": "17:00"},
                    "3": {"on": "08:00", "off": "20:00"},
                    "4": {"on": "08:00", "off": "17:00"}
                }
            },
            "time_control": {
                "1": ["10:00", "12:00", "14:00", "16:00"],
                "2": ["10:00", "12:00", "14:00", "16:00"],
                "3": ["10:00", "12:00", "14:00", "16:00"],
                "4": ["10:00", "12:00", "14:00", "16:00"]
            },
            "sensor_settings": {
                "1": {
                    "target": 150, "start_time": "09:00", "end_time": "17:30",
                    "refresh_sec": 150, "nf_value": 68, "dtm": 1.15,
                    "data_table": "", "modules": ""
                },
                "2": {
                    "target": 150, "start_time": "09:00", "end_time": "17:30",
                    "refresh_sec": 300, "nf_value": 68, "dtm": 1.15,
                    "data_table": "", "modules": ""
                },
                "3": {
                    "target": 150, "start_time": "09:00", "end_time": "17:30",
                    "refresh_sec": 300, "nf_value": 68, "dtm": 1.15,
                    "data_table": "", "modules": ""
                },
                "4": {
                    "target": 150, "start_time": "09:00", "end_time": "17:30",
                    "refresh_sec": 300, "nf_value": 68, "dtm": 1.15,
                    "data_table": "", "modules": ""
                }
            }
        }

        save_config(default_config)

    try:
        with open(SETTING_PATH, "r", encoding="utf-8") as f:
            _cached_config = json.load(f)
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
