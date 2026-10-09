"""덤프 JSON의 각 문제에 domain(시험 공식 도메인) / service(핵심 서비스) 필드를 AI로 태깅한다.
실행: 프로젝트 루트에서  python -m tools.domain_tagger
- 이미 domain이 있는 문제는 건너뛰므로 중간에 끊겨도 다시 실행하면 이어서 진행됨
- 원본은 <파일>.bak 으로 한 번 백업
"""
import json
import os
import shutil
from textwrap import dedent

from langchain_core.output_parsers import PydanticOutputParser, StrOutputParser
from langchain_core.prompts import PromptTemplate
from pydantic import BaseModel

from core.services import _clean_json_string
from core.settings import settings
from core.utils import llm_model_factory

# shortcut: GCP ACE 공식 시험 가이드 기준. 다른 시험이면 이 목록만 바꾸면 됨
DOMAINS = [
    "1. 클라우드 솔루션 환경 설정",
    "2. 클라우드 솔루션 계획 및 구현",
    "3. 클라우드 솔루션 운영 보장",
    "4. 액세스 및 보안 구성",
]
BATCH = 25


class Tag(BaseModel):
    id: int
    domain: str
    service: str


class TagList(BaseModel):
    items: list[Tag]


def tag_batch(chain, parser, batch):
    text = "\n\n".join(f"[id={q['id']}]\n{q['question']}\n{q['options']}" for q in batch)
    raw = chain.invoke({"questions": text})
    return {t.id: t for t in parser.parse(_clean_json_string(raw)).items}


def main():
    path = settings.data_file_path
    with open(path, encoding="utf-8") as f:
        questions = json.load(f)
    if not os.path.exists(path + ".bak"):
        shutil.copy(path, path + ".bak")

    parser = PydanticOutputParser(pydantic_object=TagList)
    prompt = PromptTemplate(
        template=dedent("""\
            당신은 {exam_title} 시험 전문가입니다. 아래 각 문제를 분류하세요.
            - domain: 반드시 다음 중 하나를 글자 그대로 선택: {domains}
            - service: 문제의 정답과 직결된 핵심 서비스/개념 1개 (짧은 영어 이름, 예: IAM, GKE, Cloud Storage)
            모든 id에 대해 빠짐없이 답하세요.

            {format}

            <문제들>
            {questions}"""),
        input_variables=["questions"],
        partial_variables={
            "exam_title": settings.exam_title,
            "domains": " | ".join(DOMAINS),
            "format": parser.get_format_instructions(),
        },
    )
    chain = prompt | llm_model_factory(settings.default_model) | StrOutputParser()

    todo = [q for q in questions if q.get("domain") not in DOMAINS]
    print(f"태깅 대상 {len(todo)} / 전체 {len(questions)}")
    for i in range(0, len(todo), BATCH):
        batch = todo[i:i + BATCH]
        try:
            tags = tag_batch(chain, parser, batch)
        except Exception as e:
            print(f"⚠️ 배치 {i // BATCH + 1} 실패 (다시 실행하면 이어서 진행): {e}")
            continue
        for q in batch:
            t = tags.get(q["id"])
            if t and t.domain in DOMAINS:
                q["domain"], q["service"] = t.domain, t.service
        with open(path, "w", encoding="utf-8") as f:  # 배치마다 저장 → 중단돼도 진행분 보존
            json.dump(questions, f, ensure_ascii=False, indent=2)
        print(f"✅ {min(i + BATCH, len(todo))} / {len(todo)}")

    left = sum(q.get("domain") not in DOMAINS for q in questions)
    print("완료!" if not left else f"미분류 {left}개 남음 → 한 번 더 실행하세요.")


if __name__ == "__main__":
    main()
