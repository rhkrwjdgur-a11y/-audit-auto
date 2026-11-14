# ==============================================================================
# [PART 1 / 3] 기본 설정 · KST 시간 · CSS 테마 · Google 인증 및 공통 유틸리티
# ==============================================================================
import html
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

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
# 1. 한국 표준시(KST, UTC+9) 고정 및 기본 페이지·상태 설정
# ==============================================================================
KST_TZ = timezone(timedelta(hours=9))


def now_kst() -> datetime:
    """Streamlit Cloud(UTC 서버) 환경에서도 항상 한국 표준시(KST) 반환"""
    return datetime.now(KST_TZ).replace(tzinfo=None)


st.set_page_config(
    page_title="2026 업적 KPI 현황판 | 연세유업 품질안전부문",
    layout="wide",
    initial_sidebar_state="collapsed"
)

BUNDLE_KEY = "kpi_bundle_kst_v2"

if "current_view" not in st.session_state:
    st.session_state.current_view = "main"


def set_view(view_name: str):
    st.session_state.current_view = view_name


# 5번 심사점수 진행현황 단계별 온도계 게이지 설정
AUDIT_STATUS_LIST = ["심사준비중", "심사중", "서류심사중", "현장심사중", "심사종료"]
AUDIT_STATUS_CONFIG = {
    "심사준비중": {"pct": 20, "color": "#64748B", "bg": "#F1F5F9", "fg": "#334155", "icon": "📋"},
    "심사중": {"pct": 50, "color": "#0284C7", "bg": "#E0F2FE", "fg": "#0369A1", "icon": "🔍"},
    "서류심사중": {"pct": 75, "color": "#2563EB", "bg": "#DBEAFE", "fg": "#1D4ED8", "icon": "📑"},
    "현장심사중": {"pct": 85, "color": "#D97706", "bg": "#FEF3C7", "fg": "#92400E", "icon": "🏭"},
    "심사종료": {"pct": 100, "color": "#10B981", "bg": "#DCFCE7", "fg": "#166534", "icon": "✅"}
}

# 수동/초기세팅 KPI 기본값 ('심사점수 및 일정 관리 DB'에 저장값이 있으면 시트값으로 자동 덮어씀)
DEFAULT_MANUAL_KPIS = {
    "kpi_5": {
        "no": "5",
        "title": "5. 심사점수",
        "target_text": "94.28점 이상",
        "actual_text": "91.56점",
        "sub_badge": "대비 : -2.72점",
        "target_num": 94.28,
        "actual_num": 91.56,
        "suffix": "",
        "signal": "red",
        "has_chart": False,
        "notes_title": "심사점수 주요 관리 내역",
        "notes": [
            "정기 위생·품질 심사 결과 집계 및 미비점 개선 조치 진행",
            "현장 CCP 모니터링 및 중점 위생관리 항목 상시 점검"
        ]
    },
    "kpi_8": {
        "no": "8",
        "title": "8. 식품안전 및 HACCP 강화",
        "target_text": "11건 이상",
        "actual_text": "11건, 100% 달성",
        "sub_badge": "목표 100% 달성 완료",
        "target_num": 11.0,
        "actual_num": 11.0,
        "suffix": "",
        "signal": "green",
        "has_chart": True,
        "notes_title": "식품안전 및 HACCP 강화 추진 실적",
        "notes": [
            "연간 식품안전 및 HACCP 유효성 검증·개선 과제 11건 이행 완료",
            "현장 작업자 정기 위생·CCP 교육 및 검증 프로세스 고도화"
        ]
    },
    "kpi_9": {
        "no": "9",
        "title": "9. 핵심불량(클레임) 발생 저감화",
        "target_text": "38건 이하",
        "actual_text": "5건",
        "sub_badge": "목표 대비 우수 관리 중",
        "target_num": 38.0,
        "actual_num": 5.0,
        "suffix": "",
        "signal": "green",
        "has_chart": True,
        "notes_title": "핵심불량(클레임) 중점 저감 내역",
        "notes": [
            "연간 허용 한도(38건 이하) 대비 현재 누적 5건으로 안정적 관리 중",
            "설비 접착·이물·파손 등 핵심 중대 불량 요인 사전 예방 점검"
        ]
    },
    "kpi_10": {
        "no": "10",
        "title": "10. 부자재 관리 고도화",
        "target_text": "부자재폐기 0건",
        "actual_text": "0건",
        "sub_badge": "폐기 0건 무결점 유지",
        "target_num": 0.0,
        "actual_num": 0.0,
        "suffix": "건",
        "signal": "green",
        "has_chart": False,
        "notes_title": "부자재 폐기 Zero화 관리 내역",
        "notes": [
            "표시사항 사전 심의 및 법규 개정 선제 반영으로 부자재 오인쇄·폐기 0건 유지",
            "포장재 발주 전 표시사항 더블체크 프로세스 상시 가동"
        ]
    },
    "kpi_11": {
        "no": "11",
        "title": "11. 협력업체 관리강화",
        "target_text": "실행률 88.3% 이상",
        "actual_text": "77.9%",
        "sub_badge": "목표 대비 -10.4%p (개선 추진)",
        "target_num": 88.3,
        "actual_num": 77.9,
        "suffix": "%",
        "signal": "yellow",
        "has_chart": True,
        "notes_title": "협력업체 현장·후속 관리강화 내역",
        "notes": [
            "연간 협력업체 현장심사 및 개선조치 실행률 점검 진행",
            "미이행 및 일정 지연 업체 대상 집중 피드백 및 하반기 보완 점검"
        ]
    },
    "kpi_12": {
        "no": "12",
        "title": "12. 식품안전 법적 RISK 최소화",
        "target_text": "행정처분 0건",
        "actual_text": "0건",
        "sub_badge": "법적 행정처분 무결점 유지",
        "target_num": 0.0,
        "actual_num": 0.0,
        "suffix": "건",
        "signal": "green",
        "has_chart": False,
        "notes_title": "중요건 행정기관 조사 3건 대응",
        "notes": [
            "카톤발효유 : 3월",
            "락토프리(명가) : 6월",
            "호상발효유 : 10월"
        ]
    }
}

if "manual_kpis" not in st.session_state:
    st.session_state["manual_kpis"] = {k: {**v, "notes": list(v["notes"])} for k, v in DEFAULT_MANUAL_KPIS.items()}

FISCAL_MONTHS = ["3월", "4월", "5월", "6월", "7월", "8월", "9월", "10월", "11월", "12월", "1월", "2월"]
CALENDAR_MONTHS = [f"{i}월" for i in range(1, 13)]

DAIRY_CATEGORIES = ["냉장우유 카톤팩", "냉장우유 병", "발효유/음료 카톤팩", "발효유/음료 병"]
RT_CATEGORIES = ["상온 멸균팩", "상온 프리즈마"]

SHEET_NAMES = {
    "cost": "원가절감 현황",
    "claim": "클레임 건수",
    "supplier": "협력업체 심사 결과 DB",
    "audit_db": "심사점수 및 일정 관리 DB",
    "label_status": "표시사항 현황",
    "raw_label_db": "원자재 표시사항 DB",
    "process_soy": "[상온]두유 배양검사 일보",
    "process_rt": "[상온]상온제품 공정 관리 일보",
    "process_milk": "[우유] 유제품 포장 공정관리 일보"
}

# ==============================================================================
# 2. 연세유업 브랜드 컬러 CSS (상단 잘림 차단 + 온도계 진행바 스타일 포함)
# ==============================================================================
st.markdown("""
<style>
    @import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css');

    html, body, [class*="css"] {
        font-family: 'Pretendard', 'Malgun Gothic', sans-serif;
    }
    .stApp {
        background-color: #F4F7FA;
    }
    header[data-testid="stHeader"],
    [data-testid="stAppHeader"] {
        background-color: #F4F7FA !important;
    }
    div[data-testid="stMainBlockContainer"],
    div[data-testid="stAppViewBlockContainer"],
    section.main > div.block-container,
    .stMainBlockContainer,
    .block-container {
        padding-top: 5.5rem !important;
        padding-bottom: 2.5rem !important;
        max-width: 97% !important;
    }
    .yonsei-header-bar {
        display: flex;
        justify-content: space-between;
        align-items: flex-end;
        border-bottom: 3px solid #00205B;
        padding-top: 8px !important;
        padding-bottom: 10px !important;
        margin-top: 0 !important;
        margin-bottom: 8px !important;
        overflow: visible !important;
    }
    .yonsei-title {
        display: inline-block;
        font-size: 27px;
        font-weight: 800;
        color: #00205B;
        letter-spacing: -0.5px;
        line-height: 1.55 !important;
        padding-top: 4px !important;
        overflow: visible !important;
    }
    .yonsei-subtitle {
        font-size: 13.5px;
        font-weight: 600;
        color: #475569;
        text-align: right;
        margin-bottom: 12px;
    }
    .ax-banner {
        background: linear-gradient(95deg, #00205B 0%, #003876 60%, #1E4E8C 100%);
        color: #FFFFFF;
        padding: 13px 20px;
        border-radius: 10px;
        margin-bottom: 18px;
        font-size: 14px;
        line-height: 1.6;
        box-shadow: 0 4px 12px rgba(0, 32, 91, 0.14);
    }
    div[data-testid="stVerticalBlockBorderWrapper"] {
        background-color: #FFFFFF;
        border: 1px solid #DCE4EE !important;
        border-radius: 12px !important;
        box-shadow: 0 3px 10px rgba(15, 23, 42, 0.05);
        padding: 12px 14px 12px 14px !important;
        margin-bottom: 8px;
    }
    button[kind="primary"],
    button[data-testid="baseButton-primary"],
    button[data-testid="stBaseButton-primary"] {
        width: 100% !important;
        background: linear-gradient(90deg, #00205B 0%, #003876 100%) !important;
        color: #FFFFFF !important;
        font-size: 15.5px !important;
        font-weight: 700 !important;
        border: none !important;
        border-radius: 8px !important;
        padding: 9px 12px !important;
        margin-bottom: 4px !important;
        box-shadow: 0 2px 5px rgba(0, 32, 91, 0.15) !important;
        transition: all 0.16s ease-in-out !important;
    }
    button[kind="primary"]:hover,
    button[data-testid="baseButton-primary"]:hover,
    button[data-testid="stBaseButton-primary"]:hover {
        background: linear-gradient(90deg, #003876 0%, #0052A5 100%) !important;
        transform: translateY(-1px);
        box-shadow: 0 4px 10px rgba(0, 56, 118, 0.25) !important;
    }
    button[kind="secondary"],
    button[data-testid="baseButton-secondary"],
    button[data-testid="stBaseButton-secondary"] {
        width: 100%;
        background-color: #FFFFFF !important;
        color: #00205B !important;
        font-weight: 700 !important;
        border: 1.5px solid #CBD5E1 !important;
        border-radius: 8px !important;
    }
    button[kind="secondary"]:hover,
    button[data-testid="baseButton-secondary"]:hover,
    button[data-testid="stBaseButton-secondary"]:hover {
        background-color: #EFF6FF !important;
        border-color: #003876 !important;
    }
    .kpi-meta-wrap {
        position: relative;
        min-height: 92px;
        padding: 6px 6px 4px 6px;
        font-size: 13.8px;
        color: #1E293B;
        line-height: 1.72;
    }
    .kpi-dot-bullet {
        color: #003876;
        font-weight: 800;
        margin-right: 6px;
    }
    .kpi-sub-pill {
        display: inline-block;
        margin-top: 5px;
        padding: 3px 9px;
        font-size: 12px;
        font-weight: 700;
        color: #003876;
        background-color: #EBF3FE;
        border: 1px solid #BFDBFE;
        border-radius: 999px;
    }
    .signal-dot {
        height: 20px;
        width: 20px;
        border-radius: 50%;
        position: absolute;
        top: 6px;
        right: 6px;
    }
    .signal-red {
        background-color: #EF4444;
        border: 2px solid #991B1B;
        box-shadow: 0 0 8px rgba(239, 68, 68, 0.45);
    }
    .signal-yellow {
        background-color: #F59E0B;
        border: 2px solid #92400E;
        box-shadow: 0 0 8px rgba(245, 158, 11, 0.45);
    }
    .signal-green {
        background-color: #10B981;
        border: 2px solid #065F46;
        box-shadow: 0 0 8px rgba(16, 185, 129, 0.45);
    }
    .signal-gray {
        background-color: #94A3B8;
        border: 2px solid #475569;
    }
    /* 3번 카드 전용: 체크리스트 + 특이사항 전광판 */
    .proc-hybrid-wrap {
        height: 226px;
        display: flex;
        flex-direction: column;
        justify-content: space-between;
        padding: 4px 4px 2px 4px;
    }
    .proc-check-list {
        display: flex;
        flex-direction: column;
        gap: 5px;
    }
    .proc-check-row {
        display: flex;
        justify-content: space-between;
        align-items: center;
        background-color: #F8FAFC;
        border: 1px solid #E2E8F0;
        border-radius: 7px;
        padding: 4px 9px;
        font-size: 12.5px;
    }
    .proc-check-label {
        font-weight: 700;
        color: #1E293B;
    }
    .proc-check-meta {
        font-size: 11.5px;
        color: #64748B;
        margin-left: 4px;
    }
    .badge-pill {
        padding: 2px 8px;
        border-radius: 999px;
        font-size: 11.5px;
        font-weight: 700;
        white-space: nowrap;
    }
    .badge-ok { background-color: #DCFCE7; color: #166534; border: 1px solid #86EFAC; }
    .badge-warn { background-color: #FEF3C7; color: #92400E; border: 1px solid #FCD34D; }
    .badge-err { background-color: #FEE2E2; color: #991B1B; border: 1px solid #FCA5A5; }
    .proc-issue-board {
        margin-top: 6px;
        background-color: #F8FAFC;
        border: 1px solid #DCE4EE;
        border-left: 4px solid #003876;
        border-radius: 7px;
        padding: 6px 10px;
        height: 98px;
        overflow-y: auto;
        font-size: 12px;
        line-height: 1.5;
        color: #1E293B;
    }
    /* 5번 심사점수 전용: 일정 배너 + 온도계 게이지 바 */
    .audit-panel-wrap {
        background-color: #F8FAFC;
        border: 1px solid #E2E8F0;
        border-radius: 8px;
        padding: 8px 10px;
        height: 146px;
        display: flex;
        flex-direction: column;
        justify-content: space-between;
        margin-top: 4px;
    }
    .audit-today-alert {
        background-color: #FEF2F2;
        border: 1px solid #FECACA;
        border-left: 4px solid #EF4444;
        border-radius: 6px;
        padding: 4px 8px;
        font-size: 12.2px;
        font-weight: 800;
        color: #991B1B;
    }
    .audit-upcoming-alert {
        background-color: #EFF6FF;
        border: 1px solid #BFDBFE;
        border-left: 4px solid #003876;
        border-radius: 6px;
        padding: 4px 8px;
        font-size: 12.2px;
        font-weight: 700;
        color: #00205B;
    }
    .thermo-row {
        display: flex;
        align-items: center;
        gap: 6px;
        margin: 4px 0 2px 0;
    }
    .thermo-bulb {
        width: 22px;
        height: 22px;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 12px;
        color: #FFFFFF;
        font-weight: 800;
        flex-shrink: 0;
        box-shadow: 0 1px 4px rgba(0,0,0,0.18);
    }
    .thermo-track {
        flex-grow: 1;
        height: 13px;
        background-color: #E2E8F0;
        border-radius: 999px;
        overflow: hidden;
        border: 1px solid #CBD5E1;
    }
    .thermo-fill {
        height: 100%;
        border-radius: 999px;
        transition: width 0.35s ease;
    }
    .audit-mini-list {
        max-height: 52px;
        overflow-y: auto;
        font-size: 11.5px;
        color: #334155;
        line-height: 1.45;
        border-top: 1px dashed #CBD5E1;
        padding-top: 4px;
    }
    /* 카드 내 스크롤 목록 박스 */
    .card-scroll-box {
        background-color: #F8FAFC;
        border: 1px solid #E2E8F0;
        border-radius: 8px;
        padding: 9px 11px;
        height: 146px;
        overflow-y: auto;
        margin-top: 4px;
        font-size: 12.3px;
        line-height: 1.55;
        color: #1E293B;
    }
    .card-scroll-item {
        padding: 3px 0;
        border-bottom: 1px dashed #E2E8F0;
    }
    .card-scroll-item:last-child {
        border-bottom: none;
    }
    .forecast-box {
        background-color: #FFFFFF;
        border: 1px solid #DCE4EE;
        border-left: 5px solid #00205B;
        padding: 14px 18px;
        border-radius: 8px;
        margin-bottom: 16px;
        font-size: 13.8px;
        line-height: 1.68;
        color: #1E293B;
        box-shadow: 0 2px 6px rgba(15, 23, 42, 0.04);
    }
    .issue-card-ok {
        background-color: #F0FDF4;
        border: 1px solid #BBF7D0;
        border-left: 5px solid #10B981;
        border-radius: 8px;
        padding: 12px 15px;
        margin-bottom: 14px;
        font-size: 13.5px;
        line-height: 1.6;
        color: #14532D;
    }
    .issue-card-warn {
        background-color: #FFFBEB;
        border: 1px solid #FDE68A;
        border-left: 5px solid #F59E0B;
        border-radius: 8px;
        padding: 12px 15px;
        margin-bottom: 14px;
        font-size: 13.5px;
        line-height: 1.6;
        color: #78350F;
    }
    .mon-table {
        width: 100%;
        border-collapse: collapse;
        table-layout: fixed;
        font-size: 13px;
        margin-bottom: 18px;
        background-color: #FFFFFF;
        border-radius: 10px;
        overflow: hidden;
        box-shadow: 0 2px 8px rgba(15, 23, 42, 0.05);
        border: 1px solid #E2E8F0;
    }
    .mon-table th {
        background-color: #00205B;
        color: #FFFFFF;
        font-weight: 700;
        padding: 10px 8px;
        border-bottom: 2px solid #003876;
        text-align: center;
        word-break: keep-all;
    }
    .mon-table td {
        padding: 9px 8px;
        border-bottom: 1px solid #E2E8F0;
        vertical-align: middle;
        word-break: keep-all;
        overflow-wrap: break-word;
        line-height: 1.48;
        color: #1E293B;
    }
    .mon-table tr:hover td {
        background-color: #F8FAFC;
    }
    .td-center { text-align: center; }
    .td-left { text-align: left; }
    .cell-green {
        background-color: #DCFCE7 !important;
        color: #166534 !important;
        font-weight: 700;
    }
    .cell-yellow {
        background-color: #FEF3C7 !important;
        color: #92400E !important;
        font-weight: 700;
    }
    .cell-red {
        background-color: #FEE2E2 !important;
        color: #991B1B !important;
        font-weight: 700;
    }
    .cell-gray {
        background-color: #F8FAFC !important;
        color: #94A3B8 !important;
    }
</style>
""", unsafe_allow_html=True)

