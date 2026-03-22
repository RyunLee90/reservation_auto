"""
영문 성씨(단어 단위)만 한글로 치환. 번역기 결과 보정용.
"""
from __future__ import annotations

import re

# 제공된 매핑 (중복 키는 하나로 정리: Son·No·Goo 등)
KOREAN_LAST_NAMES: dict[str, str] = {
    "Kim": "김",
    "Lee": "이",
    "Yi": "이",
    "Rhee": "이",
    "Park": "박",
    "Bak": "박",
    "Choi": "최",
    "Choe": "최",
    "Jung": "정",
    "Jeong": "정",
    "Chung": "정",
    "Kang": "강",
    "Cho": "조",
    "Jo": "조",
    "Yoon": "윤",
    "Yun": "윤",
    "Jang": "장",
    "Chang": "장",
    "Shin": "신",
    "Sin": "신",
    "Han": "한",
    "Seo": "서",
    "Suh": "서",
    "Kwon": "권",
    "Gwon": "권",
    "Son": "손",
    "Ahn": "안",
    "An": "안",
    "Hwang": "황",
    "Song": "송",
    "Yoo": "유",
    "Yu": "유",
    "Hong": "홍",
    "Jeon": "전",
    "Jun": "전",
    "Chun": "전",
    "Ko": "고",
    "Koh": "고",
    "Moon": "문",
    "Mun": "문",
    "Yang": "양",
    "Bae": "배",
    "Paek": "백",
    "Baek": "백",
    "Heo": "허",
    "Hur": "허",
    "No": "노",
    "Roh": "노",
    "Noh": "노",
    "Nam": "남",
    "Sim": "심",
    "Shim": "심",
    "Ha": "하",
    "Kwak": "곽",
    "Sung": "성",
    "Seong": "성",
    "Cha": "차",
    "Joo": "주",
    "Ju": "주",
    "Woo": "우",
    "Wu": "우",
    "Koo": "구",
    "Ku": "구",
    "Na": "나",
    "Ra": "나",
    "Min": "민",
    "Im": "임",
    "Lim": "임",
    "Eum": "엄",
    "Um": "엄",
    "Chae": "채",
    "Won": "원",
    "Cheon": "천",
    "Bang": "방",
    "Gong": "공",
    "Kong": "공",
    "Hyun": "현",
    "Ham": "함",
    "Yeom": "염",
    "Byun": "변",
    "Byeon": "변",
    "Goo": "구",
    "Do": "도",
}

# 긴 철자를 먼저 매칭 (동일 접두 가능성 대비)
_SORTED_EN_KEYS = sorted(KOREAN_LAST_NAMES.keys(), key=len, reverse=True)
_LAST_NAME_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in _SORTED_EN_KEYS) + r")\b",
    re.IGNORECASE,
)


def contains_korean_surname_token(text: str) -> bool:
    """
    영문 문자열 안에 매핑된 한국 성씨 로마자가 '단어'로 등장하는지 여부.

    예: 'Bujin Kim' → True (Kim), 'Takako Mizuno' → False (Mizuno 미매핑)
    → 번역 여부 판별에 사용 (한국 성이 있을 때만 googletrans 호출).
    """
    if not text or not text.strip():
        return False
    return _LAST_NAME_PATTERN.search(text) is not None


def replace_korean_last_names_in_text(text: str) -> str:
    """
    영문 텍스트에서 단어 단위(\\b)로만 성씨를 한글로 치환하고 나머지는 유지.

    - Kim, KIM, kim → 김 (re.IGNORECASE)
    - 'Park'만 '박'으로, 'Parking' 등은 워드 바운더리로 치환하지 않음
    """
    if not text or not text.strip():
        return text

    def _repl(m: re.Match[str]) -> str:
        word = m.group(1)
        for en_key, ko in KOREAN_LAST_NAMES.items():
            if en_key.lower() == word.lower():
                return ko
        return m.group(0)

    return _LAST_NAME_PATTERN.sub(_repl, text)
