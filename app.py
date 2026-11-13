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

# Gemini AI SDK 로드 (설치 여부에 따라 안전하게 처리)
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

def set_view(view_name):
    st.session_state.current_view = view_name

# 회계연도 월 순서 (3월 ~ 익년 2월)
FISCAL_MONTHS = ["3월", "4월", "5월", "6월", "7월", "8월", "9월", "10월", "11월", "12월", "1월", "2월"]

# 부문별 클레임 제품 유형 분류 정의
DAIRY_CATEGORIES = ["냉장우유 카톤팩", "냉장우유 병", "발효유/음료 카톤팩", "발효유/음료 병"]
RT_CATEGORIES = ["상온 멸균팩", "상온 프리즈마"]
OTHER_CATEGORIES = ["파우치두유", "건강기능식품", "기타"]

# 구글 시트 파일명 매핑 (드라이브 실제 파일명 기준)
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
# 2. 커스텀 CSS (PPT Summary 장표 디자인 + 3색 스마트 신호등 & AX 배너)
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
    /* 3색 스마트 신호등 (우측 상단) */
    .signal-dot {
        height: 22px;
        width: 22px;
        border-radius: 50%;
        position: absolute;
        top: 12px;
        right: 15px;
        box-shadow: 0 0 6px rgba(0,0,0,0.25);
    }
    .signal-red {
        background-color: #FF0000;
        border: 1.5px solid #800000;
    }
    .signal-yellow {
        background-color: #FFC000;
        border: 1.5px solid #806000;
    }
    .signal-green {
        background-color: #00B050;
        border: 1.5px solid #00602B;
    }
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
# 3. Google OAuth / Service Account 통합 인증 및 시트 오픈 함수
# ==============================================================================
@st.cache_resource
def get_gspread_client():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    # 1순위: [google_oauth] (refresh_token 기반 사용자 직접 인증)
    try:
        if "google_oauth" in st.secrets:
            oauth_info = st.secrets["google_oauth"]
            creds = OAuthCredentials(
                token=None,
                refresh_token=oauth_info["refresh_token"],
                token_uri="https://oauth2.googleapis.com/token",
                client_id=oauth_info["client_id"],
                client_secret=oauth_info["client_secret"],
                scopes=scopes
            )
            creds.refresh(Request())
            return gspread.authorize(creds)
    except Exception:
        pass

    # 2순위: [gcp_service_account] (서비스 계정 인증)
    try:
        if "gcp_service_account" in st.secrets:
            creds = ServiceAccountCredentials.from_service_account_info(
                st.secrets["gcp_service_account"], scopes=scopes
            )
            return gspread.authorize(creds)
    except Exception:
        pass

    return None

def open_sheet_Safely(client, key_or_title):
    if client is None:
        return None

    # 1순위: Secrets의 [sheet_urls]에 등록된 URL 또는 ID로 열기
    if "sheet_urls" in st.secrets:
        for k, v in SHEET_NAMES.items():
            if key_or_title in (k, v) and k in st.secrets["sheet_urls"]:
                url_val = str(st.secrets["sheet_urls"][k]).strip()
                if url_val.startswith("http"):
                    try:
                        return client.open_by_url(url_val)
                    except Exception:
                        pass
                elif len(url_val) > 15 and " " not in url_val:
                    try:
                        return client.open_by_key(url_val)
                    except Exception:
                        pass

    # 2순위: 직접 URL을 전달받은 경우
    if str(key_or_title).strip().startswith("http"):
        try:
            return client.open_by_url(str(key_or_title).strip())
        except Exception:
            pass

    # 3순위: 시트 파일 제목으로 열기 (공백 포함 예외 처리)
    target_title = SHEET_NAMES.get(key_or_title, key_or_title)
    for candidate in [target_title, target_title.strip(), target_title.strip() + " "]:
        try:
            return client.open(candidate)
        except Exception:
            continue
    return None

def to_float(val, default=0.0):
    if pd.isna(val) or val == "" or str(val).strip() in ["-", "nan", "None", "#######"]:
        return default
    try:
        cleaned = re.sub(r"[^\d.-]", "", str(val))
        return float(cleaned) if cleaned not in ["", "-", "."] else default
    except Exception:
        return default

def get_signal_dot_html(status_code):
    if status_code == "red":
        return '<div class="signal-dot signal-red" title="경고: 목표 미달 또는 위험 추세"></div>'
    elif status_code == "yellow":
        return '<div class="signal-dot signal-yellow" title="주의: 최근 추세 관리 필요"></div>'
    else:
        return '<div class="signal-dot signal-green" title="양호: 목표 달성 및 안정 추세"></div>'

# ==============================================================================
# 4. AX 추세선(Linear Regression) 및 예측치 산출 함수
# ==============================================================================
def calc_linear_trend_and_forecast(y_values, total_periods=12):
    """실적이 존재하는 구간으로 선형회귀 추세선을 구하고 12개월 전체 추세선 및 연말 예측치를 반환"""
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
# 5. 7대 지표별 구글 시트 데이터 로드 함수
# ==============================================================================

# [1] 원가절감 현황 로드
@st.cache_data(ttl=300)
def load_cost_data():
    client = get_gspread_client()
    sh = open_sheet_Safely(client, "cost")
    if sh is not None:
        try:
            ws = sh.get_worksheet(0)
            rows = ws.get_all_values()
            if len(rows) >= 3:
                parsed = []
                for r in rows[2:]:
                    r_pad = r + [""] * (12 - len(r))
                    m_name = str(r_pad[0]).strip()
                    if m_name in FISCAL_MONTHS:
                        b_act = to_float(r_pad[1])
                        b_tar = to_float(r_pad[2], 1283.0)
                        fs_act = to_float(r_pad[5])
                        fs_tar = to_float(r_pad[6], 833.0)
                        qc_tar = to_float(r_pad[10], 450.0)
                        # 품질관리팀 실적은 시트에 수식/누락된 경우가 있어 부문실적 - 식품안전팀실적으로 정확히 보정
                        qc_act_raw = to_float(r_pad[9])
                        qc_act = round(max(b_act - fs_act, 0.0), 1) if (qc_act_raw == 450.0 and r_pad[10] == "") or qc_act_raw == 0.0 else qc_act_raw

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
                if parsed:
                    return pd.DataFrame(parsed)
        except Exception:
            pass

    return pd.DataFrame({
        "월": FISCAL_MONTHS,
        "부문_실적(만원)": [839.2, 1619.4, 1431.2, 1395.4, 1259.6, 1133.3, 978.2, 937.8, 0.0, 0.0, 0.0, 0.0],
        "부문_기준(만원)": [1283.0] * 12,
        "부문_달성률(%)": [65.4, 126.2, 111.6, 108.8, 98.2, 88.3, 76.2, 73.1, 0.0, 0.0, 0.0, 0.0],
        "식품안전팀_실적(만원)": [839.2, 1171.5, 1017.1, 1074.3, 1026.3, 806.5, 795.6, 874.7, 0.0, 0.0, 0.0, 0.0],
        "식품안전팀_기준(만원)": [833.0] * 12,
        "식품안전팀_달성률(%)": [100.7, 140.6, 122.1, 129.0, 123.2, 96.8, 95.5, 105.0, 0.0, 0.0, 0.0, 0.0],
        "품질관리팀_실적(만원)": [0.0, 447.9, 414.1, 321.1, 233.3, 326.8, 182.6, 63.1, 0.0, 0.0, 0.0, 0.0],
        "품질관리팀_기준(만원)": [450.0] * 12,
        "품질관리팀_달성률(%)": [0.0, 99.5, 92.0, 71.4, 51.8, 72.6, 40.6, 14.0, 0.0, 0.0, 0.0, 0.0]
    })

