import json
import re

def id_mapper():
    json_file = "data/questions.json"
    txt_file = "data/dump.txt" 

    with open(json_file, 'r', encoding='utf-8') as f:
        questions = json.load(f)
    with open(txt_file, 'r', encoding='utf-8') as f:
        content = f.read()

    # 1. 쓸데없는 점선(----) 싹 다 지워버리기 (방해만 됨)
    content = re.sub(r'-{5,}', '', content)
    # 맨 앞에 줄바꿈 하나 추가 (첫 문제 인식을 위해)
    content = "\n" + content

    # 2. 💡 [핵심] 점선 대신, "번호가 시작되는 부분"을 기준으로 문서를 산산조각 냄
    # IMP>>>>> 든, Question 이든 상관없이 [숫자 + ] 또는 .] 패턴 앞에서 무조건 자름
    split_pattern = r'\n(?=\s*(?:IMP>+\s*)?(?:Question\s*#?\s*)?\d+\s*[\]\.])'
    blocks = re.split(split_pattern, content, flags=re.IGNORECASE)

    txt_answers_dict = {}
    for block in blocks:
        block = block.strip()
        if not block: continue
        
        # 3. 잘라낸 덩어리에서 진짜 번호(ID)만 쏙 빼오기
        id_match = re.search(r'^\s*(?:IMP>+\s*)?(?:Question\s*#?\s*)?(\d+)\s*[\]\.]', block, re.IGNORECASE)
        
        if id_match:
            q_num = int(id_match.group(1))
            
            # 4. 💡 [가위질] 보기(A. ) 또는 정답(Answer:) 시작점을 찾아 그 윗부분(질문) 날려버리기
            # Ans:, Answer:, Correct Answer:, Explanation:, 또는 줄바꿈 후 A. 을 기점으로 자름
            ans_pattern = r'\n\s*(?:Correct\s+Answer\s*:|Answer\s*:|Ans\s*:|Explanation\s*:|A\.\s)'
            ans_match = re.search(ans_pattern, block, flags=re.IGNORECASE)
            
            if ans_match:
                # 정답 파트가 시작되는 인덱스부터 끝까지만 가져옴
                clean_answer = block[ans_match.start():].strip()
            else:
                # 만약 정답 마커가 아예 안 보이면 덩어리 통째로 보존
                clean_answer = block.strip()
                
            txt_answers_dict[q_num] = clean_answer

    print(f"📄 TXT 파일에서 총 {len(txt_answers_dict)}개의 쓰레기 데이터를 걸러내고 정답을 추출했습니다.")

    # 5. JSON 파일에 정확히 덮어쓰기
    success_count = 0
    for q in questions:
        q_id = q.get('id')
        
        if q_id in txt_answers_dict:
            q['original_answer'] = txt_answers_dict[q_id]
            success_count += 1
        else:
            q['original_answer'] = f"⚠️ 덤프 원본에서 {q_id}번 해설을 찾지 못했습니다."

    # 6. 저장
    with open(json_file, 'w', encoding='utf-8') as f:
        json.dump(questions, f, ensure_ascii=False, indent=2)

    print(f"✅ 맵핑 완료! 총 {success_count}개의 문제 해설이 완벽하게 쪼개져서 제자리를 찾았습니다.")

if __name__ == "__main__":
    id_mapper()