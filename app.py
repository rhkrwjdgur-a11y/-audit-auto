import html
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import gspread
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials as OAuthCredentials
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from plotly.subplots import make_subplots

try:
    from google import genai
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False

# ==============================================================================
# 1. 기본 페이지 설정 및 세션 상태 초기화
# ==============================================================================
st.set_page_config(
    page_title="2026 업적 KPI 현황판_품질안전부문 (AX Dashboard)",
    layout="wide",
    initial_sidebar_state="collapsed"
)

if "current_view" not in st.session_state:
    st.session_state.current_view = "main"


def set_view(view_name: str):
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
# 2. 커스텀 CSS (장표 카드 + 가로 스크롤 없는 자동 줄바꿈 관제 테이블 + 신호등 색상)
# ==============================================================================
st.markdown("""
<style>
    .main-title {
        font-size: 28px;
        font-weight: 800;
        color: #002060;
        border-bottom: 3px solid #7F9EB2;
        padding-bottom: 8px;
        margin-bottom: 5px;
        display: flex;
        justify-content: space-between;
        align-items: flex-end;
    }
    .sub-date {
        font-size: 14px;
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
    /* 공정 관제 특이사항 브리핑 박스 */
    .issue-card-ok {
        background-color: #EBF5EE;
        border: 1px solid #A9D18E;
        border-left: 6px solid #00B050;
        border-radius: 6px;
        padding: 12px 15px;
        margin-bottom: 12px;
        font-size: 13.5px;
        line-height: 1.6;
        color: #1B4332;
        word-break: keep-all;
        overflow-wrap: break-word;
    }
    .issue-card-warn {
        background-color: #FFF9E6;
        border: 1px solid #FFD966;
        border-left: 6px solid #ED7D31;
        border-radius: 6px;
        padding: 12px 15px;
        margin-bottom: 12px;
        font-size: 13.5px;
        line-height: 1.6;
        color: #332701;
        word-break: keep-all;
        overflow-wrap: break-word;
    }
    /* 가로 스크롤 없는 자동 줄바꿈 관제 테이블 */
    .mon-table {
        width: 100%;
        border-collapse: collapse;
        table-layout: fixed;
        font-size: 13px;
        margin-bottom: 16px;
        background-color: #FFFFFF;
        border: 1px solid #D0D7DE;
    }
    .mon-table th {
        background-color: #44546A;
        color: #FFFFFF;
        font-weight: 700;
        padding: 8px 6px;
        border: 1px solid #D0D7DE;
        text-align: center;
        word-break: keep-all;
    }
    .mon-table td {
        padding: 7px 8px;
        border: 1px solid #D0D7DE;
        vertical-align: middle;
        word-break: keep-all;
        overflow-wrap: break-word;
        line-height: 1.45;
        color: #111111;
    }
    .td-center { text-align: center; }
    .td-left { text-align: left; }
    .cell-green {
        background-color: #E2F0D9 !important;
        color: #1E6B34 !important;
        font-weight: 700;
    }
    .cell-yellow {
        background-color: #FFF2CC !important;
        color: #7F6000 !important;
        font-weight: 700;
    }
    .cell-red {
        background-color: #FCE4D6 !important;
        color: #C00000 !important;
        font-weight: 700;
    }
    .cell-gray {
        background-color: #F5F5F5 !important;
        color: #7F7F7F !important;
    }
    div.stButton > button {
        width: 100%;
        background-color: #E7E6E6;
        color: #002060;
        font-weight: 700;
        border: 1px solid #BFBFBF;
        border-radius: 4px;
        margin-bottom: 18px;
    }
    div.stButton > button:hover {
        background-color: #002060;
        color: white;
        border-color: #002060;
    }
</style>
""", unsafe_allow_html=True)


# ==============================================================================
# 3. Google 인증 및 병렬 안전 시트 오픈 유틸리티 (invalid_scope 원천 차단)
# ==============================================================================
def build_google_credentials():
    """메인 스레드에서 OAuth 또는 서비스 계정 자격증명을 생성·갱신하여 반환"""
    if "google_oauth" in st.secrets:
        try:
            oauth_info = st.secrets["google_oauth"]
            creds = OAuthCredentials(
                token=None,
                refresh_token=oauth_info["refresh_token"],
                token_uri="https://oauth2.googleapis.com/token",
                client_id=oauth_info["client_id"],
                client_secret=oauth_info["client_secret"]
            )
            creds.refresh(Request())
            return creds, None
        except Exception as e:
            return None, f"Google OAuth 인증 실패: {e}"

    if "gcp_service_account" in st.secrets:
        try:
            scopes = [
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive"
            ]
            creds = ServiceAccountCredentials.from_service_account_info(
                dict(st.secrets["gcp_service_account"]), scopes=scopes
            )
            return creds, None
        except Exception as e:
            return None, f"Service Account 인증 실패: {e}"

    return None, "Streamlit Secrets에 [google_oauth] 또는 [gcp_service_account] 설정이 없습니다."


def open_sheet_threadsafe(creds, sheet_urls_map: dict, key_or_title: str):
    """각 워커 스레드마다 독립된 gspread Client를 생성해 스레드 충돌 없이 시트를 오픈"""
    if creds is None:
        return None, "인증 자격증명이 없습니다."

    client = gspread.authorize(creds)
    errors = []

    if key_or_title in sheet_urls_map:
        url_val = str(sheet_urls_map[key_or_title]).strip()
        if url_val:
            try:
                if url_val.startswith("http"):
                    return client.open_by_url(url_val), None
                return client.open_by_key(url_val), None
            except Exception as e:
                errors.append(f"URL/ID 열기 실패({key_or_title}): {e}")

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


def get_signal_dot_html(status_code: str) -> str:
    if status_code == "red":
        return '<div class="signal-dot signal-red" title="경고"></div>'
    if status_code == "yellow":
        return '<div class="signal-dot signal-yellow" title="주의"></div>'
    if status_code == "gray":
        return '<div class="signal-dot signal-gray" title="미연동/빈칸"></div>'
    return '<div class="signal-dot signal-green" title="양호"></div>'


# ==============================================================================
# 4. 추세선 및 잔여 월 예상 추세도(Forecast) 산출 함수
# ==============================================================================
def calc_trend_and_forecast_split(y_values: list, is_recorded_list: list = None, total_periods: int = 12):
    """
    실적이 기록된 월까지는 실적 회귀 추세선(actual_line),
    이후 잔여 월(12월~2월 등)은 예상 추세 연장선(forecast_line)으로 분리 반환
    """
    if is_recorded_list is not None:
        valid_idx = [i for i, flag in enumerate(is_recorded_list) if flag]
    else:
        valid_idx = [i for i, v in enumerate(y_values) if v > 0]

    valid_y = [float(y_values[i]) for i in valid_idx]

    if len(valid_idx) >= 2:
        slope, intercept = np.polyfit(valid_idx, valid_y, 1)
        full_line = [round(max(float(slope * i + intercept), 0.0), 2) for i in range(total_periods)]
    elif len(valid_idx) == 1:
        slope = 0.0
        full_line = [round(valid_y[0], 2)] * total_periods
    else:
        return [None] * total_periods, [None] * total_periods, [0.0] * total_periods, 0.0, 0, -1

    last_idx = max(valid_idx)
    actual_line = [full_line[i] if i <= last_idx else None for i in range(total_periods)]
    forecast_line = [full_line[i] if i >= last_idx else None for i in range(total_periods)]

    return actual_line, forecast_line, full_line, round(float(slope), 4), len(valid_idx), last_idx


# ==============================================================================
# 5. HTML 자동 줄바꿈 & 실시간 색상 판정 테이블 렌더러 (가로 스크롤 제거)
# ==============================================================================
def render_html_table(columns_spec: list, rows_data: list) -> str:
    """
    columns_spec: [{"key": str, "label": str, "width": "12%", "align": "center"|"left"}, ...]
    rows_data: [{"col_key": {"text": str, "cls": "cell-green"|"cell-yellow"|"cell-red"|"cell-gray"|""}, ...}]
    """
    if not rows_data:
        return "<div style='padding:10px; color:#666; background:#F9F9F9; border:1px solid #DDD; border-radius:4px;'>기록된 데이터가 없습니다.</div>"

    colgroup = "".join([f"<col style='width:{c.get('width', 'auto')};'>" for c in columns_spec])
    thead = "".join([f"<th>{html.escape(str(c['label']))}</th>" for c in columns_spec])

    tbody_rows = []
    for row in rows_data:
        tds = []
        for c in columns_spec:
            k = c["key"]
            align_cls = "td-left" if c.get("align") == "left" else "td-center"
            cell_obj = row.get(k, {"text": "-", "cls": ""})
            if isinstance(cell_obj, dict):
                raw_txt = str(cell_obj.get("text", "-"))
                c_cls = cell_obj.get("cls", "")
            else:
                raw_txt = str(cell_obj)
                c_cls = ""
            safe_txt = html.escape(raw_txt).replace("\n", "<br>")
            tds.append(f"<td class='{align_cls} {c_cls}'>{safe_txt}</td>")
        tbody_rows.append(f"<tr>{''.join(tds)}</tr>")

    return f"""
    <table class="mon-table">
        <colgroup>{colgroup}</colgroup>
        <thead><tr>{thead}</tr></thead>
        <tbody>{''.join(tbody_rows)}</tbody>
    </table>
    """


# ==============================================================================
# 6. 7대 지표별 실시간 시트 파싱 함수 (하드코딩 0%)
# ==============================================================================

# [1] 원가절감 현황 (공백 구분 열 E, J 포함 동적 헤더 위치 탐지)
def fetch_cost_sheet(creds, sheet_urls_map):
    sh, err = open_sheet_threadsafe(creds, sheet_urls_map, "cost")
    default_targets = {"부문": 1.54, "식품안전팀": 1.0, "품질관리팀": 0.54}
    if sh is None:
        return pd.DataFrame(), default_targets, err

    try:
        ws = sh.get_worksheet(0)
        rows = get_values_unformatted(ws)
        targets = default_targets.copy()

        if len(rows) >= 1:
            r0_join = " ".join([str(x) for x in rows[0]])
            nums_uk = re.findall(r"(\d+(?:\.\d+)?)\s*억", r0_join)
            if len(nums_uk) >= 3:
                targets = {
                    "부문": float(nums_uk[0]),
                    "식품안전팀": float(nums_uk[1]),
                    "품질관리팀": float(nums_uk[2])
                }

        # 2행(인덱스 1)에서 '원가절감' 헤더 열 인덱스를 모두 탐색 -> [1(B열), 6(G열), 11(L열)]
        hdr_row_idx = 1
        for idx, r in enumerate(rows[:5]):
            if sum(1 for c in r if re.sub(r"\s+", "", str(c)) == "원가절감") >= 2:
                hdr_row_idx = idx
                break

        hdr_cells = [re.sub(r"\s+", "", str(c)) for c in rows[hdr_row_idx]]
        act_cols = [i for i, h in enumerate(hdr_cells) if h == "원가절감"]
        if len(act_cols) < 3:
            act_cols = [1, 6, 11]

        b_c, fs_c, qc_c = act_cols[0], act_cols[1], act_cols[2]

        parsed = []
        for r in rows[hdr_row_idx + 1:]:
            r_pad = list(r) + [""] * max(0, qc_c + 4 - len(r))
            m_name = str(r_pad[max(0, b_c - 1)]).strip()
            if m_name in FISCAL_MONTHS:
                b_raw = str(r_pad[b_c]).strip()
                fs_raw = str(r_pad[fs_c]).strip()
                qc_raw = str(r_pad[qc_c]).strip()

                b_act = round(to_float(b_raw), 1)
                b_tar = round(to_float(r_pad[b_c + 1]), 1)
                fs_act = round(to_float(fs_raw), 1)
                fs_tar = round(to_float(r_pad[fs_c + 1]), 1)
                qc_act = round(to_float(qc_raw), 1)
                qc_tar = round(to_float(r_pad[qc_c + 1]), 1)

                is_rec = (b_act > 0) or (fs_act > 0) or (qc_act > 0)
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
                    "품질관리팀_달성률(%)": round((qc_act / qc_tar) * 100, 1) if qc_tar > 0 else 0.0,
                    "_기록여부": is_rec
                })
        return pd.DataFrame(parsed), targets, None
    except Exception as e:
        return pd.DataFrame(), default_targets, str(e)


# [2] 클레임 건수
def fetch_claim_sheet(creds, sheet_urls_map):
    sh, err = open_sheet_threadsafe(creds, sheet_urls_map, "claim")
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
            return pd.DataFrame(), pd.DataFrame(), "클레임 시트에서 유효한 데이터를 찾지 못했습니다."

        years_found = sorted(df_category["연도"].unique().tolist(), reverse=True)
        yr_cur = "2026년" if "2026년" in years_found else years_found[0]
        yr_prev = "2025년" if "2025년" in years_found else (years_found[1] if len(years_found) > 1 else "")

        row_cur = df_category[(df_category["연도"] == yr_cur) & (df_category["유형"] == "합계")]
        row_prev = df_category[(df_category["연도"] == yr_prev) & (df_category["유형"] == "합계")] if yr_prev else pd.DataFrame()

        trend_rows = []
        for m in FISCAL_MONTHS:
            c26 = int(row_cur[f"{m}_건수"].values[0]) if not row_cur.empty else 0
            prod26 = int(row_cur[f"{m}_생산수량"].values[0]) if not row_cur.empty else 0
            p26 = float(row_cur[f"{m}_PPM"].values[0]) if not row_cur.empty else 0.0
            c25 = int(row_prev[f"{m}_건수"].values[0]) if not row_prev.empty else 0
            p25 = float(row_prev[f"{m}_PPM"].values[0]) if not row_prev.empty else 0.0
            trend_rows.append({
                "월": m,
                "2026년_건수": c26,
                "2026년_생산수량": prod26,
                "2026년_PPM": p26,
                "2025년_건수": c25,
                "2025년_PPM": p25,
                "목표_PPM": 1.12,
                "_기록여부": (prod26 > 0 or c26 > 0)
            })
        return pd.DataFrame(trend_rows), df_category, None
    except Exception as e:
        return pd.DataFrame(), pd.DataFrame(), str(e)


def build_division_claim_df(df_category: pd.DataFrame, year_str: str, division_categories: list):
    if df_category.empty:
        return pd.DataFrame(), pd.DataFrame()
    sub = df_category[(df_category["연도"] == year_str) & (df_category["유형"].isin(division_categories))]
    monthly_rows = []
    for m in FISCAL_MONTHS:
        cnt_sum = int(sub[f"{m}_건수"].sum()) if not sub.empty else 0
        prod_sum = int(sub[f"{m}_생산수량"].sum()) if not sub.empty else 0
        ppm_val = round((cnt_sum / prod_sum) * 1_000_000, 2) if prod_sum > 0 else 0.0
        row_item = {
            "월": m,
            "합산_건수": cnt_sum,
            "합산_생산수량": prod_sum,
            "부문_통합_PPM": ppm_val,
            "_기록여부": (prod_sum > 0 or cnt_sum > 0)
        }
        for cat in division_categories:
            cat_row = sub[sub["유형"] == cat]
            row_item[f"{cat}_건수"] = int(cat_row[f"{m}_건수"].values[0]) if not cat_row.empty else 0
            row_item[f"{cat}_PPM"] = float(cat_row[f"{m}_PPM"].values[0]) if not cat_row.empty else 0.0
        monthly_rows.append(row_item)
    return pd.DataFrame(monthly_rows), sub


