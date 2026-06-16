import copy
import json
import os
import platform
import shutil
from contextlib import contextmanager
from datetime import datetime

try:
    import fcntl
except ImportError:
    fcntl = None

try:
    import msvcrt
except ImportError:
    msvcrt = None


# 📁 경로 정의 (C:\Users\{user}\Documents\telofarm\telofarmer\...)
if platform.system() == "Linux":
    USER_DOCS = "/home/telofarm/Documents/telofarm/telofarmer"
else:
    USER_DOCS = os.path.join(os.path.expanduser("~"), "Documents", "telofarm", "telofarmer")

DATA_DIR = os.path.join(USER_DOCS, "data")
LOG_DIR = os.path.join(USER_DOCS, "log")
SYSLOG_DIR = os.path.join(USER_DOCS, "systemlog")

# 🔧 setting.json 경로
SETTING_PATH = os.path.join(DATA_DIR, "setting.json")
SETTING_LOCK_PATH = f"{SETTING_PATH}.lock"
SETTING_BACKUP_PATH = f"{SETTING_PATH}.bak"
DEFAULT_SETTING_TEMPLATE_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "setting.json")
)

# 📂 폴더 생성 (최초 실행 시)
for path in [DATA_DIR, LOG_DIR, SYSLOG_DIR]:
    if not os.path.exists(path):
        os.makedirs(path)
        print(f"📂 폴더 생성됨: {path}")


BASE_DEFAULT_CONFIG = {
    "master": {
        "relay_control_type": "tcp",
        "external_sensor_enabled": True,
        "extra_control_enabled": False,
        "site_ids": [],
    },
    "relayboard_type": "8port",
    "relay_output_mode": "tcp",
    "tcp_relay": {
        "address": "192.168.5.138",
        "port": 502,
    },
    "sensor_ports": "com1",
    "test_mode": True,
    "irrigation_mix": False,
    "irrigation_mix_port": 0,
    "area_control": False,
    "area_infor": {
        "fan": 0,
        "open": 1,
        "close": 2,
        "address": "192.168.5.139",
        "port": 502,
    },
    "irrigation_channels": {
        "1": True,
        "2": False,
        "3": False,
        "4": False,
    },
    "led_channels": {
        "1": False,
        "2": False,
        "3": False,
        "4": False,
    },
    "irrigationpanel": {
        "control_mode": {
            "1": "timer",
            "2": "timer",
            "3": "timer",
            "4": "timer",
        },
        "relay_port_mapping": {
            "1": 0,
            "2": 1,
            "3": 2,
            "4": 3,
        },
        "irrigation_time": {
            "1": 100,
            "2": 100,
            "3": 100,
            "4": 100,
        },
    },
    "ledpanel": {
        "led_port_mapping": {
            "1": 4,
            "2": 5,
            "3": 6,
            "4": 7,
        },
        "led_time": {
            "1": {"on": "08:00", "off": "17:00"},
            "2": {"on": "08:00", "off": "17:00"},
            "3": {"on": "08:00", "off": "20:00"},
            "4": {"on": "08:00", "off": "17:00"},
        },
    },
    "time_control": {
        "1": ["10:00", "12:00", "14:00", "16:00"],
        "2": ["10:00", "12:00", "14:00", "16:00"],
        "3": ["10:00", "12:00", "14:00", "16:00"],
        "4": ["10:00", "12:00", "14:00", "16:00"],
    },
    "sensor_settings": {
        "1": {
            "target": 150,
            "start_time": "09:00",
            "end_time": "17:30",
            "refresh_sec": 150,
            "nf_value": 68,
            "dtm": 1.15,
            "data_table": "",
            "modules": "",
        },
        "2": {
            "target": 150,
            "start_time": "09:00",
            "end_time": "17:30",
            "refresh_sec": 300,
            "nf_value": 68,
            "dtm": 1.15,
            "data_table": "",
            "modules": "",
        },
        "3": {
            "target": 150,
            "start_time": "09:00",
            "end_time": "17:30",
            "refresh_sec": 300,
            "nf_value": 68,
            "dtm": 1.15,
            "data_table": "",
            "modules": "",
        },
        "4": {
            "target": 150,
            "start_time": "09:00",
            "end_time": "17:30",
            "refresh_sec": 300,
            "nf_value": 68,
            "dtm": 1.15,
            "data_table": "",
            "modules": "",
        },
    },
}

# 📦 내부 캐시 설정값
_cached_config = {}


def _legacy_relay_output_mode():
    return "gpio" if platform.system() == "Linux" else "tcp"


def _load_default_template():
    try:
        with open(DEFAULT_SETTING_TEMPLATE_PATH, "r", encoding="utf-8") as f:
            template = json.load(f)
        if isinstance(template, dict):
            return _deep_merge(BASE_DEFAULT_CONFIG, template)
    except Exception as exc:
        print(f"⚠ 기본 설정 템플릿 로드 실패: {DEFAULT_SETTING_TEMPLATE_PATH} / {exc}")

    return copy.deepcopy(BASE_DEFAULT_CONFIG)


