# 야놀자: Remark 매칭 키워드
# 이제는 '판매채널' 이 포함된 Remark 만 대상.

REMARK_KEYWORDS = [
    "판매채널",
]

# 야놀자 전용:
# - Remark/행 전체에 CL 또는 COMP 가 이미 들어가 있으면 "처리 완료"로 보고 스킵
# - 둘 다 없으면 히카리 OPEN 개념처럼 "처리 대상"으로 본다.
SKIP_REMARK_KEYWORDS = ["CL", "COMP"]

# 야놀자도 여기어때와 동일하게 CL / RO 사용
REMARK_FORMAT = "{total} CL / RO"
