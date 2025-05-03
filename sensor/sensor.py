import pandas as pd
from datetime import datetime, timedelta
import numpy as np


def process_raw_sensor_data(raw_module_data: dict,setting) -> pd.DataFrame:
    svalue_df_list = []
    for module_id, data in raw_module_data.items():
        if not data or "entities" not in data:
            continue
        
        
        entities = data["entities"]
    
        for key, value in entities.items():
            if "data" not in value:
                
                continue

            channel = key.split("_")[-1]  # ex: LW140..._1 → "1"
            module = value["parent_id"]
            
            try:
                suba = value["data"]["SubA"]["metrics"]
                subb = value["data"]["SubB"]["metrics"]
                dac  = value["data"]["DAC"]["metrics"]
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

            now = datetime.now().replace(second=0, microsecond=0)
            # 1. 문자열을 datetime으로 변환 + UTC 제거
            df["Time"] = pd.to_datetime(df["Time"]) + timedelta(hours=9)
            df["Time"] = df["Time"].dt.tz_localize(None)  # ✅ 타임존 제거

            # 2. cutoff 기준 설정
            cutoff_time = datetime.now().replace(second=0, microsecond=0)
            cutoff_time = cutoff_time - timedelta(minutes=cutoff_time.minute % 15)

            # 3. 시간 필터링
            df = df[df["Time"] < cutoff_time]

            # ✅ 시간 정규화
            df["Time"] = df["Time"].dt.floor("15min")
            df.set_index("Time", inplace=True)
            df.index = df.index.tz_localize(None)
            
            # ✅ 중복 제거
            df = df.loc[~df.index.duplicated(keep='last')]
            
            svalue_series = sapflow_calculate(df, setting)

            
            if svalue_series is not None and not svalue_series.empty:
                svalue_df_list.append(svalue_series.to_frame(name=prefix))  # prefix는 모듈+채널명
                
    if not svalue_df_list:
        print("❌ 유효한 sapflow 시리즈 없음")
        return pd.DataFrame(columns=["Time", "svalue"])

    # 시간 기준으로 병합
    merged_df = pd.concat(svalue_df_list, axis=1)
    merged_df = merged_df.sort_index()  # ✅ 시간 오름차순 정렬

    result_df = filter_sapflow_data(merged_df)

    # result_df = baseline_compensation_df(result_df)

    return result_df

def sapflow_calculate(df: pd.DataFrame, setting: dict) -> pd.Series:
    a_const = 3.53523
    b_const = 1.20514
    volt = 2000
    dtm_config = float(setting.get("dtm", 1.15))

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

    # dtm 적용
    # dtm = max(dT.max(), dtm_config)
    dtm = dtm_config
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

        median_val = pd.Series([v for v in values if v != 0]).median()
        upper = median_val * 1.7
        lower = median_val * 0.3

        filtered = [v for v in values if lower < v < upper]

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

def apply_conditional_filter(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df = df.sort_values("Time").reset_index(drop=True)

    # ▶ 수동관수 행 따로 보관 후 제거
    manual_rows = df[df["action"].astype(str).str.contains("수동")]
    target_df = df[~df.index.isin(manual_rows.index)].reset_index(drop=True)

    svalue_filtered = []
    ema_value = None

    for i in range(len(target_df)):
        action = str(target_df.at[i, "action"])
        svalue = target_df.at[i, "svalue"]

        # 필터 제외 조건
        if "_new" not in action or pd.isna(svalue):
            svalue_filtered.append(svalue)
            continue

        base_action = action.replace("_new", "")

        # if base_action == "오프라인":
        #     # ▶ median filter: 이전2 + 현재 + 이후2
        #     window = []
        #     for j in range(i - 2, i + 3):
        #         if 0 <= j < len(target_df):
        #             val = target_df.at[j, "svalue"]
        #             if pd.notna(val):
        #                 window.append(val)
        #     filtered = sorted(window)[len(window) // 2] if window else svalue
        # else:
            # ▶ EMA filter (alpha = 2 / (5+1) = 0.33)
        alpha = 0.4
        
        if i > 0:
            ema_value = svalue_filtered[-1]
            ema_value = alpha * svalue + (1 - alpha) * ema_value
        else:
            ema_value = svalue
                
        filtered = ema_value
        
            
        svalue_filtered.append(filtered)

    # ▶ 필터링 결과 적용 및 _new 제거
    target_df["svalue"] = svalue_filtered
    target_df["action"] = target_df["action"].str.replace("_new", "", regex=False)

    # ▶ 수동관수 행 병합 및 정렬
    final_df = pd.concat([target_df, manual_rows], ignore_index=True)
    final_df = final_df.sort_values("Time").reset_index(drop=True)

    return final_df



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
    df["action"] = df["action"].astype(str) + "_new"
    
    # 🔹 첫 줄은 last_state → 제거하고 반환
    return df