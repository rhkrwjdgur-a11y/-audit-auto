import streamlit as st
import pandas as pd
import io
import datetime
import google.generativeai as genai
import PyPDF2
import openpyxl
from openpyxl.styles import Alignment, Border, Side, Font, PatternFill
from openpyxl.drawing.image import Image as ExcelImage
from PIL import Image as PILImage

# -----------------------------------------------------------------------------
# 1. 페이지 설정 및 초기화
# -----------------------------------------------------------------------------
st.set_page_config(page_title="심사 개선요구사항 자동 분류 시스템", layout="wide")
st.title("📋 심사 개선요구사항 자동 분류 및 보고서 생성기")
st.markdown("심사 결과를 입력하면 AI가 정제 및 분류하고, **현장 사진과 공식 보고서 헤더가 포함된 부서별 엑셀 양식**을 생성합니다.")

TEAM_LIST = [
    "유제품가공팀", 
    "카톤포장팀", 
    "병포장팀", 
    "상온제품가공팀", 
    "상온제품포장팀", 
    "품질관리팀"
]

if "issue_data" not in st.session_state:
    st.session_state.issue_data = []

# -----------------------------------------------------------------------------
# 2. 파일 텍스트 추출 함수
# -----------------------------------------------------------------------------
def extract_text_from_file(uploaded_file):
    text = ""
    file_name = uploaded_file.name.lower()
    try:
        if file_name.endswith('.pdf'):
            pdf_reader = PyPDF2.PdfReader(uploaded_file)
            for page in pdf_reader.pages:
                extracted = page.extract_text()
                if extracted:
                    text += extracted + "\n"
        elif file_name.endswith(('.xlsx', '.xls')):
            xls = pd.ExcelFile(uploaded_file)
            for sheet_name in xls.sheet_names:
                df = pd.read_excel(xls, sheet_name=sheet_name)
                text += df.to_string(index=False) + "\n"
        elif file_name.endswith('.txt') or file_name.endswith('.csv'):
            text = uploaded_file.getvalue().decode("utf-8")
    except Exception as e:
        st.error(f"파일 추출 오류: {e}")
    return text

# -----------------------------------------------------------------------------
# 3. 사이드바: 설정 및 보안
# -----------------------------------------------------------------------------
with st.sidebar:
    st.header("⚙️ 환경 설정")
    try:
        api_key = st.secrets["GEMINI_API_KEY"]
        genai.configure(api_key=api_key)
        api_key_loaded = True
        st.success("✅ API Key 보안 로드 완료")
    except KeyError:
        api_key_loaded = False
        st.error("⚠️ API Key가 설정되지 않았습니다.")
    
    st.markdown("---")
    st.header("📖 사내 용어 및 어조 가이드")
    default_tone_guide = """1. 종결어미: 모든 문장은 '~함', '~미흡', '~필요' 와 같은 명사형/개조식 문어체로 끝낼 것.
2. 용어 변환: '더럽다/지저분하다' -> '청결 상태 미흡' 또는 '오염됨'
3. 용어 변환: '우유/두유' -> '원유' 또는 '내용물'
4. 용어 변환: '기계' -> '설비'
5. 감정적 표현 배제: 객관적인 사실과 상태만 건조하게 기술할 것."""
    tone_guide = st.text_area("보고서 톤앤매너 규칙", value=default_tone_guide, height=200)

# -----------------------------------------------------------------------------
# 4. 1단계: 데이터 입력, 제품군 선택 및 AI 추출
# -----------------------------------------------------------------------------
st.header("1단계: 심사 대상 선택 및 파일 업로드")

product_category = st.radio(
    "🔍 심사 대상 제품군을 선택하세요 (선택 시 해당 공정 관련 팀만 활성화되어 정확도가 향상됩니다.)",
    ["전체 (모든 부서 활성화)", "유제품 (상온 부서 제외)", "상온제품 (유제품 부서 제외)"],
    horizontal=True
)

