import logging
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import InvalidSessionIdException, TimeoutException
from webdriver_manager.chrome import ChromeDriverManager

from handlers import agoda as agoda_handler
from handlers import get_handler
from handlers.base import normalize_for_remark
from korean_last_names import (
    contains_korean_surname_token,
    replace_korean_last_names_in_text,
)

BASE_DIR = Path(__file__).resolve().parents[1]

# ── 로그 파일 설정 ──
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
_log_filename = LOG_DIR / f"reservation_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.FileHandler(_log_filename, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
# 스크린샷 저장 폴더
SCREENSHOT_DIR = BASE_DIR / "screenshots"
SCREENSHOT_DIR.mkdir(exist_ok=True)

def _save_screenshot(driver: webdriver.Chrome, label: str):
    """스크린샷을 screenshots/ 폴더에 저장. label = 파일명 구분자."""
    try:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = SCREENSHOT_DIR / f"{ts}_{label}.png"
        driver.save_screenshot(str(path))
        print(f"스크린샷 저장: {path.name}")
    except Exception as e:
        print(f"경고: 스크린샷 저장 실패: {e}")

# 기존 print 를 logging.info 로 리디렉션
_orig_print = print
def print(*args, **kwargs):
    msg = " ".join(str(a) for a in args)
    logging.info(msg)

# 번역 후 영문 성씨 → 한글 보정(워드 단위) 적용 계정
_ACCOUNTS_LAST_NAME_PATCH = frozenset({"히카리글로벌", "아고다"})


def _load_env():
    """
    reservation_auto 전용 .env 를 먼저 읽고, 이어서 형제 프로젝트 .env 를 읽어
    PMS_* 등 누락된 값만 채운다. (reservation_auto/.env 가 없으면 pms 것만 읽음)
    """
    # 1) reservation_auto/.env (ACCOUNTS 등 이 프로젝트 전용)
    env_here = BASE_DIR / ".env"
    if env_here.exists():
        load_dotenv(env_here)
    # 2) pms_leadtime_analysis/.env (PMS_* 등, 이미 설정된 env 는 덮어쓰지 않음)
    env_pms = BASE_DIR.parent / "pms_leadtime_analysis" / ".env"
    if env_pms.exists():
        load_dotenv(env_pms)
    if not env_here.exists() and not env_pms.exists():
        load_dotenv()


_load_env()

PMS_COMPANY = os.getenv("PMS_COMPANY")
PMS_ID = os.getenv("PMS_ID")
PMS_PW = os.getenv("PMS_PW")
PMS_URL = "https://pms.sanhait.com/pms/index.do#nbb"

# 처리할 Account 목록. .env 에 ACCOUNTS=히카리글로벌,아고다,여기어때,야놀자 처럼 쉼표 구분으로 넣으면 됨.
# 없으면 기본값은 히카리글로벌만.
_accounts_raw = (os.getenv("ACCOUNTS") or "히카리글로벌").strip()
ACCOUNT_NAMES = [name.strip() for name in _accounts_raw.split(",") if name.strip()]
# 테스트 전용: .env 또는 실행 전에 AGODA_TEST_ONLY=1 이면 아고다만 처리
# Dry-run 모드: .env 에 DRY_RUN=1 이면 실제 Save 없이 로그만 출력
DRY_RUN = (os.getenv("DRY_RUN") or "").strip().lower() in ("1", "true", "yes", "y")
if DRY_RUN:
    print("알림: DRY_RUN=1 → 실제 저장 없이 시뮬레이션만 합니다.")

# FIT Reservation 상세 화면에서 단계마다 대기(초)
FIT_STEP_DELAY_SEC = 0.3


def _driver_alive(driver: webdriver.Chrome) -> bool:
    """브라우저를 사용자가 닫으면 세션이 끊어짐 → False."""
    try:
        driver.current_window_handle
        return True
    except Exception:
        return False


def _is_session_lost_error(exc: BaseException) -> bool:
    """브라우저 종료·크래시 등으로 세션이 끊긴 경우."""
    if isinstance(exc, InvalidSessionIdException):
        return True
    msg = str(exc).lower()
    return "invalid session id" in msg or "session deleted" in msg


def _sleep_interruptible(
    driver: webdriver.Chrome, total_seconds: float, chunk_sec: float = 5.0
) -> bool:
    """total_seconds 동안 sleep 하되 chunk 마다 세션 확인. 브라우저 종료 시 False."""
    elapsed = 0.0
    while elapsed < total_seconds:
        step = min(chunk_sec, total_seconds - elapsed)
        time.sleep(step)
        elapsed += step
        if not _driver_alive(driver):
            return False
    return True


def _build_driver() -> webdriver.Chrome:
    options = Options()
    options.add_argument("--start-maximized")
    if (os.getenv("HEADLESS") or "1") != "0":
        options.add_argument("--headless=new")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--disable-gpu")
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=options)


def _login(driver: webdriver.Chrome, wait: WebDriverWait):
    driver.get(PMS_URL)
    wait.until(EC.presence_of_element_located((By.ID, "company")))

    el_company = driver.find_element(By.ID, "company")
    el_company.clear()
    el_company.send_keys(PMS_COMPANY)

    el_user = driver.find_element(By.ID, "username")
    el_user.clear()
    el_user.send_keys(PMS_ID)

    el_pw = driver.find_element(By.ID, "userpw")
    el_pw.clear()
    el_pw.send_keys(PMS_PW)

    driver.find_element(By.ID, "btn_login").click()

    time.sleep(2)
    wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    print("로그인 완료")


SEARCH_QUERY = "reservation list"
_CERT_DONE = False


def _enter_iframe(driver: webdriver.Chrome):
    """첫 번째 iframe으로 진입."""
    driver.switch_to.default_content()
    time.sleep(0.5)
    iframes = driver.find_elements(By.TAG_NAME, "iframe")
    if iframes:
        driver.switch_to.frame(iframes[0])


def _clear_arrival_dates(driver: webdriver.Chrome, wait: WebDriverWait):
    """
    Reservation List 화면에서 Arrival Date (From/To) 입력칸 비우기.
    - id: frmS_arrDateF, frmS_arrDateT
    """
    for element_id in ("frmS_arrDateF", "frmS_arrDateT"):
        try:
            el = wait.until(EC.presence_of_element_located((By.ID, element_id)))
            driver.execute_script("arguments[0].value = '';", el)
            try:
                el.clear()
            except Exception:
                pass
        except Exception:
            print(f"경고: Arrival Date 필드 '{element_id}' 를 찾지 못해 스킵합니다.")


def _set_rsvn_dates_today(driver: webdriver.Chrome, wait: WebDriverWait):
    """
    Rsvn Date From = 어제, To = 오늘 으로 입력.
    - 연도는 PMS 디폴트를 사용하므로 MMdd(예: 0310)만 입력.
    - id: frmS_rsvnDateF (From=어제), frmS_rsvnDateT (To=오늘)
    """
    from datetime import timedelta
    today = datetime.now()
    yesterday = today - timedelta(days=2)
    date_from = yesterday.strftime("%m%d")  # 예: 0310
    date_to   = today.strftime("%m%d")      # 예: 0311

    for element_id, mmdd in (("frmS_rsvnDateF", date_from), ("frmS_rsvnDateT", date_to)):
        try:
            el = wait.until(EC.element_to_be_clickable((By.ID, element_id)))
            el.click()
            time.sleep(0.2)
            el.send_keys(mmdd)
            driver.execute_script(
                "arguments[0].dispatchEvent(new Event('change', {bubbles: true}));",
                el,
            )
            print(f"Rsvn Date '{element_id}' 에 {mmdd} 입력 완료")
        except Exception as e:
            print(f"경고: Rsvn Date 필드 '{element_id}' 설정 실패: {e}")


def _set_account_filter(driver: webdriver.Chrome, wait: WebDriverWait, name: str = "히카리글로벌"):
    """
    Account 검색어 입력.
    - id: frmS_CorpCustmNo_desc
    """
    try:
        el = wait.until(EC.element_to_be_clickable((By.ID, "frmS_CorpCustmNo_desc")))
        el.click()
        time.sleep(0.2)
        el.clear()
        el.send_keys(name)
        time.sleep(0.5)
        # 자동완성 목록에서 한 칸 내려가서 선택 적용
        el.send_keys(Keys.ARROW_DOWN)
        time.sleep(0.2)
        el.send_keys(Keys.ENTER)
        print(f"Account 필터에 '{name}' 선택 완료 (자동완성에서 1칸 내려 엔터)")
    except Exception as e:
        print(f"경고: Account 필터 설정 실패: {e}")


