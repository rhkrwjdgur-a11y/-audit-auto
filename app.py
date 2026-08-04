import streamlit as st
import pandas as pd
import io
import datetime
import google.generativeai as genai
import PyPDF2
import openpyxl
from openpyxl.styles import Alignment, Border, Side, Font, PatternFill
from openpyxl.drawing.image import Image as ExcelImage
from PIL import Image as PILImage, ImageOps  # ImageOps 추가 (사진 회전 방지용)

# -----------------------------------------------------------------------------
# 1. 페이지 설정 및 초기화 (항상 최상단에 위치)
# -----------------------------------------------------------------------------
st.set_page_config(page_title="심사 개선요구사항 AI 자동화 시스템", layout="wide")

TEAM_LIST = [
    "유제품가공팀", 
    "카톤포장팀", 
    "병포장팀", 
    "상온제품가공팀", 
    "상온제품포장팀", 
    "품질관리팀"
]

# 세션 상태 초기화 (메뉴별 데이터 분리 관리)
if "text_issue_data" not in st.session_state:
    st.session_state.text_issue_data = []
if "image_issue_data" not in st.session_state:
    st.session_state.image_issue_data = []

# -----------------------------------------------------------------------------
# 2. 공통 유틸리티 함수
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

def create_excel_report(issue_data, allowed_teams, report_info):
    """두 메뉴에서 공통으로 사용하는 엑셀 보고서 생성 함수"""
    wb = openpyxl.Workbook()
    wb.remove(wb.active) # 기본 시트 삭제
    
    header_font = Font(bold=True, size=11, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="4F81BD")
    overview_fill = PatternFill("solid", fgColor="E9ECEF")
    bold_font = Font(bold=True, size=12)
    normal_font = Font(size=11)
    
    border_style = Border(
        left=Side(style='thin'), right=Side(style='thin'), 
        top=Side(style='thin'), bottom=Side(style='thin')
    )
    center_align = Alignment(horizontal='center', vertical='center', wrap_text=True)
    left_align = Alignment(horizontal='left', vertical='center', wrap_text=True)
    right_align = Alignment(horizontal='right', vertical='center', wrap_text=True)

    for team in allowed_teams:
        team_issues = [item for item in issue_data if item["team"] == team]
        
        if team_issues:
            ws = wb.create_sheet(title=team)
            
            # 1. 보고서 제목 
            ws.merge_cells('A1:E2')
            ws['A1'] = report_info['title']
            ws['A1'].font = Font(size=22, bold=True)
            ws['A1'].alignment = center_align
            
            # 2. 보고 일자 및 부서명
            ws['E3'] = report_info['report_date']
            ws['E3'].font = normal_font
            ws['E3'].alignment = right_align
            
            ws['E4'] = report_info['team_name']
            ws['E4'].font = normal_font
            ws['E4'].alignment = right_align
            
            # 3. 심사 개요 텍스트
            ws['A6'] = "1. 심사 개요"
            ws['A6'].font = bold_font
            
            ws.merge_cells('A7:E7')
            ws['A7'] = f"가. 심사 일자 : {report_info['audit_date']}"
            ws['A7'].font = normal_font
            
            ws.merge_cells('A8:E8')
            ws['A8'] = f"나. 심사 기관(심사자) : {report_info['audit_agency']}"
            ws['A8'].font = normal_font
            
            ws.merge_cells('A9:E9')
            ws['A9'] = f"다. 심사 목적 : {report_info['audit_purpose']}"
            ws['A9'].font = normal_font
            
            ws.row_dimensions[1].height = 20
            ws.row_dimensions[2].height = 20
            ws.row_dimensions[6].height = 20
            ws.row_dimensions[7].height = 18
            ws.row_dimensions[8].height = 18
            ws.row_dimensions[9].height = 18
            
            # 4. 데이터 표 시작
            ws['A11'] = "2. 부서별 개선 요구사항 및 조치 결과"
            ws['A11'].font = bold_font
            ws.row_dimensions[11].height = 20

            headers = ["No", "지적사항(개선요구사항)", "개선 전 사진", "원인 및 조치내역(작성란)", "개선 후 사진(첨부란)"]
            for c, h in enumerate(headers, start=1):
                cell = ws.cell(row=12, column=c, value=h)
                cell.font = header_font
                cell.fill = header_fill
                cell.border = border_style
                cell.alignment = center_align
            ws.row_dimensions[12].height = 25
            
            # 팩트 기반 수정: 열 너비를 38로 대폭 줄여 PC마다 발생하는 렌더링 오차를 강제 최소화
            ws.column_dimensions['A'].width = 5
            ws.column_dimensions['B'].width = 40
            ws.column_dimensions['C'].width = 38  
            ws.column_dimensions['D'].width = 40
            ws.column_dimensions['E'].width = 38  
            
            # 데이터 행 작성
            current_row = 13
            for idx, item in enumerate(team_issues, start=1):
                ws.cell(row=current_row, column=1, value=idx)
                ws.cell(row=current_row, column=2, value=item["issue"])
                ws.cell(row=current_row, column=4, value="") 
                
                # 행 높이는 225포인트(약 300px) 유지
                ws.row_dimensions[current_row].height = 225
                
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
                    
                    # 스마트폰 세로/가로 회전 메타데이터(EXIF) 적용하여 정방향 유지
                    img = ImageOps.exif_transpose(img)
                    
                    if img.mode in ("RGBA", "P"):
                        img = img.convert("RGB")
                        
                    # 좁혀진 셀(38) 위에 사진 크기를 340px로 넉넉히 덮어 우측 여백 완전 제거 (Zero-Gap)
                    img = img.resize((340, 298)) 
                    
                    img_byte_arr = io.BytesIO()
                    img.save(img_byte_arr, format='JPEG') 
                    img_byte_arr.seek(0)
                    
                    xl_img = ExcelImage(img_byte_arr)
                    xl_img.width = 340
                    xl_img.height = 298
                    xl_img.anchor = f"C{current_row}" 
                    ws.add_image(xl_img)
                    
                current_row += 1

    if not wb.sheetnames:
        ws = wb.create_sheet(title="조치사항없음")
        ws.append(["해당하는 지적사항이 없습니다."])

    excel_io = io.BytesIO()
    wb.save(excel_io)
    return excel_io.getvalue()