# [3] 공정일보 공통 날짜 탭 정렬 함수
def get_sorted_date_worksheets(sh):
    if sh is None:
        return None, None, []
    ws_list = sh.worksheets()
    today = datetime.now()
    yesterday = today - timedelta(days=1)

    date_tabs = []
    for w in ws_list:
        t = w.title.strip()
        if any(ex in t for ex in ["양식", "복사", "백업", "사본", "대기"]):
            continue
        m = re.match(r"^(\d{1,2})[/\.\-](\d{1,2})$", t)
        if m:
            mm, dd = int(m.group(1)), int(m.group(2))
            yr = today.year if mm <= today.month + 1 else today.year - 1
            try:
                dt_obj = datetime(yr, mm, dd)
            except ValueError:
                dt_obj = datetime(today.year, 1, 1)
            date_tabs.append((dt_obj, w))

    date_tabs.sort(key=lambda x: x[0], reverse=True)
    ordered_ws = [w for _, w in date_tabs]

    t_cands = {today.strftime("%m/%d"), f"{today.month}/{today.day}", today.strftime("%m.%d"), f"{today.month}.{today.day}"}
    y_cands = {yesterday.strftime("%m/%d"), f"{yesterday.month}/{yesterday.day}", yesterday.strftime("%m.%d"), f"{yesterday.month}.{yesterday.day}"}

    ws_today = next((w for w in ordered_ws if w.title.strip() in t_cands), None)
    ws_yest = next((w for w in ordered_ws if w.title.strip() in y_cands), None)

    if ws_today is None and len(ordered_ws) >= 1:
        ws_today = ordered_ws[0]
    if ws_yest is None and len(ordered_ws) >= 2:
        idx_t = ordered_ws.index(ws_today) if ws_today in ordered_ws else 0
        ws_yest = ordered_ws[idx_t + 1] if idx_t + 1 < len(ordered_ws) else ordered_ws[0]

    if ws_today is None and ws_list:
        ws_today = ws_list[0]

    return ws_today, ws_yest, ordered_ws


# CCP-3B 범위 적합 판정 보조 함수
def eval_ccp3b_cell(val_str: str, std_str: str, is_ho_running: bool) -> str:
    s = str(val_str).strip()
    if s in ["", "-"]:
        return ""
    nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", s)]
    if not nums:
        return "cell-green" if "적합" in s else ""

    ranges = re.findall(r"(\d+(?:\.\d+)?)\s*~\s*(\d+(?:\.\d+)?)", str(std_str))
    if not ranges:
        return "cell-green"

    all_ok = True
    for n in nums:
        if not any(float(lo) <= n <= float(hi) for lo, hi in ranges):
            all_ok = False
            break
    return "cell-green" if all_ok else "cell-red"


# 멸균기 우측 S~U열 기준값과 실측치 적합 판정 보조 함수
def eval_ster_metric(actual_str: str, std_str: str, sterilizer_ho: str, metric_kind: str) -> str:
    act_s = str(actual_str).strip()
    if act_s in ["", "-", "기록대기"]:
        return "cell-yellow"
    act_nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", act_s)]
    if not act_nums:
        return "cell-yellow"
    act_val = act_nums[0]

    std_s = str(std_str).strip()
    if std_s in ["", "-"]:
        return "cell-green"

    # 호기별 분기 기준 처리 (예: '3호기 : 143 / 그외 : 139', '143 / 슬림_멸균2호기 142℃')
    target_val = None
    ho_num_m = re.search(r"(\d+)호기", str(sterilizer_ho))
    ho_num = ho_num_m.group(1) if ho_num_m else ""

    if ho_num and f"{ho_num}호기" in std_s:
        m_specific = re.search(rf"{ho_num}호기[^\d]*(\d+(?:\.\d+)?)", std_s)
        if m_specific:
            target_val = float(m_specific.group(1))
    elif "그외" in std_s:
        m_other = re.search(r"그외[^\d]*(\d+(?:\.\d+)?)", std_s)
        if m_other:
            target_val = float(m_other.group(1))

    if target_val is None:
        std_nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", std_s)]
        if std_nums:
            target_val = min(std_nums)

    if target_val is None:
        return "cell-green"

    if metric_kind == "temp":
        return "cell-green" if act_val >= (target_val - 2.0) else "cell-red"
    if metric_kind == "press":
        return "cell-green" if act_val >= (target_val * 0.90) else "cell-red"
    if metric_kind == "hold":
        return "cell-green" if act_val >= (target_val - 0.8) else "cell-red"
    return "cell-green"


# [3-A] 상온제품 공정 관리 일보 정밀 파서 (전 행 스캔 + CCP-3B 복구 + S~V열 기준 직접 매칭)
def parse_rt_process_worksheet(ws):
    if ws is None:
        return None
    rows = ws.get_all_values()
    if len(rows) < 5:
        return None

    tab_title = ws.title.strip()
    prod_date_str = tab_title
    for r in rows[:4]:
        for c in r[:18]:
            if "생 산 일" in str(c) or re.search(r"202\d\.\s*\d{1,2}\.\s*\d{1,2}", str(c)):
                prod_date_str = str(c).replace("생 산 일 :", "").strip()
                break

    # 전체 행 제한 없이 구역 헤더 탐색
    r_pack_hdr = None
    r_ccp3b_hdr = None
    r_ster_hdr = None
    for idx, r in enumerate(rows):
        b_txt = re.sub(r"\s+", "", str(r[1])) if len(r) > 1 else ""
        row_join = re.sub(r"\s+", "", "".join(str(x) for x in r[:12]))
        if r_pack_hdr is None and b_txt == "포장호기":
            r_pack_hdr = idx
        elif r_ccp3b_hdr is None and ("CCP-3B" in row_join or "포장기공정관리" in row_join):
            r_ccp3b_hdr = idx
        elif r_ccp3b_hdr is not None and r_ster_hdr is None and b_txt == "멸균기":
            r_ster_hdr = idx
            break

    if r_pack_hdr is None:
        r_pack_hdr = 2
    if r_ccp3b_hdr is None:
        r_ccp3b_hdr = min(15, len(rows) - 1)
    if r_ster_hdr is None:
        r_ster_hdr = min(r_ccp3b_hdr + 6, len(rows) - 1)

    # 1) 상단 포장호기(A~F호기) 파싱
    ho_products = {}
    ho_rows_raw = {}
    current_ho = ""
    for r in rows[r_pack_hdr + 1 : r_ccp3b_hdr]:
        r_pad = list(r) + [""] * max(0, 18 - len(r))
        b_val = str(r_pad[1]).strip()
        if re.match(r"^[A-Z가-힣0-9]+호기$", b_val):
            current_ho = b_val
            ho_rows_raw.setdefault(current_ho, [])
            ho_products.setdefault(current_ho, [])

        if not current_ho:
            continue

        slots = [
            (r_pad[2:6], [r_pad[6]], r_pad[7:9]),
            (r_pad[9:13], r_pad[13:15], r_pad[15:17])
        ]
        for p_cells, e_cells, t_cells in slots:
            p_name = next((str(x).strip() for x in p_cells if str(x).strip() not in ["", "제 품 명", "제  품  명"]), "")
            exp_v = next((str(x).strip() for x in e_cells if str(x).strip() != ""), "")
            t_parts = [str(x).strip() for x in t_cells if str(x).strip() != ""]
            t_str = " / ".join(t_parts)

            if p_name or exp_v:
                has_time = bool(re.search(r"\d{1,2}:\d{2}", t_str))
                if p_name and has_time and exp_v:
                    st_txt, st_cls = "🟢 확인완료", "cell-green"
                elif p_name and not exp_v:
                    st_txt, st_cls = "🔴 소비기한 누락", "cell-red"
                else:
                    st_txt, st_cls = "🟡 확인시간 대기", "cell-yellow"

                if p_name and p_name not in ho_products[current_ho]:
                    ho_products[current_ho].append(p_name)

                ho_rows_raw[current_ho].append({
                    "포장호기": current_ho,
                    "생산 제품명": p_name if p_name else "(제품명 미기입)",
                    "소비기한": exp_v if exp_v else "-",
                    "확인시간": t_str if t_str else "미기입(대기)",
                    "상태": st_txt,
                    "_cls": st_cls
                })

    lines_records = []
    for ho_k, items in ho_rows_raw.items():
        if items:
            lines_records.extend(items)
        else:
            lines_records.append({
                "포장호기": ho_k,
                "생산 제품명": "(비가동)",
                "소비기한": "-",
                "확인시간": "-",
                "상태": "⚪ 비가동",
                "_cls": "cell-gray"
            })

    # 2) 중단 포장기 공정관리 [CCP-3B] 파싱 (호기 병합 열 구간 전체 스캔)
    ccp3b_records = []
    r_3b_colhdr = r_ccp3b_hdr
    for sub_i in range(r_ccp3b_hdr, min(r_ccp3b_hdr + 3, r_ster_hdr)):
        if sum(1 for c in rows[sub_i][:18] if re.match(r"^[A-F]호기$", str(c).strip())) >= 3:
            r_3b_colhdr = sub_i
            break

    hdr_3b = [str(x).strip() for x in rows[r_3b_colhdr][:18]]
    ho_pos_list = [(idx, cell) for idx, cell in enumerate(hdr_3b) if re.match(r"^[A-F]호기$", cell)]
    ho_pos_list.sort(key=lambda x: x[0])

    first_ho_col = ho_pos_list[0][0] if ho_pos_list else 8
    ho_col_spans = {}
    for i_p, (c_start, h_lbl) in enumerate(ho_pos_list):
        c_end = ho_pos_list[i_p + 1][0] if i_p + 1 < len(ho_pos_list) else 17
        ho_col_spans[h_lbl] = (c_start, c_end)

    last_item_3b = ""
    for r in rows[r_3b_colhdr + 1 : r_ster_hdr]:
        r_pad = list(r) + [""] * max(0, 18 - len(r))
        if not any(str(x).strip() for x in r_pad[1:17]):
            continue
        item_nm = str(r_pad[1]).strip()
        if item_nm:
            last_item_3b = item_nm

        left_meta = [str(x).strip() for x in r_pad[2:first_ho_col] if str(x).strip() and str(x).strip() != item_nm]
        std_parts = [x for x in left_meta if any(u in x for u in ["~", "%", "℃", "㎕", "이상", "이하"])]
        eq_parts = [x for x in left_meta if x not in std_parts]

        std_nm = " ".join(std_parts)
        equip_nm = " ".join(eq_parts)
        if not last_item_3b and not std_nm:
            continue

        rec_3b = {"항목": last_item_3b, "관리기준": std_nm or "-", "적용설비": equip_nm or "-"}
        for ho_lbl in ["A호기", "B호기", "C호기", "D호기", "E호기", "F호기"]:
            if ho_lbl in ho_col_spans:
                cs, ce = ho_col_spans[ho_lbl]
                vals_in_span = [str(x).strip() for x in r_pad[cs:ce] if str(x).strip() not in ["", "-"]]
                rec_3b[ho_lbl] = " / ".join(vals_in_span) if vals_in_span else "-"
            else:
                rec_3b[ho_lbl] = "-"
        ccp3b_records.append(rec_3b)

    # 3) 하단 멸균기 [CCP-1B / CCP-2P] + 우측 S(18)~V(21)열 제품별 기준표 1:1 매칭
    # 시트 내 S~V열 전체에서도 제품명 기준 사전 확보 (보조 매칭용)
    sv_std_by_prod = {}
    for r in rows[r_ster_hdr:]:
        if len(r) >= 22:
            s_t = re.sub(r"\s+", " ", str(r[18])).strip()
            t_p = re.sub(r"\s+", " ", str(r[19])).strip()
            u_h = re.sub(r"\s+", " ", str(r[20])).strip()
            v_pr = re.sub(r"\s+", " ", str(r[21])).strip()
            if v_pr and v_pr not in ["호기별 제품", "제품명"] and any([s_t, t_p, u_h]):
                sv_std_by_prod[v_pr] = (s_t, t_p, u_h)

    ster_blocks = []
    cur_block = None
    for r in rows[r_ster_hdr + 1:]:
        r_pad = list(r) + [""] * max(0, 23 - len(r))
        b_cell = str(r_pad[1]).strip()

        if re.match(r"^\d+호기$", b_cell):
            if cur_block:
                ster_blocks.append(cur_block)
            cur_block = {"ster_ho": b_cell, "rows": [r_pad], "remark": ""}
        elif re.sub(r"\s+", "", b_cell) == "특이사항" and cur_block is not None:
            rem_chunks = []
            for x in r_pad[2:17]:
                xs = str(x).strip()
                if xs not in ["", "-"] and xs not in rem_chunks:
                    rem_chunks.append(xs)
            cur_block["remark"] = " ".join(rem_chunks)
            ster_blocks.append(cur_block)
            cur_block = None
        elif cur_block is not None and len(cur_block["rows"]) < 5:
            if b_cell == "":
                cur_block["rows"].append(r_pad)
            else:
                ster_blocks.append(cur_block)
                cur_block = None
    if cur_block:
        ster_blocks.append(cur_block)

    ster_records = []
    ster_special_notes = []
    ho_ster_summary = {}
    ho_remark_map = {}

    for blk in ster_blocks:
        s_ho = blk["ster_ho"]
        b_rows = blk["rows"]
        pack_ho = next((str(br[2]).strip() for br in b_rows if str(br[2]).strip() not in ["", "-"]), "-")
        vol_str = next((str(br[3]).strip() for br in b_rows if str(br[3]).strip() not in ["", "-"]), "-")
        flt_str = next((str(br[13]).strip() or str(br[14]).strip() for br in b_rows if (str(br[13]).strip() or str(br[14]).strip()) not in ["", "-"]), "-")

        # 같은 행 블록 우측 S(18), T(19), U(20), V(21)열 기준값 직접 추출
        std_temp = next((re.sub(r"\s+", " ", str(br[18])).strip() for br in b_rows if str(br[18]).strip() not in ["", "-", "멸균온도"]), "")
        std_press = next((re.sub(r"\s+", " ", str(br[19])).strip() for br in b_rows if str(br[19]).strip() not in ["", "-", "균질압"]), "")
        std_hold = next((re.sub(r"\s+", " ", str(br[20])).strip() for br in b_rows if str(br[20]).strip() not in ["", "-", "멸균시간"]), "")
        std_v_prod = next((re.sub(r"\s+", " ", str(br[21])).strip() for br in b_rows if str(br[21]).strip() not in ["", "-", "호기별 제품"]), "")

        matched_prods = ho_products.get(pack_ho, [])
        matched_prod_str = ", ".join(matched_prods) if matched_prods else (std_v_prod or "-")

        if not (std_temp or std_press or std_hold) and matched_prods:
            for mp in matched_prods:
                for sv_k, (st_t, st_p, st_h) in sv_std_by_prod.items():
                    if sv_k in mp or mp in sv_k:
                        std_temp, std_press, std_hold = st_t, st_p, st_h
                        break

        rem_val = blk["remark"].strip()
        if rem_val:
            ster_special_notes.append(f"[{s_ho} → {pack_ho} {matched_prod_str}] {rem_val}")
            if pack_ho != "-":
                ho_remark_map[pack_ho] = rem_val

        has_record = False
        for br in b_rows:
            mon_time = str(br[4]).strip() or str(br[5]).strip()
            temp_v = str(br[6]).strip()
            press_v = str(br[7]).strip() or str(br[8]).strip()
            hold_v = str(br[9]).strip()
            flow_v = str(br[10]).strip() or str(br[11]).strip()
            cool_v = str(br[12]).strip()
            sign_v = str(br[15]).strip() or str(br[16]).strip()

            if any(x not in ["", "-"] for x in [mon_time, temp_v, press_v, hold_v, flow_v, cool_v]):
                has_record = True
                temp_disp = f"{temp_v}℃" + (f" (기준: {std_temp})" if std_temp else "")
                press_disp = f"{press_v}" + (f" (기준: {std_press})" if std_press else "")
                hold_disp = f"{hold_v}초" + (f" (기준: {std_hold})" if std_hold else "")

                c_temp = eval_ster_metric(temp_v, std_temp, s_ho, "temp")
                c_press = eval_ster_metric(press_v, std_press, s_ho, "press")
                c_hold = eval_ster_metric(hold_v, std_hold, s_ho, "hold")
                c_flt = "cell-green" if flt_str == "적합" else ("cell-red" if "부적합" in flt_str else "cell-yellow")
                c_time = "cell-green" if re.search(r"\d{1,2}:\d{2}", mon_time) else "cell-yellow"
                c_sign = "cell-green" if sign_v not in ["", "-"] else "cell-yellow"
                c_rem = "cell-yellow" if rem_val else ""

                ster_records.append({
                    "멸균기_포장": f"{s_ho} ({pack_ho})",
                    "매칭 제품명": f"{matched_prod_str} ({vol_str})" if vol_str != "-" else matched_prod_str,
                    "확인시간": mon_time or "미기입",
                    "멸균온도": temp_disp,
                    "균질압": press_disp,
                    "멸균시간": hold_disp,
                    "유량_냉각": f"{flow_v or '-'} L/h / {cool_v or '-'}℃",
                    "여과망_서명": f"{flt_str} / {sign_v or '미서명'}",
                    "특이사항": rem_val if rem_val else "없음",
                    "_c_time": c_time,
                    "_c_temp": c_temp,
                    "_c_press": c_press,
                    "_c_hold": c_hold,
                    "_c_flt": c_flt if c_sign == "cell-green" else "cell-yellow",
                    "_c_rem": c_rem
                })
                if pack_ho != "-":
                    ho_ster_summary[pack_ho] = f"{s_ho} ({temp_v}℃ / {press_v}bar / {hold_v}초 / 여과망:{flt_str})"

        if not has_record and pack_ho != "-":
            ster_records.append({
                "멸균기_포장": f"{s_ho} ({pack_ho})",
                "매칭 제품명": f"{matched_prod_str} ({vol_str})" if vol_str != "-" else matched_prod_str,
                "확인시간": "기록대기",
                "멸균온도": f"- (기준: {std_temp})" if std_temp else "-",
                "균질압": f"- (기준: {std_press})" if std_press else "-",
                "멸균시간": f"- (기준: {std_hold})" if std_hold else "-",
                "유량_냉각": "-",
                "여과망_서명": f"{flt_str} / 미서명",
                "특이사항": rem_val if rem_val else "없음",
                "_c_time": "cell-yellow",
                "_c_temp": "cell-yellow",
                "_c_press": "cell-yellow",
                "_c_hold": "cell-yellow",
                "_c_flt": "cell-yellow",
                "_c_rem": "cell-yellow" if rem_val else ""
            })

    # 전일 마감 요약용 호기 통합 테이블
    compact_rows = []
    for lr in lines_records:
        if lr["생산 제품명"] == "(비가동)":
            continue
        p_ho = lr["포장호기"]
        rem_txt = ho_remark_map.get(p_ho, "이상없음")
        compact_rows.append({
            "포장호기": p_ho,
            "생산 제품명": lr["생산 제품명"],
            "소비기한": lr["소비기한"],
            "확인시간": lr["확인시간"],
            "멸균기·CCP 요약": ho_ster_summary.get(p_ho, "-"),
            "특이사항": rem_txt,
            "_cls_status": lr["_cls"],
            "_cls_rem": "cell-yellow" if rem_txt != "이상없음" else "cell-green"
        })

    # 4) 우측 AB(27)~AC(28:) 전달(특이)사항 파싱
    issues = []
    for r in rows[4:]:
        if len(r) >= 29:
            dt_s = str(r[27]).strip()
            memo_chunks = []
            for c in r[28:]:
                cs = str(c).strip()
                if cs and cs not in memo_chunks and "전달(특이)" not in cs and "생 산 일" not in cs:
                    memo_chunks.append(cs)
            memo_s = " / ".join(memo_chunks)
            if dt_s not in ["", "날짜"] or memo_s:
                issues.append({"기록일자": dt_s or tab_title, "전달(특이)사항 및 소비기한 조치내역": memo_s})

    return {
        "tab_title": tab_title,
        "prod_date": prod_date_str,
        "running_hos": {k for k, v in ho_products.items() if v},
        "lines_records": lines_records,
        "compact_rows": compact_rows,
        "ccp3b_records": ccp3b_records,
        "ster_records": ster_records,
        "ster_special_notes": ster_special_notes,
        "df_issues": pd.DataFrame(list(reversed(issues)))
    }


