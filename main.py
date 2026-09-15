#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
전체 파이프라인 실행: 다운로드 -> 계산 -> 보고서 생성 -> 이메일 발송

대상 회사/종목은 config.json에서 읽는다. 여러 회사를 등록하면 순서대로 전부 처리한다.
휴장일 등으로 신규 데이터가 없으면(오늘 날짜 데이터가 없으면) 해당 회사는 건너뛰고
이메일을 보내지 않는다 (빈 보고서 스팸 방지).

데이터 출처는 KRX 직접 조회만 사용한다 (네이버 등 대체 출처는 쓰지 않음 - 당일 거래량이
KRX보다 늦게 갱신되는 문제가 있어서 정확성을 우선). KRX 조회가 실패하면 그날은
보고서/이메일을 건너뛰고 실패로 표시한다.
"""
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
SCRIPTS = ROOT / "scripts"


def run(cmd: list[str]):
    print("실행:", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)
    print(result.stdout)
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
    return result.returncode == 0


def process_company(company: str, ticker: str, today: str) -> bool:
    """성공하면 True, 실패(진짜 오류)하면 False. 휴장일 등 정상적인 건너뜀도 True로 취급."""
    DATA_DIR.mkdir(exist_ok=True)
    existing_xlsx = DATA_DIR / f"{company}_일별_기준주가.xlsx"
    raw_csv = DATA_DIR / f"{company}_원자료_임시.csv"
    report_path = DATA_DIR / f"{company}_일별_기준주가_보고서.docx"

    # 기존 파일이 있으면 마지막 날짜 다음날부터, 없으면 2025-08-01부터 (2025-10-14 기준값 계산에 필요)
    from_date = "20250801"
    if existing_xlsx.exists():
        prev = pd.read_excel(existing_xlsx, sheet_name="계산용데이터")
        last_date = pd.to_datetime(prev["날짜"]).max()
        from_date = (last_date + timedelta(days=1)).strftime("%Y%m%d")

    if from_date > today.replace("-", ""):
        print(f"[{company}] 이미 최신 데이터 보유 중 - 신규 다운로드 생략.")
    else:
        ok = run([
            "python3", str(SCRIPTS / "download_krx_data.py"),
            "--company", company, "--ticker", ticker,
            "--from", from_date, "--to", today.replace("-", ""),
            "--output", str(raw_csv),
        ])
        if not ok:
            print(f"[{company}] KRX 직접 조회 실패 - 대체 데이터는 쓰지 않고 오늘은 실패 처리합니다.")
            return False

    if raw_csv.exists():
        calc_cmd = ["python3", str(SCRIPTS / "calculate_reference_price.py"),
                    "--company", company, "--new-data", str(raw_csv),
                    "--output", str(existing_xlsx)]
        if existing_xlsx.exists():
            calc_cmd += ["--existing", str(existing_xlsx)]
        if not run(calc_cmd):
            print(f"[{company}] 계산 실패.")
            return False

    # 오늘자 데이터가 실제로 있는지 확인 (휴장일이면 신규 행이 없을 수 있음)
    updated = pd.read_excel(existing_xlsx, sheet_name="계산용데이터")
    latest_date = pd.to_datetime(updated["날짜"]).max()
    if latest_date.strftime("%Y-%m-%d") != today:
        print(f"[{company}] 오늘({today}) 신규 데이터 없음 (휴장일 등) - 이메일 건너뜀.")
        return True

    if not run(["python3", str(SCRIPTS / "generate_report.py"),
                "--company", company, "--input", str(existing_xlsx),
                "--output", str(report_path)]):
        print(f"[{company}] 보고서 생성 실패.")
        return False

    if not run(["python3", str(SCRIPTS / "send_email.py"),
                "--company", company, "--attachment", str(report_path)]):
        print(f"[{company}] 이메일 발송 실패.")
        return False

    return True


def main():
    with open(ROOT / "config.json", encoding="utf-8") as f:
        config = json.load(f)

    today = datetime.now(tz=KST).strftime("%Y-%m-%d")
    all_ok = True
    for entry in config["companies"]:
        if not process_company(entry["company"], entry["ticker"], today):
            all_ok = False

    if not all_ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
