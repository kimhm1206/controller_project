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

# lgpio 핸들
gpio_handle = None

# Raspberry Pi 전용 GPIO 핀 매핑 (BCM 기준)
RASPBERRY_PI_PINS = {
    "ch0": 26,  # BCM
    "ch1": 20,
    "ch2": 21,
}


def set_relay_state(state):
    global relay_state
    relay_state = state


def is_raspberry_pi():
    return platform.system() == "Linux"


def setup_rpi_gpio():
    global gpio_handle
    import lgpio

    if gpio_handle is not None:
        return

    gpio_handle = lgpio.gpiochip_open(0)
    print("🔧 [lgpio] 설정 시작 (gpiochip 0)")
    for ch, pin in RASPBERRY_PI_PINS.items():
        lgpio.gpio_claim_output(gpio_handle, pin)
        lgpio.gpio_write(gpio_handle, pin, 1)
        print(f"🔌 [lgpio] {ch} → 핀 {pin} 초기화 완료 (OFF)")


def gpio_control(ch, mode):
    import lgpio
    pin = RASPBERRY_PI_PINS.get(ch)
    if pin is None:
        print(f"❌ [lgpio] Unknown channel: {ch} (정의되지 않은 핀)")
        return
    if gpio_handle is None:
        print("❌ [lgpio] GPIO 핸들 미초기화")
        return

    value = 0 if mode == "on" else 1
    lgpio.gpio_write(gpio_handle, pin, value)
    print(f"➡️ [lgpio] {ch} 핀({pin}) → {'ON' if value == 0 else 'OFF'}")


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
                    port = relay_state[category][ch]["port"]
                    gpio_ch = None
                    for k, v in RASPBERRY_PI_PINS.items():
                        if int(k.replace("ch", "")) == port:
                            gpio_ch = k
                            break
                    if gpio_ch is None:
                        print(f"❌ [GPIO] 포트 {port}에 해당하는 GPIO 핀 매핑 실패")
                        continue
                    gpio_control(gpio_ch, mode)

            for category in relay_state:
                for ch_info in relay_state[category].values():
                    if ch_info["state"]:
                        new_state |= (1 << ch_info["port"])

            print(f"[lgpio] Raspberry Pi 릴레이 제어 완료 → 상태값: {bin(new_state)}")
        else:
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
            if port in target_ports:
                ch_info["state"] = 0  # 상태 OFF
                # ✅ 여기선 OFF니까 비트 안 켬
            else:
                if ch_info["state"]:  # 다른 건 기존대로 유지
                    new_state |= (1 << port)

    if test_mode:
        print(f"[TEST] 🚨 {mode} 긴급 OFF → 상태값: {bin(new_state)}")
        send_state_data(relay_state)
        return

    if is_raspberry_pi():
        setup_rpi_gpio()
        for ch, ch_info in relay_state.get(mode, {}).items():
            port = ch_info["port"]
            gpio_ch = None
            for k, v in RASPBERRY_PI_PINS.items():
                if int(k.replace("ch", "")) == port:
                    gpio_ch = k
                    break
            if gpio_ch is None:
                print(f"❌ [GPIO] 포트 {port} → ch 매핑 실패 (긴급 OFF)")
                continue
            gpio_control(gpio_ch, "off")

        # 비트 재계산 (OFF는 포함 안 함)
        new_state = 0
        for category in relay_state:
            for ch_info in relay_state[category].values():
                if ch_info["state"]:
                    new_state |= (1 << ch_info["port"])

        print(f"[lgpio] 🚨 Raspberry Pi 긴급 OFF 완료 → 상태값: {bin(new_state)}")
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
