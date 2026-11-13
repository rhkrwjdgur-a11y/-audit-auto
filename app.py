import re
from datetime import datetime, timedelta, timezone, date

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
# 0. 원칙: 모든 데이터는 구글 시트에서만 읽는다.
#    - 코드 안에 샘플/Fallback 데이터 없음
#    - 시트 연결/파싱 실패 시 조용히 넘어가지 않고 화면에 원인 표시 후 중단
#    - 시트에 없는 값은 추정하지 않고 "시트에 기록 없음"으로 표시
# ==============================================================================
st.set_page_config(
    page_title="2026 업적 KPI 현황판_품질안전부문 (AX Dashboard)",
    layout="wide",
    initial_sidebar_state="collapsed",
)

if "current_view" not in st.session_state:
    st.session_state.current_view = "main"


def set_view(view_name):
    st.session_state.current_view = view_name


class SheetLoadError(Exception):
    pass


# Streamlit Cloud 서버는 UTC이므로 한국시간(KST) 기준으로 날짜 계산
KST = timezone(timedelta(hours=9))


def now_kst():
    return datetime.now(KST)


NO_DATA = "시트에 기록 없음"

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
}

# ==============================================================================
# 1. CSS
# ==============================================================================
st.markdown("""
<style>
    .main-title { font-size: 28px; font-weight: 800; color: #002060; border-bottom: 3px solid #7F9EB2;
        padding-bottom: 8px; margin-bottom: 5px; display: flex; justify-content: space-between; align-items: flex-end; }
    .sub-date { font-size: 14px; font-weight: 700; color: #002060; text-align: right; margin-bottom: 10px; }
    .ax-banner { background: linear-gradient(90deg, #002060 0%, #1F4E78 100%); color: #FFFFFF; padding: 12px 18px;
        border-radius: 6px; margin-bottom: 16px; font-size: 14px; line-height: 1.6; box-shadow: 0 2px 6px rgba(0,0,0,0.15); }
    .kpi-card { background-color: #F2F2F2; border: 1px solid #D9D9D9; border-radius: 4px;
        box-shadow: 2px 2px 6px rgba(0,0,0,0.08); margin-bottom: 6px; overflow: hidden; }
    .kpi-header { background-color: #44546A; color: white; font-size: 16px; font-weight: 700; text-align: center; padding: 10px 5px; }
    .kpi-body { padding: 14px 15px 5px 15px; min-height: 135px; position: relative; font-size: 13.5px; color: #111111; line-height: 1.72; }
    .kpi-bullet { color: #44546A; font-weight: bold; margin-right: 6px; }
    .ai-line { font-size: 12.5px; font-weight: 700; color: #1F4E78; background-color: #E8EEF5; padding: 3px 8px;
        border-radius: 4px; margin-top: 4px; display: inline-block; }
    .unit-label { font-size: 12px; font-weight: 700; color: #002060; text-align: right; margin-top: -8px; margin-bottom: -12px; padding-right: 12px; }
    .signal-dot { height: 22px; width: 22px; border-radius: 50%; position: absolute; top: 12px; right: 15px; box-shadow: 0 0 6px rgba(0,0,0,0.25); }
    .signal-red { background-color: #FF0000; border: 1.5px solid #800000; }
    .signal-yellow { background-color: #FFC000; border: 1.5px solid #806000; }
    .signal-green { background-color: #00B050; border: 1.5px solid #00602B; }
    .signal-gray { background-color: #A6A6A6; border: 1.5px solid #595959; }
    .rep-list-box { background-color: #FFFFFF; border: 1px solid #D9D9D9; border-radius: 4px; padding: 8px 10px;
        margin-top: 6px; font-size: 12px; line-height: 1.5; color: #222222; }
    div.stButton > button { width: 100%; background-color: #E7E6E6; color: #002060; font-weight: 700;
        border: 1px solid #BFBFBF; border-radius: 4px; margin-bottom: 18px; }
    div.stButton > button:hover { background-color: #002060; color: white; border-color: #002060; }
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# 2. 구글 인증 / 시트 열기 (실패 시 원인을 담아 예외 발생)
# ==============================================================================
@st.cache_resource
def get_gspread_client():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    errs = []
    if "google_oauth" in st.secrets:
        try:
            o = st.secrets["google_oauth"]
            creds = OAuthCredentials(
                token=None,
                refresh_token=o["refresh_token"],
                token_uri="https://oauth2.googleapis.com/token",
                client_id=o["client_id"],
                client_secret=o["client_secret"],
                # scopes를 지정하지 않으면 refresh_token 발급 시 승인된 범위를 그대로 사용 (invalid_scope 방지)
            )
            creds.refresh(Request())
            return gspread.authorize(creds)
        except Exception as e:
            errs.append(f"[google_oauth] {repr(e)}")
    if "gcp_service_account" in st.secrets:
        try:
            creds = ServiceAccountCredentials.from_service_account_info(
                dict(st.secrets["gcp_service_account"]), scopes=scopes
            )
            return gspread.authorize(creds)
        except Exception as e:
            errs.append(f"[gcp_service_account] {repr(e)}")
    if not errs:
        errs.append("Secrets에 [google_oauth] 또는 [gcp_service_account] 설정이 없습니다.")
    raise SheetLoadError("구글 인증 실패 - " + " / ".join(errs))


def short_err(e, n=160):
    """HTML 에러 페이지 등 긴 메시지를 잘라서 표시"""
    txt = re.sub(r"\s+", " ", repr(e))
    return txt[:n] + ("..." if len(txt) > n else "")


def open_sheet(key):
    client = get_gspread_client()
    title = SHEET_NAMES[key]
    errs = []
    urls = st.secrets["sheet_urls"] if "sheet_urls" in st.secrets else {}
    if key in urls:
        v = str(urls[key]).strip()
        try:
            return client.open_by_url(v) if v.startswith("http") else client.open_by_key(v)
        except Exception as e:
            errs.append(f"sheet_urls.{key} 열기 실패: {short_err(e)}")
    try:
        return client.open(title)
    except Exception as e:
        errs.append(f"파일명 '{title}' 열기 실패: {short_err(e)}")
    raise SheetLoadError(
        f"'{title}' 시트를 열 수 없습니다. Secrets [sheet_urls]의 '{key}' 값과 시트 공유 권한을 확인하세요. ({' / '.join(errs)})"
    )


# ==============================================================================
# 3. 공통 유틸
# ==============================================================================
def to_float(val, default=0.0):
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return default
    s = str(val).strip()
    if s in ["", "-", "nan", "None", "#######"]:
        return default
    try:
        cleaned = re.sub(r"[^\d.-]", "", s)
        return float(cleaned) if cleaned not in ["", "-", "."] else default
    except Exception:
        return default


def normalize_comp_name(name):
    s = str(name or "")
    for token in ["주식회사", "(주)", "㈜", "(유)", "(법인)", " ", "_", "\n", "\t"]:
        s = s.replace(token, "")
    return s.strip()


def kpi_setting(name):
    """목표값 등 시트에 없는 설정은 Secrets [kpi]에서만 읽는다. 없으면 None."""
    try:
        if "kpi" in st.secrets and name in st.secrets["kpi"]:
            return float(st.secrets["kpi"][name])
    except Exception:
        pass
    return None


def get_signal_dot_html(code):
    tips = {
        "red": "경고: 목표 미달 또는 위험",
        "yellow": "주의: 확인/관리 필요",
        "green": "양호",
        "gray": "판정 불가: 목표값/데이터 없음",
    }
    return f'<div class="signal-dot signal-{code}" title="{tips[code]}"></div>'


def calc_linear_trend_and_forecast(y_values, total_periods=12):
    valid_idx = [i for i, v in enumerate(y_values) if v > 0]
    valid_y = [y_values[i] for i in valid_idx]
    if len(valid_idx) >= 2:
        slope, intercept = np.polyfit(valid_idx, valid_y, 1)
        trend = [round(max(slope * i + intercept, 0.0), 2) for i in range(total_periods)]
    elif len(valid_idx) == 1:
        slope = 0.0
        trend = [round(valid_y[0], 2)] * total_periods
    else:
        slope = 0.0
        trend = [0.0] * total_periods
    return trend, round(float(slope), 4), len(valid_idx)


def list_date_tabs(sh):
    """날짜형 탭(11/13, 11.13 등)을 최신순으로 정렬해 [(date, worksheet)] 반환"""
    today = now_kst().date()
    tabs = []
    for w in sh.worksheets():
        t = w.title.strip()
        if "양식" in t or "복사" in t:
            continue
        m = re.search(r"(\d{1,2})[/\.](\d{1,2})", t)
        if not m:
            continue
        try:
            dt = date(today.year, int(m.group(1)), int(m.group(2)))
        except ValueError:
            continue
        if dt > today:
            dt = date(today.year - 1, dt.month, dt.day)
        tabs.append((dt, w))
    tabs.sort(key=lambda x: x[0], reverse=True)
    return tabs


def pick_today_yesterday(sh):
    """(오늘 탭, 전일 탭, 안내문구). 오늘 탭이 없으면 가장 최근 탭을 쓰되 안내문구로 명시"""
    tabs = list_date_tabs(sh)
    if not tabs:
        raise SheetLoadError("날짜형 탭(예: 11/13)을 찾을 수 없습니다.")
    today = now_kst().date()
    note = ""
    ws_t, dt_t = None, None
    for d, w in tabs:
        if d == today:
            ws_t, dt_t = w, d
            break
    if ws_t is None:
        dt_t, ws_t = tabs[0]
        note = f"오늘({today:%m/%d}) 탭이 없어 가장 최근 탭 '{ws_t.title}'을 표시합니다."
    ws_y = None
    for d, w in tabs:
        if d == dt_t - timedelta(days=1):
            ws_y = w
            break
    if ws_y is None:
        older = [w for d, w in tabs if d < dt_t]
        ws_y = older[0] if older else None
    return ws_t, ws_y, note


def find_col(headers, keywords):
    hs = [str(h).replace(" ", "") for h in headers]
    for kw in keywords:
        for i, h in enumerate(hs):
            if kw in h:
                return i
    return None


# ==============================================================================
# 4. 시트 로더 (모두 시트 전용)
# ==============================================================================
@st.cache_data(ttl=300)
def load_cost_data():
    sh = open_sheet("cost")
    rows = sh.get_worksheet(0).get_all_values()
    parsed = []
    for r in rows[2:]:
        r = r + [""] * (12 - len(r))
        m = str(r[0]).strip()
        if m not in FISCAL_MONTHS:
            continue
        b_act, b_tar = to_float(r[1]), to_float(r[2])
        fs_act, fs_tar = to_float(r[5]), to_float(r[6])
        qc_act, qc_tar = to_float(r[9]), to_float(r[10])
        parsed.append({
            "월": m,
            "부문_실적(만원)": b_act, "부문_기준(만원)": b_tar,
            "부문_달성률(%)": round(b_act / b_tar * 100, 1) if b_tar > 0 else 0.0,
            "식품안전팀_실적(만원)": fs_act, "식품안전팀_기준(만원)": fs_tar,
            "식품안전팀_달성률(%)": round(fs_act / fs_tar * 100, 1) if fs_tar > 0 else 0.0,
            "품질관리팀_실적(만원)": qc_act, "품질관리팀_기준(만원)": qc_tar,
            "품질관리팀_달성률(%)": round(qc_act / qc_tar * 100, 1) if qc_tar > 0 else 0.0,
        })
    if not parsed:
        raise SheetLoadError("원가절감 시트에서 3월~2월 행을 찾지 못했습니다. 시트 구조(A열 월 표기)를 확인하세요.")
    df = pd.DataFrame(parsed)
    # 시트 월 순서를 회계연도 순서로 정렬
    df["월"] = pd.Categorical(df["월"], categories=FISCAL_MONTHS, ordered=True)
    df = df.sort_values("월").reset_index(drop=True)
    df["월"] = df["월"].astype(str)
    return df


def _find_claim_type_col(rows):
    """'유형' 헤더가 있는 열 위치를 찾는다. 없으면 '합계'가 처음 나오는 열(앞 5칸)로 추정."""
    for r in rows[:12]:
        for i, c in enumerate(r):
            if str(c).replace(" ", "") == "유형":
                return i
    for r in rows:
        for i in range(min(5, len(r))):
            if str(r[i]).replace(" ", "") == "합계":
                return i
    return None


def _parse_claim_rows(rows):
    """클레임 탭 한 장을 파싱. 병합 셀(연도)은 첫 칸에만 값이 오므로 다음 연도가 나올 때까지 유지(forward-fill)."""
    type_col = _find_claim_type_col(rows)
    if type_col is None:
        return []
    cat_list = []
    current_year = None
    for r in rows:
        if len(r) <= type_col + 3:
            continue
        # 유형 열보다 왼쪽 셀에서 연도 표기를 찾는다 (병합 셀의 첫 칸)
        for c in r[:type_col]:
            ym = re.fullmatch(r"(2025|2026)\s*년?", str(c).strip())
            if ym:
                current_year = f"{ym.group(1)}년"
        cat_name = str(r[type_col]).strip()
        if cat_name.replace(" ", "") == "합계":
            cat_name = "합계"
        if not cat_name or cat_name in ["유형", "클레임 건수"] or current_year is None:
            continue
        vals = r[type_col + 1:]
        if len(vals) < 3:
            continue
        d = {
            "연도": current_year, "유형": cat_name,
            "합계_건수": int(to_float(vals[0])),
            "합계_생산수량": int(to_float(vals[1])),
            "합계_PPM": to_float(vals[2]),
        }
        for idx, m in enumerate(FISCAL_MONTHS):
            b = 3 + idx * 3
            if b + 2 < len(vals):
                d[f"{m}_건수"] = int(to_float(vals[b]))
                d[f"{m}_생산수량"] = int(to_float(vals[b + 1]))
                d[f"{m}_PPM"] = to_float(vals[b + 2])
            else:
                d[f"{m}_건수"], d[f"{m}_생산수량"], d[f"{m}_PPM"] = 0, 0, 0.0
        cat_list.append(d)
    return cat_list


@st.cache_data(ttl=300)
def load_claim_data():
    sh = open_sheet("claim")
    df_cat, used_tab, tried = None, None, []
    # 모든 탭을 순서대로 검사: '2026년 / 합계' 행이 있는 첫 탭을 사용 (시트1 → 시트2 → ...)
    for ws in sh.worksheets():
        rows = ws.get_all_values()
        cat_list = _parse_claim_rows(rows)
        if cat_list:
            df = pd.DataFrame(cat_list)
            if not df[(df["연도"] == "2026년") & (df["유형"] == "합계")].empty:
                df_cat, used_tab = df, ws.title
                break
        sample = [str(r[0]).strip() + "|" + (str(r[1]).strip() if len(r) > 1 else "") for r in rows[:8] if any(r)]
        tried.append(f"'{ws.title}'(행 {len(rows)}, 앞부분: {sample[:5]})")
    if df_cat is None:
        raise SheetLoadError("클레임 시트의 모든 탭에서 '2026년 / 합계' 행을 찾지 못했습니다. 검사한 탭: " + " / ".join(tried))

    row_26 = df_cat[(df_cat["연도"] == "2026년") & (df_cat["유형"] == "합계")]
    row_25 = df_cat[(df_cat["연도"] == "2025년") & (df_cat["유형"] == "합계")]
    target = kpi_setting("claim_target_ppm")
    trend_rows = []
    for m in FISCAL_MONTHS:
        trend_rows.append({
            "월": m,
            "2026년_건수": int(row_26[f"{m}_건수"].values[0]),
            "2026년_PPM": float(row_26[f"{m}_PPM"].values[0]),
            "2025년_건수": int(row_25[f"{m}_건수"].values[0]) if not row_25.empty else 0,
            "2025년_PPM": float(row_25[f"{m}_PPM"].values[0]) if not row_25.empty else 0.0,
            "목표_PPM": target if target is not None else np.nan,
        })
    df_trend = pd.DataFrame(trend_rows)
    df_trend.attrs["source_tab"] = used_tab
    return df_trend, df_cat


def build_division_claim_df(df_cat, year_str, categories):
    sub = df_cat[(df_cat["연도"] == year_str) & (df_cat["유형"].isin(categories))]
    out = []
    for m in FISCAL_MONTHS:
        cnt = int(sub[f"{m}_건수"].sum()) if not sub.empty else 0
        prod = int(sub[f"{m}_생산수량"].sum()) if not sub.empty else 0
        item = {"월": m, "합산_건수": cnt, "합산_생산수량": prod,
                "부문_통합_PPM": round(cnt / prod * 1_000_000, 2) if prod > 0 else 0.0}
        for cat in categories:
            cr = sub[sub["유형"] == cat]
            item[f"{cat}_건수"] = int(cr[f"{m}_건수"].values[0]) if not cr.empty else 0
            item[f"{cat}_PPM"] = float(cr[f"{m}_PPM"].values[0]) if not cr.empty else 0.0
        out.append(item)
    return pd.DataFrame(out), sub


# ---------------------- 공정 일보 ----------------------
def parse_rt_process_worksheet(ws, warns):
    rows = ws.get_all_values()
    tab_title = ws.title
    if len(rows) < 5:
        warns.append(f"[상온 공정일보 {tab_title}] 행 수가 너무 적어 파싱할 수 없습니다.")
        return None
    prod_date_str = tab_title
    for c in rows[1][:18]:
        if "생 산 일" in str(c) or "202" in str(c):
            prod_date_str = str(c).replace("생 산 일 :", "").strip()
            break

    lines = []
    current_ho = ""
    for r in rows[3:16]:
        r = r + [""] * (18 - len(r))
        ho_cell = str(r[0]).strip() or str(r[1]).strip()
        if "호기" in ho_cell and len(ho_cell) <= 5:
            current_ho = ho_cell
        p_c = [str(x).strip() for x in r[1:6]
               if str(x).strip() not in ["", "제 품 명", "제  품  명", current_ho]
               and not re.match(r"^202\d", str(x).strip()) and "확인" not in str(x)]
        e_c = [str(x).strip() for x in r[5:9] if re.search(r"202\d[\.\-]\s*\d{1,2}[\.\-]\s*\d{1,2}", str(x).strip())]
        t_c = [str(x).strip() for x in r[6:11] if re.search(r"\d{1,2}:\d{2}", str(x).strip()) or "확인" in str(x).strip()]
        p1, exp1, t1 = (p_c[0] if p_c else ""), (e_c[0] if e_c else ""), " ".join(t_c)
        if current_ho and (p1 or exp1):
            if re.search(r"\d{1,2}:\d{2}", t1):
                status = "🟢 확인시간 기입"
            elif p1:
                status = "🟡 확인시간 대기"
            else:
                status = "-"
            lines.append({
                "날짜탭": tab_title, "포장호기": current_ho,
                "생산 제품명": p1 or "-", "소비기한": exp1 or "-",
                "확인시간": t1 or "미기입", "모니터링 상태": status,
            })

    ccp = []
    for r in rows[15:23]:
        joined = " ".join(str(x).strip() for x in r[:12] if str(x).strip())
        if any(k in joined for k in ["농도", "분사량", "온도", "E빔"]):
            r = r + [""] * (15 - len(r))
            name = str(r[0]).strip() or str(r[1]).strip()
            std = " ".join(str(x).strip() for x in r[1:4] if str(x).strip() not in ["", name])
            val = " | ".join(str(x).strip() for x in r[4:14] if str(x).strip())
            ccp.append({"점검항목(CCP-3B)": name, "관리기준 및 대상": std, "측정/기록값": val or NO_DATA})

    ster = []
    current_ster = ""
    for r in rows[22:42]:
        r = r + [""] * (16 - len(r))
        s_ho = str(r[0]).strip() or str(r[1]).strip()
        if "호기" in s_ho and "포장" not in s_ho:
            current_ster = s_ho
        nums = [str(x).strip() for x in r[2:14] if str(x).strip() not in ["", "-"]]
        if current_ster and len(nums) >= 3 and any(re.search(r"\d{2,3}", x) for x in nums):
            ster.append({"멸균기": current_ster, "측정 기록 내역": " | ".join(nums)})

    issues = []
    for r in rows[4:]:
        if len(r) >= 29:
            dt_s = str(r[27]).strip()
            memo = " ".join(str(c).strip() for c in r[28:] if str(c).strip() and "전달(특이)" not in str(c))
            if dt_s or memo:
                issues.append({"기록일자": dt_s or tab_title, "특이사항 및 조치내역": memo})

    if not lines:
        warns.append(f"[상온 공정일보 {tab_title}] 호기별 생산 행을 읽지 못했습니다. 시트 구조를 확인하세요.")
    return {
        "tab_title": tab_title, "prod_date": prod_date_str,
        "df_lines": pd.DataFrame(lines), "df_ccp3b": pd.DataFrame(ccp),
        "df_ster": pd.DataFrame(ster), "df_issues": pd.DataFrame(list(reversed(issues))),
    }


def parse_dairy_pack_sheet(ws, line_label):
    rows = ws.get_all_values()
    products = []
    w_date = NO_DATA
    for r in rows[:4]:
        joined = " ".join(str(c) for c in r if str(c).strip())
        m = re.search(r"202\d[\.\-\s]+\d{1,2}[\.\-\s]+\d{1,2}", joined)
        if m:
            w_date = m.group(0)
            break
    item_keys = {
        "확인시간": "시작/확인시간", "소비기한": "소비기한/Tank", "Tank": "소비기한/Tank",
        "표시사항": "표시사항", "상부접착": "상부접착", "하부접착": "하부접착",
        "제품용량": "제품용량", "관능": "관능(5점법)",
    }
    for r_idx, r in enumerate(rows):
        first = str(r[0]).replace(" ", "").strip() if r else ""
        if "제품명" not in first:
            continue
        for col_i in range(1, len(r)):
            p_name = str(r[col_i]).replace("\n", " ").strip()
            if not p_name or p_name.replace(" ", "") == "제품명":
                continue
            rec = {"시작/확인시간": "-", "소비기한/Tank": "-", "표시사항": "-", "상부접착": "-",
                   "하부접착": "-", "제품용량": "-", "관능(5점법)": "-"}
            for sub_r in rows[r_idx + 1: min(r_idx + 16, len(rows))]:
                title = str(sub_r[0]).replace(" ", "").strip() if sub_r else ""
                val = str(sub_r[col_i]).strip() if col_i < len(sub_r) else ""
                if not val or val == "00.00":
                    continue
                for k, field in item_keys.items():
                    if k in title:
                        rec[field] = val
                        break
            active = rec["소비기한/Tank"] != "-" or rec["시작/확인시간"] != "-"
            products.append({
                "라인구분": line_label, "작성기준일": w_date,
                "가동상태": "🟢 금일가동" if active else "⚪ 대기",
                "제품명": p_name, **rec,
            })
    return pd.DataFrame(products), w_date


def parse_soy_worksheet(ws):
    rows = ws.get_all_values()
    if len(rows) < 15:
        raise SheetLoadError(f"두유 배양검사 일보 '{ws.title}' 탭의 행 수가 부족합니다.")

    def cj(row_i, a, b):
        if row_i >= len(rows):
            return ""
        return " ".join(str(c).strip() for c in rows[row_i][a:b] if str(c).strip())

    header = {
        "시트탭": ws.title,
        "포장기": cj(4, 2, 5) or NO_DATA,
        "용량(mL)": cj(4, 5, 7) or NO_DATA,
        "품목": " ".join(str(c).strip() for c in rows[5][:13] if str(c).strip() not in ["", "품목"]) or NO_DATA,
        "생산일": cj(7, 1, 6) or NO_DATA,
        "검사일": cj(8, 1, 6) or NO_DATA,
        "시작/종료": cj(9, 0, 12) or NO_DATA,
    }
    hourly = []
    for r in rows[13:37]:
        if len(r) >= 13 and ":" in str(r[0]):
            hourly.append({
                "시간대": str(r[0]).strip(),
                "가동/샘플링": " ".join(str(x).strip() for x in r[1:5] if str(x).strip()) or "-",
                "종료샘플": str(r[5]).strip() or "-",
                "Strip 체크": " ".join(str(x).strip() for x in r[6:9] if str(x).strip()) or "-",
                "Paper 체크": " ".join(str(x).strip() for x in r[9:12] if str(x).strip()) or "-",
                "비고": str(r[12]).strip(),
            })
    # 오염 수량: '오염'이 들어간 셀 뒤의 숫자를 시트에서 찾는다 (없으면 기록 없음)
    contam = NO_DATA
    for r in rows:
        for i, c in enumerate(r):
            if "오염" in str(c):
                nums = [str(x).strip() for x in r[i:] if re.fullmatch(r"\d+\s*개?", str(x).strip())]
                if nums:
                    contam = nums[0] if "개" in nums[0] else nums[0] + " 개"
                    break
        if contam != NO_DATA:
            break
    preview = pd.DataFrame([[str(c) for c in r[:14]] for r in rows[:14] if any(str(c).strip() for c in r)])
    return header, pd.DataFrame(hourly), contam, preview


@st.cache_data(ttl=300)
def load_process_all_data():
    warns = []

    # 1) 상온제품 공정 관리 일보
    sh_rt = open_sheet("process_rt")
    ws_t, ws_y, note_t = pick_today_yesterday(sh_rt)
    rt_today = parse_rt_process_worksheet(ws_t, warns)
    rt_yest = parse_rt_process_worksheet(ws_y, warns) if ws_y is not None else None
    if note_t:
        warns.append(note_t)
    if rt_yest is None:
        warns.append("전일 탭을 찾지 못했습니다.")

    # 2) 유제품 포장 공정관리 일보
    sh_milk = open_sheet("process_milk")
    df_milk, df_ferm, milk_date = pd.DataFrame(), pd.DataFrame(), NO_DATA
    for w in sh_milk.worksheets():
        t = w.title.strip()
        if t in ["우유", "우유 포장일보 (복사용)"] and df_milk.empty:
            df_milk, milk_date = parse_dairy_pack_sheet(w, "우유 포장공정")
        elif t in ["발효유", "발효유 포장일보(복사용)"] and df_ferm.empty:
            df_ferm, _ = parse_dairy_pack_sheet(w, "발효유 포장공정")
    if df_milk.empty:
        warns.append("우유 포장일보 탭('우유')에서 제품을 읽지 못했습니다.")
    if df_ferm.empty:
        warns.append("발효유 포장일보 탭('발효유')에서 제품을 읽지 못했습니다.")

    # 3) 두유 배양검사 일보 (전일 작성 규칙: 전일 탭 우선)
    sh_soy = open_sheet("process_soy")
    s_t, s_y, s_note = pick_today_yesterday(sh_soy)
    target = s_y if s_y is not None else s_t
    soy_header, df_soy_hourly, soy_contam, soy_preview = parse_soy_worksheet(target)

    return {
        "rt_today": rt_today, "rt_yest": rt_yest,
        "milk_date": milk_date, "df_milk_pack": df_milk, "df_ferm_pack": df_ferm,
        "soy_tab": target.title, "soy_header": soy_header, "soy_contam": soy_contam,
        "df_soy_hourly": df_soy_hourly, "soy_preview": soy_preview,
        "warnings": warns,
    }


# ---------------------- 협력업체 ----------------------
def _find_header_row(rows, keyword, limit=15):
    for i, r in enumerate(rows[:limit]):
        if any(keyword in str(c).replace(" ", "") for c in r):
            return i
    return None


@st.cache_data(ttl=300)
def load_supplier_data():
    """시트2(구분/업체명/품목 = 전체 대상 업체) + 시트1(점수)을 업체명으로 매칭. 점수 없으면 미제출."""
    sh = open_sheet("supplier")
    rows1 = sh.get_worksheet(0).get_all_values()
    h1 = _find_header_row(rows1, "업체")
    if h1 is None:
        raise SheetLoadError(f"협력업체 시트1에서 '업체' 헤더 행을 찾지 못했습니다. 첫 행: {rows1[:2]}")
    hdr1 = [str(c).strip() for c in rows1[h1]]
    n1 = find_col(hdr1, ["업체명", "업체"])
    s1 = find_col(hdr1, ["최종점수", "총점", "합계", "점수"])
    if s1 is None:
        raise SheetLoadError(f"협력업체 시트1에서 점수 컬럼을 찾지 못했습니다. 헤더: {hdr1}")
    score_map = {}
    for r in rows1[h1 + 1:]:
        if len(r) > max(n1, s1) and str(r[n1]).strip():
            score_map[normalize_comp_name(r[n1])] = str(r[s1]).strip()

    rows2 = sh.get_worksheet(1).get_all_values()
    h2 = _find_header_row(rows2, "업체")
    h2 = 0 if h2 is None else h2
    hdr2 = [str(c).strip() for c in rows2[h2]]
    g_i = find_col(hdr2, ["구분"]) if find_col(hdr2, ["구분"]) is not None else 0
    n_i = find_col(hdr2, ["업체명"]) if find_col(hdr2, ["업체명"]) is not None else 1
    p_i = find_col(hdr2, ["품목"]) if find_col(hdr2, ["품목"]) is not None else 2

    recs, matched = [], set()
    for r in rows2[h2 + 1:]:
        r = r + [""] * 3
        name = str(r[n_i]).strip()
        if not name:
            continue
        key = normalize_comp_name(name)
        raw = score_map.get(key, "")
        score = to_float(raw, default=np.nan) if raw != "" else np.nan
        if key in score_map:
            matched.add(key)
        if pd.isna(score):
            result, note = "등급 외", "미제출"
        elif score >= 85:
            result, note = "승인", ""
        elif score >= 70:
            result, note = "지도", ""
        else:
            result, note = "등급 외", "복수거래, 거래중지 등 검토"
        recs.append({"구분": str(r[g_i]).strip(), "업체명": name, "품목": str(r[p_i]).strip(),
                     "점수": score, "결과": result, "비고": note})
    if not recs:
        raise SheetLoadError("협력업체 시트2에서 업체 목록을 읽지 못했습니다.")
    df = pd.DataFrame(recs)
    df.insert(0, "NO", range(1, len(df) + 1))
    unmatched = [k for k in score_map if k not in matched]
    return df, unmatched


# ---------------------- 표시사항 ----------------------
def parse_sheet_date(val):
    """시트 값(시리얼 번호 또는 날짜 문자열) → (일자, 연도, 월). 해석 불가면 '일자미상' (추정하지 않음)"""
    s = str(val).strip()
    if re.match(r"^\d{5}(\.\d+)?$", s):
        try:
            dt = datetime(1899, 12, 30) + timedelta(days=float(s))
            return dt.strftime("%Y-%m-%d"), f"{dt.year}년", f"{dt.month}월"
        except Exception:
            pass
    if s and "###" not in s:
        dt = pd.to_datetime(s, errors="coerce")
        if pd.notna(dt) and 2020 <= dt.year <= 2035:
            return dt.strftime("%Y-%m-%d"), f"{dt.year}년", f"{dt.month}월"
    return "일자미상", "일자미상", "일자미상"


def classify_label_status(status_str):
    s = str(status_str).strip()
    if s == "식품안전팀 검토중":
        return "식품안전팀 검토중"
    if s in ["개시/준비", "보류", "검토/개시", ""]:
        return "제외(개시/준비·보류)"
    return "검토완료(확인필)"


@st.cache_data(ttl=300)
def load_label_status_data():
    sh = open_sheet("label_status")
    ws = sh.get_worksheet(0)
    try:
        # 셀 너비로 인한 ####### 방지 (날짜가 시리얼 번호로 옴)
        rows = ws.get_all_values(value_render_option="UNFORMATTED_VALUE")
    except TypeError:
        rows = ws.get_all_values()
    if len(rows) < 2:
        raise SheetLoadError("표시사항 현황 시트에 데이터가 없습니다.")
    headers = [str(h).strip() for h in rows[0]]
    for need in ["상태", "제목"]:
        if need not in headers:
            raise SheetLoadError(f"표시사항 현황 시트에 '{need}' 컬럼이 없습니다. 헤더: {headers}")
    data = []
    for r in rows[1:]:
        if not any(str(c).strip() for c in r):
            continue
        r_pad = [str(x).strip() for x in r] + [""] * (len(headers) - len(r))
        data.append(dict(zip(headers, r_pad[:len(headers)])))
    df = pd.DataFrame(data)
    df["분류"] = df["상태"].apply(classify_label_status)
    parsed = [parse_sheet_date(v) for v in df["등록일"]] if "등록일" in df.columns else [("일자미상",) * 3] * len(df)
    df["등록일자"] = [p[0] for p in parsed]
    df["등록연도"] = [p[1] for p in parsed]
    df["등록월"] = [p[2] for p in parsed]
    return df


@st.cache_data(ttl=300)
def load_raw_material_label_db():
    sh = open_sheet("raw_label_db")
    rows = sh.get_worksheet(0).get_all_values()
    df_sub = pd.DataFrame()
    if len(rows) >= 2:
        headers = [h.strip() for h in rows[0]]
        data = [dict(zip(headers, (r + [""] * len(headers))[:len(headers)])) for r in rows[1:] if any(r)]
        df_sub = pd.DataFrame(data)
    try:
        rows_m = sh.worksheet("전체 원재료 명단").get_all_values()
    except Exception as e:
        raise SheetLoadError(f"'원자재 표시사항 DB'에서 '전체 원재료 명단' 탭을 열 수 없습니다: {repr(e)}")
    master_cnt = len([r for r in rows_m[1:] if any(r)])
    return df_sub, master_cnt


# ==============================================================================
# 5. Gemini 브리핑 (시트 기반 요약 문자열만 입력)
# ==============================================================================
@st.cache_data(ttl=600)
def generate_ax_executive_briefing(summary_text):
    api_key = st.secrets.get("GEMINI_API_KEY", "")
    if GENAI_AVAILABLE and api_key and not str(api_key).startswith("여기에"):
        try:
            client = genai.Client(api_key=api_key)
            prompt = (
                "당신은 연세유업 아산공장 품질안전부문의 AX 데이터 분석 AI입니다. "
                "아래 KPI 요약 수치만 인용하고 추정하지 말고, 양호한 지표와 주의가 필요한 지표를 2문장 이내로 브리핑하세요.\n\n"
                f"{summary_text}"
            )
            res = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
            if res and res.text:
                return res.text.strip()
        except Exception:
            pass
    return summary_text


def draw_mini_bar(target_val, actual_val, suffix="", bar_labels=("목표", "실적")):
    fig = go.Figure()
    for lab, val, color in [(bar_labels[0], target_val, "#7F7F7F"), (bar_labels[1], actual_val, "#ED7D31")]:
        fig.add_trace(go.Bar(x=[lab], y=[val], text=[f"{val}{suffix}"], textposition="inside",
                             insidetextanchor="end", marker_color=color, width=0.35,
                             textfont=dict(color="white", size=12)))
    mx = max(target_val, actual_val)
    fig.update_layout(
        height=150, margin=dict(l=15, r=15, t=6, b=20),
        paper_bgcolor="#F2F2F2", plot_bgcolor="#F2F2F2", showlegend=False,
        xaxis=dict(showgrid=False, zeroline=False, tickfont=dict(size=12, color="#222222")),
        yaxis=dict(showgrid=False, zeroline=True, zerolinecolor="#D9D9D9", showticklabels=False,
                   range=[0, mx * 1.28 if mx > 0 else 10]),
    )
    return fig


def kpi_card(title, lines_html, signal, unit="", min_height=None):
    style = f' style="min-height:{min_height}px;"' if min_height else ""
    unit_html = f'<div class="unit-label">{unit}</div>' if unit else ""
    st.markdown(f"""
    <div class="kpi-card">
        <div class="kpi-header">{title}</div>
        <div class="kpi-body"{style}>{get_signal_dot_html(signal)}{lines_html}</div>
        {unit_html}
    </div>""", unsafe_allow_html=True)


def bullet(text):
    return f'<div><span class="kpi-bullet">●</span><b>{text}</b></div>'


def need_setting(name):
    return f'<div class="ai-line">⚙️ Secrets [kpi]에 {name} 설정 필요</div>'


# ==============================================================================
# 6. 전체 데이터 로드 (하나라도 실패하면 원인을 모두 표시하고 중단)
# ==============================================================================
load_errors = []


def run_loader(name, fn):
    try:
        return fn()
    except Exception as e:
        load_errors.append(f"**[{name}]** {type(e).__name__}: {e}")
        return None


_cost = run_loader("원가절감", load_cost_data)
_claim = run_loader("클레임", load_claim_data)
_proc = run_loader("공정일보", load_process_all_data)
_sup = run_loader("협력업체", load_supplier_data)
_label = run_loader("표시사항 현황", load_label_status_data)
_raw = run_loader("원자재 표시사항 DB", load_raw_material_label_db)

if load_errors:
    st.error("🚨 구글 시트 연동 실패 - 코드 내 임시 데이터는 사용하지 않습니다. 아래 원인을 해결해야 대시보드가 표시됩니다.")
    for msg in load_errors:
        st.markdown(f"- {msg}")
    if st.button("🔄 다시 시도"):
        st.cache_data.clear()
        st.cache_resource.clear()
        st.rerun()
    st.stop()

df_cost = _cost
df_claim_trend, df_claim_cat = _claim
proc_data = _proc
df_sup, sup_unmatched = _sup
df_label_status = _label
df_raw_sub, raw_master_cnt = _raw

# ==============================================================================
# 7. 지표 계산 (전부 시트 값 기반, 목표 중 시트에 없는 것은 Secrets [kpi])
# ==============================================================================
# [1] 원가절감: 목표 = 시트의 월별 '기준' 합계
cost_target_man = df_cost["부문_기준(만원)"].sum()
cost_target_uk = round(cost_target_man / 10000, 2)
cost_actual_man = df_cost["부문_실적(만원)"].sum()
cost_actual_uk = round(cost_actual_man / 10000, 2)
cost_rate = round(cost_actual_uk / cost_target_uk * 100, 1) if cost_target_uk > 0 else 0.0
cost_trend_vals, cost_slope, cost_months_cnt = calc_linear_trend_and_forecast(df_cost["부문_실적(만원)"].tolist())
cost_projected_man = cost_actual_man + sum(cost_trend_vals[cost_months_cnt:]) if cost_months_cnt < 12 else cost_actual_man
cost_projected_uk = round(cost_projected_man / 10000, 2)
if cost_actual_uk >= cost_target_uk or cost_projected_uk >= cost_target_uk:
    sig_cost = "green" if cost_slope >= 0 else "yellow"
    ai_cost_msg = f"AI 예측 : 연말 {cost_projected_uk}억 예상 (목표 달성권)"
else:
    sig_cost = "red"
    ai_cost_msg = f"AI 예측 : 연말 {cost_projected_uk}억 예상 (월 추세 {cost_slope:+.1f}만)"

# [2] 클레임
claim_target_ppm = kpi_setting("claim_target_ppm")
row_26 = df_claim_cat[(df_claim_cat["연도"] == "2026년") & (df_claim_cat["유형"] == "합계")]
claim_actual_ppm = float(row_26["합계_PPM"].values[0])
claim_total_cnt = int(row_26["합계_건수"].values[0])
claim_trend_vals, claim_slope, _ = calc_linear_trend_and_forecast(df_claim_trend["2026년_PPM"].tolist())
if claim_target_ppm is None:
    sig_claim, ai_claim_msg = "gray", "목표 ppm 미설정"
elif claim_actual_ppm > claim_target_ppm:
    sig_claim, ai_claim_msg = "red", f"AI 경고 : 누적 {claim_actual_ppm}ppm (목표 초과)"
elif claim_slope > 0.03:
    sig_claim, ai_claim_msg = "yellow", f"AI 주의 : 목표 이내이나 월 추세 상승({claim_slope:+.2f}ppm/월)"
else:
    sig_claim, ai_claim_msg = "green", f"AI 양호 : 목표 이내 안정 추세 ({claim_actual_ppm}ppm)"

# [3] 공정
rt_t = proc_data["rt_today"]
rt_y = proc_data["rt_yest"]
lines_t = rt_t["df_lines"] if rt_t else pd.DataFrame()
if not lines_t.empty:
    active_rt_cnt = int((lines_t["생산 제품명"].astype(str).str.strip() != "-").sum())
    waiting_rt_cnt = int(lines_t["모니터링 상태"].astype(str).str.contains("대기").sum())
else:
    active_rt_cnt, waiting_rt_cnt = 0, 0
df_milk, df_ferm = proc_data["df_milk_pack"], proc_data["df_ferm_pack"]
active_milk_cnt = int(df_milk["가동상태"].str.contains("가동").sum()) if not df_milk.empty else 0
active_ferm_cnt = int(df_ferm["가동상태"].str.contains("가동").sum()) if not df_ferm.empty else 0
soy_contam = proc_data["soy_contam"]
soy_contam_num = re.search(r"\d+", soy_contam)
proc_warns = proc_data["warnings"]

if soy_contam_num and int(soy_contam_num.group()) > 0:
    sig_process, ai_proc_msg = "red", f"AI 경고 : 두유 배양 오염 {soy_contam}"
elif waiting_rt_cnt > 0:
    sig_process, ai_proc_msg = "yellow", f"AI 점검 : 확인시간 미기입 {waiting_rt_cnt}건"
elif not soy_contam_num or proc_warns:
    sig_process, ai_proc_msg = "yellow", "AI 점검 : 일부 시트 항목 확인 필요 (상세 화면 경고 참고)"
else:
    sig_process, ai_proc_msg = "green", "AI 판정 : 확인시간 미기입·오염 없음"

# [4] 협력업체
total_suppliers = len(df_sup)
unsubmitted_cnt = int(df_sup["점수"].isna().sum())
submitted_cnt = total_suppliers - unsubmitted_cnt
supplier_exec_rate = round(submitted_cnt / total_suppliers * 100, 1) if total_suppliers else 0.0
supplier_target = kpi_setting("supplier_exec_target")
grade_cnt = df_sup["결과"].value_counts().to_dict()
if supplier_target is None:
    sig_supplier = "gray"
else:
    sig_supplier = "green" if supplier_exec_rate >= supplier_target else "red"
ai_sup_msg = (f"AI 분석 : 승인 {grade_cnt.get('승인', 0)} / 지도 {grade_cnt.get('지도', 0)} / "
              f"등급외 {grade_cnt.get('등급 외', 0)} (미제출 {unsubmitted_cnt}개사)")

# [5] 심사점수
audit_target = kpi_setting("audit_target")
audit_actual = kpi_setting("audit_actual")
if audit_target is None or audit_actual is None:
    sig_audit = "gray"
else:
    sig_audit = "green" if audit_actual >= audit_target else "red"

# [6] 표시사항 진행
df_reviewing = df_label_status[df_label_status["분류"] == "식품안전팀 검토중"]
reviewing_cnt = len(df_reviewing)
completed_cnt = int((df_label_status["분류"] == "검토완료(확인필)").sum())
rep_titles = df_reviewing["제목"].head(4).tolist()
sig_label = "yellow" if reviewing_cnt >= 5 else "green"

# [7] 원자재 DB
sub_cnt = len(df_raw_sub)
verified_cnt = (int(df_raw_sub["검증상태"].astype(str).str.contains("완료|적합", na=False).sum())
                if "검증상태" in df_raw_sub.columns else 0)
allergy_chg_cnt = (int((df_raw_sub["신규알레르기"].astype(str).str.strip() != "").sum())
                   if "신규알레르기" in df_raw_sub.columns else 0)
sig_raw = "yellow" if allergy_chg_cnt > 0 else "green"

# ==============================================================================
# [화면 1] 메인 Summary
# ==============================================================================
if st.session_state.current_view == "main":
    c1, c2 = st.columns([8.5, 1.5])
    with c1:
        st.markdown("""<div class="main-title"><span>2026 업적 KPI 현황판_품질안전부문 (AX 스마트 대시보드)</span>
            <span style="font-size:20px;">Summary</span></div>""", unsafe_allow_html=True)
    with c2:
        if st.button("🔄 시트 실시간 동기화"):
            st.cache_data.clear()
            st.rerun()

    now = now_kst()
    st.markdown(f"<div class='sub-date'>(기준 : {now:%Y. %m. %d} | 구글 시트 조회 {now:%H:%M:%S} | 신호등: 🟢양호 🟡주의 🔴경고 ⚪판정불가)</div>",
                unsafe_allow_html=True)

    for w in proc_warns:
        st.warning(f"공정 시트 안내: {w}")
    if sup_unmatched:
        st.warning(f"협력업체 시트1 점수 중 시트2 대상 목록과 업체명이 매칭되지 않은 항목 {len(sup_unmatched)}건: "
                   f"{', '.join(sup_unmatched[:8])}{' ...' if len(sup_unmatched) > 8 else ''}")

    claim_goal_txt = f"목표 {claim_target_ppm}ppm" if claim_target_ppm is not None else "목표 미설정"
    summary = (
        f"[원가절감] 누적 {cost_actual_uk}억원({cost_rate}% 달성), 추세선 기준 연말 {cost_projected_uk}억원 예상 | "
        f"[클레임] 누적 {claim_actual_ppm}ppm ({claim_goal_txt}), 월 추세 {claim_slope:+.2f}ppm | "
        f"[공정] 금일({rt_t['tab_title'] if rt_t else '-'}) 상온 {active_rt_cnt}개 호기 가동, 확인시간 미기입 {waiting_rt_cnt}건, 두유 배양 오염 {soy_contam} | "
        f"[협력업체] {total_suppliers}개사 중 {submitted_cnt}개사 제출({supplier_exec_rate}%) | "
        f"[표시사항] 검토완료 {completed_cnt}건, 식품안전팀 검토중 {reviewing_cnt}건"
    )
    st.markdown(f"""<div class="ax-banner"><b>🤖 AX(AI 전환) 품질안전 실시간 종합 브리핑</b><br>
        {generate_ax_executive_briefing(summary)}</div>""", unsafe_allow_html=True)

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        kpi_card("1. 원가 절감",
                 bullet(f"목표 : {cost_target_uk}억원 이상") + bullet(f"실적 : {cost_actual_uk}억원 ({cost_rate}% 달성)")
                 + f'<div class="ai-line">📈 {ai_cost_msg}</div>', sig_cost, "(단위 : 억원)")
        st.plotly_chart(draw_mini_bar(cost_target_uk, cost_actual_uk), use_container_width=True, config={"displayModeBar": False})
        if st.button("🔍 1. 원가 절감 상세", key="btn_cost"):
            set_view("cost"); st.rerun()

    with col2:
        tgt_line = bullet(f"목표 : {claim_target_ppm} ppm이하") if claim_target_ppm is not None else need_setting("claim_target_ppm")
        kpi_card("2. 클레임 발생률",
                 tgt_line + bullet(f"실적 : {claim_actual_ppm} ppm (총 {claim_total_cnt:,}건)")
                 + f'<div class="ai-line">📈 {ai_claim_msg}</div>', sig_claim, "(단위 : ppm)")
        if claim_target_ppm is not None:
            st.plotly_chart(draw_mini_bar(claim_target_ppm, claim_actual_ppm), use_container_width=True, config={"displayModeBar": False})
        if st.button("🔍 2. 클레임 상세", key="btn_claim"):
            set_view("claim"); st.rerun()

    with col3:
        tab_lbl = rt_t["tab_title"] if rt_t else "-"
        yest_lbl = rt_y["tab_title"] if rt_y else "탭 없음"
        kpi_card("3. 공정 현황 및 특이사항",
                 bullet(f"금일({tab_lbl}) 상온 가동 {active_rt_cnt}개 호기 / 유제품 {active_milk_cnt + active_ferm_cnt}품목")
                 + bullet(f"두유 배양({proc_data['soy_tab']}) 오염 : {soy_contam}")
                 + bullet(f"전일 탭 : {yest_lbl}")
                 + f'<div class="ai-line">🏭 {ai_proc_msg}</div>', sig_process, "(단위 : 호기/품목)")
        st.plotly_chart(draw_mini_bar(active_rt_cnt + active_milk_cnt, (active_rt_cnt - waiting_rt_cnt) + active_milk_cnt,
                                      bar_labels=("금일가동", "확인기입")), use_container_width=True, config={"displayModeBar": False})
        if st.button("🔍 3. 공정 실시간 관제 상세", key="btn_process"):
            set_view("process"); st.rerun()

    with col4:
        tgt_line = bullet(f"목표 : 실행률 {supplier_target}% 이상 (대상 {total_suppliers}개사)") if supplier_target is not None else need_setting("supplier_exec_target")
        kpi_card("4. 협력업체 관리",
                 tgt_line + bullet(f"실적 : {supplier_exec_rate}% ({submitted_cnt}개사 제출 / 미제출 {unsubmitted_cnt})")
                 + f'<div class="ai-line">📊 {ai_sup_msg}</div>', sig_supplier, "(단위 : %)")
        if supplier_target is not None:
            st.plotly_chart(draw_mini_bar(supplier_target, supplier_exec_rate, suffix="%"), use_container_width=True, config={"displayModeBar": False})
        if st.button("🔍 4. 협력업체 서류심사 상세", key="btn_supplier"):
            set_view("supplier"); st.rerun()

    col5, col6, col7 = st.columns([1, 1.5, 1.5])
    with col5:
        if audit_target is None or audit_actual is None:
            body = need_setting("audit_target / audit_actual")
        else:
            gap = round(audit_target - audit_actual, 2)
            body = bullet(f"목표 : {audit_target}점 이상") + bullet(f"실적 : {audit_actual}점")
            body += f'<div class="ai-line">{"⚠️ 목표 대비 -" + str(gap) + "점 보완 필요" if gap > 0 else "✅ 목표 달성"}</div>'
        kpi_card("5. 심사점수", body, sig_audit, "(단위 : 점)")
        if audit_target is not None and audit_actual is not None:
            st.plotly_chart(draw_mini_bar(audit_target, audit_actual), use_container_width=True, config={"displayModeBar": False})
        if st.button("🔍 5. 심사점수 상세", key="btn_audit"):
            set_view("audit"); st.rerun()

    with col6:
        rep_html = "".join(f"<div>• {t[:42]}{'...' if len(t) > 42 else ''}</div>" for t in rep_titles) or "<div>• 현재 검토 대기 중인 품목 없음</div>"
        kpi_card("6. 표시사항 진행 현황",
                 bullet(f"검토 완료(확인필) : 누적 {completed_cnt:,}건 (개시/준비·보류 제외)")
                 + f'<div><span class="kpi-bullet">●</span><b style="color:#C00000;">현재 식품안전팀 검토중 : {reviewing_cnt:,}건</b> (전체 등록 {len(df_label_status):,}건)</div>'
                 + f'<div class="rep-list-box"><b>📌 현재 식품안전팀 검토중 대표 제품명</b>{rep_html}</div>',
                 sig_label, min_height=280)
        if st.button("🔍 6. 표시사항 진행 상세", key="btn_label_status"):
            set_view("label_status"); st.rerun()

    with col7:
        kpi_card("7. 표시사항 특이사항 (원재료 DB 현황)",
                 bullet(f"원재료 표시사항 DB 등록 : {sub_cnt:,}건 (전체 명단 {raw_master_cnt:,}건)")
                 + bullet(f"검증 완료 : {verified_cnt:,}건 / 신규 알레르기 체크 : {allergy_chg_cnt:,}건"),
                 sig_raw, min_height=280)
        if st.button("🔍 7. 표시사항 특이사항 상세", key="btn_label_issue"):
            set_view("label_issue"); st.rerun()

# ==============================================================================
# [화면 2] 상세 화면
# ==============================================================================
else:
    if st.button("⬅️ 전체 Summary 현황판으로 돌아가기"):
        set_view("main"); st.rerun()
    view = st.session_state.current_view

    # ---------------- 1. 원가절감 ----------------
    if view == "cost":
        st.markdown("<div class='main-title'>1. 원가 절감 - 월별/팀별 세부 집계 및 AX 추세 예측</div>", unsafe_allow_html=True)
        fs_sum = df_cost["식품안전팀_실적(만원)"].sum()
        qc_sum = df_cost["품질관리팀_실적(만원)"].sum()
        fs_tar = df_cost["식품안전팀_기준(만원)"].sum()
        qc_tar = df_cost["품질관리팀_기준(만원)"].sum()
        m1, m2, m3, m4 = st.columns(4)
        m1.metric(f"품질안전부문 누적 (목표 {cost_target_uk}억)", f"{cost_actual_man:,.1f} 만원 ({cost_actual_uk}억)", f"달성률 {cost_rate}%")
        m2.metric(f"식품안전팀 누적 (목표 {fs_tar:,.0f}만)", f"{fs_sum:,.1f} 만원", f"달성률 {round(fs_sum / fs_tar * 100, 1) if fs_tar else 0}%")
        m3.metric(f"품질관리팀 누적 (목표 {qc_tar:,.0f}만)", f"{qc_sum:,.1f} 만원", f"달성률 {round(qc_sum / qc_tar * 100, 1) if qc_tar else 0}%")
        m4.metric("AX 연말(2월말) 마감 예상치", f"{cost_projected_man:,.1f} 만원 ({cost_projected_uk}억)", f"월 추세 기울기 {cost_slope:+.1f}만")

        fig = go.Figure()
        fig.add_trace(go.Bar(x=df_cost["월"], y=df_cost["식품안전팀_실적(만원)"], name="식품안전팀 실적", marker_color="#2E75B6", text=df_cost["식품안전팀_실적(만원)"], textposition="auto"))
        fig.add_trace(go.Bar(x=df_cost["월"], y=df_cost["품질관리팀_실적(만원)"], name="품질관리팀 실적", marker_color="#ED7D31", text=df_cost["품질관리팀_실적(만원)"], textposition="auto"))
        fig.add_trace(go.Scatter(x=df_cost["월"], y=df_cost["부문_기준(만원)"], name="부문 월 목표 기준", mode="lines", line=dict(color="#C00000", width=2.5, dash="dash")))
        fig.add_trace(go.Scatter(x=df_cost["월"], y=cost_trend_vals, name="AX 선형회귀 추세선", mode="lines+markers", line=dict(color="#7030A0", width=3, dash="dot")))
        fig.update_layout(barmode="stack", height=420, title="📊 원가절감 월별 실적 및 AX 추세선 (단위: 만원)", margin=dict(t=50, b=20))
        st.plotly_chart(fig, use_container_width=True)
        st.subheader("📋 원가절감 월별 상세 데이터")
        st.dataframe(df_cost, use_container_width=True, hide_index=True)

    # ---------------- 2. 클레임 ----------------
    elif view == "claim":
        st.markdown("<div class='main-title'>2. 클레임 발생률 - 부문별 월단위 분석 / 연간 추이 / 유형별 상세</div>", unsafe_allow_html=True)
        tab1, tab2, tab3 = st.tabs(["🏭 부문별 월단위 분석", "📈 전사 월별 PPM·건수 (2025 vs 2026)", "🥛 유형별 상세 집계표"])

        with tab1:
            k1, k2 = st.columns([1.2, 2])
            div_year = k1.radio("조회 연도", ["2026년", "2025년"], horizontal=True, key="div_yr")
            div_sel = k2.radio("조회 부문", ["🥛 유제품생산부문", "🧃 상온제품부문", "⚖️ 양 부문 비교"], horizontal=True, key="div_type")
            df_dm, df_dr = build_division_claim_df(df_claim_cat, div_year, DAIRY_CATEGORIES)
            df_rm, df_rr = build_division_claim_df(df_claim_cat, div_year, RT_CATEGORIES)

            if "비교" not in div_sel:
                if "유제품" in div_sel:
                    tdf, traw, cats, title = df_dm, df_dr, DAIRY_CATEGORIES, f"{div_year} 유제품생산부문"
                else:
                    tdf, traw, cats, title = df_rm, df_rr, RT_CATEGORIES, f"{div_year} 상온제품부문"
                tc, tp = tdf["합산_건수"].sum(), tdf["합산_생산수량"].sum()
                tppm = round(tc / tp * 1_000_000, 2) if tp > 0 else 0.0
                d_trend, d_slope, _ = calc_linear_trend_and_forecast(tdf["부문_통합_PPM"].tolist())
                a, b, c, d = st.columns(4)
                a.metric("누적 클레임 건수", f"{tc:,} 건")
                b.metric("누적 생산수량", f"{tp:,} 개")
                c.metric("부문 통합 PPM", f"{tppm} ppm")
                d.metric("PPM 월 추세 기울기", f"{d_slope:+.2f} ppm/월", "상승 주의" if d_slope > 0.03 else "안정 추세")

                fig = make_subplots(specs=[[{"secondary_y": True}]])
                palette = ["#2E75B6", "#5B9BD5", "#ED7D31", "#F4B183"]
                for i, cat in enumerate(cats):
                    fig.add_trace(go.Bar(x=tdf["월"], y=tdf[f"{cat}_건수"], name=f"{cat} (건수)", marker_color=palette[i % 4]), secondary_y=False)
                fig.add_trace(go.Scatter(x=tdf["월"], y=tdf["부문_통합_PPM"], name="부문 통합 PPM", mode="lines+markers+text", text=tdf["부문_통합_PPM"], textposition="top center", line=dict(color="#C00000", width=3)), secondary_y=True)
                fig.add_trace(go.Scatter(x=tdf["월"], y=d_trend, name="AX PPM 추세선", mode="lines", line=dict(color="#7030A0", width=2.5, dash="dot")), secondary_y=True)
                fig.update_layout(barmode="stack", height=420, title=f"📊 {title} 월단위 건수 및 통합 PPM", margin=dict(t=50, b=20))
                fig.update_yaxes(title_text="클레임 건수", secondary_y=False)
                fig.update_yaxes(title_text="PPM", secondary_y=True)
                st.plotly_chart(fig, use_container_width=True)
                st.dataframe(tdf, use_container_width=True, hide_index=True)
                st.dataframe(traw, use_container_width=True, hide_index=True)
            else:
                fig = make_subplots(specs=[[{"secondary_y": True}]])
                fig.add_trace(go.Bar(x=df_dm["월"], y=df_dm["합산_건수"], name="유제품생산부문 건수", marker_color="#2E75B6"), secondary_y=False)
                fig.add_trace(go.Bar(x=df_rm["월"], y=df_rm["합산_건수"], name="상온제품부문 건수", marker_color="#ED7D31"), secondary_y=False)
                fig.add_trace(go.Scatter(x=df_dm["월"], y=df_dm["부문_통합_PPM"], name="유제품 PPM", mode="lines+markers", line=dict(color="#002060", width=3)), secondary_y=True)
                fig.add_trace(go.Scatter(x=df_rm["월"], y=df_rm["부문_통합_PPM"], name="상온 PPM", mode="lines+markers", line=dict(color="#C00000", width=3)), secondary_y=True)
                fig.update_layout(barmode="group", height=420, title=f"📊 {div_year} 부문 비교 (건수 및 PPM)")
                st.plotly_chart(fig, use_container_width=True)

        with tab2:
            fig = go.Figure()
            fig.add_trace(go.Bar(x=df_claim_trend["월"], y=df_claim_trend["2025년_PPM"], name="2025년 PPM", marker_color="#A6A6A6", text=df_claim_trend["2025년_PPM"], textposition="outside"))
            fig.add_trace(go.Bar(x=df_claim_trend["월"], y=df_claim_trend["2026년_PPM"], name="2026년 PPM", marker_color="#ED7D31", text=df_claim_trend["2026년_PPM"], textposition="outside"))
            if claim_target_ppm is not None:
                fig.add_trace(go.Scatter(x=df_claim_trend["월"], y=df_claim_trend["목표_PPM"], name=f"목표 ({claim_target_ppm} ppm)", mode="lines", line=dict(color="#C00000", width=2.5, dash="dash")))
            fig.add_trace(go.Scatter(x=df_claim_trend["월"], y=claim_trend_vals, name="2026 AX 추세선", mode="lines+markers", line=dict(color="#7030A0", width=3, dash="dot")))
            fig.update_layout(barmode="group", height=420, title="📊 2025 vs 2026 월별 클레임 PPM 및 AX 추세선")
            st.plotly_chart(fig, use_container_width=True)
            st.dataframe(df_claim_trend, use_container_width=True, hide_index=True)

        with tab3:
            yr_sel = st.radio("조회 연도", ["2026년", "2025년", "전체"], horizontal=True, key="cat_yr")
            dfv = df_claim_cat if yr_sel == "전체" else df_claim_cat[df_claim_cat["연도"] == yr_sel]
            dfp = dfv[dfv["유형"] != "합계"]
            fig = go.Figure()
            for yv, col in [("2026년", "#ED7D31"), ("2025년", "#7F7F7F")]:
                sp = dfp[dfp["연도"] == yv]
                if not sp.empty:
                    fig.add_trace(go.Bar(x=sp["유형"], y=sp["합계_건수"], name=f"{yv} 건수", marker_color=col, text=sp["합계_건수"], textposition="auto"))
            fig.update_layout(barmode="group", height=360, title=f"📊 {yr_sel} 제품 유형별 누적 클레임 건수")
            st.plotly_chart(fig, use_container_width=True)
            st.dataframe(dfv, use_container_width=True, hide_index=True)

    # ---------------- 3. 공정 ----------------
    elif view == "process":
        st.markdown("<div class='main-title'>3. 공정 현황 및 특이사항 - 금일·전일 생산 현황 및 CCP 모니터링</div>", unsafe_allow_html=True)
        for w in proc_warns:
            st.warning(w)
        yest_title = rt_y["tab_title"] if rt_y else "없음"
        a, b, c, d = st.columns(4)
        a.metric(f"금일({rt_t['tab_title'] if rt_t else '-'}) 상온 가동", f"{active_rt_cnt} 개 호기", f"확인시간 대기 {waiting_rt_cnt}건" if waiting_rt_cnt else "전 호기 확인시간 기입")
        b.metric("전일 탭", yest_title)
        c.metric("유제품 포장 가동 품목", f"우유 {active_milk_cnt} / 발효유 {active_ferm_cnt}", f"기준일: {proc_data['milk_date']}")
        d.metric(f"두유 배양검사 ({proc_data['soy_tab']})", f"오염 {soy_contam}")

        t1, t2, t3 = st.tabs(["🧃 [상온] 상온제품 공정 관리 일보", "🥛 [우유/발효유] 유제품 포장 공정관리 일보", "🧪 [상온] 두유 배양검사 일보"])
        with t1:
            if rt_t:
                l, r = st.columns([1.3, 1])
                with l:
                    st.subheader(f"🟢 금일 [{rt_t['tab_title']}] 호기별 생산 제품·소비기한·확인시간 ({rt_t['prod_date']})")
                    st.dataframe(rt_t["df_lines"], use_container_width=True, hide_index=True)
                with r:
                    st.subheader(f"☑️ 전일 [{yest_title}]")
                    if rt_y:
                        st.dataframe(rt_y["df_lines"], use_container_width=True, hide_index=True)
                        if not rt_y["df_issues"].empty:
                            st.dataframe(rt_y["df_issues"], use_container_width=True, hide_index=True)
                    else:
                        st.info("전일 탭이 시트에 없습니다.")
                st.markdown("---")
                x, y = st.columns(2)
                with x:
                    st.subheader("🛡️ 포장기 공정관리 [CCP-3B]")
                    st.dataframe(rt_t["df_ccp3b"], use_container_width=True, hide_index=True)
                with y:
                    st.subheader("🔥 멸균기 공정관리 [CCP-1B / CCP-2P]")
                    st.dataframe(rt_t["df_ster"], use_container_width=True, hide_index=True)
                st.subheader("📋 전달(특이)사항 이력")
                st.dataframe(rt_t["df_issues"], use_container_width=True, hide_index=True)
            else:
                st.info("금일 상온 공정일보를 읽지 못했습니다.")
        with t2:
            s1, s2 = st.tabs(["🥛 우유", "🍶 발효유"])
            with s1:
                only = st.checkbox("가동 중인 품목만", key="chk_m")
                dfm = df_milk[df_milk["가동상태"].str.contains("가동")] if (only and not df_milk.empty) else df_milk
                st.dataframe(dfm, use_container_width=True, hide_index=True)
            with s2:
                only = st.checkbox("가동 중인 품목만", key="chk_f")
                dff = df_ferm[df_ferm["가동상태"].str.contains("가동")] if (only and not df_ferm.empty) else df_ferm
                st.dataframe(dff, use_container_width=True, hide_index=True)
        with t3:
            st.caption("※ 전일 작성 탭 기준. 생산량은 시트에 기록된 값만 표시하며 코드에서 추정하지 않습니다.")
            st.dataframe(pd.DataFrame([proc_data["soy_header"]]), use_container_width=True, hide_index=True)
            if not proc_data["df_soy_hourly"].empty:
                st.subheader("⏰ 시간대별 샘플링·Strip·Paper 기록")
                st.dataframe(proc_data["df_soy_hourly"], use_container_width=True, hide_index=True)
            with st.expander("시트 상단 원본 보기 (파싱 검증용)"):
                st.dataframe(proc_data["soy_preview"], use_container_width=True, hide_index=True)

    # ---------------- 4. 협력업체 ----------------
    elif view == "supplier":
        st.markdown("<div class='main-title'>4. 협력업체 관리 - 서류심사 결과</div>", unsafe_allow_html=True)
        st.subheader("📊 등급별 집계 및 조치 현황")
        df_g = pd.DataFrame([
            {"등급": "승인", "점수": "85-100점", "업체수": grade_cnt.get("승인", 0), "조치": "승인"},
            {"등급": "지도", "점수": "70-84점", "업체수": grade_cnt.get("지도", 0), "조치": "업체별 개선사항 피드백"},
            {"등급": "등급 외", "점수": "70점미만, 미제출", "업체수": grade_cnt.get("등급 외", 0), "조치": "복수거래, 거래중지 등 검토"},
            {"등급": "합계", "점수": "-", "업체수": total_suppliers, "조치": f"제출 {submitted_cnt}개사 ({supplier_exec_rate}%) / 미제출 {unsubmitted_cnt}개사"},
        ])
        st.dataframe(df_g, use_container_width=True, hide_index=True)

        st.subheader(f"📋 협력업체 서류심사 결과 전체 목록 ({total_suppliers}개사)")
        f1, f2, f3 = st.columns(3)
        gubun_opts = ["전체"] + sorted([g for g in df_sup["구분"].unique().tolist() if g])
        sel_g = f1.selectbox("구분 필터", gubun_opts)
        sel_r = f2.selectbox("결과 등급 필터", ["전체", "승인", "지도", "등급 외"])
        kw = f3.text_input("업체명 또는 품목 검색")
        dfv = df_sup.copy()
        if sel_g != "전체":
            dfv = dfv[dfv["구분"] == sel_g]
        if sel_r != "전체":
            dfv = dfv[dfv["결과"] == sel_r]
        if kw:
            dfv = dfv[dfv["업체명"].str.contains(kw, case=False, na=False) | dfv["품목"].str.contains(kw, case=False, na=False)]
        st.dataframe(dfv, use_container_width=True, hide_index=True, height=385)

        st.markdown("---")
        st.subheader("■ 등급 외 업체")
        st.dataframe(df_sup[df_sup["결과"] == "등급 외"], use_container_width=True, hide_index=True)
        if sup_unmatched:
            st.warning(f"시트1에는 있으나 시트2 대상 목록과 매칭되지 않은 업체명: {', '.join(sup_unmatched)}")

    # ---------------- 5. 심사점수 ----------------
    elif view == "audit":
        st.markdown("<div class='main-title'>5. 심사점수 - 내/외부 식품안전 및 품질 심사 평가 현황</div>", unsafe_allow_html=True)
        if audit_target is None or audit_actual is None:
            st.info("심사점수는 별도 시트가 없어 Secrets의 [kpi] audit_target / audit_actual 값을 사용합니다. 설정이 필요합니다.")
        else:
            st.dataframe(pd.DataFrame({
                "구분": ["연간 종합 목표", "현재 종합 실적"],
                "점수(점)": [audit_target, audit_actual],
                "비고": ["Secrets [kpi] audit_target", "Secrets [kpi] audit_actual"],
            }), use_container_width=True, hide_index=True)

    # ---------------- 6. 표시사항 진행 ----------------
    elif view == "label_status":
        st.markdown("<div class='main-title'>6. 표시사항 진행 현황 - 검토중 품목 및 연도·월별 완료 집계</div>", unsafe_allow_html=True)
        excluded_cnt = int((df_label_status["분류"] == "제외(개시/준비·보류)").sum())
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("시트 전체 등록 건수", f"{len(df_label_status):,} 건")
        k2.metric("🔴 식품안전팀 검토중", f"{reviewing_cnt:,} 건")
        k3.metric("🟢 누적 검토 완료(확인필)", f"{completed_cnt:,} 건")
        k4.metric("⚪ 개시/준비·보류 (집계제외)", f"{excluded_cnt:,} 건")

        cols_to_show = [c for c in ["*docNo", "상태", "제목", "요청부서", "대분류(마케팅 카테고리)", "보관방법", "생산처", "검토 포장재 유형", "등록일자", "최종수정자"] if c in df_label_status.columns]
        st.subheader(f"🔴 현재 [식품안전팀 검토중] ({reviewing_cnt}건)")
        r1, r2 = st.columns([2.2, 1])
        with r1:
            st.dataframe(df_reviewing[cols_to_show], use_container_width=True, hide_index=True)
        with r2:
            if "요청부서" in df_reviewing.columns and not df_reviewing.empty:
                g = df_reviewing.groupby("요청부서").size().reset_index(name="건수")
                fig = go.Figure(go.Bar(x=g["요청부서"], y=g["건수"], marker_color="#C00000", text=g["건수"], textposition="auto"))
                fig.update_layout(height=260, title="📌 요청부서별 검토중", margin=dict(t=40, b=10, l=10, r=10))
                st.plotly_chart(fig, use_container_width=True)

        st.markdown("---")
        df_valid = df_label_status[df_label_status["분류"] != "제외(개시/준비·보류)"]
        unknown_cnt = int((df_valid["등록연도"] == "일자미상").sum())
        if unknown_cnt:
            st.warning(f"등록일을 해석할 수 없어 연도/월 집계에서 '일자미상'으로 분리된 건: {unknown_cnt}건")

        y1, y2 = st.columns([1, 2])
        with y1:
            st.subheader("📊 연도별 건수")
            yr = df_valid.groupby(["등록연도", "분류"]).size().unstack(fill_value=0).reset_index()
            for col in ["검토완료(확인필)", "식품안전팀 검토중"]:
                if col not in yr.columns:
                    yr[col] = 0
            yr["합계"] = yr["검토완료(확인필)"] + yr["식품안전팀 검토중"]
            fig = go.Figure()
            fig.add_trace(go.Bar(x=yr["등록연도"], y=yr["검토완료(확인필)"], name="검토완료", marker_color="#44546A", text=yr["검토완료(확인필)"], textposition="auto"))
            fig.add_trace(go.Bar(x=yr["등록연도"], y=yr["식품안전팀 검토중"], name="검토중", marker_color="#ED7D31", text=yr["식품안전팀 검토중"], textposition="auto"))
            fig.update_layout(barmode="stack", height=320, margin=dict(t=25, b=10))
            st.plotly_chart(fig, use_container_width=True)
            st.dataframe(yr, use_container_width=True, hide_index=True)
        with y2:
            years = sorted([y for y in df_valid["등록연도"].unique().tolist() if y != "일자미상"], reverse=True)
            sel_y = st.radio("월별 집계 연도", ["전체 연도 합산"] + years, horizontal=True)
            base = df_valid if sel_y == "전체 연도 합산" else df_valid[df_valid["등록연도"] == sel_y]
            rows_m = []
            for m in CALENDAR_MONTHS:
                done = len(base[(base["등록월"] == m) & (base["분류"] == "검토완료(확인필)")])
                ing = len(base[(base["등록월"] == m) & (base["분류"] == "식품안전팀 검토중")])
                rows_m.append({"월": m, "검토완료(확인필)": done, "식품안전팀 검토중": ing, "월_합계": done + ing})
            dfm = pd.DataFrame(rows_m)
            fig = go.Figure()
            fig.add_trace(go.Bar(x=dfm["월"], y=dfm["검토완료(확인필)"], name="검토완료", marker_color="#2E75B6", text=dfm["검토완료(확인필)"], textposition="auto"))
            fig.add_trace(go.Bar(x=dfm["월"], y=dfm["식품안전팀 검토중"], name="검토중", marker_color="#ED7D31", text=dfm["식품안전팀 검토중"], textposition="auto"))
            fig.update_layout(barmode="stack", height=320, title=f"📈 {sel_y} 월별 완료 및 검토중", margin=dict(t=40, b=10))
            st.plotly_chart(fig, use_container_width=True)
            st.dataframe(dfm, use_container_width=True, hide_index=True)

        st.markdown("---")
        if "요청부서" in df_valid.columns:
            st.subheader("🏢 요청부서별 누적 완료 및 검토중")
            ds = df_valid.groupby(["요청부서", "분류"]).size().unstack(fill_value=0).reset_index()
            for col in ["검토완료(확인필)", "식품안전팀 검토중"]:
                if col not in ds.columns:
                    ds[col] = 0
            ds["총_검토건수"] = ds["검토완료(확인필)"] + ds["식품안전팀 검토중"]
            ds = ds.sort_values("총_검토건수", ascending=False)
            d1, d2 = st.columns([1.3, 1])
            with d1:
                fig = go.Figure()
                fig.add_trace(go.Bar(x=ds["요청부서"], y=ds["검토완료(확인필)"], name="검토완료", marker_color="#44546A", text=ds["검토완료(확인필)"], textposition="auto"))
                fig.add_trace(go.Bar(x=ds["요청부서"], y=ds["식품안전팀 검토중"], name="검토중", marker_color="#C00000", text=ds["식품안전팀 검토중"], textposition="auto"))
                fig.update_layout(barmode="group", height=320, title="📊 요청부서별 완료 vs 검토중")
                st.plotly_chart(fig, use_container_width=True)
            with d2:
                st.dataframe(ds, use_container_width=True, hide_index=True)

        st.subheader("📋 표시사항 현황 전체 목록")
        f1, f2, f3 = st.columns(3)
        sel_cls = f1.selectbox("진행 구분", ["전체 (검토완료 + 검토중)", "식품안전팀 검토중", "검토완료(확인필)", "제외(개시/준비·보류)"])
        dept_opts = ["전체"] + sorted(df_label_status["요청부서"].dropna().unique().tolist()) if "요청부서" in df_label_status.columns else ["전체"]
        sel_dept = f2.selectbox("요청부서", dept_opts)
        kw = f3.text_input("제품명(제목) 키워드")
        dfl = df_label_status.copy()
        dfl = dfl[dfl["분류"] != "제외(개시/준비·보류)"] if sel_cls.startswith("전체") else dfl[dfl["분류"] == sel_cls]
        if sel_dept != "전체":
            dfl = dfl[dfl["요청부서"] == sel_dept]
        if kw:
            dfl = dfl[dfl["제목"].str.contains(kw, case=False, na=False)]
        st.dataframe(dfl[cols_to_show + ["분류", "등록연도", "등록월"]], use_container_width=True, hide_index=True, height=400)

    # ---------------- 7. 원자재 표시사항 DB ----------------
    elif view == "label_issue":
        st.markdown("<div class='main-title'>7. 표시사항 특이사항 - 원재료 표시사항 DB 현황</div>", unsafe_allow_html=True)
        a, b, c = st.columns(3)
        a.metric("전체 원재료 명단", f"{raw_master_cnt:,} 건")
        b.metric("원자재 표시사항 등록", f"{sub_cnt:,} 건")
        c.metric("신규 알레르기 감지", f"{allergy_chg_cnt:,} 건")
        if not df_raw_sub.empty:
            kw = st.text_input("🔍 원재료명 / 제조원 / 공급사 검색")
            dfr = df_raw_sub[df_raw_sub.astype(str).apply(lambda x: x.str.contains(kw, case=False, na=False)).any(axis=1)] if kw else df_raw_sub
            st.dataframe(dfr, use_container_width=True, hide_index=True)
        else:
            st.info("'원자재 표시사항 DB' 시트1에 등록된 데이터가 없습니다.")
        if "rt_today" in proc_data and proc_data["rt_today"] is not None and not proc_data["rt_today"]["df_issues"].empty:
            st.subheader("📋 현장 전달(특이)사항 (상온 공정일보)")
            st.dataframe(proc_data["rt_today"]["df_issues"], use_container_width=True, hide_index=True)