# 상단 고정 툴바 가림 원천 차단용 물리적 여백
st.markdown("<div style='height: 32px;'></div>", unsafe_allow_html=True)


# ==============================================================================
# 3. Google 인증 · 429 할당량 초과 자동 재시도 · 공통 헬퍼
# ==============================================================================
def api_call_with_retry(func, *args, **kwargs):
    """Google Sheets 분당 호출 한도(429) 발생 시 자동 대기 후 최대 4회 재시도"""
    for attempt in range(4):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            err_msg = str(e)
            if "429" in err_msg or "Quota exceeded" in err_msg or "RESOURCE_EXHAUSTED" in err_msg:
                time.sleep(2.5 * (attempt + 1))
                continue
            raise
    return func(*args, **kwargs)


def build_google_credentials():
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
    if creds is None:
        return None, "인증 자격증명이 없습니다."

    client = gspread.authorize(creds)
    errors = []

    if key_or_title in sheet_urls_map:
        url_val = str(sheet_urls_map[key_or_title]).strip()
        if url_val:
            try:
                if url_val.startswith("http"):
                    return api_call_with_retry(client.open_by_url, url_val), None
                return api_call_with_retry(client.open_by_key, url_val), None
            except Exception as e:
                errors.append(f"URL/ID 열기 실패({key_or_title}): {e}")

    target_title = SHEET_NAMES.get(key_or_title, key_or_title)
    for candidate in [target_title, target_title.strip(), target_title.strip() + " "]:
        try:
            return api_call_with_retry(client.open, candidate), None
        except Exception as e:
            errors.append(f"파일명 '{candidate}' 열기 실패: {e}")

    return None, " / ".join(errors)


def get_values_unformatted(ws):
    try:
        return api_call_with_retry(ws.get_all_values, value_render_option="UNFORMATTED_VALUE")
    except Exception:
        return api_call_with_retry(ws.get_all_values)


def get_values_formatted(ws):
    return api_call_with_retry(ws.get_all_values)


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
        return '<div class="signal-dot signal-gray" title="대기"></div>'
    return '<div class="signal-dot signal-green" title="양호"></div>'


# ==============================================================================
# 4. 추세선·예상 추세도 계산 및 HTML 관제 테이블 렌더러
# ==============================================================================
def calc_trend_and_forecast_split(y_values: list, is_recorded_list: list = None, total_periods: int = 12):
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


def render_html_table(columns_spec: list, rows_data: list) -> str:
    if not rows_data:
        return "<div style='padding:12px; color:#64748B; background:#FFFFFF; border:1px solid #E2E8F0; border-radius:8px;'>기록된 데이터가 없습니다.</div>"

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
# ============================ [PART 1 / 3 끝] ============================
# ==============================================================================
# [PART 2 / 3] 실시간 시트 파서 · 배양(탭날짜·검사자 판별) · 심사점수/일정 DB 연동
# ==============================================================================

def safe_ws_update(ws, payload: list):
    """gspread 구버전·신버전 호환 시트 쓰기 헬퍼"""
    try:
        api_call_with_retry(ws.update, values=payload, range_name="A1", value_input_option="USER_ENTERED")
    except TypeError:
        api_call_with_retry(ws.update, "A1", payload, value_input_option="USER_ENTERED")


# [1] 원가절감 현황
def fetch_cost_sheet(creds, sheet_urls_map):
    sh, err = open_sheet_threadsafe(creds, sheet_urls_map, "cost")
    default_targets = {"부문": 1.54, "식품안전팀": 1.0, "품질관리팀": 0.54}
    if sh is None:
        return pd.DataFrame(), default_targets, err

    try:
        ws = api_call_with_retry(sh.get_worksheet, 0)
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
                b_act = round(to_float(r_pad[b_c]), 1)
                b_tar = round(to_float(r_pad[b_c + 1]), 1)
                fs_act = round(to_float(r_pad[fs_c]), 1)
                fs_tar = round(to_float(r_pad[fs_c + 1]), 1)
                qc_act = round(to_float(r_pad[qc_c]), 1)
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
        ws_all = api_call_with_retry(sh.worksheets)
        target_ws = ws_all[0] if ws_all else None
        if len(ws_all) > 1:
            for w in ws_all:
                sample = get_values_formatted(w)[:8]
                flat_txt = " ".join([" ".join(r) for r in sample])
                if "유형" in flat_txt and ("3월" in flat_txt or "생산" in flat_txt):
                    target_ws = w
                    break

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


# [3] 공정일보 공통 하단 날짜 탭 정렬 함수 (한국 시간 KST 기준)
def get_sorted_date_worksheets(sh):
    if sh is None:
        return None, None, []
    ws_list = api_call_with_retry(sh.worksheets)
    today = now_kst()
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

    # 당일 이하 탭을 우선 최신순으로 두고, 미리 생성된 미래 날짜 탭은 뒤로 배치
    past_or_today = sorted([x for x in date_tabs if x[0].date() <= today.date()], key=lambda x: x[0], reverse=True)
    future_tabs = sorted([x for x in date_tabs if x[0].date() > today.date()], key=lambda x: x[0], reverse=True)
    ordered_ws = [w for _, w in (past_or_today + future_tabs)]

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


def eval_ccp3b_cell(val_str: str, std_str: str) -> str:
    s = str(val_str).strip()
    if s in ["", "-"]:
        return ""
    nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", s)]
    if not nums:
        return "cell-green" if "적합" in s else ""

    ranges = re.findall(r"(\d+(?:\.\d+)?)\s*~\s*(\d+(?:\.\d+)?)", str(std_str))
    if not ranges:
        return "cell-green"

    all_ok = all(any(float(lo) <= n <= float(hi) for lo, hi in ranges) for n in nums)
    return "cell-green" if all_ok else "cell-red"


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


def is_same_tab_date_memo(memo_dt_str: str, tab_title: str) -> bool:
    m_tab = re.match(r"^(\d{1,2})[/\.\-](\d{1,2})$", str(tab_title).strip())
    if not m_tab or not str(memo_dt_str).strip():
        return False
    t_m, t_d = int(m_tab.group(1)), int(m_tab.group(2))

    s = str(memo_dt_str).strip()
    if re.search(r"(?:20)?25[\.\-/]", s):
        return False
    nums = [int(x) for x in re.findall(r"\d+", s)]
    if len(nums) >= 3:
        yr, mm, dd = nums[0], nums[1], nums[2]
        if yr in (26, 2026) and mm == t_m and dd == t_d:
            return True
    elif len(nums) == 2:
        if nums[0] == t_m and nums[1] == t_d:
            return True
    return False


# [3-A] 상온제품 공정 관리 일보 파서
def parse_rt_process_worksheet(ws):
    if ws is None:
        return None
    rows = get_values_formatted(ws)
    if len(rows) < 5:
        return None

    tab_title = ws.title.strip()
    prod_date_str = tab_title
    for r in rows[:4]:
        for c in r[:18]:
            if "생 산 일" in str(c) or re.search(r"202\d\.\s*\d{1,2}\.\s*\d{1,2}", str(c)):
                prod_date_str = str(c).replace("생 산 일 :", "").strip()
                break

    r_pack_hdr, r_ccp3b_hdr, r_ster_hdr = None, None, None
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

    ho_products, ho_rows_raw = {}, {}
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

    ccp3b_records = []
    r_3b_colhdr = r_ccp3b_hdr
    for sub_i in range(r_ccp3b_hdr, min(r_ccp3b_hdr + 3, r_ster_hdr)):
        if sum(1 for c in rows[sub_i][:18] if re.match(r"^[A-F]호기$", str(c).strip())) >= 3:
            r_3b_colhdr = sub_i
            break

    hdr_3b = [str(x).strip() for x in rows[r_3b_colhdr][:18]]
    ho_pos_list = sorted([(idx, cell) for idx, cell in enumerate(hdr_3b) if re.match(r"^[A-F]호기$", cell)], key=lambda x: x[0])

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
    ho_ster_summary, ho_remark_map = {}, {}

    for blk in ster_blocks:
        s_ho = blk["ster_ho"]
        b_rows = blk["rows"]
        pack_ho = next((str(br[2]).strip() for br in b_rows if str(br[2]).strip() not in ["", "-"]), "-")
        vol_str = next((str(br[3]).strip() for br in b_rows if str(br[3]).strip() not in ["", "-"]), "-")
        flt_str = next((str(br[13]).strip() or str(br[14]).strip() for br in b_rows if (str(br[13]).strip() or str(br[14]).strip()) not in ["", "-"]), "-")

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
            ster_special_notes.append(f"[{s_ho}·{pack_ho} {matched_prod_str}] {rem_val}")
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
                    "_c_rem": "cell-yellow" if rem_val else ""
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

    for r in rows[4:]:
        if len(r) >= 29:
            dt_s = str(r[27]).strip()
            if not is_same_tab_date_memo(dt_s, tab_title):
                continue
            memo_chunks = []
            for c in r[28:]:
                cs = str(c).strip()
                if cs and cs not in memo_chunks and "전달(특이)" not in cs and "생 산 일" not in cs:
                    memo_chunks.append(cs)
            memo_s = " / ".join(memo_chunks)
            if memo_s:
                ster_special_notes.append(f"[당일 전달사항] {memo_s}")

    return {
        "tab_title": tab_title,
        "prod_date": prod_date_str,
        "running_hos": {k for k, v in ho_products.items() if v},
        "lines_records": lines_records,
        "compact_rows": compact_rows,
        "ccp3b_records": ccp3b_records,
        "ster_records": ster_records,
        "ster_special_notes": ster_special_notes
    }


# [3-B] 유제품 포장 공정관리 일보 파서
def parse_dairy_pack_worksheet(ws, line_label: str):
    if ws is None:
        return pd.DataFrame(), "-"
    rows = get_values_formatted(ws)
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


# [3-C] 두유 배양검사 일보 파서 (하단 탭 날짜 단독 기준 + 검사자 기입 유무로 검사전/검사완료 판별)
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
    rows = get_values_formatted(ws)
    if not rows:
        return pd.DataFrame(), pd.DataFrame()

    anchors = []
    for r_i, r in enumerate(rows):
        for c_i, cell in enumerate(r):
            if re.sub(r"\s+", "", str(cell)) == "배양검사":
                anchors.append((r_i, c_i))

    blocks_parsed, hourly_all = [], []

    for _, (r0, c0) in enumerate(anchors):
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

        has_valid_record = bool(machine_ho) and (bool(item_names) or bool(total_smp) or bool(t_start))
        if not has_valid_record:
            continue

        # 검사자 성명 기입 유무로 '검사전' vs '검사완료' 판별
        clean_inspector = re.sub(r"[\s\-_]", "", str(inspector_nm))
        is_inspected = bool(clean_inspector) and clean_inspector not in ["미입력", "미검사", "검사전", "대기", "없음"]

        if not is_inspected:
            insp_disp = "미입력 (검사전)"
            final_judge = "검사전"
            status_badge = "🟡 검사전"
        else:
            insp_disp = inspector_nm.strip()
            final_judge = judge_res if judge_res else "적합"
            if to_float(contam_cnt, 0) > 0 or "부적합" in final_judge:
                status_badge = "🔴 부적합"
            else:
                status_badge = "🟢 검사완료"

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
            "오염수량": contam_cnt if is_inspected and contam_cnt else ("-" if not is_inspected else (contam_cnt or "0 개")),
            "작성자": writer_nm.strip() if writer_nm.strip() else "-",
            "검사자": insp_disp,
            "검사완료여부": is_inspected,
            "진행상태": status_badge,
            "판정": final_judge,
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
        for w in api_call_with_retry(sh_milk.worksheets):
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
    """셀 내부 검사일 수식 대신 무조건 하단 시트 탭에 적힌 날짜 순서 기준으로 최신 작성 탭 선택"""
    sh_soy, err_soy = open_sheet_threadsafe(creds, sheet_urls_map, "process_soy")
    if sh_soy is None:
        return "-", {}, pd.DataFrame(), pd.DataFrame(), f"[두유배양일보] {err_soy}"
    try:
        _, _, soy_date_ws_list = get_sorted_date_worksheets(sh_soy)
        soy_tabs_parsed = {}
        default_tab_title = "-"

        # 하단 탭 날짜 최신순으로 상위 5개 탭을 확인하여 데이터가 기록된 가장 최신 탭을 기준탭으로 확정
        for w in soy_date_ws_list[:5]:
            t_title = w.title.strip()
            df_b, df_h = parse_soy_incubation_worksheet(w)
            if not df_b.empty:
                soy_tabs_parsed[t_title] = (df_b, df_h)
                if default_tab_title == "-":
                    default_tab_title = t_title

        if default_tab_title == "-" and soy_date_ws_list:
            first_ws = soy_date_ws_list[0]
            default_tab_title = first_ws.title.strip()
            soy_tabs_parsed[default_tab_title] = parse_soy_incubation_worksheet(first_ws)

        df_sb, df_sh = soy_tabs_parsed.get(default_tab_title, (pd.DataFrame(), pd.DataFrame()))
        return default_tab_title, soy_tabs_parsed, df_sb, df_sh, None
    except Exception as e:
        return "-", {}, pd.DataFrame(), pd.DataFrame(), f"[두유배양일보] {e}"


