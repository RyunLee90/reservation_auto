import os
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
from selenium.common.exceptions import TimeoutException
from webdriver_manager.chrome import ChromeDriverManager

from handlers import get_handler
from handlers.base import normalize_for_remark

BASE_DIR = Path(__file__).resolve().parents[1]


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

# 처리할 Account 목록. .env 에 ACCOUNTS=히카리글로벌,여기어때,야놀자 처럼 쉼표 구분으로 넣으면 됨.
# 없으면 기본값은 히카리글로벌만.
_accounts_raw = (os.getenv("ACCOUNTS") or "히카리글로벌").strip()
ACCOUNT_NAMES = [name.strip() for name in _accounts_raw.split(",") if name.strip()]


def _build_driver() -> webdriver.Chrome:
    options = Options()
    options.add_argument("--start-maximized")
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
    yesterday = today - timedelta(days=1)
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

            # Remark 셀만 추출 (헤더 기반 인덱스, 없으면 마지막 셀)
            if remark_col_idx is not None and remark_col_idx < len(cells):
                remark_cell = cells[remark_col_idx]
            else:
                remark_cell = cells[-1]

            remark_txt = (remark_cell.text or "").strip()
            if not remark_txt:
                remark_txt = (remark_cell.get_attribute("innerText") or "").strip()

            # 히카리글로벌 전용: 이미 작업 완료 표시(OPEN/오픈/open)가 있으면 스킵
            skip_keywords = getattr(handler, "SKIP_REMARK_KEYWORDS", []) if handler else []
            if skip_keywords and any(sk.lower() in remark_txt.lower() for sk in skip_keywords):
                print(f"  스킵: 이미 처리된 Remark (Rsvn No: {rsvn_no}, Remark: '{remark_txt[:40]}')")
                continue

            matched_text = ""
            if match_all_remaining:
                # SKIP 에 걸리지 않았으면 Remark 내용과 무관하게 대상
                matched_text = remark_txt if remark_txt else "(빈 Remark)"
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


