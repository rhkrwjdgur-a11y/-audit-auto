import html
import re
import time
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
# 한국 표준시(KST, UTC+9) 고정 유틸리티 (외부 패키지 의존성 없음)
# ==============================================================================
KST_TZ = timezone(timedelta(hours=9))


def now_kst() -> datetime:
    """Streamlit Cloud(UTC 서버) 환경에서도 항상 한국 표준시(KST) 반환"""
    return datetime.now(KST_TZ).replace(tzinfo=None)


# ==============================================================================
# 1. 페이지 기본 설정 및 세션 상태 초기화
# ==============================================================================
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


AUDIT_HEADERS = ["심사ID", "심사일자", "심사명", "진행현황", "심사점수", "비고", "최종수정일시"]
AUDIT_STAGE_ORDER = ["심사준비중", "심사중", "서류심사중", "현장심사중", "심사종료"]
AUDIT_STAGE_INFO = {
    "심사준비중": {"pct": 20, "color": "#3B82F6", "badge_cls": "badge-warn", "icon": "📋"},
    "심사중": {"pct": 50, "color": "#F59E0B", "badge_cls": "badge-warn", "icon": "🔍"},
    "서류심사중": {"pct": 75, "color": "#0284C7", "badge_cls": "badge-warn", "icon": "📂"},
    "현장심사중": {"pct": 80, "color": "#EA580C", "badge_cls": "badge-warn", "icon": "🏭"},
    "심사종료": {"pct": 100, "color": "#10B981", "badge_cls": "badge-ok", "icon": "✅"}
}

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
    "label_status": "표시사항 현황",
    "raw_label_db": "원자재 표시사항 DB",
    "process_soy": "[상온]두유 배양검사 일보",
    "process_rt": "[상온]상온제품 공정 관리 일보",
    "process_milk": "[우유] 유제품 포장 공정관리 일보",
    "audit_db": "심사점수 및 일정 관리 DB"
}

# ==============================================================================
# 2. 연세유업 브랜드 컬러 CSS (상단 고정 툴바 가림 원천 차단 + 온도계 진행바)
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
    .badge-info { background-color: #E0F2FE; color: #075985; border: 1px solid #7DD3FC; }
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
    /* 5번 심사점수 카드 전용 온도계 게이지 & 일정 보드 */
    .audit-card-box {
        background-color: #F8FAFC;
        border: 1px solid #DCE4EE;
        border-radius: 8px;
        padding: 8px 10px;
        height: 146px;
        display: flex;
        flex-direction: column;
        justify-content: space-between;
        margin-top: 4px;
    }
    .thermo-wrap {
        display: flex;
        align-items: center;
        gap: 7px;
        margin: 4px 0;
    }
    .thermo-track {
        flex: 1;
        height: 14px;
        background-color: #E2E8F0;
        border-radius: 999px;
        overflow: hidden;
        border: 1px solid #CBD5E1;
        position: relative;
    }
    .thermo-fill {
        height: 100%;
        border-radius: 999px;
        transition: width 0.35s ease;
    }
    .audit-mini-list {
        height: 62px;
        overflow-y: auto;
        border-top: 1px solid #E2E8F0;
        padding-top: 4px;
        font-size: 11.8px;
        line-height: 1.48;
        color: #334155;
    }
    /* 세부 5번 대형 단계 트래커 */
    .stage-step-bar {
        display: flex;
        gap: 8px;
        margin: 10px 0 16px 0;
    }
    .stage-step-item {
        flex: 1;
        text-align: center;
        padding: 9px 6px;
        border-radius: 8px;
        font-size: 13px;
        font-weight: 700;
        border: 1px solid #CBD5E1;
        background-color: #F8FAFC;
        color: #64748B;
    }
    .stage-step-active {
        background: linear-gradient(90deg, #00205B 0%, #0052A5 100%);
        color: #FFFFFF !important;
        border-color: #00205B;
        box-shadow: 0 3px 8px rgba(0, 56, 118, 0.25);
    }
    .stage-step-done {
        background-color: #DCFCE7;
        color: #166534;
        border-color: #86EFAC;
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

st.markdown("<div style='height: 32px;'></div>", unsafe_allow_html=True)


# ==============================================================================
# 3. Google 인증 및 429 보호 시트 입출력 유틸리티
# ==============================================================================
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


def api_call_with_retry(func, *args, **kwargs):
    """Google Sheets 429 할당량 초과 발생 시 자동 대기 후 최대 4회 재시도"""
    for attempt in range(4):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            if "429" in str(e) or "Quota exceeded" in str(e):
                time.sleep(2.5 * (attempt + 1))
                continue
            raise
    return func(*args, **kwargs)


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


def get_values_safe(ws):
    return api_call_with_retry(ws.get_all_values)


def get_values_unformatted(ws):
    try:
        return api_call_with_retry(ws.get_all_values, value_render_option="UNFORMATTED_VALUE")
    except Exception:
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


# ==============================================================================
# 5. 실시간 구글 시트 데이터 파서 (1~7번 + 5번 심사점수 및 일정 관리 DB)
# ==============================================================================

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
        target_ws = None
        for w in api_call_with_retry(sh.worksheets):
            sample = get_values_safe(w)[:8]
            flat_txt = " ".join([" ".join(r) for r in sample])
            if "유형" in flat_txt and ("3월" in flat_txt or "생산" in flat_txt):
                target_ws = w
                break
        if target_ws is None:
            target_ws = api_call_with_retry(sh.get_worksheet, 0)

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
            trend_rows.append
