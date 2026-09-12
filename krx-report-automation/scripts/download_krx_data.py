#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
KRX 일별 종가·거래량 자동 다운로드 (로그인 불필요)

pykrx의 get_market_ohlcv_by_date(adjusted=False)를 사용해
KRX가 발표한 "수정 없이 그대로"의 종가를 가져온다 (기준주가 문서 2장 원칙과 일치).

사용법:
    python3 download_krx_data.py --company "삼성전자" --ticker 005930 \
        --from 20250801 --to 20260910 \
        --output /path/to/삼성전자_원자료.csv
"""
import argparse
import sys

from pykrx import stock


def main():
    ap = argparse.ArgumentParser(description="KRX 일별 시세 다운로드")
    ap.add_argument("--company", required=True, help="회사명 (파일명 참고용)")
    ap.add_argument("--ticker", required=True, help="6자리 종목코드 (예: 005930)")
    ap.add_argument("--from", dest="fromdate", required=True, help="시작일 YYYYMMDD")
    ap.add_argument("--to", dest="todate", required=True, help="종료일 YYYYMMDD")
    ap.add_argument("--output", required=True, help="저장할 CSV 경로")
    ap.add_argument(
        "--source",
        choices=["krx", "naver"],
        default="krx",
        help="krx: KRX 직접 조회(수정 없는 원 종가, 기본값). "
        "naver: 네이버금융 경유(수정주가) - 사내망에서 KRX 직접 조회가 막혀있을 때 대안",
    )
    args = ap.parse_args()

    # adjusted=False: 액면분할/배당 등으로 소급 조정하지 않은 KRX 원 종가 사용
    # (기준주가 문서 2장: "KRX가 제공하는 종가는 별도의 수정 없이 그대로 사용")
    # --source naver 는 adjusted=True로 네이버금융 경유 조회 (사내망 우회용 대안).
    # 최근 구간에는 배당락 등으로 아주 미세한 차이만 있을 수 있음 - 액면분할이 있었다면 차이가 커짐.
    adjusted = args.source == "naver"
    try:
        df = stock.get_market_ohlcv_by_date(
            args.fromdate, args.todate, args.ticker, adjusted=adjusted
        )
    except Exception as e:
        print(f"오류: KRX/네이버 데이터 조회 실패 - {e}", file=sys.stderr)
        sys.exit(1)

    if df.empty:
        print("오류: 조회된 데이터가 없습니다. 종목코드/기간을 확인하세요.", file=sys.stderr)
        sys.exit(1)

    out = df.reset_index()[["날짜", "종가", "거래량"]]
    out.to_csv(args.output, index=False, encoding="utf-8-sig")
    print(f"{args.company}({args.ticker}) {len(out)}일치 데이터 저장 완료: {args.output}")
    print(out.tail(3).to_string(index=False))


if __name__ == "__main__":
    main()