def _click_find(driver: webdriver.Chrome, wait: WebDriverWait):
    """Find 버튼 클릭 (매 실행마다). Close 직후 DOM 갱신 지연 시 재시도."""
    for attempt in range(2):
        try:
            btn = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.ID, "comm_btn_find")),
            )
            btn.click()
            print("Find 버튼 클릭 완료")
            return
        except Exception:
            if attempt == 0:
                time.sleep(1.5)
                _enter_iframe(driver)
            else:
                print("경고: Find 버튼을 찾지 못했습니다.")


def _handle_cert_popup(driver: webdriver.Chrome, wait: WebDriverWait):
    """
    Certification Confirm 팝업 처리.
    - 비밀번호 입력 (로그인에 사용한 PMS_PW 재사용 가정)
    - 1초 대기 후 Apply 버튼 클릭
    """
    if not PMS_PW:
        print("경고: PMS_PW가 비어 있어 Cert 팝업 자동처리를 건너뜁니다.")
        return
    try:
        pwd_input = wait.until(EC.element_to_be_clickable((By.ID, "cert_btn")))
        pwd_input.click()
        pwd_input.send_keys(PMS_PW)
        time.sleep(1)
        apply_btn = wait.until(EC.element_to_be_clickable((By.ID, "cert_button")))
        apply_btn.click()
        print("Cert 팝업 비밀번호 입력 및 Apply 클릭 완료")
    except Exception as e:
        print(f"경고: Cert 팝업 처리 중 오류: {e}")


def _click_cert(driver: webdriver.Chrome, wait: WebDriverWait):
    """Cert 버튼 클릭 후 Certification Confirm 팝업 자동 처리.

    - 프로그램 실행 동안 최초 1회만 수행하면 되므로,
      한 번 성공적으로 수행된 이후에는 다시 호출되더라도 바로 리턴한다.
    """
    global _CERT_DONE
    if _CERT_DONE:
        # 이미 Cert 처리가 끝난 상태이므로 재호출 시 아무 것도 하지 않는다.
        print("알림: Cert 처리는 이미 완료되어 건너뜁니다.")
        return

    try:
        btn = wait.until(EC.element_to_be_clickable((By.ID, "comm_btn_cert")))
        btn.click()
        print("Cert 버튼 클릭 완료")
        _handle_cert_popup(driver, wait)
        _CERT_DONE = True
        print("Cert 처리를 최초 1회 완료했습니다. 이후부터는 Find 만 수행합니다.")
    except Exception:
        print("경고: Cert 버튼을 찾지 못했습니다.")


def _scroll_grid_right(driver: webdriver.Chrome):
    """
    House Keeping 그리드의 가로 스크롤을 맨 오른쪽으로 이동.
    - Kendo Grid 기준: div.k-grid-content 를 우선 시도
    - 없으면 overflow-x 가 있는 div 를 fallback 으로 사용
    """
    try:
        containers = driver.find_elements(By.CSS_SELECTOR, "div.k-grid-content")
        if not containers:
            containers = driver.find_elements(By.CSS_SELECTOR, "div[style*='overflow-x']")
        for el in containers:
            driver.execute_script("arguments[0].scrollLeft = arguments[0].scrollWidth;", el)
        if containers:
            time.sleep(0.5)
            print("그리드 가로 스크롤을 오른쪽 끝으로 이동했습니다.")
    except Exception as e:
        print(f"경고: 그리드 가로 스크롤 이동 실패: {e}")


def _scroll_grid_to_bottom(driver: webdriver.Chrome):
    """
    그리드 세로 스크롤을 맨 아래로 내려서, 아래쪽 행까지 DOM에 로드되게 한다.
    (가상 스크롤/ lazy 로딩인 경우 화면에 안 보이던 행이 생길 수 있음)
    """
    try:
        containers = driver.find_elements(By.CSS_SELECTOR, "div.k-grid-content")
        if not containers:
            containers = driver.find_elements(By.CSS_SELECTOR, "div[style*='overflow-y'], div[style*='overflow:']")
        for el in containers:
            driver.execute_script(
                "arguments[0].scrollTop = arguments[0].scrollHeight;",
                el,
            )
        if containers:
            time.sleep(0.5)
            # 다시 맨 위로 올려서 순서대로 보이게 (선택 사항)
            for el in containers:
                driver.execute_script("arguments[0].scrollTop = 0;", el)
            time.sleep(0.3)
            print("그리드 세로 스크롤 반영 완료 (아래 행까지 로드).")
    except Exception as e:
        print(f"경고: 그리드 세로 스크롤 실패: {e}")


def _get_remark_col_index(driver: webdriver.Chrome) -> int | None:
    """
    헤더(th)에서 'Remark' 컬럼 인덱스를 동적으로 찾는다.
    찾지 못하면 None 반환.
    """
    try:
        headers = driver.find_elements(By.CSS_SELECTOR, "th")
        for idx, h in enumerate(headers):
            txt = (h.text or "").strip().lower().replace(" ", "")
            if "remark" in txt:
                return idx
    except Exception as e:
        print(f"경고: Remark 헤더 탐색 중 오류: {e}")
    print("알림: Remark 헤더를 찾지 못했습니다.")
    return None


def _open_first_reservation(
    driver: webdriver.Chrome,
    wait: WebDriverWait,
    account_name: str | None = None,
    skip_rsvn_no: str | None = None,
):
    """
    Reservation List 그리드에서
    계정별 핸들러(handlers)의 REMARK_KEYWORDS 에 맞는 행을 찾아 더블클릭.
    skip_rsvn_no 가 있으면 해당 Rsvn No 행은 건너뜀 (방금 처리한 예약 재진입 방지).
    반환: (열었으면 True, rsvn_no) / (안 열었으면 False, None)
    """
    # 계정별 키워드: 핸들러 있으면 해당 키워드, 없으면 기존처럼 B2B
    handler = get_handler(account_name) if account_name else None
    match_empty_remark = bool(getattr(handler, "MATCH_EMPTY_REMARK", False)) if handler else False
    match_all_remaining = bool(getattr(handler, "MATCH_ALL_REMAINING", False)) if handler else False
    remark_keywords = getattr(handler, "REMARK_KEYWORDS", None) if handler else None
    if match_all_remaining:
        # SKIP 조건 외에는 모두 처리 대상 (키워드 매칭 불필요)
        keywords_normalized = []
        no_match_msg = f"Account '{account_name}' 처리할 예약 행을 찾지 못했습니다."
    elif handler and remark_keywords:
        keywords_normalized = [normalize_for_remark(k) for k in remark_keywords]
        no_match_msg = f"'{remark_keywords}' 가 포함된 Remark 를 가진 예약 행을 찾지 못했습니다."
    elif handler and match_empty_remark and not match_all_remaining:
        # Remark 공란만 대상 (예: 아고다). 키워드 매칭 없음.
        keywords_normalized = []
        no_match_msg = (
            f"Account '{account_name}' 처리할 예약 행을 찾지 못했습니다 (Remark 공란만 대상)."
        )
    else:
        keywords_normalized = [normalize_for_remark("B2B")]
        no_match_msg = "'B2B' 가 포함된 Remark 를 가진 예약 행을 찾지 못했습니다."

    try:
        time.sleep(1)
        _scroll_grid_right(driver)
        _scroll_grid_to_bottom(driver)
        time.sleep(0.3)
        rows = driver.find_elements(By.CSS_SELECTOR, "tr[role='row']") or driver.find_elements(By.CSS_SELECTOR, "tr")
        print(f"디버그: 그리드에서 감지한 행 개수 = {len(rows)}")

        # Remark 컬럼 인덱스 동적 탐색 (없으면 마지막 컬럼으로 폴백)
        remark_col_idx = _get_remark_col_index(driver)

        for row_idx, row in enumerate(rows):
            cells = row.find_elements(By.CSS_SELECTOR, "td")
            if not cells:
                continue
            rsvn_no = (cells[2].text or "").strip() if len(cells) >= 3 else ""
            if skip_rsvn_no and rsvn_no == skip_rsvn_no:
                continue  # 방금 처리한 예약은 건너뜀

            # 행 전체 텍스트 (히카리: OPEN/오픈/RO 여부는 행 전체에서 검사)
            row_text = " | ".join(
                ((c.text or "").strip() or (c.get_attribute("innerText") or "").strip())
                for c in cells
            )

            # Remark 셀만 추출 (헤더 기반 인덱스, 없으면 마지막 셀)
            if remark_col_idx is not None and remark_col_idx < len(cells):
                remark_cell = cells[remark_col_idx]
            else:
                remark_cell = cells[-1]

            remark_txt = (remark_cell.text or "").strip()
            if not remark_txt:
                remark_txt = (remark_cell.get_attribute("innerText") or "").strip()

            # 히카리글로벌 전용: 이미 작업 완료 표시(OPEN/오픈/open/RO)가 있으면 스킵
            skip_keywords = getattr(handler, "SKIP_REMARK_KEYWORDS", []) if handler else []
            if skip_keywords and any(
                re.search(r'\b' + re.escape(sk.lower()) + r'\b', row_text.lower())
                for sk in skip_keywords
            ):
                print(
                    f"  스킵: 이미 처리된 행 (Rsvn No: {rsvn_no}, 행 일부: '{row_text[:60]}...')"
                )
                continue

            matched_text = ""
            if match_all_remaining:
                # SKIP 에만 걸러지고, Remark 내용(공란 포함)은 그대로 둔 채 대상 선정
                matched_text = remark_txt or "[no remark]"
            else:
                # 키워드 매칭: Remark 셀에서만 확인
                remark_normalized = normalize_for_remark(remark_txt)
                for kw_norm in keywords_normalized:
                    if kw_norm and kw_norm in remark_normalized:
                        matched_text = remark_txt
                        break
                # 공란 매칭 (MATCH_EMPTY_REMARK True 인 계정)
                if not matched_text and match_empty_remark and not remark_txt:
                    matched_text = "(빈 Remark)"

            if not matched_text:
                continue
            ActionChains(driver).double_click(row).perform()
            print(f"재가공 대상 예약 행 클릭 완료 (Rsvn No: {rsvn_no}, Remark: '{matched_text}')")
            return True, rsvn_no
        print(f"알림: {no_match_msg}")
        for row_idx, row in enumerate(rows):
            cells = row.find_elements(By.CSS_SELECTOR, "td")
            if not cells:
                continue
            best = ""
            for c in cells:
                t = (c.text or "").strip() or (c.get_attribute("innerText") or "").strip()
                if len(t) > len(best):
                    best = t
            if best:
                print(f"  디버그 행{row_idx + 1}: '{best[:80]}{'...' if len(best) > 80 else ''}' | normalized 일부: {normalize_for_remark(best)[:60]}")
        return False, None
    except Exception as e:
        print(f"경고: 예약 행 클릭 중 오류: {e}")
        return False, None


