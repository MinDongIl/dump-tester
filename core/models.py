from pydantic import BaseModel, Field


class QnAModel(BaseModel):
    topic: str = Field(description="문제의 핵심 주제를 짧게 요약 (예: 핵심 개념 이름)")
    explanation: str = Field(description="왜 이 정답이 옳은지, 오답은 왜 틀렸는지에 대한 한국어 상세 해설.")
    used_services: list[str] = Field(description="문제와 보기에서 언급된 주요 서비스/기술/개념 이름 리스트.")


class StudyNoteModel(BaseModel):
    content: str = Field(description="Study notes in markdown.")
