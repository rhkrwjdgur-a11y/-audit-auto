import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import gspread
from google.oauth2.credentials import Credentials as OAuthCredentials
from google.auth.transport.requests import Request
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from datetime import datetime, timedelta
import re

try:
    from google import genai
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False

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
# 2. 커스텀 CSS
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
# 3. Google Sheets 인증 및 공통 유틸리티 (하드코딩 배제)
# ==============================================================================
@st.cache_resource
def get_gspread_client():
    # 1순위: [google_oauth] (scopes 강제 지정 제거로 invalid_scope 방지)
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
            return gspread.authorize(creds), None
        except Exception as e:
            return None, f"Google OAuth 인증 오류: {e}"

    # 2순위: [gcp_service_account]
    if "gcp_service_account" in st.secrets:
        try:
            scopes = [
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive"
            ]
            creds = ServiceAccountCredentials.from_service_account_info(
                st.secrets["gcp_service_account"], scopes=scopes
            )
            return gspread.authorize(creds), None
        except Exception as e:
            return None, f"Service Account 인증 오류: {e}"

    return None, "Streamlit Secrets에 [google_oauth] 또는 [gcp_service_account] 설정이 없습니다."

def open_sheet_safely(key_or_title):
    client, auth_err = get_gspread_client()
    if client is None:
        return None, auth_err

    errors = []
    # 1순위: [sheet_urls] 설정값이 있는 경우 시도 (실패 시 파일명 검색으로 자동 전환)
    if "sheet_urls" in st.secrets:
        for k, v in SHEET_NAMES.items():
            if key_or_title in (k, v) and k in st.secrets["sheet_urls"]:
                url_val = str(st.secrets["sheet_urls"][k]).strip()
                if url_val:
                    try:
                        if url_val.startswith("http"):
                            return client.open_by_url(url_val), None
                        else:
                            return client.open_by_key(url_val), None
                    except Exception as e:
                        errors.append(f"URL/Key 열기 실패({k}): {e}")

    # 2순위: 구글 드라이브 파일명으로 열기
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

def calc_linear_trend_and_forecast(y_values, total_periods=12):
    valid_idx = [i for i, v in enumerate(y_values) if v > 0]
    valid_y = [y_values[i] for i in valid_idx]
    if len(valid_idx) >= 2:
        slope, intercept = np.polyfit(valid_idx, valid_y, 1)
        trend_line = [round(max(slope * i + intercept, 0.0), 2) for i in range(total_periods)]
    elif len(valid_idx) == 1:
        slope = 0.0
        trend_line = [round(valid_y[0], 2)] * total_periods
    else:
        slope = 0.0
        trend_line = [0.0] * total_periods
    return trend_line, round(slope, 4), len(valid_idx)

# ==============================================================================
# 4. 시트별 실시간 좌표 파싱 함수 (1: 원가절감 / 2: 클레임 / 3-A: 상온공정)
# ==============================================================================

# [1] 원가절감 현황 (A~D: 부문, E~H: 식품안전팀, I~L: 품질관리팀 고정 열 파싱)
@st.cache_data(ttl=20)
def load_cost_data():
    sh, err = open_sheet_safely("cost")
    if sh is None:
        return pd.DataFrame(), {"부문": 1.54, "식품안전팀": 1.0, "품질관리팀": 0.54}, err

    try:
        ws = sh.get_worksheet(0)
        rows = get_values_unformatted(ws)
        targets = {"부문": 1.54, "식품안전팀": 1.0, "품질관리팀": 0.54}

        if len(rows) >= 1:
            r0_join = " ".join([str(x) for x in rows[0]])
            nums_uk = re.findall(r"(\d+\.\d+|\d+)\s*억", r0_join)
            if len(nums_uk) >= 3:
                targets = {"부문": float(nums_uk[0]), "식품안전팀": float(nums_uk[1]), "품질관리팀": float(nums_uk[2])}

        parsed = []
        for r in rows[2:]:
            r_pad = list(r) + [""] * max(0, 12 - len(r))
            m_name = str(r_pad[0]).strip()
            if m_name in FISCAL_MONTHS:
                b_act = round(to_float(r_pad[1]), 1)
                b_tar = round(to_float(r_pad[2]), 1)
                fs_act = round(to_float(r_pad[5]), 1)
                fs_tar = round(to_float(r_pad[6]), 1)
                qc_act = round(to_float(r_pad[9]), 1)
                qc_tar = round(to_float(r_pad[10]), 1)

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
        return pd.DataFrame(), {"부문": 1.54, "식품안전팀": 1.0, "품질관리팀": 0.54}, str(e)

# [2] 클레임 건수 (유형별/월별 시트 자동 탐색 + 병합된 연도 열 ffill + 고정 3칸 월별 블록 파싱)
@st.cache_data(ttl=20)
def load_claim_data():
    sh, err = open_sheet_safely("claim")
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
            return pd.DataFrame(), pd.DataFrame(), "클레임 시트에서 유효한 유형별 데이터를 찾지 못했습니다."

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

def build_division_claim_df(df_category, year_str, division_categories):
    if df_category.empty:
        return pd.DataFrame(), pd.DataFrame()
    sub = df_category[(df_category["연도"] == year_str) & (df_category["유형"].isin(division_categories))]
    monthly_rows = []
    for m in FISCAL_MONTHS:
        cnt_sum = int(sub[f"{m}_건수"].sum()) if not sub.empty else 0
        prod_sum = int(sub[f"{m}_생산수량"].sum()) if not sub.empty else 0
        ppm_val = round((cnt_sum / prod_sum) * 1_000_000, 2) if prod_sum > 0 else 0.0
        row_item = {"월": m, "합산_건수": cnt_sum, "합산_생산수량": prod_sum, "부문_통합_PPM": ppm_val}
        for cat in division_categories:
            cat_row = sub[sub["유형"] == cat]
            row_item[f"{cat}_건수"] = int(cat_row[f"{m}_건수"].values[0]) if not cat_row.empty else 0
            row_item[f"{cat}_PPM"] = float(cat_row[f"{m}_PPM"].values[0]) if not cat_row.empty else 0.0
        monthly_rows.append(row_item)
    return pd.DataFrame(monthly_rows), sub

# [3-A] 날짜 탭 탐색 공통 함수 (MM/DD 형태 탭을 날짜순 정렬하여 금일·전일 탭 반환)
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