def _translate_name_to_korean(name_en: str) -> str:
    """
    영문 이름을 한글로 번역 (googletrans 사용).
    - venv 에 googletrans==4.0.0rc1 이 설치되어 있어야 함.
    - 실패 시에는 원래 영문 이름을 그대로 반환.
    """
    try:
        from googletrans import Translator  # type: ignore

        translator = Translator()
        result = translator.translate(name_en, src="en", dest="ko")
        translated = (getattr(result, "text", None) or "").strip()
        if not translated:
            print("알림: 번역 결과가 비어 있어 영문 이름을 그대로 사용합니다.")
            return name_en
        print(f"디버그: googletrans 번역 성공: '{name_en}' -> '{translated}'")
        return translated
    except Exception as e:
        print(f"경고: googletrans 번역 실패(영문 그대로 사용): {e!r}")
        return name_en


def _digits_only(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def _format_card_spaced_16(digits: str) -> str:
    """16자리 숫자 → '5557 9776 7671 5381'."""
    d = _digits_only(digits)
    if len(d) >= 16:
        d = d[:16]
        return " ".join(d[i : i + 4] for i in range(0, 16, 4))
    return (digits or "").strip()


def _yyyymm_to_yy_mm_slash(yyyymm: str) -> str:
    """YYYYMM(예: 202610) → 리마크용 '26/10'."""
    d = _digits_only(yyyymm)
    if len(d) == 6:
        return f"{d[2:4]}/{d[4:6]}"
    return (yyyymm or "").strip()


def _fit_tel_looks_like_kr_mobile(tel: str) -> bool:
    """
    FIT 예약자 Tel(RSVN_GEST_TEL_NO, frmE01_txt_tel) 값이 국내 휴대로 보이면 True.
    예: 010-..., 010..., 82 10 ..., +82 10..., 8210...
    """
    raw = (tel or "").strip()
    if not raw:
        return False
    if len(_digits_only(raw)) < 9:
        return False
    compact = re.sub(r"[\s\-]", "", raw)
    if "010" in raw or "010" in compact:
        return True
    if re.search(r"82\s*10", raw) or compact.startswith("+8210") or compact.startswith("8210"):
        return True
    return False


def _normalize_kr_mobile_from_fit_tel(raw: str) -> str:
    """
    Tel(RSVN_GEST_TEL_NO) → Mobile 붙여넣기용 숫자만 정리.
    - 820101234567 → '010'부터 끝까지 (0101234567)
    - 82101234567  → 82 제거 후 '10…'이면 앞에 0을 붙여 010… (0101234567)
    """
    if not (raw or "").strip():
        return ""
    compact = _digits_only(raw)
    if not compact:
        return raw.strip()
    idx = compact.find("010")
    if idx >= 0:
        return compact[idx:]
    if compact.startswith("82"):
        rest = compact[2:]
        if rest.startswith("010"):
            return rest
        if rest.startswith("10"):
            return "0" + rest
    if compact.startswith("010"):
        return compact
    if compact.startswith("10") and len(compact) >= 9:
        return "0" + compact
    return raw.strip()


def _read_vcc_for_fit(driver: webdriver.Chrome) -> tuple[str, str]:
    """
    C/Card No·유효기간 입력칸 또는 화면 텍스트에서 카드 16자리·YYYYMM 추출.
    반환: (card16, yyyymm6)
    """
    card16 = ""
    yyyymm = ""
    try:
        el = driver.find_element(By.ID, "IR01_0101_V50_frmE01_txt_ccardNo")
        card16 = _digits_only(el.get_attribute("value") or "")
    except Exception:
        pass
    try:
        el = driver.find_element(By.ID, "IR01_0101_V50_frmE01_txt_expire")
        yyyymm = _digits_only(el.get_attribute("value") or "")
    except Exception:
        pass
    if len(card16) < 16 or len(yyyymm) != 6:
        try:
            body = driver.find_element(By.TAG_NAME, "body").text
            if len(card16) < 16:
                m = re.search(
                    r"\b(\d{4})[\s\-]?(\d{4})[\s\-]?(\d{4})[\s\-]?(\d{4})\b", body
                )
                if m:
                    card16 = "".join(m.groups())
            if len(yyyymm) != 6:
                m2 = re.search(r"\b(20\d{4})\b", body)
                if m2:
                    yyyymm = m2.group(1)
        except Exception:
            pass
    return card16[:16], yyyymm[:6]


def _agoda_memo_keywords_only(raw: str) -> str:
    """
    Inter Memo 그리드에서 가져온 긴 텍스트에서 금액+VCC/RO+카드 덩어리만 제거하고
    HighFloor, QuietRoom, AdditionalNotes:… 등 요청·메모만 남긴다.
    """
    if not (raw or "").strip():
        return ""
    s = raw.strip()
    for _ in range(6):
        s2 = re.sub(
            r"[\d,]+(?:\.\d+)?\s*VCC\s*/\s*RO\s*"
            r"(?:\d{4}\s+){3}\d{4}\s*\d{2}/\d{2}\s*",
            "",
            s,
            count=1,
            flags=re.I,
        )
        if s2 == s:
            break
        s = s2
    s = re.sub(r"\s+", " ", s).strip(" ,\n\r\t")
    return s.strip()


def _agoda_inter_memo_pick_best_cell_text(driver: webdriver.Chrome) -> str:
    """
    Inter Memo 그리드에서 복사할 한 덩어리의 원문 문자열을 고른다.
    handlers.agoda.INTER_MEMO_BEST_TEXT_STRATEGY 로 동작 분기.
    """
    cell_sel = "td.table-cell-fix.w_grid_cell_align_left[role='gridcell']"
    strategy = getattr(
        agoda_handler, "INTER_MEMO_BEST_TEXT_STRATEGY", "last_row_in_table"
    )

    def _cell_text(c) -> str:
        return (c.text or "").strip() or (c.get_attribute("innerText") or "").strip()

    cells = driver.find_elements(By.CSS_SELECTOR, cell_sel)
    visible = [c for c in cells if c.is_displayed()]
    if not visible:
        return ""

    if strategy == "longest_cell_on_page":
        best = ""
        for c in visible:
            t = _cell_text(c)
            if len(t) > len(best):
                best = t
        return best

    # 기본: last_row_in_table — 첫 보이는 셀이 속한 tbody 의 마지막 데이터 행만 사용
    try:
        tbody = visible[0].find_element(By.XPATH, "./ancestor::tbody[1]")
        rows = tbody.find_elements(By.CSS_SELECTOR, "tr")
        last_best = ""
        for row in rows:
            if not row.is_displayed():
                continue
            tds = row.find_elements(By.CSS_SELECTOR, cell_sel)
            row_texts = [_cell_text(td) for td in tds if _cell_text(td)]
            if not row_texts:
                continue
            last_best = max(row_texts, key=len)
        if last_best:
            return last_best
    except Exception as e:
        print(f"디버그: Inter Memo last_row_in_table 실패, 전역 최장 셀로 폴백: {e}")

    best = ""
    for c in visible:
        t = _cell_text(c)
        if len(t) > len(best):
            best = t
    return best


def _agoda_inter_memo_copy_grid(driver: webdriver.Chrome, wait: WebDriverWait) -> str:
    """
    아고다/씨트립: Inter Memo 진입 → 그리드 지정 행(기본 2번째) 더블클릭으로 MEMO_COMT 로드 후
    textarea #IR01_0114_frmE_memo 값을 복사 → Memo 닫고 FIT 복귀.
    행 수가 INTER_MEMO_MIN_ROWS_TO_READ 미만이면 요청사항 없음으로 판단, 빈 문자열 반환.
    """
    copied = ""
    fit_handle = driver.current_window_handle
    handles_before = set(driver.window_handles)
    try:
        memo_btn = wait.until(
            EC.presence_of_element_located((By.ID, "IR01_0101_V50_btn_Memo")),
        )
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", memo_btn)
        time.sleep(0.15)
        driver.execute_script("arguments[0].click();", memo_btn)
        time.sleep(1.5)

        handles_after = set(driver.window_handles)
        new_handles = handles_after - handles_before
        if new_handles:
            driver.switch_to.window(new_handles.pop())
            print("Inter Memo 새 창으로 전환 완료 (아고다/씨트립).")
            time.sleep(0.5)

        wait.until(EC.presence_of_element_located((By.ID, "IR01_0114_frmE_memo")))
        time.sleep(0.35)

        # 그리드에서 지정 행 더블클릭 → MEMO_COMT textarea 에 본문 로드
        try:
            row_idx = int(
                getattr(agoda_handler, "INTER_MEMO_MEMO_LOAD_ROW_INDEX", 1)
            )
            rows = driver.find_elements(
                By.CSS_SELECTOR, "#IR01_0114_gridSearch tbody tr"
            )
            vis = [r for r in rows if r.is_displayed()]
            min_rows = int(getattr(agoda_handler, "INTER_MEMO_MIN_ROWS_TO_READ", 4))
            dbl = None
            if not vis:
                print("알림: Inter Memo 그리드에 보이는 행이 없습니다.")
            elif len(vis) < min_rows:
                print(
                    f"알림: Inter Memo 행 수({len(vis)}줄) < 기준({min_rows}줄) "
                    f"→ 요청사항 없음으로 판단, 그냥 닫고 나옵니다."
                )
            else:
                if 0 <= row_idx < len(vis):
                    dbl = vis[row_idx]
                    print(
                        f"디버그: Inter Memo {len(vis)}줄 확인 "
                        f"→ {row_idx + 1}번째 행 더블클릭 (MEMO_COMT 로드)."
                    )
                else:
                    dbl = vis[0]
                    print(
                        f"알림: Inter Memo 그리드 보이는 행 {len(vis)}개 — "
                        f"요청 인덱스 {row_idx} 대신 1번째 행 더블클릭."
                    )
            if dbl is not None:
                driver.execute_script(
                    "arguments[0].scrollIntoView({block:'center'});", dbl
                )
                time.sleep(0.2)
                ActionChains(driver).move_to_element(dbl).double_click().perform()
                time.sleep(0.65)
        except Exception as e:
            print(f"디버그: Inter Memo 그리드 더블클릭 생략/실패: {e}")

        memo_el = driver.find_element(By.ID, "IR01_0114_frmE_memo")
        if dbl is None:
            # 더블클릭 안 한 경우(요청사항 없음) → 빈 문자열로 확정, 폴백 없음
            raw = ""
            print("알림: Inter Memo 더블클릭 없음 → 내용 복사 건너뜁니다.")
        else:
            raw = (memo_el.get_attribute("value") or "").strip()
            if not raw:
                raw = (memo_el.text or "").strip()
            if not raw:
                raw = _agoda_inter_memo_pick_best_cell_text(driver)
                print("디버그: MEMO_COMT 가 비어 있어 그리드 셀 텍스트로 폴백.")
        copied = _agoda_memo_keywords_only(raw)
        preview = copied[:120] + "..." if len(copied) > 120 else copied
        print(f"디버그: 아고다/씨트립 Inter Memo (MEMO_COMT 기준): '{preview}'")

        if driver.current_window_handle != fit_handle:
            driver.close()
            driver.switch_to.window(fit_handle)
            print("Inter Memo 창 닫고 FIT Reservation 으로 복귀 (아고다/씨트립).")
        else:
            try:
                driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
            except Exception:
                pass
            time.sleep(0.5)
            still_open = bool(driver.find_elements(By.ID, "IR01_0114_frmE_memo"))
            if still_open:
                all_close = driver.find_elements(By.ID, "comm_btn_close")
                if len(all_close) >= 2:
                    driver.execute_script(
                        "arguments[0].scrollIntoView({block:'center'});", all_close[-1]
                    )
                    time.sleep(0.15)
                    driver.execute_script("arguments[0].click();", all_close[-1])
                    print("Inter Memo 오버레이 close 버튼(마지막) 클릭 완료 (아고다/씨트립).")
                else:
                    print(
                        "경고: comm_btn_close 1개뿐 - FIT Reservation 유지, Inter Memo 닫기 건너뜀 (아고다/씨트립)."
                    )
        time.sleep(0.7)
        driver.execute_script("window.scrollTo(0, 0);")
        time.sleep(0.3)
    except Exception as e:
        print(f"경고: 아고다/씨트립 Inter Memo 복사 중 오류(빈 문자열로 계속): {e}")
        try:
            if driver.current_window_handle != fit_handle:
                driver.close()
                driver.switch_to.window(fit_handle)
        except Exception:
            pass
    return copied


def _agoda_ordered_daily_rate_keywords(remark: str, handler=None) -> list[tuple[str, str]]:
    """Remark 내 등장 순서대로 Daily Rate에 넣을 (표시명, 자동완성 입력) 목록."""
    src = handler if handler is not None else agoda_handler
    pairs = getattr(src, "DAILY_RATE_SERVICE_KEYWORDS", [])
    if not remark or not pairs:
        return []
    lower = remark.lower()
    hits: list[tuple[int, str, str]] = []
    for label, keys in pairs:
        idx = lower.find(label.lower())
        if idx >= 0:
            hits.append((idx, label, keys))
    hits.sort(key=lambda x: x[0])
    return [(h[1], h[2]) for h in hits]


def _agoda_fill_svc_name_cell(driver: webdriver.Chrome, wait: WebDriverWait, keys: str) -> None:
    """
    Daily Rate / Special Service: Add 직후 **Service 입력칸(input)** 에 포커스만 맞춘 뒤
    리마크 매핑 키워드(high, qtrm 등)를 **직접 타이핑**한다. (더블클릭·Enter로 편집 진입 X)
    """
    if not _driver_alive(driver):
        raise InvalidSessionIdException(
            "브라우저 세션이 끊어져 Daily Rate 서비스 입력을 중단합니다."
        )

    d = FIT_STEP_DELAY_SEC
    time.sleep(1.2)
    wait.until(EC.presence_of_element_located((By.ID, "IR01_0101_V50_grid_Service")))

    def _edit_row_last(drv):
        rows = drv.find_elements(
            By.CSS_SELECTOR, "#IR01_0101_V50_grid_Service tr.k-grid-edit-row"
        )
        if rows:
            return rows[-1]
        rows = drv.find_elements(
            By.CSS_SELECTOR,
            "#IR01_0101_V50_grid_Service tbody tr[data-uid], "
            "#IR01_0101_V50_grid_Service tbody tr.k-master-row",
        )
        return rows[-1] if rows else None

    tr = WebDriverWait(driver, 18).until(_edit_row_last)

    svc = None
    try:
        svc_td = tr.find_element(By.CSS_SELECTOR, "td[data-field='SVC_NAME']")
    except Exception:
        svc_td = None
    if svc_td is None:
        try:
            headers = driver.find_elements(
                By.CSS_SELECTOR, "#IR01_0101_V50_grid_Service .k-grid-header th"
            )
            idx = 3
            for i, h in enumerate(headers):
                if "service" in (h.text or "").lower():
                    idx = i
                    break
            tds = tr.find_elements(By.CSS_SELECTOR, "td[role='gridcell']")
            if idx < len(tds):
                svc_td = tds[idx]
        except Exception:
            svc_td = None

    if svc_td is not None:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", svc_td)
        time.sleep(d)
        found = svc_td.find_elements(By.CSS_SELECTOR, "input#IR01_0101_V50_SVC_NAME")
        if not found:
            driver.execute_script("arguments[0].click();", svc_td)
            time.sleep(0.45)
            found = svc_td.find_elements(By.CSS_SELECTOR, "input#IR01_0101_V50_SVC_NAME")
        if found:
            svc = found[-1]

    if svc is None:
        try:
            WebDriverWait(driver, 22).until(
                EC.presence_of_element_located((By.ID, "IR01_0101_V50_SVC_NAME")),
            )
        except Exception as e:
            if _is_session_lost_error(e):
                raise
            raise RuntimeError(f"Daily Rate SVC_NAME 입력칸을 찾지 못했습니다: {e}") from e
        svc_inputs = driver.find_elements(By.ID, "IR01_0101_V50_SVC_NAME")
        if not svc_inputs:
            raise RuntimeError("Daily Rate SVC_NAME 요소가 DOM에 없습니다.")
        svc = svc_inputs[-1]

    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", svc)
    time.sleep(d)
    try:
        svc.click()
    except Exception:
        driver.execute_script("arguments[0].focus(); arguments[0].click();", svc)
    time.sleep(0.2)

    try:
        svc.clear()
    except Exception:
        svc.send_keys(Keys.CONTROL + "a")
        svc.send_keys(Keys.DELETE)
    time.sleep(0.15)

    svc.send_keys(keys)
    time.sleep(0.6)
    driver.execute_script(
        "arguments[0].dispatchEvent(new Event('input', {bubbles: true}));"
        "arguments[0].dispatchEvent(new Event('change', {bubbles: true}));",
        svc,
    )
    # 자동완성 목록이 뜰 때까지 (Find 버튼은 팝업/포커스 이슈로 사용하지 않음)
    time.sleep(0.75)

    svc_inputs = driver.find_elements(By.ID, "IR01_0101_V50_SVC_NAME")
    svc = svc_inputs[-1] if svc_inputs else svc
    try:
        svc.click()
    except Exception:
        driver.execute_script("arguments[0].focus();", svc)
    time.sleep(0.15)
    try:
        svc.send_keys(Keys.ARROW_DOWN)
    except Exception:
        pass
    time.sleep(0.35)
    svc.send_keys(Keys.ENTER)
    time.sleep(d)


def _agoda_apply_daily_rate_services(
    driver: webdriver.Chrome, wait: WebDriverWait, remark: str, handler=None
) -> None:
    """
    Remark에 HighFloor / QuietRoom 등이 있으면 Daily Rate 탭 → Add 반복 →
    Service input 에 high / qtrm 등 직접 입력 후 자동완성 확정.
    handler 를 넘기면 해당 핸들러의 DAILY_RATE_SERVICE_KEYWORDS 사용 (씨트립 등).
    """
    ordered = _agoda_ordered_daily_rate_keywords(remark, handler=handler)
    if not ordered:
        print(
            "알림: Daily Rate 대상 키워드가 Remark에 없어 건너뜁니다."
        )
        return
    print(f"Daily Rate 자동 입력 대상: {[p[0] for p in ordered]}")
    d = FIT_STEP_DELAY_SEC
    try:
        tab = WebDriverWait(driver, 12).until(
            EC.element_to_be_clickable(
                (
                    By.XPATH,
                    "//span[contains(@class,'tab_name') and contains(normalize-space(.), 'Daily Rate')]",
                )
            )
        )
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", tab)
        time.sleep(d)
        driver.execute_script("arguments[0].click();", tab)
        print("Daily Rate 탭 클릭 완료.")
        time.sleep(0.8)
    except Exception as e:
        print(f"경고: Daily Rate 탭 클릭 실패: {e}")
        return

    for label, keys in ordered:
        try:
            add_links = driver.find_elements(
                By.CSS_SELECTOR, "a.k-button.k-grid-add[href='#']"
            )
            if not add_links:
                add_links = driver.find_elements(By.CSS_SELECTOR, "a.k-grid-add")
            if not add_links:
                print("경고: Daily Rate Add 버튼을 찾지 못했습니다.")
                return
            btn = add_links[-1]
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
            time.sleep(d)
            driver.execute_script("arguments[0].click();", btn)
            print("Daily Rate Add 클릭 완료.")
            time.sleep(1.5)

            _agoda_fill_svc_name_cell(driver, wait, keys)
            print(f"Daily Rate 서비스 입력 완료: {label} → '{keys}'")
        except InvalidSessionIdException:
            print(
                "치명적: 브라우저/세션이 끊어져 Daily Rate 입력을 중단합니다. "
                "(창을 닫지 말고 끝까지 두세요.)"
            )
            raise
        except Exception as e:
            if _is_session_lost_error(e):
                print(
                    "치명적: 브라우저/세션이 끊어져 Daily Rate 입력을 중단합니다. "
                    "(창을 닫지 말고 끝까지 두세요.)"
                )
                raise InvalidSessionIdException(str(e)) from e
            print(f"경고: Daily Rate 서비스 '{label}' 입력 중 오류: {e}")
            return


def _process_reservation_detail(
    driver: webdriver.Chrome,
    wait: WebDriverWait,
    account_name: str | None = None,
):
    """
    예약 상세 화면에서 다음 순서로 자동 처리.
    모든 필드 조작은 JS 로 수행 (그리드 오버레이로 인한 ElementClickIntercepted 방지).
    FIT 내부 순서: 이름 → (한국 성 번역 시만) Nationality → Mobile/Email 삭제
    → (아고다/씨트립/여기어때) Tel(RSVN_GEST_TEL_NO)가 010·82 10 패턴이면 Mobile 로 복사
    → Remark 비움 → Total·계정별 Remark 형식·카드 리마크·Pay 카드/만료 입력
    → Inter Memo(해당 계정) → 리마크에 메모 반영 후 Daily Rate / Special Service
    """

    fd = FIT_STEP_DELAY_SEC

    # JS 헬퍼: 스크롤 → 값 비우기/채우기/클릭 (단계 간 fd 초 대기)
    def _js_clear(el):
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
        time.sleep(fd)
        driver.execute_script("arguments[0].value = '';", el)
        driver.execute_script(
            "arguments[0].dispatchEvent(new Event('input',{bubbles:true}));", el
        )

    def _js_set(el, val):
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
        time.sleep(fd)
        driver.execute_script("arguments[0].value = arguments[1];", el, val)
        driver.execute_script(
            "arguments[0].dispatchEvent(new Event('input',{bubbles:true}));", el
        )

    def _js_click(el):
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
        time.sleep(fd)
        driver.execute_script("arguments[0].click();", el)

    try:
        # ── 0) 그리드 오버레이 제거: 맨 위로 스크롤 ──
        driver.execute_script("window.scrollTo(0, 0);")
        time.sleep(fd)

        new_remark = ""

        # ── 1) 이름 번역 (먼저) — 히카리/야놀자 등과 동일 개념
        korean_name_done = False
        try:
            name_input = wait.until(
                EC.presence_of_element_located(
                    (By.ID, "IR01_0101_V50_frmE01_txt_lastName"),
                )
            )
            name_en = (name_input.get_attribute("value") or name_input.text or "").strip()
            if name_en:
                if not contains_korean_surname_token(name_en):
                    print(
                        f"알림: 한국 성씨(로마자)가 없어 이름 번역을 건너뜁니다 (영문 유지): '{name_en}'"
                    )
                else:
                    name_ko = _translate_name_to_korean(name_en)
                    if account_name in _ACCOUNTS_LAST_NAME_PATCH:
                        name_ko_patched = replace_korean_last_names_in_text(name_ko)
                        if name_ko_patched != name_ko:
                            print(
                                f"디버그: 성씨 매핑 보정: '{name_ko}' -> '{name_ko_patched}'"
                            )
                        name_ko = name_ko_patched
                    _js_set(name_input, name_ko)
                    korean_name_done = True
                    print(f"이름 번역 및 입력 완료: '{name_en}' -> '{name_ko}'")
            else:
                print("알림: 이름 입력값이 비어 있어 번역을 건너뜁니다.")
        except Exception as e:
            print(f"경고: 이름 번역 실패(계속 진행): {e}")
        time.sleep(fd)

        # ── 2) Nationality: 한국 성으로 번역해 입력한 경우만 (kor → 아래로 한 칸 → Enter)
        if korean_name_done:
            try:
                nat_input = wait.until(
                    EC.presence_of_element_located(
                        (By.ID, "IR01_0101_V50_frmE02_cmp_nationality_desc"),
                    )
                )
                _js_clear(nat_input)
                time.sleep(fd)
                try:
                    nat_input.click()
                except Exception:
                    driver.execute_script("arguments[0].focus();", nat_input)
                time.sleep(fd)
                nat_input.send_keys("kor")
                time.sleep(1.0)
                try:
                    dropdown_item = WebDriverWait(driver, 5).until(
                        EC.element_to_be_clickable(
                            (By.XPATH, "//li[contains(., 'South Korea')]"),
                        )
                    )
                    dropdown_item.click()
                    print("Nationality 드롭다운에서 'South Korea' 직접 클릭 완료.")
                except Exception:
                    nat_input.send_keys(Keys.ARROW_DOWN)
                    time.sleep(fd)
                    nat_input.send_keys(Keys.ENTER)
                    print("Nationality 키보드로 'South Korea' 선택 완료.")
            except Exception as e:
                print(f"경고: Nationality 자동 설정 건너뜁니다: {e}")
        time.sleep(fd)

        # ── 3) Mobile 삭제 ──
        try:
            mobile_input = wait.until(
                EC.presence_of_element_located(
                    (By.ID, "IR01_0101_V50_frmE02_txt_mobile"),
                )
            )
            _js_clear(mobile_input)
            print("Mobile 번호 삭제 완료.")
        except Exception as e:
            print(f"경고: Mobile 삭제 건너뜁니다: {e}")
        time.sleep(fd)

        # ── 4) E-Mail 삭제 ──
        try:
            email_input = wait.until(
                EC.presence_of_element_located(
                    (By.ID, "IR01_0101_V50_frmE02_txt_email"),
                )
            )
            _js_clear(email_input)
            print("E-Mail 삭제 완료.")
        except Exception as e:
            print(f"경고: E-Mail 삭제 건너뜁니다: {e}")
        time.sleep(fd)

        # ── 4b) 아고다/씨트립/여기어때: Tel → Mobile 복사 후 CAR_NO 팝업 처리 (아고다만 활성)
        if account_name in ("아고다", "씨트립", "여기어때"):
            try:
                tel_el = driver.find_element(By.ID, "IR01_0101_V50_frmE01_txt_tel")
                tel_val = (tel_el.get_attribute("value") or tel_el.text or "").strip()
                if tel_val and _fit_tel_looks_like_kr_mobile(tel_val):
                    mobile_input = wait.until(
                        EC.presence_of_element_located(
                            (By.ID, "IR01_0101_V50_frmE02_txt_mobile"),
                        )
                    )
                    mobile_norm = _normalize_kr_mobile_from_fit_tel(tel_val)
                    _js_set(mobile_input, mobile_norm)
                    print(
                        f"{account_name}: Tel → Mobile (정규화): '{tel_val}' → '{mobile_norm}'"
                    )
                    time.sleep(fd)

                    # ── 4c) CAR_NO 클릭 → 팝업 뜨면 기존고객 → 첫 번째 줄 더블클릭
                    #        팝업 안 뜨면 신규고객 → 그냥 패스 (아고다만 활성)
                    if account_name == "아고다":
                        try:
                            car_el = wait.until(
                                EC.element_to_be_clickable(
                                    (By.ID, "IR01_0101_V50_frmE02_txt_carNo"),
                                )
                            )
                            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", car_el)
                            time.sleep(0.5)
                            mobile_input.send_keys(Keys.TAB)
                            time.sleep(0.8)
                            ActionChains(driver).move_to_element(car_el).click().perform()
                            time.sleep(1.5)

                            # 새 창 대신 팝업 오버레이 감지
                            popup_visible = False
                            try:
                                WebDriverWait(driver, 3).until(
                                    EC.presence_of_element_located(
                                        (By.ID, "COMN02_0100I_gridSearch")
                                    )
                                )
                                popup_visible = True
                            except Exception:
                                popup_visible = False

                            if popup_visible:
                                print("CAR_NO 팝업 감지 → 기존 고객, 첫 번째 줄 더블클릭.")
                                popup_rows = driver.find_elements(
                                    By.CSS_SELECTOR, "#COMN02_0100I_gridSearch tbody tr"
                                )
                                vis_rows = [r for r in popup_rows if r.is_displayed()]
                                if vis_rows:
                                    driver.execute_script(
                                        "arguments[0].scrollIntoView({block:'center'});",
                                        vis_rows[0],
                                    )
                                    time.sleep(0.2)
                                    ActionChains(driver).move_to_element(
                                        vis_rows[0]
                                    ).click().perform()
                                    time.sleep(0.5)
                                    apply_btn = driver.find_element(By.ID, "comm_btn_apply")
                                    driver.execute_script("arguments[0].click();", apply_btn)
                                    print("CAR_NO 팝업 Apply 클릭 완료.")
                                    time.sleep(2.0)
                                    try:
                                        driver.switch_to.default_content()
                                        ok_btn = WebDriverWait(driver, 5).until(
                                            EC.presence_of_element_located((By.NAME, "btn_msgBox_ok"))
                                        )
                                        driver.execute_script("arguments[0].click();", ok_btn)
                                        print("CAR_NO OK 팝업 닫기 완료.")
                                    except Exception:
                                        pass
                                    time.sleep(2.0)
                                    _enter_iframe(driver)
                                    time.sleep(1.0)

                                    # CAR_NO 비우기
                                    try:
                                        car_input = driver.find_element(
                                            By.ID, "IR01_0101_V50_frmE02_txt_carNo"
                                        )
                                        _js_clear(car_input)
                                        print("CAR_NO 비우기 완료.")
                                    except Exception as e:
                                        print(f"경고: CAR_NO 비우기 실패: {e}")

                                    # Daily Rate → Add → rpg
                                    for _retry in range(3):
                                        try:
                                            time.sleep(1.5)
                                            _enter_iframe(driver)
                                            time.sleep(0.5)
                                            driver.execute_script("window.scrollTo(0, 0);")
                                            time.sleep(0.5)
                                            _agoda_apply_daily_rate_services(
                                                driver, wait, "rpg_trigger",
                                                handler=type(
                                                    "H", (),
                                                    {"DAILY_RATE_SERVICE_KEYWORDS": [("rpg_trigger", "rpg")]}
                                                )()
                                            )
                                            print("CAR_NO Daily Rate rpg 입력 완료.")
                                            break
                                        except Exception as e:
                                            print(f"경고: CAR_NO Daily Rate rpg 재시도 {_retry+1}/3: {e}")
                                            if _retry == 2:
                                                print("경고: CAR_NO Daily Rate rpg 최종 실패, 계속 진행.")
                                else:
                                    print("경고: CAR_NO 팝업에 보이는 행이 없습니다.")
                            else:
                                print("CAR_NO 팝업 없음 → 신규 고객, 기존 플로우 계속.")
                        except Exception as e:
                            print(f"경고: CAR_NO 팝업 처리 중 오류(계속 진행): {e}")
            except Exception as e:
                print(f"경고: {account_name} Tel→Mobile 복사 건너뜀: {e}")
            time.sleep(fd)

        # ── 5) Remark 비우기 ──
        try:
            remark_input = wait.until(
                EC.presence_of_element_located(
                    (By.ID, "IR01_0101_V50_frmE01_txt_remark"),
                )
            )
            _js_clear(remark_input)
            print("Remark 내용 삭제 완료.")
        except Exception as e:
            print(f"경고: Remark 초기화 실패(계속 진행): {e}")
        time.sleep(fd)

        # ── 6) Total → 계정별 Remark 형식 → Pay 카드·만료 입력 →
        #    리마크: 첫 줄 아래 빈 줄 두 줄 뒤에 "1234 5678 ...   yy/mm"
        try:
            total_input = wait.until(
                EC.presence_of_element_located(
                    (By.ID, "IR01_0101_V50_frmE01_cur_total"),
                )
            )
            total_val = (total_input.get_attribute("value") or total_input.text or "").strip()
            card16, yyyymm = _read_vcc_for_fit(driver)
            if not total_val:
                print("알림: Total Amount 값이 비어 있어 Remark / VCC 처리를 건너뜁니다.")
            else:
                if len(card16) == 16:
                    try:
                        ccard_el = wait.until(
                            EC.presence_of_element_located(
                                (By.ID, "IR01_0101_V50_frmE01_txt_ccardNo"),
                            )
                        )
                        _js_set(ccard_el, card16)
                        print("C/Card No 입력 완료 (16자리).")
                    except Exception as e:
                        print(f"경고: C/Card No 입력 실패: {e}")
                else:
                    print(
                        f"알림: 카드 16자리를 찾지 못했습니다 (읽은 값: '{card16[:20]}...')."
                    )
                if len(yyyymm) == 6:
                    try:
                        exp_el = wait.until(
                            EC.presence_of_element_located(
                                (By.ID, "IR01_0101_V50_frmE01_txt_expire"),
                            )
                        )
                        _js_set(exp_el, yyyymm)
                        print("유효기간(YYYYMM) 입력 완료.")
                    except Exception as e:
                        print(f"경고: 유효기간 입력 실패: {e}")
                else:
                    print(f"알림: 유효기간 6자리(YYYYMM)를 찾지 못했습니다: '{yyyymm}'")

                # 계정별 Remark 형식 적용
                handler = get_handler(account_name)
                remark_fmt = getattr(handler, "REMARK_FORMAT", "{total} VCC / RO") if handler else "{total} VCC / RO"
                base_remark = remark_fmt.format(total=total_val)
                new_remark = base_remark
                if len(card16) == 16 and len(yyyymm) == 6:
                    card_line = (
                        f"{_format_card_spaced_16(card16)}     "
                        f"{_yyyymm_to_yy_mm_slash(yyyymm)}"
                    )
                    new_remark = base_remark + "\n\n\n" + card_line
                elif len(card16) == 16:
                    new_remark = base_remark + "\n\n\n" + _format_card_spaced_16(card16)

                remark_input = wait.until(
                    EC.presence_of_element_located(
                        (By.ID, "IR01_0101_V50_frmE01_txt_remark"),
                    )
                )
                _js_set(remark_input, new_remark)
                print(f"Remark 입력 완료: '{new_remark}'")
        except InvalidSessionIdException:
            raise
        except Exception as e:
            print(f"경고: Remark / VCC 처리 실패(계속 진행): {e}")
        time.sleep(fd)

        # ── 7) Inter Memo (아고다 / 씨트립 / 여기어때 / 야놀자)
        agoda_memo_addon = ""
        if account_name in ("아고다", "씨트립"):
            agoda_memo_addon = _agoda_inter_memo_copy_grid(driver, wait)
        elif account_name in ("여기어때", "야놀자"):
            memo_keywords = (
                ["룸온리"] if account_name == "여기어때"
                else ["룸UP", "선착순특가", "Room Only"]
            )
            try:
                fit_handle = driver.current_window_handle
                handles_before = set(driver.window_handles)

                memo_btn = wait.until(
                    EC.presence_of_element_located(
                        (By.ID, "IR01_0101_V50_btn_Memo"),
                    )
                )
                _js_click(memo_btn)
                time.sleep(1.5)

                handles_after = set(driver.window_handles)
                new_handles = handles_after - handles_before

                if new_handles:
                    memo_handle = new_handles.pop()
                    driver.switch_to.window(memo_handle)
                    print("Inter Memo 새 창으로 전환 완료.")
                    time.sleep(0.5)

                memo_area = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.ID, "IR01_0114_frmE_memo")),
                )
                memo_text = (
                    memo_area.get_attribute("value") or memo_area.text or ""
                ).strip()
                print(f"디버그: Inter Memo 내용(account={account_name}): '{memo_text[:80]}'")
                has_required = any(kw in memo_text for kw in memo_keywords)

                if driver.current_window_handle != fit_handle:
                    driver.close()
                    driver.switch_to.window(fit_handle)
                    print("Inter Memo 창 닫고 FIT Reservation 으로 복귀.")
                else:
                    try:
                        driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
                    except Exception:
                        pass
                    time.sleep(fd)

                    still_open = bool(driver.find_elements(By.ID, "IR01_0114_frmE_memo"))
                    if still_open:
                        all_close = driver.find_elements(By.ID, "comm_btn_close")
                        if len(all_close) >= 2:
                            _js_click(all_close[-1])
                            print("Inter Memo 오버레이 close 버튼(마지막) 클릭 완료.")
                        else:
                            print(
                                "경고: comm_btn_close 1개뿐 - FIT Reservation 유지, Inter Memo 닫기 건너뜀."
                            )
                time.sleep(fd)

                driver.execute_script("window.scrollTo(0, 0);")
                time.sleep(fd)

                if not has_required:
                    print(
                        f"알림: Inter Memo 에 필수 워딩 {memo_keywords} 중 어느 것도 없음. 상관없이 나머지 자동 처리 계속 진행합니다."
                    )
                else:
                    print(
                        f"Inter Memo 에 필수 워딩 {memo_keywords} 중 하나 이상 확인됨. 나머지 자동 처리 계속 진행합니다."
                    )
                time.sleep(fd)
            except Exception as e:
                print(f"경고: Inter Memo 확인 중 오류(예약 건너뜁니다): {e}")
                try:
                    if driver.current_window_handle != fit_handle:
                        driver.switch_to.window(fit_handle)
                except Exception:
                    pass
                return

        # ── 8) 아고다/씨트립: Inter Memo 문구를 리마크에 이어 붙인 뒤 Daily Rate
        if account_name == "아고다":
            try:
                if agoda_memo_addon.strip():
                    new_remark = (new_remark or "").rstrip() + "\n\n" + agoda_memo_addon.strip()
                    remark_input = wait.until(
                        EC.presence_of_element_located(
                            (By.ID, "IR01_0101_V50_frmE01_txt_remark"),
                        )
                    )
                    _js_set(remark_input, new_remark)
                    print(f"Remark 입력 (Inter Memo 반영): '{new_remark}'")
                if new_remark.strip():
                    _agoda_apply_daily_rate_services(driver, wait, new_remark)
            except Exception as e:
                print(f"경고: 아고다 Inter Memo 병합 또는 Daily Rate 실패: {e}")
        elif account_name == "씨트립":
            try:
                ctrip_handler = get_handler("씨트립")
                raw_memo = agoda_memo_addon.strip()
                # "Please charge" 기준으로 앞/뒤 분리
                charge_idx = raw_memo.find("Please charge")
                if charge_idx > 0:
                    # 앞에 텍스트 있으면 Remark에 추가
                    before_text = raw_memo[:charge_idx].strip().rstrip(";").strip()
                    service_text = raw_memo[charge_idx:]
                    if before_text:
                        new_remark = (new_remark or "").rstrip() + "\n\n" + before_text
                        remark_input = wait.until(
                            EC.presence_of_element_located(
                                (By.ID, "IR01_0101_V50_frmE01_txt_remark"),
                            )
                        )
                        _js_set(remark_input, new_remark)
                        print(f"Remark 입력 (씨트립 Inter Memo 반영): '{new_remark}'")
                    else:
                        service_text = raw_memo
                        print("알림: 씨트립 Inter Memo 'Please charge' 앞 텍스트 없음 → Remark 추가 생략.")
                else:
                    service_text = raw_memo
                    print("알림: 씨트립 Inter Memo 'Please charge' 없음 → 전체를 서비스 탐색 대상으로.")
                # "Please charge" 뒤 텍스트에서 서비스 키워드 탐색 → Daily Rate
                if service_text.strip():
                    _agoda_apply_daily_rate_services(driver, wait, service_text, handler=ctrip_handler)
            except Exception as e:
                print(f"경고: 씨트립 Inter Memo 병합 또는 Daily Rate 실패: {e}")
        time.sleep(fd)

        print("예약 상세 화면 자동 처리 완료.")
    except Exception as e:
        print(f"경고: 예약 상세 화면 자동 처리 중 오류: {e}")
        _save_screenshot(driver, "error")
        # 브라우저 세션이 끊어진 경우에는 더 이상 진행해도 의미가 없으므로 그대로 예외를 올려서 run() 전체를 종료한다.
        if _is_session_lost_error(e):
            print("치명적: 브라우저 세션이 끊어져 자동화를 중단합니다.")
            raise


