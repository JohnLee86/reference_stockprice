#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
3단계: 로그인 후 '개별종목 종합정보' 화면(직접 URL)으로 이동해서
검색창/버튼 구조와 '일자별 시세' 표의 실제 내용을 확인한다.

자격증명은 환경변수로만 받는다: KRX_ID, KRX_PW
"""
import os
import sys

from playwright.sync_api import sync_playwright

LOGIN_URL = "https://data.krx.co.kr/contents/MDC/COMS/client/MDCCOMS001.cmd"
STOCK_PAGE_URL = "https://data.krx.co.kr/contents/MDC/MDI/mdiLoader/index.cmd?menuId=MDC0201020203"
TARGET_NAME = "삼성전자"


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


def login(page, krx_id, krx_pw):
    page.goto(LOGIN_URL, wait_until="networkidle", timeout=30000)
    page.wait_for_timeout(1500)

    for attempt in range(5):
        popup_frame = check_popup(page)
        if popup_frame:
            print(f"[시도 {attempt + 1}] 팝업 발견 - '확인' 클릭")
            try:
                popup_frame.get_by_role("button", name="확인", exact=True).click()
            except Exception as e:
                print(f"[시도 {attempt + 1}] 팝업 클릭 실패: {e}")
            page.wait_for_timeout(1500)
            continue

        if check_success(page):
            print(f"[시도 {attempt + 1}] 로그인 성공 확인")
            return

        login_frame = find_login_frame(page)
        if login_frame is None:
            page.wait_for_timeout(1500)
            continue

        try:
            login_frame.locator("input[name='mbrId']").fill(krx_id)
            login_frame.locator("input[name='pw']").fill(krx_pw)
            login_frame.get_by_role("link", name="로그인", exact=True).click(timeout=5000)
        except Exception as e:
            print(f"[시도 {attempt + 1}] 클릭 실패: {type(e).__name__}")
            page.wait_for_timeout(1000)
            continue

        popped_up = False
        for _ in range(16):
            page.wait_for_timeout(500)
            if check_success(page):
                print(f"[시도 {attempt + 1}] 로그인 성공 확인")
                return
            if check_popup(page):
                popped_up = True
                break
        if not popped_up:
            print(f"[시도 {attempt + 1}] 8초 내 결과 미확인")

    print("경고: 로그인 성공을 확인하지 못했습니다.")


def dump_inputs_and_buttons(page):
    for fi, frame in enumerate(page.frames):
        try:
            inputs = frame.locator("input").all()
        except Exception:
            continue
        if not inputs:
            continue
        print(f"\n[frame {fi}] url={frame.url}")
        for i, el in enumerate(inputs):
            try:
                print(
                    f"  input[{i}] type={el.get_attribute('type')} "
                    f"name={el.get_attribute('name')} id={el.get_attribute('id')} "
                    f"placeholder={el.get_attribute('placeholder')}"
                )
            except Exception:
                pass
        try:
            for i, el in enumerate(frame.locator("button").all()):
                try:
                    print(f"  button[{i}] text='{el.inner_text().strip()}' id={el.get_attribute('id')}")
                except Exception:
                    pass
        except Exception:
            pass


def main():
    krx_id = os.environ.get("KRX_ID")
    krx_pw = os.environ.get("KRX_PW")
    if not krx_id or not krx_pw:
        print("오류: KRX_ID 또는 KRX_PW 환경변수가 설정되지 않았습니다.", file=sys.stderr)
        sys.exit(1)

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
        login(page, krx_id, krx_pw)
        if not check_success(page):
            print("경고: 로그인 실패. 중단합니다.")
            page.screenshot(path="/tmp/krx_stock_page_step1.png", full_page=True)
            browser.close()
            return

        print(f"\n개별종목 종합정보 페이지로 직접 이동: {STOCK_PAGE_URL}")
        page.goto(STOCK_PAGE_URL, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(2500)
        page.screenshot(path="/tmp/krx_stock_page_step1.png", full_page=True)
        print("이동 후 현재 URL:", page.url)

        print("\n=== 입력창/버튼 목록 ===")
        dump_inputs_and_buttons(page)

        # 종목명 검색창: KRX 표준 위젯 (name=tboxisuCd_finder_stkisu0_0)
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
            print("\n종목검색기 입력창(tboxisuCd_finder_stkisu0_0)을 찾지 못했습니다.")
            browser.close()
            return

        print(f"\n종목명 입력창 발견 (frame={target_frame.url}) - '{TARGET_NAME}' 입력")
        search_input.click()
        search_input.fill(TARGET_NAME)
        page.wait_for_timeout(2000)
        page.screenshot(path="/tmp/krx_stock_page_step2.png", full_page=True)

        # 자동완성 드롭다운에서 정확히 일치하는 항목 클릭 시도
        suggestion_clicked = False
        try:
            for tag in ["li", "div", "td", "a"]:
                loc = target_frame.locator(f"{tag}:text-is('{TARGET_NAME}')")
                if loc.count() > 0:
                    loc.first.click()
                    suggestion_clicked = True
                    print(f"자동완성 항목 클릭 성공 (tag={tag})")
                    break
        except Exception as e:
            print(f"자동완성 클릭 시도 중 오류: {e}")

        if not suggestion_clicked:
            print("자동완성 항목을 못 찾아 Enter로 대체 시도")
            try:
                search_input.press("Enter")
            except Exception:
                pass

        page.wait_for_timeout(1500)
        page.screenshot(path="/tmp/krx_stock_page_step2b.png", full_page=True)

        # '조회' 텍스트를 가진 아무 태그나 클릭 (버튼이 아닐 수 있음)
        clicked_search_btn = False
        for frame in page.frames:
            try:
                loc = frame.locator(":text-is('조회')")
                if loc.count() > 0:
                    loc.first.click()
                    clicked_search_btn = True
                    print("'조회' 요소 클릭 성공")
                    break
            except Exception:
                continue
        if not clicked_search_btn:
            print("'조회' 텍스트를 가진 요소를 찾지 못했습니다.")

        # 표 데이터 로딩 대기 (최대 15초)
        loaded = False
        for _ in range(30):
            page.wait_for_timeout(500)
            for frame in page.frames:
                try:
                    if frame.locator("table tr").count() > 3:
                        loaded = True
                        break
                except Exception:
                    continue
            if loaded:
                break
        print(f"\n조회 후 데이터 로딩 {'완료' if loaded else '15초 내 미확인'}")

        page.screenshot(path="/tmp/krx_stock_page_step3.png", full_page=True)
        print("최종 URL:", page.url)

        print("\n=== 최종 화면의 table 내용 ===")
        for fi, frame in enumerate(page.frames):
            try:
                tables = frame.locator("table").all()
                if not tables:
                    continue
                print(f"\n[frame {fi}] url={frame.url} - table {len(tables)}개")
                for ti, table in enumerate(tables):
                    try:
                        row_count = table.locator("tr").count()
                        if row_count == 0:
                            continue
                        print(f"  table[{ti}] 행수={row_count}")
                        for ri in range(min(row_count, 4)):
                            print(f"    행[{ri}]: {table.locator('tr').nth(ri).inner_text()[:200]}")
                    except Exception as e:
                        print(f"  table[{ti}] 읽기 실패: {e}")
            except Exception:
                continue

        browser.close()


if __name__ == "__main__":
    main()