# [3-B] 유제품 포장 공정관리 일보 파서
def parse_dairy_pack_worksheet(ws, line_label: str):
    if ws is None:
        return pd.DataFrame(), "-"
    rows = ws.get_all_values()
    w_date = ws.title.strip()
    for r in rows[:5]:
        joined = " ".join([str(c).strip() for c in r if str(c).strip()])
        m_dt = re.search(r"202\d[\.\-\s]+\d{1,2}[\.\-\s]+\d{1,2}", joined)
        if m_dt:
            w_date = m_dt.group(0).strip()
            break

    parsed_products = []
    for r_idx, r in enumerate(rows):
        first_cell = re.sub(r"\s+", "", str(r[0])) if len(r) > 0 else ""
        if first_cell in ["제품명", "품목"]:
            next_block_r = len(rows)
            for nr in range(r_idx + 1, min(r_idx + 20, len(rows))):
                nc = re.sub(r"\s+", "", str(rows[nr][0])) if len(rows[nr]) > 0 else ""
                if nc in ["제품명", "품목", "생산시간", "CCP검증모니터링"]:
                    next_block_r = nr
                    break

            for col_i in range(1, len(r)):
                p_name = re.sub(r"\s+", " ", str(r[col_i])).strip()
                if not p_name or p_name in ["제 품 명", "제품명", "품 목", "품목"] or "특이사항" in p_name:
                    continue

                vol_str, chk_time = "", "-"
                exp_list = []
                label_ok, top_ok, bot_ok, vol_ok, sens_ok = "-", "-", "-", "-", "-"

                for sub_r in rows[r_idx + 1 : next_block_r]:
                    row_lbl = re.sub(r"\s+", "", str(sub_r[0])) if len(sub_r) > 0 else ""
                    val = str(sub_r[col_i]).strip() if col_i < len(sub_r) else ""
                    if not val:
                        continue
                    if "㎖" in val or "mL" in val:
                        vol_str = val
                    elif "확인시간" in row_lbl:
                        chk_time = val
                    elif any(k in row_lbl for k in ["소비기한", "Tank"]) or re.match(r"^\d{2}\.\d{2}[A-Z]?$", row_lbl):
                        if val not in ["00.00", "-", "소비기한"] and "제조일로부터" not in val:
                            exp_list.append(val)
                    elif "표시사항" in row_lbl or "표기사항" in row_lbl:
                        label_ok = val
                    elif "상부접착" in row_lbl or "상/하부접착" in row_lbl:
                        top_ok = val
                        if "상/하부" in row_lbl:
                            bot_ok = val
                    elif "하부접착" in row_lbl:
                        bot_ok = val
                    elif "제품용량" in row_lbl:
                        vol_ok = val
                    elif "관능" in row_lbl:
                        sens_ok = val

                exp_joined = ", ".join(dict.fromkeys(exp_list)) if exp_list else "-"
                is_running = (exp_joined != "-") or (chk_time not in ["-", ""])
                full_p_name = f"{p_name} ({vol_str})" if vol_str else p_name

                parsed_products.append({
                    "라인구분": line_label,
                    "작성일": w_date,
                    "가동여부": "🟢 금일생산" if is_running else "⚪ 미생산(00.00)",
                    "제품명": full_p_name,
                    "확인시간": chk_time,
                    "표기 소비기한": exp_joined,
                    "표시사항": label_ok,
                    "상부접착": top_ok,
                    "하부접착": bot_ok,
                    "제품용량": vol_ok,
                    "관능(5점법)": sens_ok
                })

    return pd.DataFrame(parsed_products), w_date


# [3-C] 두유 배양검사 일보 파서 (빈 블록 6~10 제외 & 체크박스 TRUE/라벨 문구 완전 제거)
SOY_STOP_LABELS = {
    "배양검사", "배양온도", "용량/포장기", "포장기", "작성자", "검사자",
    "품목", "생산일", "소비기한", "검사일", "생산시작", "생산종료",
    "총검사수량", "오염수량", "판정", "특이사항", "소비기한품목명표시",
    "확인시간", "제품명", "TRUE", "FALSE"
}


def calc_run_duration(start_str: str, end_str: str) -> str:
    m1 = re.search(r"(\d{1,2}):(\d{2})", str(start_str))
    m2 = re.search(r"(\d{1,2}):(\d{2})", str(end_str))
    if not m1 or not m2:
        return "-"
    s_min = int(m1.group(1)) * 60 + int(m1.group(2))
    e_min = int(m2.group(1)) * 60 + int(m2.group(2))
    if e_min < s_min:
        e_min += 24 * 60
    diff = e_min - s_min
    return f"{diff // 60}시간 {diff % 60:02d}분"


def extract_clean_right_values(sr: list, start_idx: int) -> list:
    out = []
    for raw_x in sr[start_idx + 1:]:
        xs = str(raw_x).strip()
        if not xs:
            continue
        norm_x = re.sub(r"\s+", "", xs).upper()
        if norm_x in SOY_STOP_LABELS or "소비기한품목명표시" in norm_x:
            break
        out.append(xs)
    return out


def parse_soy_incubation_worksheet(ws):
    if ws is None:
        return pd.DataFrame(), pd.DataFrame()
    rows = ws.get_all_values()
    if not rows:
        return pd.DataFrame(), pd.DataFrame()

    anchors = []
    for r_i, r in enumerate(rows):
        for c_i, cell in enumerate(r):
            if re.sub(r"\s+", "", str(cell)) == "배양검사":
                anchors.append((r_i, c_i))

    blocks_parsed = []
    hourly_all = []

    for idx, (r0, c0) in enumerate(anchors):
        same_row_next_c = [c for (rr, c) in anchors if abs(rr - r0) <= 2 and c > c0]
        c_end = min(same_row_next_c) if same_row_next_c else c0 + 14

        same_col_next_r = [rr for (rr, c) in anchors if abs(c - c0) <= 2 and rr > r0]
        r_end = min(same_col_next_r) if same_col_next_r else min(len(rows), r0 + 48)

        sub_rows = [list(rows[rr][c0:min(c_end, len(rows[rr]))]) for rr in range(r0, r_end)]

        inc_days, inc_temp, vol_ml, machine_ho = "", "", "", ""
        writer_nm, inspector_nm = "", ""
        item_names, exp_dates = [], []
        prod_dt, insp_dt, t_start, t_end, total_smp = "", "", "", "", ""
        contam_cnt, judge_res, remark_txt = "", "", ""

        for sr_i, sr in enumerate(sub_rows):
            for sc_i, val in enumerate(sr):
                key = re.sub(r"\s+", "", str(val))
                if not key:
                    continue
                right_vals = extract_clean_right_values(sr, sc_i)

                if key == "배양검사" and not inc_days and right_vals:
                    inc_days = right_vals[0]
                elif key == "배양온도" and not inc_temp and right_vals:
                    inc_temp = right_vals[0]
                elif ("용량/포장기" in key or key == "포장기") and not machine_ho:
                    for rv in right_vals[:3]:
                        if "호기" in rv and not machine_ho:
                            machine_ho = rv
                        elif re.search(r"^\d{2,4}$", rv.replace("mL", "").replace("㎖", "").strip()) and not vol_ml:
                            vol_ml = rv
                elif key == "작성자" and not writer_nm and right_vals:
                    writer_nm = right_vals[0]
                elif key == "검사자" and not inspector_nm and right_vals:
                    inspector_nm = right_vals[0]
                elif key == "품목":
                    for rv in right_vals:
                        if rv not in item_names:
                            item_names.append(rv)
                    if sr_i + 1 < len(sub_rows):
                        next_sr = sub_rows[sr_i + 1]
                        next_first = re.sub(r"\s+", "", str(next_sr[0])) if next_sr else ""
                        if next_first not in SOY_STOP_LABELS:
                            for rv in [str(x).strip() for x in next_sr if str(x).strip()]:
                                norm_rv = re.sub(r"\s+", "", rv).upper()
                                if norm_rv in SOY_STOP_LABELS or "소비기한품목명표시" in norm_rv:
                                    continue
                                if not re.search(r"^202\d", rv) and rv not in item_names:
                                    item_names.append(rv)
                elif key == "생산일" and not prod_dt and right_vals:
                    prod_dt = right_vals[0]
                elif key == "소비기한":
                    for rv in right_vals:
                        if re.search(r"\d{2,4}[\.\-/]\s*\d{1,2}[\.\-/]\s*\d{1,2}", rv) and rv not in exp_dates:
                            exp_dates.append(rv)
                elif key == "검사일" and not insp_dt and right_vals:
                    insp_dt = right_vals[0]
                elif key == "생산시작" and not t_start and right_vals:
                    if re.search(r"\d{1,2}:\d{2}", right_vals[0]):
                        t_start = right_vals[0]
                elif key == "생산종료" and not t_end and right_vals:
                    if re.search(r"\d{1,2}:\d{2}", right_vals[0]):
                        t_end = right_vals[0]
                elif key == "총검사수량" and not total_smp and right_vals:
                    if re.search(r"\d+", right_vals[0]):
                        total_smp = right_vals[0]
                elif key == "오염수량":
                    look_cells = right_vals[:]
                    if sr_i + 1 < len(sub_rows):
                        look_cells.extend([
                            str(x).strip() for x in sub_rows[sr_i + 1]
                            if str(x).strip() and re.sub(r"\s+", "", str(x)).upper() not in SOY_STOP_LABELS
                        ])
                    for lv in look_cells:
                        if ("개" in lv or lv.isdigit()) and not contam_cnt:
                            contam_cnt = lv
                        elif lv in ["적합", "부적합"] and not judge_res:
                            judge_res = lv
                elif key == "특이사항" and right_vals:
                    remark_txt = " ".join(right_vals)

            first_t = str(sr[0]).strip() if sr else ""
            if re.match(r"^\d{2}\s*:$", first_t) and machine_ho:
                smp_v = " ".join([str(x).strip() for x in sr[1:6] if str(x).strip()])
                strp_v = " ".join([str(x).strip() for x in sr[6:9] if str(x).strip()])
                pap_v = " ".join([str(x).strip() for x in sr[9:12] if str(x).strip()])
                if smp_v or strp_v or pap_v:
                    hourly_all.append({
                        "포장기": machine_ho,
                        "시간대": first_t,
                        "샘플체크": smp_v or "-",
                        "Strip": strp_v or "-",
                        "Paper": pap_v or "-"
                    })

        # 표기가 없는 빈 양식 블록(블록6~10 등)은 완전히 제외
        has_valid_record = bool(machine_ho) and (bool(item_names) or bool(total_smp) or bool(t_start))
        if not has_valid_record:
            continue

        blocks_parsed.append({
            "시트탭": ws.title.strip(),
            "포장기": machine_ho,
            "배양구분": f"{inc_days} ({inc_temp})".strip(" ()"),
            "용량(mL)": vol_ml or "-",
            "품목명": " / ".join(item_names) if item_names else "-",
            "생산일": prod_dt or "-",
            "소비기한": " / ".join(exp_dates) if exp_dates else "-",
            "검사일(개봉일)": insp_dt or "-",
            "생산 시작~종료": f"{t_start} ~ {t_end}" if (t_start or t_end) else "-",
            "실가동시간": calc_run_duration(t_start, t_end),
            "총 검사수량": total_smp or "0",
            "오염수량": contam_cnt or "0 개",
            "판정": judge_res or "적합",
            "작성/검사자": f"{writer_nm} / {inspector_nm}".strip(" /"),
            "특이사항": remark_txt or "없음"
        })

    return pd.DataFrame(blocks_parsed), pd.DataFrame(hourly_all)


def fetch_process_rt_sheet(creds, sheet_urls_map):
    sh_rt, err_rt = open_sheet_threadsafe(creds, sheet_urls_map, "process_rt")
    if sh_rt is None:
        return None, None, f"[상온공정일보] {err_rt}"
    try:
        ws_rt_today, ws_rt_yest, _ = get_sorted_date_worksheets(sh_rt)
        return parse_rt_process_worksheet(ws_rt_today), parse_rt_process_worksheet(ws_rt_yest), None
    except Exception as e:
        return None, None, f"[상온공정일보] {e}"


def fetch_process_milk_sheet(creds, sheet_urls_map):
    sh_milk, err_milk = open_sheet_threadsafe(creds, sheet_urls_map, "process_milk")
    if sh_milk is None:
        return pd.DataFrame(), pd.DataFrame(), "-", "-", f"[유제품포장일보] {err_milk}"
    try:
        ws_m, ws_f = None, None
        for w in sh_milk.worksheets():
            wt = w.title.strip()
            if "우유" in wt and "발효유" not in wt and ws_m is None:
                ws_m = w
            elif "발효유" in wt and ws_f is None:
                ws_f = w
        df_m, m_dt = parse_dairy_pack_worksheet(ws_m, "우유")
        df_f, f_dt = parse_dairy_pack_worksheet(ws_f, "발효유")
        return df_m, df_f, m_dt, f_dt, None
    except Exception as e:
        return pd.DataFrame(), pd.DataFrame(), "-", "-", f"[유제품포장일보] {e}"


