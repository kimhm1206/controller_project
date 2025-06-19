# test_run_both.py

import asyncio
from sensor.monitor import run_sensor_cycle

async def main():

    await run_sensor_cycle()

if __name__ == "__main__":
    asyncio.run(main())