# ==============================================================================
# [3-B] 상온제품 공정 관리 일보 고정 좌표 파서 (포장호기 ↔ 멸균기 ↔ 하단 제품기준 매칭)
# ==============================================================================
def parse_rt_process_worksheet(ws):
    if ws is None:
        return None
    rows = ws.get_all_values()
    if len(rows) < 5:
        return None

    tab_title = ws.title.strip()
    prod_date_str = tab_title
    for r in rows[:3]:
        for c in r[:18]:
            if "생 산 일" in str(c) or re.search(r"202\d\.\s*\d{1,2}\.\s*\d{1,2}", str(c)):
                prod_date_str = str(c).replace("생 산 일 :", "").strip()
                break

    # 구역 행 인덱스 탐색
    r_pack_hdr = 2
    r_ccp3b_hdr = 15
    r_ster_hdr = 20
    for idx, r in enumerate(rows[:35]):
        b_txt = str(r[1]).replace(" ", "").strip() if len(r) > 1 else ""
        row_join = " ".join([str(x).strip() for x in r[:10] if str(x).strip()])
        if b_txt == "포장호기" and idx < 8:
            r_pack_hdr = idx
        elif "포장기공정관리" in row_join.replace(" ", ""):
            r_ccp3b_hdr = idx
        elif b_txt == "멸균기" and idx > r_ccp3b_hdr:
            r_ster_hdr = idx
            break

    # 시트 하단 제품별 기준표 스캔 (제품명 기준 온도/압력/시간/유량/냉각온도 참조 사전을 생성)
    product_std_map = {}
    for r in rows[r_ster_hdr + 12:]:
        r_clean = [str(x).strip() for x in r[:18] if str(x).strip() not in ["", "-"]]
        if len(r_clean) >= 3:
            first_txt = r_clean[0]
            if not re.match(r"^\d+호기$", first_txt) and first_txt not in ["특이사항", "멸균기", "포장호기", "구 분", "구분"]:
                if any(re.search(r"\d{2,3}", x) for x in r_clean[1:]):
                    product_std_map[first_txt] = " / ".join(r_clean[1:7])

    # 1) 상단 포장호기(A~F호기) 고정 열 파싱: B(1)=호기, C~F(2..5)=제품1, G(6)=소비기한1, H~I(7..8)=확인시간1, J~M(9..12)=제품2, N~O(13..14)=소비기한2, P~Q(15..16)=확인시간2
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
                status_str = "🟢 확인완료" if has_time else ("🟡 확인시간 대기" if p_name else "-")
                if p_name and p_name not in ho_products[current_ho]:
                    ho_products[current_ho].append(p_name)
                ho_rows_raw[current_ho].append({
                    "포장호기": current_ho,
                    "생산 제품명": p_name if p_name else "(제품명 미선택)",
                    "소비기한": exp_v if exp_v else "-",
                    "확인시간": t_str if t_str else "미기입",
                    "상태": status_str
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
                "상태": "⚪ 비가동"
            })

    # 2) 중단 포장기 공정관리 [CCP-3B] 파싱
    ccp3b_records = []
    hdr_3b = [str(x).strip() for x in rows[r_ccp3b_hdr]]
    ho_cols_3b = {cell: idx for idx, cell in enumerate(hdr_3b) if re.match(r"^[A-F]호기$", cell)}
    last_item_3b = ""
    for r in rows[r_ccp3b_hdr + 1 : r_ster_hdr]:
        r_pad = list(r) + [""] * max(0, 18 - len(r))
        item_nm = str(r_pad[1]).strip()
        if item_nm:
            last_item_3b = item_nm
        std_nm = " ".join([str(x).strip() for x in r_pad[2:6] if str(x).strip()])
        equip_nm = " ".join([str(x).strip() for x in r_pad[6:8] if str(x).strip() and "호기" not in str(x)])
        if not last_item_3b and not std_nm:
            continue
        rec_3b = {"항목": last_item_3b, "관리기준": std_nm, "적용설비": equip_nm}
        for ho_lbl in ["A호기", "B호기", "C호기", "D호기", "E호기", "F호기"]:
            c_i = ho_cols_3b.get(ho_lbl, -1)
            rec_3b[ho_lbl] = str(r_pad[c_i]).strip() if (0 <= c_i < len(r_pad) and str(r_pad[c_i]).strip()) else "-"
        ccp3b_records.append(rec_3b)

    # 3) 하단 멸균기 [CCP-1B / CCP-2P] 고정 열 파싱 (B:멸균기, C:포장호기, D:용량, E~F:시간, G:멸균온도, H~I:균질압, J:멸균시간, K~L:유량, M:냉각온도, N~O:여과망, P~Q:서명)
    ster_blocks = []
    cur_block = None
    for r in rows[r_ster_hdr + 1:]:
        r_pad = list(r) + [""] * max(0, 18 - len(r))
        b_cell = str(r_pad[1]).strip()

        if re.match(r"^\d+호기$", b_cell):
            if cur_block:
                ster_blocks.append(cur_block)
            cur_block = {"ster_ho": b_cell, "rows": [r_pad], "remark": ""}
        elif b_cell == "특이사항" and cur_block is not None:
            rem_txt = " ".join([str(x).strip() for x in r_pad[2:17] if str(x).strip() not in ["", "-"]])
            cur_block["remark"] = rem_txt
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
    ho_ster_summary = {}
    for blk in ster_blocks:
        s_ho = blk["ster_ho"]
        b_rows = blk["rows"]
        pack_ho = next((str(br[2]).strip() for br in b_rows if str(br[2]).strip() not in ["", "-"]), "-")
        vol_str = next((str(br[3]).strip() for br in b_rows if str(br[3]).strip() not in ["", "-"]), "-")
        flt_str = next((str(br[13]).strip() or str(br[14]).strip() for br in b_rows if (str(br[13]).strip() or str(br[14]).strip()) not in ["", "-"]), "-")

        matched_prods = ho_products.get(pack_ho, [])
        matched_prod_str = ", ".join(matched_prods) if matched_prods else "-"

        matched_std = "-"
        for mp in matched_prods:
            for std_k, std_v in product_std_map.items():
                if std_k in mp or mp in std_k:
                    matched_std = std_v
                    break

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
                ster_records.append({
                    "멸균기": s_ho,
                    "포장호기": pack_ho,
                    "매칭 제품명": matched_prod_str,
                    "용량": vol_str,
                    "모니터링시간": mon_time or "-",
                    "멸균온도(℃)": temp_v or "-",
                    "균질압(bar)": press_v or "-",
                    "멸균시간(초)": hold_v or "-",
                    "유량(L/hr)": flow_v or "-",
                    "냉각온도(℃)": cool_v or "-",
                    "여과망[CCP-2P]": flt_str,
                    "서명": sign_v or "-",
                    "제품별 기준": matched_std,
                    "특이사항": blk["remark"] or "없음"
                })
                if pack_ho != "-":
                    ho_ster_summary[pack_ho] = f"{s_ho} ({temp_v}℃ / {hold_v}초 / 여과망:{flt_str})"

        if not has_record and pack_ho != "-":
            ster_records.append({
                "멸균기": s_ho, "포장호기": pack_ho, "매칭 제품명": matched_prod_str, "용량": vol_str,
                "모니터링시간": "기록대기", "멸균온도(℃)": "-", "균질압(bar)": "-", "멸균시간(초)": "-",
                "유량(L/hr)": "-", "냉각온도(℃)": "-", "여과망[CCP-2P]": flt_str, "서명": "-",
                "제품별 기준": matched_std, "특이사항": blk["remark"] or "없음"
            })

    # 전일 간소화 표시용 호기+제품명+멸균기 통합 요약 테이블 생성
    compact_rows = []
    for lr in lines_records:
        if lr["생산 제품명"] == "(비가동)":
            continue
        p_ho = lr["포장호기"]
        compact_rows.append({
            "포장호기": p_ho,
            "생산 제품명": lr["생산 제품명"],
            "소비기한": lr["소비기한"],
            "확인시간": lr["확인시간"],
            "멸균기·CCP 요약": ho_ster_summary.get(p_ho, "-"),
            "특이사항": next((sr["특이사항"] for sr in ster_records if sr["포장호기"] == p_ho and sr["특이사항"] != "없음"), "이상없음")
        })

    # 4) 우측 AB열(27): 날짜, AC열~(28:): 전달(특이)사항 파싱
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
        "df_lines": pd.DataFrame(lines_records),
        "df_compact": pd.DataFrame(compact_rows),
        "df_ccp3b": pd.DataFrame(ccp3b_records),
        "df_ster": pd.DataFrame(ster_records),
        "df_issues": pd.DataFrame(list(reversed(issues)))
    }