# [4] 협력업체 심사 결과 DB
def fetch_supplier_sheet(creds, sheet_urls_map):
    sh, err = open_sheet_threadsafe(creds, sheet_urls_map, "supplier")
    if sh is None:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), err

    try:
        ws_list = api_call_with_retry(sh.worksheets)
        ws1 = ws_list[0] if len(ws_list) >= 1 else None
        ws2 = ws_list[1] if len(ws_list) >= 2 else None
        if ws2 is None:
            return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), "협력업체 시트2가 없습니다."

        rows1 = get_values_formatted(ws1) if ws1 else []
        df_s1 = pd.DataFrame()
        if len(rows1) >= 2:
            hdr1 = [str(h).strip() for h in rows1[0]]
            data1 = [dict(zip(hdr1, (list(r) + [""] * len(hdr1))[:len(hdr1)])) for r in rows1[1:] if any(r)]
            df_s1 = pd.DataFrame(data1)

        rows2 = get_values_formatted(ws2)
        if len(rows2) < 2:
            return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), df_s1, "협력업체 시트2(마스터 명단)가 비어 있습니다."

        exact_score_map, core_score_map = {}, {}
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
        col_res2 = next((i for i, h in enumerate(hdr2) if "결과" in h), -1)
        col_note2 = next((i for i, h in enumerate(hdr2) if "비고" in h), -1)

        temp_list = []
        for r in rows2[1:]:
            if not any(str(x).strip() for x in r):
                continue
            r_pad = list(r) + [""] * max(0, 7 - len(r))
            gubun = str(r_pad[col_gubun]).strip()
            comp = str(r_pad[col_comp]).strip()
            item = str(r_pad[col_item]).strip()
            if not comp:
                continue

            nk_exact = normalize_comp_name(comp, core_only=False)
            nk_core = normalize_comp_name(comp, core_only=True)
            matched = exact_score_map.get(nk_exact) or core_score_map.get(nk_core)

            s2_score_txt = str(r_pad[col_sc2]).strip() if col_sc2 >= 0 else ""
            s2_res_txt = str(r_pad[col_res2]).strip() if col_res2 >= 0 else ""
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

            if s2_res_txt in ["승인", "지도", "등급 외"]:
                grade = s2_res_txt
            else:
                grade = "승인" if sc_num >= 85 else ("지도" if sc_num >= 70 else "등급 외")

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
                        "대상 구분": rec["업체명"],
                        "분류": "서류심사 미흡",
                        "미비 사항": ", ".join(rec["_weak_list"])
                    })

        ws_under = next((w for w in ws_list if w.title.strip() == "등급외_미비사항"), None)
        if ws_under is not None:
            u_rows = get_values_formatted(ws_under)
            if len(u_rows) >= 2:
                sheet_uc, sheet_ud = [], []
                hdr_uc = [str(x).strip() for x in u_rows[0][:4]]
                hdr_ud = [str(x).strip() for x in u_rows[0][5:8]] if len(u_rows[0]) >= 8 else []

                for ur in u_rows[1:]:
                    ur_pad = list(ur) + [""] * max(0, 8 - len(ur))
                    if any(str(x).strip() for x in ur_pad[:4]) and len(hdr_uc) == 4:
                        sheet_uc.append(dict(zip(hdr_uc, [str(x).strip() for x in ur_pad[:4]])))
                    if any(str(x).strip() for x in ur_pad[5:8]) and len(hdr_ud) == 3:
                        sheet_ud.append(dict(zip(hdr_ud, [str(x).strip() for x in ur_pad[5:8]])))
                if sheet_uc:
                    under_comp_rows = sheet_uc
                if sheet_ud:
                    under_detail_rows = sheet_ud

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


# [5] 심사점수 및 일정 관리 DB (일정 + 진행현황 + 수동 KPI 점수 영구 저장 연동)
AUDIT_COLS = ["고유ID", "심사일자", "심사명", "진행현황", "점수", "비고", "수정일시"]
MANUAL_KPI_TAB = "수동KPI_설정"
MANUAL_KPI_COLS = [
    "kpi_key", "target_text", "actual_text", "sub_badge",
    "target_num", "actual_num", "signal", "notes_title", "notes_joined", "updated_at"
]


def fetch_audit_and_manual_db(creds, sheet_urls_map):
    empty_sched = pd.DataFrame(columns=AUDIT_COLS)
    sh, err = open_sheet_threadsafe(creds, sheet_urls_map, "audit_db")
    if sh is None:
        return empty_sched, {}, None  # 파일 미공유 시 에러 배너 대신 초기값으로 유연 동작

    try:
        ws_list = api_call_with_retry(sh.worksheets)
        ws_sched = ws_list[0] if ws_list else None
        df_sched = empty_sched.copy()

        if ws_sched is not None:
            rows = get_values_formatted(ws_sched)
            if len(rows) >= 2:
                hdr = [str(c).strip() for c in rows[0]]
                recs = []
                for r in rows[1:]:
                    if not any(str(x).strip() for x in r):
                        continue
                    r_pad = [str(x).strip() for x in r] + [""] * max(0, len(hdr) - len(r))
                    item = dict(zip(hdr, r_pad[:len(hdr)]))
                    dt_parsed = pd.to_datetime(item.get("심사일자", ""), errors="coerce")
                    dt_norm = dt_parsed.strftime("%Y-%m-%d") if pd.notna(dt_parsed) else item.get("심사일자", "")
                    st_val = item.get("진행현황", "심사준비중")
                    if st_val not in AUDIT_STATUS_LIST:
                        st_val = "심사준비중"
                    recs.append({
                        "고유ID": item.get("고유ID", "") or str(uuid.uuid4())[:8],
                        "심사일자": dt_norm,
                        "심사명": item.get("심사명", ""),
                        "진행현황": st_val,
                        "점수": item.get("점수", ""),
                        "비고": item.get("비고", ""),
                        "수정일시": item.get("수정일시", "")
                    })
                if recs:
                    df_sched = pd.DataFrame(recs).sort_values("심사일자", ascending=True).reset_index(drop=True)

        saved_manual = {}
        ws_manual = next((w for w in ws_list if w.title.strip() == MANUAL_KPI_TAB), None)
        if ws_manual is not None:
            m_rows = get_values_formatted(ws_manual)
            if len(m_rows) >= 2:
                m_hdr = [str(c).strip() for c in m_rows[0]]
                for mr in m_rows[1:]:
                    if not any(str(x).strip() for x in mr):
                        continue
                    mr_pad = [str(x).strip() for x in mr] + [""] * max(0, len(m_hdr) - len(mr))
                    md = dict(zip(m_hdr, mr_pad[:len(m_hdr)]))
                    k_key = md.get("kpi_key", "")
                    if k_key in DEFAULT_MANUAL_KPIS:
                        notes_raw = md.get("notes_joined", "")
                        saved_manual[k_key] = {
                            "target_text": md.get("target_text", DEFAULT_MANUAL_KPIS[k_key]["target_text"]),
                            "actual_text": md.get("actual_text", DEFAULT_MANUAL_KPIS[k_key]["actual_text"]),
                            "sub_badge": md.get("sub_badge", DEFAULT_MANUAL_KPIS[k_key]["sub_badge"]),
                            "target_num": to_float(md.get("target_num"), DEFAULT_MANUAL_KPIS[k_key]["target_num"]),
                            "actual_num": to_float(md.get("actual_num"), DEFAULT_MANUAL_KPIS[k_key]["actual_num"]),
                            "signal": md.get("signal", DEFAULT_MANUAL_KPIS[k_key]["signal"]),
                            "notes_title": md.get("notes_title", DEFAULT_MANUAL_KPIS[k_key]["notes_title"]),
                            "notes": [x.strip() for x in notes_raw.split("||") if x.strip()] if notes_raw else list(DEFAULT_MANUAL_KPIS[k_key]["notes"])
                        }

        return df_sched, saved_manual, None
    except Exception as e:
        return empty_sched, {}, f"[심사점수 및 일정 관리 DB] {e}"


def save_audit_schedule_df_to_sheet(df_sched: pd.DataFrame):
    creds, auth_err = build_google_credentials()
    if creds is None:
        return False, auth_err
    sheet_urls_map = dict(st.secrets["sheet_urls"]) if "sheet_urls" in st.secrets else {}
    sh, err = open_sheet_threadsafe(creds, sheet_urls_map, "audit_db")
    if sh is None:
        return False, f"'심사점수 및 일정 관리 DB' 시트를 열 수 없습니다 (공유 권한 확인 필요): {err}"

    try:
        ws_sched = api_call_with_retry(sh.get_worksheet, 0)
        df_clean = df_sched.copy()
        for c in AUDIT_COLS:
            if c not in df_clean.columns:
                df_clean[c] = ""
        df_clean = df_clean[AUDIT_COLS].fillna("").sort_values("심사일자", ascending=True).reset_index(drop=True)
        payload = [AUDIT_COLS] + df_clean.astype(str).values.tolist()
        api_call_with_retry(ws_sched.clear)
        safe_ws_update(ws_sched, payload)

        if BUNDLE_KEY in st.session_state:
            st.session_state[BUNDLE_KEY]["df_audit_sched"] = df_clean
        st.cache_data.clear()
        return True, "심사 일정 및 진행현황이 구글 시트에 저장되었습니다."
    except Exception as e:
        return False, f"시트 저장 실패: {e}"


def save_manual_kpi_to_sheet(kpi_key: str, kpi_info: dict):
    creds, auth_err = build_google_credentials()
    if creds is None:
        return False, auth_err
    sheet_urls_map = dict(st.secrets["sheet_urls"]) if "sheet_urls" in st.secrets else {}
    sh, err = open_sheet_threadsafe(creds, sheet_urls_map, "audit_db")
    if sh is None:
        return False, f"'심사점수 및 일정 관리 DB' 시트를 열 수 없습니다: {err}"

    try:
        ws_list = api_call_with_retry(sh.worksheets)
        ws_manual = next((w for w in ws_list if w.title.strip() == MANUAL_KPI_TAB), None)
        if ws_manual is None:
            ws_manual = api_call_with_retry(sh.add_worksheet, title=MANUAL_KPI_TAB, rows=30, cols=12)

        all_manual = st.session_state["manual_kpis"]
        all_manual[kpi_key] = kpi_info
        now_s = now_kst().strftime("%Y-%m-%d %H:%M:%S")

        payload = [MANUAL_KPI_COLS]
        for k, v in all_manual.items():
            payload.append([
                str(k),
                str(v.get("target_text", "")),
                str(v.get("actual_text", "")),
                str(v.get("sub_badge", "")),
                str(v.get("target_num", 0.0)),
                str(v.get("actual_num", 0.0)),
                str(v.get("signal", "green")),
                str(v.get("notes_title", "")),
                "||".join(v.get("notes", [])),
                now_s
            ])
        api_call_with_retry(ws_manual.clear)
        safe_ws_update(ws_manual, payload)

        if BUNDLE_KEY in st.session_state:
            st.session_state[BUNDLE_KEY]["saved_manual_kpis"][kpi_key] = kpi_info
        st.cache_data.clear()
        return True, "구글 시트('심사점수 및 일정 관리 DB')에 영구 저장되었습니다."
    except Exception as e:
        return False, f"시트 영구 저장 실패(현재 화면 세션에는 반영됨): {e}"


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
                return dt.strftime("%Y-%m-%d"), f"{dt.year}년", f"{dt.month}월", dt.year, dt.month
            except Exception:
                pass
        dt_parsed = pd.to_datetime(s, errors="coerce")
        if pd.notna(dt_parsed) and 2018 <= dt_parsed.year <= 2035:
            return dt_parsed.strftime("%Y-%m-%d"), f"{dt.year}년", f"{dt.month}월", int(dt_parsed.year), int(dt_parsed.month)

    return "원본날짜깨짐(#######)", "날짜미상", "날짜미상", 0, 0


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
        ws = api_call_with_retry(sh.get_worksheet, 0)
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
            dt_str, yr_str, mo_str, yr_num, mo_num = parse_factual_date(item)
            item["등록일자"] = dt_str
            item["등록연도"] = yr_str
            item["등록월"] = mo_str
            item["_yr_num"] = yr_num
            item["_mo_num"] = mo_num
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
        ws_list = api_call_with_retry(sh.worksheets)
        if ws_list:
            rows_sub = get_values_formatted(ws_list[0])
            if len(rows_sub) >= 2:
                headers = [str(h).strip() for h in rows_sub[0]]
                data = [dict(zip(headers, (list(r) + [""] * len(headers))[:len(headers)])) for r in rows_sub[1:] if any(r)]
                df_submitted = pd.DataFrame(data)
        ws_master = next((w for w in ws_list if w.title.strip() == "전체 원재료 명단"), None)
        if ws_master is not None:
            rows_m = get_values_formatted(ws_master)
            total_master_count = max(len([r for r in rows_m[1:] if any(r)]), 0)
    except Exception:
        pass
    return df_submitted, total_master_count, None


# ==============================================================================
# 6. 병렬 로딩 엔진 (5분 캐시 + max_workers=3 호출 분산으로 429 에러 원천 차단)
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


@st.cache_data(ttl=300, show_spinner=False)
def load_all_sheets_parallel(today_cache_key: str) -> dict:
    creds, auth_err = build_google_credentials()
    sheet_urls_map = dict(st.secrets["sheet_urls"]) if "sheet_urls" in st.secrets else {}
    cur_kst = now_kst()

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
            "df_audit_sched": pd.DataFrame(columns=AUDIT_COLS),
            "saved_manual_kpis": {},
            "df_label_status": pd.DataFrame(),
            "df_raw_sub": pd.DataFrame(),
            "raw_master_cnt": 0,
            "errors": [auth_err],
            "loaded_at": cur_kst.strftime("%Y. %m. %d %H:%M:%S (KST)"),
            "loaded_date": today_cache_key
        }

    with ThreadPoolExecutor(max_workers=3) as ex:
        f_cost = ex.submit(fetch_cost_sheet, creds, sheet_urls_map)
        f_claim = ex.submit(fetch_claim_sheet, creds, sheet_urls_map)
        f_rt = ex.submit(fetch_process_rt_sheet, creds, sheet_urls_map)
        f_milk = ex.submit(fetch_process_milk_sheet, creds, sheet_urls_map)
        f_soy = ex.submit(fetch_process_soy_sheet, creds, sheet_urls_map)
        f_sup = ex.submit(fetch_supplier_sheet, creds, sheet_urls_map)
        f_audit = ex.submit(fetch_audit_and_manual_db, creds, sheet_urls_map)
        f_lbl = ex.submit(fetch_label_status_sheet, creds, sheet_urls_map)
        f_raw = ex.submit(fetch_raw_material_db_sheet, creds, sheet_urls_map)

        df_cost, cost_targets, err_cost = f_cost.result()
        df_claim_trend, df_claim_cat, err_claim = f_claim.result()
        rt_today, rt_yest, err_rt = f_rt.result()
        df_milk, df_ferm, milk_dt, ferm_dt, err_milk = f_milk.result()
        soy_def_tab, soy_map, df_soy_b, df_soy_h, err_soy = f_soy.result()
        df_sup_m, df_sup_g, df_sup_uc, df_sup_ud, err_sup = f_sup.result()
        df_audit_sched, saved_manual_kpis, err_audit = f_audit.result()
        df_lbl, err_lbl = f_lbl.result()
        df_raw_sub, raw_m_cnt, err_raw = f_raw.result()

    errors = []
    for label_nm, er in [
        ("원가절감", err_cost), ("클레임", err_claim), ("협력업체", err_sup),
        ("표시사항 현황", err_lbl), ("원자재 DB", err_raw)
    ]:
        if er:
            errors.append(f"[{label_nm}] {er}")
    for p_er in [err_rt, err_milk, err_soy, err_audit]:
        if p_er:
            errors.append(p_er)

    done_kst = now_kst()
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
        "df_audit_sched": df_audit_sched,
        "saved_manual_kpis": saved_manual_kpis,
        "df_label_status": df_lbl,
        "df_raw_sub": df_raw_sub,
        "raw_master_cnt": raw_m_cnt,
        "errors": errors,
        "loaded_at": done_kst.strftime("%Y. %m. %d %H:%M:%S (KST)"),
        "loaded_date": done_kst.strftime("%Y-%m-%d")
    }


def trigger_manual_sync():
    st.cache_data.clear()
    st.session_state.pop(BUNDLE_KEY, None)
    st.session_state.pop("ax_brief_text", None)


today_kst_str = now_kst().strftime("%Y-%m-%d")
if BUNDLE_KEY not in st.session_state or st.session_state[BUNDLE_KEY].get("loaded_date") != today_kst_str:
    st.session_state.pop("ax_brief_text", None)
    loading_box = st.empty()
    loading_box.markdown(
        """
        <div style="margin-top: 24px; padding: 18px 22px; background: #FFFFFF;
                    border: 1px solid #DCE4EE; border-left: 5px solid #00205B;
                    border-radius: 10px; font-size: 15px; font-weight: 700; color: #00205B;
                    box-shadow: 0 2px 8px rgba(0, 32, 91, 0.08);">
            ⏳ 연세유업 품질안전부문 KPI 실시간 데이터를 병렬로 불러오는 중입니다...
        </div>
        """,
        unsafe_allow_html=True
    )
    loaded_bundle = load_all_sheets_parallel(today_kst_str)
    # 시트에 영구 저장된 수동 KPI 설정이 있으면 세션에 자동 반영
    for mk_k, mk_val in loaded_bundle.get("saved_manual_kpis", {}).items():
        if mk_k in st.session_state["manual_kpis"]:
            st.session_state["manual_kpis"][mk_k].update(mk_val)
    st.session_state[BUNDLE_KEY] = loaded_bundle
    loading_box.empty()