def _save_and_close(driver: webdriver.Chrome, wait: WebDriverWait):
    """
    예약 상세 화면 저장 후 FIT 상세만 닫기.
    Save → OK 팝업 → (iframe 복귀 후) 상세창 Close 클릭 → Reservation List 로 복귀.
    Close 를 눌러야 Find 버튼이 다시 보이므로 반드시 수행.
    """
    try:
        if not _driver_alive(driver):
            print("알림: 브라우저가 이미 종료되어 Save/Close 를 건너뜁니다.")
            return
        if DRY_RUN:
            print("DRY_RUN: Save 건너뜁니다 (실제 저장 안 함). Close만 수행.")
            _enter_iframe(driver)
            all_close = driver.find_elements(By.ID, "comm_btn_close")
            if all_close:
                try:
                    all_close[-1].click()
                except Exception:
                    driver.execute_script("arguments[0].click();", all_close[-1])
            return
        # 1) Save 직전 스크린샷
        _save_screenshot(driver, "before_save")
        # 1) Save (현재 iframe 컨텍스트 안에서)
        save_btn = wait.until(
            EC.element_to_be_clickable((By.ID, "comm_btn_save")),
        )
        save_btn.click()
        print("Save 버튼 클릭 완료.")
        time.sleep(0.7)

        # 2) OK 팝업 (메인/iframe 어디든 있을 수 있음)
        ok_btn = None
        try:
            ok_btn = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.NAME, "btn_msgBox_ok")),
            )
        except Exception:
            pass
        if ok_btn is None:
            try:
                driver.switch_to.default_content()
            except Exception:
                pass
            ok_btn = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.NAME, "btn_msgBox_ok")),
            )
        try:
            ok_btn.click()
        except Exception:
            driver.execute_script("arguments[0].click();", ok_btn)
        print("메시지 박스 OK 버튼 클릭 완료.")
        time.sleep(1.0)

        # 3) iframe 복귀 후 상세창 Close 클릭 (FIT 만 닫고 List 는 유지)
        try:
            _enter_iframe(driver)
            time.sleep(0.8)
            all_close = driver.find_elements(By.ID, "comm_btn_close")
            if all_close:
                # 상세창 Close 는 보통 나중에 그려진(마지막) 버튼
                close_btn = all_close[-1]
                try:
                    close_btn.click()
                except Exception:
                    driver.execute_script("arguments[0].click();", close_btn)
                print("FIT 상세 Close 버튼 클릭 완료.")
            else:
                print("경고: comm_btn_close 를 찾지 못해 Close 생략.")
        except Exception as e_close:
            print(f"경고: Close 클릭 중 오류(무시): {e_close!r}")
            # 세션이 이미 끊어진 경우에는 바로 상위로 예외를 올려 전체 플로우를 중단
            if _is_session_lost_error(e_close):
                print("치명적: Close 중 세션 종료 감지 → 자동화 중단.")
                raise
        time.sleep(1.5)
    except InvalidSessionIdException:
        print("알림: 세션이 끊어져 Save/Close 를 건너뜁니다.")
        raise
    except Exception as e:
        print(f"경고: 저장/닫기 처리 중 오류: {e!r}")
        if _is_session_lost_error(e):
            print("치명적: 브라우저 세션이 끊어져 자동화를 중단합니다.")
            raise