if product_category == "유제품 (상온 부서 제외)":
    current_teams = ["유제품가공팀", "카톤포장팀", "병포장팀", "품질관리팀"]
elif product_category == "상온제품 (유제품 부서 제외)":
    current_teams = ["상온제품가공팀", "상온제품포장팀", "품질관리팀"]
else:
    current_teams = ["유제품가공팀", "카톤포장팀", "병포장팀", "상온제품가공팀", "상온제품포장팀", "품질관리팀"]

st.info(f"선택된 제품군에 따라 다음 부서로만 분류됩니다: **{', '.join(current_teams)}**")

col1, col2 = st.columns(2)
with col1:
    uploaded_file = st.file_uploader("📄 파일 업로드 (PDF, 엑셀, 텍스트)", type=['pdf', 'xlsx', 'xls', 'txt', 'csv'])
with col2:
    raw_text = st.text_area("✍️ 텍스트 직접 붙여넣기", height=100)

if st.button("🚀 AI 추출 및 자동 분류 실행"):
    if not api_key_loaded:
        st.error("API Key가 없습니다.")
    elif uploaded_file is None and not raw_text.strip():
        st.warning("분석할 파일이나 텍스트를 입력해 주세요.")
    else:
        with st.spinner("AI가 데이터를 추출하고 분류 중입니다..."):
            combined_text = ""
            if uploaded_file is not None:
                combined_text += extract_text_from_file(uploaded_file) + "\n"
            if raw_text.strip():
                combined_text += raw_text.strip()

            model = genai.GenerativeModel('gemini-3.6-flash')
            prompt = f"""
            당신은 식품 제조 현장의 심사 지적사항을 분석하여 담당 부서를 배정하는 전문가입니다.
            아래 텍스트에서 지적사항을 추출하고 어조를 변환하여 지정된 부서 중 하나로 분류하십시오.

            [어조 변환 규칙]
            {tone_guide}

            [담당 부서 매칭 기준]
            각 항목의 원인과 공정을 분석하여 반드시 아래의 '담당 부서' 중 가장 적합한 1개의 부서와 매칭하십시오.
            [{', '.join(current_teams)}]

            [출력 규칙]
            - 반드시 "지적사항|담당부서" 형태의 파이프(|) 구분자로만 출력하십시오.
            - 첫 줄은 헤더 "지적사항|담당부서" 로 고정.
            - 마크다운이나 기타 부연 설명 절대 금지.

            [데이터]
            {combined_text}
            """
            
            try:
                response = model.generate_content(prompt)
                result_text = response.text.strip()
                if result_text.startswith("```"):
                    result_text = result_text.split("\n", 1)[1]
                if result_text.endswith("```"):
                    result_text = result_text.rsplit("\n", 1)[0]
                
                df_parsed = pd.read_csv(io.StringIO(result_text), sep="|")
                if len(df_parsed.columns) == 2:
                    df_parsed.columns = ["지적사항", "담당부서"]
                    parsed_list = []
                    for _, row in df_parsed.iterrows():
                        assigned_team = row["담당부서"] if row["담당부서"] in current_teams else "품질관리팀"
                        parsed_list.append({
                            "issue": row["지적사항"],
                            "team": assigned_team,
                            "image": None
                        })
                    st.session_state.issue_data = parsed_list
                    st.success("추출 완료! 2단계에서 사진을 추가하고 내용을 검수하세요.")
                else:
                    st.error("형식이 올바르지 않습니다.")
            except Exception as e:
                st.error(f"오류 발생: {e}")

# -----------------------------------------------------------------------------
# 5. 2단계: 데이터 검수 및 사진 첨부 
# -----------------------------------------------------------------------------
st.header("2단계: 분류 결과 검수 및 현장 사진 첨부")
st.markdown("각 항목별로 지적사항을 수정하거나 부서를 변경하고, **해당하는 지적사항 사진(개선 전)**을 첨부하세요.")

