# test_run_both.py

import asyncio
from datetime import datetime
from sensor.monitor import run_sensor_cycle, get_test_data

async def main():
    test_ch = "1"
    today_str = datetime.now().strftime("%Y-%m-%d")

    print("✅ get_test_data 실행 중...")
    await get_test_data({
        "ch": test_ch,
        "start": today_str,
        "end": today_str,
        "nf": 68,
        "goal": 220
    })

    print("✅ run_sensor_cycle 실행 중...")
    await run_sensor_cycle()

if __name__ == "__main__":
    asyncio.run(main())