def _go_to_reservation_list_page(driver: webdriver.Chrome, wait: WebDriverWait):
    """메인 화면에서 검색창으로 'reservation list' 페이지 진입."""
    driver.switch_to.default_content()
    search_input = wait.until(EC.presence_of_element_located((By.ID, "w_search")))
    time.sleep(1)
    search_input.click()
    search_input.clear()
    time.sleep(0.3)
    search_input.send_keys(SEARCH_QUERY)
    time.sleep(2)

    try:
        # 자동완성 목록이 뜨면, 아래로 두 번 내려가서 Enter (사용자 요청 동작)
        wait.until(EC.visibility_of_element_located((By.ID, "w_search_listbox")))
        time.sleep(0.5)
        search_input.send_keys(Keys.ARROW_DOWN)
        time.sleep(0.2)
        search_input.send_keys(Keys.ARROW_DOWN)
        time.sleep(0.2)
        search_input.send_keys(Keys.ENTER)
        print("검색 자동완성에서 아래로 2번 이동 후 항목 선택 완료.")
    except Exception:
        # 실패 시엔 한 번만 내려서 Enter 로 폴백
        search_input.send_keys(Keys.ARROW_DOWN)
        time.sleep(0.3)
        search_input.send_keys(Keys.ENTER)

    # 페이지 로딩 대기 후 iframe 진입
    time.sleep(5)
    _enter_iframe(driver)

    # 1) Arrival Date F/T 먼저 비우기
    _clear_arrival_dates(driver, wait)
    time.sleep(1)
    # 2) Rsvn Date F/T 오늘 날짜(MMDd) 입력
    _set_rsvn_dates_today(driver, wait)
    time.sleep(1)

    # 3) ACCOUNT_NAMES(.env의 ACCOUNTS) 순서대로 각 계정에 대해 Find → Cert(최초 1회만) → B2B 처리
    for i, account_name in enumerate(ACCOUNT_NAMES):
        print(f"--- Account '{account_name}' 처리 중 ---")
        _process_b2b_cycle(driver, wait, account_name=account_name, do_cert=(i == 0))

    print("Reservation List 페이지 설정 및 첫 회차 모든 Account B2B 예약 자동 처리 완료.")