def _process_reservation_detail(
    driver: webdriver.Chrome,
    wait: WebDriverWait,
    account_name: str | None = None,
):
    """
    예약 상세 화면에서 다음 순서로 자동 처리.
    모든 필드 조작은 JS 로 수행 (그리드 오버레이로 인한 ElementClickIntercepted 방지).
    여기어때/야놀자는 Inter Memo 확인을 맨 먼저 수행.
    """

    # JS 헬퍼: 스크롤 → 값 비우기/채우기/클릭
    def _js_clear(el):
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
        time.sleep(0.15)
        driver.execute_script("arguments[0].value = '';", el)
        driver.execute_script(
            "arguments[0].dispatchEvent(new Event('input',{bubbles:true}));", el
        )

    def _js_set(el, val):
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
        time.sleep(0.15)
        driver.execute_script("arguments[0].value = arguments[1];", el, val)
        driver.execute_script(
            "arguments[0].dispatchEvent(new Event('input',{bubbles:true}));", el
        )

    def _js_click(el):
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
        time.sleep(0.15)
        driver.execute_script("arguments[0].click();", el)

    try:
        # ── 0) 그리드 오버레이 제거: 맨 위로 스크롤 ──
        driver.execute_script("window.scrollTo(0, 0);")
        time.sleep(0.5)

        # ── 1) (여기어때/야놀자 전용) Inter Memo 필수 워딩 먼저 확인 ──
        if account_name in ("여기어때", "야놀자"):
            memo_keywords = (
                ["룸온리"] if account_name == "여기어때"
                else ["룸UP", "선착순특가", "Room Only"]
            )
            try:
                # 클릭 전 현재 창 핸들 저장
                fit_handle = driver.current_window_handle
                handles_before = set(driver.window_handles)

                memo_btn = wait.until(
                    EC.presence_of_element_located(
                        (By.ID, "IR01_0101_V50_btn_Memo"),
                    )
                )
                _js_click(memo_btn)
                time.sleep(1.5)  # 새 창이 열릴 시간 확보

                # 새 창이 열렸는지 확인
                handles_after = set(driver.window_handles)
                new_handles = handles_after - handles_before

                if new_handles:
                    # 새 창으로 전환
                    memo_handle = new_handles.pop()
                    driver.switch_to.window(memo_handle)
                    print(f"Inter Memo 새 창으로 전환 완료.")
                    time.sleep(0.5)

                # 메모 텍스트 읽기
                memo_area = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.ID, "IR01_0114_frmE_memo")),
                )
                memo_text = (
                    memo_area.get_attribute("value") or memo_area.text or ""
                ).strip()
                print(f"디버그: Inter Memo 내용(account={account_name}): '{memo_text[:80]}'")
                has_required = any(kw in memo_text for kw in memo_keywords)

                # Inter Memo 닫기
                if driver.current_window_handle != fit_handle:
                    # 새 창으로 열린 경우 → 창 자체를 닫고 FIT Reservation 으로 복귀
                    driver.close()
                    driver.switch_to.window(fit_handle)
                    print("Inter Memo 창 닫고 FIT Reservation 으로 복귀.")
                else:
                    # 같은 창(오버레이)인 경우
                    # ★ comm_btn_close 를 그냥 클릭하면 FIT Reservation 자체가 닫힌다.
                    #   → Escape 키를 먼저 시도, 그래도 오버레이가 남으면
                    #     DOM 에서 comm_btn_close 가 2개 이상일 때만 마지막 것 클릭.
                    try:
                        driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
                    except Exception:
                        pass
                    time.sleep(0.5)

                    # 오버레이가 아직 살아 있는지 확인
                    still_open = bool(driver.find_elements(By.ID, "IR01_0114_frmE_memo"))
                    if still_open:
                        all_close = driver.find_elements(By.ID, "comm_btn_close")
                        if len(all_close) >= 2:
                            # 마지막 close 버튼이 Inter Memo 오버레이의 것
                            _js_click(all_close[-1])
                            print("Inter Memo 오버레이 close 버튼(마지막) 클릭 완료.")
                        else:
                            # close 버튼이 1개뿐 → FIT Reservation 버튼이므로 절대 클릭 금지
                            print("경고: comm_btn_close 1개뿐 - FIT Reservation 유지, Inter Memo 닫기 건너뜀.")
                time.sleep(0.7)

                # 복귀 후 맨 위로 스크롤
                driver.execute_script("window.scrollTo(0, 0);")
                time.sleep(0.3)

                if not has_required:
                    print(
                        f"알림: Inter Memo 에 필수 워딩 {memo_keywords} 중 어느 것도 없어 이 예약은 건너뜁니다."
                    )
                    return
                print(
                    f"Inter Memo 에 필수 워딩 {memo_keywords} 중 하나 이상을 확인했습니다. 나머지 자동 처리 계속 진행합니다."
                )
                time.sleep(0.3)
            except Exception as e:
                print(f"경고: Inter Memo 확인 중 오류(예약 건너뜁니다): {e}")
                # 혹시 창이 바뀐 상태라면 FIT Reservation 창으로 복귀 시도
                try:
                    if driver.current_window_handle != fit_handle:
                        driver.switch_to.window(fit_handle)
                except Exception:
                    pass
                return

        # ── 2) 이름 번역 ──
        try:
            name_input = wait.until(
                EC.presence_of_element_located(
                    (By.ID, "IR01_0101_V50_frmE01_txt_lastName"),
                )
            )
            name_en = (name_input.get_attribute("value") or name_input.text or "").strip()
            if name_en:
                name_ko = _translate_name_to_korean(name_en)
                _js_set(name_input, name_ko)
                print(f"이름 번역 및 입력 완료: '{name_en}' -> '{name_ko}'")
            else:
                print("알림: 이름 입력값이 비어 있어 번역을 건너뜁니다.")
        except Exception as e:
            print(f"경고: 이름 번역 실패(계속 진행): {e}")
        time.sleep(0.7)

        # ── 3) Nationality: 항상 기존 값 지우고 'kor' 입력 → South Korea 선택 ──
        try:
            nat_input = wait.until(
                EC.presence_of_element_located(
                    (By.ID, "IR01_0101_V50_frmE02_cmp_nationality_desc"),
                )
            )
            # 1) 기존 값 JS 로 초기화
            _js_clear(nat_input)
            time.sleep(0.3)
            # 2) 실제 클릭으로 포커스 이동 (JS click 은 send_keys 포커스가 안 잡힘)
            try:
                nat_input.click()
            except Exception:
                driver.execute_script("arguments[0].focus();", nat_input)
            time.sleep(0.3)
            # 3) 'kor' 입력
            nat_input.send_keys("kor")
            time.sleep(1.0)  # 자동완성 드롭다운 뜰 시간
            # 4) 자동완성 목록에서 'South Korea' 직접 클릭 시도, 실패 시 키보드로 선택
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
                time.sleep(0.3)
                nat_input.send_keys(Keys.ENTER)
                print("Nationality 키보드로 'South Korea' 선택 완료.")
        except Exception as e:
            print(f"경고: Nationality 자동 설정 건너뜁니다: {e}")
        time.sleep(0.7)

        # ── 4) Mobile 삭제 ──
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
        time.sleep(0.7)

        # ── 5) E-Mail 삭제 ──
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
        time.sleep(0.7)

        # ── 6) Remark 비우기 ──
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
        time.sleep(0.7)

        # ── 7) Total Amount → Remark 에 계정별 형식으로 입력 ──
        try:
            total_input = wait.until(
                EC.presence_of_element_located(
                    (By.ID, "IR01_0101_V50_frmE01_cur_total"),
                )
            )
            total_val = (total_input.get_attribute("value") or total_input.text or "").strip()
            if not total_val:
                print("알림: Total Amount 값이 비어 있어 Remark 에 금액을 입력하지 않습니다.")
            else:
                handler = get_handler(account_name) if account_name else None
                fmt = getattr(handler, "REMARK_FORMAT", None) if handler else None
                new_remark = fmt.format(total=total_val) if fmt else f"{total_val} OPEN / RO"
                remark_input = wait.until(
                    EC.presence_of_element_located(
                        (By.ID, "IR01_0101_V50_frmE01_txt_remark"),
                    )
                )
                _js_set(remark_input, new_remark)
                print(f"Remark 에 금액 입력 완료: '{new_remark}'")
        except Exception as e:
            print(f"경고: Remark 금액 입력 실패(계속 진행): {e}")
        time.sleep(0.7)

        print("예약 상세 화면 자동 처리 완료.")
    except Exception as e:
        print(f"경고: 예약 상세 화면 자동 처리 중 오류: {e}")
        # 브라우저 세션이 끊어진 경우에는 더 이상 진행해도 의미가 없으므로 그대로 예외를 올려서 run() 전체를 종료한다.
        if "invalid session id" in str(e).lower():
            print("치명적: 브라우저 세션이 끊어져 자동화를 중단합니다.")
            raise


