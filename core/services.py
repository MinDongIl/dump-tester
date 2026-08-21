from typing import cast, List
from pydantic import BaseModel, Field
from core.models import QnAModel, StudyNoteModel
from core.utils import llm_model_factory
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import PydanticOutputParser, StrOutputParser
from textwrap import dedent
from notion_client import Client as NotionClient

from core.settings import settings
from notionize import notionize

# ==========================================
# 공통 유틸리티 함수
# ==========================================

def _clean_json_string(raw_str: str) -> str:
    cleaned = raw_str.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    return cleaned.strip()

# ==========================================
# 학습 튜터 핵심 기능
# ==========================================

def answer_question(model_name: str, question: str, options: str, answer: str) -> QnAModel:
    parser = PydanticOutputParser(pydantic_object=QnAModel)
    prompt = PromptTemplate(
        template=dedent("""\
            당신은 {exam_title} 시험 전문가이자 튜터입니다.
            제공된 문제와 정답을 바탕으로 상세한 분석을 수행하세요.

            <과업>
            1. **모든 설명은 반드시 한국어로 작성하세요.**
            2. 이 문제의 핵심 주제(topic)를 짧게 요약하세요. (예: 핵심 개념 이름)
            3. 왜 이 정답이 옳은지, 그리고 오답들은 왜 틀렸는지 기술적/이론적 근거를 들어 상세히 설명하세요.
            4. 💡 문제와 보기에서 언급된 주요 개념/기술/서비스 이름을 추출하되, 노션 태그로 사용해야 하므로 **절대 괄호()나 쉼표(,)를 포함하지 마세요**. 오직 단일 단어로만 압축해서 리스트를 만드세요.
            </과업>

            <format>
            {format}
            </format>

            🚨 주의: JSON 값 내부에 큰따옴표(")를 직접 쓰지 마세요. 필요하면 작은따옴표(')를 쓰세요.

            <문제>
            {question}
            </문제>

            <보기>
            {options}
            </보기>

            <원본 정답 및 해설>
            {answer}
            </원본 정답 및 해설>"""),
        input_variables=["question", "options", "answer", "format"],
        partial_variables={
            "format": parser.get_format_instructions(),
            "exam_title": settings.exam_title # 💡 .env에서 설정한 과목명 자동 주입
        },
    )
    model = llm_model_factory(model_name)
    chain = prompt | model | StrOutputParser()
    raw_result = chain.invoke({"question": question, "options": options, "answer": answer})
    cleaned_json = _clean_json_string(raw_result)
    result = parser.parse(cleaned_json)
    return cast(QnAModel, result)

def explain_service(model_name: str, service_name: str) -> StudyNoteModel:
    parser = PydanticOutputParser(pydantic_object=StudyNoteModel)
    prompt = PromptTemplate(
        template=dedent("""\
            당신은 {exam_title} 전문 강사입니다. 요청받은 핵심 개념(또는 서비스)에 대해 **반드시 한국어로** 요약 노트를 작성하세요.

            <과업>
            1. 해당 개념의 정의, 주요 특징, 그리고 {exam_title} 시험에 자주 나오는 핵심 포인트를 정리하세요.
            2. 마크다운의 리스트 형식(- 항목)을 사용하여 읽기 쉽게 작성하세요.
            3. 모든 내용은 한국어로 작성해야 합니다.
            </과업>
            
            <format>
            {format}
            </format>
            
            🚨 주의: JSON 값 내부에 큰따옴표(")를 쓰지 마세요.

            <대상 개념>
            {input}
            </대상 개념>"""),
        input_variables=["input", "format"],
        partial_variables={
            "format": parser.get_format_instructions(),
            "exam_title": settings.exam_title
        },
    )
    model = llm_model_factory(model_name)
    chain = prompt | model | StrOutputParser()
    raw_result = chain.invoke({"input": service_name})
    cleaned_json = _clean_json_string(raw_result)
    result = parser.parse(cleaned_json)
    return cast(StudyNoteModel, result)

def save_to_notion(
    notion_client: NotionClient, service_name: str, content: str
) -> None:
    print("🔥 학습 노트를 Notion에 저장합니다...")
    notion_client.pages.create(
        parent={"database_id": settings.notion_database_id},
        icon={"type": "emoji", "emoji": "📚"},
        properties={
            "이름": {  
                "title": [
                    {
                        "type": "text",
                        "text": {"content": f"{service_name} 학습 요약"},
                    }
                ]
            },
            "Tags": {  
                "multi_select": [
                    {"name": settings.exam_title},
                    {"name": service_name},
                ]
            },
        },
        children=notionize(content),
    )


