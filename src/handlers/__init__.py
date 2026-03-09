# 계정별 핸들러: Remark 매칭 키워드 및 상세 처리 로직
# ACCOUNT_NAMES(.env) 와 동일한 이름으로 매핑

from . import hikari, yeogi, yanolja

# 계정 표시 이름 -> 핸들러 모듈
HANDLERS = {
    "히카리글로벌": hikari,
    "여기어때": yeogi,
    "야놀자": yanolja,
}


def get_handler(account_name: str):
    """계정 이름에 해당하는 핸들러 모듈 반환. 없으면 None."""
    return HANDLERS.get(account_name)