def fetch_process_soy_sheet(creds, sheet_urls_map):
    sh_soy, err_soy = open_sheet_threadsafe(creds, sheet_urls_map, "process_soy")
    if sh_soy is None:
        return "-", {}, pd.DataFrame(), pd.DataFrame(), f"[두유배양일보] {err_soy}"
    try:
        ws_soy_t, ws_soy_y, soy_date_ws_list = get_sorted_date_worksheets(sh_soy)
        today_mmdd = datetime.now().strftime("%m. %d").replace("0", "").strip()

        default_soy_ws = ws_soy_y if ws_soy_y is not None else ws_soy_t
        soy_tabs_parsed = {}
        for w in soy_date_ws_list[:4]:
            df_b, df_h = parse_soy_incubation_worksheet(w)
            if not df_b.empty:
                soy_tabs_parsed[w.title.strip()] = (df_b, df_h)
                if df_b["검사일(개봉일)"].astype(str).str.contains(today_mmdd, na=False).any():
                    default_soy_ws = w

        def_title = default_soy_ws.title.strip() if default_soy_ws is not None else "-"
        if def_title not in soy_tabs_parsed and default_soy_ws is not None:
            soy_tabs_parsed[def_title] = parse_soy_incubation_worksheet(default_soy_ws)

        df_sb, df_sh = soy_tabs_parsed.get(def_title, (pd.DataFrame(), pd.DataFrame()))
        return def_title, soy_tabs_parsed, df_sb, df_sh, None
    except Exception as e:
        return "-", {}, pd.DataFrame(), pd.DataFrame(), f"[두유배양일보] {e}"


# [4] 협력업체 심사 결과 DB (시트2 마스터 + 시트1 실시간 점수 합산 매칭)
def fetch_supplier_sheet(creds, sheet_urls_map):
    sh, err = open_sheet_threadsafe(creds, sheet_urls_map, "supplier")
    if sh is None:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), err

    try:
        ws1 = sh.get_worksheet(0)
        rows1 = ws1.get_all_values()
        df_s1 = pd.DataFrame()
        if len(rows1) >= 2:
            hdr1 = [str(h).strip() for h in rows1[0]]
            data1 = [dict(zip(hdr1, (list(r) + [""] * len(hdr1))[:len(hdr1)])) for r in rows1[1:] if any(r)]
            df_s1 = pd.DataFrame(data1)

        ws2 = sh.get_worksheet(1)
        rows2 = ws2.get_all_values()
        if len(rows2) < 2:
            return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), df_s1, "협력업체 시트2(마스터 명단)가 비어 있습니다."

        exact_score_map = {}
        core_score_map = {}
        if not df_s1.empty and "업체명" in df_s1.columns and "심사항목" in df_s1.columns:
            df_s1["_norm_exact"] = df_s1["업체명"].apply(lambda x: normalize_comp_name(x, core_only=False))
            df_s1["_norm_core"] = df_s1["업체명"].apply(lambda x: normalize_comp_name(x, core_only=True))
            df_s1["_item_clean"] = df_s1["심사항목"].astype(str).str.strip()
            if "제출일시" in df_s1.columns:
                df_s1 = df_s1.sort_values("제출일시")
            df_dedup = df_s1.drop_duplicates(subset=["_norm_exact", "_item_clean"], keep="last")

            for norm_k, grp in df_dedup.groupby("_norm_exact"):
                if not norm_k:
                    continue
                total_pts = 0.0
                weak_items = []
                for _, s_row in grp.iterrows():
                    adm_str = str(s_row.get("관리자최종점수", "")).strip()
                    ai_str = str(s_row.get("AI판정결과", "")).strip()
                    target_str = adm_str if adm_str != "" else ai_str
                    m_pt = re.search(r"(\d+(?:\.\d+)?)\s*점", target_str)
                    pt_val = float(m_pt.group(1)) if m_pt else to_float(target_str, 0.0)
                    total_pts += pt_val

                    if any(w in target_str for w in ["부적합", "미흡", "누락", "0점"]):
                        clean_it = re.sub(r"^\[[^\]]+\]\s*\(\d+\)\s*", "", s_row["_item_clean"])
                        weak_items.append(clean_it)

                info_pack = {
                    "score": int(round(min(total_pts, 100.0))),
                    "weak_count": len(weak_items),
                    "weak_items": weak_items
                }
                exact_score_map[norm_k] = info_pack
                core_k = grp["_norm_core"].iloc[0]
                if core_k and core_k not in core_score_map:
                    core_score_map[core_k] = info_pack

        hdr2 = [str(c).replace(" ", "").strip() for c in rows2[0]]
        col_gubun = next((i for i, h in enumerate(hdr2) if "구분" in h), 0)
        col_comp = next((i for i, h in enumerate(hdr2) if "업체" in h), 1)
        col_item = next((i for i, h in enumerate(hdr2) if "품목" in h), 2)
        col_sc2 = next((i for i, h in enumerate(hdr2) if "점수" in h), -1)
        col_note2 = next((i for i, h in enumerate(hdr2) if "비고" in h), -1)

        temp_list = []
        for r in rows2[1:]:
            if not any(str(x).strip() for x in r):
                continue
            r_pad = list(r) + [""] * max(0, 6 - len(r))
            gubun = str(r_pad[col_gubun]).strip()
            comp = str(r_pad[col_comp]).strip()
            item = str(r_pad[col_item]).strip()
            if not comp:
                continue

            nk_exact = normalize_comp_name(comp, core_only=False)
            nk_core = normalize_comp_name(comp, core_only=True)
            matched = exact_score_map.get(nk_exact) or core_score_map.get(nk_core)

            s2_score_txt = str(r_pad[col_sc2]).strip() if col_sc2 >= 0 else ""
            s2_note_txt = str(r_pad[col_note2]).strip() if col_note2 >= 0 else ""

            if s2_score_txt != "":
                if s2_score_txt == "미제출":
                    sc_num, sc_disp = -1, "미제출"
                else:
                    sc_num = int(round(to_float(s2_score_txt, -1)))
                    sc_disp = str(sc_num) if sc_num >= 0 else "미제출"
                weak_cnt = matched["weak_count"] if matched else 0
                weak_list = matched["weak_items"] if matched else []
            elif matched is not None:
                sc_num = matched["score"]
                sc_disp = str(sc_num)
                weak_cnt = matched["weak_count"]
                weak_list = matched["weak_items"]
            else:
                sc_num, sc_disp = -1, "미제출"
                weak_cnt, weak_list = 0, []

            if sc_num >= 85:
                grade = "승인"
            elif sc_num >= 70:
                grade = "지도"
            else:
                grade = "등급 외"

            note_final = s2_note_txt if s2_note_txt else ("미제출" if sc_disp == "미제출" else ("복수거래, 거래중지 등 검토" if grade == "등급 외" else ""))
            temp_list.append({
                "_sort_sc": sc_num,
                "구분": gubun,
                "업체명": comp,
                "품목": item,
                "점수": sc_disp,
                "결과": grade,
                "비고": note_final,
                "_weak_cnt": weak_cnt,
                "_weak_list": weak_list
            })

        temp_list.sort(key=lambda x: x["_sort_sc"], reverse=True)
        master_records, under_comp_rows, under_detail_rows = [], [], []

        for i, rec in enumerate(temp_list, start=1):
            master_records.append({
                "NO": i,
                "구분": rec["구분"],
                "업체명": rec["업체명"],
                "품목": rec["품목"],
                "점수": rec["점수"],
                "결과": rec["결과"],
                "비고": rec["비고"]
            })
            if rec["결과"] == "등급 외":
                under_comp_rows.append({
                    "업체명": rec["업체명"],
                    "점수": f"{rec['점수']}점" if rec["점수"] != "미제출" else "미제출",
                    "미비 항목": f"{rec['_weak_cnt']}개" if rec["점수"] != "미제출" else "미제출",
                    "조치": "복수거래, 거래중지 등 검토"
                })
                if rec["_weak_list"]:
                    under_detail_rows.append({
                        "업체명": rec["업체명"],
                        "미비 사항 (시트1 실시간 판정 기준)": ", ".join(rec["_weak_list"])
                    })

        df_master = pd.DataFrame(master_records)
        cnt_ok = int((df_master["결과"] == "승인").sum())
        cnt_guide = int((df_master["결과"] == "지도").sum())
        cnt_out = int((df_master["결과"] == "등급 외").sum())
        cnt_unsub = int((df_master["점수"] == "미제출").sum())
        tot_sup = len(df_master)

        df_grade_sum = pd.DataFrame([
            {"등급": "승인", "점수": "85-100점", "업체수": cnt_ok, "조치": "승인"},
            {"등급": "지도", "점수": "70-84점", "업체수": cnt_guide, "조치": "업체별 개선사항 피드백"},
            {"등급": "등급 외", "점수": "70점미만, 미제출", "업체수": cnt_out, "조치": "복수거래, 거래중지 등 검토"},
            {"등급": "합계", "점수": "-", "업체수": tot_sup, "조치": f"제출 {tot_sup - cnt_unsub}개사 / 미제출 {cnt_unsub}개사"}
        ])

        return df_master, df_grade_sum, pd.DataFrame(under_comp_rows), pd.DataFrame(under_detail_rows), None
    except Exception as e:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), str(e)


# [6] 표시사항 현황 & [7] 원자재 표시사항 DB
def parse_factual_date(row_dict: dict):
    for col_key in ["등록일", "최종수정일", "완료일"]:
        raw = row_dict.get(col_key, "")
        if raw is None:
            continue
        s = str(raw).strip()
        if not s or "###" in s:
            continue
        if re.match(r"^\d{5}(\.\d+)?$", s):
            try:
                dt = datetime(1899, 12, 30) + timedelta(days=float(s))
                return dt.strftime("%Y-%m-%d"), f"{dt.year}년", f"{dt.month}월"
            except Exception:
                pass
        dt_parsed = pd.to_datetime(s, errors="coerce")
        if pd.notna(dt_parsed) and 2018 <= dt_parsed.year <= 2035:
            return dt_parsed.strftime("%Y-%m-%d"), f"{dt_parsed.year}년", f"{dt_parsed.month}월"

    return "원본날짜깨짐(#######)", "날짜미상", "날짜미상"


def classify_label_status(status_str: str) -> str:
    s = str(status_str).strip()
    if s == "식품안전팀 검토중":
        return "식품안전팀 검토중"
    if s in ["개시/준비", "보류", "검토/개시", ""]:
        return "제외(개시/준비·보류)"
    return "검토완료(확인필)"


def fetch_label_status_sheet(creds, sheet_urls_map):
    sh, err = open_sheet_threadsafe(creds, sheet_urls_map, "label_status")
    if sh is None:
        return pd.DataFrame(), err
    try:
        ws = sh.get_worksheet(0)
        rows = get_values_unformatted(ws)
        if len(rows) < 2:
            return pd.DataFrame(), "표시사항 현황 시트에 데이터가 없습니다."
        headers = [str(h).strip() for h in rows[0]]
        data = []
        for r in rows[1:]:
            if not any(str(x).strip() != "" for x in r):
                continue
            r_pad = [str(x).strip() for x in r] + [""] * max(0, len(headers) - len(r))
            item = dict(zip(headers, r_pad[:len(headers)]))
            dt_str, yr_str, mo_str = parse_factual_date(item)
            item["등록일자"] = dt_str
            item["등록연도"] = yr_str
            item["등록월"] = mo_str
            item["분류"] = classify_label_status(item.get("상태", ""))
            data.append(item)
        return pd.DataFrame(data), None
    except Exception as e:
        return pd.DataFrame(), str(e)


def fetch_raw_material_db_sheet(creds, sheet_urls_map):
    sh, err = open_sheet_threadsafe(creds, sheet_urls_map, "raw_label_db")
    if sh is None:
        return pd.DataFrame(), 0, err
    df_submitted = pd.DataFrame()
    total_master_count = 0
    try:
        ws_sub = sh.get_worksheet(0)
        rows_sub = ws_sub.get_all_values()
        if len(rows_sub) >= 2:
            headers = [str(h).strip() for h in rows_sub[0]]
            data = [dict(zip(headers, (list(r) + [""] * len(headers))[:len(headers)])) for r in rows_sub[1:] if any(r)]
            df_submitted = pd.DataFrame(data)
    except Exception:
        pass
    try:
        ws_master = sh.worksheet("전체 원재료 명단")
        rows_m = ws_master.get_all_values()
        total_master_count = max(len([r for r in rows_m[1:] if any(r)]), 0)
    except Exception:
        pass
    return df_submitted, total_master_count, None


# ==============================================================================
# 7. 최초 1회 병렬 로딩 엔진 (세션 메모리 영구 보관 -> 화면 전환 시 로딩 0초)
# ==============================================================================
def generate_ax_executive_briefing(summary_context_str: str) -> str:
    api_key = st.secrets.get("GEMINI_API_KEY", "")
    if GENAI_AVAILABLE and api_key and not str(api_key).startswith("여기에"):
        try:
            client = genai.Client(api_key=api_key)
            prompt = (
                "당신은 연세유업 아산공장 품질안전부문의 데이터 브리핑 AI입니다. "
                "추정이나 판단 없이 아래 실시간 시트 집계 수치만 인용하여 2문장 이내로 간결하게 요약하세요.\n\n"
                f"{summary_context_str}"
            )
            res = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
            if res and res.text:
                return res.text.strip()
        except Exception:
            pass
    return summary_context_str


def load_all_sheets_parallel() -> dict:
    creds, auth_err = build_google_credentials()
    sheet_urls_map = dict(st.secrets["sheet_urls"]) if "sheet_urls" in st.secrets else {}

    if creds is None:
        return {
            "df_cost": pd.DataFrame(),
            "cost_targets": {"부문": 1.54, "식품안전팀": 1.0, "품질관리팀": 0.54},
            "df_claim_trend": pd.DataFrame(),
            "df_claim_cat": pd.DataFrame(),
            "proc_data": {
                "rt_today": None, "rt_yest": None, "milk_date": "-", "ferm_date": "-",
                "df_milk_pack": pd.DataFrame(), "df_ferm_pack": pd.DataFrame(),
                "soy_default_tab": "-", "soy_tabs_map": {},
                "df_soy_blocks": pd.DataFrame(), "df_soy_hourly": pd.DataFrame()
            },
            "df_sup_master": pd.DataFrame(),
            "df_sup_grade": pd.DataFrame(),
            "df_sup_under_c": pd.DataFrame(),
            "df_sup_under_d": pd.DataFrame(),
            "df_label_status": pd.DataFrame(),
            "df_raw_sub": pd.DataFrame(),
            "raw_master_cnt": 0,
            "errors": [auth_err],
            "loaded_at": datetime.now().strftime("%Y. %m. %d %H:%M:%S")
        }

    with ThreadPoolExecutor(max_workers=7) as ex:
        f_cost = ex.submit(fetch_cost_sheet, creds, sheet_urls_map)
        f_claim = ex.submit(fetch_claim_sheet, creds, sheet_urls_map)
        f_rt = ex.submit(fetch_process_rt_sheet, creds, sheet_urls_map)
        f_milk = ex.submit(fetch_process_milk_sheet, creds, sheet_urls_map)
        f_soy = ex.submit(fetch_process_soy_sheet, creds, sheet_urls_map)
        f_sup = ex.submit(fetch_supplier_sheet, creds, sheet_urls_map)
        f_lbl = ex.submit(fetch_label_status_sheet, creds, sheet_urls_map)
        f_raw = ex.submit(fetch_raw_material_db_sheet, creds, sheet_urls_map)

        df_cost, cost_targets, err_cost = f_cost.result()
        df_claim_trend, df_claim_cat, err_claim = f_claim.result()
        rt_today, rt_yest, err_rt = f_rt.result()
        df_milk, df_ferm, milk_dt, ferm_dt, err_milk = f_milk.result()
        soy_def_tab, soy_map, df_soy_b, df_soy_h, err_soy = f_soy.result()
        df_sup_m, df_sup_g, df_sup_uc, df_sup_ud, err_sup = f_sup.result()
        df_lbl, err_lbl = f_lbl.result()
        df_raw_sub, raw_m_cnt, err_raw = f_raw.result()

    errors = []
    for label_nm, er in [
        ("원가절감", err_cost), ("클레임", err_claim), ("협력업체", err_sup),
        ("표시사항 현황", err_lbl), ("원자재 DB", err_raw)
    ]:
        if er:
            errors.append(f"[{label_nm}] {er}")
    for p_er in [err_rt, err_milk, err_soy]:
        if p_er:
            errors.append(p_er)

    return {
        "df_cost": df_cost,
        "cost_targets": cost_targets,
        "df_claim_trend": df_claim_trend,
        "df_claim_cat": df_claim_cat,
        "proc_data": {
            "rt_today": rt_today,
            "rt_yest": rt_yest,
            "milk_date": milk_dt,
            "ferm_date": ferm_dt,
            "df_milk_pack": df_milk,
            "df_ferm_pack": df_ferm,
            "soy_default_tab": soy_def_tab,
            "soy_tabs_map": soy_map,
            "df_soy_blocks": df_soy_b,
            "df_soy_hourly": df_soy_h
        },
        "df_sup_master": df_sup_m,
        "df_sup_grade": df_sup_g,
        "df_sup_under_c": df_sup_uc,
        "df_sup_under_d": df_sup_ud,
        "df_label_status": df_lbl,
        "df_raw_sub": df_raw_sub,
        "raw_master_cnt": raw_m_cnt,
        "errors": errors,
        "loaded_at": datetime.now().strftime("%Y. %m. %d %H:%M:%S")
    }


