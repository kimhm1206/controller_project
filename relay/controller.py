import socket
import asyncio 
import threading
import platform
from config.loader import get_config
from websocket.wsnotify import send_data

TCP_IP = "192.168.5.138"
TCP_PORT = 502

# 전역 릴레이 상태 및 락
relay_state = None
relay_lock = threading.Lock()

def set_relay_state(state):
    global relay_state
    relay_state = state

# Raspberry Pi 전용 GPIO 핀 매핑 (BCM 기준)
RASPBERRY_PI_PINS = {
    "ch1": 26,
    "ch2": 20,
    "ch3": 21,
}

def is_raspberry_pi():
    return platform.system() == "Linux"

def setup_rpi_gpio():
    import RPi.GPIO as GPIO
    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BCM)
    for pin in RASPBERRY_PI_PINS.values():
        GPIO.setup(pin, GPIO.OUT)
        GPIO.output(pin, GPIO.HIGH)  # 기본 OFF (LOW가 ON이기 때문)

def gpio_control(ch, mode):
    import RPi.GPIO as GPIO
    pin = RASPBERRY_PI_PINS.get(ch)
    if pin is None:
        raise ValueError(f"Unknown channel: {ch}")
    GPIO.output(pin, GPIO.LOW if mode == "on" else GPIO.HIGH)

def tcpcontrol_multi(port_dict: dict, test_mode: bool = False) -> int:
    global relay_state
    config = get_config()
    relay_type = config.get("relayboard_type", "4port")
    relay_size = 4 if relay_type == "4port" else 8

    with relay_lock:
        for category, changes in port_dict.items():
            if category not in relay_state:
                raise ValueError(f"Unknown category: {category}")
            for ch, mode in changes.items():
                if ch not in relay_state[category]:
                    raise ValueError(f"Unknown channel {ch} in {category}")
                if mode not in ["on", "off"]:
                    raise ValueError(f"Invalid mode '{mode}' for {category} {ch}")
                relay_state[category][ch]["state"] = 1 if mode == "on" else 0

        new_state = 0

        if is_raspberry_pi():
            setup_rpi_gpio()
            for category, changes in port_dict.items():
                for ch, mode in changes.items():
                    gpio_control(ch, mode)

            # GPIO에서도 상태 비트 계산 동일하게 적용
            for category in relay_state:
                for ch_info in relay_state[category].values():
                    if ch_info["state"]:
                        new_state |= (1 << ch_info["port"])

            print(f"[GPIO] Raspberry Pi 릴레이 제어 완료 → 상태값: {bin(new_state)}")
        else:
            # TCP용 릴레이 비트 계산
            for category in relay_state:
                for ch_info in relay_state[category].values():
                    if ch_info["state"]:
                        new_state |= (1 << ch_info["port"])

            packet = bytearray([
                0, 0, 0, 0, 0, 8,
                1, 15,
                0, 8,
                0, relay_size, 1, new_state
            ])

            # TCP 상태 동기화
            for category in relay_state:
                for ch_name, ch_info in relay_state[category].items():
                    port = ch_info["port"]
                    is_on = (new_state >> port) & 1
                    relay_state[category][ch_name]["state"] = is_on

            if test_mode:
                print(f"[TEST] TCP 멀티포트 제어 요청: {port_dict}")
                print(f"[TEST] 최종 상태값 (bit): {bin(new_state)}")
                send_state_data(relay_state)
                return new_state

            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.connect((TCP_IP, TCP_PORT))
                    s.sendall(packet)
                    print(f"[TCP] 멀티포트 제어 완료 → 상태값: {bin(new_state)}")
            except Exception as e:
                print(f"[TCP ERROR] 제어 실패: {e}")

        send_state_data(relay_state)
        return

def emergency_shutdown(mode: str, test_mode: bool = False):
    global relay_state
    config = get_config()
    relay_type = config.get("relayboard_type", "4port")
    relay_size = 4 if relay_type == "4port" else 8

    target_ports = [
        ch_info["port"] for ch_info in relay_state.get(mode, {}).values()
    ]

    new_state = 0
    for category in relay_state:
        for ch, ch_info in relay_state[category].items():
            port = ch_info["port"]
            if ch_info["state"] and port not in target_ports:
                new_state |= (1 << port)
            else:
                ch_info["state"] = 0

    if test_mode:
        print(f"[TEST] 🚨 {mode} 긴급 OFF → 상태값: {bin(new_state)}")
        send_state_data(relay_state)
        return

    if is_raspberry_pi():
        setup_rpi_gpio()
        for ch in relay_state.get(mode, {}):
            gpio_control(ch, "off")

        # 상태 비트 계산
        for category in relay_state:
            for ch_info in relay_state[category].values():
                if ch_info["state"]:
                    new_state |= (1 << ch_info["port"])

        print(f"[GPIO] 🚨 Raspberry Pi 긴급 OFF 완료 → 상태값: {bin(new_state)}")
    else:
        packet = bytearray([
            0, 0, 0, 0, 0, 8,
            1, 15,
            0, 8,
            0, relay_size, 1, new_state
        ])
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect((TCP_IP, TCP_PORT))
                s.sendall(packet)
            print(f"[TCP] 🚨 {mode} 긴급 OFF 완료 → 상태값: {bin(new_state)}")
        except Exception as e:
            print(f"[TCP ERROR] 긴급 OFF 실패: {e}")

    send_state_data(relay_state)
    return

def send_state_data(relay_state=None):
    if relay_state is None:
        relay_state = {}
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(send_data(relay_state))
        else:
            loop.run_until_complete(send_data(relay_state))
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(send_data(relay_state))
        else:
            loop.run_until_complete(send_data(relay_state))