def _process_b2b_cycle(
    driver: webdriver.Chrome,
    wait: WebDriverWait,
    account_name: str | None = None,
    do_cert: bool = False,
):
    """
    이미 Reservation List 화면이 열려 있다는 전제 하에,
    - account_name 이 있으면 해당 Account 필터 적용 후 Find (do_cert True면 Cert 최초 1회)
    - B2B 대상 예약들을 모두 순차 처리한 뒤 다시 Reservation List 로 돌아오는 사이클 1회.
    """
    _enter_iframe(driver)
    if account_name:
        _set_account_filter(driver, wait, account_name)
        time.sleep(1)
    _click_find(driver, wait)
    time.sleep(1)
    if do_cert:
        _click_cert(driver, wait)

    last_rsvn_no = None  # 방금 처리한 예약 번호 → 다음 탐색에서 제외
    while True:
        opened, rsvn_no = _open_first_reservation(
            driver, wait, account_name=account_name, skip_rsvn_no=last_rsvn_no
        )
        if not opened:
            break
        last_rsvn_no = rsvn_no
        time.sleep(2)  # 상세 화면 로딩 시간

        try:
            _process_reservation_detail(driver, wait, account_name=account_name)
            _save_and_close(driver, wait)
        except InvalidSessionIdException:
            print(
                "브라우저/세션이 끊어져 예약 상세 처리 루프를 종료합니다. "
                "(자동화 중에는 크롬 창을 닫지 마세요.)"
            )
            raise

        # List 로 복귀 후 Find 로 그리드 갱신, 갱신 대기 후 다음 행 탐색
        time.sleep(1)
        _enter_iframe(driver)
        _click_find(driver, wait)
        time.sleep(2.5)  # Find 후 그리드가 서버에서 갱신될 시간 확보

    label = f"Account '{account_name}' " if account_name else ""
    print(f"이번 회차 {label}B2B 예약 자동 처리를 모두 완료했습니다.")