bundle = st.session_state[BUNDLE_KEY]
df_cost = bundle["df_cost"]
cost_targets = bundle["cost_targets"]
df_claim_trend = bundle["df_claim_trend"]
df_claim_cat = bundle["df_claim_cat"]
proc_data = bundle["proc_data"]
df_sup_master = bundle["df_sup_master"]
df_sup_grade = bundle["df_sup_grade"]
df_sup_under_c = bundle["df_sup_under_c"]
df_sup_under_d = bundle["df_sup_under_d"]
df_audit_sched = bundle["df_audit_sched"]
df_label_status = bundle["df_label_status"]
df_raw_sub = bundle["df_raw_sub"]
raw_master_cnt = bundle["raw_master_cnt"]
all_load_errors = bundle["errors"]
# ============================ [PART 2 / 3 끝] ============================
# ==============================================================================
# [PART 3 / 3] 지표 계산 · 메인 현황판(온도계·검사전 반영) · 세부 페이지 전체
# ==============================================================================

def draw_mini_bar(target_val: float, actual_val: float, suffix: str = "", bar_labels=("목표", "실적")):
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=[bar_labels[0]], y=[target_val], text=[f"{target_val}{suffix}"],
        textposition="inside", insidetextanchor="end", marker_color="#94A3B8", width=0.36,
        textfont=dict(color="white", size=12, family="Pretendard, Malgun Gothic")
    ))
    fig.add_trace(go.Bar(
        x=[bar_labels[1]], y=[actual_val], text=[f"{actual_val}{suffix}"],
        textposition="inside", insidetextanchor="end", marker_color="#0052A5", width=0.36,
        textfont=dict(color="white", size=12, family="Pretendard, Malgun Gothic")
    ))
    max_y = max(target_val, actual_val) * 1.28 if max(target_val, actual_val) > 0 else 10
    fig.update_layout(
        height=155,
        margin=dict(l=10, r=10, t=6, b=18),
        paper_bgcolor="#FFFFFF",
        plot_bgcolor="#FFFFFF",
        showlegend=False,
        xaxis=dict(showgrid=False, zeroline=False, tickfont=dict(size=12, color="#334155")),
        yaxis=dict(showgrid=False, zeroline=True, zerolinecolor="#E2E8F0", showticklabels=False, range=[0, max_y])
    )
    return fig


def get_active_audit_summary(df_sched: pd.DataFrame, today_str: str) -> dict:
    """오늘(KST) 기준 당일 심사 -> 진행중 심사 -> 차기 예정 심사 -> 최근 종료 심사 순으로 대표 심사 추출"""
    if df_sched is None or df_sched.empty:
        return {
            "has_data": False,
            "mode": "empty",
            "banner_cls": "audit-upcoming-alert",
            "banner_text": "📅 등록된 심사 일정이 없습니다 (클릭하여 일정 등록)",
            "status": "심사준비중",
            "pct": 0,
            "color": "#94A3B8",
            "icon": "⏳",
            "row": None
        }

    today_dt = pd.to_datetime(today_str).date()
    df_w = df_sched.copy()
    df_w["_dt"] = pd.to_datetime(df_w["심사일자"], errors="coerce").dt.date

    # 1순위: 금일 심사
    today_rows = df_w[df_w["_dt"] == today_dt]
    if not today_rows.empty:
        r = today_rows.iloc[0]
        st_nm = r["진행현황"] if r["진행현황"] in AUDIT_STATUS_CONFIG else "심사준비중"
        cfg = AUDIT_STATUS_CONFIG[st_nm]
        return {
            "has_data": True,
            "mode": "today",
            "banner_cls": "audit-today-alert",
            "banner_text": f"🚨 [금일 심사 · {r['심사일자'][5:]}] {r['심사명']}",
            "status": st_nm,
            "pct": cfg["pct"],
            "color": cfg["color"],
            "icon": cfg["icon"],
            "row": r
        }

    # 2순위: 현재 심사 진행 단계(심사중·서류심사중·현장심사중)에 있는 항목
    in_prog_rows = df_w[df_w["진행현황"].isin(["심사중", "서류심사중", "현장심사중"])]
    if not in_prog_rows.empty:
        r = in_prog_rows.iloc[0]
        st_nm = r["진행현황"]
        cfg = AUDIT_STATUS_CONFIG[st_nm]
        dt_short = str(r["심사일자"])[5:] if len(str(r["심사일자"])) >= 10 else str(r["심사일자"])
        return {
            "has_data": True,
            "mode": "in_progress",
            "banner_cls": "audit-today-alert",
            "banner_text": f"🔥 [심사 진행중 · {dt_short}] {r['심사명']}",
            "status": st_nm,
            "pct": cfg["pct"],
            "color": cfg["color"],
            "icon": cfg["icon"],
            "row": r
        }

    # 3순위: 오늘 이후 가장 가까운 예정 심사
    future_rows = df_w[df_w["_dt"].notna() & (df_w["_dt"] > today_dt)].sort_values("_dt", ascending=True)
    if not future_rows.empty:
        r = future_rows.iloc[0]
        d_left = (r["_dt"] - today_dt).days
        st_nm = r["진행현황"] if r["진행현황"] in AUDIT_STATUS_CONFIG else "심사준비중"
        cfg = AUDIT_STATUS_CONFIG[st_nm]
        return {
            "has_data": True,
            "mode": "upcoming",
            "banner_cls": "audit-upcoming-alert",
            "banner_text": f"📅 차기 심사 ({r['심사일자'][5:]} · D-{d_left}) : {r['심사명']}",
            "status": st_nm,
            "pct": cfg["pct"],
            "color": cfg["color"],
            "icon": cfg["icon"],
            "row": r
        }

    # 4순위: 가장 최근 지난 심사
    past_rows = df_w.sort_values("심사일자", ascending=False)
    r = past_rows.iloc[0]
    st_nm = r["진행현황"] if r["진행현황"] in AUDIT_STATUS_CONFIG else "심사종료"
    cfg = AUDIT_STATUS_CONFIG[st_nm]
    dt_short = str(r["심사일자"])[5:] if len(str(r["심사일자"])) >= 10 else str(r["심사일자"])
    return {
        "has_data": True,
        "mode": "past",
        "banner_cls": "audit-upcoming-alert",
        "banner_text": f"☑️ 최근 심사 ({dt_short}) : {r['심사명']}",
        "status": st_nm,
        "pct": cfg["pct"],
        "color": cfg["color"],
        "icon": cfg["icon"],
        "row": r
    }


def render_audit_kpi5_card(df_sched: pd.DataFrame, today_str: str):
    """5번 심사점수 전용 카드: 상단 점수 유지 + 하단 당일/차기 심사 배너 및 온도계 게이지 바"""
    info = st.session_state["manual_kpis"]["kpi_5"]
    aud_sum = get_active_audit_summary(df_sched, today_str)

    with st.container(border=True):
        st.button(
            f"{info['title']}  ›",
            key="hdr_kpi_5",
            type="primary",
            use_container_width=True,
            on_click=set_view,
            args=("kpi_5",)
        )
        st.markdown(f"""
        <div class="kpi-meta-wrap">
            {get_signal_dot_html(info['signal'])}
            <div><span class="kpi-dot-bullet">●</span><b>목표 : {html.escape(info['target_text'])}</b></div>
            <div><span class="kpi-dot-bullet">●</span><b>실적 : {html.escape(info['actual_text'])}</b></div>
            <div class="kpi-sub-pill">{html.escape(info['sub_badge'])}</div>
        </div>
        """, unsafe_allow_html=True)

        if df_sched is not None and not df_sched.empty:
            mini_rows = []
            for _, sr in df_sched.sort_values("심사일자", ascending=True).iterrows():
                dt_s = str(sr["심사일자"])[5:] if len(str(sr["심사일자"])) >= 10 else str(sr["심사일자"])
                sc_s = f" ({sr['점수']})" if str(sr.get("점수", "")).strip() else ""
                is_today_mark = "🔴 " if str(sr["심사일자"]) == today_str else "• "
                mini_rows.append(
                    f"<div>{is_today_mark}<b>{html.escape(dt_s)}</b> {html.escape(str(sr['심사명']))} "
                    f"<span style='color:#003876; font-weight:700;'>[{html.escape(str(sr['진행현황']))}{html.escape(sc_s)}]</span></div>"
                )
            mini_list_html = "".join(mini_rows)
        else:
            mini_list_html = "<div style='color:#64748B;'>상단 제목 클릭 후 심사 날짜와 내용을 등록하세요.</div>"

        status_label = f"{aud_sum['icon']} {aud_sum['status']} ({aud_sum['pct']}%)" if aud_sum["has_data"] else "⏳ 일정 미등록 (0%)"

        st.markdown(f"""
        <div class="audit-panel-wrap">
            <div class="{aud_sum['banner_cls']}">{html.escape(aud_sum['banner_text'])}</div>
            <div class="thermo-row">
                <div class="thermo-bulb" style="background-color:{aud_sum['color']};">🌡️</div>
                <div class="thermo-track">
                    <div class="thermo-fill" style="width:{aud_sum['pct']}%; background-color:{aud_sum['color']};"></div>
                </div>
                <span style="font-size:11.5px; font-weight:800; color:{aud_sum['color']}; white-space:nowrap;">
                    {html.escape(status_label)}
                </span>
            </div>
            <div class="audit-mini-list">{mini_list_html}</div>
        </div>
        """, unsafe_allow_html=True)


def render_manual_kpi_card(kpi_key: str):
    info = st.session_state["manual_kpis"][kpi_key]
    with st.container(border=True):
        st.button(
            f"{info['title']}  ›",
            key=f"hdr_{kpi_key}",
            type="primary",
            use_container_width=True,
            on_click=set_view,
            args=(kpi_key,)
        )
        st.markdown(f"""
        <div class="kpi-meta-wrap">
            {get_signal_dot_html(info['signal'])}
            <div><span class="kpi-dot-bullet">●</span><b>목표 : {html.escape(info['target_text'])}</b></div>
            <div><span class="kpi-dot-bullet">●</span><b>실적 : {html.escape(info['actual_text'])}</b></div>
            <div class="kpi-sub-pill">{html.escape(info['sub_badge'])}</div>
        </div>
        """, unsafe_allow_html=True)

        if info["has_chart"]:
            st.plotly_chart(
                draw_mini_bar(float(info["target_num"]), float(info["actual_num"]), suffix=info["suffix"]),
                use_container_width=True,
                config={"displayModeBar": False}
            )
        else:
            notes_items = "".join([
                f"<div class='card-scroll-item'>- {html.escape(line)}</div>"
                for line in info["notes"]
            ]) if info["notes"] else "<div class='card-scroll-item'>등록된 세부 메모 없음</div>"
            st.markdown(f"""
            <div class="card-scroll-box">
                <div style="font-weight:700; color:#00205B; margin-bottom:4px;">✓ {html.escape(info['notes_title'])}</div>
                {notes_items}
            </div>
            """, unsafe_allow_html=True)


def render_team_cost_panel(container_col, team_name: str, bar_color: str, target_uk: float):
    """세부 1번 원가절감 좌(식품안전팀)·우(품질관리팀) 개별 실적·기준선·추세 차트 렌더러"""
    act_col = f"{team_name}_실적(만원)"
    std_col = f"{team_name}_기준(만원)"

    with container_col:
        t_sum_man = round(float(df_cost[act_col].sum()), 1) if not df_cost.empty else 0.0
        t_sum_uk = round(t_sum_man / 10000, 2)
        t_target_man = round(target_uk * 10000, 1)
        t_rate = round((t_sum_man / t_target_man) * 100, 1) if t_target_man > 0 else 0.0

        rec_flags = df_cost["_기록여부"].tolist() if "_기록여부" in df_cost.columns else None
        t_act_l, t_fc_l, t_full_l, t_slope, t_mcnt, t_last_i = calc_trend_and_forecast_split(
            df_cost[act_col].tolist(), rec_flags
        )
        t_proj_man = round(t_sum_man + sum(t_full_l[t_last_i + 1:]), 1) if (0 <= t_last_i < 11) else t_sum_man
        t_proj_uk = round(t_proj_man / 10000, 2)
        t_proj_rate = round((t_proj_man / t_target_man) * 100, 1) if t_target_man > 0 else 0.0

        rec_df = df_cost[df_cost["_기록여부"]] if "_기록여부" in df_cost.columns else df_cost[df_cost[act_col] > 0]
        pass_m_cnt = int((rec_df[act_col] >= rec_df[std_col]).sum()) if not rec_df.empty else 0

        status_tag = "🟢 목표 순항" if t_proj_man >= t_target_man else "🟡 추세 보완 필요"
        st.markdown(f"""
        <div class="forecast-box" style="border-left-color:{bar_color}; margin-bottom:10px;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
                <b style="font-size:15.5px; color:#00205B;">🏢 {html.escape(team_name)} (연간 목표 {target_uk}억원)</b>
                <span class="kpi-sub-pill" style="margin-top:0;">{status_tag}</span>
            </div>
            • <b>현재 누적 실적 :</b> <b>{t_sum_man:,.1f} 만원 ({t_sum_uk}억원)</b> — 연간 목표 대비 <b>{t_rate}%</b> 달성 (월 기준 달성: {pass_m_cnt}/{max(t_mcnt, 0)}개월)<br>
            • <b>연말(2월) 추세 예측 :</b> <b>{t_proj_man:,.1f} 만원 ({t_proj_uk}억원 / 예상 {t_proj_rate}%)</b> · 월 기울기 <b>{t_slope:+.1f}만/월</b>
        </div>
        """, unsafe_allow_html=True)

        fig_t = go.Figure()
        fig_t.add_trace(go.Bar(
            x=df_cost["월"],
            y=df_cost[act_col],
            name=f"{team_name} 실적",
            marker_color=bar_color,
            text=[f"{v:,.0f}" if v > 0 else "" for v in df_cost[act_col]],
            textposition="outside"
        ))
        fig_t.add_trace(go.Scatter(
            x=df_cost["월"],
            y=df_cost[std_col],
            name="팀 월 기준선",
            mode="lines",
            line=dict(color="#DC2626", width=2.3, dash="dash")
        ))
        fig_t.add_trace(go.Scatter(
            x=df_cost["월"],
            y=t_act_l,
            name="실적 추세선",
            mode="lines+markers",
            line=dict(color="#7C3AED", width=2.6)
        ))
        if 0 <= t_last_i < 11:
            fig_t.add_trace(go.Scatter(
                x=df_cost["월"],
                y=t_fc_l,
                name="잔여월 예상 추세",
                mode="lines+markers+text",
                text=[f"{v:.0f}" if (v is not None and idx > t_last_i) else "" for idx, v in enumerate(t_fc_l)],
                textposition="top center",
                line=dict(color="#0EA5E9", width=2.6, dash="dot"),
                marker=dict(symbol="diamond", size=8)
            ))
        max_v = max(
            float(df_cost[act_col].max()) if not df_cost.empty else 0.0,
            float(df_cost[std_col].max()) if not df_cost.empty else 0.0,
            max([x for x in t_full_l if x is not None], default=0.0)
        )
        fig_t.update_layout(
            height=370,
            title=f"📊 {team_name} 월별 실적·기준선 및 잔여월 추세 예측 (단위: 만원)",
            paper_bgcolor="#FFFFFF",
            plot_bgcolor="#FFFFFF",
            margin=dict(l=20, r=20, t=48, b=30),
            yaxis=dict(range=[0, max_v * 1.25 if max_v > 0 else 1000]),
            legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="right", x=1)
        )
        st.plotly_chart(fig_t, use_container_width=True)


# ==============================================================================
# 7. 1~7번 지표 실시간 요약 집계
# ==============================================================================

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

# (3) 공정 현황 및 특이사항 요약 (두유 배양 검사자 기입 유무 반영)
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

