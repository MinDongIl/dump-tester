from pydantic import BaseModel, Field

class QnAModel(BaseModel):
    topic: str = Field(description="문제의 핵심 주제 (예: RDS 자격 증명 로테이션)")
    explanation: str = Field(description="왜 이 정답이 옳은지, 오답은 왜 틀렸는지에 대한 한국어 상세 해설.")
    used_services: list[str] = Field(description="문제와 보기에서 언급된 모든 주요 AWS 서비스 리스트.")
    
class StudyNoteModel(BaseModel):
    content: str = Field(description="Study notes in markdown.")

# 오답노트용 모델
class WrongAnswerAnalysisModel(BaseModel):
    topic: str = Field(description="문제의 핵심 주제 (예: RDS 자격 증명 로테이션)")
    tags: list[str] = Field(description="핵심 기술 태그 리스트")
    detailed_analysis: str = Field(description="마크다운 형식의 문제 상세 분석 및 해설")

# 키워드 정리용 모델
class KeywordPair(BaseModel):
    keyword: str = Field(description="문제에 등장하는 핵심 키워드")
    service_mapping: str = Field(description="해당 키워드와 연관된 AWS 서비스나 솔루션")

class KeywordListModel(BaseModel):
    items: list[KeywordPair]