import pandas as pd
from datetime import datetime, timedelta
import numpy as np
from scipy.signal import savgol_filter
import serial

def apply_ema_filter(series: pd.Series, alpha: float = 0.1) -> pd.Series:
    ema = []
    for i, val in enumerate(series):
        if i == 0:
            ema.append(val)
        else:
            ema.append(alpha * val + (1 - alpha) * ema[-1])
    return pd.Series(ema, index=series.index)

def process_raw_sensor_data(raw_module_data: dict, setting) -> pd.DataFrame:
    svalue_df_list = []
    for module_id, data in raw_module_data.items():
        if not data or "entities" not in data:
            continue

        entities = data["entities"]
        for key, value in entities.items():
            if "data" not in value:
                continue

            channel = key.split("_")[-1]
            module = value["parent_id"]

            try:
                suba = value["data"]["SubA"]["metrics"]
                subb = value["data"]["SubB"]["metrics"]
                dac = value["data"]["DAC"]["metrics"]
            except KeyError:
                continue

            module_name = module.split("LW140C5BFFFF")[-1]
            prefix = f"{module_name}_ch{channel}"

            df = pd.DataFrame({
                "Time": [d["ts"] for d in dac],
                f"{prefix}_SubA": [int(d["number"]) for d in suba],
                f"{prefix}_SubB": [int(d["number"]) for d in subb],
                f"{prefix}_DAC":  [int(d["number"]) for d in dac],
            })

            df[f"{prefix}_SubA"] = apply_ema_filter(df[f"{prefix}_SubA"])
            df[f"{prefix}_SubB"] = apply_ema_filter(df[f"{prefix}_SubB"])

            # 시간 보정
            df["Time"] = pd.to_datetime(df["Time"]) + timedelta(hours=9)
            df["Time"] = df["Time"].dt.floor("15min")
            df.set_index("Time", inplace=True)
            df.index = df.index.tz_localize(None)
            df = df.loc[~df.index.duplicated(keep='last')]

            # 🔥 현재 시각 기준 필터링 (현재 floor된 시각은 제외, 그 이전까지만)
            now_floor = pd.Timestamp.now().floor("15min")
            df = df[df.index < now_floor]


            svalue_series = sapflow_calculate(df, setting)
            if svalue_series is not None and not svalue_series.empty:
                # ✅ 채널별 baseline 보정 수행
                corrected_series = compute_corrected_svalue_per_channel(svalue_series)
                svalue_df_list.append(corrected_series.to_frame(name=prefix))


    if not svalue_df_list:
        print("❌ 유효한 sapflow 시리즈 없음")
        return pd.DataFrame(columns=["Time", "svalue"])

    # ✅ 채널별 보정된 시리즈 병합 후 대표 시그널 계산
    merged_df = pd.concat(svalue_df_list, axis=1).sort_index()
    filtered_df = filter_sapflow_data(merged_df)

    return filtered_df

def sapflow_calculate(df: pd.DataFrame, setting: dict) -> pd.Series:
    a_const = 3.53523
    b_const = 1.20514
    volt = 2000
    dtm_config = 5

    try:
        suba_col = [col for col in df.columns if "_SubA" in col][0]
        subb_col = [col for col in df.columns if "_SubB" in col][0]
        dac_col  = [col for col in df.columns if "_DAC"  in col][0]
    except IndexError:
        return pd.Series(dtype=float)

    T1 = df[dac_col] + df[suba_col] / 51
    T2 = df[dac_col] + df[subb_col] / 51

    # 둘 중 하나가 0이면 둘 다 0 처리
    mask = (T1 == 0) | (T2 == 0)
    T1[mask] = 0
    T2[mask] = 0

    # 저항값 변환
    T1_R = (100 * T1) / (volt - T1)
    T2_R = (100 * T2) / (volt - T2)

    # ΔT 계산
    dT = (T2_R - T1_R).clip(lower=0)

    try:
        dtm_range = df.between_time("00:00", "04:00")
        T1_dtm = T1_R[dtm_range.index]
        T2_dtm = T2_R[dtm_range.index]
        dT_dtm = (T2_dtm - T1_dtm).clip(lower=0)
        dtm = dT_dtm.max() if not dT_dtm.empty else 2  # fallback
    except Exception as e:
        print("⚠️ dtm 계산 오류:", e)
        dtm = 2
        
    # sap 계산
    with np.errstate(divide='ignore', invalid='ignore'):
        svalue = a_const * ((dtm - dT) / dT) ** b_const

    # 후처리
    svalue[np.isinf(svalue)] = 0
    svalue[np.isnan(svalue)] = 0
    svalue[np.iscomplex(svalue)] = 0
    svalue = np.real(svalue)

    svalue = pd.Series(svalue, index=df.index)
            
    # svalue = svalue.ffill().fillna(0)

    return svalue