df_milk_run = proc_data["df_milk_pack"][proc_data["df_milk_pack"]["가동여부"].str.contains("금일생산", na=False)] if not proc_data["df_milk_pack"].empty else pd.DataFrame()
df_ferm_run = proc_data["df_ferm_pack"][proc_data["df_ferm_pack"]["가동여부"].str.contains("금일생산", na=False)] if not proc_data["df_ferm_pack"].empty else pd.DataFrame()
active_dairy_cnt = len(df_milk_run) + len(df_ferm_run)

df_soy_b_main = proc_data["df_soy_blocks"]
soy_blocks_cnt = len(df_soy_b_main)
soy_total_samples = sum(int(to_float(x, 0)) for x in df_soy_b_main["총 검사수량"]) if not df_soy_b_main.empty else 0
soy_uninspected_cnt = int((~df_soy_b_main["검사완료여부"]).sum()) if (not df_soy_b_main.empty and "검사완료여부" in df_soy_b_main.columns) else 0
soy_inspected_cnt = soy_blocks_cnt - soy_uninspected_cnt
soy_contam_total = sum(
    int(to_float(r["오염수량"], 0))
    for _, r in df_soy_b_main.iterrows()
    if bool(r.get("검사완료여부", False))
) if not df_soy_b_main.empty else 0

today_real_notes = list(rt_t["ster_special_notes"]) if rt_t else []
yest_real_notes = list(rt_y["ster_special_notes"]) if rt_y else []

if rt_t is None:
    sig_process = "gray"
elif red_rt_cnt > 0 or soy_contam_total > 0:
    sig_process = "red"
elif wait_rt_cnt > 0 or soy_uninspected_cnt > 0 or len(today_real_notes) > 0:
    sig_process = "yellow"
else:
    sig_process = "green"

# (4) 협력업체 서류심사 요약
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
    all_rev_items = []
    for _, r_rev in df_rev_now.iterrows():
        dept_t = str(r_rev.get("요청부서", "")).strip()
        title_t = str(r_rev.get("제목", "")).strip()
        prefix = f"[{dept_t}] " if dept_t else ""
        all_rev_items.append(f"{prefix}{title_t}")
else:
    reviewing_cnt, completed_cnt, broken_date_cnt, all_rev_items = 0, 0, 0, []
sig_label = "yellow" if reviewing_cnt >= 5 else ("green" if not df_label_status.empty else "gray")

# (7) 원자재 표시사항 DB 요약
sub_raw_cnt = len(df_raw_sub)
verified_raw_cnt = len(df_raw_sub[df_raw_sub["검증상태"].astype(str).str.contains("완료|적합", na=False)]) if ("검증상태" in df_raw_sub.columns and not df_raw_sub.empty) else 0
allergy_raw_cnt = len(df_raw_sub[df_raw_sub["신규알레르기"].astype(str).str.strip() != ""]) if ("신규알레르기" in df_raw_sub.columns and not df_raw_sub.empty) else 0
sig_raw = "yellow" if allergy_raw_cnt > 0 else ("green" if not df_raw_sub.empty or raw_master_cnt > 0 else "gray")

soy_brief_state = (
    f"오염 {soy_contam_total}건" if soy_contam_total > 0
    else (f"검사전 {soy_uninspected_cnt}건 대기" if soy_uninspected_cnt > 0 else f"{soy_total_samples:,}개 검사완료(적합)")
)

if "ax_brief_text" not in st.session_state:
    brief_ctx = (
        f"[원가절감] 누적 {cost_actual_uk}억({cost_rate}%), 연말 추세 예상 {cost_proj_uk}억 | "
        f"[클레임] 2026년 누적 {claim_actual_ppm}ppm({claim_total_cnt}건), 2월 예상 추세 {claim_feb_pred}ppm | "
        f"[공정] 상온({rt_t_tab}) {active_rt_cnt}건 가동(특이사항 금일 {len(today_real_notes)}건·전일 {len(yest_real_notes)}건), "
        f"유제품 {active_dairy_cnt}품목 생산, 배양({proc_data['soy_default_tab']}탭) {soy_brief_state} | "
        f"[협력업체 서류심사] 승인 {ok_sup_cnt}·지도 {guide_sup_cnt}·등급외 {out_sup_cnt} ({sup_exec_rate}%) | "
        f"[표시사항] 누적 완료 {completed_cnt:,}건, 현재 검토중 {reviewing_cnt}건"
    )
    st.session_state["ax_brief_text"] = generate_ax_executive_briefing(brief_ctx)


# ==============================================================================
# [화면 1] 메인 Summary 대시보드 (12개 KPI, 상단 제목 바 클릭 시 세부 이동)
# ==============================================================================
if st.session_state.current_view == "main":
    top_c1, top_c2 = st.columns([8.4, 1.6])
    with top_c1:
        st.markdown("""
        <div class="yonsei-header-bar">
            <span class="yonsei-title">2026 업적 KPI 현황판_품질안전부문</span>
            <span style="font-size:17px; font-weight:700; color:#003876;">Summary (항목 제목 클릭 시 상세 이동)</span>
        </div>
        """, unsafe_allow_html=True)
    with top_c2:
        st.button("🔄 시트 실시간 동기화", on_click=trigger_manual_sync, key="btn_sync_top")

    st.markdown(
        f"<div class='yonsei-subtitle'>동기화 기준 : {bundle['loaded_at']} &nbsp;|&nbsp; 상태 신호등 : 🟢 양호 &nbsp;🟡 주의/검사전/특이사항 &nbsp;🔴 경고</div>",
        unsafe_allow_html=True
    )

    if all_load_errors:
        with st.expander(f"⚠️ 시트 연동 점검 필요 항목 ({len(all_load_errors)}건)", expanded=True):
            for err_line in all_load_errors:
                st.write(f"- {err_line}")

    st.markdown(
        f"<div class='ax-banner'><b>🤖 연세유업 품질안전부문 실시간 KPI 브리핑</b><br>{html.escape(st.session_state['ax_brief_text'])}</div>",
        unsafe_allow_html=True
    )

    # ------------------ [1열: KPI 1 ~ 4번] ------------------
    r1_c1, r1_c2, r1_c3, r1_c4 = st.columns(4)

    with r1_c1:
        with st.container(border=True):
            st.button("1. 원가 절감  ›", key="hdr_cost", type="primary", use_container_width=True, on_click=set_view, args=("cost",))
            st.markdown(f"""
            <div class="kpi-meta-wrap">
                {get_signal_dot_html(sig_cost)}
                <div><span class="kpi-dot-bullet">●</span><b>목표 : {cost_target_uk}억원 이상</b></div>
                <div><span class="kpi-dot-bullet">●</span><b>실적 : {cost_actual_uk}억원 ({cost_rate}% 달성)</b></div>
                <div class="kpi-sub-pill">📈 추세 예측 : 연말 {cost_proj_uk}억원</div>
            </div>
            """, unsafe_allow_html=True)
            st.plotly_chart(draw_mini_bar(cost_target_uk, cost_actual_uk), use_container_width=True, config={"displayModeBar": False})

    with r1_c2:
        with st.container(border=True):
            st.button("2. 클레임 발생률  ›", key="hdr_claim", type="primary", use_container_width=True, on_click=set_view, args=("claim",))
            st.markdown(f"""
            <div class="kpi-meta-wrap">
                {get_signal_dot_html(sig_claim)}
                <div><span class="kpi-dot-bullet">●</span><b>목표 : {claim_target_ppm} ppm 이하</b></div>
                <div><span class="kpi-dot-bullet">●</span><b>실적 : {claim_actual_ppm} ppm (총 {claim_total_cnt:,}건)</b></div>
                <div class="kpi-sub-pill">📈 기울기 {claim_slope:+.2f} / 2월 예상 {claim_feb_pred:.2f}ppm</div>
            </div>
            """, unsafe_allow_html=True)
            st.plotly_chart(draw_mini_bar(claim_target_ppm, claim_actual_ppm), use_container_width=True, config={"displayModeBar": False})

    with r1_c3:
        with st.container(border=True):
            st.button("3. 공정 현황 및 특이사항  ›", key="hdr_process", type="primary", use_container_width=True, on_click=set_view, args=("process",))

            rt_badge_cls = "badge-err" if red_rt_cnt > 0 else ("badge-warn" if wait_rt_cnt > 0 else "badge-ok")
            rt_badge_txt = "기준이탈 확인" if red_rt_cnt > 0 else (f"확인대기 {wait_rt_cnt}건" if wait_rt_cnt > 0 else "CCP 적합")

            dairy_badge_cls = "badge-ok" if active_dairy_cnt > 0 else "badge-warn"
            dairy_badge_txt = "점검 완료" if active_dairy_cnt > 0 else "생산 없음"

            if soy_contam_total > 0:
                soy_badge_cls, soy_badge_txt = "badge-err", f"오염 {soy_contam_total}건"
            elif soy_blocks_cnt == 0:
                soy_badge_cls, soy_badge_txt = "badge-warn", "기록 대기"
            elif soy_uninspected_cnt > 0:
                soy_badge_cls = "badge-warn"
                soy_badge_txt = f"검사전 ({soy_uninspected_cnt}호기 대기)" if soy_inspected_cnt == 0 else f"검사전 {soy_uninspected_cnt}·완료 {soy_inspected_cnt}"
            else:
                soy_badge_cls, soy_badge_txt = "badge-ok", "검사완료(적합)"

            board_lines = []
            for tn in today_real_notes:
                board_lines.append(f"<div class='card-scroll-item'><b style='color:#B45309;'>[금일 {html.escape(rt_t_tab)}]</b> {html.escape(tn)}</div>")
            for yn in yest_real_notes:
                board_lines.append(f"<div class='card-scroll-item'><b style='color:#003876;'>[전일 {html.escape(rt_y_tab)}]</b> {html.escape(yn)}</div>")
            if not board_lines:
                board_lines.append(f"<div class='card-scroll-item' style='color:#166534; font-weight:700;'>🟢 금일({html.escape(rt_t_tab)}) 및 전일({html.escape(rt_y_tab)}) 설비·품질 특이사항 없음</div>")

            st.markdown(f"""
            <div style="position:relative; padding: 2px 4px 0 4px;">
                {get_signal_dot_html(sig_process)}
                <div style="font-size:12.5px; font-weight:700; color:#475569; margin-bottom:5px;">
                    기준탭 : 상온({html.escape(rt_t_tab)}) · 배양({html.escape(proc_data['soy_default_tab'])})
                </div>
            </div>
            <div class="proc-hybrid-wrap">
                <div class="proc-check-list">
                    <div class="proc-check-row">
                        <span><span class="proc-check-label">상온 CCP</span><span class="proc-check-meta">({active_rt_cnt}건 가동)</span></span>
                        <span class="badge-pill {rt_badge_cls}">{rt_badge_txt}</span>
                    </div>
                    <div class="proc-check-row">
                        <span><span class="proc-check-label">유제품 포장</span><span class="proc-check-meta">(금일 {active_dairy_cnt}품목)</span></span>
                        <span class="badge-pill {dairy_badge_cls}">{dairy_badge_txt}</span>
                    </div>
                    <div class="proc-check-row">
                        <span><span class="proc-check-label">두유 배양</span><span class="proc-check-meta">({soy_blocks_cnt}호기·{soy_total_samples:,}개)</span></span>
                        <span class="badge-pill {soy_badge_cls}">{soy_badge_txt}</span>
                    </div>
                </div>
                <div class="proc-issue-board">
                    <div style="font-weight:800; color:#00205B; margin-bottom:3px;">📋 금일·전일 현장 특이사항 전광판</div>
                    {''.join(board_lines)}
                </div>
            </div>
            """, unsafe_allow_html=True)

    with r1_c4:
        with st.container(border=True):
            st.button("4. 협력업체 관리 (서류심사)  ›", key="hdr_supplier", type="primary", use_container_width=True, on_click=set_view, args=("supplier",))
            st.markdown(f"""
            <div class="kpi-meta-wrap">
                {get_signal_dot_html(sig_supplier)}
                <div><span class="kpi-dot-bullet">●</span><b>목표 : {target_exec}% 이상 (대상 {total_sup_cnt}개사)</b></div>
                <div><span class="kpi-dot-bullet">●</span><b>제출 : {sub_sup_cnt}개사 ({sup_exec_rate}% / 미제출 {unsub_sup_cnt})</b></div>
                <div class="kpi-sub-pill">승인 {ok_sup_cnt} / 지도 {guide_sup_cnt} / 등급외 {out_sup_cnt}</div>
            </div>
            """, unsafe_allow_html=True)
            st.plotly_chart(draw_mini_bar(target_exec, sup_exec_rate, suffix="%"), use_container_width=True, config={"displayModeBar": False})

    # ------------------ [2열: KPI 5 ~ 8번] ------------------
    r2_c1, r2_c2, r2_c3, r2_c4 = st.columns(4)

    with r2_c1:
        render_audit_kpi5_card(df_audit_sched, today_kst_str)

    with r2_c2:
        with st.container(border=True):
            st.button("6. 표시사항 진행 현황  ›", key="hdr_label_status", type="primary", use_container_width=True, on_click=set_view, args=("label_status",))
            rev_all_html = "".join([
                f"<div class='card-scroll-item'>• {html.escape(item)}</div>"
                for item in all_rev_items
            ]) if all_rev_items else "<div class='card-scroll-item'>현재 검토 대기 중인 품목이 없습니다.</div>"

            st.markdown(f"""
            <div class="kpi-meta-wrap">
                {get_signal_dot_html(sig_label)}
                <div><span class="kpi-dot-bullet">●</span><b>검토 완료(확인필) : 누적 {completed_cnt:,}건</b></div>
                <div><span class="kpi-dot-bullet">●</span><b style="color:#DC2626;">현재 식품안전팀 검토중 : {reviewing_cnt:,}건</b></div>
                <div class="kpi-sub-pill">시트 전체 {len(df_label_status):,}건 · 전년비 분석 제공</div>
            </div>
            <div class="card-scroll-box">
                <div style="font-weight:800; color:#00205B; margin-bottom:4px;">📌 현재 검토중 전 품목 ({reviewing_cnt}건 전체 스크롤)</div>
                {rev_all_html}
            </div>
            """, unsafe_allow_html=True)

    with r2_c3:
        with st.container(border=True):
            st.button("7. 표시사항 특이사항 (원자재 DB)  ›", key="hdr_label_issue", type="primary", use_container_width=True, on_click=set_view, args=("label_issue",))
            st.markdown(f"""
            <div class="kpi-meta-wrap">
                {get_signal_dot_html(sig_raw)}
                <div><span class="kpi-dot-bullet">●</span><b>원자재 등록 : {sub_raw_cnt:,}건</b> {f'(마스터 {raw_master_cnt:,}건)' if raw_master_cnt > 0 else ''}</div>
                <div><span class="kpi-dot-bullet">●</span><b>검증 완료 : {verified_raw_cnt:,}건 / 신규 알레르기 : {allergy_raw_cnt:,}건</b></div>
                <div class="kpi-sub-pill">원재료·제조원·공급사(판매원) 검증</div>
            </div>
            <div class="card-scroll-box">
                <div style="font-weight:800; color:#00205B; margin-bottom:4px;">✓ 원자재 표시사항 중점 관리</div>
                <div class="card-scroll-item">• 원재료 한글표시사항 및 원산지 적합 검증</div>
                <div class="card-scroll-item">• 제조원 및 공급사(판매원) 일치 여부 확인</div>
                <div class="card-scroll-item">• 기존 알레르기 대비 신규 알레르기 혼입 추적</div>
            </div>
            """, unsafe_allow_html=True)

    with r2_c4:
        render_manual_kpi_card("kpi_8")

    # ------------------ [3열: KPI 9 ~ 12번] ------------------
    r3_c1, r3_c2, r3_c3, r3_c4 = st.columns(4)

    with r3_c1:
        render_manual_kpi_card("kpi_9")
    with r3_c2:
        render_manual_kpi_card("kpi_10")
    with r3_c3:
        render_manual_kpi_card("kpi_11")
    with r3_c4:
        render_manual_kpi_card("kpi_12")