# -----------------------------------------------------------------------------
# 3. 사이드바: 메뉴 및 환경 설정
# -----------------------------------------------------------------------------
with st.sidebar:
    st.title("🗂️ 업무 메뉴")
    app_mode = st.radio(
        "사용할 기능을 선택하세요",
        ["심사 개선요구사항 문서 분류", "지적사항 사진 자동 분류"]
    )
    
    st.markdown("---")
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


# =============================================================================
# [메뉴 1] 심사 개선요구사항 문서 분류 
# =============================================================================
if app_mode == "심사 개선요구사항 문서 분류":
    st.title("📋 심사 문서 텍스트 자동 추출 및 분류기")
    st.markdown("심사 결과 파일(PDF, 엑셀 등)을 입력하면 AI가 정제 및 분류하고 엑셀 양식을 생성합니다.")

    st.header("1단계: 심사 대상 선택 및 파일 업로드")

    product_category = st.radio(
        "🔍 심사 대상 제품군을 선택하세요",
        ["전체 (모든 부서 활성화)", "유제품 (상온 부서 제외)", "상온제품 (유제품 부서 제외)"],
        horizontal=True,
        key="menu1_radio"
    )

    if product_category == "유제품 (상온 부서 제외)":
        current_teams = ["유제품가공팀", "카톤포장팀", "병포장팀", "품질관리팀"]
    elif product_category == "상온제품 (유제품 부서 제외)":
        current_teams = ["상온제품가공팀", "상온제품포장팀", "품질관리팀"]
    else:
        current_teams = ["유제품가공팀", "카톤포장팀", "병포장팀", "상온제품가공팀", "상온제품포장팀", "품질관리팀"]

    col1, col2 = st.columns(2)
    with col1:
        uploaded_file = st.file_uploader("📄 파일 업로드 (PDF, 엑셀, 텍스트)", type=['pdf', 'xlsx', 'xls', 'txt', 'csv'], key="menu1_file")
    with col2:
        raw_text = st.text_area("✍️ 텍스트 직접 붙여넣기", height=100, key="menu1_text")

    if st.button("🚀 문서 AI 추출 및 분류 실행"):
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
                [{', '.join(current_teams)}] 중 가장 적합한 1개의 부서와 매칭하십시오.

                [출력 규칙]
                - 반드시 "지적사항|담당부서" 형태의 파이프(|) 구분자로만 출력하십시오.
                - 첫 줄은 헤더 "지적사항|담당부서" 로 고정.

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
                        st.session_state.text_issue_data = parsed_list
                        st.success("추출 완료! 2단계에서 사진을 추가하고 내용을 검수하세요.")
                    else:
                        st.error("형식이 올바르지 않습니다.")
                except Exception as e:
                    st.error(f"오류 발생: {e}")

    st.header("2단계: 분류 결과 검수 및 현장 사진 첨부")
    if st.session_state.text_issue_data:
        for i, item in enumerate(st.session_state.text_issue_data):
            with st.container():
                st.markdown(f"**항목 {i+1}**")
                col_a, col_b, col_c = st.columns([4, 2, 2])
                with col_a:
                    st.session_state.text_issue_data[i]["issue"] = st.text_area("지적사항 (수정 가능)", value=item["issue"], height=100, key=f"t_issue_{i}")
                with col_b:
                    st.session_state.text_issue_data[i]["team"] = st.selectbox("담당부서", options=current_teams, index=current_teams.index(item["team"]) if item["team"] in current_teams else (len(current_teams)-1), key=f"t_team_{i}")
                with col_c:
                    uploaded_img = st.file_uploader("개선 전 사진 첨부", type=['png', 'jpg', 'jpeg'], key=f"t_img_{i}")
                    if uploaded_img is not None:
                        st.session_state.text_issue_data[i]["image"] = uploaded_img
                st.markdown("---")

        st.header("3단계: 부서별 엑셀 통합 보고서 다운로드")
        st.markdown("📝 **보고서 상단에 인쇄될 정보를 입력해 주세요.**")
        col_h1, col_h2 = st.columns(2)
        with col_h1:
            r_title = st.text_input("보고서 제목", "심사 결과 보고서", key="t_r_title")
            r_date = st.text_input("보고 일자", datetime.datetime.now().strftime("%Y. %m. %d"), key="t_r_date")
            t_name = st.text_input("작성 부서", "식품안전팀", key="t_t_name")
        with col_h2:
            a_date = st.text_input("심사 일자", datetime.datetime.now().strftime("%Y. %m. %d"), key="t_a_date")
            a_agency = st.text_input("심사 기관(심사자)", "한국뷰로베리타스 윤대민", key="t_a_agency")
            a_purpose = st.text_input("심사 목적", "정기심사", key="t_a_purpose")

        report_info = {
            'title': r_title, 'report_date': r_date, 'team_name': t_name,
            'audit_date': a_date, 'audit_agency': a_agency, 'audit_purpose': a_purpose
        }

        if st.button("📊 문서 기반 보고서 양식 엑셀 다운로드"):
            excel_data = create_excel_report(st.session_state.text_issue_data, current_teams, report_info)
            st.download_button(
                label="💾 '심사조치_통합보고서.xlsx' 다운로드",
                data=excel_data,
                file_name="심사조치_통합보고서.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="t_download"
            )

