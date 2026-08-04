import streamlit as st
import pandas as pd
import io
import google.generativeai as genai
from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.table import WD_TABLE_ALIGNMENT
import PyPDF2

# -----------------------------------------------------------------------------
# 1. 페이지 설정 및 초기화
# -----------------------------------------------------------------------------
st.set_page_config(page_title="심사 개선요구사항 자동 분류 시스템", layout="wide")
st.title("📋 심사 개선요구사항 자동 분류 및 보고서 생성기")
st.markdown("업체 심사 결과(파일 또는 텍스트)를 입력하면, AI가 **공장 내부 보고서 어조로 문장을 정제**한 후 부서별로 분류하여 통합 워드 양식을 생성합니다.")

if "df" not in st.session_state:
    st.session_state.df = pd.DataFrame(columns=["개선요구사항", "담당부서"])

TEAM_LIST = [
    "유제품가공팀", 
    "카톤포장팀", 
    "병포장팀", 
    "상온제품가공팀", 
    "상온제품포장팀", 
    "품질관리팀"
]

# -----------------------------------------------------------------------------
# 2. 파일 텍스트 추출 함수 (팩트 기반 로직)
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
                text += f"--- {sheet_name} ---\n"
                text += df.to_string(index=False) + "\n"
        elif file_name.endswith('.docx'):
            doc = Document(uploaded_file)
            for para in doc.paragraphs:
                text += para.text + "\n"
        else:
            # txt 또는 csv 등 일반 텍스트 파일
            text = uploaded_file.getvalue().decode("utf-8")
    except Exception as e:
        st.error(f"파일을 읽는 중 오류가 발생했습니다: {e}")

    return text

# -----------------------------------------------------------------------------
# 3. 사이드바: 톤앤매너 가이드 설정 및 API 키 검증 (st.secrets 활용)
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
        st.error("⚠️ API Key가 설정되지 않았습니다. .streamlit/secrets.toml 파일을 확인해 주세요.")
    
    st.markdown("---")
    st.header("📖 사내 용어 및 어조 가이드")
    st.markdown("AI가 문장을 정제할 때 적용할 규칙을 입력하세요.")
    
    default_tone_guide = """1. 종결어미: 모든 문장은 '~함', '~미흡', '~필요' 와 같은 명사형/개조식 문어체로 끝낼 것.
2. 용어 변환: '더럽다/지저분하다' -> '청결 상태 미흡' 또는 '오염됨'
3. 용어 변환: '우유/두유' -> '원유' 또는 '내용물'
4. 용어 변환: '기계' -> '설비'
5. 감정적 표현 배제: 객관적인 사실과 상태만 건조하게 기술할 것."""
    
    tone_guide = st.text_area(
        "보고서 톤앤매너 규칙", 
        value=default_tone_guide, 
        height=200
    )

    st.markdown("---")
    st.markdown("### 담당 부서 목록")
    for team in TEAM_LIST:
        st.markdown(f"- {team}")

# -----------------------------------------------------------------------------
# 4. 데이터 입력 및 AI 추출/변환 (1단계) - 파일 업로드 추가
# -----------------------------------------------------------------------------
st.header("1단계: 심사 결과 파일 업로드 및 AI 자동 분류")

col1, col2 = st.columns(2)
with col1:
    uploaded_file = st.file_uploader("📄 심사 결과 파일 업로드 (PDF, 엑셀, 워드, 텍스트)", type=['pdf', 'xlsx', 'xls', 'docx', 'txt', 'csv'])
with col2:
    raw_text = st.text_area("✍️ 또는 텍스트 직접 붙여넣기", height=150, placeholder="파일 대신 텍스트를 직접 입력할 수도 있습니다.")

