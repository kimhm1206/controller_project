import asyncio

from datetime import datetime, timedelta
from sensor.token import get_token
import aiohttp

token_cache = None  # 캐시된 토큰

async def fetch_raw_sensor_data(setting, start_time: datetime, end_time: datetime):
    global token_cache

    site = setting.get("data_table")
    modules = setting.get("modules", "").splitlines()
    prefix = "LW140C5BFFFF"

    # UTC로 변환
    start_utc = start_time - timedelta(hours=9)
    end_utc = end_time - timedelta(hours=9)

    begin_str = start_utc.strftime("%Y-%m-%dT%H:%M:%S") + "%2B00:00"
    end_str = end_utc.strftime("%Y-%m-%dT%H:%M:%S") + "%2B00:00"

    # ✅ 00시 수집 시작이면 토큰 갱신
    if start_time.hour == 0 and start_time.minute == 0:
        token_cache = get_token()
    elif not token_cache:
        token_cache = get_token()

    headers = {
        "Cookie": token_cache
    }
    tasks = []
    for module in modules:
        module = module.strip()
        full_module_id = prefix + module

        url = f"https://datadam.telofarm.com/api/data/sites/{site}/devices/{full_module_id}?begin={begin_str}&end={end_str}"
        tasks.append(fetch_single_module(full_module_id, url, headers))

    results = await asyncio.gather(*tasks)
    return {mod: data for mod, data in results if data is not None}


async def fetch_single_module(module, url, headers):
    try:
        async with aiohttp.ClientSession(headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if isinstance(data, list):
                        if len(data) == 1 and isinstance(data[0], dict):
                            data = data[0]  # ✅ dict 꺼냄
                        else:
                            print(f"⚠️ 모듈 {module}: 응답이 리스트 형식 (빈 데이터 처리)")
                            return module, None

                    if data.get("total_count") != "0":
                        return module, data
                    else:
                        print(f"⚠️ 모듈 {module}: total_count = 0 (데이터 없음)")
                else:
                    print(f"❌ 모듈 {module} 요청 실패 - 상태코드 {resp.status}")
    except Exception as e:
        print(f"❌ 모듈 {module} 요청 중 예외 발생: {e}")
    return module, None