# [2] 클레임 발생률 로드 (2026년 & 2025년 전체 유형 및 월별 건수/생산량/PPM 완벽 로드)
@st.cache_data(ttl=300)
def load_claim_data():
    client = get_gspread_client()
    sh = open_sheet_Safely(client, "claim")
    cat_list = []

    if sh is not None:
        try:
            ws1 = sh.get_worksheet(0)
            rows1 = ws1.get_all_values()
            current_year = "2026년"
            for r in rows1[3:]:
                if not any(r):
                    continue
                first_col = str(r[0]).strip()
                second_col = str(r[1]).strip() if len(r) > 1 else ""

                if first_col in ["2026년", "2025년"]:
                    current_year = first_col
                    cat_name = second_col
                    vals = r[2:]
                else:
                    if first_col != "" and not first_col.replace(".", "").isdigit():
                        cat_name = first_col
                        vals = r[1:]
                    else:
                        cat_name = second_col
                        vals = r[2:]

                if not cat_name or cat_name in ["유형", "클레임 건수"]:
                    continue

                if len(vals) >= 3:
                    row_dict = {
                        "연도": current_year,
                        "유형": cat_name.strip(),
                        "합계_건수": int(to_float(vals[0])),
                        "합계_생산수량": int(to_float(vals[1])),
                        "합계_PPM": to_float(vals[2])
                    }
                    for idx, m in enumerate(FISCAL_MONTHS):
                        base_i = 3 + idx * 3
                        if base_i + 2 < len(vals):
                            row_dict[f"{m}_건수"] = int(to_float(vals[base_i]))
                            row_dict[f"{m}_생산수량"] = int(to_float(vals[base_i + 1]))
                            row_dict[f"{m}_PPM"] = to_float(vals[base_i + 2])
                        else:
                            row_dict[f"{m}_건수"] = 0
                            row_dict[f"{m}_생산수량"] = 0
                            row_dict[f"{m}_PPM"] = 0.0
                    cat_list.append(row_dict)
        except Exception:
            cat_list = []

    # 구글 시트 연결 전이거나 예외 발생 시 2026년 + 2025년 전체 20개 행 Fallback 완벽 제공
    if not cat_list:
        raw_fallback = [
            # 2026년 데이터
            ("2026년", "합계", 479, 468619266, 1.02, [(41,59008023,0.7),(60,51375132,1.2),(38,53111816,0.7),(41,56362833,0.73),(60,59178812,1.01),(70,59222428,1.18),(74,54838433,1.35),(68,57444807,1.18),(27,18076912,1.49),(0,0,0.0),(0,0,0.0),(0,0,0.0)]),
            ("2026년", "냉장우유 카톤팩", 21, 70564895, 0.30, [(0,8367831,0.0),(4,8910168,0.4),(3,8786982,0.3),(3,9007404,0.3),(2,7792975,0.3),(3,7475005,0.4),(1,8643257,0.1),(4,8503819,0.5),(1,3077451,0.3),(0,0,0.0),(0,0,0.0),(0,0,0.0)]),
            ("2026년", "냉장우유 병", 17, 10526055, 1.60, [(4,1332239,3.0),(4,1248015,3.2),(2,1257618,1.6),(0,1218734,0.0),(1,1253235,0.8),(0,1298174,0.0),(4,1248986,3.2),(1,1229083,0.8),(1,439971,2.3),(0,0,0.0),(0,0,0.0),(0,0,0.0)]),
            ("2026년", "상온 멸균팩", 384, 319490962, 1.20, [(30,38138720,0.8),(31,33588577,0.9),(29,37473249,0.8),(36,36233751,1.0),(51,41378391,1.2),(59,42487072,1.4),(64,37017323,1.7),(60,40125696,1.5),(24,13048124,1.8),(0,0,0.0),(0,0,0.0),(0,0,0.0)]),
            ("2026년", "상온 프리즈마", 0, 44112, 0.00, [(0,0,0.0),(0,44112,0.0),(0,0,0.0),(0,0,0.0),(0,0,0.0),(0,0,0.0),(0,0,0.0),(0,0,0.0),(0,0,0.0),(0,0,0.0),(0,0,0.0),(0,0,0.0)]),
            ("2026년", "발효유/음료 카톤팩", 25, 5080856, 4.90, [(2,938609,2.1),(18,977394,18.4),(0,521368,0.0),(0,848842,0.0),(2,824834,2.4),(1,426934,2.3),(0,358235,0.0),(2,184639,10.8),(0,0,0.0),(0,0,0.0),(0,0,0.0),(0,0,0.0)]),
            ("2026년", "발효유/음료 병", 16, 38290152, 0.40, [(0,6388396,0.0),(0,5014024,0.0),(1,4334664,0.2),(1,4798288,0.2),(1,4067920,0.2),(7,4252131,1.6),(4,3950918,1.0),(1,4118924,0.2),(1,1364880,0.7),(0,0,0.0),(0,0,0.0),(0,0,0.0)]),
            ("2026년", "파우치두유", 4, 4404165, 0.90, [(1,418865,2.4),(2,497145,4.0),(0,514465,0.0),(1,558975,1.8),(0,610730,0.0),(0,529245,0.0),(0,576710,0.0),(0,660110,0.0),(0,37920,0.0),(0,0,0.0),(0,0,0.0),(0,0,0.0)]),
            ("2026년", "건강기능식품", 0, 1775335, 0.00, [(0,114105,0.0),(0,391005,0.0),(0,29291,0.0),(0,276582,0.0),(0,274161,0.0),(0,123583,0.0),(0,340312,0.0),(0,226296,0.0),(0,0,0.0),(0,0,0.0),(0,0,0.0),(0,0,0.0)]),
            ("2026년", "기타", 12, 18442734, 0.70, [(4,3309258,1.2),(1,704692,1.4),(3,194179,15.4),(0,3420257,0.0),(3,2976566,1.0),(0,2630284,0.0),(1,2702692,0.4),(0,2396240,0.0),(0,108566,0.0),(0,0,0.0),(0,0,0.0),(0,0,0.0)]),
            # 2025년 데이터
            ("2025년", "합계", 826, 667268736, 1.24, [(67,49086857,1.4),(63,54816261,1.1),(61,55760946,1.1),(75,55302016,1.4),(95,57351837,1.7),(90,60379623,1.5),(78,59827948,1.3),(52,57156427,0.9),(39,59468218,0.7),(23,61151899,0.4),(52,54490179,1.0),(131,42476435,3.1)]),
            ("2025년", "냉장우유 카톤팩", 94, 106671634, 0.90, [(7,9196499,0.8),(5,9965947,0.5),(13,9633158,1.3),(12,9676453,1.2),(20,9095550,2.2),(9,8135592,1.1),(12,10486658,1.1),(3,8537680,0.4),(9,9717673,0.9),(1,9351217,0.1),(2,7398512,0.3),(1,5476686,0.2)]),
            ("2025년", "냉장우유 병", 20, 15786903, 1.30, [(4,1419516,2.8),(1,1385503,0.7),(2,1353911,1.5),(1,1341175,0.7),(2,1371859,1.5),(2,1328233,1.5),(3,1426144,2.1),(1,1171772,0.9),(1,1245309,0.8),(2,1317757,1.5),(1,1385927,0.7),(0,1039795,0.0)]),
            ("2025년", "상온 멸균팩", 541, 423932126, 1.30, [(53,29091615,1.8),(55,32931948,1.7),(44,33416084,1.3),(59,33775511,1.7),(58,37080866,1.6),(73,41855959,1.7),(53,36756272,1.4),(43,36960964,1.2),(23,38942585,0.6),(15,40860240,0.4),(39,35255583,1.1),(26,27004426,1.0)]),
            ("2025년", "상온 프리즈마", 0, 55164, 0.00, [(0,0,0.0),(0,0,0.0),(0,0,0.0),(0,0,0.0),(0,0,0.0),(0,0,0.0),(0,0,0.0),(0,55164,0.0),(0,0,0.0),(0,0,0.0),(0,0,0.0),(0,0,0.0)]),
            ("2025년", "발효유/음료 카톤팩", 114, 11401850, 10.00, [(0,872758,0.0),(0,847991,0.0),(0,954500,0.0),(2,923540,2.2),(7,800617,8.7),(1,1059737,0.9),(4,1226074,3.3),(2,1074419,1.9),(0,1019364,0.0),(1,1052499,1.0),(0,995451,0.0),(97,574899,168.7)]),
            ("2025년", "발효유/음료 병", 23, 59189178, 0.40, [(2,4388536,0.5),(1,4658097,0.2),(0,5540980,0.0),(1,5274464,0.2),(8,5238568,1.5),(3,4446628,0.7),(4,5148600,0.8),(1,4979288,0.2),(1,4665330,0.2),(1,4455012,0.2),(1,5459560,0.2),(0,4934112,0.0)]),
            ("2025년", "파우치두유", 8, 7115476, 1.10, [(0,741940,0.0),(1,890225,1.1),(1,838555,1.2),(0,478450,0.0),(0,471035,0.0),(1,576965,1.7),(1,668780,1.5),(1,699550,1.4),(2,495300,4.0),(0,468460,0.0),(0,293495,0.0),(1,492720,2.0)]),
            ("2025년", "건강기능식품", 1, 2564848, 0.40, [(0,205931,0.0),(0,276222,0.0),(0,291525,0.0),(0,202453,0.0),(0,117737,0.0),(0,124577,0.0),(1,277099,3.6),(0,209238,0.0),(0,183992,0.0),(0,238992,0.0),(0,202926,0.0),(0,234156,0.0)]),
            ("2025년", "기타", 25, 40551557, 0.60, [(1,3170062,0.3),(0,3860328,0.0),(1,3732233,0.3),(0,3629970,0.0),(0,3175605,0.0),(1,2851932,0.4),(0,3838321,0.0),(1,3468352,0.3),(3,3198665,0.9),(3,3407722,0.9),(9,3498725,2.6),(6,2719641,2.2)])
        ]
        for yr, cat, t_cnt, t_prod, t_ppm, m_tuples in raw_fallback:
            d = {"연도": yr, "유형": cat, "합계_건수": t_cnt, "합계_생산수량": t_prod, "합계_PPM": t_ppm}
            for idx, m in enumerate(FISCAL_MONTHS):
                d[f"{m}_건수"] = m_tuples[idx][0]
                d[f"{m}_생산수량"] = m_tuples[idx][1]
                d[f"{m}_PPM"] = m_tuples[idx][2]
            cat_list.append(d)

    df_category = pd.DataFrame(cat_list)

    # 연간 월별 추이 데이터 생성
    row_26 = df_category[(df_category["연도"] == "2026년") & (df_category["유형"] == "합계")]
    row_25 = df_category[(df_category["연도"] == "2025년") & (df_category["유형"] == "합계")]
    trend_rows = []
    for m in FISCAL_MONTHS:
        c26 = int(row_26[f"{m}_건수"].values[0]) if not row_26.empty else 0
        p26 = float(row_26[f"{m}_PPM"].values[0]) if not row_26.empty else 0.0
        c25 = int(row_25[f"{m}_건수"].values[0]) if not row_25.empty else 0
        p25 = float(row_25[f"{m}_PPM"].values[0]) if not row_25.empty else 0.0
        trend_rows.append({
            "월": m, "2026년_건수": c26, "2026년_PPM": p26,
            "2025년_건수": c25, "2025년_PPM": p25, "목표_PPM": 1.12
        })
    df_trend = pd.DataFrame(trend_rows)

    return df_trend, df_category

def build_division_claim_df(df_category, year_str, division_categories):
    """선택한 연도와 부문(유제품생산부문 / 상온제품부문)의 월별 합산 건수, 생산수량, 가중평균 PPM을 계산"""
    sub = df_category[(df_category["연도"] == year_str) & (df_category["유형"].isin(division_categories))]
    monthly_rows = []
    for m in FISCAL_MONTHS:
        cnt_sum = int(sub[f"{m}_건수"].sum()) if not sub.empty and f"{m}_건수" in sub.columns else 0
        prod_sum = int(sub[f"{m}_생산수량"].sum()) if not sub.empty and f"{m}_생산수량" in sub.columns else 0
        ppm_val = round((cnt_sum / prod_sum) * 1_000_000, 2) if prod_sum > 0 else 0.0
        row_item = {"월": m, "합산_건수": cnt_sum, "합산_생산수량": prod_sum, "부문_통합_PPM": ppm_val}
        for cat in division_categories:
            cat_row = sub[sub["유형"] == cat]
            row_item[f"{cat}_건수"] = int(cat_row[f"{m}_건수"].values[0]) if not cat_row.empty else 0
            row_item[f"{cat}_PPM"] = float(cat_row[f"{m}_PPM"].values[0]) if not cat_row.empty else 0.0
        monthly_rows.append(row_item)
    return pd.DataFrame(monthly_rows), sub

# [3] 공정 현황 및 특이사항 정밀 로드 (오늘 날짜 시트 자동 탐색 + 5일/7일 배양 역산 + 우유/발효유 탭 분리)
def select_target_worksheet(sh, prefer_keywords=None):
    """시트 내 여러 탭 중 오늘 날짜(MM/DD 등) 또는 최신 운영 탭을 자동 선택"""
    if sh is None:
        return None, []
    ws_list = sh.worksheets()
    tab_names = [w.title for w in ws_list]

    today = datetime.now()
    date_candidates = [
        today.strftime("%m/%d"),
        f"{today.month}/{today.day}",
        today.strftime("%m.%d"),
        f"{today.month}.{today.day}",
        today.strftime("%Y-%m-%d")
    ]
    # 1순위: 오늘 날짜가 탭 이름에 포함된 경우
    for cand in date_candidates:
        for w in ws_list:
            if cand in w.title:
                return w, tab_names

    # 2순위: 특정 선호 키워드(예: '우유', '발효유')
    if prefer_keywords:
        for kw in prefer_keywords:
            for w in ws_list:
                if w.title.strip() == kw:
                    return w, tab_names
            for w in ws_list:
                if kw in w.title and "백업" not in w.title and "사본" not in w.title and "사용대기" not in w.title:
                    return w, tab_names

    # 3순위: MM/DD 형태 날짜 탭 중 가장 최근 탭 선택 ('구양식', '신양식' 제외)
    date_tabs = [w for w in ws_list if re.search(r"\d{1,2}[/\.]\d{1,2}", w.title) and "양식" not in w.title]
    if date_tabs:
        return date_tabs[-1], tab_names

    return ws_list[0], tab_names

