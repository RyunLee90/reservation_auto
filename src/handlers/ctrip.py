# 씨트립: 아고다와 동일한 구조
# Remark 셀이 공란인 행만 처리 대상, VCC/COMP/RO 있으면 스킵
 
REMARK_KEYWORDS = []
MATCH_EMPTY_REMARK = True
MATCH_ALL_REMAINING = False
 
SKIP_REMARK_KEYWORDS = ["VCC", "COMP", "RO"]
 
REMARK_FORMAT = "{total} VCC / RO"
 
# FIT Remark(또는 Inter Memo에서 복사한 문구)에 아래 표시명이 포함되면 Daily Rate 탭에서 행 추가 후 자동완성
# (표시명, 자동완성 입력 문자열)
# "Please charge" 뒤 텍스트에서 아래 키워드를 탐색해 Daily Rate 에 입력
DAILY_RATE_SERVICE_KEYWORDS = [
    ("Quiet room preferred", "qtrm"),
    ("Away from elevator", "fafe"),
    ("Near elevator", "nefe"),
    # Smoke-free treatment required → 무시
]
 
# Inter Memo: 실제 복사 원본은 textarea #IR01_0114_frmE_memo (MEMO_COMT).
INTER_MEMO_BEST_TEXT_STRATEGY = "last_row_in_table"
 
# MEMO_COMT 로드용 그리드 더블클릭 대상 행 — 0부터 센다.
INTER_MEMO_MEMO_LOAD_ROW_INDEX = 1
 
# Inter Memo 행이 이 수 이상일 때만 요청사항 있음으로 판단해 더블클릭.
INTER_MEMO_MIN_ROWS_TO_READ = 2
 