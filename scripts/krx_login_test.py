#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2단계: KRX Data Marketplace에 실제로 로그인을 시도하고 성공 여부를 확인한다.

자격증명은 절대 코드/로그에 남기지 않는다. 반드시 환경변수로만 받는다:
    KRX_ID
    KRX_PW

사용법:
    python3 krx_login_test.py
출력:
    /tmp/krx_after_login.png (로그인 시도 후 화면 스크린샷)
    표준출력에 성공/실패 판정
"""
import os
import sys

from playwright.sync_api import sync_playwright

LOGIN_URL = "https://data.krx.co.kr/contents/MDC/COMS/client/MDCCOMS001.cmd"


def main():
    krx_id = os.environ.get("KRX_ID")
    krx_pw = os.environ.get("KRX_PW")
    if not krx_id or not krx_pw:
        print("오류: KRX_ID 또는 KRX_PW 환경변수가 설정되지 않았습니다.", file=sys.stderr)
        sys.exit(1)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1400, "height": 1000},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()

        print(f"이동: {LOGIN_URL}")
        page.goto(LOGIN_URL, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(1500)

        # 로그인 폼은 COMS001_FRAME 안에 있다 (1단계 조사 결과)
        login_frame = None
        for frame in page.frames:
            if frame.name == "COMS001_FRAME":
                login_frame = frame
                break
        if login_frame is None:
            print("오류: 로그인 폼이 있는 프레임(COMS001_FRAME)을 찾지 못했습니다.", file=sys.stderr)
            page.screenshot(path="/tmp/krx_after_login.png", full_page=True)
            sys.exit(1)

        print("로그인 폼 프레임 발견, 아이디/비밀번호 입력 중... (값은 로그에 남기지 않음)")
        login_frame.locator("input[name='mbrId']").fill(krx_id)
        login_frame.locator("input[name='pw']").fill(krx_pw)

        login_frame.get_by_role("link", name="로그인", exact=True).click()
        page.wait_for_timeout(3000)  # 로그인 처리 및 리다이렉트 대기

        page.screenshot(path="/tmp/krx_after_login.png", full_page=True)
        print("로그인 시도 후 스크린샷 저장: /tmp/krx_after_login.png")
        print("현재 URL:", page.url)
        print("현재 페이지 제목:", page.title())

        # 성공 판정: 로그인 페이지에서 벗어났는지, 또는 '로그아웃' 텍스트가 보이는지로 추정
        page_text = page.inner_text("body")
        if "로그아웃" in page_text or "logout" in page_text.lower():
            print("판정: 로그인 성공으로 보입니다 ('로그아웃' 표시 확인).")
        elif "MDCCOMS001" in page.url:
            print("판정: 여전히 로그인 페이지입니다 - 로그인 실패 가능성이 높습니다.")
        else:
            print("판정: 로그인 페이지를 벗어났습니다 - 성공 가능성이 있습니다. 스크린샷으로 확인 필요.")

        browser.close()


if __name__ == "__main__":
    main()
