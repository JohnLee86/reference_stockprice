#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
KRX Data Marketplace에 실제 계정으로 로그인한 뒤(1회), 여러 회사를 순회하며
'개별종목 시세 추이' 화면에서 일자별 종가와 "정규시장" 거래량을 추출한다.

정규시장/애프터마켓 거래량은 header 텍스트가 아니라, 각 행에서
"총계 = 정규시장 + 애프터마켓"이 성립하는 연속된 세 숫자(트리플렛)를 찾아
자동으로 식별한다 (표의 정확한 열 구조가 바뀌어도 견고하게 동작).

입력: --manifest로 지정한 JSON 파일
      [{"company": "삼성전자", "ticker": "005930",
        "from_date": "20250801", "to_date": "20260915", "output": "data/..."}, ...]

출력: 각 회사별로 output에 지정한 경로 (날짜,종가,거래량)
      거래량 컬럼에는 "정규시장" 거래량만 들어간다.

자격증명은 환경변수로만 받는다: KRX_ID, KRX_PW
"""
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

LOGIN_URL = "https://data.krx.co.kr/contents/MDC/COMS/client/MDCCOMS001.cmd"
STOCK_PAGE_URL = "https://data.krx.co.kr/contents/MDC/MDI/mdiLoader/index.cmd?menuId=MDC0201020203"


def find_login_frame(page):
    """로그인 프레임 찾기"""
    for f in page.frames:
        if f.name == "COMS001_FRAME":
            return f
    return None


def check_popup(page):
    """팝업 메시지 확인"""
    for frame in page.frames:
        try:
            if frame.get_by_text("이미 로그인된 계정입니다").count() > 0:
                return frame
        except Exception:
            continue
    return None


def check_success(page) -> bool:
    """로그인 성공 확인"""
    try:
        return "로그아웃" in page.inner_text("body")
    except Exception:
        return False


def login(page, krx_id, krx_pw) -> bool:
    """KRX 로그인"""
    print("[로그인] 로그인 페이지 이동 중...")
    page.goto(LOGIN_URL, wait_until="networkidle", timeout=30000)
    page.wait_for_timeout(1500)

    for attempt in range(5):
        popup_frame = check_popup(page)
        if popup_frame:
            try:
                popup_frame.get_by_role("button", name="확인", exact=True).click()
            except Exception:
                pass
            page.wait_for_timeout(1500)
            continue

        if check_success(page):
            print("[로그인] 이미 로그인된 상태")
            return True

        login_frame = find_login_frame(page)
        if login_frame is None:
            print(f"[로그인] 시도 {attempt+1}/5 - 로그인 프레임 찾기 실패, 대기 중...")
            page.wait_for_timeout(1500)
            continue

        try:
            print(f"[로그인] 시도 {attempt+1}/5 - 자격증명 입력 중...")
            login_frame.locator("input[name='mbrId']").fill(krx_id)
            login_frame.locator("input[name='pw']").fill(krx_pw)
            login_frame.get_by_role("link", name="로그인", exact=True).click(timeout=5000)
        except Exception as e:
            print(f"[로그인] 입력/클릭 실패: {e}")
            page.wait_for_timeout(1000)
            continue

        for _ in range(16):
            page.wait_for_timeout(500)
            if check_success(page):
                print("[로그인] ✓ 로그인 성공!")
                return True
            if check_popup(page):
                break

    print("[로그인] ✗ 최대 시도 횟수 초과", file=sys.stderr)
    return False


def parse_number(text: str):
    """숫자 파싱 (쉼표, % 제거)"""
    t = text.replace(",", "").replace("%", "").strip()
    if re.match(r"^-?\d+$", t):
        return int(t)
    return None


def _count_date_rows(table) -> int:
    """표 안에서 '일자 형식' 셀로 시작하는 행이 몇 개인지 센다 (가상 스크롤 진행 상황 확인용)."""
    try:
        rows = table.locator("tr").all()
    except Exception:
        return 0
    count = 0
    for row in rows:
        try:
            first_td = row.locator("td").first
            text = first_td.inner_text(timeout=500).strip()
        except Exception:
            continue
        if re.match(r"^\d{4}/\d{2}/\d{2}$", text):
            count += 1
    return count


def find_data_table(page):
    """일자 형식 행을 하나 이상 포함한 표를 프레임 전체에서 찾아 반환한다 (없으면 None)."""
    best_table = None
    best_count = 0
    for frame in page.frames:
        try:
            tables = frame.locator("table").all()
        except Exception:
            continue
        for table in tables:
            count = _count_date_rows(table)
            if count > best_count:
                best_count = count
                best_table = table
    return best_table, best_count


def scroll_to_load_all_rows(page, company: str, expected_count: int | None = None, max_iterations: int = 150) -> None:
    """KRX [12003] 표는 가상 스크롤(virtual scroll) 그리드라서, 화면에 렌더링된 행만
    DOM에 존재한다. scroll_into_view_if_needed는 이 그리드의 lazy-load를 못 건드리는
    것으로 확인되어, 실제 마우스 휠 스크롤을 흉내내는 page.mouse.wheel로 반복 스크롤한다.
    expected_count(서버 응답의 실제 건수)를 알면 그 값에 도달할 때까지, 모르면 행 개수가
    더 늘지 않을 때까지 진행한다."""
    table, prev_count = find_data_table(page)
    if table is None:
        print(f"[{company}] ⚠ 스크롤 대상 표를 찾지 못했습니다 (건너뜀)")
        return

    try:
        box = table.bounding_box()
        if box:
            page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    except Exception:
        pass

    stable_rounds = 0
    for i in range(max_iterations):
        try:
            page.mouse.wheel(0, 1500)
        except Exception:
            pass
        page.wait_for_timeout(200)

        table, count = find_data_table(page)
        if table is None:
            break

        if expected_count and count >= expected_count:
            prev_count = count
            break

        if count <= prev_count:
            stable_rounds += 1
        else:
            stable_rounds = 0
        prev_count = count

        # expected_count를 모를 때만: 5번 연속 행 개수가 안 늘면 종료
        if not expected_count and stable_rounds >= 5:
            break

    print(f"[{company}] 스크롤 완료 - 렌더링된 행 수: {prev_count}"
          + (f" / 목표: {expected_count}" if expected_count else ""))


def extract_regular_volume_rows(page, from_dt: datetime, to_dt: datetime) -> dict:
    """{날짜문자열(YYYY-MM-DD): (종가, 정규시장거래량)} 딕셔너리 반환.

    페이지에는 이전 조회의 잔여 표(stale)나 로딩 중간 상태의 표가 함께 남아있을 수 있으므로,
    '일자 형식의 셀을 가장 많이 포함한 표' 하나만 진짜 데이터로 간주해 사용한다.
    """
    best_table_rows = []
    best_date_count = 0

    for frame in page.frames:
        try:
            tables = frame.locator("table").all()
        except Exception:
            continue
        for table in tables:
            try:
                rows = table.locator("tr").all()
            except Exception:
                continue
            date_count = 0
            row_cells = []
            for row in rows:
                try:
                    tds = row.locator("td").all_inner_texts()
                except Exception:
                    continue
                if (
                    tds
                    and re.match(r"^\d{4}/\d{2}/\d{2}$", tds[0].strip())
                    and len(tds) >= 4
                    and parse_number(tds[1]) is not None
                ):
                    date_count += 1
                row_cells.append(tds)
            if date_count > best_date_count:
                best_date_count = date_count
                best_table_rows = row_cells

    results = {}
    for tds in best_table_rows:
        if len(tds) < 4:
            continue
        date_text = tds[0].strip()
        if not re.match(r"^\d{4}/\d{2}/\d{2}$", date_text):
            continue
        try:
            row_date = datetime.strptime(date_text, "%Y/%m/%d")
        except ValueError:
            continue
        if row_date < from_dt or row_date > to_dt:
            continue

        close = parse_number(tds[1])
        if close is None:
            continue

        nums = [n for n in (parse_number(t) for t in tds[2:]) if n is not None]
        regular_volume = None
        for i in range(len(nums) - 2):
            a, b, c = nums[i], nums[i + 1], nums[i + 2]
            if a > 0 and a == b + c:
                regular_volume = b
                break
        if regular_volume is None:
            continue

        key = row_date.strftime("%Y-%m-%d")
        results[key] = (close, regular_volume)
    return results


def find_search_result(page, ticker: str, company: str, max_wait_ms: int = 12000) -> bool:
    """
    검색 결과에서 종목코드 찾아 클릭 (개선된 3가지 방법)

    방법 1: 정확한 텍스트 매칭 (text= selector)
    방법 2: 셀 텍스트 포함 검색
    방법 3: 행(row) 전체 텍스트 검색

    Args:
        page: Playwright page 객체
        ticker: 종목코드 (예: "005930")
        company: 회사명 (로그 출력용)
        max_wait_ms: 최대 대기 시간 (밀리초)

    Returns:
        성공 시 True, 실패 시 False
    """
    print(f"[{company}] 검색 결과 대기 중 ({ticker})...")

    start_time = datetime.now()
    attempt_count = 0

    while True:
        elapsed_ms = (datetime.now() - start_time).total_seconds() * 1000
        if elapsed_ms > max_wait_ms:
            print(f"[{company}] ✗ 검색 결과 타임아웃 ({max_wait_ms}ms 초과)")
            return False

        attempt_count += 1

        # 모든 frame에서 종목코드 검색
        for frame in page.frames:
            try:
                # ========== 방법 1: text= selector로 직접 검색 ==========
                try:
                    cells = frame.locator(f"text={ticker}").all()
                    if cells:
                        for cell in cells:
                            try:
                                cell.click(timeout=2000)
                                print(f"[{company}] ✓ 검색 결과 클릭 성공 (방법 1: text selector)")
                                return True
                            except Exception:
                                continue
                except Exception:
                    pass

                # ========== 방법 2: 모든 td 셀 텍스트 검색 ==========
                try:
                    td_elements = frame.locator("td").all()
                    if td_elements:
                        for i, td_el in enumerate(td_elements):
                            try:
                                td_text = td_el.inner_text()
                                if ticker in td_text.strip():
                                    td_el.click(timeout=2000)
                                    print(f"[{company}] ✓ 검색 결과 클릭 성공 (방법 2: td 텍스트 검색)")
                                    return True
                            except Exception:
                                continue
                except Exception:
                    pass

                # ========== 방법 3: tr(행) 전체 텍스트 검색 ==========
                try:
                    rows = frame.locator("tr").all()
                    if rows:
                        for row in rows:
                            try:
                                row_text = row.inner_text()
                                if ticker in row_text:
                                    row.click(timeout=2000)
                                    print(f"[{company}] ✓ 검색 결과 클릭 성공 (방법 3: row 텍스트 검색)")
                                    return True
                            except Exception:
                                continue
                except Exception:
                    pass

            except Exception:
                continue

        # 500ms 대기 후 재시도
        page.wait_for_timeout(500)

        # 10회 시도마다 진행 상황 로그
        if attempt_count % 10 == 0:
            print(f"[{company}] 계속 대기 중... ({int(elapsed_ms)}ms / {max_wait_ms}ms)")


def save_debug_snapshot(page, company: str, tag: str):
    """디버깅용: 현재 화면 스크린샷 + 각 프레임의 HTML을 data/debug/에 저장한다."""
    debug_dir = Path("data/debug")
    debug_dir.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^0-9A-Za-z가-힣_-]", "_", f"{company}_{tag}")
    try:
        page.screenshot(path=str(debug_dir / f"{safe}.png"), full_page=True)
        print(f"[{company}] 📸 디버그 스크린샷 저장: data/debug/{safe}.png")
    except Exception as e:
        print(f"[{company}] 스크린샷 저장 실패: {e}")


def process_company(page, company: str, ticker: str, from_date: str, to_date: str, output_path: Path,
                     debug: bool = False) -> bool:
    """각 회사의 데이터를 조회하고 저장"""
    print(f"\n{'='*70}")
    print(f"[{company}] ({ticker}) 처리 시작")
    print(f"{'='*70}")

    if debug:
        def _log_request(request):
            if "getJsonData.cmd" in request.url and request.method == "POST":
                try:
                    print(f"[{company}] 🌐 실제 전송된 요청 파라미터: {request.post_data}")
                except Exception as e:
                    print(f"[{company}] 요청 로깅 실패: {e}")
        page.on("request", _log_request)
          
    try:
        print(f"[{company}] 1단계: 종목 선택 페이지로 이동...")
        page.goto(STOCK_PAGE_URL, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(2000)
    except Exception as e:
        print(f"[{company}] ✗ 페이지 이동 실패: {e}")
        return False

    # ========== 1단계: 상단 통합검색에서 회사명 검색 ==========
    print(f"[{company}] 회사명 검색 중: {company}")

    search_box = None
    for frame in page.frames:
        try:
            el = frame.locator("input[id='jsTotSch']")
            if el.count() > 0:
                search_box = el.first
                break
        except Exception:
            continue

    if search_box is None:
        print(f"[{company}] ✗ 상단 통합검색창을 찾지 못했습니다.")
        return False

    search_box.click()
    search_box.fill(company)
    page.wait_for_timeout(300)

    # 검색 버튼 클릭
    clicked_search = False
    for frame in page.frames:
        try:
            btn = frame.locator("button[id='jsTotSchBtn']")
            if btn.count() > 0:
                btn.first.click()
                clicked_search = True
                break
        except Exception:
            continue

    if not clicked_search:
        print(f"[{company}] Enter 키로 검색...")
        search_box.press("Enter")

    page.wait_for_timeout(1000)

    # ========== 검색 결과에서 종목코드 클릭 (개선된 방식) ==========
    if not find_search_result(page, ticker, company, max_wait_ms=12000):
        print(f"[{company}] ✗ 검색 결과에서 종목코드를 찾지 못했습니다. 건너뜁니다.")
        return False

    page.wait_for_timeout(2000)

    # 종목코드 확인
    ticker_confirmed = False
    for frame in page.frames:
        try:
            if f"({ticker})" in frame.inner_text("body"):
                ticker_confirmed = True
                break
        except Exception:
            continue

    if not ticker_confirmed:
        print(f"[{company}] ✗ 종목 선택 화면에서 {ticker} 확인 실패")
        return False

    print(f"[{company}] ✓ 종목 선택 완료")

    # ========== 2단계: 화면번호로 [12003] 이동 ==========
    print(f"[{company}] 2단계: 개별종목 시세추이 화면(12003) 이동 중...")

    screen_search = None
    for frame in page.frames:
        try:
            el = frame.locator("input[id='jsMdiMenuSearchValue']")
            if el.count() > 0:
                screen_search = el.first
                break
        except Exception:
            continue

    if screen_search is None:
        print(f"[{company}] ✗ 화면번호 검색창을 찾지 못했습니다.")
        return False

    screen_search.click()
    screen_search.fill("12003")
    page.wait_for_timeout(800)

    clicked_search_link = False
    for frame in page.frames:
        try:
            btn = frame.locator("a[id='jsMdiMenuSearchButton']")
            if btn.count() > 0:
                btn.first.click()
                clicked_search_link = True
                break
        except Exception:
            continue

    if not clicked_search_link:
        screen_search.press("Enter")

    page.wait_for_timeout(1500)

    # 개별종목 시세추이 메뉴 클릭
    for frame in page.frames:
        try:
            cand = frame.locator(":text-is('개별종목 시세추이')")
            if cand.count() > 0:
                cand.first.click()
                break
        except Exception:
            continue

    page.wait_for_timeout(2000)
    print(f"[{company}] ✓ 화면 전환 완료")

    if debug:
        save_debug_snapshot(page, company, "01_화면전환직후")

    # ========== 3단계: 조회기간 입력 ==========
    print(f"[{company}] 3단계: 조회기간 입력 중... ({from_date} ~ {to_date})")

    filled_dates = False
    for attempt in range(3):
        date_els = None
        for frame in page.frames:
            try:
                date_inputs = frame.locator("input[type='text']").all()
            except Exception:
                continue

            matches = []
            for el in date_inputs:
                try:
                    val = el.input_value()
                except Exception:
                    continue
                if re.match(r"^\d{8}$", val or ""):
                    matches.append(el)

            if len(matches) >= 2:
                date_els = matches
                break

        if date_els is None:
            print(f"[{company}] ⚠ 조회기간 입력창을 찾지 못했습니다 (시도 {attempt + 1}/3)")
            if debug:
                for fi, frame in enumerate(page.frames):
                    try:
                        info = frame.eval_on_selector_all(
                            "input[type='text']",
                            "els => els.map(e => `id=${e.id}|name=${e.name}|value=${e.value}`)"
                        )
                        print(f"[{company}]   frame{fi} ({frame.url}) 텍스트 입력창 목록: {info}")
                    except Exception as e:
                        print(f"[{company}]   frame{fi} 조회 실패: {e}")
            page.wait_for_timeout(500)
            continue

        start_input, end_input = date_els[0], date_els[1]

        # .fill()은 값만 강제로 바꿀 뿐 keyup 이벤트를 안 보내서, 이 값에 의존하는
        # 사이트 내부 로직이 반응 안 할 수 있다 (예전 종목명 자동완성 문제와 동일한 패턴).
        # 실제 키 입력을 흉내내는 press_sequentially로 한 글자씩 입력한다.
        for el, val in ((start_input, from_date), (end_input, to_date)):
            el.click()
            el.press("Control+A")
            el.press("Delete")
            el.press_sequentially(val, delay=60)
            el.press("Tab")  # blur를 발생시켜 사이트 쪽 값 검증/등록을 유도
        page.wait_for_timeout(300)

        actual_from = start_input.input_value()
        actual_to = end_input.input_value()
        if actual_from == from_date and actual_to == to_date:
            filled_dates = True
            print(f"[{company}] ✓ 조회기간 입력 완료 및 값 확인됨 (키 입력 방식)")
            break
        else:
            print(f"[{company}] ⚠ 조회기간 값이 유지되지 않음 "
                  f"(기대: {from_date}~{to_date}, 실제: {actual_from}~{actual_to}) - 재시도 (시도 {attempt + 1}/3)")

    if not filled_dates:
        print(f"[{company}] ⚠ 조회기간 입력에 실패했습니다 (기본 프리셋 기간으로 조회될 수 있음)")
        if debug:
            save_debug_snapshot(page, company, "02_기간입력실패")

    page.wait_for_timeout(800)

    # ========== 조회 버튼 클릭 (응답 도착까지만 대기 - 더 이상 표를 안 읽으므로 카운트는 불필요) ==========
    response_arrived = {"done": False}

    def _mark_response(response):
        if "getJsonData.cmd" in response.url and response.request.method == "POST":
            response_arrived["done"] = True

    page.on("response", _mark_response)

    clicked_search_btn = False
    for frame in page.frames:
        try:
            btn = frame.locator("a[id='jsSearchButton']")
            if btn.count() > 0:
                btn.first.click()
                clicked_search_btn = True
                break
        except Exception:
            continue

    if not clicked_search_btn:
        for frame in page.frames:
            try:
                loc = frame.locator(":text-is('조회')")
                cnt = loc.count()
                if cnt > 0:
                    loc.nth(cnt - 1).click()
                    clicked_search_btn = True
                    break
            except Exception:
                continue

    if not clicked_search_btn:
        page.remove_listener("response", _mark_response)
        print(f"[{company}] ✗ 조회 버튼을 찾지 못했습니다.")
        return False

    print(f"[{company}] 데이터 조회 진행 중 (서버 응답 대기)...")
    for _ in range(40):
        page.wait_for_timeout(500)
        if response_arrived["done"]:
            break
    page.remove_listener("response", _mark_response)
    page.wait_for_timeout(1000)  # 응답 도착 후 화면 반영 약간의 여유

    # ========== [임시] 다운로드 버튼 -> CSV 클릭 -> 실제 다운로드 파일 저장 ==========
    # 표를 직접 읽는 방식 대신, KRX가 제공하는 CSV 다운로드 기능을 그대로 사용한다.
    # 다운로드된 파일의 실제 컬럼 구조를 아직 모르므로, 이번 단계는 "원본 그대로 저장"까지만
    # 하고 최종 형식(날짜,종가,거래량)으로 변환하는 건 다음 단계에서 완성한다.
    download_btn = None
    for frame in page.frames:
        try:
            candidate = frame.locator("button.CI-MDI-UNIT-DOWNLOAD:visible")
            if candidate.count() > 0:
                download_btn = candidate.first
                break
        except Exception:
            continue

    if download_btn is None:
        print(f"[{company}] ✗ 다운로드 버튼(.CI-MDI-UNIT-DOWNLOAD)을 찾지 못했습니다.")
        return False

    try:
        download_btn.scroll_into_view_if_needed(timeout=5000)
    except Exception:
        pass

    if debug:
        save_debug_snapshot(page, company, "03_다운로드버튼클릭직전")

    try:
        download_btn.click(timeout=5000)
    except Exception as e:
        print(f"[{company}] ✗ 다운로드 버튼 클릭 실패: {e}")
        if debug:
            save_debug_snapshot(page, company, "04_다운로드버튼클릭실패")
        return False

    page.wait_for_timeout(500)

    csv_link = None
    for frame in page.frames:
        try:
            candidate = frame.locator("div[data-type='csv'] a:visible")
            if candidate.count() > 0:
                csv_link = candidate.first
                break
        except Exception:
            continue

    if csv_link is None:
        print(f"[{company}] ✗ 다운로드 팝업의 CSV 링크를 찾지 못했습니다.")
        if debug:
            save_debug_snapshot(page, company, "03_다운로드팝업")
        return False

    raw_path = output_path.parent / f"{company}_KRX원본다운로드.csv"
    try:
        with page.expect_download(timeout=15000) as download_info:
            csv_link.click()
        download = download_info.value
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        download.save_as(str(raw_path))
    except Exception as e:
        print(f"[{company}] ✗ CSV 다운로드 실패: {e}")
        return False

    # ========== 다운로드된 CSV에서 날짜/종가/정규시장 거래량만 추출해 저장 ==========
    # KRX 다운로드 CSV 컬럼: 일자,종가,대비,등락률,시가,고가,저가,거래량,
    #                        거래량_정규시장,거래량_애프터마켓,거래대금,... (확인 완료)
    try:
        raw_bytes = raw_path.read_bytes()
        text = None
        for enc in ("utf-8-sig", "cp949", "euc-kr"):
            try:
                text = raw_bytes.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            raise ValueError("알 수 없는 인코딩")

        import csv as csv_module
        import io
        reader = csv_module.DictReader(io.StringIO(text))
        rows = {}
        for row in reader:
            date_str = (row.get("일자") or "").strip()
            close = (row.get("종가") or "").replace(",", "").strip()
            vol_regular = (row.get("거래량_정규시장") or "").replace(",", "").strip()
            if not date_str or not close or not vol_regular:
                continue
            rows[date_str] = (close, vol_regular)
    except Exception as e:
        print(f"[{company}] ✗ CSV 파싱 실패: {e}")
        return False

    if not rows:
        print(f"[{company}] ✗ 다운로드된 CSV에서 유효한 행을 찾지 못했습니다.")
        return False

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8-sig") as f:
        f.write("날짜,종가,거래량\n")
        for date_str in sorted(rows.keys()):
            close, vol = rows[date_str]
            f.write(f"{date_str},{close},{vol}\n")

    print(f"[{company}] ✓ 저장 완료: {len(rows)}일치 → {output_path}")
    return True
                           
def main():
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True, help="회사/기간 목록 JSON 파일 경로")
    args = ap.parse_args()

    krx_id = os.environ.get("KRX_ID")
    krx_pw = os.environ.get("KRX_PW")
    if not krx_id or not krx_pw:
        print("✗ 오류: KRX_ID 또는 KRX_PW 환경변수가 설정되지 않았습니다.", file=sys.stderr)
        sys.exit(1)

    with open(args.manifest, encoding="utf-8") as f:
        manifest = json.load(f)

    print("\n" + "="*70)
    print("KRX 데이터 자동 다운로드 시작")
    print("="*70)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1920, "height": 2400},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()

        print("\n[로그인] KRX 로그인 시도 중...")
        if not login(page, krx_id, krx_pw):
            print("✗ 로그인 실패", file=sys.stderr)
            browser.close()
            sys.exit(1)

        overall_ok = True
        success_count = 0
        fail_count = 0

        for i, entry in enumerate(manifest, 1):
            print(f"\n[진행률] {i}/{len(manifest)}")
            output_path = Path(entry["output"])
            ok = process_company(
                page, entry["company"], entry["ticker"],
                entry["from_date"], entry["to_date"], output_path,
                debug=(i == 1),
            )
            if ok:
                success_count += 1
            else:
                fail_count += 1
                overall_ok = False

        browser.close()

    # ========== 최종 결과 ==========
    print("\n" + "="*70)
    print("처리 완료")
    print("="*70)
    print(f"✓ 성공: {success_count}개")
    print(f"✗ 실패: {fail_count}개")
    print("="*70)

    if not overall_ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