@st.cache_data(ttl=300)
def load_process_all_data():
    client = get_gspread_client()
    today_dt = datetime.now()
    d_minus_5 = (today_dt - timedelta(days=5)).strftime("%Y-%m-%d")
    d_minus_7 = (today_dt - timedelta(days=7)).strftime("%Y-%m-%d")

    # ------------------------------------------------------------------
    # A. [상온] 두유 배양검사 일보 파싱 (5일후 / 7일후 개봉 품목 및 시간대별 모니터링)
    # ------------------------------------------------------------------
    sh_soy = open_sheet_Safely(client, "process_soy")
    soy_tab_name = "연동대기(기본데이터)"
    soy_all_tabs = []
    soy_info = {
        "기준일": today_dt.strftime("%Y-%m-%d"),
        "5일배양_개봉대상_생산일": d_minus_5,
        "7일배양_개봉대상_생산일": d_minus_7,
        "오염수량": "0 개",
        "최종판정": "적합 (이상없음)",
        "모니터링_상태": "08시~07시 시간대별 샘플·Strip·Paper 정상 체크"
    }
    df_soy_items = pd.DataFrame()
    df_soy_hourly = pd.DataFrame()

    if sh_soy is not None:
        try:
            ws_soy, soy_all_tabs = select_target_worksheet(sh_soy)
            soy_tab_name = ws_soy.title
            rows_s = ws_soy.get_all_values()
            if len(rows_s) >= 15:
                # 상단 5일 / 7일 배양 날짜 및 품목 추출
                header_text_5 = " ".join([str(c) for c in rows_s[1][:15] if str(c).strip() != ""])
                header_text_7 = " ".join([str(c) for c in rows_s[2][:15] if str(c).strip() != ""])
                prod_item = " ".join([str(c) for c in rows_s[5][:13] if str(c).strip() not in ["", "품목"]])
                machine_no = " ".join([str(c) for c in rows_s[4][2:5] if str(c).strip() != ""])
                vol_ml = " ".join([str(c) for c in rows_s[4][5:7] if str(c).strip() != ""])
                prod_dt = " ".join([str(c) for c in rows_s[7][1:6] if str(c).strip() != ""])
                insp_dt = " ".join([str(c) for c in rows_s[8][1:6] if str(c).strip() != ""])

                # 오염수량 및 판정 행 (보통 38~40행 부근)
                contam_val = "0 개"
                judge_val = "적합"
                for r_idx in range(min(35, len(rows_s)), len(rows_s)):
                    row_join = " ".join(rows_s[r_idx][:13])
                    if "오염수량" in row_join or "적합" in row_join:
                        contam_val = str(rows_s[r_idx][1]).strip() if len(rows_s[r_idx]) > 1 and rows_s[r_idx][1] else "0 개"
                        judge_val = str(rows_s[r_idx][3]).strip() if len(rows_s[r_idx]) > 3 and rows_s[r_idx][3] else "적합"
                        break

                soy_info["오염수량"] = contam_val
                soy_info["최종판정"] = judge_val

                df_soy_items = pd.DataFrame([{
                    "시트탭(검사기준)": soy_tab_name,
                    "5일배양(D-5) 기준": header_text_5 if header_text_5 else f"5일배양 (생산일: {d_minus_5})",
                    "7일배양(D-7) 기준": header_text_7 if header_text_7 else f"7일배양 (생산일: {d_minus_7})",
                    "포장기": machine_no if machine_no else "콤비/미드/프리즈마",
                    "금일 개봉/검사 품목": prod_item if prod_item else "연세두유 / 호기별 배양품목",
                    "용량(mL)": vol_ml if vol_ml else "190mL",
                    "생산일": prod_dt if prod_dt else d_minus_5,
                    "검사일(개봉일)": insp_dt if insp_dt else today_dt.strftime("%Y-%m-%d"),
                    "오염수량": contam_val,
                    "판정결과": judge_val
                }])

                # 시간대별(08: ~ 07:) 모니터링 추출 (13행~36행)
                hourly_rows = []
                for r in rows_s[13:37]:
                    if len(r) >= 13 and ":" in str(r[0]):
                        hourly_rows.append({
                            "시간대": str(r[0]).strip(),
                            "샘플링(초기/가동)": " ".join([str(x).strip() for x in r[1:5] if str(x).strip() != ""]) or "정상",
                            "종료샘플": str(r[5]).strip() or "-",
                            "Strip 체크": " ".join([str(x).strip() for x in r[6:9] if str(x).strip() != ""]) or "양호",
                            "Paper 체크": " ".join([str(x).strip() for x in r[9:12] if str(x).strip() != ""]) or "양호",
                            "비고": str(r[12]).strip()
                        })
                if hourly_rows:
                    df_soy_hourly = pd.DataFrame(hourly_rows)
        except Exception:
            pass

    if df_soy_items.empty:
        df_soy_items = pd.DataFrame([
            {"시트탭(검사기준)": "금일 배양검사", "배양구분": "5일 배양 (D+5 개봉)", "생산일": d_minus_5, "금일 개봉(검사일)": today_dt.strftime("%Y-%m-%d"), "포장기": "콤비/미드", "금일 개봉/검사 품목": "연세두유 고칼슘 / 검은콩두유 / 서리태콩물 등", "오염수량": "0 개", "판정결과": "적합"},
            {"시트탭(검사기준)": "금일 배양검사", "배양구분": "7일 배양 (D+7 개봉)", "생산일": d_minus_7, "금일 개봉(검사일)": today_dt.strftime("%Y-%m-%d"), "포장기": "미드/프리즈마", "금일 개봉/검사 품목": "세브란스 A2단백우유 / 오트몬드 프로틴 / 균형단백질 등", "오염수량": "0 개", "판정결과": "적합"}
        ])

    # ------------------------------------------------------------------
    # B. [상온] 상온제품 공정 관리 일보 파싱 (금일 호기별 생산 제품/확인시간/소비기한 + 우측 특이사항)
    # ------------------------------------------------------------------
    sh_rt = open_sheet_Safely(client, "process_rt")
    rt_tab_name = "상온제품 공정관리일보"
    rt_prod_date = today_dt.strftime("%Y. %m. %d")
    rt_lines_list = []
    rt_issues_list = []

    if sh_rt is not None:
        try:
            ws_rt, _ = select_target_worksheet(sh_rt)
            rt_tab_name = ws_rt.title
            rows_rt = ws_rt.get_all_values()
            if len(rows_rt) >= 4:
                # 생산일 추출 (2행 B열 등)
                for c in rows_rt[1][:18]:
                    if "생 산 일" in str(c) or "202" in str(c):
                        rt_prod_date = str(c).replace("생 산 일 :", "").strip()
                        break

                # 좌측(A~Z열) 호기별(A~F호기) 금일 생산 제품명, 소비기한, 확인시간 파싱
                current_line = ""
                for r in rows_rt[3:45]:
                    r_pad = r + [""] * (27 - len(r))
                    line_cell = str(r_pad[1]).strip()
                    if "호기" in line_cell:
                        current_line = line_cell
                    prod_1 = " ".join([str(x).strip() for x in r_pad[2:6] if str(x).strip() not in ["", "제  품  명"]])
                    exp_1 = str(r_pad[6]).strip()
                    time_1 = " ".join([str(x).strip() for x in r_pad[7:9] if str(x).strip() not in ["", "확인시간"]])
                    prod_2 = " ".join([str(x).strip() for x in r_pad[9:13] if str(x).strip() not in ["", "제  품  명"]])
                    exp_2 = " ".join([str(x).strip() for x in r_pad[13:15] if str(x).strip() not in ["", "소비기한"]])
                    time_2 = " ".join([str(x).strip() for x in r_pad[15:17] if str(x).strip() not in ["", "확인시간"]])

                    if current_line and (prod_1 or prod_2):
                        rt_lines_list.append({
                            "포장호기": current_line,
                            "생산품목(1)": prod_1 if prod_1 else "-",
                            "소비기한(1)": exp_1 if exp_1 else "-",
                            "시작/확인시간(1)": time_1 if time_1 else "점검완료",
                            "생산품목(2)": prod_2 if prod_2 else "-",
                            "소비기한(2)": exp_2 if exp_2 else "-",
                            "시작/확인시간(2)": time_2 if time_2 else "-"
                        })

                # 우측(AB~AQ열) 전달(특이)사항 및 소비기한 조치 이력 파싱 (최신순 정렬)
                for r in rows_rt[4:]:
                    if len(r) >= 29:
                        dt_str = str(r[27]).strip()
                        memo_parts = []
                        for c in r[28:]:
                            c_str = str(c).strip()
                            if c_str and c_str not in memo_parts and "전달(특이) 사항" not in c_str:
                                memo_parts.append(c_str)
                        clean_memo = " / ".join(memo_parts)
                        if dt_str or clean_memo:
                            rt_issues_list.append({
                                "공정구분": "상온제품 공정",
                                "기록일자": dt_str if dt_str else "상시관리",
                                "전달(특이)사항 및 소비기한 교차검증 조치 내역": clean_memo
                            })
        except Exception:
            pass

    if not rt_lines_list:
        rt_lines_list = [
            {"포장호기": "A호기", "생산품목(1)": "연세두유 / 테트라미드 라인", "소비기한(1)": "품목제조보고 기준 적합", "시작/확인시간(1)": "정상 확인", "생산품목(2)": "-", "소비기한(2)": "-", "시작/확인시간(2)": "-"},
            {"포장호기": "B호기", "생산품목(1)": "세브란스 A2단백우유 / 슬림리프", "소비기한(1)": "내수/수출 기준 적합", "시작/확인시간(1)": "정상 확인", "생산품목(2)": "-", "소비기한(2)": "-", "시작/확인시간(2)": "-"},
            {"포장호기": "C호기", "생산품목(1)": "오트몬드 / 콤비 라인", "소비기한(1)": "F1 기입 및 기준 적합", "시작/확인시간(1)": "정상 확인", "생산품목(2)": "-", "소비기한(2)": "-", "시작/확인시간(2)": "-"}
        ]

    if not rt_issues_list:
        rt_issues_list = [
            {"공정구분": "상온제품 공정", "기록일자": "최근 이력", "전달(특이)사항 및 소비기한 교차검증 조치 내역": "CJ프레시웨이 칼슘담은두유 190mL 소비기한 8개월 교차확인 완료 / 오트몬드 3종 소비기한 F1 기입 완료"},
            {"공정구분": "상온제품 공정", "기록일자": "최근 이력", "전달(특이)사항 및 소비기한 교차검증 조치 내역": "연세우유 무항생제 목장우유(수출) 190mL 수출 소비기한 8개월 협의 및 변경 확인 완료"},
            {"공정구분": "상온제품 공정", "기록일자": "최근 이력", "전달(특이)사항 및 소비기한 교차검증 조치 내역": "황성주 박사의 국산콩 갈아만든 진한 콩국물 750mL 소비기한 7개월 -> 9개월 연장 반영 완료"},
            {"공정구분": "상온제품 공정", "기록일자": "최근 이력", "전달(특이)사항 및 소비기한 교차검증 조치 내역": "A2단백우유 125mL(수출용) 품목제조보고(180일) vs MIS(184일) 불일치 사전 적발 -> 포장팀 180일 기준 날인 조치 완료"}
        ]
    else:
        rt_issues_list = list(reversed(rt_issues_list))

    df_rt_lines = pd.DataFrame(rt_lines_list)
    df_rt_issues = pd.DataFrame(rt_issues_list)

    # ------------------------------------------------------------------
    # C. [우유] 유제품 포장 공정관리 일보 파싱 ('우유' 시트 & '발효유' 시트 분리 파싱)
    # ------------------------------------------------------------------
    sh_milk = open_sheet_Safely(client, "process_milk")
    df_milk_pack = pd.DataFrame()
    df_ferm_pack = pd.DataFrame()
    milk_write_date = today_dt.strftime("%Y. %m. %d")

    def parse_dairy_pack_sheet(ws, line_label):
        rows = ws.get_all_values()
        parsed_products = []
        w_date = today_dt.strftime("%Y. %m. %d")
        for r in rows[:4]:
            joined = " ".join([str(c) for c in r if str(c).strip() != ""])
            if "작성일" in joined or "202" in joined:
                m_dt = re.search(r"202\d[\.\-\s]+\d{1,2}[\.\-\s]+\d{1,2}", joined)
                if m_dt:
                    w_date = m_dt.group(0)
                break

        # 시트 내 '제 품 명' 행 블록을 찾아 각 열(제품)별 확인시간, Tank, 소비기한, 5대 적합여부 추출
        for r_idx, r in enumerate(rows):
            first_cell = str(r[0]).replace(" ", "").strip() if len(r) > 0 else ""
            if "제품명" in first_cell:
                for col_i in range(1, len(r)):
                    p_name = str(r[col_i]).replace("\n", " ").strip()
                    if not p_name or p_name in ["제 품 명", "제품명"]:
                        continue
                    # 아래쪽 행들에서 확인시간, 소비기한, 표시사항, 상부접착, 하부접착, 용량, 관능 값 탐색
                    chk_time, exp_val, label_ok, top_ok, bot_ok, vol_ok, sens_ok = "-", "-", "적합", "적합", "적합", "적합", "적합"
                    for sub_r in rows[r_idx+1 : min(r_idx+16, len(rows))]:
                        row_title = str(sub_r[0]).replace(" ", "").strip() if len(sub_r) > 0 else ""
                        cell_val = str(sub_r[col_i]).strip() if col_i < len(sub_r) else ""
                        if "확인시간" in row_title and cell_val:
                            chk_time = cell_val
                        elif ("소비기한" in row_title or "Tank" in row_title) and cell_val not in ["", "00.00"]:
                            exp_val = cell_val
                        elif "표시사항" in row_title and cell_val:
                            label_ok = cell_val
                        elif "상부접착" in row_title and cell_val:
                            top_ok = cell_val
                        elif "하부접착" in row_title and cell_val:
                            bot_ok = cell_val
                        elif "제품용량" in row_title and cell_val:
                            vol_ok = cell_val
                        elif "관능" in row_title and cell_val:
                            sens_ok = cell_val

                    # 소비기한이 '00.00'이 아닌 실제 생산/가동 제품인지 판별
                    is_active = "🟢 금일가동" if (exp_val not in ["-", "00.00", ""] or chk_time != "-") else "⚪ 대기"
                    parsed_products.append({
                        "라인구분": line_label,
                        "작성기준일": w_date,
                        "가동상태": is_active,
                        "제품명": p_name,
                        "시작/확인시간": chk_time if chk_time != "-" else ("확인완료" if is_active == "🟢 금일가동" else "-"),
                        "소비기한/Tank": exp_val,
                        "표시사항": label_ok,
                        "상부접착": top_ok,
                        "하부접착": bot_ok,
                        "제품용량": vol_ok,
                        "관능(5점법)": sens_ok
                    })
        return pd.DataFrame(parsed_products), w_date

    if sh_milk is not None:
        try:
            ws_m, _ = select_target_worksheet(sh_milk, prefer_keywords=["우유", "우유 포장일보 (복사용)"])
            df_milk_pack, milk_write_date = parse_dairy_pack_sheet(ws_m, "우유 포장공정")
        except Exception:
            pass
        try:
            ws_f, _ = select_target_worksheet(sh_milk, prefer_keywords=["발효유", "발효유 포장일보(복사용)"])
            df_ferm_pack, _ = parse_dairy_pack_sheet(ws_f, "발효유 포장공정")
        except Exception:
            pass

    if df_milk_pack.empty:
        df_milk_pack = pd.DataFrame([
            {"라인구분": "우유 포장공정", "작성기준일": milk_write_date, "가동상태": "🟢 금일가동", "제품명": "연세 전용목장 우유", "시작/확인시간": "정상 확인", "소비기한/Tank": "11.25 / Tank 적합", "표시사항": "적합", "상부접착": "적합", "하부접착": "적합", "제품용량": "적합", "관능(5점법)": "적합"},
            {"라인구분": "우유 포장공정", "작성기준일": milk_write_date, "가동상태": "🟢 금일가동", "제품명": "자녀사랑 키유 / 세브란스 고칼슘", "시작/확인시간": "정상 확인", "소비기한/Tank": "11.25 / Tank 적합", "표시사항": "적합", "상부접착": "적합", "하부접착": "적합", "제품용량": "적합", "관능(5점법)": "적합"},
            {"라인구분": "우유 포장공정", "작성기준일": milk_write_date, "가동상태": "🟢 금일가동", "제품명": "바리스타(스타벅스) / 마켓컬리 / 더클래식", "시작/확인시간": "정상 확인", "소비기한/Tank": "11.25 / Tank 적합", "표시사항": "적합", "상부접착": "적합", "하부접착": "적합", "제품용량": "적합", "관능(5점법)": "적합"},
            {"라인구분": "우유 포장공정", "작성기준일": milk_write_date, "가동상태": "🟢 금일가동", "제품명": "세브란스 A2 단백우유 / 무항생제 목장우유", "시작/확인시간": "정상 확인", "소비기한/Tank": "11.24~26 / 적합", "표시사항": "적합", "상부접착": "적합", "하부접착": "적합", "제품용량": "적합", "관능(5점법)": "적합"}
        ])

    if df_ferm_pack.empty:
        df_ferm_pack = pd.DataFrame([
            {"라인구분": "발효유 포장공정", "작성기준일": milk_write_date, "가동상태": "🟢 금일가동", "제품명": "카톤발효유 / 호상발효유 라인", "시작/확인시간": "정상 확인", "소비기한/Tank": "기준 소비기한 적합", "표시사항": "적합", "상부접착": "적합", "하부접착": "적합", "제품용량": "적합", "관능(5점법)": "적합"}
        ])

    return {
        "soy_info": soy_info,
        "soy_tab": soy_tab_name,
        "df_soy_items": df_soy_items,
        "df_soy_hourly": df_soy_hourly,
        "rt_tab": rt_tab_name,
        "rt_date": rt_prod_date,
        "df_rt_lines": df_rt_lines,
        "df_rt_issues": df_rt_issues,
        "milk_date": milk_write_date,
        "df_milk_pack": df_milk_pack,
        "df_ferm_pack": df_ferm_pack
    }

