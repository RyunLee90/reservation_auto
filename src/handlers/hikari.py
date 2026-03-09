# 히카리글로벌:
# Remark 에 아래 SKIP 단어가 없으면 무조건 처리 대상으로 본다.
# (이미 작업된 행에는 OPEN / RO 가 들어가 있으므로 자동으로 걸러짐)
# 상세 Remark 입력 형식: 금액 OPEN / RO

# 키워드 매칭 / 공란 매칭은 사용하지 않음 → MATCH_ALL_REMAINING 으로 대체
REMARK_KEYWORDS = []
MATCH_EMPTY_REMARK = False

# SKIP: 이 단어 중 하나라도 Remark 에 있으면 절대 들어가지 않음
SKIP_REMARK_KEYWORDS = ["OPEN", "오픈", "open", "RO"]

# 히카리 전용: SKIP 에 걸리지 않은 행은 모두 처리 대상
MATCH_ALL_REMAINING = True

REMARK_FORMAT = "{total} OPEN / RO"
