import os
import certifi
import json
import re
import httpx
import streamlit as st
from core.services import (
    answer_question, 
    explain_service, 
    save_to_notion,
    save_wrong_note_to_notion,
    extract_and_save_keywords
)
from core.settings import settings
from core.models import QnAModel
from notion_client import Client as NotionClient

# 🛡️ SSL 인증서 경로 강제 지정 (가장 먼저 실행되어야 함)
os.environ['SSL_CERT_FILE'] = certifi.where()
os.environ['REQUESTS_CA_BUNDLE'] = certifi.where()

# --- 환경 변수에서 데이터 파일 경로 불러오기 (기본값 설정) ---
DATA_FILE = settings.data_file_path

# --- 1. 데이터 로드 ---
@st.cache_data
def load_json_questions(filepath=DATA_FILE):
    if not os.path.exists(filepath):
        return []
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            questions = json.load(f)
    except json.JSONDecodeError:
        return []
    for q in questions:
        for k in ('question', 'options', 'original_answer'):
            q[k] = fix_mojibake(q.get(k) or '')
    return questions


def fix_mojibake(text: str) -> str:
    """PDF 추출 때 깨진 특수문자 복구 (예: 'ג€ role' -> '" role', 'n2ג€"highmem' -> 'n2-highmem')"""
    return text.replace('ג€"', '-').replace('ג€', '"').replace('"¢ ', '• ')


def norm_answer(ans: str) -> str:
    """'B, D' / 'b,d' / '' -> 'B,D' 형태로 정규화 (정답 뒤에 해설이 붙어 있어도 앞의 글자만 사용)"""
    m = re.match(r"\s*([A-F](?:\s*,\s*[A-F])*)\b", (ans or "").upper())
    return ",".join(sorted(re.findall(r"[A-F]", m.group(1)))) if m else ""


# --- AI 해설 캐시: 같은 문제는 AI를 다시 부르지 않음 ---
EXPLAIN_FILE = os.path.splitext(DATA_FILE)[0] + "_explanations.json"


