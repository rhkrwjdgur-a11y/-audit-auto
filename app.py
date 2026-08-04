import streamlit as st
import pandas as pd
import io
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
st.markdown("심사 결과를 입력하면 AI가 정제 및 분류하고, **현장 사진을 포함하여 부서별 시트로 나뉜 완벽한 엑셀 양식**을 생성합니다.")

TEAM_LIST = [
    "유제품가공팀", 
    "카톤포장팀", 
    "병포장팀", 
    "상온제품가공팀", 
    "상온제품포장팀", 
    "품질관리팀"
]

# 세션 상태 초기화 (항목별 데이터 리스트 관리)
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
# 4. 1단계: 데이터 입력 및 AI 추출
# -----------------------------------------------------------------------------
st.header("1단계: 심사 결과 파일 업로드 및 AI 자동 분류")
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

            model = genai.GenerativeModel('gemini-1.5-pro-latest')
            prompt = f"""
            당신은 식품 제조 현장의 심사 지적사항을 분석하여 담당 부서를 배정하는 전문가입니다.
            아래 텍스트에서 지적사항을 추출하고 어조를 변환하여 6개 부서(유제품가공팀, 카톤포장팀, 병포장팀, 상온제품가공팀, 상온제품포장팀, 품질관리팀) 중 하나로 분류하십시오.

            [어조 변환 규칙]
            {tone_guide}

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
                    # 세션 상태 리스트로 변환 (사진 데이터를 담기 위함)
                    parsed_list = []
                    for _, row in df_parsed.iterrows():
                        parsed_list.append({
                            "issue": row["지적사항"],
                            "team": row["담당부서"] if row["담당부서"] in TEAM_LIST else "품질관리팀",
                            "image": None
                        })
                    st.session_state.issue_data = parsed_list
                    st.success("추출 완료! 2단계에서 사진을 추가하고 내용을 검수하세요.")
                else:
                    st.error("형식이 올바르지 않습니다.")
            except Exception as e:
                st.error(f"오류 발생: {e}")

# -----------------------------------------------------------------------------
# 5. 2단계: 데이터 검수 및 사진 첨부 (UI 고도화)
# -----------------------------------------------------------------------------
st.header("2단계: 분류 결과 검수 및 현장 사진 첨부")
st.markdown("각 항목별로 지적사항을 수정하거나 부서를 변경하고, **해당하는 지적사항 사진(개선 전)**을 첨부하세요.")

if st.session_state.issue_data:
    for i, item in enumerate(st.session_state.issue_data):
        with st.container():
            st.markdown(f"**항목 {i+1}**")
            col_a, col_b, col_c = st.columns([4, 2, 2])
            
            with col_a:
                # 지적사항 텍스트 수정
                st.session_state.issue_data[i]["issue"] = st.text_area(
                    "지적사항 (수정 가능)", 
                    value=item["issue"], 
                    height=100, 
                    key=f"issue_{i}"
                )
            with col_b:
                # 부서 선택 수정
                st.session_state.issue_data[i]["team"] = st.selectbox(
                    "담당부서", 
                    options=TEAM_LIST, 
                    index=TEAM_LIST.index(item["team"]) if item["team"] in TEAM_LIST else 5,
                    key=f"team_{i}"
                )
            with col_c:
                # 사진 첨부 (메모리에 유지)
                uploaded_img = st.file_uploader(
                    "개선 전 사진 첨부", 
                    type=['png', 'jpg', 'jpeg'], 
                    key=f"img_{i}"
                )
                if uploaded_img is not None:
                    st.session_state.issue_data[i]["image"] = uploaded_img
            st.markdown("---")

    # -----------------------------------------------------------------------------
    # 6. 3단계: 부서별 시트 분할 엑셀 보고서 생성 및 이미지 삽입
    # -----------------------------------------------------------------------------
    st.header("3단계: 부서별 엑셀 통합 보고서 생성")
    
    def create_excel_report(issue_data):
        wb = openpyxl.Workbook()
        wb.remove(wb.active) # 기본 시트 삭제
        
        # 엑셀 공통 서식 정의
        header_font = Font(bold=True, size=11, color="FFFFFF")
        header_fill = PatternFill("solid", fgColor="4F81BD")
        border_style = Border(
            left=Side(style='thin'), right=Side(style='thin'), 
            top=Side(style='thin'), bottom=Side(style='thin')
        )
        center_align = Alignment(horizontal='center', vertical='center', wrap_text=True)
        left_align = Alignment(horizontal='left', vertical='center', wrap_text=True)

        for team in TEAM_LIST:
            # 해당 부서의 데이터만 필터링
            team_issues = [item for item in issue_data if item["team"] == team]
            
            if team_issues:
                ws = wb.create_sheet(title=team)
                
                # 헤더 작성
                headers = ["No", "지적사항(개선요구사항)", "개선 전 사진", "원인 및 조치내역(작성란)", "개선 후 사진(첨부란)"]
                ws.append(headers)
                
                # 열 너비 설정 (픽셀 단위 조정)
                ws.column_dimensions['A'].width = 5
                ws.column_dimensions['B'].width = 40
                ws.column_dimensions['C'].width = 30
                ws.column_dimensions['D'].width = 40
                ws.column_dimensions['E'].width = 30
                
                # 헤더 서식 적용
                for cell in ws[1]:
                    cell.font = header_font
                    cell.fill = header_fill
                    cell.border = border_style
                    cell.alignment = center_align
                
                # 데이터 행 작성 및 이미지 삽입
                current_row = 2
                for idx, item in enumerate(team_issues, start=1):
                    # 텍스트 데이터 입력
                    ws.cell(row=current_row, column=1, value=idx)
                    ws.cell(row=current_row, column=2, value=item["issue"])
                    ws.cell(row=current_row, column=4, value="") # 조치내역 빈칸
                    
                    # 행 높이 넉넉하게 설정 (사진이 들어갈 공간)
                    ws.row_dimensions[current_row].height = 150
                    
                    # 서식 적용
                    for col in range(1, 6):
                        cell = ws.cell(row=current_row, column=col)
                        cell.border = border_style
                        if col == 2 or col == 4:
                            cell.alignment = left_align
                        else:
                            cell.alignment = center_align

                    # 사진(이미지) 삽입 처리
                    if item["image"] is not None:
                        # 이미지를 PIL로 열고 엑셀에 맞게 리사이징(썸네일 처리)
                        img = PILImage.open(item["image"])
                        img.thumbnail((200, 180)) # 셀 크기에 맞게 리사이징
                        
                        # 바이너리 스트림으로 변환 (파일 저장 없이 처리)
                        img_byte_arr = io.BytesIO()
                        img.save(img_byte_arr, format='PNG')
                        img_byte_arr.seek(0)
                        
                        xl_img = ExcelImage(img_byte_arr)
                        # C열(개선 전 사진) 위치에 앵커 고정 (예: C2, C3...)
                        xl_img.anchor = f"C{current_row}" 
                        
                        # 여백 조절을 위해 약간의 offset 적용 가능하나, 여기서는 정위치 삽입
                        ws.add_image(xl_img)
                        
                    current_row += 1

        # 데이터가 있는 시트가 하나도 없을 경우 빈 시트 생성
        if not wb.sheetnames:
            ws = wb.create_sheet(title="조치사항없음")
            ws.append(["해당하는 지적사항이 없습니다."])

        # 완성된 엑셀 파일을 바이너리로 변환하여 반환
        excel_io = io.BytesIO()
        wb.save(excel_io)
        return excel_io.getvalue()

    if st.button("📊 부서별 엑셀 보고서 다운로드 (사진 자동 삽입)"):
        excel_data = create_excel_report(st.session_state.issue_data)
        st.download_button(
            label="💾 '심사조치_통합보고서.xlsx' 다운로드",
            data=excel_data,
            file_name="심사조치_통합보고서.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
else:
    st.info("데이터를 입력하고 실행하면 사진 첨부 및 검수 화면이 활성화됩니다.")