def filter_sapflow_data(merged_df: pd.DataFrame) -> pd.DataFrame:
    if merged_df.empty:
        print("❗ merged_df가 비어 있습니다.")
        return pd.DataFrame(columns=["Time", "svalue"])

    nansrow = []
    svalue_list = []

    for i in range(len(merged_df)):
        row = merged_df.iloc[i]
        values = row.dropna().values

        if len(values) == 0:
            nansrow.append(True)
            svalue_list.append(None)
            continue

        median_val = pd.Series(values).median()
        upper = median_val * 1.6
        lower = median_val * 0.4

        filtered = [v for v in values if lower <= v <= upper]  # 0도 포함 가능하게

        if len(filtered) == 0:
            nansrow.append(True)
            svalue_list.append(None)
        else:
            nansrow.append(False)
            svalue_list.append(sum(filtered) / len(filtered))

    df = pd.DataFrame({
        "Time": merged_df.index,
        "svalue": svalue_list
    })

    df = df[~pd.Series(nansrow)]
    df = df.reset_index(drop=True)
    df = df.sort_values("Time").reset_index(drop=True)  # ✅ 시간 정렬
    return df


def calculate_sumx(df: pd.DataFrame, setting: dict, start, end, last_state=None) -> pd.DataFrame:
    df = df.sort_values("Time").reset_index(drop=True)

    goal = setting["target"]
    nf = setting["nf_value"]

    # 🔹 상태 초기화
    if last_state is not None:
        # concat용 row 만들기
        base = pd.DataFrame({
            "Time": [last_state["Time"]],
            "svalue": [last_state["svalue"]],
            "sumx": [last_state["sumx"]],
            "dailysumx": [last_state["dailysumx"]],
            "action": [last_state.get("action", "이전")],
            "goal": [last_state["goal"]],
        })

        df = pd.concat([base, df], ignore_index=True)
        df = df.sort_values("Time").reset_index(drop=True)  # ✅ 여기 추가
        current_sumx = last_state["sumx"]
        current_dailysum = last_state["dailysumx"]
    else:
        current_sumx = 0
        current_dailysum = 0

    sv = df["svalue"].values
    times = df["Time"].dt.time.values

    sumx_list = [current_sumx]
    dailysum_list = [current_dailysum]
    action_list = ["이전상태"]
    goal_list = [goal]

    for i in range(1, len(sv)):
        t = times[i]
        in_range = start <= t <= end

        if in_range:
            delta = (sv[i - 1] + sv[i]) / 2 * nf

            if current_sumx + delta >= goal:
                overflow = (current_sumx + delta) - goal
                current_sumx = overflow
                action = "관수"
            else:
                current_sumx += delta
                action = "온라인"

            current_dailysum += delta
        else:
            current_dailysum = 0
            current_sumx = 0
            action = "오프라인"

        sumx_list.append(current_sumx)
        dailysum_list.append(current_dailysum)
        action_list.append(action)
        goal_list.append(goal)

    df["sumx"] = sumx_list
    df["dailysumx"] = dailysum_list
    df["action"] = action_list
    df["goal"] = goal_list
    
    
    df = df.iloc[1:] if last_state is not None else df
    # df["action"] = df["action"].astype(str) + "_new"
    
    # 🔹 첫 줄은 last_state → 제거하고 반환
    return df