# ==============================================================================
# [3-C] 유제품(우유/발효유) 포장 공정관리 일보 & 두유 배양검사(2D 전 호기 블록) 파서
# ==============================================================================
def parse_dairy_pack_worksheet(ws, line_label):
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
                    elif any(k in row_lbl for k in ["소비기한", "Tank", "11.", "12.", "01.", "02.", "03.", "04.", "05.", "06.", "07.", "08.", "09.", "10."]) or re.match(r"^\d{2}\.\d{2}[A-Z]?$", row_lbl):
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

def calc_run_duration(start_str, end_str):
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

def parse_soy_incubation_worksheet(ws):
    """시트 내 '배양검사' 시작 앵커를 2차원으로 모두 찾아 A·B·D·E·F호기 등 전 호기 블록을 실시간 추출"""
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
        c_end = min(same_row_next_c) if same_row_next_c else c0 + 15

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
                right_vals = [str(x).strip() for x in sr[sc_i + 1:] if str(x).strip() != ""]

                if key == "배양검사" and not inc_days and right_vals:
                    inc_days = right_vals[0]
                elif key == "배양온도" and not inc_temp and right_vals:
                    inc_temp = right_vals[0]
                elif ("용량/포장기" in key or key == "포장기") and not machine_ho:
                    for rv in right_vals[:3]:
                        if "호기" in rv and not machine_ho:
                            machine_ho = rv
                        elif re.search(r"\d{2,3}", rv) and not vol_ml:
                            vol_ml = rv
                elif key == "작성자" and not writer_nm and right_vals:
                    writer_nm = right_vals[0]
                elif key == "검사자" and not inspector_nm and right_vals:
                    inspector_nm = right_vals[0]
                elif key == "품목":
                    for rv in right_vals:
                        if rv not in ["생산일", "소비기한", "검사일"] and rv not in item_names:
                            item_names.append(rv)
                    if sr_i + 1 < len(sub_rows):
                        next_sr = sub_rows[sr_i + 1]
                        next_first = re.sub(r"\s+", "", str(next_sr[0])) if next_sr else ""
                        if next_first not in ["생산일", "소비기한", "검사일", "생산시작"]:
                            for rv in [str(x).strip() for x in next_sr if str(x).strip()]:
                                if rv not in item_names and not re.search(r"^202\d", rv):
                                    item_names.append(rv)
                elif key == "생산일" and not prod_dt and right_vals:
                    prod_dt = right_vals[0]
                elif key == "소비기한":
                    for rv in right_vals:
                        if rv not in ["검사일", "생산시작"] and rv not in exp_dates:
                            exp_dates.append(rv)
                elif key == "검사일" and not insp_dt and right_vals:
                    insp_dt = right_vals[0]
                elif key == "생산시작" and not t_start and right_vals:
                    t_start = right_vals[0]
                elif key == "생산종료" and not t_end and right_vals:
                    t_end = right_vals[0]
                elif key == "총검사수량" and not total_smp and right_vals:
                    total_smp = right_vals[0]
                elif key == "오염수량":
                    look_cells = right_vals[:]
                    if sr_i + 1 < len(sub_rows):
                        look_cells.extend([str(x).strip() for x in sub_rows[sr_i + 1] if str(x).strip()])
                    for lv in look_cells:
                        if ("개" in lv or lv.isdigit()) and not contam_cnt:
                            contam_cnt = lv
                        elif lv in ["적합", "부적합"] and not judge_res:
                            judge_res = lv
                elif key == "특이사항" and right_vals:
                    remark_txt = " ".join(right_vals)

            # 시간대별 샘플링 행(08: ~ 07:) 추출
            first_t = str(sr[0]).strip() if sr else ""
            if re.match(r"^\d{2}\s*:$", first_t):
                smp_v = " ".join([str(x).strip() for x in sr[1:6] if str(x).strip()])
                strp_v = " ".join([str(x).strip() for x in sr[6:9] if str(x).strip()])
                pap_v = " ".join([str(x).strip() for x in sr[9:12] if str(x).strip()])
                if smp_v or strp_v or pap_v:
                    hourly_all.append({
                        "포장기": machine_ho or f"블록{idx+1}",
                        "시간대": first_t,
                        "샘플체크": smp_v or "-",
                        "Strip": strp_v or "-",
                        "Paper": pap_v or "-"
                    })

        duration_str = calc_run_duration(t_start, t_end)
        blocks_parsed.append({
            "시트탭": ws.title.strip(),
            "포장기": machine_ho or f"블록{idx+1}",
            "배양구분": f"{inc_days} ({inc_temp})".strip(" ()"),
            "용량(mL)": vol_ml or "-",
            "품목명": " / ".join(item_names) if item_names else "-",
            "생산일": prod_dt or "-",
            "소비기한": " / ".join(exp_dates[:4]) if exp_dates else "-",
            "검사일(개봉일)": insp_dt or "-",
            "생산 시작~종료": f"{t_start} ~ {t_end}" if (t_start or t_end) else "-",
            "실가동시간": duration_str,
            "총 검사수량": total_smp or "0",
            "오염수량": contam_cnt or "0 개",
            "판정": judge_res or "-",
            "작성/검사자": f"{writer_nm} / {inspector_nm}".strip(" /"),
            "특이사항": remark_txt or "없음"
        })

    return pd.DataFrame(blocks_parsed), pd.DataFrame(hourly_all)