if st.button("🚀 AI 추출 및 자동 분류 실행"):
    if not api_key_loaded:
        st.error("시스템에 API Key가 등록되지 않아 실행할 수 없습니다.")
    elif uploaded_file is None and not raw_text.strip():
        st.warning("분석할 파일이나 텍스트를 입력해 주세요.")
    else:
        with st.spinner("AI가 파일 데이터를 추출하여 공장 내부 어조로 변환하고 부서를 분류 중입니다..."):
            try:
                # 파일 데이터와 직접 입력 텍스트 병합
                combined_text = ""
                if uploaded_file is not None:
                    combined_text += extract_text_from_file(uploaded_file) + "\n"
                if raw_text.strip():
                    combined_text += raw_text.strip()

                model = genai.GenerativeModel('gemini-1.5-pro-latest')
                
                prompt = f"""
                당신은 식품 제조 현장의 품질 관리 및 외부 심사 지적사항을 분석하고 담당 부서를 배정하는 데이터 분류 전문가입니다.
                아래의 '심사 결과 텍스트'에서 개선요구사항(지적사항) 항목들만 명확히 추출하십시오.

                [톤앤매너 및 용어 변환 절대 규칙]
                추출된 항목은 외부 심사원의 원문 그대로 쓰지 말고, 아래의 '보고서 톤앤매너 규칙'을 엄격히 적용하여 
                공장 내부 보고서용 전문적이고 건조한 문어체(명사형 종결)로 재작성(Rewrite) 하십시오. 단, 원본의 객관적 팩트는 절대 훼손하지 마십시오.
                
                {tone_guide}

                [담당 부서 매칭 기준]
                각 항목의 원인과 공정을 분석하여 반드시 아래 6개의 '담당 부서' 중 가장 적합한 1개의 부서와 매칭하십시오.
                유제품가공팀, 카톤포장팀, 병포장팀, 상온제품가공팀, 상온제품포장팀, 품질관리팀

                [출력 절대 규칙 - 위반 시 시스템 오류 발생]
                1. 오직 "개선요구사항|담당부서" 형태의 파이프(|) 구분자로만 출력하십시오. (개선요구사항 열에는 톤앤매너가 적용되어 변환된 텍스트가 들어가야 합니다.)
                2. 첫 번째 줄은 무조건 헤더인 "개선요구사항|담당부서" 로 작성하십시오.
                3. 마크다운 기호(```), 인사말, 부연 설명, 번호 매기기 등은 절대 포함하지 마십시오. 오직 데이터만 출력하십시오.

                [심사 결과 텍스트]
                {combined_text}
                """
                
                response = model.generate_content(prompt)
                result_text = response.text.strip()
                
                if result_text.startswith("```"):
                    result_text = result_text.split("\n", 1)[1]
                if result_text.endswith("```"):
                    result_text = result_text.rsplit("\n", 1)[0]
                    
                data_io = io.StringIO(result_text)
                df_parsed = pd.read_csv(data_io, sep="|")
                
                if len(df_parsed.columns) == 2:
                    df_parsed.columns = ["개선요구사항", "담당부서"]
                    df_parsed["담당부서"] = df_parsed["담당부서"].apply(lambda x: x if x in TEAM_LIST else "품질관리팀")
                    st.session_state.df = df_parsed
                    st.success("AI 어조 변환 및 분류가 완료되었습니다. 아래 2단계에서 결과를 검수해 주세요.")
                else:
                    st.error("AI 출력 형식이 올바르지 않습니다. 다시 시도해 주세요.")
                    
            except Exception as e:
                st.error(f"오류가 발생했습니다: {e}")

# -----------------------------------------------------------------------------
# 5. 데이터 검수 및 수정 (2단계)
# -----------------------------------------------------------------------------
st.header("2단계: 분류 결과 검수 (체크 및 수정)")
st.markdown("AI가 내부 규격에 맞게 변환한 문장과 할당한 부서입니다. 표를 클릭하여 내용을 직접 수정할 수 있습니다.")

if not st.session_state.df.empty:
    edited_df = st.data_editor(
        st.session_state.df,
        use_container_width=True,
        num_rows="dynamic",
        column_config={
            "개선요구사항": st.column_config.TextColumn(
                "개선요구사항 (정제된 텍스트)", 
                width="large",
                required=True
            ),
            "담당부서": st.column_config.SelectboxColumn(
                "담당부서",
                options=TEAM_LIST,
                required=True
            )
        }
    )
    
    # -----------------------------------------------------------------------------
    # 6. 워드 보고서 생성 및 다운로드 (3단계)
    # -----------------------------------------------------------------------------
    st.header("3단계: 단일 워드 보고서(양식) 다운로드")
    
    def generate_word_report(df):
        doc = Document()
        
        title = doc.add_heading('현장 심사 개선요구사항 조치 보고서', level=0)
        title.alignment = 1 
        doc.add_paragraph("") 
        
        team_number = 1
        
        for team in TEAM_LIST:
            team_df = df[df['담당부서'] == team]
            
            if not team_df.empty:
                heading = doc.add_heading(f"{team_number}. {team}", level=1)
                
                item_number = 1
                for idx, row in team_df.iterrows():
                    circle_nums = ["①","②","③","④","⑤","⑥","⑦","⑧","⑨","⑩","⑪","⑫","⑬","⑭","⑮","⑯","⑰","⑱","⑲","⑳"]
                    prefix = circle_nums[item_number - 1] if item_number <= 20 else f"{item_number})"
                    
                    p = doc.add_paragraph()
                    run = p.add_run(f"{prefix} 지적사항 : {row['개선요구사항']}")
                    run.bold = True
                    
                    table = doc.add_table(rows=2, cols=2)
                    table.style = 'Table Grid'
                    table.alignment = WD_TABLE_ALIGNMENT.CENTER
                    table.autofit = False
                    
                    for cell in table.columns[0].cells:
                        cell.width = Cm(8.0)
                    for cell in table.columns[1].cells:
                        cell.width = Cm(8.0)
                    
                    hdr_cells = table.rows[0].cells
                    hdr_cells[0].text = "개선 조치 내역 (원인 및 조치결과)"
                    hdr_cells[1].text = "개선 후 사진 첨부란"
                    
                    for cell in hdr_cells:
                        for paragraph in cell.paragraphs:
                            for run in paragraph.runs:
                                run.bold = True
                    
                    row_cells = table.rows[1].cells
                    row_cells[0].text = "\n\n\n\n\n" 
                    row_cells[1].text = "\n\n\n\n\n" 
                    
                    doc.add_paragraph("") 
                    item_number += 1
                
                team_number += 1
                doc.add_page_break() 
                
        bio = io.BytesIO()
        doc.save(bio)
        return bio.getvalue()

    if st.button("📄 통합 워드 보고서 파일 생성"):
        word_data = generate_word_report(edited_df)
        
        st.download_button(
            label="💾 '심사_개선요구사항_통합보고서.docx' 다운로드",
            data=word_data,
            file_name="심사_개선요구사항_통합보고서.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
else:
    st.info("데이터를 입력하고 자동 분류를 실행하면 여기에 표가 나타납니다.")