def compute_corrected_svalue_per_channel(series: pd.Series) -> pd.Series:
    """
    개별 채널의 svalue 시리즈를 받아 baseline 보정을 수행한 compensated 시리즈 반환
    - 새벽 00:00~06:00의 rolling 최소값 기준 anchor 설정
    - anchor 기반 보간 후 baseline 보정
    """
    series = series.copy()
    series.index = pd.to_datetime(series.index)

    # baseline anchor 추출
    baseline_points = []
    for date in pd.to_datetime(series.index.date).unique():
        date = pd.Timestamp(date)  # ✅ 타입 확실하게 맞춤
        day_start = date.replace(hour=0, minute=0)
        day_end = date.replace(hour=4, minute=0)

        segment = series[(series.index >= day_start) & (series.index <= day_end)]

        if not segment.empty:
            smooth = segment.rolling('20min').mean().dropna()
            if not smooth.empty:
                min_point = smooth.idxmin()
                baseline_points.append(min_point)

    if not baseline_points:
        print("⚠️ 개별 채널 baseline anchor 없음 → 보정 없이 반환")
        return series

    baseline_points = [series.index[0]] + baseline_points
    baseline_points = sorted(set(baseline_points))

    baseline_series = pd.Series(index=series.index, dtype=float)
    anchors = series.loc[baseline_points]
    baseline_series.update(anchors)
    baseline_series = baseline_series.interpolate(method='time')

    compensated = series - baseline_series
    min_val = compensated.min()
    if min_val <= 0:
        compensated += abs(min_val) + 0.01
        
    compensated.loc[compensated.index.time < datetime.strptime("04:00", "%H:%M").time()] = 0
    return compensated


#def apply_conditional_filter(df: pd.DataFrame) -> pd.DataFrame:
#     df = df.copy()
#     df = df.sort_values("Time").reset_index(drop=True)

#     # ▶ 수동관수 행 따로 보관 후 제거
#     manual_rows = df[df["action"].astype(str).str.contains("수동")]
#     target_df = df[~df.index.isin(manual_rows.index)].reset_index(drop=True)

#     svalue_filtered = []
#     ema_value = None

#     for i in range(len(target_df)):
#         action = str(target_df.at[i, "action"])
#         svalue = target_df.at[i, "svalue"]

#         # 필터 제외 조건
#         if "_new" not in action or pd.isna(svalue):
#             svalue_filtered.append(svalue)
#             continue

#         base_action = action.replace("_new", "")

#         # if base_action == "오프라인":
#         #     # ▶ median filter: 이전2 + 현재 + 이후2
#         #     window = []
#         #     for j in range(i - 2, i + 3):
#         #         if 0 <= j < len(target_df):
#         #             val = target_df.at[j, "svalue"]
#         #             if pd.notna(val):
#         #                 window.append(val)
#         #     filtered = sorted(window)[len(window) // 2] if window else svalue
#         # else:
#             # ▶ EMA filter (alpha = 2 / (5+1) = 0.33)
#         alpha = 0.4
        
#         if i > 0:
#             ema_value = svalue_filtered[-1]
#             ema_value = alpha * svalue + (1 - alpha) * ema_value
#         else:
#             ema_value = svalue
                
#         filtered = ema_value
        
            
#         svalue_filtered.append(filtered)

#     # ▶ 필터링 결과 적용 및 _new 제거
#     target_df["svalue"] = svalue_filtered
#     target_df["action"] = target_df["action"].str.replace("_new", "", regex=False)

#     # ▶ 수동관수 행 병합 및 정렬
#     final_df = pd.concat([target_df, manual_rows], ignore_index=True)
#     final_df = final_df.sort_values("Time").reset_index(drop=True)

#     return final_df

def read_weather_sensor_packet(port_name, baudrate=9600, timeout=2):
    try:
        ser = serial.Serial(port_name, baudrate=baudrate, timeout=timeout)
        
        # 보낼 명령 (MATLAB의 hex data + checksum)
        data = bytearray([
            0x02, ord('0'), 0x52, 0x58, 0x5A, 0x54, 0x48, 0x4C, 0x03
        ])
        
        # XOR 체크섬 추가
        xor_value = 0
        for b in data:
            xor_value ^= b
        data.append(xor_value)

        # 전송
        ser.write(data)

        # 응답 수신 (28바이트)
        response = ser.read(28)

        # 응답 길이 검증
        if len(response) < 28:
            print("⚠ 응답 길이가 짧습니다.")
            return None

        response_str = response.decode("utf-8", errors="ignore")
        print(f"📥 수신 문자열: {response_str}")

        # 값 추출 (MATLAB과 동일 위치)
        co2 = int(response_str[5:9])
        temp_val = int(response_str[11:15]) / 10
        temp = temp_val if response_str[10] == '1' else -temp_val
        humi = int(response_str[16:20]) / 10
        lux = int(response_str[21:26])

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return {
            "time": now,
            "CO2": co2,
            "Temp": temp,
            "Humi": humi,
            "Lux": lux
        }

    except Exception as e:
        print(f"❌ 센서 통신 오류: {e}")
        return None
    finally:
        if 'ser' in locals():
            ser.close()