@st.cache_data(ttl=20)
def load_process_all_data():
    errors = []
    # 1) 상온제품 공정 관리 일보
    sh_rt, err_rt = open_sheet_safely("process_rt")
    if err_rt:
        errors.append(f"[상온공정일보] {err_rt}")
    ws_rt_today, ws_rt_yest, rt_date_ws_list = get_sorted_date_worksheets(sh_rt)
    rt_today_data = parse_rt_process_worksheet(ws_rt_today)
    rt_yest_data = parse_rt_process_worksheet(ws_rt_yest)

    # 2) 유제품 포장 공정관리 일보 ('우유' 탭 / '발효유' 탭)
    sh_milk, err_milk = open_sheet_safely("process_milk")
    if err_milk:
        errors.append(f"[유제품포장일보] {err_milk}")
    df_milk_pack, df_ferm_pack = pd.DataFrame(), pd.DataFrame()
    milk_date_str, ferm_date_str = "-", "-"
    if sh_milk is not None:
        ws_m, ws_f = None, None
        for w in sh_milk.worksheets():
            wt = w.title.strip()
            if "우유" in wt and "발효유" not in wt and ws_m is None:
                ws_m = w
            elif "발효유" in wt and ws_f is None:
                ws_f = w
        df_milk_pack, milk_date_str = parse_dairy_pack_worksheet(ws_m, "우유")
        df_ferm_pack, ferm_date_str = parse_dairy_pack_worksheet(ws_f, "발효유")

    # 3) 두유 배양검사 일보 (전날 작성 탭 = 어제 날짜 탭 우선 선택, 전체 날짜 탭 맵 지원)
    sh_soy, err_soy = open_sheet_safely("process_soy")
    if err_soy:
        errors.append(f"[두유배양일보] {err_soy}")
    ws_soy_t, ws_soy_y, soy_date_ws_list = get_sorted_date_worksheets(sh_soy)
    today_str_dot = datetime.now().strftime("%Y. %m. %d")

    # 전날 작성 규칙 반영: 어제 탭(예: 11/12)을 기본으로 하되, 최근 3개 탭 중 검사일이 오늘인 탭이 있으면 최우선 매칭
    default_soy_ws = ws_soy_y if ws_soy_y is not None else ws_soy_t
    soy_tabs_parsed = {}
    for w in soy_date_ws_list[:5]:
        df_b, df_h = parse_soy_incubation_worksheet(w)
        soy_tabs_parsed[w.title.strip()] = (df_b, df_h)
        if not df_b.empty and df_b["검사일(개봉일)"].astype(str).str.contains(today_str_dot[-5:].replace(" ", ""), na=False).any():
            default_soy_ws = w

    default_soy_title = default_soy_ws.title.strip() if default_soy_ws is not None else "-"
    if default_soy_title not in soy_tabs_parsed and default_soy_ws is not None:
        soy_tabs_parsed[default_soy_title] = parse_soy_incubation_worksheet(default_soy_ws)

    df_soy_blocks, df_soy_hourly = soy_tabs_parsed.get(default_soy_title, (pd.DataFrame(), pd.DataFrame()))

    return {
        "rt_today": rt_today_data,
        "rt_yest": rt_yest_data,
        "milk_date": milk_date_str,
        "ferm_date": ferm_date_str,
        "df_milk_pack": df_milk_pack,
        "df_ferm_pack": df_ferm_pack,
        "soy_default_tab": default_soy_title,
        "soy_tabs_map": soy_tabs_parsed,
        "df_soy_blocks": df_soy_blocks,
        "df_soy_hourly": df_soy_hourly,
        "errors": errors
    }

# ==============================================================================
# [4] 협력업체 심사 결과 DB (시트2 마스터 + 시트1 항목별 최신 관리자최종점수 실시간 합산)
# ==============================================================================
@st.cache_data(ttl=20)
def load_supplier_matched_data():
    sh, err = open_sheet_safely("supplier")
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

        # 시트1에서 업체별·심사항목별 최신 제출건만 남긴 후 관리자최종점수 합산 및 미비항목 추출
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

        # 시트2 마스터 결합 (시트2에 별도 점수 열이 있으면 우선 활용, 없으면 시트1 실시간 합산치 적용)
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
        master_records = []
        under_comp_rows = []
        under_detail_rows = []

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

# ==============================================================================
# [6] 표시사항 현황 & [7] 원자재 표시사항 DB 실시간 파서 (추정 배제, 팩트 날짜 파싱)
# ==============================================================================
def parse_factual_date(row_dict):
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

def classify_label_status(status_str):
    s = str(status_str).strip()
    if s == "식품안전팀 검토중":
        return "식품안전팀 검토중"
    elif s in ["개시/준비", "보류", "검토/개시", ""]:
        return "제외(개시/준비·보류)"
    return "검토완료(확인필)"

@st.cache_data(ttl=20)
def load_label_status_data():
    sh, err = open_sheet_safely("label_status")
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

@st.cache_data(ttl=20)
def load_raw_material_label_db():
    sh, err = open_sheet_safely("raw_label_db")
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
# 5. 미니 차트 & AX 브리핑 유틸리티
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

@st.cache_data(ttl=120)
def generate_ax_executive_briefing(summary_context_str):
    api_key = st.secrets.get("GEMINI_API_KEY", "")
    if GENAI_AVAILABLE and api_key and not api_key.startswith("여기에"):
        try:
            client = genai.Client(api_key=api_key)
            prompt = (
                "당신은 연세유업 아산공장 품질안전부문의 데이터 브리핑 AI입니다. "
                "추정이나 판단 없이 아래 실시간 시트 집계 수치만 인용하여 2문장 이내로 요약하세요.\n\n"
                f"{summary_context_str}"
            )
            res = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
            if res and res.text:
                return res.text.strip()
        except Exception:
            pass
    return summary_context_str

