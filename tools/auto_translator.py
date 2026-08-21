import os
import time
import json
from pypdf import PdfReader
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from pydantic import BaseModel, Field
from core.utils import llm_model_factory
from core.settings import settings

# --- 1. 출력할 JSON 데이터 구조 정의 ---
class QuestionItem(BaseModel):
    id: int = Field(description="문제 번호 (예: 1, 2, 3)")
    question: str = Field(description="번역된 한글 문제")
    options: str = Field(description="번역된 한글 보기 (A, B, C, D 형식으로 묶어서)")
    original_answer: str = Field(description="영어 원본 정답 및 해설")

class QuestionList(BaseModel):
    items: list[QuestionItem]

# --- 2. PDF 텍스트 추출 함수 ---
def extract_text_from_pdf(pdf_path, start_page=0, num_pages=5):
    reader = PdfReader(pdf_path)
    text = ""
    end_page = min(start_page + num_pages, len(reader.pages))
    for i in range(start_page, end_page):
        page_text = reader.pages[i].extract_text()
        if page_text:
            text += page_text + "\n"
    return text, end_page, len(reader.pages)

# --- 3. 자동 번역 및 파싱 실행 ---
def run_auto_translator():
    pdf_path = "data/AWS Certified Solutions Architect Associate SAA-C03.pdf"
    output_file = "data/questions.json"
    
    if not os.path.exists(pdf_path):
        print("❌ PDF 파일을 찾을 수 없습니다. 경로를 확인해주세요.")
        return

    # 이미 번역된 파일이 있다면 이어서 쓸 수 있도록 로드
    all_questions = []
    if os.path.exists(output_file):
        with open(output_file, 'r', encoding='utf-8') as f:
            try:
                all_questions = json.load(f)
                print(f"✅ 기존 파일 로드 완료: {len(all_questions)}문제")
            except:
                pass

    # AI 모델 및 프롬프트 준비 (가장 빠르고 저렴한 flash 모델 사용 권장)
    model = llm_model_factory(settings.default_model)
    parser = JsonOutputParser(pydantic_object=QuestionList)
    
    prompt = PromptTemplate(
        template="""당신은 AWS SAA 자격증 시험 문제를 정리하는 어시스턴트입니다.
        아래에 제공된 텍스트(PDF에서 추출함)에서 AWS 문제들을 찾아서 다음 형식의 JSON 배열로 만들어주세요.
        
        규칙:
        1. 문제는 자연스러운 한국어로 번역하세요.
        2. 보기(A,B,C,D)도 한국어로 번역해서 하나의 문자열로 합치세요.
        3. 정답(Answer)이나 해설이 있다면 영어 원본 그대로 'original_answer'에 넣으세요.
        4. 텍스트가 잘렸거나 불완전한 문제는 무시하세요.
        5. "문자열 안에 큰따옴표(\")를 사용할 경우 반드시 이스케이프(\\") 처리하거나 작은따옴표로 바꾸세요."

        <Format>
        {format_instructions}
        </Format>

        <Text>
        {text}
        </Text>
        """,
        input_variables=["text"],
        partial_variables={"format_instructions": parser.get_format_instructions()}
    )
    
    chain = prompt | model | parser

    # 10페이지씩 끊어서 번역 진행 (과부하 방지)
    current_page = 1
    total_pages = PdfReader(pdf_path).pages
    batch_size = 10

    print(f"🚀 총 {len(total_pages)}페이지 번역 작업을 시작합니다...")
    
    while current_page < len(total_pages):
        print(f"📖 {current_page + 1} ~ {current_page + batch_size} 페이지 텍스트 추출 중...")
        text_chunk, next_page, _ = extract_text_from_pdf(pdf_path, current_page, batch_size)
        
        if len(text_chunk.strip()) > 50:
            try:
                print("🧠 AI에게 번역 및 JSON 변환 요청 중...")
                result = chain.invoke({"text": text_chunk})
                
                if "items" in result:
                    all_questions.extend(result["items"])
                    print(f"✅ {len(result['items'])}문제 추가 완료! (현재 총 {len(all_questions)}문제)")
                
                # 파일에 즉시 저장 (중간에 에러나도 날아가지 않도록)
                with open(output_file, 'w', encoding='utf-8') as f:
                    json.dump(all_questions, f, ensure_ascii=False, indent=2)
                    
            except Exception as e:
                print(f"⚠️ 에러 발생 (페이지 {current_page}): {e}")
                print("잠시 후 다음 페이지를 계속 진행합니다.")
        
        
        time.sleep(1)
        
        current_page = next_page

    print("🎉 모든 번역 작업이 완료되었습니다! data/questions.json 파일을 확인하세요.")

if __name__ == "__main__":
    run_auto_translator()