import fitz  # PyMuPDF
import json
import re
import os

def extract_from_pdf(pdf_path, output_json_path):
    print(f"📄 '{pdf_path}' 파일에서 텍스트를 추출합니다...")
    
    try:
        # 1. PDF 열고 전체 텍스트 읽어오기
        doc = fitz.open(pdf_path)
        full_text = ""
        for page in doc:
            full_text += page.get_text()
        doc.close()
    except Exception as e:
        print(f"❌ PDF 읽기 오류 발생: {e}")
        return

    # 2. 'Q숫자' 패턴을 기준으로 전체 텍스트를 문제 단위로 쪼개기
    # (?=Q\d+) : 'Q' 뒤에 숫자가 오는 부분 앞에서 문자열을 나눕니다.
    raw_questions = re.split(r'\n(?=Q\d+)', full_text)
    
    parsed_data = []
    
    for raw_q in raw_questions:
        raw_q = raw_q.strip()
        if not raw_q.startswith('Q'):
            continue
            
        # 문제 번호 추출 (예: Q1 -> 1)
        q_num_match = re.search(r'^Q(\d+)', raw_q)
        if not q_num_match:
            continue
        q_id = int(q_num_match.group(1))
        
        # 3. 문제와 보기 분리하기 (줄바꿈 후 A. 또는 A) 로 시작하는 부분 찾기)
        options_match = re.search(r'\n([A-E][\.\)])', raw_q)
        
        if options_match:
            split_idx = options_match.start()
            
            # 문제 내용: 시작 부분의 'Q1' 글자를 날리고 남은 텍스트
            question_text = re.sub(r'^Q\d+\s*', '', raw_q[:split_idx]).strip()
            
            # 보기 및 정답 영역: A. 이후의 텍스트
            rest_text = raw_q[split_idx:].strip()
            
            # 4. 정답(Answer) 추출하기
            # 문서에 'Answer: A' 또는 'Correct Answer: B' 형태로 적혀있다고 가정
            answer_text = ""
            ans_match = re.search(r'(?:Answer|Correct Answer)[\s\:]+([A-Ea-e,\s]+)', rest_text, re.IGNORECASE)
            
            if ans_match:
                answer_text = ans_match.group(1).strip()
                # 정답 문구는 보기 텍스트에서 잘라내기
                options_text = rest_text[:ans_match.start()].strip()
            else:
                options_text = rest_text
                
            # JSON 구조로 조립
            parsed_data.append({
                "id": q_id,
                "question": question_text,
                "options": options_text,
                "original_answer": answer_text
            })

    # 5. JSON 파일로 예쁘게 저장하기
    os.makedirs(os.path.dirname(output_json_path), exist_ok=True)
    with open(output_json_path, 'w', encoding='utf-8') as f:
        json.dump(parsed_data, f, ensure_ascii=False, indent=2)
        
    print(f"✅ 총 {len(parsed_data)}개의 문제를 성공적으로 추출하여 '{output_json_path}'에 저장했습니다!")

if __name__ == "__main__":
    # 💡 덤프 PDF 파일이 있는 경로와 저장할 JSON 파일 경로를 입력하세요.
    PDF_FILE = "data/GCP-ACE.pdf"
    JSON_FILE = "data/questions_GCP_ACE.json"
    
    extract_from_pdf(PDF_FILE, JSON_FILE)