# ==============================================================================
# 6. 전체 시트 실시간 로드 및 지표 산출
# ==============================================================================
df_cost, cost_targets, err_cost = load_cost_data()
df_claim_trend, df_claim_cat, err_claim = load_claim_data()
proc_data = load_process_all_data()
df_sup_master, df_sup_grade, df_sup_under_c, df_sup_under_d, err_sup = load_supplier_matched_data()
df_label_status, err_label = load_label_status_data()
df_raw_sub, raw_master_cnt, err_raw = load_raw_material_label_db()

all_load_errors = [
    f"[{nm}] {er}" for nm, er in [
        ("원가절감", err_cost), ("클레임", err_claim), ("협력업체", err_sup),
        ("표시사항 현황", err_label), ("원자재 DB", err_raw)
    ] if er
] + proc_data["errors"]

# (1) 원가절감 지표
cost_target_uk = cost_targets["부문"]
cost_actual_man = round(df_cost["부문_실적(만원)"].sum(), 1) if not df_cost.empty else 0.0
cost_actual_uk = round(cost_actual_man / 10000, 2)
cost_rate = round((cost_actual_uk / cost_target_uk) * 100, 1) if cost_target_uk > 0 else 0.0
cost_trend_vals, cost_slope, cost_m_cnt = calc_linear_trend_and_forecast(
    df_cost["부문_실적(만원)"].tolist() if not df_cost.empty else []
)
cost_proj_man = round(cost_actual_man + sum(cost_trend_vals[cost_m_cnt:]), 1) if cost_m_cnt < 12 else cost_actual_man
cost_proj_uk = round(cost_proj_man / 10000, 2)
sig_cost = "green" if (cost_actual_uk >= cost_target_uk or cost_proj_uk >= cost_target_uk) else ("red" if not df_cost.empty else "gray")

# (2) 클레임 지표
claim_target_ppm = 1.12
row_26_sum = df_claim_cat[(df_claim_cat["연도"] == "2026년") & (df_claim_cat["유형"] == "합계")] if not df_claim_cat.empty else pd.DataFrame()
claim_actual_ppm = float(row_26_sum["합계_PPM"].values[0]) if not row_26_sum.empty else 0.0
claim_total_cnt = int(row_26_sum["합계_건수"].values[0]) if not row_26_sum.empty else 0
claim_trend_vals, claim_slope, _ = calc_linear_trend_and_forecast(
    df_claim_trend["2026년_PPM"].tolist() if not df_claim_trend.empty else []
)
if row_26_sum.empty:
    sig_claim = "gray"
elif claim_actual_ppm > claim_target_ppm:
    sig_claim = "red"
elif claim_slope > 0.03:
    sig_claim = "yellow"
else:
    sig_claim = "green"

# (3) 공정 현황 지표
rt_t = proc_data["rt_today"]
rt_y = proc_data["rt_yest"]
rt_t_tab = rt_t["tab_title"] if rt_t else "-"
rt_y_tab = rt_y["tab_title"] if rt_y else "-"
df_rt_t_lines = rt_t["df_lines"] if rt_t else pd.DataFrame()
active_rt_cnt = len(df_rt_t_lines[df_rt_t_lines["생산 제품명"] != "(비가동)"]) if not df_rt_t_lines.empty else 0
wait_rt_cnt = len(df_rt_t_lines[df_rt_t_lines["상태"].str.contains("대기", na=False)]) if not df_rt_t_lines.empty else 0
active_milk_cnt = len(proc_data["df_milk_pack"][proc_data["df_milk_pack"]["가동여부"].str.contains("금일생산", na=False)]) if not proc_data["df_milk_pack"].empty else 0
active_ferm_cnt = len(proc_data["df_ferm_pack"][proc_data["df_ferm_pack"]["가동여부"].str.contains("금일생산", na=False)]) if not proc_data["df_ferm_pack"].empty else 0
soy_blocks_cnt = len(proc_data["df_soy_blocks"])
sig_process = "yellow" if wait_rt_cnt > 0 else ("green" if rt_t is not None else "gray")

# (4) 협력업체 지표
target_exec = 88.3
total_sup_cnt = len(df_sup_master)
unsub_sup_cnt = int((df_sup_master["점수"] == "미제출").sum()) if not df_sup_master.empty else 0
sub_sup_cnt = total_sup_cnt - unsub_sup_cnt
sup_exec_rate = round((sub_sup_cnt / total_sup_cnt) * 100, 1) if total_sup_cnt > 0 else 0.0
ok_sup_cnt = int((df_sup_master["결과"] == "승인").sum()) if not df_sup_master.empty else 0
guide_sup_cnt = int((df_sup_master["결과"] == "지도").sum()) if not df_sup_master.empty else 0
out_sup_cnt = int((df_sup_master["결과"] == "등급 외").sum()) if not df_sup_master.empty else 0
sig_supplier = "green" if sup_exec_rate >= target_exec else ("red" if total_sup_cnt > 0 else "gray")

# (6) 표시사항 진행 현황 지표
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

# (7) 원자재 표시사항 DB 지표
sub_raw_cnt = len(df_raw_sub)
verified_raw_cnt = len(df_raw_sub[df_raw_sub["검증상태"].astype(str).str.contains("완료|적합", na=False)]) if ("검증상태" in df_raw_sub.columns and not df_raw_sub.empty) else 0
allergy_raw_cnt = len(df_raw_sub[df_raw_sub["신규알레르기"].astype(str).str.strip() != ""]) if ("신규알레르기" in df_raw_sub.columns and not df_raw_sub.empty) else 0
sig_raw = "yellow" if allergy_raw_cnt > 0 else ("green" if not df_raw_sub.empty or raw_master_cnt > 0 else "gray")

