# 아고다: 야놀자와 동일 — 행 전체에 CL/COMP/RO 가 있으면 스킵(이미 처리된 행)
# 차이점: Remark 셀이 공란인 행만 처리 대상 (MATCH_EMPTY_REMARK)

REMARK_KEYWORDS = []
MATCH_EMPTY_REMARK = True
MATCH_ALL_REMAINING = False

SKIP_REMARK_KEYWORDS = ["VCC", "EXP", "RO"]

REMARK_FORMAT = "{total} VCC / RO"

# FIT Remark(또는 Inter Memo에서 복사한 문구)에 아래 표시명이 포함되면 Daily Rate 탭에서 행 추가 후 자동완성
# (표시명, 자동완성 입력 문자열)
DAILY_RATE_SERVICE_KEYWORDS = [
    ("HighFloor", "high"),
    ("QuietRoom", "qtrm"),
    ("근처", "nefe"),
    ("떨어진", "fafe"),
    ("산방산", "mtv"),
]

# Inter Memo: 실제 복사 원본은 textarea #IR01_0114_frmE_memo (MEMO_COMT).
# textarea 가 비었을 때만 그리드 셀에서 끌어올 때 사용하는 폴백 전략.
# - "last_row_in_table" / "longest_cell_on_page" → _agoda_inter_memo_pick_best_cell_text
INTER_MEMO_BEST_TEXT_STRATEGY = "last_row_in_table"

# MEMO_COMT 로드용 그리드(#IR01_0114_gridSearch tbody tr) 더블클릭 대상 행 — 0부터 센다.
# 1 = 두 번째 행 (첫 행은 결제 요약 등, 두 번째 행에 HighFloor 등 실제 메모가 있는 경우)
INTER_MEMO_MEMO_LOAD_ROW_INDEX = 1

# Inter Memo 행이 이 수 이상일 때만 요청사항 있음으로 판단해 더블클릭.
# 요청사항 있음 = 4줄, 요청사항 없음 = 3줄 → 4 미만이면 그냥 닫고 나옴.
INTER_MEMO_MIN_ROWS_TO_READ = 4