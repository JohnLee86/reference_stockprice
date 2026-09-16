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
        "from_date": "20250801", "to_date": "20260915"}, ...]

출력: 각 회사별로 data/{company}_원자료_임시.csv (날짜,종가,거래량)
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
    for f in page.frames:
        if f.name == "COMS001_FRAME":
            return f
    return None


def check_popup(page):
    for frame in page.frames:
        try:
            if frame.get_by_text("이미 로그인된 계정입니다").count() > 0:
                return frame
        except Exception:
            continue
    return None


def check_success(page) -> bool:
    try:
        return "로그아웃" in page.inner_text("body")
    except Exception:
        return False


def login(page, krx_id, krx_pw) -> bool:
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
            return True

        login_frame = find_login_frame(page)
        if login_frame is None:
            page.wait_for_timeout(1500)
            continue

        try:
            login_frame.locator("input[name='mbrId']").fill(krx_id)
            login_frame.locator("input[name='pw']").fill(krx_pw)
            login_frame.get_by_role("link", name="로그인", exact=True).click(timeout=5000)
        except Exception:
            page.wait_for_timeout(1000)
            continue

        for _ in range(16):
            page.wait_for_timeout(500)
            if check_success(page):
                return True
            if check_popup(page):
                break

    return False


def parse_number(text: str):
    t = text.replace(",", "").replace("%", "").strip()
    if re.match(r"^-?\d+$", t):
        return int(t)
    return None


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
        results[key] = (close, regular_volume)  # 동일 날짜가 또 나오면 마지막 값으로 덮어씀
    return results


