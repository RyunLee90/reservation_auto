# 공통: Remark 매칭 시 사용하는 정규화 (공백/괄호/전각 제거 후 소문자)

def normalize_for_remark(txt: str) -> str:
    if not txt:
        return ""
    for full, half in [
        ("２", "2"), ("Ｂ", "b"), ("Ｃ", "c"),
        ("０", "0"), ("１", "1"), (" ", ""), ("　", ""),
    ]:
        txt = txt.replace(full, half)
    return (
        txt.lower()
        .replace(" ", "")
        .replace("　", "")
        .replace("[", "")
        .replace("]", "")
        .replace("(", "")
        .replace(")", "")
        .replace("/", "")
        .replace("-", "")
        .replace("_", "")
    )