def _load_explanations() -> dict:
    try:
        with open(EXPLAIN_FILE, encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def get_cached_explanation(q: dict):
    d = _load_explanations().get(str(q.get('id')))
    return QnAModel(**d) if d else None


def explain_cached(q: dict) -> QnAModel:
    res = get_cached_explanation(q)
    if res:
        return res
    res = answer_question(settings.default_model, q.get('question', ''), q.get('options', ''), q.get('original_answer', ''))
    if q.get('id') is not None:
        cache = _load_explanations()
        cache[str(q['id'])] = res.model_dump()
        tmp = EXPLAIN_FILE + ".tmp"
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
        os.replace(tmp, EXPLAIN_FILE)  # 쓰다가 끊겨도 기존 캐시가 깨지지 않게
    return res

# --- 페이지 기본 설정 (동적 타이틀 적용) ---
st.set_page_config(
    page_title=f"{settings.exam_title} 나만의 튜터", 
    page_icon=settings.exam_icon, 
    layout="wide"
)

# --- 2. 상태 관리 및 공통 객체 세팅 ---
if 'q_idx' not in st.session_state:
    st.session_state.q_idx = 0
if 'ai_result' not in st.session_state:
    st.session_state.ai_result = None
if 'ext_ai_result' not in st.session_state:
    st.session_state.ext_ai_result = None

# 💡 노션 클라이언트를 여기서 딱 한 번만 생성하여 전체 공유 (보안 무시 설정 포함)
notion_client = NotionClient(
    auth=settings.notion_api_key.get_secret_value(), 
    client=httpx.Client(verify=False)
)

questions = load_json_questions()

# --- 3. 사이드바 (메뉴 및 내비게이션) ---
st.sidebar.title(f"{settings.exam_icon} 튜터 메뉴")

app_mode = st.sidebar.radio(
    "학습 모드를 선택하세요:",
    ["📚 내 문제집 풀기", "📝 모의고사 모드", "🔎 외부 문제 분석기"]
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

    correct = norm_answer(current_q.get('original_answer', ''))
    letters = sorted(set(re.findall(r'(?:^|\s)([A-F])\.', raw_options))) or ["A", "B", "C", "D", "E"]
    n_ans = len(correct.split(",")) if correct else 1
    if n_ans > 1:
        picked = st.multiselect(f"📝 내 정답 선택 ({n_ans}개):", letters, max_selections=n_ans, key=f"q_{st.session_state.q_idx}")
    else:
        picked = st.radio("📝 내 정답 선택:", letters, index=None, horizontal=True, key=f"q_{st.session_state.q_idx}")
    mine = norm_answer(",".join(picked) if isinstance(picked, list) else (picked or ""))
    sub_key = f"submitted_{st.session_state.q_idx}"
    # 클릭 실수 방지: 제출 버튼을 눌러야 채점 (제출 후 답을 바꾸면 다시 제출해야 반영)
    if st.button("✅ 제출하고 채점", disabled=not (mine and len(mine.split(",")) == n_ans)):
        st.session_state[sub_key] = mine
    submitted = st.session_state.get(sub_key)
    if submitted and correct:
        if submitted == correct:
            st.success(f"⭕ 정답! (내 답 {submitted})")
        else:
            st.error(f"❌ 오답 · 내 답 {submitted} / 정답 **{correct}**")

    st.divider()

    st.markdown("##### 📖 덤프 원본 정답·해설")
    with st.expander("클릭하여 덤프 원본 확인 (해설이 있으면 AI 없이 먼저 확인)", expanded=False):
        orig_ans = current_q.get('original_answer', '').strip()
        if orig_ans:
            st.markdown(orig_ans)
        else:
            st.error("원본 정답이 비어있습니다. AI 해설을 활용하세요.")

    st.write("") 
    st.markdown("##### 🤖 AI 심층 분석")
    
    if st.button("AI 상세 해설 및 노션 노트 생성" + (" (저장된 해설·무료)" if get_cached_explanation(current_q) else ""), type="primary"):
        with st.spinner("AI가 분석 중입니다..."):
            try:
                st.session_state.ai_result = explain_cached(current_q)
            except Exception as e:
                st.error(f"오류 발생: {e}")

    if st.session_state.ai_result:
        res = st.session_state.ai_result
        st.divider()
        
        st.subheader(f"💡 AI 상세 해설: {res.topic}")
        st.write(res.explanation)
        
        st.divider()
        st.subheader("📚 핵심 개념 요약 저장")
        concepts = st.multiselect("저장할 핵심 개념 선택:", options=list(res.used_services), default=list(res.used_services))
        
        if st.button("📝 개념 요약 Notion에 저장하기"):
            for concept in concepts:
                with st.spinner(f"[{concept}] 저장 중..."):
                    note = explain_service(settings.default_model, concept)
                    save_to_notion(notion_client, concept, note.content)
            st.success("개념 요약 전송 완료!")

        st.divider()
        st.subheader("📝 심화 학습 (오답노트 & 키워드)")
        col1, col2 = st.columns(2)
        
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
                            res.explanation,
                            question=current_q.get('question', ''),
                            options=current_q.get('options', ''),
                            my_answer=st.session_state.get(f"submitted_{st.session_state.q_idx}") or mine,
                            correct_answer=current_q.get('original_answer', ''),
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
# 모드 3: 모의고사
# ==========================================
elif app_mode == "📝 모의고사 모드":
    import random
    import time
    import pandas as pd

    ss = st.session_state
    pool = [q for q in questions if norm_answer(q.get('original_answer', ''))]
    if not pool:
        st.warning(f"{DATA_FILE} 에 정답이 있는 문제가 없습니다.")
        st.stop()

    st.sidebar.subheader("📝 모의고사 설정")
    n = st.sidebar.number_input("문항 수", min_value=1, max_value=len(pool), value=min(50, len(pool)), step=5)
    if st.sidebar.button("🚀 새 모의고사 시작", type="primary"):
        ss.mock_qs = random.sample(pool, int(n))
        ss.mock_round = ss.get('mock_round', 0) + 1
        ss.mock_start = time.time()
        ss.mock_done = False
        st.rerun()

    st.title(f"📝 {settings.exam_title} 모의고사")
    if 'mock_qs' not in ss:
        st.info("왼쪽에서 문항 수를 정하고 **새 모의고사 시작**을 누르세요. 전체 문제에서 랜덤 출제됩니다.")
        if not any(q.get('domain') for q in pool):
            st.caption("💡 도메인별 분석을 보려면 먼저 `python -m tools.domain_tagger` 로 문제에 도메인을 태깅하세요.")
        st.stop()

    qs, rnd = ss.mock_qs, ss.mock_round

    def key_of(i):
        return f"mock_{rnd}_{i}"

    # --- 응시 화면 ---
    if not ss.mock_done:
        st.caption(f"총 {len(qs)}문항 · 시작 {time.strftime('%H:%M', time.localtime(ss.mock_start))} · 다 풀고 맨 아래 **제출** 버튼")
        with st.form(f"mock_form_{rnd}"):
            for i, q in enumerate(qs):
                st.markdown(f"#### {i + 1}.")
                st.write(q.get('question', ''))
                opts = q.get('options', '')
                st.markdown(re.sub(r'([A-F]\.)', r'\n\n**\1**', opts).strip())
                letters = sorted(set(re.findall(r'(?:^|\s)([A-F])\.', opts))) or ["A", "B", "C", "D"]
                n_ans = len(norm_answer(q['original_answer']).split(","))
                if n_ans > 1:
                    st.multiselect(f"답 {n_ans}개 선택", letters, max_selections=n_ans, key=key_of(i))
                else:
                    st.radio("답 선택", letters, index=None, horizontal=True, key=key_of(i))
                st.divider()
            if st.form_submit_button("✅ 제출하고 채점하기", type="primary"):
                ss.mock_done = True
                ss.mock_elapsed = time.time() - ss.mock_start
                st.rerun()
        st.stop()

    # --- 채점 ---
    rows = []
    for i, q in enumerate(qs):
        picked = ss.get(key_of(i))
        mine = norm_answer(",".join(picked) if isinstance(picked, list) else (picked or ""))
        correct = norm_answer(q['original_answer'])
        rows.append({
            "no": i + 1, "id": q.get('id'), "q": q,
            "도메인": q.get('domain') or "미분류", "서비스": q.get('service') or "미분류",
            "내 답": mine or "무응답", "정답": correct, "정답여부": mine == correct,
        })
    df = pd.DataFrame(rows)
    total, right = len(df), int(df["정답여부"].sum())

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("점수", f"{right} / {total}")
    c2.metric("정답률", f"{right / total:.0%}")
    c3.metric("오답률", f"{1 - right / total:.0%}")
    c4.metric("소요 시간", f"{int(ss.mock_elapsed // 60)}분")

    st.subheader("📊 도메인별 정답률 (약한 순)")
    dom = df.groupby("도메인")["정답여부"].agg(문항수="count", 정답="sum")
    dom["정답률"] = (dom["정답"] / dom["문항수"] * 100).round(0)
    dom = dom.sort_values("정답률")
    st.dataframe(dom, use_container_width=True)
    st.bar_chart(dom["정답률"], horizontal=True)
    weakest = dom.index[0]
    st.error(f"가장 약한 도메인: **{weakest}** (정답률 {dom.loc[weakest, '정답률']:.0f}%)")

    wrong = df[~df["정답여부"]]
    if not wrong.empty:
        st.subheader("🎯 자주 틀린 서비스/개념 TOP 10")
        st.dataframe(wrong["서비스"].value_counts().head(10).rename("오답 수"), use_container_width=True)

    st.divider()
    st.subheader(f"❌ 오답 목록 ({len(wrong)}개)")

    def save_mock_wrong(r):
        q = r["q"]
        res = explain_cached(q)
        save_wrong_note_to_notion(
            notion_client, settings.notion_wrong_db_id, q.get('id', r["no"]),
            res.topic, res.used_services, res.explanation,
            question=q['question'], options=q['options'],
            my_answer=r["내 답"], correct_answer=q['original_answer'],
        )
        return res

    if not wrong.empty and st.button(f"📥 오답 {len(wrong)}개 전부 AI 해설 + 노션 오답노트 저장"):
        bar = st.progress(0.0)
        fails = []
        for k, (_, r) in enumerate(wrong.iterrows(), 1):
            try:
                save_mock_wrong(r)
            except Exception as e:
                fails.append(f"#{r['id']}: {e}")
            bar.progress(k / len(wrong), text=f"{k}/{len(wrong)} 저장 중...")
        st.success(f"{len(wrong) - len(fails)}개 저장 완료!")
        for f in fails:
            st.error(f)

    for _, r in wrong.iterrows():
        q = r["q"]
        with st.expander(f"{r['no']}번 (원본 #{r['id']}) · {r['도메인']} · {r['서비스']} — 내 답 {r['내 답']} / 정답 {r['정답']}"):
            st.write(q['question'])
            st.markdown(re.sub(r'([A-F]\.)', r'\n\n**\1**', q['options']).strip())
            if st.button("🤖 AI 해설 보고 오답노트 저장", key=f"mock_save_{rnd}_{r['no']}"):
                with st.spinner("AI 해설 생성 + 노션 저장 중..."):
                    try:
                        st.markdown(save_mock_wrong(r).explanation)
                        st.success("오답노트 저장 완료!")
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
            for concept in ext_concepts:
                with st.spinner(f"[{concept}] 저장 중..."):
                    note = explain_service(settings.default_model, concept)
                    save_to_notion(notion_client, concept, note.content)
            st.success("노션 전송 완료!")

        st.divider()
        st.subheader("📝 심화 학습 (오답노트 & 키워드)")
        ext_col1, ext_col2 = st.columns(2)
        
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
                            res.explanation,
                            question=external_text,
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