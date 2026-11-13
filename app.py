import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import gspread
from google.oauth2.credentials import Credentials as OAuthCredentials
from google.auth.transport.requests import Request
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import html
import re

try:
    from google import genai
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False

# Streamlit 버전에 따른 fragment 데코레이터 안전 호환
fragment_decorator = getattr(st, "fragment", lambda func: func)

# ==============================================================================
# 1. 기본 페이지 설정 및 상수 정의
# ==============================================================================
st.set_page_config(
    page_title="2026 업적 KPI 현황판_품질안전부문",
    layout="wide",
    initial_sidebar_state="collapsed"
)

if "current_view" not in st.session_state:
    st.session_state.current_view = "main"

if "soy_tab_cache" not in st.session_state:
    st.session_state.soy_tab_cache = {}

def set_view(view_name):
    st.session_state.current_view = view_name

FISCAL_MONTHS = ["3월", "4월", "5월", "6월", "7월", "8월", "9월", "10월", "11월", "12월", "1월", "2월"]
CALENDAR_MONTHS = [f"{i}월" for i in range(1, 13)]

DAIRY_CATEGORIES = ["냉장우유 카톤팩", "냉장우유 병", "발효유/음료 카톤팩", "발효유/음료 병"]
RT_CATEGORIES = ["상온 멸균팩", "상온 프리즈마"]

SHEET_NAMES = {
    "cost": "원가절감 현황",
    "claim": "클레임 건수",
    "supplier": "협력업체 심사 결과 DB",
    "label_status": "표시사항 현황",
    "raw_label_db": "원자재 표시사항 DB",
    "process_soy": "[상온]두유 배양검사 일보",
    "process_rt": "[상온]상온제품 공정 관리 일보",
    "process_milk": "[우유] 유제품 포장 공정관리 일보"
}