# ==============================================================================
# [화면 2] 세부 페이지 (1~12번 전체 Drill-Down 및 시트 영구 저장 편집기)
# ==============================================================================
else:
    nav_c1, nav_c2 = st.columns([8.4, 1.6])
    with nav_c1:
        st.button("⬅️ 전체 Summary 현황판으로 돌아가기", key="btn_back_main", on_click=set_view, args=("main",))
    with nav_c2:
        st.button("🔄 시트 실시간 동기화", key="btn_sync_sub", on_click=trigger_manual_sync)

    view = st.session_state.current_view

    # [세부 1] 원가 절감 (상단 부문 통합 + 중단 좌 식품안전팀 / 우 품질관리팀 + 하단 표)
    if view == "cost":
        st.markdown("<div class='yonsei-header-bar'><span class='yonsei-title'>1. 원가 절감 — 부문 통합 및 팀별(식품안전팀 · 품질관리팀) 추세 분석</span></div>", unsafe_allow_html=True)
        if df_cost.empty:
            st.error("원가절감 현황 시트 데이터를 불러오지 못했습니다.")
        else:
            fs_sum = round(float(df_cost["식품안전팀_실적(만원)"].sum()), 1)
            qc_sum = round(float(df_cost["품질관리팀_실적(만원)"].sum()), 1)
            m1, m2, m3, m4 = st.columns(4)
            m1.metric(f"품질안전부문 누적 (목표 {cost_targets['부문']}억)", f"{cost_actual_man:,.1f} 만원 ({cost_actual_uk}억)", f"달성률 {cost_rate}%")
            m2.metric(f"식품안전팀 누적 (목표 {cost_targets['식품안전팀']}억)", f"{fs_sum:,.1f} 만원", f"달성률 {round(fs_sum / (cost_targets['식품안전팀'] * 10000) * 100, 1)}%")
            m3.metric(f"품질관리팀 누적 (목표 {cost_targets['품질관리팀']}억)", f"{qc_sum:,.1f} 만원", f"달성률 {round(qc_sum / (cost_targets['품질관리팀'] * 10000) * 100, 1)}%")
            m4.metric("부문 연말(2월말) 추세 예상치", f"{cost_proj_man:,.1f} 만원 ({cost_proj_uk}억)", f"월 기울기 {cost_slope:+.1f}만/월")

            fig_cost = go.Figure()
            fig_cost.add_trace(go.Bar(
                x=df_cost["월"], y=df_cost["식품안전팀_실적(만원)"],
                name="식품안전팀 실적(만원)", marker_color="#003876",
                text=df_cost["식품안전팀_실적(만원)"], textposition="inside"
            ))
            fig_cost.add_trace(go.Bar(
                x=df_cost["월"], y=df_cost["품질관리팀_실적(만원)"],
                name="품질관리팀 실적(만원)", marker_color="#3B82F6",
                text=df_cost["품질관리팀_실적(만원)"], textposition="inside"
            ))
            fig_cost.add_trace(go.Scatter(
                x=df_cost["월"], y=df_cost["부문_기준(만원)"],
                name="부문 월 기준", mode="lines", line=dict(color="#DC2626", width=2.5, dash="dash")
            ))
            fig_cost.add_trace(go.Scatter(
                x=df_cost["월"], y=cost_act_line,
                name="실적 회귀 추세선", mode="lines+markers", line=dict(color="#7C3AED", width=3)
            ))
            if 0 <= cost_last_i < 11:
                fig_cost.add_trace(go.Scatter(
                    x=df_cost["월"], y=cost_fc_line,
                    name="AI 잔여월 예상 추세선", mode="lines+markers+text",
                    text=[f"{v:.0f}" if (v is not None and idx > cost_last_i) else "" for idx, v in enumerate(cost_fc_line)],
                    textposition="top center",
                    line=dict(color="#0EA5E9", width=3, dash="dot"),
                    marker=dict(symbol="diamond", size=9)
                ))
            fig_cost.update_layout(
                barmode="stack",
                height=410,
                title="📊 [품질안전부문 통합] 3월~2월 원가절감 실적 및 잔여월 예상 추세도 (단위: 만원)",
                paper_bgcolor="#FFFFFF",
                plot_bgcolor="#FFFFFF"
            )
            st.plotly_chart(fig_cost, use_container_width=True)

            st.markdown("---")
            st.subheader("🏢 팀별 원가절감 상세 성과 및 추세 비교 (좌: 식품안전팀 / 우: 품질관리팀)")
            team_left_col, team_right_col = st.columns(2)
            render_team_cost_panel(team_left_col, "식품안전팀", "#003876", cost_targets["식품안전팀"])
            render_team_cost_panel(team_right_col, "품질관리팀", "#3B82F6", cost_targets["품질관리팀"])

            st.markdown("---")
            st.subheader("📋 월별·팀별 원가절감 상세 수치 테이블")
            st.dataframe(df_cost.drop(columns=["_기록여부"], errors="ignore"), use_container_width=True, hide_index=True)

    # [세부 2] 클레임 발생률
    elif view == "claim":
        st.markdown("<div class='yonsei-header-bar'><span class='yonsei-title'>2. 클레임 발생률 — 전사 추이·AI 예상 추세도 및 부문별 분석</span></div>", unsafe_allow_html=True)
        if df_claim_cat.empty:
            st.error("클레임 건수 시트 데이터를 불러오지 못했습니다.")
        else:
            avail_claim_years = sorted(df_claim_cat["연도"].unique().tolist(), reverse=True)
            tab_c1, tab_c2, tab_c3 = st.tabs([
                "📈 전사 클레임 월별 추이 및 AI 예상 추세도 (2025 vs 2026)",
                "🏭 부문별 월단위 분석 및 예상 추세도 (유제품생산부문 vs 상온제품부문)",
                "🥛 전체 제품 유형별 상세 집계표"
            ])

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
                ck4.metric("회계연도 말(2월) 예상 PPM", f"{claim_feb_pred:.2f} ppm", f"기록된 {claim_m_cnt}개월 추세 기준")

                rem_months_str = ", ".join(FISCAL_MONTHS[claim_last_i + 1:]) if 0 <= claim_last_i < 11 else "없음"
                pred_vals_str = ", ".join([
                    f"{FISCAL_MONTHS[i]} {claim_full_line[i]:.2f}ppm"
                    for i in range(claim_last_i + 1, 12)
                ]) if 0 <= claim_last_i < 11 else "연간 집계 완료"

                st.markdown(f"""
                <div class="forecast-box">
                    <b>🤖 전사 클레임 실시간 추세 및 AI 예상 추세 진단</b><br>
                    • <b>실적 추세 :</b> 현재 기록된 {claim_m_cnt}개월 누적 발생률은 <b>{claim_actual_ppm} ppm</b>(총 {claim_total_cnt:,}건)이며, 월평균 증감 기울기는 <b>{claim_slope:+.2f} ppm/월</b>입니다. (최다 발생 유형: {html.escape(top_cat_txt)})<br>
                    • <b>잔여월 예상 추세 ({rem_months_str}) :</b> 현재 선형 추세 연장 시 <b>{pred_vals_str}</b> 흐름으로 2월 당월 예상치는 <b>{claim_feb_pred:.2f} ppm</b>입니다.
                </div>
                """, unsafe_allow_html=True)

                fig_cl = go.Figure()
                fig_cl.add_trace(go.Bar(
                    x=df_claim_trend["월"], y=df_claim_trend["2025년_PPM"],
                    name="2025년 실적 PPM", marker_color="#CBD5E1",
                    text=df_claim_trend["2025년_PPM"], textposition="outside"
                ))
                fig_cl.add_trace(go.Bar(
                    x=df_claim_trend["월"], y=df_claim_trend["2026년_PPM"],
                    name="2026년 실적 PPM", marker_color="#003876",
                    text=[v if flag else "" for v, flag in zip(df_claim_trend["2026년_PPM"], df_claim_trend["_기록여부"])],
                    textposition="outside"
                ))
                fig_cl.add_trace(go.Scatter(
                    x=df_claim_trend["월"], y=df_claim_trend["목표_PPM"],
                    name="2026 목표 기준 (1.12 ppm)", mode="lines",
                    line=dict(color="#DC2626", width=2.5, dash="dash")
                ))
                fig_cl.add_trace(go.Scatter(
                    x=df_claim_trend["월"], y=claim_act_line,
                    name="2026 실적 추세선", mode="lines+markers",
                    line=dict(color="#7C3AED", width=3)
                ))
                if 0 <= claim_last_i < 11:
                    fig_cl.add_trace(go.Scatter(
                        x=df_claim_trend["월"], y=claim_fc_line,
                        name="AI 예상 추세선 (잔여월 예측)", mode="lines+markers+text",
                        text=[f"예상 {v:.2f}" if (v is not None and idx > claim_last_i) else "" for idx, v in enumerate(claim_fc_line)],
                        textposition="top center",
                        line=dict(color="#0284C7", width=3, dash="dot"),
                        marker=dict(symbol="diamond", size=9, color="#0284C7")
                    ))
                fig_cl.update_layout(barmode="group", height=440, title="📊 전사 2025년 vs 2026년 월별 클레임 PPM 및 잔여월 AI 예상 추세도", paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF")
                st.plotly_chart(fig_cl, use_container_width=True)

                disp_cl_trend = df_claim_trend.drop(columns=["_기록여부"], errors="ignore").copy()
                disp_cl_trend["추세/예상_PPM"] = claim_full_line
                st.dataframe(disp_cl_trend, use_container_width=True, hide_index=True)

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
                    d_act_l, d_fc_l, d_full_l, d_slp, _, d_last_i = calc_trend_and_forecast_split(
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
                        <b>📌 {d_lbl} 추세 요약 :</b> 누적 <b>{tot_ppm} ppm</b> ({tot_c:,}건 / {tot_p:,}개) | 월 기울기 <b>{d_slp:+.2f} ppm/월</b> | 잔여월 예상: <b>{d_pred_txt}</b>
                    </div>
                    """, unsafe_allow_html=True)

                    fig_div = make_subplots(specs=[[{"secondary_y": True}]])
                    colors = ["#00205B", "#0052A5", "#3B82F6", "#93C5FD"]
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
                            textposition="top center", line=dict(color="#DC2626", width=3)
                        ),
                        secondary_y=True
                    )
                    fig_div.add_trace(go.Scatter(x=t_df_m["월"], y=d_act_l, name="실적 추세선", mode="lines", line=dict(color="#7C3AED", width=2.5)), secondary_y=True)
                    if 0 <= d_last_i < 11:
                        fig_div.add_trace(
                            go.Scatter(
                                x=t_df_m["월"], y=d_fc_l, name="AI 예상 추세선(잔여월)",
                                mode="lines+markers+text",
                                text=[f"{v:.2f}" if (v is not None and idx > d_last_i) else "" for idx, v in enumerate(d_fc_l)],
                                textposition="bottom center",
                                line=dict(color="#0284C7", width=3, dash="dot"),
                                marker=dict(symbol="diamond", size=8)
                            ),
                            secondary_y=True
                        )
                    fig_div.update_layout(barmode="stack", height=430, title=f"📊 {d_lbl} 월단위 건수 및 통합 PPM·예상 추세도", paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF")
                    fig_div.update_yaxes(title_text="클레임 건수(건)", secondary_y=False)
                    fig_div.update_yaxes(title_text="PPM", secondary_y=True)
                    st.plotly_chart(fig_div, use_container_width=True)

                    st.dataframe(t_df_m.drop(columns=["_기록여부"], errors="ignore"), use_container_width=True, hide_index=True)
                    st.dataframe(t_df_raw, use_container_width=True, hide_index=True)
                else:
                    _, dairy_fc, _, _, _, d_li = calc_trend_and_forecast_split(df_dairy_m["부문_통합_PPM"].tolist(), df_dairy_m["_기록여부"].tolist())
                    _, rt_fc, _, _, _, r_li = calc_trend_and_forecast_split(df_rt_m["부문_통합_PPM"].tolist(), df_rt_m["_기록여부"].tolist())
                    fig_cmp = make_subplots(specs=[[{"secondary_y": True}]])
                    fig_cmp.add_trace(go.Bar(x=df_dairy_m["월"], y=df_dairy_m["합산_건수"], name="유제품생산 건수", marker_color="#003876"), secondary_y=False)
                    fig_cmp.add_trace(go.Bar(x=df_rt_m["월"], y=df_rt_m["합산_건수"], name="상온제품 건수", marker_color="#F59E0B"), secondary_y=False)
                    fig_cmp.add_trace(go.Scatter(x=df_dairy_m["월"], y=df_dairy_m["부문_통합_PPM"], name="유제품생산 PPM", mode="lines+markers", line=dict(color="#00205B", width=3)), secondary_y=True)
                    fig_cmp.add_trace(go.Scatter(x=df_rt_m["월"], y=df_rt_m["부문_통합_PPM"], name="상온제품 PPM", mode="lines+markers", line=dict(color="#DC2626", width=3)), secondary_y=True)
                    if 0 <= d_li < 11:
                        fig_cmp.add_trace(go.Scatter(x=df_dairy_m["월"], y=dairy_fc, name="유제품 예상 추세", mode="lines+markers", line=dict(color="#00205B", width=2, dash="dot")), secondary_y=True)
                    if 0 <= r_li < 11:
                        fig_cmp.add_trace(go.Scatter(x=df_rt_m["월"], y=rt_fc, name="상온 예상 추세", mode="lines+markers", line=dict(color="#DC2626", width=2, dash="dot")), secondary_y=True)
                    fig_cmp.update_layout(barmode="group", height=430, title=f"📊 {d_lbl} (실적 및 잔여월 예상 추세)", paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF")
                    st.plotly_chart(fig_cmp, use_container_width=True)

            with tab_c3:
                yr_opt = st.radio("연도 필터", avail_claim_years + ["전체"], horizontal=True, key="all_cat_yr")
                df_cv = df_claim_cat if yr_opt == "전체" else df_claim_cat[df_claim_cat["연도"] == yr_opt]
                st.dataframe(df_cv, use_container_width=True, hide_index=True)

    # [세부 3] 공정 현황 및 특이사항 (두유 배양 하단 탭 날짜 기준 + 검사자 미입력 '검사전' 구분)
    elif view == "process":
        st.markdown("<div class='yonsei-header-bar'><span class='yonsei-title'>3. 공정 현황 및 특이사항 — 금일·전일 생산 및 CCP·배양 실시간 관제</span></div>", unsafe_allow_html=True)

        tab_p1, tab_p2, tab_p3 = st.tabs([
            f"🧃 [상온] 상온제품 공정 관리 일보 (금일 {rt_t_tab} & 전일 {rt_y_tab})",
            "🥛 [우유/발효유] 유제품 포장 공정관리 일보",
            f"🧪 [상온] 두유 배양검사 일보 (최신 작성 탭: {proc_data['soy_default_tab']})"
        ])

        with tab_p1:
            if rt_t is None:
                st.warning("상온제품 공정 관리 일보 시트 데이터를 불러오지 못했습니다.")
            else:
                b_left, b_right = st.columns(2)
                with b_left:
                    if today_real_notes:
                        notes_html = "<br>".join([f"• {html.escape(n)}" for n in today_real_notes])
                        st.markdown(f"<div class='issue-card-warn'><b>⚠️ 금일 [{html.escape(rt_t['tab_title'])}] 현장 특이사항 및 설비 조치 ({len(today_real_notes)}건)</b><br>{notes_html}</div>", unsafe_allow_html=True)
                    else:
                        st.markdown(f"<div class='issue-card-ok'><b>🟢 금일 [{html.escape(rt_t['tab_title'])}] 현장 특이사항 없음</b><br>• 전 가동 호기 및 멸균기 특이사항 없이 정상 생산 중입니다.</div>", unsafe_allow_html=True)

                with b_right:
                    if rt_y is not None:
                        if yest_real_notes:
                            yn_html = "<br>".join([f"• {html.escape(n)}" for n in yest_real_notes])
                            st.markdown(f"<div class='issue-card-warn'><b>📌 전일 [{html.escape(rt_y['tab_title'])}] 마감 특이사항 기록 ({len(yest_real_notes)}건)</b><br>{yn_html}</div>", unsafe_allow_html=True)
                        else:
                            st.markdown(f"<div class='issue-card-ok'><b>🟢 전일 [{html.escape(rt_y['tab_title'])}] 전 호기 특이사항 없이 정상 생산 마감</b><br>• 전일 설비 이상 및 품질 특이사항 기록 없음</div>", unsafe_allow_html=True)

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

                st.subheader(f"🔥 금일 [{rt_t['tab_title']}] 멸균기 실시간 모니터링 [CCP-1B / CCP-2P] (우측 S~V열 기준 자동 대조)")
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
                        row_obj[ho_nm] = {"text": v_txt, "cls": eval_ccp3b_cell(v_txt, r3["관리기준"])}
                    ccp3b_rows_html.append(row_obj)
                st.markdown(render_html_table(ccp3b_cols, ccp3b_rows_html), unsafe_allow_html=True)

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

        with tab_p3:
            soy_map = proc_data["soy_tabs_map"]
            if not soy_map:
                st.warning("두유 배양검사 일보 날짜 탭 데이터를 불러오지 못했습니다.")
            else:
                tab_keys = list(soy_map.keys())
                def_idx = tab_keys.index(proc_data["soy_default_tab"]) if proc_data["soy_default_tab"] in tab_keys else 0
                sel_soy_tab = st.selectbox("조회할 배양검사 하단 시트 탭 날짜 선택 (하단 탭 날짜 최신순)", tab_keys, index=def_idx)
                df_sb, df_sh = soy_map[sel_soy_tab]

                tot_samples = sum(int(to_float(x, 0)) for x in df_sb["총 검사수량"]) if not df_sb.empty else 0
                uninsp_cnt = int((~df_sb["검사완료여부"]).sum()) if (not df_sb.empty and "검사완료여부" in df_sb.columns) else 0
                insp_cnt = len(df_sb) - uninsp_cnt

                if uninsp_cnt > 0:
                    st.markdown(
                        f"<div class='issue-card-warn'><b>🟡 [{html.escape(sel_soy_tab)} 탭] 배양검사 진행 현황 : 총 {len(df_sb)}호기 중 "
                        f"검사완료 {insp_cnt}건 / 검사전 {uninsp_cnt}건 대기</b><br>"
                        f"• 검사자 성명이 아직 기입되지 않은 호기는 <b>검사전(배양중·개봉대기)</b> 상태로 자동 분류됩니다.</div>",
                        unsafe_allow_html=True
                    )
                else:
                    st.markdown(
                        f"<div class='issue-card-ok'><b>🟢 [{html.escape(sel_soy_tab)} 탭] 전 호기({len(df_sb)}건) 검사자 확인 및 배양검사 완료 (총 {tot_samples:,}개)</b></div>",
                        unsafe_allow_html=True
                    )

                st.subheader(f"🔬 [{sel_soy_tab} 탭] 호기별 작성자·검사자 확인 및 배양 판독 내역")

                soy_cols = [
                    {"key": "ho", "label": "포장기", "width": "6%", "align": "center"},
                    {"key": "inc", "label": "배양구분", "width": "9%", "align": "center"},
                    {"key": "vol", "label": "용량", "width": "5%", "align": "center"},
                    {"key": "item", "label": "품목명", "width": "21%", "align": "left"},
                    {"key": "pdt", "label": "생산일", "width": "8%", "align": "center"},
                    {"key": "exp", "label": "소비기한", "width": "8%", "align": "center"},
                    {"key": "time", "label": "가동시간", "width": "10%", "align": "center"},
                    {"key": "qty", "label": "검사수량", "width": "6%", "align": "center"},
                    {"key": "wrt", "label": "작성자", "width": "6%", "align": "center"},
                    {"key": "ins", "label": "검사자", "width": "8%", "align": "center"},
                    {"key": "st", "label": "진행상태", "width": "7%", "align": "center"},
                    {"key": "jdg", "label": "오염/판정", "width": "6%", "align": "center"}
                ]
                soy_rows_html = []
                for _, sr in df_sb.iterrows():
                    done_flag = bool(sr.get("검사완료여부", False))
                    is_zero_contam = to_float(sr["오염수량"], 0) == 0
                    jdg_txt = str(sr["판정"]).strip()

                    if not done_flag:
                        st_cls = "cell-yellow"
                        jdg_disp = "검사전"
                        jdg_cls = "cell-yellow"
                    elif not is_zero_contam or "부적합" in jdg_txt:
                        st_cls = "cell-red"
                        jdg_disp = f"{sr['오염수량']} / {jdg_txt}"
                        jdg_cls = "cell-red"
                    else:
                        st_cls = "cell-green"
                        jdg_disp = f"{sr['오염수량']} / {jdg_txt}"
                        jdg_cls = "cell-green"

                    soy_rows_html.append({
                        "ho": {"text": sr["포장기"], "cls": ""},
                        "inc": {"text": sr["배양구분"], "cls": ""},
                        "vol": {"text": sr["용량(mL)"], "cls": ""},
                        "item": {"text": sr["품목명"], "cls": ""},
                        "pdt": {"text": sr["생산일"], "cls": ""},
                        "exp": {"text": sr["소비기한"], "cls": ""},
                        "time": {"text": f"{sr['생산 시작~종료']}\n({sr['실가동시간']})", "cls": ""},
                        "qty": {"text": sr["총 검사수량"], "cls": "cell-green" if done_flag else ""},
                        "wrt": {"text": sr["작성자"], "cls": ""},
                        "ins": {"text": sr["검사자"], "cls": st_cls},
                        "st": {"text": sr["진행상태"], "cls": st_cls},
                        "jdg": {"text": jdg_disp, "cls": jdg_cls}
                    })
                st.markdown(render_html_table(soy_cols, soy_rows_html), unsafe_allow_html=True)

                if not df_sh.empty:
                    with st.expander("⏰ 시간대별(08시~07시) 샘플·Strip·Paper 체크 상세 보기"):
                        st.dataframe(df_sh, use_container_width=True, hide_index=True)

    # [세부 4] 협력업체 관리
    elif view == "supplier":
        st.markdown("<div class='yonsei-header-bar'><span class='yonsei-title'>4. 협력업체 관리 — 2026년 원·부자재 및 OEM 서류심사 확정 집계</span></div>", unsafe_allow_html=True)
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

            st.dataframe(df_sf, use_container_width=True, hide_index=True, height=390)

            st.subheader("■ 등급 외 업체 주요 미비사항")
            uc1, uc2 = st.columns([1, 1.45])
            with uc1:
                st.dataframe(df_sup_under_c, use_container_width=True, hide_index=True)
            with uc2:
                st.dataframe(df_sup_under_d, use_container_width=True, hide_index=True)

    # [세부 5] 심사점수 및 일정 · 실시간 진행현황(온도계) 통합 관리 ('심사점수 및 일정 관리 DB' 시트 연동)
    elif view == "kpi_5":
        info5 = st.session_state["manual_kpis"]["kpi_5"]
        aud_sum = get_active_audit_summary(df_audit_sched, today_kst_str)

        st.markdown("<div class='yonsei-header-bar'><span class='yonsei-title'>5. 심사점수 — 연간 심사 일정 등록 · 실시간 진행 온도계 · 점수 관리</span></div>", unsafe_allow_html=True)

        # 상단 실시간 대표 심사 진행 온도계 대형 배너
        st.markdown(f"""
        <div class="forecast-box">
            <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;">
                <div>
                    <b style="font-size:16px; color:#00205B;">{html.escape(aud_sum['banner_text'])}</b><br>
                    <span style="font-size:13.5px; color:#475569;">
                        현재 심사점수 — <b>목표 : {html.escape(info5['target_text'])}</b> &nbsp;|&nbsp;
                        <b>실적 : {html.escape(info5['actual_text'])}</b> ({html.escape(info5['sub_badge'])})
                    </span>
                </div>
                <span class="badge-pill" style="font-size:13.5px; padding:5px 14px; background:{aud_sum['color']}; color:#FFFFFF;">
                    {html.escape(aud_sum['icon'])} 현재 단계 : {html.escape(aud_sum['status'])} ({aud_sum['pct']}%)
                </span>
            </div>
            <div class="thermo-row" style="margin-top:10px;">
                <div class="thermo-bulb" style="width:28px; height:28px; font-size:15px; background-color:{aud_sum['color']};">🌡️</div>
                <div class="thermo-track" style="height:18px;">
                    <div class="thermo-fill" style="width:{aud_sum['pct']}%; background-color:{aud_sum['color']};"></div>
                </div>
            </div>
            <div style="display:flex; justify-content:space-between; font-size:11.8px; color:#64748B; font-weight:700; padding:0 4px;">
                <span>📋 심사준비중(20%)</span>
                <span>🔍 심사중(50%)</span>
                <span>📑 서류심사중(75%)</span>
                <span>🏭 현장심사중(85%)</span>
                <span>✅ 심사종료(100%)</span>
            </div>
        </div>
        """, unsafe_allow_html=True)

        col_add, col_score = st.columns([1.25, 1.0])

        with col_add:
            st.subheader("➕ 신규 심사 일정 등록 (시트 자동 저장)")
            with st.form("form_add_audit_schedule", clear_on_submit=True):
                fa1, fa2 = st.columns([1, 1])
                with fa1:
                    in_audit_dt = st.date_input("심사 일자", value=now_kst().date())
                with fa2:
                    in_audit_st = st.selectbox("초기 진행현황", AUDIT_STATUS_LIST, index=0)
                in_audit_nm = st.text_input("심사명 / 심사 내용 (예: 아산공장 HACCP 정기심사, FSSC 22000 사후심사)")
                fa3, fa4 = st.columns([1, 1.5])
                with fa3:
                    in_audit_sc = st.text_input("획득 점수 (종료 시 선택 입력, 예: 95.2점)")
                with fa4:
                    in_audit_memo = st.text_input("비고 / 중점 대응 메모")

                btn_add_sched = st.form_submit_button("💾 심사 일정 추가 및 시트 저장")
                if btn_add_sched:
                    if not in_audit_nm.strip():
                        st.warning("심사명(심사 내용)을 입력해 주세요.")
                    else:
                        new_row = pd.DataFrame([{
                            "고유ID": str(uuid.uuid4())[:8],
                            "심사일자": in_audit_dt.strftime("%Y-%m-%d"),
                            "심사명": in_audit_nm.strip(),
                            "진행현황": in_audit_st,
                            "점수": in_audit_sc.strip(),
                            "비고": in_audit_memo.strip(),
                            "수정일시": now_kst().strftime("%Y-%m-%d %H:%M:%S")
                        }])
                        updated_df = pd.concat([df_audit_sched, new_row], ignore_index=True)
                        ok_s, msg_s = save_audit_schedule_df_to_sheet(updated_df)
                        if ok_s:
                            st.success(msg_s)
                            st.rerun()
                        else:
                            st.error(msg_s)

        with col_score:
            st.subheader("🎯 상단 대표 심사점수 수정 (시트 영구 저장)")
            with st.form("form_kpi5_score_edit"):
                s_t_txt = st.text_input("목표 점수 문구", value=info5["target_text"])
                s_a_txt = st.text_input("실적 점수 문구", value=info5["actual_text"])
                s_badge = st.text_input("대비/보조 배지 문구", value=info5["sub_badge"])
                sig_opts = ["green", "yellow", "red", "gray"]
                sig_labels = {"green": "🟢 양호 (초록)", "yellow": "🟡 주의 (노랑)", "red": "🔴 경고 (빨강)", "gray": "⚪ 대기 (회색)"}
                s_sig = st.selectbox(
                    "카드 신호등 색상",
                    sig_opts,
                    index=sig_opts.index(info5["signal"]) if info5["signal"] in sig_opts else 0,
                    format_func=lambda x: sig_labels[x]
                )
                btn_save_sc = st.form_submit_button("💾 대표 점수 저장")
                if btn_save_sc:
                    updated_k5 = {
                        **info5,
                        "target_text": s_t_txt.strip(),
                        "actual_text": s_a_txt.strip(),
                        "sub_badge": s_badge.strip(),
                        "signal": s_sig
                    }
                    st.session_state["manual_kpis"]["kpi_5"] = updated_k5
                    ok_m, msg_m = save_manual_kpi_to_sheet("kpi_5", updated_k5)
                    if ok_m:
                        st.success(msg_m)
                        st.rerun()
                    else:
                        st.warning(msg_m)

        st.markdown("---")
        st.subheader("🌡️ 등록된 심사 일정 진행현황 실시간 변경 및 전체 목록")

        if df_audit_sched.empty:
            st.info("아직 등록된 심사 일정이 없습니다. 위 '신규 심사 일정 등록'에서 날짜와 심사 내용을 추가하면 이곳에서 진행현황(심사준비중~심사종료)을 실시간으로 전환할 수 있습니다.")
        else:
            df_sorted_aud = df_audit_sched.sort_values("심사일자", ascending=True).reset_index(drop=True)
            opt_labels = [
                f"[{r['심사일자']}] {r['심사명']} (현재: {r['진행현황']})"
                for _, r in df_sorted_aud.iterrows()
            ]
            sel_idx = st.selectbox("상태를 변경하거나 수정·삭제할 심사 선택", range(len(opt_labels)), format_func=lambda i: opt_labels[i])
            sel_row = df_sorted_aud.iloc[sel_idx]
            sel_uid = sel_row["고유ID"]

            with st.form("form_update_audit_status"):
                u1, u2, u3 = st.columns([1.0, 1.6, 1.1])
                with u1:
                    parsed_d = pd.to_datetime(sel_row["심사일자"], errors="coerce")
                    def_d = parsed_d.date() if pd.notna(parsed_d) else now_kst().date()
                    up_dt = st.date_input("심사 일자 수정", value=def_d)
                with u2:
                    up_nm = st.text_input("심사명 수정", value=str(sel_row["심사명"]))
                with u3:
                    cur_st_idx = AUDIT_STATUS_LIST.index(sel_row["진행현황"]) if sel_row["진행현황"] in AUDIT_STATUS_LIST else 0
                    up_st = st.selectbox("🌡️ 실시간 진행현황 선택", AUDIT_STATUS_LIST, index=cur_st_idx)

                u4, u5 = st.columns([1.0, 2.0])
                with u4:
                    up_sc = st.text_input("획득 점수", value=str(sel_row.get("점수", "")))
                with u5:
                    up_memo = st.text_input("비고 / 특이사항", value=str(sel_row.get("비고", "")))

                b_col_save, b_col_del = st.columns([3, 1])
                with b_col_save:
                    do_update = st.form_submit_button("✅ 선택한 심사 진행현황·내용 즉시 반영")
                with b_col_del:
                    do_delete = st.form_submit_button("🗑️ 이 일정 삭제")

                if do_update:
                    df_mod = df_audit_sched.copy()
                    mask = df_mod["고유ID"] == sel_uid
                    df_mod.loc[mask, "심사일자"] = up_dt.strftime("%Y-%m-%d")
                    df_mod.loc[mask, "심사명"] = up_nm.strip()
                    df_mod.loc[mask, "진행현황"] = up_st
                    df_mod.loc[mask, "점수"] = up_sc.strip()
                    df_mod.loc[mask, "비고"] = up_memo.strip()
                    df_mod.loc[mask, "수정일시"] = now_kst().strftime("%Y-%m-%d %H:%M:%S")
                    ok_u, msg_u = save_audit_schedule_df_to_sheet(df_mod)
                    if ok_u:
                        st.success(msg_u)
                        st.rerun()
                    else:
                        st.error(msg_u)

                if do_delete:
                    df_rem = df_audit_sched[df_audit_sched["고유ID"] != sel_uid].copy()
                    ok_d, msg_d = save_audit_schedule_df_to_sheet(df_rem)
                    if ok_d:
                        st.success("선택한 심사 일정이 삭제되었습니다.")
                        st.rerun()
                    else:
                        st.error(msg_d)

            aud_cols = [
                {"key": "dday", "label": "구분", "width": "10%", "align": "center"},
                {"key": "dt", "label": "심사일자", "width": "12%", "align": "center"},
                {"key": "nm", "label": "심사명 (내용)", "width": "30%", "align": "left"},
                {"key": "st", "label": "진행현황 (게이지)", "width": "16%", "align": "center"},
                {"key": "sc", "label": "결과 점수", "width": "10%", "align": "center"},
                {"key": "memo", "label": "비고", "width": "22%", "align": "left"}
            ]
            today_d_obj = now_kst().date()
            aud_html_rows = []
            for _, ar in df_sorted_aud.iterrows():
                a_dt = pd.to_datetime(ar["심사일자"], errors="coerce")
                if pd.notna(a_dt):
                    diff_d = (a_dt.date() - today_d_obj).days
                    if diff_d == 0:
                        d_txt, d_cls = "🚨 금일심사", "cell-red"
                    elif diff_d > 0:
                        d_txt, d_cls = f"D-{diff_d}", "cell-yellow" if diff_d <= 7 else ""
                    else:
                        d_txt, d_cls = f"경과({abs(diff_d)}일)", "cell-gray"
                else:
                    d_txt, d_cls = "-", ""

                st_v = ar["진행현황"]
                pct_v = AUDIT_STATUS_CONFIG.get(st_v, {"pct": 20})["pct"]
                if st_v == "심사종료":
                    st_c = "cell-green"
                elif st_v in ["심사중", "서류심사중", "현장심사중"]:
                    st_c = "cell-yellow"
                else:
                    st_c = ""

                aud_html_rows.append({
                    "dday": {"text": d_txt, "cls": d_cls},
                    "dt": {"text": ar["심사일자"], "cls": "cell-red" if d_txt == "🚨 금일심사" else ""},
                    "nm": {"text": ar["심사명"], "cls": ""},
                    "st": {"text": f"{st_v} ({pct_v}%)", "cls": st_c},
                    "sc": {"text": ar["점수"] if str(ar["점수"]).strip() else "-", "cls": "cell-green" if str(ar["점수"]).strip() else ""},
                    "memo": {"text": ar["비고"] if str(ar["비고"]).strip() else "-", "cls": ""}
                })
            st.markdown(render_html_table(aud_cols, aud_html_rows), unsafe_allow_html=True)

    # [세부 6] 표시사항 진행 현황
    elif view == "label_status":
        st.markdown("<div class='yonsei-header-bar'><span class='yonsei-title'>6. 표시사항 진행 현황 — 전년 대비 업무량 증가 분석 및 실시간 검토 현황</span></div>", unsafe_allow_html=True)
        if df_label_status.empty:
            st.error("표시사항 현황 시트 데이터를 불러오지 못했습니다.")
        else:
            if broken_date_cnt > 0:
                st.warning(f"참고: 시트 원본에 텍스트 '#######'로 저장되어 연도 분류에서 제외된 행이 {broken_date_cnt}건 있습니다.")

            df_valid_lb = df_label_status[df_label_status["분류"] != "제외(개시/준비·보류)"].copy()
            if "_yr_num" not in df_valid_lb.columns:
                df_valid_lb["_yr_num"] = (
                    df_valid_lb["등록연도"].astype(str).str.extract(r"(\d{4})")[0].fillna(0).astype(int)
                    if "등록연도" in df_valid_lb.columns else 0
                )
            if "_mo_num" not in df_valid_lb.columns:
                df_valid_lb["_mo_num"] = (
                    df_valid_lb["등록월"].astype(str).str.extract(r"(\d{1,2})")[0].fillna(0).astype(int)
                    if "등록월" in df_valid_lb.columns else 0
                )

            df_2025 = df_valid_lb[df_valid_lb["_yr_num"] == 2025]
            df_2026 = df_valid_lb[df_valid_lb["_yr_num"] == 2026]

            cnt_25_all = len(df_2025)
            cnt_26_all = len(df_2026)

            max_m_26 = int(df_2026["_mo_num"].max()) if not df_2026.empty and df_2026["_mo_num"].max() > 0 else now_kst().month
            active_m_25 = max(int(df_2025[df_2025["_mo_num"] > 0]["_mo_num"].nunique()), 1) if not df_2025.empty else 12
            active_m_26 = max(int(df_2026[df_2026["_mo_num"] > 0]["_mo_num"].nunique()), 1) if not df_2026.empty else max_m_26

            cnt_25_ytd = len(df_2025[(df_2025["_mo_num"] >= 1) & (df_2025["_mo_num"] <= max_m_26)])
            cnt_26_ytd = len(df_2026[(df_2026["_mo_num"] >= 1) & (df_2026["_mo_num"] <= max_m_26)])
            ytd_diff = cnt_26_ytd - cnt_25_ytd
            ytd_pct = round((ytd_diff / cnt_25_ytd) * 100, 1) if cnt_25_ytd > 0 else 0.0

            m_avg_25 = round(cnt_25_all / active_m_25, 1) if cnt_25_all > 0 else 0.0
            m_avg_26 = round(cnt_26_all / active_m_26, 1) if cnt_26_all > 0 else 0.0
            avg_diff = round(m_avg_26 - m_avg_25, 1)

            tab_lb1, tab_lb2, tab_lb3 = st.tabs([
                "📈 전년 대비(2025 vs 2026) 업무량 증가 및 급증 제품군 분석",
                f"🔴 현재 검토중 목록 ({reviewing_cnt}건) 및 연도·월별 추이",
                "📋 전체 표시사항 심의 이력 조회"
            ])

            with tab_lb1:
                m1, m2, m3, m4 = st.columns(4)
                m1.metric(f"2026년 누적 검토 (1~{max_m_26}월)", f"{cnt_26_all:,} 건", f"동기간 전년비 {ytd_diff:+,}건 ({ytd_pct:+.1f}%)")
                m2.metric("전년도(2025년) 연간 실적", f"{cnt_25_all:,} 건", f"25년 1~{max_m_26}월 동기간 {cnt_25_ytd:,}건")
                m3.metric("월평균 검토 처리량 변화", f"월 {m_avg_26} 건", f"25년 월 {m_avg_25}건 대비 {avg_diff:+.1f}건/월")
                m4.metric("현재 실시간 검토 진행", f"{reviewing_cnt:,} 건", f"누적 완료 총 {completed_cnt:,}건")

                cat_col_nm = "대분류(마케팅 카테고리)" if "대분류(마케팅 카테고리)" in df_valid_lb.columns else None
                top_growth_txt = "-"
                df_cat_cmp = pd.DataFrame()
                if cat_col_nm:
                    c25 = df_2025.groupby(cat_col_nm).size().rename("2025년_건수")
                    c26 = df_2026.groupby(cat_col_nm).size().rename("2026년_건수")
                    df_cat_cmp = pd.concat([c25, c26], axis=1).fillna(0).astype(int).reset_index()
                    df_cat_cmp[cat_col_nm] = df_cat_cmp[cat_col_nm].replace("", "미분류")
                    df_cat_cmp["증감(건)"] = df_cat_cmp["2026년_건수"] - df_cat_cmp["2025년_건수"]
                    df_cat_cmp["26년_비중(%)"] = round(df_cat_cmp["2026년_건수"] / max(cnt_26_all, 1) * 100, 1)
                    df_cat_cmp = df_cat_cmp.sort_values("2026년_건수", ascending=False)
                    if not df_cat_cmp.empty:
                        top_g = df_cat_cmp.sort_values("증감(건)", ascending=False).iloc[0]
                        top_growth_txt = f"{top_g[cat_col_nm]} (25년 {top_g['2025년_건수']}건 → 26년 {top_g['2026년_건수']}건, {top_g['증감(건)']:+d}건)"

                st.markdown(f"""
                <div class="forecast-box">
                    <b>📊 표시사항 심의·검토 업무량 증가 팩트 요약</b><br>
                    • <b>동기간 처리량 비교 :</b> 1~{max_m_26}월 동기간 기준 2025년 <b>{cnt_25_ytd:,}건</b>에서 2026년 <b>{cnt_26_ytd:,}건</b>으로 <b>{ytd_diff:+,}건({ytd_pct:+.1f}%)</b> 변동했으며, 월평균 처리 건수는 <b>{m_avg_25}건/월 → {m_avg_26}건/월({avg_diff:+.1f}건/월)</b> 수준입니다.<br>
                    • <b>최다 증가 제품 카테고리 :</b> <b>{html.escape(top_growth_txt)}</b> 제품군을 중심으로 표시사항 신규·변경 검토 건수가 집중되고 있습니다.
                </div>
                """, unsafe_allow_html=True)

                g_left, g_right = st.columns(2)
                with g_left:
                    m_cmp_rows = []
                    for m_i in range(1, 13):
                        m_cmp_rows.append({
                            "월": f"{m_i}월",
                            "2025년": int((df_2025["_mo_num"] == m_i).sum()),
                            "2026년": int((df_2026["_mo_num"] == m_i).sum())
                        })
                    df_mcmp = pd.DataFrame(m_cmp_rows)
                    fig_mcmp = go.Figure()
                    fig_mcmp.add_trace(go.Bar(x=df_mcmp["월"], y=df_mcmp["2025년"], name="2025년 건수", marker_color="#CBD5E1", text=df_mcmp["2025년"], textposition="outside"))
                    fig_mcmp.add_trace(go.Bar(x=df_mcmp["월"], y=df_mcmp["2026년"], name="2026년 건수", marker_color="#003876", text=df_mcmp["2026년"], textposition="outside"))
                    fig_mcmp.update_layout(barmode="group", height=360, title="📅 월별 표시사항 심의 건수 비교 (2025년 vs 2026년)", paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF")
                    st.plotly_chart(fig_mcmp, use_container_width=True)

                with g_right:
                    if not df_cat_cmp.empty:
                        fig_cat = go.Figure()
                        fig_cat.add_trace(go.Bar(x=df_cat_cmp[cat_col_nm], y=df_cat_cmp["2025년_건수"], name="2025년", marker_color="#94A3B8", text=df_cat_cmp["2025년_건수"], textposition="outside"))
                        fig_cat.add_trace(go.Bar(x=df_cat_cmp[cat_col_nm], y=df_cat_cmp["2026년_건수"], name="2026년", marker_color="#0052A5", text=df_cat_cmp["2026년_건수"], textposition="outside"))
                        fig_cat.update_layout(barmode="group", height=360, title="🥛 제품 대분류(카테고리)별 검토 건수 증가 비교", paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF")
                        st.plotly_chart(fig_cat, use_container_width=True)

                b_col1, b_col2, b_col3 = st.columns(3)
                with b_col1:
                    st.markdown("##### 📦 제품 카테고리별 증감표")
                    if not df_cat_cmp.empty:
                        st.dataframe(df_cat_cmp, use_container_width=True, hide_index=True)
                with b_col2:
                    st.markdown("##### 🏭 2026년 주요 생산처 TOP 10")
                    if "생산처" in df_2026.columns and not df_2026.empty:
                        prod_site_df = df_2026["생산처"].replace("", "미기입").value_counts().head(10).reset_index()
                        prod_site_df.columns = ["생산처(자체/OEM)", "2026년_검토건수"]
                        st.dataframe(prod_site_df, use_container_width=True, hide_index=True)
                with b_col3:
                    st.markdown("##### 🏷️ 2026년 포장재 유형 & 요청부서")
                    if "검토 포장재 유형" in df_2026.columns and not df_2026.empty:
                        pkg_df = df_2026["검토 포장재 유형"].replace("", "미기입").value_counts().head(10).reset_index()
                        pkg_df.columns = ["검토 포장재 유형", "2026년_검토건수"]
                        st.dataframe(pkg_df, use_container_width=True, hide_index=True)

            with tab_lb2:
                show_cols = [c for c in ["*docNo", "상태", "제목", "요청부서", "대분류(마케팅 카테고리)", "보관방법", "생산처", "검토 포장재 유형", "등록일자", "최종수정자"] if c in df_label_status.columns]
                st.subheader(f"🔴 현재 [식품안전팀 검토중] 전체 목록 ({reviewing_cnt}건)")
                st.dataframe(df_label_status[df_label_status["분류"] == "식품안전팀 검토중"][show_cols], use_container_width=True, hide_index=True)

                if "요청부서" in df_valid_lb.columns:
                    st.subheader("🏢 요청부서(등록팀)별 2025년 vs 2026년 의뢰 현황")
                    d25 = df_2025.groupby("요청부서").size().rename("2025년")
                    d26 = df_2026.groupby("요청부서").size().rename("2026년")
                    d_now = df_valid_lb[df_valid_lb["분류"] == "식품안전팀 검토중"].groupby("요청부서").size().rename("현재_검토중")
                    dept_cmp = pd.concat([d25, d26, d_now], axis=1).fillna(0).astype(int).reset_index()
                    dept_cmp["증감(26-25)"] = dept_cmp["2026년"] - dept_cmp["2025년"]
                    dept_cmp = dept_cmp.sort_values("2026년", ascending=False)
                    st.dataframe(dept_cmp, use_container_width=True, hide_index=True)

            with tab_lb3:
                show_cols = [c for c in ["*docNo", "상태", "제목", "요청부서", "대분류(마케팅 카테고리)", "보관방법", "생산처", "검토 포장재 유형", "등록일자", "최종수정자"] if c in df_label_status.columns]
                kw_lb = st.text_input("🔍 품목 제목 / 요청부서 / 생산처 검색")
                df_lv = df_label_status[show_cols + ["분류", "등록연도", "등록월"]]
                if kw_lb:
                    df_lv = df_lv[df_lv.astype(str).apply(lambda x: x.str.contains(kw_lb, case=False, na=False)).any(axis=1)]
                st.dataframe(df_lv, use_container_width=True, hide_index=True, height=450)

    # [세부 7] 표시사항 특이사항 (원자재 표시사항 DB 단독)
    elif view == "label_issue":
        st.markdown("<div class='yonsei-header-bar'><span class='yonsei-title'>7. 표시사항 특이사항 — 원자재 표시사항 DB 검증 및 알레르기 현황</span></div>", unsafe_allow_html=True)
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

    # [세부 8~12] 수동 관리 KPI 세부 조회 및 시트 영구 저장 편집기
    elif view in st.session_state["manual_kpis"]:
        info = st.session_state["manual_kpis"][view]
        st.markdown(f"<div class='yonsei-header-bar'><span class='yonsei-title'>{html.escape(info['title'])} — 세부 현황 및 수치 편집 (시트 영구 저장)</span></div>", unsafe_allow_html=True)

        c_preview, c_edit = st.columns([1.15, 1.35])

        with c_preview:
            st.subheader("📌 현재 현황판 표시 데이터")
            st.markdown(f"""
            <div class="forecast-box">
                • <b>목표 :</b> {html.escape(info['target_text'])}<br>
                • <b>실적 :</b> {html.escape(info['actual_text'])}<br>
                • <b>보조 요약 :</b> {html.escape(info['sub_badge'])}
            </div>
            """, unsafe_allow_html=True)
            if info["has_chart"]:
                st.plotly_chart(
                    draw_mini_bar(float(info["target_num"]), float(info["actual_num"]), suffix=info["suffix"]),
                    use_container_width=True
                )
            st.markdown(f"##### 📋 {info['notes_title']}")
            for line in info["notes"]:
                st.write(f"- {line}")

        with c_edit:
            st.subheader("✏️ 수치 및 세부 내역 수정 (저장 시 시트 자동 기록)")
            with st.form(key=f"form_{view}"):
                new_t_txt = st.text_input("목표 표시 문구", value=info["target_text"])
                new_a_txt = st.text_input("실적 표시 문구", value=info["actual_text"])
                new_badge = st.text_input("하단 배지 문구", value=info["sub_badge"])

                sig_opts = ["green", "yellow", "red", "gray"]
                sig_labels = {"green": "🟢 양호 (초록)", "yellow": "🟡 주의 (노랑)", "red": "🔴 경고 (빨강)", "gray": "⚪ 대기 (회색)"}
                new_sig = st.selectbox(
                    "신호등 상태 선택",
                    sig_opts,
                    index=sig_opts.index(info["signal"]) if info["signal"] in sig_opts else 0,
                    format_func=lambda x: sig_labels[x]
                )

                if info["has_chart"]:
                    nc1, nc2 = st.columns(2)
                    with nc1:
                        new_t_num = st.number_input("그래프 목표 숫자", value=float(info["target_num"]), step=0.1)
                    with nc2:
                        new_a_num = st.number_input("그래프 실적 숫자", value=float(info["actual_num"]), step=0.1)
                else:
                    new_t_num, new_a_num = info["target_num"], info["actual_num"]

                new_notes_title = st.text_input("세부 메모 소제목", value=info["notes_title"])
                new_notes_raw = st.text_area("세부 항목 (줄바꿈으로 구분)", value="\n".join(info["notes"]), height=130)

                submitted = st.form_submit_button("💾 변경사항 시트 영구 저장")
                if submitted:
                    updated_item = {
                        **info,
                        "target_text": new_t_txt,
                        "actual_text": new_a_txt,
                        "sub_badge": new_badge,
                        "signal": new_sig,
                        "target_num": float(new_t_num),
                        "actual_num": float(new_a_num),
                        "notes_title": new_notes_title,
                        "notes": [ln.strip() for ln in new_notes_raw.splitlines() if ln.strip()]
                    }
                    st.session_state["manual_kpis"][view] = updated_item
                    ok_save, msg_save = save_manual_kpi_to_sheet(view, updated_item)
                    if ok_save:
                        st.success(msg_save)
                    else:
                        st.warning(msg_save)
                    st.rerun()
# ============================ [PART 3 / 3 끝] ============================