def process_company(page, company: str, ticker: str, from_date: str, to_date: str, output_path: Path) -> bool:
    """'화면번호/화면명 검색'창에 12003을 입력해 '[12003] 개별종목 시세 추이' 화면으로 바로 이동한 뒤,
    종목명 검색 + 조회기간 입력 + 조회를 한 번에 수행한다."""
    print(f"\n--- [{company}] 처리 시작 ---")

    try:
        page.goto(STOCK_PAGE_URL, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(3000)
    except Exception as e:
        print(f"[{company}] 페이지 이동 실패: {e}")
        return False

    # 사이드바가 접혀있을 수 있어 햄버거(☰) 아이콘이 있으면 눌러서 펼친다
    try:
        for frame in page.frames:
            hamburger = frame.locator("button:has-text('☰'), .hamburger, [class*='menu-toggle'], [class*='gnb-toggle']")
            if hamburger.count() > 0 and hamburger.first.is_visible():
                hamburger.first.click()
                page.wait_for_timeout(1000)
                break
    except Exception:
        pass

    # 1단계: 화면번호 검색으로 [12003] 이동
    screen_search = None
    for frame in page.frames:
        try:
            el = frame.locator("input[id='CI-ALL-MENU-SEARCH-VALUE']")
            if el.count() > 0:
                screen_search = el.first
                break
        except Exception:
            continue
    if screen_search is None:
        print(f"[{company}] 화면번호 검색창을 찾지 못했습니다.")
        return False

    try:
        screen_search.wait_for(state="visible", timeout=8000)
        screen_search.click()
    except Exception:
        print(f"[{company}] 화면번호 검색창이 안 보여 강제(force) 입력으로 시도합니다.")
        try:
            screen_search.click(force=True)
        except Exception as e:
            print(f"[{company}] 강제 클릭도 실패: {e}")
            return False
    screen_search.fill("12003", force=True)
    page.wait_for_timeout(800)
    screen_search.press("Enter")
    page.wait_for_timeout(2000)

    # 2단계: [12003] 화면에서 종목명 검색
    search_input = None
    target_frame = None
    for frame in page.frames:
        try:
            el = frame.locator("input[name*='tboxisuCd_finder']")
            if el.count() > 0:
                search_input = el.first
                target_frame = frame
                break
        except Exception:
            continue

    if search_input is None:
        print(f"[{company}] [12003] 화면의 종목검색기 입력창을 찾지 못했습니다.")
        return False

    search_input.click()
    search_input.fill("")
    page.wait_for_timeout(300)
    try:
        search_input.press_sequentially(company, delay=120)
    except Exception:
        search_input.fill(company)
    page.wait_for_timeout(2000)

    suggestion_clicked = False
    try:
        for tag in ["li", "div", "td", "a", "span"]:
            loc = target_frame.locator(f"{tag}:text-is('{company}')")
            if loc.count() > 0:
                loc.first.click()
                suggestion_clicked = True
                print(f"[{company}] 자동완성 항목 클릭 성공 (tag={tag})")
                break
    except Exception as e:
        print(f"[{company}] 자동완성 클릭 시도 중 오류: {e}")

    if not suggestion_clicked:
        print(f"[{company}] 자동완성 항목을 못 찾아 방향키+엔터로 대체 시도")
        try:
            search_input.press("ArrowDown")
            page.wait_for_timeout(500)
            search_input.press("Enter")
        except Exception:
            pass
    page.wait_for_timeout(800)

    # 3단계: 조회기간(시작일/종료일) 입력 - 8자리 날짜값을 가진 입력창 두 개를 찾는다
    filled_dates = False
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
            matches[0].fill(from_date)
            matches[1].fill(to_date)
            filled_dates = True
            print(f"[{company}] 조회기간 입력: {from_date} ~ {to_date}")
            break
    if not filled_dates:
        print(f"[{company}] 조회기간 입력창을 찾지 못했습니다 - 기본 기간으로 진행합니다.")

    # 4단계: 조회
    clicked_search_btn = False
    for frame in page.frames:
        try:
            loc = frame.locator(":text-is('조회')")
            if loc.count() > 0:
                loc.first.click()
                clicked_search_btn = True
                break
        except Exception:
            continue
    if not clicked_search_btn:
        print(f"[{company}] '조회' 요소를 찾지 못했습니다.")
        return False

    page.wait_for_timeout(2500)

    ticker_confirmed = False
    for frame in page.frames:
        try:
            if f"({ticker})" in frame.inner_text("body") or ticker in frame.inner_text("body"):
                ticker_confirmed = True
                break
        except Exception:
            continue
    if not ticker_confirmed:
        print(f"[{company}] 검색/선택 실패로 보입니다 - 화면에서 종목코드({ticker})를 확인하지 못했습니다. 건너뜁니다.")
        return False

    from_dt = datetime.strptime(from_date, "%Y%m%d")
    to_dt = datetime.strptime(to_date, "%Y%m%d")
    rows = extract_regular_volume_rows(page, from_dt, to_dt)

    if not rows:
        print(f"[{company}] 추출된 데이터가 없습니다 (기간: {from_date}~{to_date}).")
        return False

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8-sig") as f:
        f.write("날짜,종가,거래량\n")
        for date_str in sorted(rows.keys()):
            close, vol = rows[date_str]
            f.write(f"{date_str},{close},{vol}\n")

    print(f"[{company}] {len(rows)}일치 저장 완료: {output_path}")
    return True


def main():
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True, help="회사/기간 목록 JSON 파일 경로")
    args = ap.parse_args()

    krx_id = os.environ.get("KRX_ID")
    krx_pw = os.environ.get("KRX_PW")
    if not krx_id or not krx_pw:
        print("오류: KRX_ID 또는 KRX_PW 환경변수가 설정되지 않았습니다.", file=sys.stderr)
        sys.exit(1)

    with open(args.manifest, encoding="utf-8") as f:
        manifest = json.load(f)

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

        print("로그인 시도 중...")
        if not login(page, krx_id, krx_pw):
            print("오류: 로그인에 실패했습니다.", file=sys.stderr)
            sys.exit(1)
        print("로그인 성공.")

        overall_ok = True
        for entry in manifest:
            output_path = Path(entry["output"])
            ok = process_company(
                page, entry["company"], entry["ticker"],
                entry["from_date"], entry["to_date"], output_path,
            )
            if not ok:
                overall_ok = False

        browser.close()

    if not overall_ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