# ==============================================================================
# 2. 커스텀 CSS (메인 KPI 카드 + 가로 스크롤 없는 실시간 컬러 관제 테이블)
# ==============================================================================
st.markdown("""
<style>
    .main-title {
        font-size: 27px;
        font-weight: 800;
        color: #002060;
        border-bottom: 3px solid #7F9EB2;
        padding-bottom: 8px;
        margin-bottom: 6px;
        display: flex;
        justify-content: space-between;
        align-items: flex-end;
    }
    .sub-date {
        font-size: 13.5px;
        font-weight: 700;
        color: #002060;
        text-align: right;
        margin-bottom: 10px;
    }
    .ax-banner {
        background: linear-gradient(90deg, #002060 0%, #1F4E78 100%);
        color: #FFFFFF;
        padding: 12px 18px;
        border-radius: 6px;
        margin-bottom: 16px;
        font-size: 14px;
        line-height: 1.6;
        box-shadow: 0 2px 6px rgba(0,0,0,0.15);
    }
    .forecast-box {
        background-color: #F4F7FB;
        border-left: 5px solid #1F4E78;
        padding: 12px 16px;
        border-radius: 4px;
        margin-bottom: 14px;
        font-size: 13.5px;
        line-height: 1.65;
        color: #111111;
    }
    .kpi-card {
        background-color: #F2F2F2;
        border: 1px solid #D9D9D9;
        border-radius: 4px;
        box-shadow: 2px 2px 6px rgba(0,0,0,0.08);
        margin-bottom: 6px;
        overflow: hidden;
    }
    .kpi-header {
        background-color: #44546A;
        color: white;
        font-size: 16px;
        font-weight: 700;
        text-align: center;
        padding: 10px 5px;
    }
    .kpi-body {
        padding: 14px 15px 5px 15px;
        min-height: 135px;
        position: relative;
        font-size: 13.5px;
        color: #111111;
        line-height: 1.72;
    }
    .kpi-bullet {
        color: #44546A;
        font-weight: bold;
        margin-right: 6px;
    }
    .ai-line {
        font-size: 12.5px;
        font-weight: 700;
        color: #1F4E78;
        background-color: #E8EEF5;
        padding: 3px 8px;
        border-radius: 4px;
        margin-top: 4px;
        display: inline-block;
    }
    .unit-label {
        font-size: 12px;
        font-weight: 700;
        color: #002060;
        text-align: right;
        margin-top: -8px;
        margin-bottom: -12px;
        padding-right: 12px;
    }
    .signal-dot {
        height: 22px;
        width: 22px;
        border-radius: 50%;
        position: absolute;
        top: 12px;
        right: 15px;
        box-shadow: 0 0 6px rgba(0,0,0,0.25);
    }
    .signal-red { background-color: #FF0000; border: 1.5px solid #800000; }
    .signal-yellow { background-color: #FFC000; border: 1.5px solid #806000; }
    .signal-green { background-color: #00B050; border: 1.5px solid #00602B; }
    .signal-gray { background-color: #BFBFBF; border: 1.5px solid #7F7F7F; }
    .rep-list-box {
        background-color: #FFFFFF;
        border: 1px solid #D9D9D9;
        border-radius: 4px;
        padding: 8px 10px;
        margin-top: 6px;
        font-size: 12px;
        line-height: 1.5;
        color: #222222;
    }
    div.stButton > button {
        width: 100%;
        background-color: #E7E6E6;
        color: #002060;
        font-weight: 700;
        border: 1px solid #BFBFBF;
        border-radius: 4px;
        margin-bottom: 14px;
    }
    div.stButton > button:hover {
        background-color: #002060;
        color: white;
        border-color: #002060;
    }

    /* 공정 실시간 관제 브리핑 카드 & 자동 줄바꿈 테이블 */
    .issue-card-ok {
        background-color: #EBF6EE;
        border: 1.5px solid #2E8B57;
        border-left: 6px solid #00B050;
        border-radius: 6px;
        padding: 12px 15px;
        margin-bottom: 12px;
        font-size: 13.5px;
        color: #145A32;
        line-height: 1.6;
        word-break: keep-all;
    }
    .issue-card-warn {
        background-color: #FFF9E6;
        border: 1.5px solid #E6A700;
        border-left: 6px solid #FF9900;
        border-radius: 6px;
        padding: 12px 15px;
        margin-bottom: 12px;
        font-size: 13.5px;
        color: #5C3D00;
        line-height: 1.6;
        word-break: keep-all;
    }
    .ctrl-table {
        width: 100%;
        border-collapse: collapse;
        table-layout: fixed;
        font-size: 13px;
        margin-bottom: 16px;
        background-color: #FFFFFF;
        border: 1px solid #CBD5E1;
    }
    .ctrl-table th {
        background-color: #334155;
        color: #FFFFFF;
        font-weight: 700;
        padding: 8px 6px;
        border: 1px solid #475569;
        text-align: center;
        word-break: keep-all;
    }
    .ctrl-table td {
        padding: 7px 8px;
        border: 1px solid #CBD5E1;
        vertical-align: middle;
        word-break: keep-all;
        overflow-wrap: break-word;
        white-space: pre-wrap;
        line-height: 1.45;
        color: #1E293B;
    }
    .cell-ok {
        background-color: #E2F0D9 !important;
        color: #165B28 !important;
        font-weight: 700;
    }
    .cell-warn {
        background-color: #FFF2CC !important;
        color: #7F5200 !important;
        font-weight: 700;
    }
    .cell-ng {
        background-color: #FCE4D6 !important;
        color: #B91C1C !important;
        font-weight: 800;
    }
    .cell-idle {
        background-color: #F8FAFC !important;
        color: #94A3B8 !important;
    }
    .row-issue {
        background-color: #FFFBEB;
    }
    .std-sub {
        font-size: 11.5px;
        color: #475569;
        font-weight: 600;
        display: block;
    }
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# 3. 인증 및 공통 유틸리티 (스레드 안전한 시트 오픈 지원)
# ==============================================================================
@st.cache_resource
def get_gspread_client():
    if "google_oauth" in st.secrets:
        try:
            oauth_info = dict(st.secrets["google_oauth"])
            creds = OAuthCredentials(
                token=None,
                refresh_token=oauth_info["refresh_token"],
                token_uri="https://oauth2.googleapis.com/token",
                client_id=oauth_info["client_id"],
                client_secret=oauth_info["client_secret"]
            )
            creds.refresh(Request())
            return gspread.authorize(creds), None
        except Exception as e:
            return None, f"Google OAuth 인증 오류: {e}"

    if "gcp_service_account" in st.secrets:
        try:
            scopes = [
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive"
            ]
            sa_info = dict(st.secrets["gcp_service_account"])
            creds = ServiceAccountCredentials.from_service_account_info(sa_info, scopes=scopes)
            return gspread.authorize(creds), None
        except Exception as e:
            return None, f"Service Account 인증 오류: {e}"

    return None, "Streamlit Secrets에 [google_oauth] 또는 [gcp_service_account] 설정이 없습니다."

def get_sheet_urls_dict():
    if "sheet_urls" in st.secrets:
        return {k: str(v).strip() for k, v in dict(st.secrets["sheet_urls"]).items()}
    return {}

def open_sheet_with_client(client, sheet_urls, key_or_title):
    if client is None:
        return None, "구글 인증 클라이언트가 초기화되지 않았습니다."

    errors = []
    for k, v in SHEET_NAMES.items():
        if key_or_title in (k, v) and k in sheet_urls:
            url_val = sheet_urls[k]
            if url_val:
                try:
                    if url_val.startswith("http"):
                        return client.open_by_url(url_val), None
                    return client.open_by_key(url_val), None
                except Exception as e:
                    errors.append(f"URL/ID 열기 실패({k}): {e}")

    target_title = SHEET_NAMES.get(key_or_title, key_or_title)
    for candidate in [target_title, target_title.strip(), target_title.strip() + " "]:
        try:
            return client.open(candidate), None
        except Exception as e:
            errors.append(f"파일명 '{candidate}' 열기 실패: {e}")

    return None, " / ".join(errors)

def get_values_unformatted(ws):
    try:
        return ws.get_all_values(value_render_option="UNFORMATTED_VALUE")
    except Exception:
        return ws.get_all_values()

def to_float(val, default=0.0):
    if val is None or pd.isna(val):
        return default
    s = str(val).strip()
    if s in ["", "-", "nan", "None", "#######"]:
        return default
    try:
        cleaned = re.sub(r"[^\d.-]", "", s)
        return float(cleaned) if cleaned not in ["", "-", "."] else default
    except Exception:
        return default

def normalize_comp_name(name, core_only=False):
    if not name:
        return ""
    s = str(name).strip()
    if core_only:
        s = re.sub(r"\([^)]*\)", "", s)
        s = s.split("_")[0]
    for token in ["농업회사법인", "주식회사", "유한회사", "(주)", "㈜", "(유)", "(법인)", " ", "_", "\n", "\t", ","]:
        s = s.replace(token, "")
    s = s.replace("롯데웰푸드", "롯데푸드")
    return s.strip()

def get_signal_dot_html(status_code):
    if status_code == "red":
        return '<div class="signal-dot signal-red" title="경고"></div>'
    elif status_code == "yellow":
        return '<div class="signal-dot signal-yellow" title="주의"></div>'
    elif status_code == "gray":
        return '<div class="signal-dot signal-gray" title="미연동/빈칸"></div>'
    return '<div class="signal-dot signal-green" title="양호"></div>'

def calc_regression_and_forecast(y_values, active_flags=None):
    """실적 구간 선형회귀 추세선과 잔여 회계월 예상 추세 연장선을 분리 산출"""
    n = len(y_values)
    if active_flags is not None:
        valid_idx = [i for i in range(n) if active_flags[i]]
    else:
        valid_idx = [i for i, v in enumerate(y_values) if v > 0]

    valid_y = [float(y_values[i]) for i in valid_idx]

    if len(valid_idx) >= 2:
        slope, intercept = np.polyfit(valid_idx, valid_y, 1)
        full_line = [round(max(slope * i + intercept, 0.0), 2) for i in range(n)]
    elif len(valid_idx) == 1:
        slope = 0.0
        full_line = [round(valid_y[0], 2)] * n
    else:
        slope = 0.0
        full_line = [0.0] * n

    last_actual_idx = max(valid_idx) if valid_idx else -1
    actual_trend = [full_line[i] if i <= last_actual_idx else None for i in range(n)]
    forecast_trend = [full_line[i] if i >= last_actual_idx and last_actual_idx >= 0 else None for i in range(n)]

    return {
        "full": full_line,
        "actual_trend": actual_trend,
        "forecast_trend": forecast_trend,
        "slope": round(float(slope), 4),
        "valid_count": len(valid_idx),
        "last_idx": last_actual_idx
    }

# ==============================================================================
# 4. 7대 지표별 실시간 시트 파서 (하드코딩 0%)
# ==============================================================================

# [1] 원가절감 현황 (공백 구분 열 E, J 반영: 부문 B·C열 / 식품안전팀 G·H열 / 품질관리팀 L·M열 동적 탐색)
def fetch_cost_data(client, sheet_urls):
    sh, err = open_sheet_with_client(client, sheet_urls, "cost")
    default_targets = {"부문": 1.54, "식품안전팀": 1.0, "품질관리팀": 0.54}
    if sh is None:
        return pd.DataFrame(), default_targets, err

    try:
        ws = sh.get_worksheet(0)
        rows = get_values_unformatted(ws)
        if len(rows) < 3:
            return pd.DataFrame(), default_targets, "원가절감 시트에 데이터 행이 부족합니다."

        targets = default_targets.copy()
        r0_join = " ".join([str(x) for x in rows[0]])
        nums_uk = re.findall(r"(\d+(?:\.\d+)?)\s*억", r0_join)
        if len(nums_uk) >= 3:
            targets = {"부문": float(nums_uk[0]), "식품안전팀": float(nums_uk[1]), "품질관리팀": float(nums_uk[2])}

        # 2행(인덱스 1) 헤더에서 '원가절감'과 '기준' 열 위치를 순서대로 3세트 탐색 (예: [1, 6, 11] / [2, 7, 12])
        hdr_row = [re.sub(r"\s+", "", str(c)) for c in rows[1]]
        act_cols = [i for i, h in enumerate(hdr_row) if "원가절감" in h]
        tar_cols = [i for i, h in enumerate(hdr_row) if "기준" in h]

        b_act_c = act_cols[0] if len(act_cols) >= 1 else 1
        fs_act_c = act_cols[1] if len(act_cols) >= 2 else 6
        qc_act_c = act_cols[2] if len(act_cols) >= 3 else 11

        b_tar_c = tar_cols[0] if len(tar_cols) >= 1 else 2
        fs_tar_c = tar_cols[1] if len(tar_cols) >= 2 else 7
        qc_tar_c = tar_cols[2] if len(tar_cols) >= 3 else 12

        need_len = max(b_act_c, fs_act_c, qc_act_c, b_tar_c, fs_tar_c, qc_tar_c) + 2
        parsed = []
        for r in rows[2:]:
            r_pad = list(r) + [""] * max(0, need_len - len(r))
            m_name = str(r_pad[0]).strip()
            if m_name in FISCAL_MONTHS:
                b_act = round(to_float(r_pad[b_act_c]), 1)
                b_tar = round(to_float(r_pad[b_tar_c]), 1)
                fs_act = round(to_float(r_pad[fs_act_c]), 1)
                fs_tar = round(to_float(r_pad[fs_tar_c]), 1)
                qc_act = round(to_float(r_pad[qc_act_c]), 1)
                qc_tar = round(to_float(r_pad[qc_tar_c]), 1)

                parsed.append({
                    "월": m_name,
                    "부문_실적(만원)": b_act,
                    "부문_기준(만원)": b_tar,
                    "부문_달성률(%)": round((b_act / b_tar) * 100, 1) if b_tar > 0 else 0.0,
                    "식품안전팀_실적(만원)": fs_act,
                    "식품안전팀_기준(만원)": fs_tar,
                    "식품안전팀_달성률(%)": round((fs_act / fs_tar) * 100, 1) if fs_tar > 0 else 0.0,
                    "품질관리팀_실적(만원)": qc_act,
                    "품질관리팀_기준(만원)": qc_tar,
                    "품질관리팀_달성률(%)": round((qc_act / qc_tar) * 100, 1) if qc_tar > 0 else 0.0
                })
        return pd.DataFrame(parsed), targets, None
    except Exception as e:
        return pd.DataFrame(), default_targets, str(e)

# [2] 클레임 건수
def fetch_claim_data(client, sheet_urls):
    sh, err = open_sheet_with_client(client, sheet_urls, "claim")
    if sh is None:
        return pd.DataFrame(), pd.DataFrame(), err

    try:
        target_ws = None
        for w in sh.worksheets():
            sample = w.get_all_values()[:8]
            flat_txt = " ".join([" ".join(r) for r in sample])
            if "유형" in flat_txt and ("3월" in flat_txt or "생산" in flat_txt):
                target_ws = w
                break
        if target_ws is None:
            target_ws = sh.get_worksheet(0)

        rows = get_values_unformatted(target_ws)
        header_row_idx = 1
        for idx, r in enumerate(rows[:10]):
            r_str = [str(c).strip() for c in r]
            if "유형" in r_str and "합계" in r_str:
                header_row_idx = idx
                break

        hdr = [str(c).strip() for c in rows[header_row_idx]]
        cat_col = hdr.index("유형") if "유형" in hdr else 1
        sum_col = hdr.index("합계") if "합계" in hdr else 2
        year_col = max(0, cat_col - 1)

        month_col_map = {}
        for idx, cell_txt in enumerate(hdr):
            if cell_txt in FISCAL_MONTHS:
                month_col_map[cell_txt] = idx
        for idx, m in enumerate(FISCAL_MONTHS):
            if m not in month_col_map:
                month_col_map[m] = sum_col + 3 + (idx * 3)

        cat_list = []
        current_year = ""
        for r in rows[header_row_idx + 2:]:
            if not any(str(x).strip() != "" for x in r):
                continue
            r_pad = list(r) + [""] * max(0, 45 - len(r))
            yr_raw = str(r_pad[year_col]).strip()
            cat_raw = str(r_pad[cat_col]).strip()

            if re.search(r"20\d{2}", yr_raw):
                m_yr = re.search(r"(20\d{2})", yr_raw)
                current_year = f"{m_yr.group(1)}년"

            if not current_year or not cat_raw or cat_raw in ["유형", "클레임 건수"]:
                continue

            t_cnt = int(round(to_float(r_pad[sum_col])))
            t_prod = int(round(to_float(r_pad[sum_col + 1])))
            t_ppm = round(to_float(r_pad[sum_col + 2]), 2)

            row_dict = {
                "연도": current_year,
                "유형": cat_raw,
                "합계_건수": t_cnt,
                "합계_생산수량": t_prod,
                "합계_PPM": t_ppm
            }
            for m in FISCAL_MONTHS:
                mc = month_col_map[m]
                m_cnt = int(round(to_float(r_pad[mc]))) if mc < len(r_pad) else 0
                m_prd = int(round(to_float(r_pad[mc + 1]))) if mc + 1 < len(r_pad) else 0
                m_ppm = round(to_float(r_pad[mc + 2]), 2) if mc + 2 < len(r_pad) else 0.0
                row_dict[f"{m}_건수"] = m_cnt
                row_dict[f"{m}_생산수량"] = m_prd
                row_dict[f"{m}_PPM"] = m_ppm
            cat_list.append(row_dict)

        df_category = pd.DataFrame(cat_list)
        if df_category.empty:
            return pd.DataFrame(), pd.DataFrame(), "클레임 시트에서 데이터를 찾지 못했습니다."

        years_found = sorted(df_category["연도"].unique().tolist(), reverse=True)
        yr_cur = "2026년" if "2026년" in years_found else years_found[0]
        yr_prev = "2025년" if "2025년" in years_found else (years_found[1] if len(years_found) > 1 else "")

        row_cur = df_category[(df_category["연도"] == yr_cur) & (df_category["유형"] == "합계")]
        row_prev = df_category[(df_category["연도"] == yr_prev) & (df_category["유형"] == "합계")] if yr_prev else pd.DataFrame()

       trend_rows = []
        for m in FISCAL_MONTHS:
            c26 = int(row_cur[f"{m}_건수"].values[0]) if not row_cur.empty else 0
            p26 = float(row_cur[f"{m}_PPM"].values[0]) if not row_cur.empty else 0.0
            c25 = int(row_prev[f"{m}_건수"].values[0]) if not row_prev.empty else 0
            p25 = float(row_prev[f"{m}_PPM"].values[0]) if not row_prev.empty else 0.0
            trend_rows.append({
                "월": m,
                "2026년_건수": c26,
                "2026년_PPM": p26,
                "2025년_건수": c25,
                "2025년_PPM": p25,
                "목표_PPM": 1.12
            })
        return pd.DataFrame(trend_rows), df_category, None
    except Exception as e:
        return pd.DataFrame(), pd.DataFrame(), str(e)
