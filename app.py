import os
import json
import re
import streamlit as st
from core.services import (
    answer_question, 
    explain_service, 
    save_to_notion,
    save_wrong_note_to_notion,
    extract_and_save_keywords
)
from core.settings import settings
from notion_client import Client as NotionClient

# --- 환경 변수에서 데이터 파일 경로 불러오기 (기본값 설정) ---
DATA_FILE = settings.data_file_path

# --- 1. 데이터 로드 ---
@st.cache_data
def load_json_questions(filepath=DATA_FILE):
    if not os.path.exists(filepath):
        return []
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError:
        return []

# --- 페이지 기본 설정 (동적 타이틀 적용) ---
st.set_page_config(
    page_title=f"{settings.exam_title} 나만의 튜터", 
    page_icon=settings.exam_icon, 
    layout="wide"
)

# --- 2. 상태 관리 세팅 ---
if 'q_idx' not in st.session_state:
    st.session_state.q_idx = 0
if 'ai_result' not in st.session_state:
    st.session_state.ai_result = None
if 'ext_ai_result' not in st.session_state:
    st.session_state.ext_ai_result = None

questions = load_json_questions()

# --- 3. 사이드바 (메뉴 및 내비게이션) ---
st.sidebar.title(f"{settings.exam_icon} 튜터 메뉴")

app_mode = st.sidebar.radio(
    "학습 모드를 선택하세요:",
    ["📚 내 문제집 풀기", "🔎 외부 문제 분석기"]
)

st.sidebar.divider()

# ==========================================
# 모드 1: 내 문제집 풀기
# ==========================================
if app_mode == "📚 내 문제집 풀기":
    if not questions:
        st.warning(f"{DATA_FILE} 파일이 없거나 경로를 확인해주세요.")
        st.stop()

    st.sidebar.subheader("📚 학습 컨트롤러")
    jump_idx = st.sidebar.number_input(
        "🔢 문제 번호로 바로 이동", 
        min_value=1, 
        max_value=len(questions), 
        value=st.session_state.q_idx + 1,
        step=1
    )

    if jump_idx != st.session_state.q_idx + 1:
        st.session_state.q_idx = jump_idx - 1
        st.session_state.ai_result = None
        st.rerun()

    st.sidebar.write(f"현재 위치: **{st.session_state.q_idx + 1} / {len(questions)}**")
    st.sidebar.progress((st.session_state.q_idx + 1) / len(questions))

    col_prev, col_next = st.sidebar.columns(2)
    if col_prev.button("⬅️ 이전 문제"):
        if st.session_state.q_idx > 0:
            st.session_state.q_idx -= 1
            st.session_state.ai_result = None
            st.rerun()

    if col_next.button("다음 문제 ➡️"):
        if st.session_state.q_idx < len(questions) - 1:
            st.session_state.q_idx += 1
            st.session_state.ai_result = None
            st.rerun()

    current_q = questions[st.session_state.q_idx]

    # 동적 메인 타이틀
    st.title(f"{settings.exam_icon} {settings.exam_title} 학습 튜터")
    
    st.caption(f"현재 진행률: {st.session_state.q_idx + 1} 번째 문제")
    st.divider()

    st.info(f"**[문제 {st.session_state.q_idx + 1}]**\n\n{current_q.get('question', '')}")

    raw_options = current_q.get('options', '')
    formatted_options = re.sub(r'([A-E]\.)', r'\n\n**\1**', raw_options).strip()
    st.warning(f"**보기:**\n{formatted_options}")

    st.radio(
        "📝 내 정답 선택:", 
        ["A", "B", "C", "D", "E", "복수 정답"], 
        index=None, 
        horizontal=True, 
        key=f"q_{st.session_state.q_idx}"
    )

    st.divider()

    st.markdown("##### 📖 덤프 원본 정답")
    with st.expander(f"클릭하여 정답 확인 (문제 {st.session_state.q_idx + 1})", expanded=False):
        orig_ans = current_q.get('original_answer', '').strip()
        if orig_ans:
            st.success(orig_ans)
        else:
            st.error("원본 정답이 비어있습니다. AI 해설을 활용하세요.")

    st.write("") 
    st.markdown("##### 🤖 AI 심층 분석")
    
    if st.button("AI 상세 해설 및 노션 노트 생성", type="primary"):
        with st.spinner("AI가 분석 중입니다..."):
            try:
                result = answer_question(
                    settings.default_model, 
                    current_q.get("question", ""), 
                    current_q.get("options", ""), 
                    current_q.get("original_answer", "")
                )
                st.session_state.ai_result = result
            except Exception as e:
                st.error(f"오류 발생: {e}")

    if st.session_state.ai_result:
        res = st.session_state.ai_result
        st.divider()
        
        st.subheader(f"💡 AI 상세 해설: {res.topic}")
        st.write(res.explanation)
        
        st.divider()
        st.subheader("📚 핵심 개념 요약 저장")
        # '서비스'라는 단어를 '개념(Concept)'으로 범용화
        concepts = st.multiselect("저장할 핵심 개념 선택:", options=list(res.used_services), default=list(res.used_services))
        
        if st.button("📝 개념 요약 Notion에 저장하기"):
            notion_client = NotionClient(auth=settings.notion_api_key.get_secret_value())
            for concept in concepts:
                with st.spinner(f"[{concept}] 저장 중..."):
                    note = explain_service(settings.default_model, concept)
                    save_to_notion(notion_client, concept, note.content)
            st.success("개념 요약 전송 완료!")

        st.divider()
        st.subheader("📝 심화 학습 (오답노트 & 키워드)")
        col1, col2 = st.columns(2)
        
        notion_client = NotionClient(auth=settings.notion_api_key.get_secret_value())
        
        with col1:
            if st.button("❌ 오답노트 바로 전송 (기존 해설 활용)"):
                with st.spinner("해설 데이터를 노션에 복사 중입니다..."):
                    try:
                        save_wrong_note_to_notion(
                            notion_client, 
                            settings.notion_wrong_db_id, 
                            st.session_state.q_idx + 1,
                            res.topic,         
                            res.used_services, 
                            res.explanation    
                        )
                        st.success("오답노트가 노션에 저장되었습니다! ⚡")
                    except Exception as e:
                        st.error(f"오류 발생: {e}")

        with col2:
            if st.button("🔑 핵심 키워드 표 추출 및 전송"):
                with st.spinner("핵심 키워드 추출 중..."):
                    try:
                        extract_and_save_keywords(
                            notion_client, 
                            settings.notion_keyword_db_id, 
                            current_q.get('question', '')
                        )
                        st.success("키워드 정리가 노션 표에 추가되었습니다!")
                    except Exception as e:
                        st.error(f"오류 발생: {e}")


