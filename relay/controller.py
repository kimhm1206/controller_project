import socket
import asyncio 
import threading
import platform
import copy
from config.loader import get_config
from websocket.wsnotify import send_data

DEFAULT_TCP_IP = "192.168.5.138"
DEFAULT_TCP_PORT = 502

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


def get_relay_output_mode(config):
    mode = config.get("relay_output_mode", "tcp")
    if mode not in {"tcp", "gpio"}:
        return "tcp"
    return mode


def get_tcp_endpoint(config):
    tcp_relay = config.get("tcp_relay", {})
    if not isinstance(tcp_relay, dict):
        tcp_relay = {}

    host = str(tcp_relay.get("address") or DEFAULT_TCP_IP)
    try:
        port = int(tcp_relay.get("port", DEFAULT_TCP_PORT))
    except (TypeError, ValueError):
        port = DEFAULT_TCP_PORT
    return host, port


def get_gpio_channel_for_port(port):
    for ch, _pin in RASPBERRY_PI_PINS.items():
        if int(ch.replace("ch", "")) == int(port):
            return ch
    return None


def calculate_state_bits(state):
    new_state = 0
    for category in state:
        for ch_info in state[category].values():
            if ch_info["state"]:
                new_state |= (1 << ch_info["port"])
    return new_state


def build_tcp_packet(relay_size, state_bits):
    return bytearray([
        0, 0, 0, 0, 0, 8,
        1, 15,
        0, 8,
        0, relay_size, 1, state_bits
    ])


def send_tcp_state(config, relay_size, state_bits):
    host, port = get_tcp_endpoint(config)
    packet = build_tcp_packet(relay_size, state_bits)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(3)
        s.connect((host, port))
        s.sendall(packet)
    print(f"[TCP] 릴레이 제어 완료 → {host}:{port} / 상태값: {bin(state_bits)}")


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
        return False
    if gpio_handle is None:
        print("❌ [lgpio] GPIO 핸들 미초기화")
        return False

    value = 0 if mode == "on" else 1
    lgpio.gpio_write(gpio_handle, pin, value)
    print(f"➡️ [lgpio] {ch} 핀({pin}) → {'ON' if value == 0 else 'OFF'}")
    return True


def apply_gpio_changes(port_dict, desired_state):
    if not is_raspberry_pi():
        raise RuntimeError("GPIO 릴레이 출력은 Linux/Raspberry Pi 환경에서만 사용할 수 있습니다.")

    setup_rpi_gpio()
    for category, changes in port_dict.items():
        for ch, mode in changes.items():
            port = desired_state[category][ch]["port"]
            gpio_ch = get_gpio_channel_for_port(port)
            if gpio_ch is None:
                raise ValueError(f"GPIO 포트 매핑 실패: port={port}")
            if not gpio_control(gpio_ch, mode):
                raise RuntimeError(f"GPIO 제어 실패: {gpio_ch}")


def apply_gpio_shutdown(mode, current_state):
    if not is_raspberry_pi():
        raise RuntimeError("GPIO 릴레이 출력은 Linux/Raspberry Pi 환경에서만 사용할 수 있습니다.")

    setup_rpi_gpio()

    if mode == "led":
        # 기존 GPIO LED 긴급 OFF 동작은 전체 GPIO OFF로 유지한다.
        print("💡 [lgpio] LED 모드 → 모든 GPIO 핀 OFF 처리")
        for ch in RASPBERRY_PI_PINS:
            gpio_control(ch, "off")
        return

    for ch, ch_info in current_state.get(mode, {}).items():
        port = ch_info["port"]
        gpio_ch = get_gpio_channel_for_port(port)
        if gpio_ch is None:
            raise ValueError(f"GPIO 포트 매핑 실패: port={port}")
        if not gpio_control(gpio_ch, "off"):
            raise RuntimeError(f"GPIO 긴급 OFF 실패: {gpio_ch}")


def tcpcontrol_multi(port_dict: dict, test_mode: bool = False) -> int:
    global relay_state
    config = get_config()
    relay_type = config.get("relayboard_type", "4port")
    relay_size = 4 if relay_type == "4port" else 8
    relay_output_mode = get_relay_output_mode(config)

    with relay_lock:
        if relay_state is None:
            print("❌ 릴레이 상태가 초기화되지 않았습니다.")
            return None

        desired_state = copy.deepcopy(relay_state)

        for category, changes in port_dict.items():
            if category not in desired_state:
                raise ValueError(f"Unknown category: {category}")
            for ch, mode in changes.items():
                if ch not in desired_state[category]:
                    raise ValueError(f"Unknown channel {ch} in {category}")
                if mode not in ["on", "off"]:
                    raise ValueError(f"Invalid mode '{mode}' for {category} {ch}")
                desired_state[category][ch]["state"] = 1 if mode == "on" else 0

        new_state = calculate_state_bits(desired_state)

        if test_mode:
            relay_state = desired_state
            print(f"[TEST] 릴레이 제어 요청: {port_dict}")
            print(f"[TEST] 출력 방식: {relay_output_mode} / 최종 상태값: {bin(new_state)}")
            send_state_data(relay_state)
            return new_state

        try:
            if relay_output_mode == "gpio":
                apply_gpio_changes(port_dict, desired_state)
                print(f"[lgpio] Raspberry Pi 릴레이 제어 완료 → 상태값: {bin(new_state)}")
            else:
                send_tcp_state(config, relay_size, new_state)
        except Exception as e:
            print(f"[RELAY ERROR] 제어 실패: {e}")
            send_state_data(relay_state)
            return None

        relay_state = desired_state
        send_state_data(relay_state)
        return new_state


def emergency_shutdown(mode: str, test_mode: bool = False):
    global relay_state
    config = get_config()
    relay_type = config.get("relayboard_type", "4port")
    relay_size = 4 if relay_type == "4port" else 8
    relay_output_mode = get_relay_output_mode(config)

    with relay_lock:
        if relay_state is None:
            print("❌ 릴레이 상태가 초기화되지 않았습니다.")
            return None

        if mode not in relay_state:
            raise ValueError(f"Unknown emergency mode: {mode}")

        desired_state = copy.deepcopy(relay_state)

        # OFF할 포트들 추출
        target_ports = [
            ch_info["port"] for ch_info in desired_state.get(mode, {}).values()
        ]

        for category in desired_state:
            for _ch, ch_info in desired_state[category].items():
                if ch_info["port"] in target_ports:
                    ch_info["state"] = 0

        new_state = calculate_state_bits(desired_state)

        if test_mode:
            relay_state = desired_state
            print(f"[TEST] 🚨 {mode} 긴급 OFF → 상태값: {bin(new_state)}")
            send_state_data(relay_state)
            return new_state

        try:
            if relay_output_mode == "gpio":
                apply_gpio_shutdown(mode, relay_state)
                print(f"[lgpio] 🚨 Raspberry Pi 긴급 OFF 완료 → 상태값: {bin(new_state)}")
            else:
                send_tcp_state(config, relay_size, new_state)
                print(f"[TCP] 🚨 {mode} 긴급 OFF 완료 → 상태값: {bin(new_state)}")
        except Exception as e:
            print(f"[RELAY ERROR] 긴급 OFF 실패: {e}")
            send_state_data(relay_state)
            return None

        relay_state = desired_state
        send_state_data(relay_state)
        return new_state



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
