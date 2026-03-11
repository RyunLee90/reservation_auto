# 여기어때: Remark 에 '판매가' 가 포함된 행만 대상
# 상세 Remark 입력 형식: 금액 CL / RO

REMARK_KEYWORDS = [
    "판매가",
]

# 여기어때 전용:
# - Remark/행 전체에 CL 또는 COMP 가 이미 들어가 있으면 "처리 완료"로 보고 스킵
# - 둘 다 없으면 히카리 OPEN 개념처럼 "처리 대상"으로 본다.
SKIP_REMARK_KEYWORDS = ["CL", "COMP", "RO"]

REMARK_FORMAT = "{total} CL / RO"