def trigger_manual_sync():
    st.cache_data.clear()
    st.session_state.pop("kpi_bundle", None)
    st.session_state.pop("ax_brief_text", None)


if "kpi_bundle" not in st.session_state:
    with st.spinner("구글 시트 실시간 데이터를 병렬로 불러오는 중입니다 (최초 1회)..."):
        st.session_state["kpi_bundle"] = load_all_sheets_parallel()

bundle = st.session_state["kpi_bundle"]
df_cost = bundle["df_cost"]
cost_targets = bundle["cost_targets"]
df_claim_trend = bundle["df_claim_trend"]
df_claim_cat = bundle["df_claim_cat"]
proc_data = bundle["proc_data"]
df_sup_master = bundle["df_sup_master"]
df_sup_grade = bundle["df_sup_grade"]
df_sup_under_c = bundle["df_sup_under_c"]
df_sup_under_d = bundle["df_sup_under_d"]
df_label_status = bundle["df_label_status"]
df_raw_sub = bundle["df_raw_sub"]
raw_master_cnt = bundle["raw_master_cnt"]
all_load_errors = bundle["errors"]


# ==============================================================================
# 8. 차트 유틸리티 및 KPI 요약 지표 계산
# ==============================================================================
def draw_mini_bar(target_val, actual_val, suffix="", bar_labels=("목표", "실적"), empty_mode=False):
    fig = go.Figure()
    if not empty_mode:
        fig.add_trace(go.Bar(
            x=[bar_labels[0]], y=[target_val], text=[f"{target_val}{suffix}"],
            textposition="inside", insidetextanchor="end", marker_color="#7F7F7F", width=0.35,
            textfont=dict(color="white", size=12, family="Malgun Gothic")
        ))
        fig.add_trace(go.Bar(
            x=[bar_labels[1]], y=[actual_val], text=[f"{actual_val}{suffix}"],
            textposition="inside", insidetextanchor="end", marker_color="#ED7D31", width=0.35,
            textfont=dict(color="white", size=12, family="Malgun Gothic")
        ))
    max_y = max(target_val, actual_val) * 1.28 if (not empty_mode and max(target_val, actual_val) > 0) else 10
    fig.update_layout(
        height=150, margin=dict(l=15, r=15, t=6, b=20),
        paper_bgcolor="#F2F2F2", plot_bgcolor="#F2F2F2", showlegend=False,
        xaxis=dict(showgrid=False, zeroline=False, tickfont=dict(size=12, color="#222222")),
        yaxis=dict(showgrid=False, zeroline=True, zerolinecolor="#D9D9D9", showticklabels=False, range=[0, max_y])
    )
    return fig


# (1) 원가절감 요약
cost_target_uk = cost_targets["부문"]
cost_actual_man = round(float(df_cost["부문_실적(만원)"].sum()), 1) if not df_cost.empty else 0.0
cost_actual_uk = round(cost_actual_man / 10000, 2)
cost_rate = round((cost_actual_uk / cost_target_uk) * 100, 1) if cost_target_uk > 0 else 0.0
cost_act_line, cost_fc_line, cost_full_line, cost_slope, cost_m_cnt, cost_last_i = calc_trend_and_forecast_split(
    df_cost["부문_실적(만원)"].tolist() if not df_cost.empty else [],
    df_cost["_기록여부"].tolist() if not df_cost.empty and "_기록여부" in df_cost.columns else None
)
cost_proj_man = round(cost_actual_man + sum(cost_full_line[cost_last_i + 1:]), 1) if (0 <= cost_last_i < 11) else cost_actual_man
cost_proj_uk = round(cost_proj_man / 10000, 2)
sig_cost = "green" if (cost_actual_uk >= cost_target_uk or cost_proj_uk >= cost_target_uk) else ("red" if not df_cost.empty else "gray")

# (2) 클레임 요약
claim_target_ppm = 1.12
row_26_sum = df_claim_cat[(df_claim_cat["연도"] == "2026년") & (df_claim_cat["유형"] == "합계")] if not df_claim_cat.empty else pd.DataFrame()
claim_actual_ppm = float(row_26_sum["합계_PPM"].values[0]) if not row_26_sum.empty else 0.0
claim_total_cnt = int(row_26_sum["합계_건수"].values[0]) if not row_26_sum.empty else 0
claim_act_line, claim_fc_line, claim_full_line, claim_slope, claim_m_cnt, claim_last_i = calc_trend_and_forecast_split(
    df_claim_trend["2026년_PPM"].tolist() if not df_claim_trend.empty else [],
    df_claim_trend["_기록여부"].tolist() if not df_claim_trend.empty and "_기록여부" in df_claim_trend.columns else None
)
claim_feb_pred = claim_full_line[-1] if claim_full_line else 0.0
if row_26_sum.empty:
    sig_claim = "gray"
elif claim_actual_ppm > claim_target_ppm:
    sig_claim = "red"
elif claim_slope > 0.03:
    sig_claim = "yellow"
else:
    sig_claim = "green"

# (3) 공정 요약
rt_t = proc_data["rt_today"]
rt_y = proc_data["rt_yest"]
rt_t_tab = rt_t["tab_title"] if rt_t else "-"
rt_y_tab = rt_y["tab_title"] if rt_y else "-"
rt_t_lines = rt_t["lines_records"] if rt_t else []
active_rt_cnt = sum(1 for r in rt_t_lines if r["생산 제품명"] != "(비가동)")
wait_rt_cnt = sum(1 for r in rt_t_lines if r["_cls"] == "cell-yellow")
red_rt_cnt = sum(1 for r in rt_t_lines if r["_cls"] == "cell-red") + (
    sum(1 for sr in rt_t["ster_records"] if "cell-red" in (sr["_c_temp"], sr["_c_press"], sr["_c_hold"], sr["_c_flt"])) if rt_t else 0
)
active_milk_cnt = len(proc_data["df_milk_pack"][proc_data["df_milk_pack"]["가동여부"].str.contains("금일생산", na=False)]) if not proc_data["df_milk_pack"].empty else 0
active_ferm_cnt = len(proc_data["df_ferm_pack"][proc_data["df_ferm_pack"]["가동여부"].str.contains("금일생산", na=False)]) if not proc_data["df_ferm_pack"].empty else 0
soy_blocks_cnt = len(proc_data["df_soy_blocks"])
if rt_t is None:
    sig_process = "gray"
elif red_rt_cnt > 0:
    sig_process = "red"
elif wait_rt_cnt > 0 or (rt_t and len(rt_t["ster_special_notes"]) > 0):
    sig_process = "yellow"
else:
    sig_process = "green"

# (4) 협력업체 요약
target_exec = 88.3
total_sup_cnt = len(df_sup_master)
unsub_sup_cnt = int((df_sup_master["점수"] == "미제출").sum()) if not df_sup_master.empty else 0
sub_sup_cnt = total_sup_cnt - unsub_sup_cnt
sup_exec_rate = round((sub_sup_cnt / total_sup_cnt) * 100, 1) if total_sup_cnt > 0 else 0.0
ok_sup_cnt = int((df_sup_master["결과"] == "승인").sum()) if not df_sup_master.empty else 0
guide_sup_cnt = int((df_sup_master["결과"] == "지도").sum()) if not df_sup_master.empty else 0
out_sup_cnt = int((df_sup_master["결과"] == "등급 외").sum()) if not df_sup_master.empty else 0
sig_supplier = "green" if sup_exec_rate >= target_exec else ("red" if total_sup_cnt > 0 else "gray")

# (6) 표시사항 진행 현황 요약
if not df_label_status.empty:
    df_rev_now = df_label_status[df_label_status["분류"] == "식품안전팀 검토중"]
    df_comp_now = df_label_status[df_label_status["분류"] == "검토완료(확인필)"]
    reviewing_cnt = len(df_rev_now)
    completed_cnt = len(df_comp_now)
    broken_date_cnt = int((df_label_status["등록연도"] == "날짜미상").sum())
    rep_titles = df_rev_now["제목"].head(4).tolist() if "제목" in df_rev_now.columns else []
else:
    reviewing_cnt, completed_cnt, broken_date_cnt, rep_titles = 0, 0, 0, []
sig_label = "yellow" if reviewing_cnt >= 5 else ("green" if not df_label_status.empty else "gray")

# (7) 원자재 표시사항 DB 요약
sub_raw_cnt = len(df_raw_sub)
verified_raw_cnt = len(df_raw_sub[df_raw_sub["검증상태"].astype(str).str.contains("완료|적합", na=False)]) if ("검증상태" in df_raw_sub.columns and not df_raw_sub.empty) else 0
allergy_raw_cnt = len(df_raw_sub[df_raw_sub["신규알레르기"].astype(str).str.strip() != ""]) if ("신규알레르기" in df_raw_sub.columns and not df_raw_sub.empty) else 0
sig_raw = "yellow" if allergy_raw_cnt > 0 else ("green" if not df_raw_sub.empty or raw_master_cnt > 0 else "gray")

if "ax_brief_text" not in st.session_state:
    brief_ctx = (
        f"[원가절감] 누적 {cost_actual_uk}억({cost_rate}%), 연말 추세 예측 {cost_proj_uk}억 | "
        f"[클레임] 2026년 누적 {claim_actual_ppm}ppm({claim_total_cnt}건), 2월 예상 추세 {claim_feb_pred}ppm | "
        f"[공정] 상온({rt_t_tab}) {active_rt_cnt}건 가동, 유제품 {active_milk_cnt + active_ferm_cnt}품목 생산, 배양개봉({proc_data['soy_default_tab']}) {soy_blocks_cnt}개 호기 점검 | "
        f"[협력업체] {total_sup_cnt}개사 중 {sub_sup_cnt}개사 제출({sup_exec_rate}%) | "
        f"[표시사항] 완료 {completed_cnt}건, 현재 검토중 {reviewing_cnt}건"
    )
    st.session_state["ax_brief_text"] = generate_ax_executive_briefing(brief_ctx)


# ==============================================================================
# [화면 1] 메인 Summary 대시보드 (콜백 네비게이션으로 즉시 전환)
# ==============================================================================
if st.session_state.current_view == "main":
    top_c1, top_c2 = st.columns([8.3, 1.7])
    with top_c1:
        st.markdown("""
            <div class="main-title">
                <span>2026 업적 KPI 현황판_품질안전부문 (AX 스마트 대시보드)</span>
                <span style="font-size: 20px;">Summary</span>
            </div>
        """, unsafe_allow_html=True)
    with top_c2:
        st.button("🔄 시트 실시간 동기화", on_click=trigger_manual_sync, key="btn_sync_top")

    st.markdown(
        f"<div class='sub-date'>(동기화 시각 : {bundle['loaded_at']} | 신호등: 🟢양호 🟡주의/특이사항 🔴경고)</div>",
        unsafe_allow_html=True
    )

    if all_load_errors:
        with st.expander(f"⚠️ 시트 연동 점검 필요 항목 ({len(all_load_errors)}건)", expanded=True):
            for err_line in all_load_errors:
                st.write(f"- {err_line}")

    st.markdown(
        f"<div class='ax-banner'><b>🤖 실시간 시트 데이터 종합 요약</b><br>{html.escape(st.session_state['ax_brief_text'])}</div>",
        unsafe_allow_html=True
    )

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.markdown(f"""
        <div class="kpi-card">
            <div class="kpi-header">1. 원가 절감</div>
            <div class="kpi-body">
                {get_signal_dot_html(sig_cost)}
                <div><span class="kpi-bullet">●</span><b>목표 : {cost_target_uk}억원 이상</b></div>
                <div><span class="kpi-bullet">●</span><b>실적 : {cost_actual_uk}억원 ({cost_rate}%)</b></div>
                <div class="ai-line">📈 추세 예측 : 연말 {cost_proj_uk}억</div>
            </div>
            <div class="unit-label">(단위 : 억원)</div>
        </div>
        """, unsafe_allow_html=True)
        st.plotly_chart(draw_mini_bar(cost_target_uk, cost_actual_uk), use_container_width=True, config={"displayModeBar": False})
        st.button("🔍 1. 원가 절감 상세 (팀별/추세예측)", key="btn_cost", on_click=set_view, args=("cost",))

    with col2:
        st.markdown(f"""
        <div class="kpi-card">
            <div class="kpi-header">2. 클레임 발생률</div>
            <div class="kpi-body">
                {get_signal_dot_html(sig_claim)}
                <div><span class="kpi-bullet">●</span><b>목표 : {claim_target_ppm} ppm이하</b></div>
                <div><span class="kpi-bullet">●</span><b>실적 : {claim_actual_ppm} ppm ({claim_total_cnt:,}건)</b></div>
                <div class="ai-line">📈 월 기울기 {claim_slope:+.2f} / 2월 예상 {claim_feb_pred}ppm</div>
            </div>
            <div class="unit-label">(단위 : ppm)</div>
        </div>
        """, unsafe_allow_html=True)
        st.plotly_chart(draw_mini_bar(claim_target_ppm, claim_actual_ppm), use_container_width=True, config={"displayModeBar": False})
        st.button("🔍 2. 클레임 상세 (전사예측/부문별)", key="btn_claim", on_click=set_view, args=("claim",))

    with col3:
        t_note_cnt = len(rt_t["ster_special_notes"]) + len(rt_t["df_issues"]) if rt_t else 0
        st.markdown(f"""
        <div class="kpi-card">
            <div class="kpi-header">3. 공정 현황 및 특이사항</div>
            <div class="kpi-body">
                {get_signal_dot_html(sig_process)}
                <div><span class="kpi-bullet">●</span><b>상온({rt_t_tab}) : {active_rt_cnt}건 가동 / 특이사항 {t_note_cnt}건</b></div>
                <div><span class="kpi-bullet">●</span><b>우유·발효유 : 금일 {active_milk_cnt + active_ferm_cnt}품목 생산</b></div>
                <div class="ai-line">🧪 배양({proc_data['soy_default_tab']}) : {soy_blocks_cnt}개 호기 적합</div>
            </div>
            <div class="unit-label">(단위 : 건/품목)</div>
        </div>
        """, unsafe_allow_html=True)
        st.plotly_chart(
            draw_mini_bar(active_rt_cnt + active_milk_cnt, max(active_rt_cnt - wait_rt_cnt, 0) + active_milk_cnt, bar_labels=("금일가동", "확인완료")),
            use_container_width=True, config={"displayModeBar": False}
        )
        st.button("🔍 3. 금일·전일 공정 및 배양 관제", key="btn_process", on_click=set_view, args=("process",))

    with col4:
        st.markdown(f"""
        <div class="kpi-card">
            <div class="kpi-header">4. 협력업체 관리</div>
            <div class="kpi-body">
                {get_signal_dot_html(sig_supplier)}
                <div><span class="kpi-bullet">●</span><b>목표 : {target_exec}% 이상 (대상 {total_sup_cnt}개사)</b></div>
                <div><span class="kpi-bullet">●</span><b>제출 : {sub_sup_cnt}개사 ({sup_exec_rate}% / 미제출 {unsub_sup_cnt})</b></div>
                <div class="ai-line">📊 승인 {ok_sup_cnt} / 지도 {guide_sup_cnt} / 등급외 {out_sup_cnt}</div>
            </div>
            <div class="unit-label">(단위 : %)</div>
        </div>
        """, unsafe_allow_html=True)
        st.plotly_chart(draw_mini_bar(target_exec, sup_exec_rate, suffix="%"), use_container_width=True, config={"displayModeBar": False})
        st.button("🔍 4. 협력업체 서류심사 상세", key="btn_supplier", on_click=set_view, args=("supplier",))

    col5, col6, col7 = st.columns([1, 1.5, 1.5])

    with col5:
        st.markdown(f"""
        <div class="kpi-card">
            <div class="kpi-header">5. 심사점수</div>
            <div class="kpi-body">
                {get_signal_dot_html("gray")}
                <div><span class="kpi-bullet">●</span><b>목표 : -</b></div>
                <div><span class="kpi-bullet">●</span><b>실적 : -</b></div>
                <div><span class="kpi-bullet">●</span><b>대비 : -</b></div>
            </div>
            <div class="unit-label">(단위 : 점)</div>
        </div>
        """, unsafe_allow_html=True)
        st.plotly_chart(draw_mini_bar(0, 0, empty_mode=True), use_container_width=True, config={"displayModeBar": False})
        st.button("🔍 5. 심사점수 상세", key="btn_audit", on_click=set_view, args=("audit",))

    with col6:
        rep_html = "".join([f"<div>• {html.escape(t[:44])}{'...' if len(t) > 44 else ''}</div>" for t in rep_titles]) if rep_titles else "<div>• 현재 검토중 품목 없음</div>"
        st.markdown(f"""
        <div class="kpi-card">
            <div class="kpi-header">6. 표시사항 진행 현황</div>
            <div class="kpi-body" style="min-height: 280px;">
                {get_signal_dot_html(sig_label)}
                <div><span class="kpi-bullet">●</span><b>검토 완료(확인필) : 누적 {completed_cnt:,}건</b> <span style="font-size:12px; color:#555;">(개시/준비·보류 제외)</span></div>
                <div><span class="kpi-bullet">●</span><b style="color:#C00000;">현재 식품안전팀 검토중 : {reviewing_cnt:,}건</b> <span style="font-size:12px; color:#555;">(시트 총 {len(df_label_status):,}행)</span></div>
                <div class="rep-list-box">
                    <b>📌 현재 검토중 대표 품목 (실시간)</b>
                    {rep_html}
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)
        st.button("🔍 6. 표시사항 진행 상세 (연도·월별 완료 & 등록팀별)", key="btn_label_status", on_click=set_view, args=("label_status",))

    with col7:
        st.markdown(f"""
        <div class="kpi-card">
            <div class="kpi-header">7. 표시사항 특이사항 (원자재 DB 현황)</div>
            <div class="kpi-body" style="min-height: 280px;">
                {get_signal_dot_html(sig_raw)}
                <div><span class="kpi-bullet">●</span><b>원자재 표시사항 등록 : {sub_raw_cnt:,}건</b> {f'(전체 명단 {raw_master_cnt:,}건)' if raw_master_cnt > 0 else ''}</div>
                <div><span class="kpi-bullet">●</span><b>검증 완료 : {verified_raw_cnt:,}건 / 신규 알레르기 체크 : {allergy_raw_cnt:,}건</b></div>
                <div class="rep-list-box">
                    <b>✓ 원자재 표시사항 DB 실시간 관리 항목</b>
                    <div>• 원재료 한글표시사항·원산지·제조원·공급사(판매원) 교차검증</div>
                    <div>• 기존 알레르기 vs 신규 알레르기 변경 원료 추적</div>
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)
        st.button("🔍 7. 원자재 표시사항 DB 상세", key="btn_label_issue", on_click=set_view, args=("label_issue",))


