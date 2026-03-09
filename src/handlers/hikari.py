# 히카리글로벌: Remark 에 'TotalGuestName' 이 포함된 행 또는
# Remark 가 완전히 비어 있는 행을 재가공 대상으로 본다.
# 상세 Remark 입력 형식: 금액 OPEN / RO

REMARK_KEYWORDS = [
    "TotalGuestName",
]

# 히카리 전용: Remark 컬럼이 완전히 공란인 행도 매칭 대상으로 포함
MATCH_EMPTY_REMARK = True

REMARK_FORMAT = "{total} OPEN / RO"
