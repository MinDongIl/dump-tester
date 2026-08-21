import os
import json
import re
import time
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from core.utils import llm_model_factory
from core.settings import settings

def map_and_translate_txt_answers():
    # 🚨 파일 경로를 맞춰주세요
    json_file = "data/questions.json"
    txt_file = "data/dump.txt"

    if not os.path.exists(json_file) or not os.path.exists(txt_file):
        print(f"❌ {json_file} 또는 {txt_file} 파일을 찾을 수 없습니다.")
        return

    # JSON과 TXT 파일 읽기
    with open(json_file, 'r', encoding='utf-8') as f:
        questions = json.load(f)

    with open(txt_file, 'r', encoding='utf-8') as f:
        content = f.read()

    # 점선(-----) 기준으로 TXT 파일을 문제별로 쪼개기
    blocks = re.split(r'-{20,}', content)
    valid_blocks = [b.strip() for b in blocks if b.strip()]

    print(f"📄 JSON 파일 문제: {len(questions)}개")
    print(f"📄 TXT 파일 블록: {len(valid_blocks)}개")

    model = llm_model_factory(settings.default_model)

    # 💡 [핵심] AI에게 TXT 원본을 던져주고 알아서 정답/해설만 번역해오라고 지시
    prompt = PromptTemplate(
        template="""당신은 AWS SAA 시험 문제 전문 번역가입니다.
        아래에 제공된 텍스트는 덤프 파일에서 발췌한 1개의 문제 블록입니다. (문제 질문, 정답, 해설이 섞여 있습니다.)

        [지시사항]
        1. 이 텍스트에서 '문제 질문(Question)' 부분은 무시하세요.
        2. '정답(예: B. Use AWS Config...)'과 그 뒤에 이어지는 '해설(Explanation)' 부분만 찾아내세요.
        3. 찾아낸 정답과 해설을 **가독성 좋은 자연스러운 한국어로 번역**하세요.
        4. 출력은 오직 번역된 정답과 해설만 제공하세요.

        <덤프 텍스트 원본>
        {text}
        """,
        input_variables=["text"]
    )
    chain = prompt | model | StrOutputParser()

    translated_count = 0
    # PDF와 TXT의 문제 순서가 동일하다고 전제하고 1:1 매핑 진행
    for i, q in enumerate(questions):
        if i >= len(valid_blocks):
            break

        current_ans = str(q.get('original_answer', ''))
        # 이미 한글화된 정답이 들어가 있다면 건너뛰기 (비용/시간 절약)
        if len(current_ans) > 15 and not re.search(r'[a-zA-Z]{15,}', current_ans):
            continue

        block = valid_blocks[i]
        print(f"🔄 [{i+1}/{len(questions)}] TXT에서 정답 추출 및 한글 번역 중...")

        try:
            kor_ans = chain.invoke({"text": block})
            q['original_answer'] = kor_ans.strip()
            translated_count += 1

            # 실시간 저장 (중간에 에러나도 날아가지 않음)
            with open(json_file, 'w', encoding='utf-8') as f:
                json.dump(questions, f, ensure_ascii=False, indent=2)

        except Exception as e:
            print(f"⚠️ {i+1}번 문제 에러 발생: {e}")

        time.sleep(1) # 유료 API 쿨타임

    print(f"🎉 작업 완료! TXT 파일의 정답과 해설이 한글로 번역되어 JSON 파일에 완벽히 병합되었습니다.")

if __name__ == "__main__":
    map_and_translate_txt_answers()