# =============================================================================
# [메뉴 2] 지적사항 사진 자동 분류 
# =============================================================================
elif app_mode == "지적사항 사진 자동 분류":
    st.title("📸 지적사항 사진 AI 자동 분석 및 분류기")
    st.markdown("현장에서 찍은 지적사항 **사진을 여러 장 업로드**하면, AI가 사진을 보고 문제점을 스스로 파악하여 지적사항 멘트를 작성하고 부서를 매칭합니다.")

    st.header("1단계: 심사 대상 선택 및 다중 사진 업로드")
    
    product_category_img = st.radio(
        "🔍 심사 대상 제품군을 선택하세요",
        ["전체 (모든 부서 활성화)", "유제품 (상온 부서 제외)", "상온제품 (유제품 부서 제외)"],
        horizontal=True,
        key="menu2_radio"
    )

    if product_category_img == "유제품 (상온 부서 제외)":
        current_teams_img = ["유제품가공팀", "카톤포장팀", "병포장팀", "품질관리팀"]
    elif product_category_img == "상온제품 (유제품 부서 제외)":
        current_teams_img = ["상온제품가공팀", "상온제품포장팀", "품질관리팀"]
    else:
        current_teams_img = ["유제품가공팀", "카톤포장팀", "병포장팀", "상온제품가공팀", "상온제품포장팀", "품질관리팀"]

    st.info(f"선택된 제품군에 따라 다음 부서로만 분류됩니다: **{', '.join(current_teams_img)}**")

    uploaded_images = st.file_uploader("📷 지적사항 사진 여러 장 일괄 업로드", type=['png', 'jpg', 'jpeg'], accept_multiple_files=True)

    if st.button("🚀 사진 AI 분석 및 자동 분류 실행"):
        if not api_key_loaded:
            st.error("API Key가 없습니다.")
        elif not uploaded_images:
            st.warning("분석할 사진을 업로드해 주세요.")
        else:
            with st.spinner(f"AI가 총 {len(uploaded_images)}장의 사진을 분석 중입니다. 잠시만 기다려주세요..."):
                model = genai.GenerativeModel('gemini-3.6-flash')
                parsed_img_list = []
                
                progress_bar = st.progress(0)
                total_imgs = len(uploaded_images)
                
                for idx, img_file in enumerate(uploaded_images):
                    try:
                        pil_img = PILImage.open(img_file)
                        
                        prompt = f"""
                        당신은 식품 제조 현장의 심사관입니다. 
                        첨부된 사진을 보고 어떤 위생/품질 문제가 있는지 객관적으로 파악하십시오.
                        
                        [어조 변환 규칙]
                        {tone_guide}

                        [담당 부서 매칭 기준]
                        사진의 문제를 해결해야 할 가장 적합한 부서를 아래 목록 중에서 단 1개만 고르십시오.
                        [{', '.join(current_teams_img)}]

                        [출력 규칙]
                        - 반드시 "지적사항|담당부서" 형태의 파이프(|) 구분자로만 1줄로 출력하십시오. (예: 바닥 파손으로 인한 밀폐관리 미흡|유제품가공팀)
                        - 부가적인 설명은 절대 금지합니다.
                        """
                        
                        response = model.generate_content([prompt, pil_img])
                        result_text = response.text.strip().replace("```", "").strip()
                        
                        if "|" in result_text:
                            issue_desc, team_name = result_text.split("|", 1)
                            assigned_team = team_name.strip() if team_name.strip() in current_teams_img else "품질관리팀"
                            parsed_img_list.append({
                                "issue": issue_desc.strip(),
                                "team": assigned_team,
                                "image": img_file 
                            })
                        else:
                            parsed_img_list.append({
                                "issue": f"AI 분석 실패: {result_text}",
                                "team": "품질관리팀",
                                "image": img_file
                            })
                    except Exception as e:
                        st.error(f"{img_file.name} 분석 중 오류 발생: {e}")
                    
                    progress_bar.progress((idx + 1) / total_imgs)

                st.session_state.image_issue_data = parsed_img_list
                st.success("사진 분석 및 추출이 완료되었습니다! 2단계에서 내용을 검수하세요.")

    st.header("2단계: 사진 분석 결과 검수 및 수정")
    st.markdown("AI가 사진을 보고 판단한 지적사항입니다. 눈으로 확인하고 부서나 멘트를 수정하십시오.")

    if st.session_state.image_issue_data:
        for i, item in enumerate(st.session_state.image_issue_data):
            with st.container():
                st.markdown(f"**사진 {i+1}**")
                col_a, col_b, col_c = st.columns([2, 4, 2])
                
                with col_a:
                    st.image(item["image"], use_column_width=True)
                with col_b:
                    st.session_state.image_issue_data[i]["issue"] = st.text_area("AI 작성 지적사항 (수정 가능)", value=item["issue"], height=100, key=f"i_issue_{i}")
                with col_c:
                    st.session_state.image_issue_data[i]["team"] = st.selectbox("담당부서", options=current_teams_img, index=current_teams_img.index(item["team"]) if item["team"] in current_teams_img else (len(current_teams_img)-1), key=f"i_team_{i}")
                st.markdown("---")

        st.header("3단계: 부서별 엑셀 통합 보고서 다운로드")
        st.markdown("📝 **보고서 상단에 인쇄될 정보를 입력해 주세요.**")
        col_h1, col_h2 = st.columns(2)
        with col_h1:
            r_title_img = st.text_input("보고서 제목", "현장 순회 점검 결과 보고서", key="i_r_title")
            r_date_img = st.text_input("보고 일자", datetime.datetime.now().strftime("%Y. %m. %d"), key="i_r_date")
            t_name_img = st.text_input("작성 부서", "식품안전팀", key="i_t_name")
        with col_h2:
            a_date_img = st.text_input("심사(점검) 일자", datetime.datetime.now().strftime("%Y. %m. %d"), key="i_a_date")
            a_agency_img = st.text_input("심사 기관(점검자)", "자체 점검", key="i_a_agency")
            a_purpose_img = st.text_input("심사(점검) 목적", "자체 위생 점검 및 시정조치", key="i_a_purpose")

        report_info_img = {
            'title': r_title_img, 'report_date': r_date_img, 'team_name': t_name_img,
            'audit_date': a_date_img, 'audit_agency': a_agency_img, 'audit_purpose': a_purpose_img
        }

        if st.button("📊 사진 기반 보고서 양식 엑셀 다운로드"):
            excel_data = create_excel_report(st.session_state.image_issue_data, current_teams_img, report_info_img)
            st.download_button(
                label="💾 '사진점검_통합보고서.xlsx' 다운로드",
                data=excel_data,
                file_name="사진점검_통합보고서.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="i_download"
            )