if st.session_state.issue_data:
    for i, item in enumerate(st.session_state.issue_data):
        with st.container():
            st.markdown(f"**항목 {i+1}**")
            col_a, col_b, col_c = st.columns([4, 2, 2])
            
            with col_a:
                st.session_state.issue_data[i]["issue"] = st.text_area(
                    "지적사항 (수정 가능)", 
                    value=item["issue"], 
                    height=100, 
                    key=f"issue_{i}"
                )
            with col_b:
                st.session_state.issue_data[i]["team"] = st.selectbox(
                    "담당부서", 
                    options=current_teams, 
                    index=current_teams.index(item["team"]) if item["team"] in current_teams else (len(current_teams)-1),
                    key=f"team_{i}"
                )
            with col_c:
                uploaded_img = st.file_uploader(
                    "개선 전 사진 첨부", 
                    type=['png', 'jpg', 'jpeg'], 
                    key=f"img_{i}"
                )
                if uploaded_img is not None:
                    st.session_state.issue_data[i]["image"] = uploaded_img
            st.markdown("---")

    # -----------------------------------------------------------------------------
    # 6. 3단계: 부서별 시트 분할 엑셀 보고서 생성 및 이미지 삽입 (보고서 포맷 적용)
    # -----------------------------------------------------------------------------
    st.header("3단계: 부서별 엑셀 통합 보고서 생성")
    
    def create_excel_report(issue_data, allowed_teams):
        # 다운로드 시점의 현재 시스템 날짜 확보
        today_str = datetime.datetime.now().strftime("%Y-%m-%d")

        wb = openpyxl.Workbook()
        wb.remove(wb.active) # 기본 시트 삭제
        
        # 엑셀 공통 서식 정의
        header_font = Font(bold=True, size=11, color="FFFFFF")
        header_fill = PatternFill("solid", fgColor="4F81BD")
        overview_fill = PatternFill("solid", fgColor="E9ECEF")
        bold_font = Font(bold=True, size=11)
        border_style = Border(
            left=Side(style='thin'), right=Side(style='thin'), 
            top=Side(style='thin'), bottom=Side(style='thin')
        )
        center_align = Alignment(horizontal='center', vertical='center', wrap_text=True)
        left_align = Alignment(horizontal='left', vertical='center', wrap_text=True)

        for team in allowed_teams:
            team_issues = [item for item in issue_data if item["team"] == team]
            
            if team_issues:
                ws = wb.create_sheet(title=team)
                
                # --- [보고서 상단 헤더 및 개요 구성] ---
                
                # 1. 보고서 제목 
                ws.merge_cells('A1:E1')
                ws['A1'] = f"[{team}] 심사 개선요구사항 조치 보고서"
                ws['A1'].font = Font(size=16, bold=True)
                ws['A1'].alignment = center_align
                ws.row_dimensions[1].height = 30
                
                # 2. 작성일자 및 작성부서 (우측 정렬)
                ws.merge_cells('A2:E2')
                ws['A2'] = f"작성일자: {today_str}    |    작성부서: 식품안전팀"
                ws['A2'].font = Font(size=11, bold=True)
                ws['A2'].alignment = Alignment(horizontal='right', vertical='center')
                ws.row_dimensions[2].height = 20
                
                # 3. 심사 개요 서브타이틀
                ws.merge_cells('A3:E3')
                ws['A3'] = "■ 심사 개요"
                ws['A3'].font = bold_font
                ws['A3'].alignment = Alignment(horizontal='left', vertical='center')
                ws.row_dimensions[3].height = 20
                
                # 4. 심사 개요 입력 표
                ws['A4'] = "심사기관"
                ws['B4'] = "(기관명 기입)"
                ws['C4'] = "심사일자"
                ws.merge_cells('D4:E4')
                ws['D4'] = "(일자 기입)"
                
                ws['A5'] = "심사목적"
                ws.merge_cells('B5:E5')
                ws['B5'] = "정기 위생/품질 심사 대응 및 시정조치"
                
                # 심사 개요 표 서식 적용
                for r in range(4, 6):
                    ws.row_dimensions[r].height = 25
                    for c in range(1, 6):
                        cell = ws.cell(row=r, column=c)
                        cell.border = border_style
                        if c in [1, 3]: # A열, C열 (라벨)
                            cell.fill = overview_fill
                            cell.alignment = center_align
                            cell.font = bold_font
                        else:
                            cell.alignment = left_align
                
                # 간격 띄우기
                ws.merge_cells('A6:E6')
                ws['A6'] = ""
                ws.row_dimensions[6].height = 10
                
                # 5. 본문 서브타이틀
                ws.merge_cells('A7:E7')
                ws['A7'] = "■ 개선 요구사항 및 조치 결과"
                ws['A7'].font = bold_font
                ws.row_dimensions[7].height = 20

                # --- [데이터 표(리스트) 구성] ---
                
                # 6. 표 헤더 작성
                headers = ["No", "지적사항(개선요구사항)", "개선 전 사진", "원인 및 조치내역(작성란)", "개선 후 사진(첨부란)"]
                for c, h in enumerate(headers, start=1):
                    cell = ws.cell(row=8, column=c, value=h)
                    cell.font = header_font
                    cell.fill = header_fill
                    cell.border = border_style
                    cell.alignment = center_align
                ws.row_dimensions[8].height = 25
                
                # 7. 열 너비 설정 (사진 크기 확대를 위해 C열, E열 너비 대폭 증가)
                ws.column_dimensions['A'].width = 5
                ws.column_dimensions['B'].width = 40
                ws.column_dimensions['C'].width = 45  # 확대됨
                ws.column_dimensions['D'].width = 40
                ws.column_dimensions['E'].width = 45  # 확대됨
                
                # 8. 데이터 행 작성 및 큰 이미지 삽입
                current_row = 9
                for idx, item in enumerate(team_issues, start=1):
                    ws.cell(row=current_row, column=1, value=idx)
                    ws.cell(row=current_row, column=2, value=item["issue"])
                    ws.cell(row=current_row, column=4, value="") # 조치내역 빈칸
                    
                    # 행 높이 넉넉하게 설정 (사진 확대를 위해 220 픽셀로 증가)
                    ws.row_dimensions[current_row].height = 220
                    
                    # 테두리 및 정렬 서식
                    for col in range(1, 6):
                        cell = ws.cell(row=current_row, column=col)
                        cell.border = border_style
                        if col == 2 or col == 4:
                            cell.alignment = left_align
                        else:
                            cell.alignment = center_align

                    # 사진(이미지) 삽입 처리
                    if item["image"] is not None:
                        img = PILImage.open(item["image"])
                        # 이미지 해상도를 기존 대비 크게 확대 (310x280)
                        img.thumbnail((310, 280)) 
                        
                        img_byte_arr = io.BytesIO()
                        img.save(img_byte_arr, format='PNG')
                        img_byte_arr.seek(0)
                        
                        xl_img = ExcelImage(img_byte_arr)
                        # C열(개선 전 사진) 위치에 앵커 고정
                        xl_img.anchor = f"C{current_row}" 
                        
                        ws.add_image(xl_img)
                        
                    current_row += 1

        if not wb.sheetnames:
            ws = wb.create_sheet(title="조치사항없음")
            ws.append(["해당하는 지적사항이 없습니다."])

        excel_io = io.BytesIO()
        wb.save(excel_io)
        return excel_io.getvalue()

    if st.button("📊 부서별 보고서 양식 엑셀 다운로드"):
        excel_data = create_excel_report(st.session_state.issue_data, current_teams)
        st.download_button(
            label="💾 '심사조치_통합보고서.xlsx' 다운로드",
            data=excel_data,
            file_name="심사조치_통합보고서.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
else:
    st.info("데이터를 입력하고 실행하면 사진 첨부 및 검수 화면이 활성화됩니다.")
