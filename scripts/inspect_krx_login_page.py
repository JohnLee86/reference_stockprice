#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
1단계: KRX Data Marketplace 로그인 페이지의 실제 구조를 확인한다.
아직 로그인은 시도하지 않는다 (아이디/비밀번호 불필요).

화면 스크린샷과, 페이지 안의 모든 input/button 요소의 속성(name, id, type,
placeholder, 보이는 텍스트)을 출력해서, 실제 로그인 폼이 어떻게 생겼는지 파악한다.

사용법:
    python3 inspect_krx_login_page.py
출력:
    /tmp/krx_login_page.png (스크린샷)
    표준출력에 input/button 목록
"""
from playwright.sync_api import sync_playwright

LOGIN_URL = "https://data.krx.co.kr/contents/MDC/COMS/client/MDCCOMS001.cmd"


def main():
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
        page.wait_for_timeout(2000)  # 동적 렌더링 대기

        print("페이지 제목:", page.title())
        print("현재 URL:", page.url)

        page.screenshot(path="/tmp/krx_login_page.png", full_page=True)
        print("스크린샷 저장: /tmp/krx_login_page.png")

        print("\n--- input 요소 목록 (메인 프레임) ---")
        inputs = page.locator("input").all()
        for i, el in enumerate(inputs):
            try:
                print(
                    f"[{i}] type={el.get_attribute('type')} "
                    f"name={el.get_attribute('name')} "
                    f"id={el.get_attribute('id')} "
                    f"placeholder={el.get_attribute('placeholder')}"
                )
            except Exception as e:
                print(f"[{i}] 읽기 실패: {e}")

        print("\n--- button 요소 목록 (메인 프레임) ---")
        buttons = page.locator("button").all()
        for i, el in enumerate(buttons):
            try:
                print(f"[{i}] text='{el.inner_text().strip()}' id={el.get_attribute('id')}")
            except Exception as e:
                print(f"[{i}] 읽기 실패: {e}")

        print("\n--- '로그인' 텍스트를 포함한 링크/버튼 (메인 프레임) ---")
        login_like = page.locator("text=로그인").all()
        for i, el in enumerate(login_like):
            try:
                print(f"[{i}] tag={el.evaluate('e => e.tagName')} text='{el.inner_text().strip()}'")
            except Exception as e:
                print(f"[{i}] 읽기 실패: {e}")

        print("\n=== 페이지 안의 모든 frame(iframe 포함) 목록 ===")
        for fi, frame in enumerate(page.frames):
            print(f"\n[frame {fi}] name={frame.name!r} url={frame.url}")
            try:
                f_inputs = frame.locator("input").all()
                for i, el in enumerate(f_inputs):
                    try:
                        print(
                            f"  input[{i}] type={el.get_attribute('type')} "
                            f"name={el.get_attribute('name')} "
                            f"id={el.get_attribute('id')} "
                            f"placeholder={el.get_attribute('placeholder')}"
                        )
                    except Exception as e:
                        print(f"  input[{i}] 읽기 실패: {e}")
                f_buttons = frame.locator("button").all()
                for i, el in enumerate(f_buttons):
                    try:
                        print(f"  button[{i}] text='{el.inner_text().strip()}' id={el.get_attribute('id')}")
                    except Exception as e:
                        print(f"  button[{i}] 읽기 실패: {e}")
            except Exception as e:
                print(f"  프레임 조회 실패: {e}")

        browser.close()


if __name__ == "__main__":
    main()
