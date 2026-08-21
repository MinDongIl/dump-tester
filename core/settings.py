from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # .env 파일을 자동으로 읽어오도록 설정 (prefix 제거)
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # ==========================================
    # 📝 UI & 시험 기본 설정 (app.py 하드코딩 방지)
    # ==========================================
    exam_title: str = "자격증"  # 예: "AWS SAA", "정보처리기사" 등
    exam_icon: str = "☁️"
    data_file_path: str = "data/example.json"

    # ==========================================
    # 🤖 AI 모델 설정
    # ==========================================
    default_model: str = "gpt-4o"       # 범용적으로 많이 쓰는 모델로 기본값 변경
    alternative_model: str = "gemini-1.5-pro"
    
    # ==========================================
    # 📚 노션 데이터베이스 ID 설정
    # ==========================================
    notion_database_id: str = ""
    notion_wrong_db_id: str = ""      # 오답노트 DB
    notion_keyword_db_id: str = ""    # 키워드 정리 DB
    
    # ==========================================
    # 🔑 API Keys
    # ==========================================
    notion_api_key: SecretStr = SecretStr("")
    anthropic_api_key: SecretStr = SecretStr("")
    openai_api_key: SecretStr = SecretStr("")
    google_api_key: SecretStr = SecretStr("")

settings = Settings()

__all__ = ["settings"]