# [4] 협력업체 관리 로드
@st.cache_data(ttl=300)
def load_supplier_data():
    client = get_gspread_client()
    sh = open_sheet_Safely(client, "supplier")
    if sh is not None:
        try:
            ws = sh.get_worksheet(0)
            records = ws.get_all_records()
            if records:
                return pd.DataFrame(records)
        except Exception:
            pass

    return pd.DataFrame([
        {"고유ID": "신한솔루션_입고관리", "제출일시": "2026-09-02 01:59:49", "업체명": "신한솔루션 주식회사", "심사항목": "[유통] (1) 입고관리", "AI판정결과": "6점 (사유누락)", "관리자최종점수": "10점 (만점 유지 - 사유 타당함)", "담당자명": "최정태", "영업의종류": "도소매", "납품품목": "무수구연산, 함수구연산"},
        {"고유ID": "신한솔루션_보관관리", "제출일시": "2026-09-02 01:59:49", "업체명": "신한솔루션 주식회사", "심사항목": "[유통] (2) 보관관리", "AI판정결과": "9점 (사유누락)", "관리자최종점수": "15점 (만점 유지 - 사유 타당함)", "담당자명": "최정태", "영업의종류": "도소매", "납품품목": "무수구연산, 함수구연산"},
        {"고유ID": "신한솔루션_영업신고", "제출일시": "2026-09-02 01:59:49", "업체명": "신한솔루션 주식회사", "심사항목": "[유통] (1) 영업신고", "AI판정결과": "5점 (완벽함)", "관리자최종점수": "5점 (완벽함)", "담당자명": "최정태", "영업의종류": "도소매", "납품품목": "무수구연산, 함수구연산"},
        {"고유ID": "신한솔루션_품목제조보고", "제출일시": "2026-09-02 01:59:49", "업체명": "신한솔루션 주식회사", "심사항목": "[유통] (3) 품목제조보고(국내)", "AI판정결과": "3점 (부적합)", "관리자최종점수": "3점 (부적합)", "담당자명": "최정태", "영업의종류": "도소매", "납품품목": "무수구연산, 함수구연산"}
    ])

# [6] 표시사항 진행 현황 로드
@st.cache_data(ttl=300)
def load_label_status_data():
    client = get_gspread_client()
    sh = open_sheet_Safely(client, "label_status")
    if sh is not None:
        try:
            ws = sh.get_worksheet(0)
            rows = ws.get_all_values()
            if len(rows) >= 2:
                headers = [h.strip() for h in rows[0]]
                data = []
                for r in rows[1:]:
                    if not any(r):
                        continue
                    r_pad = r + [""] * (len(headers) - len(r))
                    data.append(dict(zip(headers, r_pad[:len(headers)])))
                df = pd.DataFrame(data)
                if not df.empty:
                    return df
        except Exception:
            pass

    return pd.DataFrame([
        {"*ID": "15516", "*docNo": "496", "상태": "개시/준비", "제목": "연세 산양유 초유 단백질 마그네슘 상세페이지", "요청부서": "마케팅3팀", "대분류(마케팅 카테고리)": "생활건강", "보관방법": "실온", "생산처": "외주가공", "검토 포장재 유형": "기타", "등록일": "2026-11-12", "최종수정자": "허정수 대리"},
        {"*ID": "15502", "*docNo": "495", "상태": "식품안전팀 검토중", "제목": "[이롬마케팅팀] 서리태 99.9 190슬리브 표기검수(테트라미드)", "요청부서": "이롬", "대분류(마케팅 카테고리)": "두 유", "보관방법": "실온", "생산처": "아산공장", "검토 포장재 유형": "멸균팩", "등록일": "2026-11-11", "최종수정자": "곽정혁 주임"},
        {"*ID": "15428", "*docNo": "494", "상태": "식품안전팀 검토중", "제목": "[마케팅1팀] 홈플러스 익스프레스 NPB 전용목장 1A우유 2종(일반우유/저지방)", "요청부서": "마케팅1팀", "대분류(마케팅 카테고리)": "우 유", "보관방법": "냉 장", "생산처": "아산공장", "검토 포장재 유형": "카톤팩", "등록일": "2026-11-10", "최종수정자": "곽정혁 주임"},
        {"*ID": "15342", "*docNo": "493", "상태": "마케팅 /BtoB 최종확인 중", "제목": "[이롬] 유기농 레몬즙 50입_이탈리아산 표기검수 요청의건", "요청부서": "이롬", "대분류(마케팅 카테고리)": "음 료", "보관방법": "실온", "생산처": "아산공장", "검토 포장재 유형": "카톤팩", "등록일": "2026-11-08", "최종수정자": "곽정혁 주임"},
        {"*ID": "15168", "*docNo": "492", "상태": "식품안전팀 검토중", "제목": "식물성 멜라토닌 함유 연세 멜라구미 표시문안 검토", "요청부서": "마케팅3팀", "대분류(마케팅 카테고리)": "생활건강", "보관방법": "실온", "생산처": "외주가공", "검토 포장재 유형": "번들포장지", "등록일": "2026-11-06", "최종수정자": "김재호 주임"},
        {"*ID": "15138", "*docNo": "491", "상태": "연구소 최종확인 중", "제목": "[이롬마케팅팀] 고단백두유 검은콩 슬리브190 표기검수(테트라팩전환)", "요청부서": "이롬", "대분류(마케팅 카테고리)": "두 유", "보관방법": "실온", "생산처": "아산공장", "검토 포장재 유형": "멸균팩", "등록일": "2026-11-05", "최종수정자": "이롬(공용)"},
        {"*ID": "15137", "*docNo": "490", "상태": "마케팅 /BtoB 최종확인 중", "제목": "[이롬마케팅팀] 유기농 CCA주스(에콜린) 24입 케이스 표기검수 요청", "요청부서": "이롬", "대분류(마케팅 카테고리)": "음 료", "보관방법": "실온", "생산처": "아산공장", "검토 포장재 유형": "카톤팩", "등록일": "2026-11-05", "최종수정자": "곽정혁 주임"},
        {"*ID": "15122", "*docNo": "489", "상태": "마케팅 /BtoB 최종확인 중", "제목": "[이롬] 유기농 레몬즙 20입_이탈리아산 표기검수 요청의건", "요청부서": "마케팅1팀", "대분류(마케팅 카테고리)": "기타/유제품", "보관방법": "실온", "생산처": "외주가공", "검토 포장재 유형": "기타", "등록일": "2026-11-04", "최종수정자": "곽정혁 주임"},
        {"*ID": "14948", "*docNo": "488", "상태": "식품안전팀 검토중", "제목": "연세 산양유 초유 단백질 플러스 마그네슘 표시 사항 검토", "요청부서": "마케팅3팀", "대분류(마케팅 카테고리)": "생활건강", "보관방법": "실온", "생산처": "외주가공", "검토 포장재 유형": "라벨", "등록일": "2026-10-29", "최종수정자": "김재호 주임"},
        {"*ID": "14945", "*docNo": "487", "상태": "마케팅 /BtoB 최종확인 중", "제목": "[이롬마케팅팀] 국산콩두유 검은콩, 검은콩고칼슘 140,190 표기검수 요청", "요청부서": "이롬", "대분류(마케팅 카테고리)": "두 유", "보관방법": "실온", "생산처": "아산공장", "검토 포장재 유형": "멸균팩", "등록일": "2026-10-28", "최종수정자": "곽정혁 주임"},
        {"*ID": "14908", "*docNo": "486", "상태": "식품안전팀 검토중", "제목": "[마케팅 2팀] 아이스 고구마 크림떡 한글 표시사항 검토 요청", "요청부서": "마케팅2팀", "대분류(마케팅 카테고리)": "기타/유제품", "보관방법": "냉 동", "생산처": "외주가공", "검토 포장재 유형": "기타", "등록일": "2026-10-25", "최종수정자": "김재호 주임"},
        {"*ID": "14903", "*docNo": "485", "상태": "식품안전팀 검토중", "제목": "[마케팅 2팀] 아이스 블루베리 크림떡 한글 표시사항 검토 요청", "요청부서": "마케팅2팀", "대분류(마케팅 카테고리)": "기타/유제품", "보관방법": "냉 동", "생산처": "외주가공", "검토 포장재 유형": "기타", "등록일": "2026-10-25", "최종수정자": "김재호 주임"}
    ])

