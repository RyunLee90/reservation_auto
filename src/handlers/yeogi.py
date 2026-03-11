# 여기어때: 스킵(CL/COMP/RO) 제외하면 전부 처리 대상 (히카리 OPEN 개념과 동일)
# 상세 Remark 입력 형식: 금액 CL / RO

REMARK_KEYWORDS = []
MATCH_EMPTY_REMARK = False
MATCH_ALL_REMAINING = True

# 행 전체에 아래 중 하나라도 있으면 스킵 (이미 처리된 행)
SKIP_REMARK_KEYWORDS = ["CL", "COMP", "RO"]

REMARK_FORMAT = "{total} CL / RO"