# ==============================================================================
# [화면 2] 세부 페이지 (세션 메모리 즉시 렌더링 -> 로딩 지연 0초)
# ==============================================================================
else:
    nav_c1, nav_c2 = st.columns([8.3, 1.7])
    with nav_c1:
        st.button("⬅️ 전체 Summary 현황판으로 돌아가기", key="btn_back_main", on_click=set_view, args=("main",))
    with nav_c2:
        st.button("🔄 시트 실시간 동기화", key="btn_sync_sub", on_click=trigger_manual_sync)

    view = st.session_state.current_view

    # --------------------------------------------------------------------------
    # [세부 1] 원가 절감 (식품안전팀 G열 & 품질관리팀 L열 정확 반영 + 잔여월 예측)
    # --------------------------------------------------------------------------
    if view == "cost":
        st.markdown("<div class='main-title'>1. 원가 절감 - 월별/팀별 실시간 실적 및 잔여월 추세 예측</div>", unsafe_allow_html=True)
        if df_cost.empty:
            st.error("원가절감 현황 시트 데이터를 불러오지 못했습니다.")
        else:
            fs_sum = round(float(df_cost["식품안전팀_실적(만원)"].sum()), 1)
            qc_sum = round(float(df_cost["품질관리팀_실적(만원)"].sum()), 1)
            m1, m2, m3, m4 = st.columns(4)
            m1.metric(f"품질안전부문 누적 (목표 {cost_targets['부문']}억)", f"{cost_actual_man:,.1f} 만원 ({cost_actual_uk}억)", f"달성률 {cost_rate}%")
            m2.metric(f"식품안전팀 누적 (목표 {cost_targets['식품안전팀']}억)", f"{fs_sum:,.1f} 만원", f"달성률 {round(fs_sum / (cost_targets['식품안전팀'] * 10000) * 100, 1)}%")
            m3.metric(f"품질관리팀 누적 (목표 {cost_targets['품질관리팀']}억)", f"{qc_sum:,.1f} 만원", f"달성률 {round(qc_sum / (cost_targets['품질관리팀'] * 10000) * 100, 1)}%")
            m4.metric("연말(2월말) 추세 예상치", f"{cost_proj_man:,.1f} 만원 ({cost_proj_uk}억)", f"월 기울기 {cost_slope:+.1f}만/월")

            fig_cost = go.Figure()
            fig_cost.add_trace(go.Bar(
                x=df_cost["월"], y=df_cost["식품안전팀_실적(만원)"],
                name="식품안전팀 실적(만원)", marker_color="#2E75B6",
                text=df_cost["식품안전팀_실적(만원)"], textposition="inside"
            ))
            fig_cost.add_trace(go.Bar(
                x=df_cost["월"], y=df_cost["품질관리팀_실적(만원)"],
                name="품질관리팀 실적(만원)", marker_color="#ED7D31",
                text=df_cost["품질관리팀_실적(만원)"], textposition="inside"
            ))
            fig_cost.add_trace(go.Scatter(
                x=df_cost["월"], y=df_cost["부문_기준(만원)"],
                name="부문 월 기준", mode="lines", line=dict(color="#C00000", width=2.5, dash="dash")
            ))
            fig_cost.add_trace(go.Scatter(
                x=df_cost["월"], y=cost_act_line,
                name="실적 회귀 추세선", mode="lines+markers", line=dict(color="#7030A0", width=3)
            ))
            if cost_last_i < 11:
                fig_cost.add_trace(go.Scatter(
                    x=df_cost["월"], y=cost_fc_line,
                    name="AI 잔여월 예상 추세선", mode="lines+markers+text",
                    text=[f"{v:.0f}" if (v is not None and idx > cost_last_i) else "" for idx, v in enumerate(cost_fc_line)],
                    textposition="top center",
                    line=dict(color="#00B0F0", width=3, dash="dot"),
                    marker=dict(symbol="diamond", size=9)
                ))
            fig_cost.update_layout(barmode="stack", height=430, title="📊 3월~2월 팀별 원가절감 실적 및 잔여월 예상 추세도 (단위: 만원)")
            st.plotly_chart(fig_cost, use_container_width=True)

            disp_cost = df_cost.drop(columns=["_기록여부"], errors="ignore")
            st.dataframe(disp_cost, use_container_width=True, hide_index=True)

    # --------------------------------------------------------------------------
    # [세부 2] 클레임 발생률 (1탭: 전사 추이 & AI 예상 추세도 최우선 배치 -> 2탭: 부문별)
    # --------------------------------------------------------------------------
    elif view == "claim":
        st.markdown("<div class='main-title'>2. 클레임 발생률 - 전사 월별 추이·예상 추세도 및 부문별 상세 분석</div>", unsafe_allow_html=True)
        if df_claim_cat.empty:
            st.error("클레임 건수 시트 데이터를 불러오지 못했습니다.")
        else:
            avail_claim_years = sorted(df_claim_cat["연도"].unique().tolist(), reverse=True)
            tab_c1, tab_c2, tab_c3 = st.tabs([
                "📈 전사 클레임 월별 추이 및 AI 예상 추세도 (2025 vs 2026)",
                "🏭 부문별 월단위 분석 및 예상 추세도 (유제품생산부문 vs 상온제품부문)",
                "🥛 전체 제품 유형별 상세 집계표"
            ])

            # [탭 1] 전사 클레임 추이 (최우선 첫 탭) + 실적 추세선 + 잔여월 예상 추세선
            with tab_c1:
                sub_26_cats = df_claim_cat[(df_claim_cat["연도"] == "2026년") & (df_claim_cat["유형"] != "합계")]
                top_cat_txt = "-"
                if not sub_26_cats.empty:
                    top_r = sub_26_cats.sort_values("합계_건수", ascending=False).iloc[0]
                    top_cat_txt = f"{top_r['유형']} ({int(top_r['합계_건수']):,}건, {top_r['합계_PPM']}ppm)"

                ck1, ck2, ck3, ck4 = st.columns(4)
                ck1.metric("2026년 전사 누적 클레임", f"{claim_total_cnt:,} 건")
                ck2.metric("2026년 전사 누적 PPM (목표 1.12)", f"{claim_actual_ppm} ppm", "목표 이내" if claim_actual_ppm <= claim_target_ppm else "목표 초과")
                ck3.metric("월별 PPM 추세 기울기", f"{claim_slope:+.2f} ppm/월")
                ck4.metric("회계연도 말(2월) 예상 PPM", f"{claim_feb_pred:.2f} ppm", f"현재 기록 {claim_m_cnt}개월 기준")

                rem_months_str = ", ".join(FISCAL_MONTHS[claim_last_i + 1:]) if 0 <= claim_last_i < 11 else "없음"
                pred_vals_str = ", ".join([
                    f"{FISCAL_MONTHS[i]} {claim_full_line[i]:.2f}ppm"
                    for i in range(claim_last_i + 1, 12)
                ]) if 0 <= claim_last_i < 11 else "연간 집계 완료"

                st.markdown(f"""
                <div class="forecast-box">
                    <b>🤖 전사 클레임 실시간 추세 및 AI 예상 추세 진단 (팩트 수치 기준)</b><br>
                    • <b>실적 추세 :</b> 현재 기록된 {claim_m_cnt}개월 누적 발생률은 <b>{claim_actual_ppm} ppm</b>(총 {claim_total_cnt:,}건)이며, 월평균 증감 기울기는 <b>{claim_slope:+.2f} ppm/월</b>입니다. (최다 발생 유형: {html.escape(top_cat_txt)})<br>
                    • <b>잔여월 예상 추세 ({rem_months_str}) :</b> 현재 선형 추세 연장 시 <b>{pred_vals_str}</b> 흐름으로 2월 말 당월 예상치는 <b>{claim_feb_pred:.2f} ppm</b>입니다.
                </div>
                """, unsafe_allow_html=True)

                fig_cl = go.Figure()
                fig_cl.add_trace(go.Bar(
                    x=df_claim_trend["월"], y=df_claim_trend["2025년_PPM"],
                    name="2025년 실적 PPM", marker_color="#BFBFBF",
                    text=df_claim_trend["2025년_PPM"], textposition="outside"
                ))
                fig_cl.add_trace(go.Bar(
                    x=df_claim_trend["월"], y=df_claim_trend["2026년_PPM"],
                    name="2026년 실적 PPM", marker_color="#ED7D31",
                    text=[v if flag else "" for v, flag in zip(df_claim_trend["2026년_PPM"], df_claim_trend["_기록여부"])],
                    textposition="outside"
                ))
                fig_cl.add_trace(go.Scatter(
                    x=df_claim_trend["월"], y=df_claim_trend["목표_PPM"],
                    name="2026 목표 기준 (1.12 ppm)", mode="lines",
                    line=dict(color="#C00000", width=2.5, dash="dash")
                ))
                fig_cl.add_trace(go.Scatter(
                    x=df_claim_trend["월"], y=claim_act_line,
                    name="2026 실적 추세선", mode="lines+markers",
                    line=dict(color="#7030A0", width=3)
                ))
                if 0 <= claim_last_i < 11:
                    fig_cl.add_trace(go.Scatter(
                        x=df_claim_trend["월"], y=claim_fc_line,
                        name="AI 예상 추세선 (잔여월 예측)", mode="lines+markers+text",
                        text=[f"예상 {v:.2f}" if (v is not None and idx > claim_last_i) else "" for idx, v in enumerate(claim_fc_line)],
                        textposition="top center",
                        line=dict(color="#0070C0", width=3, dash="dot"),
                        marker=dict(symbol="diamond", size=9, color="#0070C0")
                    ))
                fig_cl.update_layout(barmode="group", height=440, title="📊 전사 2025년 vs 2026년 월별 클레임 PPM 및 잔여월 AI 예상 추세도")
                st.plotly_chart(fig_cl, use_container_width=True)

                disp_cl_trend = df_claim_trend.drop(columns=["_기록여부"], errors="ignore").copy()
                disp_cl_trend["추세/예상_PPM"] = claim_full_line
                st.dataframe(disp_cl_trend, use_container_width=True, hide_index=True)

            # [탭 2] 부문별 월단위 분석 및 예상 추세도
            with tab_c2:
                cc1, cc2 = st.columns([1.2, 2.2])
                with cc1:
                    div_year = st.radio("조회 연도", avail_claim_years, horizontal=True, key="div_yr")
                with cc2:
                    div_sel = st.radio(
                        "조회 부문",
                        ["🥛 유제품생산부문 (냉장우유 카톤·병 / 발효유·음료 카톤·병)", "🧃 상온제품부문 (상온 멸균팩 / 상온 프리즈마)", "⚖️ 양 부문 통합 비교"],
                        horizontal=True, key="div_sel"
                    )

                df_dairy_m, df_dairy_raw = build_division_claim_df(df_claim_cat, div_year, DAIRY_CATEGORIES)
                df_rt_m, df_rt_raw = build_division_claim_df(df_claim_cat, div_year, RT_CATEGORIES)

                if "유제품생산부문" in div_sel:
                    t_df_m, t_df_raw, t_cats, d_lbl = df_dairy_m, df_dairy_raw, DAIRY_CATEGORIES, f"{div_year} 유제품생산부문"
                elif "상온제품부문" in div_sel:
                    t_df_m, t_df_raw, t_cats, d_lbl = df_rt_m, df_rt_raw, RT_CATEGORIES, f"{div_year} 상온제품부문"
                else:
                    t_df_m, t_df_raw, t_cats, d_lbl = None, None, [], f"{div_year} 유제품생산부문 vs 상온제품부문"

                if t_df_m is not None:
                    tot_c = int(t_df_m["합산_건수"].sum())
                    tot_p = int(t_df_m["합산_생산수량"].sum())
                    tot_ppm = round((tot_c / tot_p) * 1_000_000, 2) if tot_p > 0 else 0.0
                    d_act_l, d_fc_l, d_full_l, d_slp, d_mcnt, d_last_i = calc_trend_and_forecast_split(
                        t_df_m["부문_통합_PPM"].tolist(),
                        t_df_m["_기록여부"].tolist()
                    )

                    k1, k2, k3, k4 = st.columns(4)
                    k1.metric("부문 누적 건수", f"{tot_c:,} 건")
                    k2.metric("부문 누적 생산량", f"{tot_p:,} 개")
                    k3.metric("부문 통합 PPM", f"{tot_ppm} ppm")
                    k4.metric("2월 예상 PPM (월 기울기)", f"{d_full_l[-1]:.2f} ppm", f"{d_slp:+.2f} ppm/월")

                    d_pred_txt = ", ".join([f"{FISCAL_MONTHS[i]} {d_full_l[i]:.2f}ppm" for i in range(d_last_i + 1, 12)]) if 0 <= d_last_i < 11 else "연간 집계 완료"
                    st.markdown(f"""
                    <div class="forecast-box">
                        <b>📌 {d_lbl} 추세 및 예상 추세 요약 :</b> 누적 <b>{tot_ppm} ppm</b> ({tot_c:,}건 / {tot_p:,}개) | 월 기울기 <b>{d_slp:+.2f} ppm/월</b> | 잔여월 예상: <b>{d_pred_txt}</b>
                    </div>
                    """, unsafe_allow_html=True)

                    fig_div = make_subplots(specs=[[{"secondary_y": True}]])
                    colors = ["#2E75B6", "#5B9BD5", "#ED7D31", "#F4B183"]
                    for i, cat in enumerate(t_cats):
                        fig_div.add_trace(
                            go.Bar(
                                x=t_df_m["월"], y=t_df_m[f"{cat}_건수"], name=f"{cat} 건수",
                                marker_color=colors[i % 4], text=t_df_m[f"{cat}_건수"], textposition="inside"
                            ),
                            secondary_y=False
                        )
                    fig_div.add_trace(
                        go.Scatter(
                            x=t_df_m["월"], y=t_df_m["부문_통합_PPM"], name="부문 통합 PPM",
                            mode="lines+markers+text",
                            text=[v if flag else "" for v, flag in zip(t_df_m["부문_통합_PPM"], t_df_m["_기록여부"])],
                            textposition="top center", line=dict(color="#C00000", width=3)
                        ),
                        secondary_y=True
                    )
                    fig_div.add_trace(
                        go.Scatter(
                            x=t_df_m["월"], y=d_act_l, name="실적 추세선",
                            mode="lines", line=dict(color="#7030A0", width=2.5)
                        ),
                        secondary_y=True
                    )
                    if 0 <= d_last_i < 11:
                        fig_div.add_trace(
                            go.Scatter(
                                x=t_df_m["월"], y=d_fc_l, name="AI 예상 추세선(잔여월)",
                                mode="lines+markers+text",
                                text=[f"{v:.2f}" if (v is not None and idx > d_last_i) else "" for idx, v in enumerate(d_fc_l)],
                                textposition="bottom center",
                                line=dict(color="#0070C0", width=3, dash="dot"),
                                marker=dict(symbol="diamond", size=8)
                            ),
                            secondary_y=True
                        )
                    fig_div.update_layout(barmode="stack", height=430, title=f"📊 {d_lbl} 월단위 건수 및 통합 PPM·예상 추세도")
                    fig_div.update_yaxes(title_text="클레임 건수(건)", secondary_y=False)
                    fig_div.update_yaxes(title_text="PPM", secondary_y=True)
                    st.plotly_chart(fig_div, use_container_width=True)

                    st.dataframe(t_df_m.drop(columns=["_기록여부"], errors="ignore"), use_container_width=True, hide_index=True)
                    st.dataframe(t_df_raw, use_container_width=True, hide_index=True)
                else:
                    _, dairy_fc, _, _, _, d_li = calc_trend_and_forecast_split(df_dairy_m["부문_통합_PPM"].tolist(), df_dairy_m["_기록여부"].tolist())
                    _, rt_fc, _, _, _, r_li = calc_trend_and_forecast_split(df_rt_m["부문_통합_PPM"].tolist(), df_rt_m["_기록여부"].tolist())
                    fig_cmp = make_subplots(specs=[[{"secondary_y": True}]])
                    fig_cmp.add_trace(go.Bar(x=df_dairy_m["월"], y=df_dairy_m["합산_건수"], name="유제품생산 건수", marker_color="#2E75B6"), secondary_y=False)
                    fig_cmp.add_trace(go.Bar(x=df_rt_m["월"], y=df_rt_m["합산_건수"], name="상온제품 건수", marker_color="#ED7D31"), secondary_y=False)
                    fig_cmp.add_trace(go.Scatter(x=df_dairy_m["월"], y=df_dairy_m["부문_통합_PPM"], name="유제품생산 PPM", mode="lines+markers", line=dict(color="#002060", width=3)), secondary_y=True)
                    fig_cmp.add_trace(go.Scatter(x=df_rt_m["월"], y=df_rt_m["부문_통합_PPM"], name="상온제품 PPM", mode="lines+markers", line=dict(color="#C00000", width=3)), secondary_y=True)
                    if 0 <= d_li < 11:
                        fig_cmp.add_trace(go.Scatter(x=df_dairy_m["월"], y=dairy_fc, name="유제품 예상 추세", mode="lines+markers", line=dict(color="#002060", width=2, dash="dot")), secondary_y=True)
                    if 0 <= r_li < 11:
                        fig_cmp.add_trace(go.Scatter(x=df_rt_m["월"], y=rt_fc, name="상온 예상 추세", mode="lines+markers", line=dict(color="#C00000", width=2, dash="dot")), secondary_y=True)
                    fig_cmp.update_layout(barmode="group", height=430, title=f"📊 {d_lbl} (실적 및 잔여월 예상 추세)")
                    st.plotly_chart(fig_cmp, use_container_width=True)

            with tab_c3:
                yr_opt = st.radio("연도 필터", avail_claim_years + ["전체"], horizontal=True, key="all_cat_yr")
                df_cv = df_claim_cat if yr_opt == "전체" else df_claim_cat[df_claim_cat["연도"] == yr_opt]
                st.dataframe(df_cv, use_container_width=True, hide_index=True)

    # --------------------------------------------------------------------------
    # [세부 3] 공정 현황 및 특이사항 (가로 스크롤 제거 + 특이사항 최상단 배너 + 초록/노랑/빨강 모니터링 표)
    # --------------------------------------------------------------------------
    elif view == "process":
        st.markdown("<div class='main-title'>3. 공정 현황 및 특이사항 - 금일·전일 생산 및 CCP·배양 실시간 관제</div>", unsafe_allow_html=True)

        tab_p1, tab_p2, tab_p3 = st.tabs([
            f"🧃 [상온] 상온제품 공정 관리 일보 (금일 {rt_t_tab} & 전일 {rt_y_tab})",
            "🥛 [우유/발효유] 유제품 포장 공정관리 일보",
            f"🧪 [상온] 두유 배양검사 일보 (기준탭: {proc_data['soy_default_tab']})"
        ])

        # [탭 1] 상온제품 공정 관리 일보
        with tab_p1:
            if rt_t is None:
                st.warning("상온제품 공정 관리 일보 시트 데이터를 불러오지 못했습니다.")
            else:
                # 1) 최상단 금일 vs 전일 특이사항 전문 브리핑 배너 (가로 스크롤 없이 100% 전문 노출)
                b_left, b_right = st.columns(2)
                with b_left:
                    today_notes = list(rt_t["ster_special_notes"])
                    if not rt_t["df_issues"].empty:
                        for _, ir in rt_t["df_issues"].head(3).iterrows():
                            today_notes.append(f"[전달사항 {ir['기록일자']}] {ir['전달(특이)사항 및 소비기한 조치내역']}")
                    if today_notes:
                        notes_html = "<br>".join([f"• {html.escape(n)}" for n in today_notes])
                        st.markdown(f"<div class='issue-card-warn'><b>⚠️ 금일 [{html.escape(rt_t['tab_title'])}] 현장 특이사항 및 설비 조치 ({len(today_notes)}건)</b><br>{notes_html}</div>", unsafe_allow_html=True)
                    else:
                        st.markdown(f"<div class='issue-card-ok'><b>🟢 금일 [{html.escape(rt_t['tab_title'])}] 현장 특이사항 없음</b><br>• 가동 호기 및 멸균기 특이사항 없이 정상 생산 중입니다.</div>", unsafe_allow_html=True)

                with b_right:
                    if rt_y is not None:
                        yest_notes = list(rt_y["ster_special_notes"])
                        if not rt_y["df_issues"].empty:
                            for _, ir in rt_y["df_issues"].head(3).iterrows():
                                yest_notes.append(f"[전달사항 {ir['기록일자']}] {ir['전달(특이)사항 및 소비기한 조치내역']}")
                        if yest_notes:
                            yn_html = "<br>".join([f"• {html.escape(n)}" for n in yest_notes])
                            st.markdown(f"<div class='issue-card-warn'><b>📌 전일 [{html.escape(rt_y['tab_title'])}] 마감 특이사항 기록 ({len(yest_notes)}건)</b><br>{yn_html}</div>", unsafe_allow_html=True)
                        else:
                            st.markdown(f"<div class='issue-card-ok'><b>🟢 전일 [{html.escape(rt_y['tab_title'])}] 전 호기 특이사항 없이 정상 생산 마감</b><br>• 전일 설비 이상 및 품질 특이사항 기록 없음</div>", unsafe_allow_html=True)

                # 2) 금일 포장호기(A~F) 모니터링 표 (전체 폭, 자동 줄바꿈, 초록/노랑/회색 하이라이트)
                st.subheader(f"🟢 금일 [{rt_t['tab_title']}] 포장호기별 생산 제품·소비기한·확인시간 ({rt_t['prod_date']})")
                pack_cols = [
                    {"key": "ho", "label": "포장호기", "width": "10%", "align": "center"},
                    {"key": "prod", "label": "생산 제품명", "width": "44%", "align": "left"},
                    {"key": "exp", "label": "소비기한", "width": "16%", "align": "center"},
                    {"key": "time", "label": "확인시간", "width": "16%", "align": "center"},
                    {"key": "st", "label": "모니터링 상태", "width": "14%", "align": "center"}
                ]
                pack_rows_html = [
                    {
                        "ho": {"text": r["포장호기"], "cls": r["_cls"] if r["_cls"] == "cell-gray" else ""},
                        "prod": {"text": r["생산 제품명"], "cls": r["_cls"] if r["_cls"] == "cell-gray" else ""},
                        "exp": {"text": r["소비기한"], "cls": "cell-green" if r["_cls"] == "cell-green" else r["_cls"]},
                        "time": {"text": r["확인시간"], "cls": r["_cls"]},
                        "st": {"text": r["상태"], "cls": r["_cls"]}
                    }
                    for r in rt_t["lines_records"]
                ]
                st.markdown(render_html_table(pack_cols, pack_rows_html), unsafe_allow_html=True)

                # 3) 금일 멸균기 [CCP-1B / CCP-2P] + 우측 S~V열 기준 통합 관제 표 (가로 스크롤 없음)
                st.subheader(f"🔥 금일 [{rt_t['tab_title']}] 멸균기 실시간 모니터링 [CCP-1B / CCP-2P] (우측 S~V열 제품 기준 자동 대조)")
                ster_cols = [
                    {"key": "s_ho", "label": "멸균기 (포장)", "width": "9%", "align": "center"},
                    {"key": "prod", "label": "매칭 제품명 (용량)", "width": "22%", "align": "left"},
                    {"key": "time", "label": "확인시간", "width": "7%", "align": "center"},
                    {"key": "temp", "label": "멸균온도 [실측 (기준)]", "width": "13%", "align": "center"},
                    {"key": "press", "label": "균질압 [실측 (기준)]", "width": "11%", "align": "center"},
                    {"key": "hold", "label": "멸균시간 [실측 (기준)]", "width": "10%", "align": "center"},
                    {"key": "flow", "label": "처리량 / 냉각온도", "width": "10%", "align": "center"},
                    {"key": "flt", "label": "여과망 / 서명", "width": "8%", "align": "center"},
                    {"key": "rem", "label": "특이사항 (전문)", "width": "10%", "align": "left"}
                ]
                ster_rows_html = [
                    {
                        "s_ho": {"text": sr["멸균기_포장"], "cls": ""},
                        "prod": {"text": sr["매칭 제품명"], "cls": ""},
                        "time": {"text": sr["확인시간"], "cls": sr["_c_time"]},
                        "temp": {"text": sr["멸균온도"], "cls": sr["_c_temp"]},
                        "press": {"text": sr["균질압"], "cls": sr["_c_press"]},
                        "hold": {"text": sr["멸균시간"], "cls": sr["_c_hold"]},
                        "flow": {"text": sr["유량_냉각"], "cls": ""},
                        "flt": {"text": sr["여과망_서명"], "cls": sr["_c_flt"]},
                        "rem": {"text": sr["특이사항"], "cls": sr["_c_rem"]}
                    }
                    for sr in rt_t["ster_records"]
                ]
                st.markdown(render_html_table(ster_cols, ster_rows_html), unsafe_allow_html=True)

                # 4) 금일 포장기 공정관리 [CCP-3B] 표 (구간 복구 + 초록/빨강 범위 판정)
                st.subheader(f"🛡️ 금일 [{rt_t['tab_title']}] 포장기 공정관리 [CCP-3B] (농도·분사량·온도·E빔)")
                ccp3b_cols = [
                    {"key": "item", "label": "점검항목", "width": "10%", "align": "center"},
                    {"key": "std", "label": "관리기준", "width": "14%", "align": "center"},
                    {"key": "eq", "label": "적용설비", "width": "10%", "align": "center"},
                    {"key": "A호기", "label": "A호기", "width": "11%", "align": "center"},
                    {"key": "B호기", "label": "B호기", "width": "11%", "align": "center"},
                    {"key": "C호기", "label": "C호기", "width": "11%", "align": "center"},
                    {"key": "D호기", "label": "D호기", "width": "11%", "align": "center"},
                    {"key": "E호기", "label": "E호기", "width": "11%", "align": "center"},
                    {"key": "F호기", "label": "F호기", "width": "11%", "align": "center"}
                ]
                ccp3b_rows_html = []
                for r3 in rt_t["ccp3b_records"]:
                    row_obj = {
                        "item": {"text": r3["항목"], "cls": ""},
                        "std": {"text": r3["관리기준"], "cls": ""},
                        "eq": {"text": r3["적용설비"], "cls": ""}
                    }
                    for ho_nm in ["A호기", "B호기", "C호기", "D호기", "E호기", "F호기"]:
                        v_txt = r3.get(ho_nm, "-")
                        c_cls = eval_ccp3b_cell(v_txt, r3["관리기준"], ho_nm in rt_t["running_hos"])
                        row_obj[ho_nm] = {"text": v_txt, "cls": c_cls}
                    ccp3b_rows_html.append(row_obj)
                st.markdown(render_html_table(ccp3b_cols, ccp3b_rows_html), unsafe_allow_html=True)

                # 5) 전일 마감 생산 내역 및 특이사항 전체 폭 표 (오른쪽 잘림 완전 해소)
                if rt_y is not None:
                    st.markdown("---")
                    st.subheader(f"☑️ 전일 [{rt_y['tab_title']}] 마감 생산 제품 및 멸균·특이사항 전체 내역 ({rt_y['prod_date']})")
                    yest_cols = [
                        {"key": "ho", "label": "포장호기", "width": "8%", "align": "center"},
                        {"key": "prod", "label": "생산 제품명", "width": "28%", "align": "left"},
                        {"key": "exp", "label": "소비기한", "width": "12%", "align": "center"},
                        {"key": "time", "label": "확인시간", "width": "11%", "align": "center"},
                        {"key": "ster", "label": "멸균기·CCP 요약", "width": "21%", "align": "center"},
                        {"key": "rem", "label": "전일 특이사항 (전문)", "width": "20%", "align": "left"}
                    ]
                    yest_rows_html = [
                        {
                            "ho": {"text": yr["포장호기"], "cls": ""},
                            "prod": {"text": yr["생산 제품명"], "cls": ""},
                            "exp": {"text": yr["소비기한"], "cls": "cell-green"},
                            "time": {"text": yr["확인시간"], "cls": yr["_cls_status"]},
                            "ster": {"text": yr["멸균기·CCP 요약"], "cls": "cell-green" if yr["멸균기·CCP 요약"] != "-" else ""},
                            "rem": {"text": yr["특이사항"], "cls": yr["_cls_rem"]}
                        }
                        for yr in rt_y["compact_rows"]
                    ]
                    st.markdown(render_html_table(yest_cols, yest_rows_html), unsafe_allow_html=True)

        # [탭 2] 유제품 포장 공정관리 일보 (초록/노랑/빨강 셀 색상 적용)
        with tab_p2:
            sub_m, sub_f = st.tabs([f"🥛 우유 포장 ({proc_data['milk_date']})", f"🍶 발효유 포장 ({proc_data['ferm_date']})"])
            dairy_cols = [
                {"key": "run", "label": "가동상태", "width": "11%", "align": "center"},
                {"key": "prod", "label": "제품명 (용량)", "width": "27%", "align": "left"},
                {"key": "time", "label": "확인시간", "width": "10%", "align": "center"},
                {"key": "exp", "label": "표기 소비기한", "width": "17%", "align": "center"},
                {"key": "c1", "label": "표시사항", "width": "7%", "align": "center"},
                {"key": "c2", "label": "상부접착", "width": "7%", "align": "center"},
                {"key": "c3", "label": "하부접착", "width": "7%", "align": "center"},
                {"key": "c4", "label": "제품용량", "width": "7%", "align": "center"},
                {"key": "c5", "label": "관능", "width": "7%", "align": "center"}
            ]

            def build_dairy_html_rows(df_d: pd.DataFrame):
                out_r = []
                for _, dr in df_d.iterrows():
                    running = "금일생산" in str(dr["가동여부"])
                    row_cls = "cell-green" if running else "cell-gray"

                    def chk_cls(v):
                        vs = str(v).strip()
                        if "부적합" in vs:
                            return "cell-red"
                        if vs not in ["", "-"]:
                            return "cell-green"
                        return "cell-yellow" if running else "cell-gray"

                    out_r.append({
                        "run": {"text": dr["가동여부"], "cls": row_cls},
                        "prod": {"text": dr["제품명"], "cls": "" if running else "cell-gray"},
                        "time": {"text": dr["확인시간"], "cls": chk_cls(dr["확인시간"])},
                        "exp": {"text": dr["표기 소비기한"], "cls": "cell-green" if running and dr["표기 소비기한"] != "-" else ("cell-gray" if not running else "cell-yellow")},
                        "c1": {"text": dr["표시사항"], "cls": chk_cls(dr["표시사항"])},
                        "c2": {"text": dr["상부접착"], "cls": chk_cls(dr["상부접착"])},
                        "c3": {"text": dr["하부접착"], "cls": chk_cls(dr["하부접착"])},
                        "c4": {"text": dr["제품용량"], "cls": chk_cls(dr["제품용량"])},
                        "c5": {"text": dr["관능(5점법)"], "cls": chk_cls(dr["관능(5점법)"])}
                    })
                return out_r

            with sub_m:
                only_run_m = st.checkbox("금일 실제 생산 품목만 보기 (00.00 제외)", value=True, key="chk_milk")
                df_m_v = proc_data["df_milk_pack"]
                if only_run_m and not df_m_v.empty:
                    df_m_v = df_m_v[df_m_v["가동여부"].str.contains("금일생산", na=False)]
                st.markdown(render_html_table(dairy_cols, build_dairy_html_rows(df_m_v)), unsafe_allow_html=True)

            with sub_f:
                only_run_f = st.checkbox("금일 실제 생산 품목만 보기 (00.00 제외)", value=True, key="chk_ferm")
                df_f_v = proc_data["df_ferm_pack"]
                if only_run_f and not df_f_v.empty:
                    df_f_v = df_f_v[df_f_v["가동여부"].str.contains("금일생산", na=False)]
                st.markdown(render_html_table(dairy_cols, build_dairy_html_rows(df_f_v)), unsafe_allow_html=True)

        # [탭 3] 두유 배양검사 일보 (빈 블록 제외 완료 + 초록색 적합 표시 + 가로 스크롤 제거)
        with tab_p3:
            soy_map = proc_data["soy_tabs_map"]
            if not soy_map:
                st.warning("두유 배양검사 일보 날짜 탭 데이터를 불러오지 못했습니다.")
            else:
                tab_keys = list(soy_map.keys())
                def_idx = tab_keys.index(proc_data["soy_default_tab"]) if proc_data["soy_default_tab"] in tab_keys else 0
                sel_soy_tab = st.selectbox("조회할 배양검사 날짜 탭 선택 (전일 작성분 기본 선택)", tab_keys, index=def_idx)
                df_sb, df_sh = soy_map[sel_soy_tab]

                tot_samples = sum(int(to_float(x, 0)) for x in df_sb["총 검사수량"]) if not df_sb.empty else 0
                st.subheader(f"🔬 [{sel_soy_tab} 탭] 기록된 호기별 배양 개봉 판독 및 가동시간·검사수량 (총 {tot_samples:,}개)")

                soy_cols = [
                    {"key": "ho", "label": "포장기", "width": "7%", "align": "center"},
                    {"key": "inc", "label": "배양구분", "width": "11%", "align": "center"},
                    {"key": "vol", "label": "용량", "width": "6%", "align": "center"},
                    {"key": "item", "label": "품목명", "width": "24%", "align": "left"},
                    {"key": "pdt", "label": "생산일", "width": "9%", "align": "center"},
                    {"key": "exp", "label": "소비기한", "width": "9%", "align": "center"},
                    {"key": "idt", "label": "검사일", "width": "9%", "align": "center"},
                    {"key": "time", "label": "가동시간", "width": "10%", "align": "center"},
                    {"key": "qty", "label": "검사수량", "width": "6%", "align": "center"},
                    {"key": "cntm", "label": "오염", "width": "4%", "align": "center"},
                    {"key": "jdg", "label": "판정", "width": "5%", "align": "center"}
                ]
                soy_rows_html = []
                for _, sr in df_sb.iterrows():
                    is_zero_contam = to_float(sr["오염수량"], 0) == 0
                    jdg_txt = str(sr["판정"]).strip()
                    jdg_cls = "cell-green" if jdg_txt == "적합" else ("cell-red" if "부적합" in jdg_txt else "cell-yellow")
                    soy_rows_html.append({
                        "ho": {"text": sr["포장기"], "cls": ""},
                        "inc": {"text": sr["배양구분"], "cls": ""},
                        "vol": {"text": sr["용량(mL)"], "cls": ""},
                        "item": {"text": sr["품목명"], "cls": ""},
                        "pdt": {"text": sr["생산일"], "cls": ""},
                        "exp": {"text": sr["소비기한"], "cls": ""},
                        "idt": {"text": sr["검사일(개봉일)"], "cls": ""},
                        "time": {"text": f"{sr['생산 시작~종료']}\n({sr['실가동시간']})", "cls": ""},
                        "qty": {"text": sr["총 검사수량"], "cls": "cell-green"},
                        "cntm": {"text": sr["오염수량"], "cls": "cell-green" if is_zero_contam else "cell-red"},
                        "jdg": {"text": jdg_txt, "cls": jdg_cls}
                    })
                st.markdown(render_html_table(soy_cols, soy_rows_html), unsafe_allow_html=True)

                if not df_sh.empty:
                    with st.expander("⏰ 시간대별(08시~07시) 샘플·Strip·Paper 체크 상세 보기"):
                        st.dataframe(df_sh, use_container_width=True, hide_index=True)

    # --------------------------------------------------------------------------
    # [세부 4] 협력업체 관리
    # --------------------------------------------------------------------------
    elif view == "supplier":
        st.markdown("<div class='main-title'>4. 협력업체 관리 - 서류심사 실시간 집계 및 미비사항</div>", unsafe_allow_html=True)
        if df_sup_master.empty:
            st.error("협력업체 심사 결과 DB를 불러오지 못했습니다.")
        else:
            st.dataframe(df_sup_grade, use_container_width=True, hide_index=True)

            fc1, fc2, fc3 = st.columns(3)
            with fc1:
                g_opts = ["전체"] + sorted(df_sup_master["구분"].dropna().unique().tolist())
                sel_g = st.selectbox("구분 필터", g_opts)
            with fc2:
                sel_r = st.selectbox("결과 필터", ["전체", "승인", "지도", "등급 외"])
            with fc3:
                kw_s = st.text_input("업체명 / 품목 검색")

            df_sf = df_sup_master.copy()
            if sel_g != "전체":
                df_sf = df_sf[df_sf["구분"] == sel_g]
            if sel_r != "전체":
                df_sf = df_sf[df_sf["결과"] == sel_r]
            if kw_s:
                df_sf = df_sf[df_sf["업체명"].str.contains(kw_s, case=False, na=False) | df_sf["품목"].str.contains(kw_s, case=False, na=False)]

            st.dataframe(df_sf, use_container_width=True, hide_index=True, height=385)

            st.subheader("■ 등급 외 업체 주요 미비사항")
            uc1, uc2 = st.columns([1, 1.4])
            with uc1:
                st.dataframe(df_sup_under_c, use_container_width=True, hide_index=True)
            with uc2:
                st.dataframe(df_sup_under_d, use_container_width=True, hide_index=True)

    # --------------------------------------------------------------------------
    # [세부 5] 심사점수 (빈칸 유지)
    # --------------------------------------------------------------------------
    elif view == "audit":
        st.markdown("<div class='main-title'>5. 심사점수</div>", unsafe_allow_html=True)
        st.info("현재 연동된 구글 시트가 없어 빈칸으로 유지 중입니다.")
        st.dataframe(pd.DataFrame([{"구분": "-", "목표": "-", "실적": "-", "비고": "-"}]), use_container_width=True, hide_index=True)

    # --------------------------------------------------------------------------
    # [세부 6] 표시사항 진행 현황
    # --------------------------------------------------------------------------
    elif view == "label_status":
        st.markdown("<div class='main-title'>6. 표시사항 진행 현황 - 현재 검토중(등록팀별) 및 연도·월별 완료 집계</div>", unsafe_allow_html=True)
        if df_label_status.empty:
            st.error("표시사항 현황 시트 데이터를 불러오지 못했습니다.")
        else:
            if broken_date_cnt > 0:
                st.warning(f"시트 원본 셀에 텍스트 '#######'로 저장되어 날짜를 읽을 수 없는 행이 {broken_date_cnt}건 있습니다. 원본 엑셀에서 등록일 열 너비를 넓혀 다시 붙여넣으시면 연도·월별 차트에 즉시 반영됩니다.")

            k1, k2, k3, k4 = st.columns(4)
            k1.metric("전체 등록 건수", f"{len(df_label_status):,} 건")
            k2.metric("🔴 현재 식품안전팀 검토중", f"{reviewing_cnt:,} 건")
            k3.metric("🟢 누적 검토 완료", f"{completed_cnt:,} 건")
            excl_cnt = int((df_label_status["분류"] == "제외(개시/준비·보류)").sum())
            k4.metric("⚪ 개시/준비·보류 (제외)", f"{excl_cnt:,} 건")

            st.subheader(f"🔴 현재 [식품안전팀 검토중] 실시간 목록 ({reviewing_cnt}건)")
            show_cols = [c for c in ["*docNo", "상태", "제목", "요청부서", "대분류(마케팅 카테고리)", "보관방법", "생산처", "검토 포장재 유형", "등록일자", "최종수정자"] if c in df_label_status.columns]
            rc1, rc2 = st.columns([2.2, 1])
            with rc1:
                st.dataframe(df_label_status[df_label_status["분류"] == "식품안전팀 검토중"][show_cols], use_container_width=True, hide_index=True)
            with rc2:
                if "요청부서" in df_label_status.columns:
                    rev_dept = df_label_status[df_label_status["분류"] == "식품안전팀 검토중"].groupby("요청부서").size().reset_index(name="검토중_건수")
                    fig_rd = go.Figure(go.Bar(x=rev_dept["요청부서"], y=rev_dept["검토중_건수"], marker_color="#C00000", text=rev_dept["검토중_건수"], textposition="auto"))
                    fig_rd.update_layout(height=260, title="📌 등록팀별 현재 검토중 건수", margin=dict(t=40, b=10, l=10, r=10))
                    st.plotly_chart(fig_rd, use_container_width=True)

            st.markdown("---")
            df_valid_lb = df_label_status[df_label_status["분류"] != "제외(개시/준비·보류)"]
            yc1, yc2 = st.columns([1, 2])
            with yc1:
                st.subheader("📊 연도별 완료 및 검토중 건수")
                yr_grp = df_valid_lb.groupby(["등록연도", "분류"]).size().unstack(fill_value=0).reset_index()
                for cname in ["검토완료(확인필)", "식품안전팀 검토중"]:
                    if cname not in yr_grp.columns:
                        yr_grp[cname] = 0
                yr_grp["합계"] = yr_grp["검토완료(확인필)"] + yr_grp["식품안전팀 검토중"]
                fig_yr = go.Figure()
                fig_yr.add_trace(go.Bar(x=yr_grp["등록연도"], y=yr_grp["검토완료(확인필)"], name="검토완료", marker_color="#44546A", text=yr_grp["검토완료(확인필)"], textposition="auto"))
                fig_yr.add_trace(go.Bar(x=yr_grp["등록연도"], y=yr_grp["식품안전팀 검토중"], name="검토중", marker_color="#ED7D31", text=yr_grp["식품안전팀 검토중"], textposition="auto"))
                fig_yr.update_layout(barmode="stack", height=320)
                st.plotly_chart(fig_yr, use_container_width=True)
                st.dataframe(yr_grp, use_container_width=True, hide_index=True)

            with yc2:
                real_years = [y for y in sorted(df_valid_lb["등록연도"].unique().tolist(), reverse=True) if y != "날짜미상"]
                sel_lb_yr = st.radio("월별 집계 연도 선택", ["전체 연도"] + real_years, horizontal=True)
                df_mb = df_valid_lb if sel_lb_yr == "전체 연도" else df_valid_lb[df_valid_lb["등록연도"] == sel_lb_yr]
                m_list = []
                for ms in CALENDAR_MONTHS:
                    d_cnt = int(((df_mb["등록월"] == ms) & (df_mb["분류"] == "검토완료(확인필)")).sum())
                    i_cnt = int(((df_mb["등록월"] == ms) & (df_mb["분류"] == "식품안전팀 검토중")).sum())
                    m_list.append({"월": ms, "검토완료(확인필)": d_cnt, "식품안전팀 검토중": i_cnt, "합계": d_cnt + i_cnt})
                df_m_lb = pd.DataFrame(m_list)
                fig_ml = go.Figure()
                fig_ml.add_trace(go.Bar(x=df_m_lb["월"], y=df_m_lb["검토완료(확인필)"], name="검토완료", marker_color="#2E75B6", text=df_m_lb["검토완료(확인필)"], textposition="auto"))
                fig_ml.add_trace(go.Bar(x=df_m_lb["월"], y=df_m_lb["식품안전팀 검토중"], name="검토중", marker_color="#ED7D31", text=df_m_lb["식품안전팀 검토중"], textposition="auto"))
                fig_ml.update_layout(barmode="stack", height=320, title=f"📈 {sel_lb_yr} 월별(1~12월) 완료 및 검토중 건수")
                st.plotly_chart(fig_ml, use_container_width=True)
                st.dataframe(df_m_lb, use_container_width=True, hide_index=True)

            if "요청부서" in df_valid_lb.columns:
                st.subheader("🏢 등록팀(요청부서)별 누적 완료 및 검토중 현황")
                dept_df = df_valid_lb.groupby(["요청부서", "분류"]).size().unstack(fill_value=0).reset_index()
                for cname in ["검토완료(확인필)", "식품안전팀 검토중"]:
                    if cname not in dept_df.columns:
                        dept_df[cname] = 0
                dept_df["합계"] = dept_df["검토완료(확인필)"] + dept_df["식품안전팀 검토중"]
                dept_df = dept_df.sort_values("합계", ascending=False)
                st.dataframe(dept_df, use_container_width=True, hide_index=True)

            st.subheader("📋 표시사항 현황 전체 목록 조회")
            st.dataframe(df_label_status[show_cols + ["분류", "등록연도", "등록월"]], use_container_width=True, hide_index=True, height=400)

    # --------------------------------------------------------------------------
    # [세부 7] 표시사항 특이사항 (원자재 표시사항 DB 단독 구성)
    # --------------------------------------------------------------------------
    elif view == "label_issue":
        st.markdown("<div class='main-title'>7. 표시사항 특이사항 - 원자재 표시사항 DB 검증 및 알레르기 현황</div>", unsafe_allow_html=True)
        r1, r2, r3 = st.columns(3)
        r1.metric("전체 원재료 마스터 수", f"{raw_master_cnt:,} 건")
        r2.metric("원자재 표시사항 등록 건수", f"{sub_raw_cnt:,} 건")
        r3.metric("신규 알레르기 감지 건수", f"{allergy_raw_cnt:,} 건")

        if df_raw_sub.empty:
            st.info("현재 '원자재 표시사항 DB'의 제출 시트에 데이터가 비어 있거나 시트 연동 확인이 필요합니다.")
        else:
            raw_kw = st.text_input("🔍 원재료명 / 제조원 / 공급사(판매원) 검색")
            df_rv = df_raw_sub[df_raw_sub.astype(str).apply(lambda x: x.str.contains(raw_kw, case=False, na=False)).any(axis=1)] if raw_kw else df_raw_sub
            st.dataframe(df_rv, use_container_width=True, hide_index=True)
