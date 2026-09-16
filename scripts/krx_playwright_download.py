#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
KRX Data Marketplace에 실제 계정으로 로그인한 뒤(1회), 여러 회사를 순회하며
'개별종목 종합정보' 화면에서 일자별 종가와 "정규시장" 거래량을 추출한다.

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
    print(f"\n--- [{company}] 처리 시작 ---")
    try:
        page.goto(STOCK_PAGE_URL, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(2000)
    except Exception as e:
        print(f"[{company}] 페이지 이동 실패: {e}")
        return False

    search_input = None
    target_frame = None
    for frame in page.frames:
        try:
            el = frame.locator("input[name='tboxisuCd_finder_stkisu0_0']")
            if el.count() > 0:
                search_input = el.first
                target_frame = frame
                break
        except Exception:
            continue

    if search_input is None:
        print(f"[{company}] 종목검색기 입력창을 찾지 못했습니다.")
        return False

    search_input.click()
    search_input.fill("")
    page.wait_for_timeout(300)
    try:
        search_input.press_sequentially(company, delay=120)
    except Exception:
        search_input.fill(company)
    page.wait_for_timeout(2000)

    # 자동완성 드롭다운에서 회사명과 정확히 일치하는 항목을 클릭 (여러 태그 유형 대응)
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
    page.wait_for_timeout(1000)

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

    page.wait_for_timeout(1500)

    # 조회 결과가 실제로 원하는 종목코드인지 검증 (틀리면 저장하지 않고 실패 처리)
    ticker_confirmed = False
    for frame in page.frames:
        try:
            if f"({ticker})" in frame.inner_text("body"):
                ticker_confirmed = True
                break
        except Exception:
            continue
    if not ticker_confirmed:
        print(f"[{company}] 검색/선택 실패로 보입니다 - 화면에서 종목코드({ticker})를 확인하지 못했습니다. 건너뜁니다.")
        return False

    # 'Open' 버튼을 반복 클릭해 과거 데이터를 추가로 불러온다 (필요한 from_date까지, 또는 더 이상
    # 새 행이 늘어나지 않을 때까지, 최대 40회 시도)
    from_dt_check = datetime.strptime(from_date, "%Y%m%d")

    def current_min_date():
        earliest = None
        for frame in page.frames:
            try:
                rows = frame.locator("tr").all()
            except Exception:
                continue
            for row in rows:
                try:
                    tds = row.locator("td").all_inner_texts()
                except Exception:
                    continue
                if len(tds) < 4:
                    continue
                d = tds[0].strip()
                if not re.match(r"^\d{4}/\d{2}/\d{2}$", d):
                    continue
                if parse_number(tds[1]) is None:  # 종가로 보이는 값이 없으면 시세 행이 아님 (예: 설립일 등)
                    continue
                dt = datetime.strptime(d, "%Y/%m/%d")
                if earliest is None or dt < earliest:
                    earliest = dt
        return earliest

    for _ in range(40):
        earliest = current_min_date()
        if earliest is not None and earliest <= from_dt_check:
            break
        opened = False
        for frame in page.frames:
            try:
                open_btn = frame.locator(":text-is('Open')")
                if open_btn.count() > 0:
                    open_btn.first.click()
                    opened = True
                    break
            except Exception:
                continue
        if not opened:
            break
        page.wait_for_timeout(800)
    print(f"[{company}] 과거 데이터 확보 후 가장 이른 날짜: {current_min_date()}")

    # '거래량' 헤더 클릭 -> 정규시장/애프터마켓 세부 컬럼 펼치기
    for frame in page.frames:
        try:
            header_cell = frame.locator(":text-is('거래량')").first
            if header_cell.count() if hasattr(header_cell, "count") else 0:
                header_cell.click()
                break
        except Exception:
            continue
    page.wait_for_timeout(1500)

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
            viewport={"width": 1600, "height": 1100},
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