def _save_and_close(driver: webdriver.Chrome, wait: WebDriverWait):
    """
    예약 상세 화면 저장 후 FIT 상세만 닫기.
    Save → OK 팝업 → (iframe 복귀 후) 상세창 Close 클릭 → Reservation List 로 복귀.
    Close 를 눌러야 Find 버튼이 다시 보이므로 반드시 수행.
    """
    try:
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
        time.sleep(1.5)
    except Exception as e:
        print(f"경고: 저장/닫기 처리 중 오류: {e!r}")
        if "invalid session id" in str(e).lower():
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
        listbox = wait.until(EC.visibility_of_element_located((By.ID, "w_search_listbox")))
        time.sleep(0.5)
        items = listbox.find_elements(By.CSS_SELECTOR, "li[role='option'], .k-item, li")
        clicked = False
        preferred = None
        fallback = None
        for item in items:
            text_raw = item.text or ""
            text = text_raw.lower().strip()
            # 1순위: 'reservation list' 이면서 'group' 이 포함되지 않은 항목
            if "reservation list" in text and "group" not in text:
                preferred = item
                break
            # 2순위: 'reservation list' 가 들어간 항목 (기억만 해둠)
            if "reservation list" in text and fallback is None:
                fallback = item
        target = preferred or fallback or (items[0] if items else None)
        if target:
            driver.execute_script("arguments[0].click();", target)
            clicked = True
            print(f"검색 자동완성에서 선택한 항목: '{(target.text or '').strip()}'")
    except Exception:
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

        _process_reservation_detail(driver, wait, account_name=account_name)
        _save_and_close(driver, wait)

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
        while True:
            print("5분 대기 후 다음 B2B 자동 처리 회차를 시작합니다.")
            for remaining in range(300, 0, -60):
                print(f"다음 실행까지 남은 시간: 약 {remaining}초")
                time.sleep(60)

            print("다음 회차 B2B 자동 처리를 시작합니다.")
            for account_name in ACCOUNT_NAMES:
                print(f"--- Account '{account_name}' 처리 중 ---")
                _process_b2b_cycle(driver, wait, account_name=account_name, do_cert=False)
    finally:
        driver.quit()


if __name__ == "__main__":
    run()