# ==============================================================================
# [화면 1] 메인 Summary 대시보드
# ==============================================================================
if st.session_state.current_view == "main":
    top_c1, top_c2 = st.columns([8.5, 1.5])
    with top_c1:
        st.markdown("""
            <div class="main-title">
                <span>2026 업적 KPI 현황판_품질안전부문</span>
                <span style="font-size: 20px;">Summary</span>
            </div>
        """, unsafe_allow_html=True)
    with top_c2:
        if st.button("🔄 시트 실시간 동기화"):
            st.cache_data.clear()
            st.rerun()

    st.markdown(f"<div class='sub-date'>(기준 : {datetime.now().strftime('%Y. %m. %d')} | 구글 시트 실시간 직접 연동)</div>", unsafe_allow_html=True)

    if all_load_errors:
        with st.expander(f"⚠️ 시트 연동 점검 필요 항목 ({len(all_load_errors)}건)", expanded=True):
            for err_line in all_load_errors:
                st.write(f"- {err_line}")

    brief_ctx = (
        f"[원가절감] 누적 {cost_actual_uk}억({cost_rate}%), 연말 추세 예측 {cost_proj_uk}억 | "
        f"[클레임] 2026년 누적 {claim_actual_ppm}ppm({claim_total_cnt}건) | "
        f"[공정] 상온({rt_t_tab}) {active_rt_cnt}건 가동, 유제품 {active_milk_cnt + active_ferm_cnt}품목 가동, 배양개봉({proc_data['soy_default_tab']}) {soy_blocks_cnt}개 호기 점검 | "
        f"[협력업체] {total_sup_cnt}개사 중 {sub_sup_cnt}개사 제출({sup_exec_rate}%) | "
        f"[표시사항] 완료 {completed_cnt}건, 현재 검토중 {reviewing_cnt}건"
    )
    st.markdown(f"<div class='ax-banner'><b>🤖 실시간 시트 데이터 종합 요약</b><br>{generate_ax_executive_briefing(brief_ctx)}</div>", unsafe_allow_html=True)

    col1, col2, col3, col4 = st.columns(4)

    # 1. 원가 절감
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
        if st.button("🔍 1. 원가 절감 상세", key="btn_cost"):
            set_view("cost")
            st.rerun()

    # 2. 클레임 발생률
    with col2:
        st.markdown(f"""
        <div class="kpi-card">
            <div class="kpi-header">2. 클레임 발생률</div>
            <div class="kpi-body">
                {get_signal_dot_html(sig_claim)}
                <div><span class="kpi-bullet">●</span><b>목표 : {claim_target_ppm} ppm이하</b></div>
                <div><span class="kpi-bullet">●</span><b>실적 : {claim_actual_ppm} ppm ({claim_total_cnt:,}건)</b></div>
                <div class="ai-line">📈 월 추세 기울기 : {claim_slope:+.2f} ppm</div>
            </div>
            <div class="unit-label">(단위 : ppm)</div>
        </div>
        """, unsafe_allow_html=True)
        st.plotly_chart(draw_mini_bar(claim_target_ppm, claim_actual_ppm), use_container_width=True, config={"displayModeBar": False})
        if st.button("🔍 2. 클레임 상세 (부문별/25·26년)", key="btn_claim"):
            set_view("claim")
            st.rerun()

    # 3. 공정 현황 및 특이사항
    with col3:
        st.markdown(f"""
        <div class="kpi-card">
            <div class="kpi-header">3. 공정 현황 및 특이사항</div>
            <div class="kpi-body">
                {get_signal_dot_html(sig_process)}
                <div><span class="kpi-bullet">●</span><b>상온({rt_t_tab}) : {active_rt_cnt}건 / 전일({rt_y_tab}) 완료</b></div>
                <div><span class="kpi-bullet">●</span><b>우유·발효유 : 금일 {active_milk_cnt + active_ferm_cnt}품목 생산</b></div>
                <div class="ai-line">🧪 배양({proc_data['soy_default_tab']}) : {soy_blocks_cnt}개 호기 판독</div>
            </div>
            <div class="unit-label">(단위 : 건/품목)</div>
        </div>
        """, unsafe_allow_html=True)
        st.plotly_chart(draw_mini_bar(active_rt_cnt + active_milk_cnt, max(active_rt_cnt - wait_rt_cnt, 0) + active_milk_cnt, bar_labels=("금일가동", "확인완료")), use_container_width=True, config={"displayModeBar": False})
        if st.button("🔍 3. 금일·전일 공정 및 배양 상세", key="btn_process"):
            set_view("process")
            st.rerun()

    # 4. 협력업체 관리
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
        if st.button("🔍 4. 협력업체 서류심사 상세", key="btn_supplier"):
            set_view("supplier")
            st.rerun()

    col5, col6, col7 = st.columns([1, 1.5, 1.5])

    # 5. 심사점수 (요청에 따라 연동 시트 없음 -> 빈칸 처리)
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
        if st.button("🔍 5. 심사점수 상세", key="btn_audit"):
            set_view("audit")
            st.rerun()

    # 6. 표시사항 진행 현황
    with col6:
        rep_html = "".join([f"<div>• {t[:42]}{'...' if len(t)>42 else ''}</div>" for t in rep_titles]) if rep_titles else "<div>• 현재 검토중 품목 없음</div>"
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
        if st.button("🔍 6. 표시사항 진행 상세 (연도·월별 완료 & 등록팀별)", key="btn_label_status"):
            set_view("label_status")
            st.rerun()

    # 7. 표시사항 특이사항 (원자재 표시사항 DB 단독)
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
        if st.button("🔍 7. 원자재 표시사항 DB 상세", key="btn_label_issue"):
            set_view("label_issue")
            st.rerun()