def run():
    if not PMS_COMPANY or not PMS_ID or not PMS_PW:
        raise EnvironmentError(".env 파일에 PMS_COMPANY, PMS_ID, PMS_PW를 설정하세요.")

    driver = _build_driver()
    wait = WebDriverWait(driver, 30)

    try:
        _login(driver, wait)

        # 최초 1회: Reservation List 화면을 검색으로 연 뒤,
        # 필터/Cert 설정 및 B2B 예약들을 한 번 모두 처리한다.
        _go_to_reservation_list_page(driver, wait)

        # 이후에는 Reservation List 화면을 계속 켜 둔 채로,
        # 5분마다 각 Account 순서대로 Find → B2B 처리 반복.
        # (브라우저를 직접 닫으면 세션이 끊어져 대기 루프를 빠져나옴)
        while True:
            if not _driver_alive(driver):
                print("브라우저가 종료되어 자동화를 종료합니다.")
                break
            print("5분 대기 후 다음 B2B 자동 처리 회차를 시작합니다.")
            dead = False
            for remaining in range(300, 0, -60):
                print(f"다음 실행까지 남은 시간: 약 {remaining}초")
                if not _sleep_interruptible(driver, 60.0):
                    dead = True
                    break
            if dead:
                print("브라우저가 종료되어 자동화를 종료합니다.")
                break

            if not _driver_alive(driver):
                print("브라우저가 종료되어 자동화를 종료합니다.")
                break
            print("다음 회차 B2B 자동 처리를 시작합니다.")
            for account_name in ACCOUNT_NAMES:
                if not _driver_alive(driver):
                    dead = True
                    break
                print(f"--- Account '{account_name}' 처리 중 ---")
                _process_b2b_cycle(driver, wait, account_name=account_name, do_cert=False)
            if dead:
                print("브라우저가 종료되어 자동화를 종료합니다.")
                break
    except InvalidSessionIdException:
        print("브라우저 세션이 끊어져 자동화를 종료합니다. (크롬 창을 닫았거나 연결이 끊긴 경우)")
    finally:
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    run()