def _default_config():
    config = _load_default_template()
    master = config.get("master") if isinstance(config.get("master"), dict) else {}
    relay_mode = master.get("relay_control_type") or config.get("relay_output_mode")
    if relay_mode not in {"tcp", "gpio"}:
        relay_mode = _legacy_relay_output_mode()
    config.setdefault("master", {})["relay_control_type"] = relay_mode
    config["relay_output_mode"] = relay_mode
    return config


def _deep_merge(default, override):
    result = copy.deepcopy(default)
    if not isinstance(override, dict):
        return result

    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _coerce_site_ids(value):
    if isinstance(value, list):
        raw_items = value
    elif isinstance(value, str):
        raw_items = value.replace(",", "\n").splitlines()
    else:
        raw_items = []

    site_ids = []
    for item in raw_items:
        site_id = str(item).strip()
        if site_id and site_id not in site_ids:
            site_ids.append(site_id)
    return site_ids


def normalize_config(config):
    if not isinstance(config, dict):
        raise ValueError("setting.json root must be an object")

    normalized = _deep_merge(_default_config(), config)

    raw_master = config.get("master") if isinstance(config.get("master"), dict) else {}
    master = normalized.get("master")
    if not isinstance(master, dict):
        master = {}

    relay_control_type = raw_master.get("relay_control_type")
    if relay_control_type not in {"tcp", "gpio"}:
        relay_control_type = normalized.get("relay_output_mode")
    if relay_control_type not in {"tcp", "gpio"}:
        relay_control_type = _legacy_relay_output_mode()

    master["relay_control_type"] = relay_control_type
    master["external_sensor_enabled"] = bool(raw_master.get("external_sensor_enabled", master.get("external_sensor_enabled", True)))
    master["extra_control_enabled"] = bool(raw_master.get(
        "extra_control_enabled",
        bool(normalized.get("irrigation_mix")) or bool(normalized.get("area_control")),
    ))
    master["site_ids"] = _coerce_site_ids(raw_master.get("site_ids", master.get("site_ids", [])))
    normalized["master"] = master
    normalized["relay_output_mode"] = relay_control_type

    if normalized.get("relayboard_type") not in {"4port", "8port"}:
        normalized["relayboard_type"] = "8port"

    tcp_relay = normalized.get("tcp_relay")
    if not isinstance(tcp_relay, dict):
        tcp_relay = {}

    tcp_relay["address"] = str(tcp_relay.get("address") or "192.168.5.138")
    try:
        tcp_relay["port"] = int(tcp_relay.get("port", 502))
    except (TypeError, ValueError):
        tcp_relay["port"] = 502
    normalized["tcp_relay"] = tcp_relay

    return normalized


@contextmanager
def _setting_file_lock():
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(SETTING_LOCK_PATH, "a+") as lock_file:
        if fcntl:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        elif msvcrt:
            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)

        try:
            yield
        finally:
            if fcntl:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            elif msvcrt:
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)


def _write_config_unlocked(config):
    os.makedirs(DATA_DIR, exist_ok=True)

    if os.path.exists(SETTING_PATH):
        shutil.copy2(SETTING_PATH, SETTING_BACKUP_PATH)

    temp_path = f"{SETTING_PATH}.tmp"
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
        f.write("\n")

    os.replace(temp_path, SETTING_PATH)


def load_config():
    """setting.json을 읽어서 파싱된 dict 반환"""
    global _cached_config

    with _setting_file_lock():
        if not os.path.exists(SETTING_PATH):
            print(f"⚠️ 설정파일 없음 → 새로 생성: {SETTING_PATH}")
            _cached_config = _default_config()
            _write_config_unlocked(_cached_config)
            return _cached_config

        try:
            with open(SETTING_PATH, "r", encoding="utf-8") as f:
                loaded_config = json.load(f)
            normalized = normalize_config(loaded_config)
        except Exception as e:
            invalid_path = f"{SETTING_PATH}.invalid_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            try:
                shutil.copy2(SETTING_PATH, invalid_path)
            except Exception:
                pass
            print(f"❌ 설정 로드 실패: {e} → 기본 설정으로 복구")
            normalized = _default_config()

        if normalized != _cached_config:
            _cached_config = normalized

        # 누락된 신규 기본값이 있으면 파일에도 반영한다.
        needs_write = True if "loaded_config" not in locals() else normalized != loaded_config
        if needs_write:
            _write_config_unlocked(normalized)

    return _cached_config


def get_config():
    """캐싱된 설정값 반환"""
    if not _cached_config:
        return load_config()
    return _cached_config


def reload_config():
    """설정 재로딩"""
    print("🔁 setting.json 리로드됨")
    return load_config()


def save_config(config):
    """setting.json을 안전하게 덮어쓰기"""
    global _cached_config

    if config is None:
        print("❗ Error: 저장할 설정값이 없습니다.")
        return None

    try:
        normalized = normalize_config(config)
        with _setting_file_lock():
            _write_config_unlocked(normalized)
        print(f"💾 설정 저장됨: {SETTING_PATH}")
        _cached_config = normalized
        return normalized
    except Exception as e:
        print(f"❌ 설정 저장 실패: {e}")
        return None
