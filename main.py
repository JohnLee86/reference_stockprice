#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
전체 파이프라인 실행: (회사별) 다운로드 -> 계산  ->  (1) 삼성전자 단독 보고서+메일
                                                  (2) 전체 회사 통합 보고서+메일

대상 회사/종목은 config.json에서 읽는다. "individual_email": true 로 표시된 회사는
별도로 단독 보고서 메일도 받는다 (현재는 삼성전자만 해당).

데이터 출처는 KRX 직접 조회만 사용한다 (네이버 등 대체 출처는 쓰지 않음 - 당일 거래량이
KRX보다 늦게 갱신되는 문제가 있어서 정확성을 우선). KRX 조회가 실패하면 그날은
해당 회사를 건너뛰고 실패로 표시한다.
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


def run(cmd: list[str]) -> bool:
    print("실행:", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)
    print(result.stdout)
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
    return result.returncode == 0


def update_company_data(company: str, ticker: str, today: str) -> tuple[bool, bool]:
    """(성공 여부, 오늘자 신규 데이터 있음 여부)를 반환. 다운로드/계산만 수행."""
    DATA_DIR.mkdir(exist_ok=True)
    existing_xlsx = DATA_DIR / f"{company}_일별_기준주가.xlsx"
    raw_csv = DATA_DIR / f"{company}_원자료_임시.csv"

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
            return False, False

    if raw_csv.exists():
        calc_cmd = ["python3", str(SCRIPTS / "calculate_reference_price.py"),
                    "--company", company, "--new-data", str(raw_csv),
                    "--output", str(existing_xlsx)]
        if existing_xlsx.exists():
            calc_cmd += ["--existing", str(existing_xlsx)]
        if not run(calc_cmd):
            print(f"[{company}] 계산 실패.")
            return False, False

    if not existing_xlsx.exists():
        print(f"[{company}] 누적 데이터 파일이 없습니다.")
        return False, False

    updated = pd.read_excel(existing_xlsx, sheet_name="계산용데이터")
    latest_date = pd.to_datetime(updated["날짜"]).max()
    has_today = latest_date.strftime("%Y-%m-%d") == today

    return True, has_today


def send_individual_report(company: str) -> bool:
    existing_xlsx = DATA_DIR / f"{company}_일별_기준주가.xlsx"
    report_path = DATA_DIR / f"{company}_일별_기준주가_보고서.docx"

    if not run(["python3", str(SCRIPTS / "generate_report.py"),
                "--company", company, "--input", str(existing_xlsx),
                "--output", str(report_path)]):
        print(f"[{company}] 개별 보고서 생성 실패.")
        return False

    if not run(["python3", str(SCRIPTS / "send_email.py"),
                "--company", company, "--attachment", str(report_path)]):
        print(f"[{company}] 개별 이메일 발송 실패.")
        return False
    return True


def send_combined_report(companies: list[str]) -> bool:
    combined_path = DATA_DIR / "삼성그룹_통합_보고서.docx"
    input_args = []
    for company in companies:
        xlsx_path = DATA_DIR / f"{company}_일별_기준주가.xlsx"
        if xlsx_path.exists():
            input_args.append(f"{company}:{xlsx_path}")

    if not input_args:
        print("통합 보고서: 사용할 수 있는 회사 데이터가 없습니다.")
        return False

    if not run(["python3", str(SCRIPTS / "generate_combined_report.py"),
                "--input", *input_args, "--output", str(combined_path)]):
        print("통합 보고서 생성 실패.")
        return False

    if not run(["python3", str(SCRIPTS / "send_email.py"),
                "--company", "삼성그룹 전체", "--attachment", str(combined_path)]):
        print("통합 보고서 이메일 발송 실패.")
        return False
    return True


def main():
    with open(ROOT / "config.json", encoding="utf-8") as f:
        config = json.load(f)

    today = datetime.now(tz=KST).strftime("%Y-%m-%d")
    all_ok = True
    ready_companies = []  # 오늘자 데이터가 확보된 회사만 보고서 대상
    individual_targets = []

    for entry in config["companies"]:
        company, ticker = entry["company"], entry["ticker"]
        ok, has_today = update_company_data(company, ticker, today)
        if not ok:
            all_ok = False
            continue
        if has_today:
            ready_companies.append(company)
            if entry.get("individual_email"):
                individual_targets.append(company)
        else:
            print(f"[{company}] 오늘({today}) 신규 데이터 없음 (휴장일 등) - 보고서 대상에서 제외.")

    for company in individual_targets:
        if not send_individual_report(company):
            all_ok = False

    if ready_companies:
        if not send_combined_report(ready_companies):
            all_ok = False
    else:
        print("오늘 보고서를 발송할 회사가 없습니다 (전체 휴장일 등).")

    if not all_ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