# ==========================================
# 심화 학습 (오답노트 초고속 전송 및 키워드 추출)
# ==========================================

class KeywordPair(BaseModel):
    keyword: str = Field(description="문제에 등장하는 핵심 키워드 (여러 단어일 경우 쉼표로 연결 가능)")
    service_mapping: str = Field(description="해당 키워드와 연관된 정답 개념, 기술 또는 서비스명")
    category: str = Field(description="해당 개념의 대분류 카테고리 (단일 단어로 작성하며, 절대로 쉼표를 포함하지 마세요)")

class KeywordListModel(BaseModel):
    items: List[KeywordPair]

def save_wrong_note_to_notion(
    notion_client: NotionClient, db_id: str, q_no: int, topic: str, tags: list, explanation: str
) -> None:
    print(f"❌ 기존 해설을 활용하여 오답노트를 Notion에 직접 저장합니다... (문제 {q_no}번)")
    
    safe_tags = []
    for tag in tags:
        clean_tag = tag.replace(",", " ").strip()
        clean_tag = clean_tag.split("(")[0].strip()
        if clean_tag:
            safe_tags.append({"name": clean_tag})

    notion_client.pages.create(
        parent={"database_id": db_id},
        icon={"type": "emoji", "emoji": "❌"},
        properties={
            "문제 요약": { 
                "title": [
                    {
                        "type": "text",
                        "text": {"content": f"문제 {q_no}번 - {topic}"},
                    }
                ]
            },
            "Tags": { 
                "multi_select": safe_tags  
            }
        },
        children=notionize(explanation)
    )

def extract_and_save_keywords(
    notion_client: NotionClient, db_id: str, text: str, model_name: str = settings.default_model
) -> None:
    parser = PydanticOutputParser(pydantic_object=KeywordListModel)
    prompt = PromptTemplate(
        template=dedent("""\
            제공된 문제 텍스트에서 정답을 파악한 뒤, {exam_title} 시험에 자주 나오는 **'핵심 요구사항(키워드) - 정답 개념 - 카테고리'** 매핑 공식을 추출하세요.
            오답 보기에 대한 정보는 철저히 무시하고, 오직 '어떤 조건일 때 어떤 개념이 정답인지'만 정리하세요.
            
            🚨 [작성 규칙]
            1. '키워드' 항목에는 문제에서 요구하는 **핵심 제약 조건**을 반드시 포함하여 쉼표(,)로 묶어주세요.
            2. '확인 사항(service_mapping)'에는 해당 요구사항을 해결하는 **정답 개념/기술/서비스명**만 깔끔하게 적으세요.
            3. 단, '카테고리' 항목은 노션의 선택 속성이므로 **절대로 쉼표(,)를 포함해서는 안 됩니다.** 여러 카테고리가 겹친다면 가장 핵심적인 단일 단어 하나만 선택하세요.
            4. 모든 내용은 한국어로 작성하세요.
            
            {format_instructions}
            
            <텍스트>
            {text}"""),
        input_variables=["text"],
        partial_variables={
            "format_instructions": parser.get_format_instructions(),
            "exam_title": settings.exam_title
        },
    )
    model = llm_model_factory(model_name)
    chain = prompt | model | StrOutputParser()
    raw_result = chain.invoke({"text": text})
    cleaned_json = _clean_json_string(raw_result)
    result = parser.parse(cleaned_json)
    
    print(f"🔑 키워드를 Notion 표에 저장합니다... (총 {len(result.items)}개)")
    for item in result.items:
        safe_category = item.category.replace(",", " ").strip()
        
        notion_client.pages.create(
            parent={"database_id": db_id},
            icon={"type": "emoji", "emoji": "🔑"},
            properties={
                "키워드": {
                    "title": [
                        {
                            "type": "text",
                            "text": {"content": item.keyword},
                        }
                    ]
                },
                "확인 사항": {
                    "rich_text": [
                        {
                            "type": "text",
                            "text": {"content": item.service_mapping},
                        }
                    ]
                },
                "카테고리": {
                    "select": {
                        "name": safe_category 
                    }
                }
            }
        )