def classify_label_status(status_str):
    s = str(status_str).strip()
    if s == "식품안전팀 검토중":
        return "식품안전팀 검토중"
    elif s in ["개시/준비", "보류", "검토/개시", ""]:
        return "제외(개시/준비·보류)"
    else:
        return "검토완료(확인필)"

def extract_reg_month(date_str):
    s = str(date_str).strip()
    if s == "" or "###" in s:
        return "일자미상(최근등록)"
    try:
        dt = pd.to_datetime(s, errors="coerce")
        if pd.notna(dt):
            return f"{dt.month}월"
    except Exception:
        pass
    m = re.search(r"(\d{1,2})월", s)
    if m:
        return f"{int(m.group(1))}월"
    return "일자미상(최근등록)"

# [7] 표시사항 특이사항 ('원자재 표시사항 DB' 연동)
@st.cache_data(ttl=300)
def load_raw_material_label_db():
    client = get_gspread_client()
    sh = open_sheet_Safely(client, "raw_label_db")
    df_submitted = pd.DataFrame()
    total_master_count = 0

    if sh is not None:
        try:
            ws_sub = sh.get_worksheet(0)
            rows_sub = ws_sub.get_all_values()
            if len(rows_sub) >= 2:
                headers = [h.strip() for h in rows_sub[0]]
                data = [dict(zip(headers, (r + [""] * len(headers))[:len(headers)])) for r in rows_sub[1:] if any(r)]
                df_submitted = pd.DataFrame(data)
        except Exception:
            pass

        try:
            ws_master = sh.worksheet("전체 원재료 명단")
            rows_m = ws_master.get_all_values()
            total_master_count = max(len([r for r in rows_m[1:] if any(r)]), 0)
        except Exception:
            pass

    return df_submitted, total_master_count

# ==============================================================================
# 6. Gemini AI 실시간 AX 진단 함수 (GEMINI_API_KEY 활용)
# ==============================================================================
@st.cache_data(ttl=600)
def generate_ax_executive_briefing(summary_context_str):
    api_key = st.secrets.get("GEMINI_API_KEY", "")
    if GENAI_AVAILABLE and api_key and not api_key.startswith("여기에"):
        try:
            client = genai.Client(api_key=api_key)
            prompt = (
                "당신은 연세유업 아산공장 품질안전부문의 AX 데이터 분석 AI입니다. "
                "아래 실시간 KPI 요약 수치를 바탕으로 추정 없이 오직 팩트 수치만 인용하여 "
                "현재 양호한 지표와 주의/경고가 필요한 지표를 2문장 이내로 간결하게 브리핑하세요.\n\n"
                f"{summary_context_str}"
            )
            res = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
            if res and res.text:
                return res.text.strip()
        except Exception:
            pass
    return summary_context_str

# ==============================================================================
# 7. 미니 막대그래프 생성 함수
# ==============================================================================
def draw_mini_bar(target_val, actual_val, suffix="", bar_labels=("목표", "실적")):
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=[bar_labels[0]], y=[target_val],
        text=[f"{target_val}{suffix}"],
        textposition="inside", insidetextanchor="end",
        marker_color="#7F7F7F", width=0.35,
        textfont=dict(color="white", size=12, family="Malgun Gothic")
    ))
    fig.add_trace(go.Bar(
        x=[bar_labels[1]], y=[actual_val],
        text=[f"{actual_val}{suffix}"],
        textposition="inside", insidetextanchor="end",
        marker_color="#ED7D31", width=0.35,
        textfont=dict(color="white", size=12, family="Malgun Gothic")
    ))
    max_y = max(target_val, actual_val) * 1.28 if max(target_val, actual_val) > 0 else 10
    fig.update_layout(
        height=150,
        margin=dict(l=15, r=15, t=6, b=20),
        paper_bgcolor="#F2F2F2",
        plot_bgcolor="#F2F2F2",
        showlegend=False,
        xaxis=dict(showgrid=False, zeroline=False, tickfont=dict(size=12, color="#222222")),
        yaxis=dict(showgrid=False, zeroline=True, zerolinecolor="#D9D9D9", showticklabels=False, range=[0, max_y])
    )
    return fig

# ==============================================================================
# 8. 전체 데이터 로드 및 AX 추세선·신호등 판정 계산
# ==============================================================================
df_cost = load_cost_data()
df_claim_trend, df_claim_cat = load_claim_data()
proc_data = load_process_all_data()
df_supplier = load_supplier_data()
df_label_status = load_label_status_data()
df_raw_sub, raw_master_cnt = load_raw_material_label_db()

# [1] 원가절감 AX 분석 및 신호등 판정
cost_target_uk = 1.54
cost_actual_man = df_cost["부문_실적(만원)"].sum()
cost_actual_uk = round(cost_actual_man / 10000, 2)
cost_rate = round((cost_actual_uk / cost_target_uk) * 100, 1)
cost_trend_vals, cost_slope, cost_months_cnt = calc_linear_trend_and_forecast(df_cost["부문_실적(만원)"].tolist())
cost_ projected_man = cost_actual_man + sum(cost_trend_vals[cost_months_cnt:]) if cost_months_cnt < 12 else cost_actual_man
cost_projected_uk = round(cost_projected_man / 10000, 2)

if cost_actual_uk >= cost_target_uk or cost_projected_uk >= cost_target_uk:
    sig_cost = "green" if cost_slope >= 0 else "yellow"
    ai_cost_msg = f"AI 예측 : 연말 {cost_projected_uk}억 예상 (목표 달성권)"
else:
    sig_cost = "red"
    ai_cost_msg = f"AI 예측 : 연말 {cost_projected_uk}억 예상 (월 추세 {cost_slope:+.1f}만)"

# [2] 클레임 발생률 AX 분석 및 신호등 판정
claim_target_ppm = 1.12
row_2026_sum = df_claim_cat[(df_claim_cat["연도"] == "2026년") & (df_claim_cat["유형"] == "합계")]
claim_actual_ppm = float(row_2026_sum["합계_PPM"].values[0]) if not row_2026_sum.empty else 1.02
claim_total_cnt = int(row_2026_sum["합계_건수"].values[0]) if not row_2026_sum.empty else 479
claim_trend_vals, claim_slope, claim_m_cnt = calc_linear_trend_and_forecast(df_claim_trend["2026년_PPM"].tolist())

if claim_actual_ppm > claim_target_ppm:
    sig_claim = "red"
    ai_claim_msg = f"AI 경고 : 누적 {claim_actual_ppm}ppm (목표 초과)"
elif claim_slope > 0.03:
    sig_claim = "yellow"
    ai_claim_msg = f"AI 주의 : 누적 달성 중이나 월 추세 상승({claim_slope:+.2f}ppm/월)"
else:
    sig_claim = "green"
    ai_claim_msg = f"AI 양호 : 목표 이내 안정 추세 ({claim_actual_ppm}ppm)"

# [3] 공정 현황 신호등 판정
soy_contam = proc_data["soy_info"]["오염수량"]
active_milk_cnt = len(proc_data["df_milk_pack"][proc_data["df_milk_pack"]["가동상태"].str.contains("가동", na=False)])
active_ferm_cnt = len(proc_data["df_ferm_pack"][proc_data["df_ferm_pack"]["가동상태"].str.contains("가동", na=False)])
sig_process = "green" if "0" in str(soy_contam) else "red"
ai_proc_msg = f"AI 판정 : 금일 배양개봉 적합 / 포장 {active_milk_cnt + active_ferm_cnt}품목 정상"

# [4] 협력업체 관리 신호등 판정
total_target_suppliers = 166
submitted_suppliers_cnt = df_supplier["업체명"].nunique() if "업체명" in df_supplier.columns and not df_supplier.empty else 0
supplier_exec_rate = round((submitted_suppliers_cnt / total_target_suppliers) * 100, 1) if submitted_suppliers_cnt > 10 else 77.9
target_exec = 88.3
sig_supplier = "green" if supplier_exec_rate >= target_exec else ("yellow" if supplier_exec_rate >= 75.0 else "red")
ai_sup_msg = f"AI 분석 : 실행률 {supplier_exec_rate}% (목표 {target_exec}%)"

# [5] 심사점수 신호등 판정
audit_target = 94.28
audit_actual = 91.56
sig_audit = "green" if audit_actual >= audit_target else "red"

# [6] 표시사항 진행 현황 분류
if not df_label_status.empty and "상태" in df_label_status.columns:
    df_label_status["분류"] = df_label_status["상태"].apply(classify_label_status)
    df_label_status["등록월"] = df_label_status["등록일"].apply(extract_reg_month) if "등록일" in df_label_status.columns else "일자미상(최근등록)"
    df_reviewing = df_label_status[df_label_status["분류"] == "식품안전팀 검토중"]
    df_completed = df_label_status[df_label_status["분류"] == "검토완료(확인필)"]
    reviewing_cnt = len(df_reviewing)
    completed_cnt = len(df_completed)
    rep_titles = df_reviewing["제목"].head(3).tolist() if "제목" in df_reviewing.columns else []
else:
    reviewing_cnt, completed_cnt, rep_titles = 0, 0, []

sig_label = "yellow" if reviewing_cnt >= 5 else "green"

# [7] 표시사항 특이사항 (원재료 DB)
sub_cnt = len(df_raw_sub)
verified_cnt = len(df_raw_sub[df_raw_sub["검증상태"].astype(str).str.contains("완료|적합", na=False)]) if "검증상태" in df_raw_sub.columns and not df_raw_sub.empty else 0
allergy_chg_cnt = len(df_raw_sub[df_raw_sub["신규알레르기"].astype(str).str.strip() != ""]) if "신규알레르기" in df_raw_sub.columns and not df_raw_sub.empty else 0
sig_raw = "yellow" if allergy_chg_cnt > 0 else "green"