# ==========================================
# 모드 2: 외부 문제 분석기
# ==========================================
elif app_mode == "🔎 외부 문제 분석기":
    st.title("🔎 외부 문제 분석기")
    st.write("다른 사이트에서 풀다가 막힌 문제나 텍스트를 통째로 붙여넣으세요. 튜터가 분석해 드립니다.")
    
    external_text = st.text_area(
        "📝 문제, 보기, 해설 등을 자유롭게 붙여넣으세요:", 
        height=250, 
        placeholder="예시) 다음 중 데이터베이스 트랜잭션의 특징으로 알맞지 않은 것은? ..."
    )
    
    if st.button("🤖 붙여넣은 문제 AI 상세 해설 및 노션 저장", type="primary"):
        if not external_text.strip():
            st.warning("분석할 텍스트를 먼저 입력해주세요!")
        else:
            with st.spinner("AI가 입력된 외부 문제를 분석하고 있습니다..."):
                try:
                    result = answer_question(
                        settings.default_model, 
                        external_text, 
                        "", 
                        ""
                    )
                    st.session_state.ext_ai_result = result
                except Exception as e:
                    st.error(f"오류 발생: {e}")

    if st.session_state.ext_ai_result:
        res = st.session_state.ext_ai_result
        st.divider()
        st.subheader(f"💡 AI 상세 해설: {res.topic}")
        st.write(res.explanation)
        
        st.divider()
        st.subheader("📚 핵심 개념 요약 저장")
        ext_concepts = st.multiselect(
            "저장할 핵심 개념 선택:", 
            options=list(res.used_services), 
            default=list(res.used_services),
            key="ext_services_select"
        )
        
        if st.button("📝 외부 문제 개념 Notion에 저장하기", key="ext_save_btn"):
            notion_client = NotionClient(auth=settings.notion_api_key.get_secret_value())
            for concept in ext_concepts:
                with st.spinner(f"[{concept}] 저장 중..."):
                    note = explain_service(settings.default_model, concept)
                    save_to_notion(notion_client, concept, note.content)
            st.success("노션 전송 완료!")

        st.divider()
        st.subheader("📝 심화 학습 (오답노트 & 키워드)")
        ext_col1, ext_col2 = st.columns(2)
        
        notion_client = NotionClient(auth=settings.notion_api_key.get_secret_value())
        
        with ext_col1:
            if st.button("❌ 외부문제 오답노트 전송", key="ext_wrong_btn"):
                with st.spinner("해설 데이터를 노션에 복사 중입니다..."):
                    try:
                        save_wrong_note_to_notion(
                            notion_client, 
                            settings.notion_wrong_db_id, 
                            0, 
                            res.topic,
                            res.used_services,
                            res.explanation
                        )
                        st.success("외부 문제 오답노트 생성 완료!")
                    except Exception as e:
                        st.error(f"오류 발생: {e}")

        with ext_col2:
            if st.button("🔑 외부문제 키워드 추출 전송", key="ext_key_btn"):
                with st.spinner("핵심 키워드 추출 중..."):
                    try:
                        extract_and_save_keywords(
                            notion_client, 
                            settings.notion_keyword_db_id, 
                            external_text
                        )
                        st.success("외부 문제 키워드 정리 완료!")
                    except Exception as e:
                        st.error(f"오류 발생: {e}")