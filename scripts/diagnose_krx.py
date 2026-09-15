#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pykrx가 실제로 보내는 것과 동일한 요청을 그대로 재현해서,
정확히 어느 지점에서 실패하는지 눈으로 확인하는 진단 스크립트.

KRX는 단일 엔드포인트(getJsonData.cmd)에 bld + 조회 파라미터를 POST하면
JSON을 돌려주는 구조다 (별도 OTP 단계 없음).

두 가지를 비교한다:
  A) pykrx가 실제로 쓰는 것과 동일한(아주 단순한) 헤더
  B) 실제 브라우저에 가까운 완전한 헤더
회사 네트워크 보안장비가 헤더 패턴으로 자동화 도구를 걸러내는 경우,
A는 막히고 B는 통과하는 경우가 흔하다.

사용법:
    python3 diagnose_krx.py
"""
import requests

URL = "https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd"

PARAMS = {
    "bld": "dbms/MDC/STAT/standard/MDCSTAT01701",
    "isuCd": "KR7005930003",  # 삼성전자 보통주 ISIN
    "strtDd": "20260801",
    "endDd": "20260910",
    "adjStkPrc": "1",  # 1: 단순종가(수정 없음), 2: 수정종가
}

HEADERS_PYKRX = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://data.krx.co.kr/contents/MDC/MDI/outerLoader/index.cmd",
    "X-Requested-With": "XMLHttpRequest",
}

HEADERS_BROWSER = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://data.krx.co.kr/contents/MDC/MDI/mdiLoader/index.cmd?menuId=MDC0201020101",
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Origin": "https://data.krx.co.kr",
}


def try_request(label, headers):
    print(f"\n=== {label} ===")
    try:
        resp = requests.post(URL, data=PARAMS, headers=headers, timeout=15)
    except Exception as e:
        print("요청 자체가 실패했습니다 (연결 문제):", e)
        return
    print("상태 코드:", resp.status_code)
    content_type = resp.headers.get("Content-Type", "")
    print("Content-Type:", content_type)
    print("응답 앞부분(최대 400자):")
    print(resp.text[:400] if resp.text else "(빈 응답)")


def main():
    try_request("A) pykrx와 동일한 단순 헤더", HEADERS_PYKRX)
    try_request("B) 완전한 브라우저형 헤더", HEADERS_BROWSER)


if __name__ == "__main__":
    main()
