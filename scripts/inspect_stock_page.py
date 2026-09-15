#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
3단계: 로그인 후 '개별종목 종합정보' 화면으로 이동해서
검색창/버튼 구조와 '일자별 시세' 표의 실제 HTML을 확인한다.

자격증명은 환경변수로만 받는다: KRX_ID, KRX_PW

사용법:
    python3 inspect_stock_page.py
출력:
    /tmp/krx_stock_page_step1.png, /tmp/krx_stock_page_step2.png
    표준출력에 input 목록과 본문 텍스트 일부
"""
import os
import sys

from playwright.sync_api import sync_playwright

LOGIN_URL = "https://data.krx.co.kr/contents/MDC/COMS/client/MDCCOMS001.cmd"
TARGET_TICKER = "005930"
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
                popup_frame.get_by_text("확인", exact=True).click()
            except Exception as e:
                print(f"[시도 {attempt + 1}] 팝업 클릭 실패: {e}")
            page.wait_for_timeout(1500)
            continue

        if check_success(page):
            print(f"[시도 {attempt + 1}] 로그인 성공 확인 ('로그아웃' 문구 발견)")
            return

        login_frame = find_login_frame(page)
        if login_frame is None:
            print(f"[시도 {attempt + 1}] 로그인 프레임 없음 - 대기")
            page.wait_for_timeout(1500)
            continue

        try:
            login_frame.locator("input[name='mbrId']").fill(krx_id)
            login_frame.locator("input[name='pw']").fill(krx_pw)
            login_frame.get_by_role("link", name="로그인", exact=True).click(timeout=5000)
            print(f"[시도 {attempt + 1}] 로그인 버튼 클릭 완료, 결과 대기 중...")
        except Exception as e:
            print(f"[시도 {attempt + 1}] 클릭 실패: {type(e).__name__}")
            page.wait_for_timeout(1000)
            continue

        # 클릭 직후 최대 8초간 폴링하며 성공/팝업 여부 확인
        popped_up = False
        for _ in range(16):
            page.wait_for_timeout(500)
            if check_success(page):
                print(f"[시도 {attempt + 1}] 로그인 성공 확인 ('로그아웃' 문구 발견)")
                return
            if check_popup(page):
                print(f"[시도 {attempt + 1}] 클릭 직후 팝업 발견 - 다음 루프에서 처리")
                popped_up = True
                break
        if not popped_up:
            print(f"[시도 {attempt + 1}] 8초 내 로그인 성공/팝업 모두 미확인")

    print("경고: 여러 번 시도했지만 로그인 성공을 스크립트로 확인하지 못했습니다.")


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
        print("로그인 후 현재 URL:", page.url)

        if not check_success(page):
            print("경고: 로그인이 완료되지 않은 것으로 보입니다. 스크린샷만 남기고 중단합니다.")
            page.screenshot(path="/tmp/krx_stock_page_step1.png", full_page=True)
            browser.close()
            return

        print("\n좌측 메뉴에서 '주식' -> '종목정보' -> '개별종목 종합정보' 클릭 시도...")
        try:
            page.get_by_text("주식", exact=True).first.click()
            page.wait_for_timeout(800)
            page.get_by_text("종목정보", exact=True).first.click()
            page.wait_for_timeout(800)
            page.get_by_text("개별종목 종합정보", exact=True).first.click()
            page.wait_for_timeout(2000)
        except Exception as e:
            print(f"메뉴 클릭 중 오류: {e}", file=sys.stderr)

        print("메뉴 클릭 후 현재 URL:", page.url)
        page.screenshot(path="/tmp/krx_stock_page_step1.png", full_page=True)

        print("\n=== 현재 페이지(및 모든 frame)의 input 요소 ===")
        for fi, frame in enumerate(page.frames):
            print(f"\n[frame {fi}] name={frame.name!r} url={frame.url}")
            try:
                for i, el in enumerate(frame.locator("input").all()):
                    try:
                        print(
                            f"  input[{i}] type={el.get_attribute('type')} "
                            f"name={el.get_attribute('name')} id={el.get_attribute('id')} "
                            f"placeholder={el.get_attribute('placeholder')}"
                        )
                    except Exception as e:
                        print(f"  input[{i}] 읽기 실패: {e}")
            except Exception as e:
                print(f"  프레임 조회 실패: {e}")

        search_input = None
        target_frame = None
        for frame in page.frames:
            try:
                candidates = frame.locator("input[type='text'], input[type='search']").all()
                for el in candidates:
                    ph = (el.get_attribute("placeholder") or "")
                    if "종목" in ph or "검색" in ph or ph == "":
                        search_input = el
                        target_frame = frame
                        break
                if search_input:
                    break
            except Exception:
                continue

        if search_input is None:
            print("\n종목명 검색창을 자동으로 찾지 못했습니다. 위 input 목록을 보고 알려주세요.")
            browser.close()
            return

        print(f"\n검색창으로 추정되는 입력창 발견 (frame url={target_frame.url}), '{TARGET_NAME}' 입력 시도...")
        search_input.click()
        search_input.fill(TARGET_NAME)
        page.wait_for_timeout(1500)
        page.screenshot(path="/tmp/krx_stock_page_step2.png", full_page=True)

        print("\n=== 검색어 입력 후 보이는 텍스트 일부 (자동완성 목록 확인용) ===")
        try:
            body_text = target_frame.inner_text("body")
            idx = body_text.find(TARGET_NAME)
            print(body_text[max(0, idx - 100): idx + 300] if idx >= 0 else "(검색어를 본문에서 못 찾음)")
        except Exception as e:
            print("본문 텍스트 읽기 실패:", e)

        browser.close()


if __name__ == "__main__":
    main()