# ==============================================================================
# [화면 2] 세부 페이지 (Drill-Down Views)
# ==============================================================================
else:
    if st.button("⬅️ 전체 Summary 현황판으로 돌아가기"):
        set_view("main")
        st.rerun()

    view = st.session_state.current_view

    # [세부 1] 원가 절감
    if view == "cost":
        st.markdown("<div class='main-title'>1. 원가 절감 - 월별/팀별 실시간 집계</div>", unsafe_allow_html=True)
        if df_cost.empty:
            st.error(f"원가절감 시트를 불러오지 못했습니다: {err_cost}")
        else:
            m1, m2, m3, m4 = st.columns(4)
            fs_sum = round(df_cost["식품안전팀_실적(만원)"].sum(), 1)
            qc_sum = round(df_cost["품질관리팀_실적(만원)"].sum(), 1)
            m1.metric(f"품질안전부문 (목표 {cost_targets['부문']}억)", f"{cost_actual_man:,.1f} 만원 ({cost_actual_uk}억)", f"{cost_rate}%")
            m2.metric(f"식품안전팀 (목표 {cost_targets['식품안전팀']}억)", f"{fs_sum:,.1f} 만원", f"{round(fs_sum/(cost_targets['식품안전팀']*10000)*100, 1)}%")
            m3.metric(f"품질관리팀 (목표 {cost_targets['품질관리팀']}억)", f"{qc_sum:,.1f} 만원", f"{round(qc_sum/(cost_targets['품질관리팀']*10000)*100, 1)}%")
            m4.metric("연말 마감 추세 예측", f"{cost_proj_man:,.1f} 만원 ({cost_proj_uk}억)", f"기울기 {cost_slope:+.1f}만/월")

            fig_cost = go.Figure()
            fig_cost.add_trace(go.Bar(x=df_cost["월"], y=df_cost["식품안전팀_실적(만원)"], name="식품안전팀 실적", marker_color="#2E75B6", text=df_cost["식품안전팀_실적(만원)"], textposition="auto"))
            fig_cost.add_trace(go.Bar(x=df_cost["월"], y=df_cost["품질관리팀_실적(만원)"], name="품질관리팀 실적", marker_color="#ED7D31", text=df_cost["품질관리팀_실적(만원)"], textposition="auto"))
            fig_cost.add_trace(go.Scatter(x=df_cost["월"], y=df_cost["부문_기준(만원)"], name="부문 월 기준", mode="lines", line=dict(color="#C00000", width=2.5, dash="dash")))
            fig_cost.add_trace(go.Scatter(x=df_cost["월"], y=cost_trend_vals, name="선형 추세선", mode="lines+markers", line=dict(color="#7030A0", width=3, dash="dot")))
            fig_cost.update_layout(barmode="stack", height=420, title="📊 월별 원가절감 실적 및 추세선 (단위: 만원)")
            st.plotly_chart(fig_cost, use_container_width=True)
            st.dataframe(df_cost, use_container_width=True, hide_index=True)

    # [세부 2] 클레임 발생률
    elif view == "claim":
        st.markdown("<div class='main-title'>2. 클레임 발생률 - 부문별 월단위 분석 및 연도별 집계</div>", unsafe_allow_html=True)
        if df_claim_cat.empty:
            st.error(f"클레임 시트를 불러오지 못했습니다: {err_claim}")
        else:
            avail_claim_years = sorted(df_claim_cat["연도"].unique().tolist(), reverse=True)
            tab_c1, tab_c2, tab_c3 = st.tabs([
                "🏭 부문별 월단위 분석 (유제품생산부문 vs 상온제품부문)",
                "📈 전사 월별 PPM 추이 (2025 vs 2026)",
                "🥛 전체 제품 유형별 상세 집계표"
            ])

            with tab_c1:
                cc1, cc2 = st.columns([1.2, 2.2])
                with cc1:
                    div_year = st.radio("조회 연도", avail_claim_years, horizontal=True, key="div_yr")
                with cc2:
                    div_sel = st.radio(
                        "부문 선택",
                        ["🥛 유제품생산부문 (냉장우유 카톤·병 / 발효유·음료 카톤·병)", "🧃 상온제품부문 (상온 멸균팩 / 상온 프리즈마)", "⚖️ 양 부문 비교"],
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
                    d_tr, d_slp, _ = calc_linear_trend_and_forecast(t_df_m["부문_통합_PPM"].tolist())

                    k1, k2, k3, k4 = st.columns(4)
                    k1.metric("부문 누적 건수", f"{tot_c:,} 건")
                    k2.metric("부문 누적 생산량", f"{tot_p:,} 개")
                    k3.metric("부문 통합 PPM", f"{tot_ppm} ppm")
                    k4.metric("월 PPM 추세 기울기", f"{d_slp:+.2f} ppm/월")

                    fig_div = make_subplots(specs=[[{"secondary_y": True}]])
                    colors = ["#2E75B6", "#5B9BD5", "#ED7D31", "#F4B183"]
                    for i, cat in enumerate(t_cats):
                        fig_div.add_trace(go.Bar(x=t_df_m["월"], y=t_df_m[f"{cat}_건수"], name=f"{cat} 건수", marker_color=colors[i % 4], text=t_df_m[f"{cat}_건수"], textposition="inside"), secondary_y=False)
                    fig_div.add_trace(go.Scatter(x=t_df_m["월"], y=t_df_m["부문_통합_PPM"], name="부문 통합 PPM", mode="lines+markers+text", text=t_df_m["부문_통합_PPM"], textposition="top center", line=dict(color="#C00000", width=3)), secondary_y=True)
                    fig_div.add_trace(go.Scatter(x=t_df_m["월"], y=d_tr, name="PPM 추세선", mode="lines", line=dict(color="#7030A0", width=2.5, dash="dot")), secondary_y=True)
                    fig_div.update_layout(barmode="stack", height=420, title=f"📊 {d_lbl} 월단위 클레임 건수 및 통합 PPM")
                    fig_div.update_yaxes(title_text="클레임 건수(건)", secondary_y=False)
                    fig_div.update_yaxes(title_text="PPM", secondary_y=True)
                    st.plotly_chart(fig_div, use_container_width=True)

                    st.dataframe(t_df_m, use_container_width=True, hide_index=True)
                    st.dataframe(t_df_raw, use_container_width=True, hide_index=True)
                else:
                    fig_cmp = make_subplots(specs=[[{"secondary_y": True}]])
                    fig_cmp.add_trace(go.Bar(x=df_dairy_m["월"], y=df_dairy_m["합산_건수"], name="유제품생산 건수", marker_color="#2E75B6"), secondary_y=False)
                    fig_cmp.add_trace(go.Bar(x=df_rt_m["월"], y=df_rt_m["합산_건수"], name="상온제품 건수", marker_color="#ED7D31"), secondary_y=False)
                    fig_cmp.add_trace(go.Scatter(x=df_dairy_m["월"], y=df_dairy_m["부문_통합_PPM"], name="유제품생산 PPM", mode="lines+markers", line=dict(color="#002060", width=3)), secondary_y=True)
                    fig_cmp.add_trace(go.Scatter(x=df_rt_m["월"], y=df_rt_m["부문_통합_PPM"], name="상온제품 PPM", mode="lines+markers", line=dict(color="#C00000", width=3)), secondary_y=True)
                    fig_cmp.update_layout(barmode="group", height=420, title=f"📊 {d_lbl}")
                    st.plotly_chart(fig_cmp, use_container_width=True)

            with tab_c2:
                fig_cl = go.Figure()
                fig_cl.add_trace(go.Bar(x=df_claim_trend["월"], y=df_claim_trend["2025년_PPM"], name="2025년 PPM", marker_color="#A6A6A6", text=df_claim_trend["2025년_PPM"], textposition="outside"))
                fig_cl.add_trace(go.Bar(x=df_claim_trend["월"], y=df_claim_trend["2026년_PPM"], name="2026년 PPM", marker_color="#ED7D31", text=df_claim_trend["2026년_PPM"], textposition="outside"))
                fig_cl.add_trace(go.Scatter(x=df_claim_trend["월"], y=df_claim_trend["목표_PPM"], name="목표 (1.12 ppm)", mode="lines", line=dict(color="#C00000", width=2.5, dash="dash")))
                fig_cl.update_layout(barmode="group", height=420, title="📊 2025년 vs 2026년 월별 클레임 PPM")
                st.plotly_chart(fig_cl, use_container_width=True)
                st.dataframe(df_claim_trend, use_container_width=True, hide_index=True)

            with tab_c3:
                yr_opt = st.radio("연도 필터", avail_claim_years + ["전체"], horizontal=True, key="all_cat_yr")
                df_cv = df_claim_cat if yr_opt == "전체" else df_claim_cat[df_claim_cat["연도"] == yr_opt]
                st.dataframe(df_cv, use_container_width=True, hide_index=True)

    # [세부 3] 공정 현황 및 특이사항 (1: 상온공정 ➔ 2: 유제품 포장 ➔ 3: 두유 배양검사)
    elif view == "process":
        st.markdown("<div class='main-title'>3. 공정 현황 및 특이사항 - 금일·전일 생산 및 CCP·배양 실시간 관제</div>", unsafe_allow_html=True)

        tab_p1, tab_p2, tab_p3 = st.tabs([
            f"🧃 [상온] 상온제품 공정 관리 일보 (금일 {rt_t_tab} & 전일 {rt_y_tab})",
            "🥛 [우유/발효유] 유제품 포장 공정관리 일보",
            f"🧪 [상온] 두유 배양검사 일보 (기준탭: {proc_data['soy_default_tab']})"
        ])

        with tab_p1:
            if rt_t is None:
                st.warning("상온제품 공정 관리 일보 시트 데이터를 불러오지 못했습니다.")
            else:
                c_today, c_yest = st.columns([1.25, 1])
                with c_today:
                    st.subheader(f"🟢 금일 [{rt_t['tab_title']}] 포장호기별 생산 제품 및 확인시간 ({rt_t['prod_date']})")
                    st.dataframe(rt_t["df_lines"], use_container_width=True, hide_index=True)
                with c_yest:
                    if rt_y is not None:
                        st.subheader(f"☑️ 전일 [{rt_y['tab_title']}] 생산 제품 및 멸균·특이사항 요약 ({rt_y['prod_date']})")
                        st.dataframe(rt_y["df_compact"] if not rt_y["df_compact"].empty else rt_y["df_lines"], use_container_width=True, hide_index=True)

                st.subheader(f"🔥 금일 [{rt_t['tab_title']}] 멸균기 모니터링 [CCP-1B / CCP-2P] (포장호기 제품명 및 기준 자동 매칭)")
                st.dataframe(rt_t["df_ster"], use_container_width=True, hide_index=True)

                st.subheader(f"🛡️ 금일 [{rt_t['tab_title']}] 포장기 공정관리 [CCP-3B]")
                st.dataframe(rt_t["df_ccp3b"], use_container_width=True, hide_index=True)

                if not rt_t["df_issues"].empty:
                    st.subheader("📋 상온 공정 전달(특이)사항 및 소비기한 조치 이력")
                    st.dataframe(rt_t["df_issues"], use_container_width=True, hide_index=True)

        with tab_p2:
            sub_m, sub_f = st.tabs([f"🥛 우유 포장 ({proc_data['milk_date']})", f"🍶 발효유 포장 ({proc_data['ferm_date']})"])
            with sub_m:
                only_run_m = st.checkbox("금일 실제 생산 품목만 보기 (00.00 제외)", value=True, key="chk_milk")
                df_m_v = proc_data["df_milk_pack"]
                if only_run_m and not df_m_v.empty:
                    df_m_v = df_m_v[df_m_v["가동여부"].str.contains("금일생산", na=False)]
                st.dataframe(df_m_v, use_container_width=True, hide_index=True)
            with sub_f:
                only_run_f = st.checkbox("금일 실제 생산 품목만 보기 (00.00 제외)", value=True, key="chk_ferm")
                df_f_v = proc_data["df_ferm_pack"]
                if only_run_f and not df_f_v.empty:
                    df_f_v = df_f_v[df_f_v["가동여부"].str.contains("금일생산", na=False)]
                st.dataframe(df_f_v, use_container_width=True, hide_index=True)

        with tab_p3:
            soy_map = proc_data["soy_tabs_map"]
            if not soy_map:
                st.warning("두유 배양검사 일보 날짜 탭을 불러오지 못했습니다.")
            else:
                tab_keys = list(soy_map.keys())
                def_idx = tab_keys.index(proc_data["soy_default_tab"]) if proc_data["soy_default_tab"] in tab_keys else 0
                sel_soy_tab = st.selectbox("조회할 배양검사 날짜 탭 선택 (전일 작성 탭 기본 선택)", tab_keys, index=def_idx)
                df_sb, df_sh = soy_map[sel_soy_tab]

                tot_samples = sum(int(to_float(x, 0)) for x in df_sb["총 검사수량"]) if not df_sb.empty else 0
                st.subheader(f"🔬 [{sel_soy_tab} 탭] 호기별 5일/7일 배양 개봉 판독 및 가동시간·검사수량 집계 (총 {tot_samples:,}개)")
                st.dataframe(df_sb, use_container_width=True, hide_index=True)

                if not df_sh.empty:
                    with st.expander("⏰ 시간대별(08시~07시) 샘플·Strip·Paper 체크 상세 보기"):
                        st.dataframe(df_sh, use_container_width=True, hide_index=True)

    # [세부 4] 협력업체 관리 (시트2 + 시트1 실시간 매칭 / 제목·일자·부문 제외 3단 표 / 10줄 스크롤)
    elif view == "supplier":
        if df_sup_master.empty:
            st.error(f"협력업체 심사 결과 DB를 불러오지 못했습니다: {err_sup}")
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

    # [세부 5] 심사점수 (빈칸 처리)
    elif view == "audit":
        st.markdown("<div class='main-title'>5. 심사점수</div>", unsafe_allow_html=True)
        st.info("현재 연동된 구글 시트가 없어 빈칸으로 유지 중입니다.")
        st.dataframe(pd.DataFrame([{"구분": "-", "목표": "-", "실적": "-", "비고": "-"}]), use_container_width=True, hide_index=True)

    # [세부 6] 표시사항 진행 현황
    elif view == "label_status":
        st.markdown("<div class='main-title'>6. 표시사항 진행 현황 - 현재 검토중(등록팀별) 및 연도·월별 완료 집계</div>", unsafe_allow_html=True)
        if df_label_status.empty:
            st.error(f"표시사항 현황 시트를 불러오지 못했습니다: {err_label}")
        else:
            if broken_date_cnt > 0:
                st.warning(f"시트 원본 셀에 텍스트 '#######'로 저장되어 날짜를 읽을 수 없는 행이 {broken_date_cnt}건 있습니다. 원본 엑셀에서 등록일 열 너비를 넓혀 다시 붙여넣으시면 해당 건들도 연도·월별 차트에 즉시 반영됩니다.")

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

    # [세부 7] 표시사항 특이사항 (공정 특이사항 탭 제거, 원자재 표시사항 DB 단독 구성)
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