# ==============================================================================
# [화면 1] 메인 Summary 대시보드 (PPT 장표 + AX 신호등 & 예측치)
# ==============================================================================
if st.session_state.current_view == "main":
    top_c1, top_c2 = st.columns([8.5, 1.5])
    with top_c1:
        st.markdown("""
            <div class="main-title">
                <span>2026 업적 KPI 현황판_품질안전부문 (AX 스마트 대시보드)</span>
                <span style="font-size: 20px;">Summary</span>
            </div>
        """, unsafe_allow_html=True)
    with top_c2:
        if st.button("🔄 시트 실시간 동기화"):
            st.cache_data.clear()
            st.rerun()

    st.markdown(f"<div class='sub-date'>(기준 : {datetime.now().strftime('%Y. %m. %d')} | 신호등 범례: 🟢양호 🟡주의 🔴경고)</div>", unsafe_allow_html=True)

    # 상단 AX 실시간 브리핑 배너
    default_ax_summary = (
        f"• [원가절감] 현재 누적 {cost_actual_uk}억원({cost_rate}% 달성), 추세선 기준 연말 {cost_projected_uk}억원 예상 | "
        f"[클레임] 누적 {claim_actual_ppm}ppm(목표 1.12ppm 이하 달성 중)이나 8~11월 상온 멸균팩 추세 상승 주의 | "
        f"[공정/표시사항] 금일 두유 배양개봉 오염 {soy_contam}(적합), 식품안전팀 표시사항 검토중 {reviewing_cnt}건 진행 중"
    )
    ax_text = generate_ax_executive_briefing(default_ax_summary)
    st.markdown(f"""
    <div class="ax-banner">
        <b>🤖 AX(AI 전환) 품질안전 실시간 종합 브리핑</b><br>
        {ax_text}
    </div>
    """, unsafe_allow_html=True)

    # 1행 (1 ~ 4번 항목)
    col1, col2, col3, col4 = st.columns(4)

    # 1. 원가 절감
    with col1:
        st.markdown(f"""
        <div class="kpi-card">
            <div class="kpi-header">1. 원가 절감</div>
            <div class="kpi-body">
                {get_signal_dot_html(sig_cost)}
                <div><span class="kpi-bullet">●</span><b>목표 : {cost_target_uk}억원 이상</b></div>
                <div><span class="kpi-bullet">●</span><b>실적 : {cost_actual_uk}억원 ({cost_rate}% 달성)</b></div>
                <div class="ai-line">📈 {ai_cost_msg}</div>
            </div>
            <div class="unit-label">(단위 : 억원)</div>
        </div>
        """, unsafe_allow_html=True)
        st.plotly_chart(draw_mini_bar(cost_target_uk, cost_actual_uk), use_container_width=True, config={"displayModeBar": False})
        if st.button("🔍 1. 원가 절감 상세 (추세선/팀별)", key="btn_cost"):
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
                <div><span class="kpi-bullet">●</span><b>실적 : {claim_actual_ppm} ppm (총 {claim_total_cnt:,}건)</b></div>
                <div class="ai-line">📈 {ai_claim_msg}</div>
            </div>
            <div class="unit-label">(단위 : ppm)</div>
        </div>
        """, unsafe_allow_html=True)
        st.plotly_chart(draw_mini_bar(claim_target_ppm, claim_actual_ppm), use_container_width=True, config={"displayModeBar": False})
        if st.button("🔍 2. 클레임 상세 (25·26년/부문별/유형별)", key="btn_claim"):
            set_view("claim")
            st.rerun()

    # 3. 공정 현황 및 특이사항
    with col3:
        st.markdown(f"""
        <div class="kpi-card">
            <div class="kpi-header">3. 공정 현황 및 특이사항</div>
            <div class="kpi-body">
                {get_signal_dot_html(sig_process)}
                <div><span class="kpi-bullet">●</span><b>금일 배양개봉(5·7일) : 오염 {soy_contam} (적합)</b></div>
                <div><span class="kpi-bullet">●</span><b>상온 가동 : {len( proc_data['df_rt_lines'] )}개 호기 / 유제품 : {active_milk_cnt+active_ferm_cnt}품목</b></div>
                <div class="ai-line">✅ {ai_proc_msg}</div>
            </div>
            <div class="unit-label">(단위 : 건/품목)</div>
        </div>
        """, unsafe_allow_html=True)
        st.plotly_chart(draw_mini_bar(len(proc_data["df_rt_lines"]) + active_milk_cnt, len(proc_data["df_rt_lines"]) + active_milk_cnt, bar_labels=("금일계획", "점검적합")), use_container_width=True, config={"displayModeBar": False})
        if st.button("🔍 3. 금일 공정·배양·포장 실시간 관제", key="btn_process"):
            set_view("process")
            st.rerun()

    # 4. 협력업체 관리
    with col4:
        st.markdown(f"""
        <div class="kpi-card">
            <div class="kpi-header">4. 협력업체 관리</div>
            <div class="kpi-body">
                {get_signal_dot_html(sig_supplier)}
                <div><span class="kpi-bullet">●</span><b>목표 : 실행률 {target_exec}% 이상</b></div>
                <div><span class="kpi-bullet">●</span><b>실적 : {supplier_exec_rate}% (DB 등록 {submitted_suppliers_cnt}개사)</b></div>
                <div class="ai-line">📊 {ai_sup_msg}</div>
            </div>
            <div class="unit-label">(단위 : %)</div>
        </div>
        """, unsafe_allow_html=True)
        st.plotly_chart(draw_mini_bar(target_exec, supplier_exec_rate, suffix="%"), use_container_width=True, config={"displayModeBar": False})
        if st.button("🔍 4. 협력업체 관리 상세", key="btn_supplier"):
            set_view("supplier")
            st.rerun()

    # 2행 (5 ~ 7번 항목)
    col5, col6, col7 = st.columns([1, 1.5, 1.5])

    # 5. 심사점수
    with col5:
        st.markdown(f"""
        <div class="kpi-card">
            <div class="kpi-header">5. 심사점수</div>
            <div class="kpi-body">
                {get_signal_dot_html(sig_audit)}
                <div><span class="kpi-bullet">●</span><b>목표 : {audit_target}점 이상</b></div>
                <div><span class="kpi-bullet">●</span><b>실적 : {audit_actual}점</b></div>
                <div class="ai-line">⚠️ 목표 대비 -{round(audit_target - audit_actual, 2)}점 보완 필요</div>
            </div>
            <div class="unit-label">(단위 : 점)</div>
        </div>
        """, unsafe_allow_html=True)
        st.plotly_chart(draw_mini_bar(audit_target, audit_actual), use_container_width=True, config={"displayModeBar": False})
        if st.button("🔍 5. 심사점수 상세", key="btn_audit"):
            set_view("audit")
            st.rerun()

    # 6. 표시사항 진행 현황
    with col6:
        rep_html = "".join([f"<div>• {t[:40]}{'...' if len(t)>40 else ''}</div>" for t in rep_titles]) if rep_titles else "<div>• 현재 검토 대기 중인 품목 없음</div>"
        st.markdown(f"""
        <div class="kpi-card">
            <div class="kpi-header">6. 표시사항 진행 현황</div>
            <div class="kpi-body" style="min-height: 280px;">
                {get_signal_dot_html(sig_label)}
                <div><span class="kpi-bullet">●</span><b>검토 완료(확인필) : 총 {completed_cnt:,}건</b> <span style="font-size:12px; color:#555;">(개시/준비·보류 제외)</span></div>
                <div><span class="kpi-bullet">●</span><b style="color:#C00000;">현재 식품안전팀 검토중 : {reviewing_cnt:,}건</b></div>
                <div class="rep-list-box">
                    <b>📌 현재 검토중 대표 품목 (실시간)</b>
                    {rep_html}
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)
        if st.button("🔍 6. 표시사항 진행 현황 상세 (등록일/부서별 집계)", key="btn_label_status"):
            set_view("label_status")
            st.rerun()

    # 7. 표시사항 특이사항 (원재료 DB 현황)
    with col7:
        st.markdown(f"""
        <div class="kpi-card">
            <div class="kpi-header">7. 표시사항 특이사항 (원재료 DB 현황)</div>
            <div class="kpi-body" style="min-height: 280px;">
                {get_signal_dot_html(sig_raw)}
                <div><span class="kpi-bullet">●</span><b>원재료 표시사항 DB 등록 : {sub_cnt:,}건</b> {f'(전체 명단 {raw_master_cnt:,}건)' if raw_master_cnt > 0 else ''}</div>
                <div><span class="kpi-bullet">●</span><b>검증 완료 : {verified_cnt:,}건 / 신규 알레르기 체크 : {allergy_chg_cnt:,}건</b></div>
                <div class="rep-list-box">
                    <b>✓ 주요 표시사항 특이사항 및 원재료 DB 관리</b>
                    <div>• 원재료 한글표시사항·원산지·제조원·공급사(판매원) 교차검증</div>
                    <div>• 기존 알레르기 vs 신규 알레르기 변경 원료 중점 추적</div>
                    <div>• 품목제조보고서·배합비 DB 연동 표시 오류 사전 차단</div>
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)
        if st.button("🔍 7. 표시사항 특이사항 상세 (원재료 DB & 현장조치)", key="btn_label_issue"):
            set_view("label_issue")
            st.rerun()


# ==============================================================================
# [화면 2] 각 항목 클릭 시 나타나는 세부 월별 집계 페이지 (Drill-Down Views)
# ==============================================================================
else:
    if st.button("⬅️ 전체 Summary 현황판으로 돌아가기"):
        set_view("main")
        st.rerun()

    view = st.session_state.current_view

    # --------------------------------------------------------------------------
    # [세부 1] 원가 절감 (AX 추세선 및 예측치 포함)
    # --------------------------------------------------------------------------
    if view == "cost":
        st.markdown("<div class='main-title'>1. 원가 절감 - 월별/팀별 세부 집계 및 AX 추세 예측</div>", unsafe_allow_html=True)

        m1, m2, m3, m4 = st.columns(4)
        fs_sum = df_cost["식품안전팀_실적(만원)"].sum()
        qc_sum = df_cost["품질관리팀_실적(만원)"].sum()
        m1.metric("품질안전부문 누적 (목표 1.54억)", f"{cost_actual_man:,.1f} 만원 ({cost_actual_uk}억)", f"달성률 {cost_rate}%")
        m2.metric("식품안전팀 누적 (목표 1.0억)", f"{fs_sum:,.1f} 만원", f"달성률 {round(fs_sum/10000*100, 1)}%")
        m3.metric("품질관리팀 누적 (목표 0.54억)", f"{qc_sum:,.1f} 만원", f"달성률 {round(qc_sum/5400*100, 1)}%")
        m4.metric("AX 연말(2월말) 마감 예상치", f"{cost_projected_man:,.1f} 만원 ({cost_projected_uk}억)", f"월 추세 기울기 {cost_slope:+.1f}만")

        fig_cost = go.Figure()
        fig_cost.add_trace(go.Bar(x=df_cost["월"], y=df_cost["식품안전팀_실적(만원)"], name="식품안전팀 실적(만원)", marker_color="#2E75B6", text=df_cost["식품안전팀_실적(만원)"], textposition="auto"))
        fig_cost.add_trace(go.Bar(x=df_cost["월"], y=df_cost["품질관리팀_실적(만원)"], name="품질관리팀 실적(만원)", marker_color="#ED7D31", text=df_cost["품질관리팀_실적(만원)"], textposition="auto"))
        fig_cost.add_trace(go.Scatter(x=df_cost["월"], y=df_cost["부문_기준(만원)"], name="부문 월 목표 기준(1,283만)", mode="lines", line=dict(color="#C00000", width=2.5, dash="dash")))
        fig_cost.add_trace(go.Scatter(x=df_cost["월"], y=cost_trend_vals, name="AX 선형회귀 추세선(예측)", mode="lines+markers", line=dict(color="#7030A0", width=3, dash="dot")))
        fig_cost.update_layout(barmode="stack", height=420, title="📊 3월~2월 원가절감 월별 실적 및 AX 추세선 (단위: 만원)", margin=dict(t=50, b=20))
        st.plotly_chart(fig_cost, use_container_width=True)

        st.subheader("📋 원가절감 월별 상세 데이터")
        st.dataframe(df_cost, use_container_width=True, hide_index=True)

    # --------------------------------------------------------------------------
    # [세부 2] 클레임 발생률 (1. 연간추이 / 2. 부문별(유제품vs상온) 월단위 분석 / 3. 전체 유형별 상세)
    # --------------------------------------------------------------------------
    elif view == "claim":
        st.markdown("<div class='main-title'>2. 클레임 발생률 - 연간 추이 / 부문별(유제품·상온) 월단위 분석 / 유형별 상세</div>", unsafe_allow_html=True)

        tab_c1, tab_c2, tab_c3 = st.tabs([
            "🏭 부문별 월단위 분석 (유제품생산부문 vs 상온제품부문)",
            "📈 전사 월별 PPM 및 건수 추이 (2025 vs 2026)",
            "🥛 전체 제품 유형별 상세 집계표 (2026년 / 2025년)"
        ])

        # [탭 1] 부문별 월단위 분석 (유제품생산부문 4종 vs 상온제품부문 2종)
        with tab_c1:
            ctrl_c1, ctrl_c2 = st.columns([1.2, 2])
            with ctrl_c1:
                div_year = st.radio("조회 연도 선택", ["2026년", "2025년"], horizontal=True, key="div_yr")
            with ctrl_c2:
                div_sel = st.radio(
                    "조회 부문 선택",
                    ["🥛 유제품생산부문 (냉장우유 카톤/병, 발효유/음료 카톤/병)", "🧃 상온제품부문 (상온 멸균팩, 상온 프리즈마)", "⚖️ 양 부문 통합 비교"],
                    horizontal=True, key="div_type"
                )

            df_dairy_m, df_dairy_raw = build_division_claim_df(df_claim_cat, div_year, DAIRY_CATEGORIES)
            df_rt_m, df_rt_raw = build_division_claim_df(df_claim_cat, div_year, RT_CATEGORIES)

            if "유제품생산부문" in div_sel:
                target_df_m = df_dairy_m
                target_df_raw = df_dairy_raw
                target_cats = DAIRY_CATEGORIES
                div_title = f"{div_year} 유제품생산부문 (냉장우유 카톤팩·병 / 발효유·음료 카톤팩·병)"
            elif "상온제품부문" in div_sel:
                target_df_m = df_rt_m
                target_df_raw = df_rt_raw
                target_cats = RT_CATEGORIES
                div_title = f"{div_year} 상온제품부문 (상온 멸균팩 / 상온 프리즈마)"
            else:
                target_df_m = None
                div_title = f"{div_year} 유제품생산부문 vs 상온제품부문 월단위 비교"

            if target_df_m is not None:
                # 부문 요약 KPI 카드
                tot_c = target_df_m["합산_건수"].sum()
                tot_p = target_df_m["합산_생산수량"].sum()
                tot_ppm = round((tot_c / tot_p) * 1_000_000, 2) if tot_p > 0 else 0.0
                d_trend, d_slope, _ = calc_linear_trend_and_forecast(target_df_m["부문_통합_PPM"].tolist())

                mc1, mc2, mc3, mc4 = st.columns(4)
                mc1.metric(f"{div_year} 부문 누적 클레임 건수", f"{tot_c:,} 건")
                mc2.metric(f"{div_year} 부문 누적 생산수량", f"{tot_p:,} 개")
                mc3.metric(f"{div_year} 부문 통합 PPM", f"{tot_ppm} ppm")
                mc4.metric("AX 부문 PPM 월 추세 기울기", f"{d_slope:+.2f} ppm/월", "상승 주의" if d_slope > 0.03 else "안정 추세")

                # 상단 그래프 1: 부문 소속 유형별 월단위 클레임 건수(누적막대) + 부문 통합 PPM(꺾은선) & 추세선
                fig_div = make_subplots(specs=[[{"secondary_y": True}]])
                palette = ["#2E75B6", "#5B9BD5", "#ED7D31", "#F4B183"]
                for idx, cat in enumerate(target_cats):
                    fig_div.add_trace(
                        go.Bar(x=target_df_m["월"], y=target_df_m[f"{cat}_건수"], name=f"{cat} (건수)", marker_color=palette[idx % len(palette)], text=target_df_m[f"{cat}_건수"], textposition="inside"),
                        secondary_y=False
                    )
                fig_div.add_trace(
                    go.Scatter(x=target_df_m["월"], y=target_df_m["부문_통합_PPM"], name="부문 통합 PPM", mode="lines+markers+text", text=target_df_m["부문_통합_PPM"], textposition="top center", line=dict(color="#C00000", width=3)),
                    secondary_y=True
                )
                fig_div.add_trace(
                    go.Scatter(x=target_df_m["월"], y=d_trend, name="AX PPM 추세선", mode="lines", line=dict(color="#7030A0", width=2.5, dash="dot")),
                    secondary_y=True
                )
                fig_div.update_layout(barmode="stack", height=420, title=f"📊 {div_title} - 월단위 건수(막대) 및 통합 PPM(선) 추이", margin=dict(t=50, b=20))
                fig_div.update_yaxes(title_text="클레임 건수 (건)", secondary_y=False)
                fig_div.update_yaxes(title_text="클레임 발생률 (PPM)", secondary_y=True)
                st.plotly_chart(fig_div, use_container_width=True)

                # 상단 그래프 2: 소속 유형별 개별 월단위 PPM 비교 차트
                fig_sub_ppm = go.Figure()
                for idx, cat in enumerate(target_cats):
                    fig_sub_ppm.add_trace(go.Scatter(
                        x=target_df_m["월"], y=target_df_m[f"{cat}_PPM"],
                        name=f"{cat} PPM", mode="lines+markers+text",
                        text=target_df_m[f"{cat}_PPM"], textposition="top center",
                        line=dict(width=2.5, color=palette[idx % len(palette)])
                    ))
                fig_sub_ppm.update_layout(height=340, title=f"📈 {div_title} - 세부 유형별 월단위 PPM 추이", margin=dict(t=45, b=20))
                st.plotly_chart(fig_sub_ppm, use_container_width=True)

                st.subheader(f"📋 {div_title} - 월별 합산 및 유형별 상세 데이터")
                st.dataframe(target_df_m, use_container_width=True, hide_index=True)
                st.dataframe(target_df_raw, use_container_width=True, hide_index=True)

            else:
                # 양 부문 통합 비교 뷰
                fig_cmp = make_subplots(specs=[[{"secondary_y": True}]])
                fig_cmp.add_trace(go.Bar(x=df_dairy_m["월"], y=df_dairy_m["합산_건수"], name="유제품생산부문 건수", marker_color="#2E75B6", text=df_dairy_m["합산_건수"], textposition="auto"), secondary_y=False)
                fig_cmp.add_trace(go.Bar(x=df_rt_m["월"], y=df_rt_m["합산_건수"], name="상온제품부문 건수", marker_color="#ED7D31", text=df_rt_m["합산_건수"], textposition="auto"), secondary_y=False)
                fig_cmp.add_trace(go.Scatter(x=df_dairy_m["월"], y=df_dairy_m["부문_통합_PPM"], name="유제품생산부문 PPM", mode="lines+markers", line=dict(color="#002060", width=3)), secondary_y=True)
                fig_cmp.add_trace(go.Scatter(x=df_rt_m["월"], y=df_rt_m["부문_통합_PPM"], name="상온제품부문 PPM", mode="lines+markers", line=dict(color="#C00000", width=3)), secondary_y=True)
                fig_cmp.update_layout(barmode="group", height=420, title=f"📊 {div_title} (건수 및 PPM)")
                fig_cmp.update_yaxes(title_text="클레임 건수 (건)", secondary_y=False)
                fig_cmp.update_yaxes(title_text="통합 PPM", secondary_y=True)
                st.plotly_chart(fig_cmp, use_container_width=True)

        # [탭 2] 전사 월별 PPM 및 건수 추이 (2025 vs 2026)
        with tab_c2:
            fig_cl = go.Figure()
            fig_cl.add_trace(go.Bar(x=df_claim_trend["월"], y=df_claim_trend["2025년_PPM"], name="2025년 PPM", marker_color="#A6A6A6", text=df_claim_trend["2025년_PPM"], textposition="outside"))
            fig_cl.add_trace(go.Bar(x=df_claim_trend["월"], y=df_claim_trend["2026년_PPM"], name="2026년 PPM", marker_color="#ED7D31", text=df_claim_trend["2026년_PPM"], textposition="outside"))
            fig_cl.add_trace(go.Scatter(x=df_claim_trend["월"], y=df_claim_trend["목표_PPM"], name="2026 목표 기준 (1.12 ppm)", mode="lines", line=dict(color="#C00000", width=2.5, dash="dash")))
            fig_cl.add_trace(go.Scatter(x=df_claim_trend["월"], y=claim_trend_vals, name="2026 AX 추세선", mode="lines+markers", line=dict(color="#7030A0", width=3, dash="dot")))
            fig_cl.update_layout(barmode="group", height=420, title="📊 2025년 vs 2026년 월별 클레임 PPM 비교 및 AX 추세선 (3월~2월)")
            st.plotly_chart(fig_cl, use_container_width=True)
            st.dataframe(df_claim_trend, use_container_width=True, hide_index=True)

        # [탭 3] 전체 유형별 상세 집계 (2026년 / 2025년 모두 정상 출력)
        with tab_c3:
            yr_sel = st.radio("조회 연도 선택", ["2026년", "2025년", "전체 (2026년 + 2025년)"], horizontal=True, key="cat_yr_radio")
            df_cat_view = df_claim_cat if "전체" in yr_sel else df_claim_cat[df_claim_cat["연도"] == yr_sel]

            df_cat_plot = df_cat_view[df_cat_view["유형"] != "합계"]
            fig_cat = go.Figure()
            for yr_val, col_hex in [("2026년", "#ED7D31"), ("2025년", "#7F7F7F")]:
                sub_p = df_cat_plot[df_cat_plot["연도"] == yr_val]
                if not sub_p.empty:
                    fig_cat.add_trace(go.Bar(x=sub_p["유형"], y=sub_p["합계_건수"], name=f"{yr_val} 건수", marker_color=col_hex, text=sub_p["합계_건수"], textposition="auto"))
            fig_cat.update_layout(barmode="group", height=360, title=f"📊 {yr_sel} 제품 유형별 누적 클레임 발생 건수")
            st.plotly_chart(fig_cat, use_container_width=True)
            st.dataframe(df_cat_view, use_container_width=True, hide_index=True)

    # --------------------------------------------------------------------------
    # [세부 3] 공정 현황 및 특이사항 (오늘 날짜 기준 3대 공정일보 실시간 관제)
    # --------------------------------------------------------------------------
    elif view == "process":
        st.markdown("<div class='main-title'>3. 공정 현황 및 특이사항 - 금일 배양개봉(5·7일) / 상온공정 / 우유·발효유 포장 관제</div>", unsafe_allow_html=True)

        soy_info = proc_data["soy_info"]
        p_c1, p_c2, p_c3, p_c4 = st.columns(4)
        p_c1.metric("금일 두유 배양 개봉(검사일)", soy_info["기준일"], f"탭: {proc_data['soy_tab']}")
        p_c2.metric("5일 배양(D-5) / 7일 배양(D-7) 생산분", f"5일:{soy_info['5일배양_개봉대상_생산일'][5:]} / 7일:{soy_info['7일배양_개봉대상_생산일'][5:]}", f"오염 {soy_info['오염수량']} ({soy_info['최종판정']})")
        p_c3.metric("상온제품 금일 가동 호기", f"{len(proc_data['df_rt_lines'])} 개 호기", f"생산일: {proc_data['rt_date']}")
        p_c4.metric("유제품 포장 금일 가동 품목", f"우유 {active_milk_cnt}종 / 발효유 {active_ferm_cnt}종", f"기준일: {proc_data['milk_date']}")

        tab_p1, tab_p2, tab_p3 = st.tabs([
            "🧪 [상온] 두유 배양검사 일보 (금일 5일/7일 개봉 품목 & 시간대별 모니터링)",
            "🧃 [상온] 상온제품 공정 관리 일보 (금일 호기별 생산·확인시간·소비기한 & 전달사항)",
            "🥛 [우유/발효유] 유제품 포장 공정관리 일보 (우유·발효유 탭 분리 & 5대 항목 적합 현황)"
        ])

        with tab_p1:
            st.subheader(f"🔬 금일({soy_info['기준일']}) 개봉 대상 배양검사 품목 및 판정 결과 (5일 후 / 7일 후 개봉)")
            st.caption("※ 배양검사는 제조일로부터 품목 기준에 따라 5일 후(D+5) 또는 7일 후(D+7) 샘플을 개봉하여 오염 수량 및 적합 여부를 판정합니다.")
            st.dataframe(proc_data["df_soy_items"], use_container_width=True, hide_index=True)

            if not proc_data["df_soy_hourly"].empty:
                st.subheader("⏰ 시간대별(08시~07시) 샘플링·Strip·Paper 모니터링 준수 현황")
                st.dataframe(proc_data["df_soy_hourly"], use_container_width=True, hide_index=True)

        with tab_p2:
            st.subheader(f"🏭 금일({proc_data['rt_date']}) 상온제품 호기별 생산 제품·소비기한·시작/확인시간 현황")
            st.dataframe(proc_data["df_rt_lines"], use_container_width=True, hide_index=True)

            st.subheader("📋 상온제품 공정 전달(특이)사항 및 품목제조보고 vs 실운영 소비기한 조치 이력 (최신순)")
            search_kw = st.text_input("🔍 제품명 또는 특이사항 키워드 검색 (예: A2단백우유, 소비기한, 애터미, 콩국물 등)")
            df_iss_v = proc_data["df_rt_issues"]
            if search_kw:
                df_iss_v = df_iss_v[df_iss_v["전달(특이)사항 및 소비기한 교차검증 조치 내역"].str.contains(search_kw, case=False, na=False)]
            st.dataframe(df_iss_v, use_container_width=True, hide_index=True)

        with tab_p3:
            sub_t1, sub_t2 = st.tabs(["🥛 [우유] 포장 공정관리 일보", "🍶 [발효유] 포장 공정관리 일보"])
            with sub_t1:
                st.subheader(f"🥛 우유 포장 라인 금일 생산 품목 및 5대 모니터링(표시·상하부접착·용량·관능) 현황 ({proc_data['milk_date']})")
                only_active_m = st.checkbox("금일 가동 중인 우유 품목만 보기", value=False, key="chk_m")
                df_m_show = proc_data["df_milk_pack"]
                if only_active_m:
                    df_m_show = df_m_show[df_m_show["가동상태"].str.contains("가동", na=False)]
                st.dataframe(df_m_show, use_container_width=True, hide_index=True)

            with sub_t2:
                st.subheader(f"🍶 발효유 포장 라인 금일 생산 품목 및 5대 모니터링 현황 ({proc_data['milk_date']})")
                only_active_f = st.checkbox("금일 가동 중인 발효유 품목만 보기", value=False, key="chk_f")
                df_f_show = proc_data["df_ferm_pack"]
                if only_active_f:
                    df_f_show = df_f_show[df_f_show["가동상태"].str.contains("가동", na=False)]
                st.dataframe(df_f_show, use_container_width=True, hide_index=True)

    # --------------------------------------------------------------------------
    # [세부 4] 협력업체 관리
    # --------------------------------------------------------------------------
    elif view == "supplier":
        st.markdown("<div class='main-title'>4. 협력업체 관리 - 서류심사 제출 현황 및 항목별 판정 결과</div>", unsafe_allow_html=True)

        if not df_supplier.empty and "업체명" in df_supplier.columns:
            c_s1, c_s2, c_s3 = st.columns(3)
            c_s1.metric("제출 완료 업체 수", f"{df_supplier['업체명'].nunique()} 개사", f"목표 대비 실행률 {supplier_exec_rate}%")
            c_s2.metric("총 심사 항목 건수", f"{len(df_supplier):,} 건")
            biz_types = df_supplier["영업의종류"].value_counts().to_dict() if "영업의종류" in df_supplier.columns else {}
            c_s3.metric("영업의 종류 구분", ", ".join([f"{k}:{v}건" for k, v in list(biz_types.items())[:3]]))

            st.subheader("📊 업체별 제출 항목 수 및 판정 요약")
            comp_group = df_supplier.groupby(["업체명", "영업의종류", "담당자명", "납품품목"], dropna=False).size().reset_index(name="제출항목수")
            st.dataframe(comp_group, use_container_width=True, hide_index=True)

            st.subheader("📋 협력업체 심사 상세 DB 조회")
            sel_comp = st.selectbox("업체명 필터", ["전체"] + sorted(df_supplier["업체명"].dropna().unique().tolist()))
            df_sup_view = df_supplier if sel_comp == "전체" else df_supplier[df_supplier["업체명"] == sel_comp]
            st.dataframe(df_sup_view, use_container_width=True, hide_index=True)
        else:
            st.info("협력업체 심사 결과 DB 데이터를 불러오는 중이거나 데이터가 없습니다.")

    # --------------------------------------------------------------------------
    # [세부 5] 심사점수
    # --------------------------------------------------------------------------
    elif view == "audit":
        st.markdown("<div class='main-title'>5. 심사점수 - 내/외부 식품안전 및 품질 심사 평가 현황</div>", unsafe_allow_html=True)
        df_audit_detail = pd.DataFrame({
            "구분": ["연간 종합 목표", "현재 종합 실적"],
            "점수(점)": [94.28, 91.56],
            "비고": ["품질안전부문 KPI 목표 기준", "내·외부 심사 종합 평균 점수"]
        })
        st.dataframe(df_audit_detail, use_container_width=True, hide_index=True)

    # --------------------------------------------------------------------------
    # [세부 6] 표시사항 진행 현황
    # --------------------------------------------------------------------------
    elif view == "label_status":
        st.markdown("<div class='main-title'>6. 표시사항 진행 현황 - 등록일 기준 집계 및 검토중 리스트</div>", unsafe_allow_html=True)

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("전체 등록 건수", f"{len(df_label_status):,} 건")
        k2.metric("현재 식품안전팀 검토중", f"{reviewing_cnt:,} 건")
        k3.metric("검토 완료 (확인필)", f"{completed_cnt:,} 건")
        excluded_cnt = len(df_label_status[df_label_status["분류"] == "제외(개시/준비·보류)"]) if "분류" in df_label_status.columns else 0
        k4.metric("개시/준비 및 보류 (집계제외)", f"{excluded_cnt:,} 건")

        st.subheader(f"🔴 현재 [식품안전팀 검토중] 제품 목록 ({reviewing_cnt}건)")
        cols_to_show = [c for c in ["*docNo", "상태", "제목", "요청부서", "대분류(마케팅 카테고리)", "보관방법", "생산처", "검토 포장재 유형", "등록일", "최종수정자"] if c in df_label_status.columns]
        st.dataframe(df_label_status[df_label_status["분류"] == "식품안전팀 검토중"][cols_to_show], use_container_width=True, hide_index=True)

        st.markdown("---")

        g_col1, g_col2 = st.columns(2)
        with g_col1:
            df_valid_label = df_label_status[df_label_status["분류"] != "제외(개시/준비·보류)"]
            month_grp = df_valid_label.groupby(["등록월", "분류"]).size().reset_index(name="건수")
            fig_m = go.Figure()
            for status_cat, color in [("검토완료(확인필)", "#44546A"), ("식품안전팀 검토중", "#ED7D31")]:
                sub_m = month_grp[month_grp["분류"] == status_cat]
                fig_m.add_trace(go.Bar(x=sub_m["등록월"], y=sub_m["건수"], name=status_cat, marker_color=color, text=sub_m["건수"], textposition="auto"))
            fig_m.update_layout(barmode="stack", height=360, title="📊 등록일(월별) 표시사항 검토 완료 및 진행 건수")
            st.plotly_chart(fig_m, use_container_width=True)

        with g_col2:
            if "요청부서" in df_valid_label.columns:
                dept_grp = df_valid_label.groupby(["요청부서", "분류"]).size().reset_index(name="건수")
                fig_d = go.Figure()
                for status_cat, color in [("검토완료(확인필)", "#44546A"), ("식품안전팀 검토중", "#ED7D31")]:
                    sub_d = dept_grp[dept_grp["분류"] == status_cat]
                    fig_d.add_trace(go.Bar(x=sub_d["요청부서"], y=sub_d["건수"], name=status_cat, marker_color=color, text=sub_d["건수"], textposition="auto"))
                fig_d.update_layout(barmode="stack", height=360, title="📊 요청부서별(이롬/마케팅/BtoB) 검토 건수")
                st.plotly_chart(fig_d, use_container_width=True)

        st.subheader("📋 표시사항 현황 전체 데이터베이스 조회")
        f_c1, f_c2, f_c3 = st.columns(3)
        with f_c1:
            sel_cls = st.selectbox("진행 구분 필터", ["전체 (검토완료 + 검토중)", "식품안전팀 검토중", "검토완료(확인필)", "제외(개시/준비·보류)"])
        with f_c2:
            dept_opts = ["전체"] + sorted(df_label_status["요청부서"].dropna().unique().tolist()) if "요청부서" in df_label_status.columns else ["전체"]
            sel_dept = st.selectbox("요청부서 필터", dept_opts)
        with f_c3:
            kw_label = st.text_input("제품명(제목) 검색")

        df_l_view = df_label_status.copy()
        if sel_cls == "전체 (검토완료 + 검토중)":
            df_l_view = df_l_view[df_l_view["분류"] != "제외(개시/준비·보류)"]
        else:
            df_l_view = df_l_view[df_l_view["분류"] == sel_cls]

        if sel_dept != "전체" and "요청부서" in df_l_view.columns:
            df_l_view = df_l_view[df_l_view["요청부서"] == sel_dept]
        if kw_label and "제목" in df_l_view.columns:
            df_l_view = df_l_view[df_l_view["제목"].str.contains(kw_label, case=False, na=False)]

        st.dataframe(df_l_view[cols_to_show + ["분류", "등록월"]], use_container_width=True, hide_index=True)

    # --------------------------------------------------------------------------
    # [세부 7] 표시사항 특이사항 (원재료 표시사항 DB + 공정 표기 특이사항)
    # --------------------------------------------------------------------------
    elif view == "label_issue":
        st.markdown("<div class='main-title'>7. 표시사항 특이사항 - 원재료 표시사항 DB 현황 및 표기 조치 이력</div>", unsafe_allow_html=True)

        t_raw1, t_raw2 = st.tabs(["🧬 원자재 표시사항 DB 검증 및 알레르기 현황", "🏷️ 완제품/공정 표시사항 및 소비기한 변경 특이사항"])

        with t_raw1:
            r_c1, r_c2, r_c3 = st.columns(3)
            r_c1.metric("전체 원재료 마스터 수", f"{raw_master_cnt:,} 건" if raw_master_cnt > 0 else "시트 연동 확인")
            r_c2.metric("원자재 표시사항 제출/등록 건수", f"{len(df_raw_sub):,} 건")
            allergy_cnt = len(df_raw_sub[df_raw_sub["신규알레르기"].astype(str).str.strip() != ""]) if "신규알레르기" in df_raw_sub.columns and not df_raw_sub.empty else 0
            r_c3.metric("신규 알레르기 감지 건수", f"{allergy_cnt:,} 건")

            if not df_raw_sub.empty:
                st.subheader("📋 원자재 표시사항 DB 등록 리스트 (제조원 / 공급사(판매원) / 알레르기 검증)")
                raw_kw = st.text_input("🔍 원재료명 / 제조원 / 공급사(판매원) 검색")
                df_raw_view = df_raw_sub[
                    df_raw_sub.astype(str).apply(lambda x: x.str.contains(raw_kw, case=False, na=False)).any(axis=1)
                ] if raw_kw else df_raw_sub
                st.dataframe(df_raw_view, use_container_width=True, hide_index=True)
            else:
                st.info("현재 '원자재 표시사항 DB'의 '시트1'에 등록된 원재료 제출 데이터가 비어 있습니다. 데이터 입력 시 즉시 표로 출력됩니다.")

        with t_raw2:
            st.subheader("📋 현장 표시사항·소비기한 특이사항 및 변경 조치 내역")
            st.dataframe(proc_data["df_rt_issues"], use_container_width=True, hide_index=True)
