#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
전체 파이프라인 실행: (회사별) 다운로드 -> 계산  ->  (1) 삼성전자 단독 보고서+메일
                                                  (2) 전체 회사 통합 보고서+메일

대상 회사/종목은 config.json에서 읽는다. "individual_email": true 로 표시된 회사는
별도로 단독 보고서 메일도 받는다 (현재는 삼성전자만 해당). "baseline_date"를 지정한
회사는 상승률 산정 기준일을 그 날짜로 사용한다 (예: 상장일이 늦은 회사, 기본값 2025-10-14).

데이터 수집은 KRX Data Marketplace에 실제 계정으로 로그인하는 Playwright 스크립트
(krx_playwright_download.py)를 통해 이루어진다. 로그인은 1회만 하고, 그 세션으로
등록된 모든 회사를 순회하며 "정규시장" 거래량을 가져온다 (애프터마켓 거래량 제외).
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


def build_manifest(companies: list[dict], today: str) -> list[dict]:
    DATA_DIR.mkdir(exist_ok=True)
    manifest = []
    for entry in companies:
        company, ticker = entry["company"], entry["ticker"]
        existing_xlsx = DATA_DIR / f"{company}_일별_기준주가.xlsx"
        # 기준주가는 2025-10-14부터 필요하고, 2개월 VWAP 산정을 위해 그보다 앞선
        # 데이터가 필요하므로(최소 2025-08-15부터) 여유를 두어 2025-01-01부터 수집한다.
        from_date = "20250101"
        if existing_xlsx.exists():
            prev = pd.read_excel(existing_xlsx, sheet_name="계산용데이터")
            last_date = pd.to_datetime(prev["날짜"]).max()
            from_date = (last_date + timedelta(days=1)).strftime("%Y%m%d")

        today_compact = today.replace("-", "")
        if from_date > today_compact:
            print(f"[{company}] 이미 최신 데이터 보유 중 - 다운로드 목록에서 제외.")
            continue

        manifest.append({
            "company": company,
            "ticker": ticker,
            "from_date": from_date,
            "to_date": today_compact,
            "output": str(DATA_DIR / f"{company}_원자료_임시.csv"),
        })
    return manifest


def update_company_data(company: str, baseline_date: str) -> tuple[bool, bool]:
    """(성공 여부, 오늘자 신규 데이터 있음 여부). 다운로드는 이미 완료된 상태로 가정하고 계산만 수행."""
    existing_xlsx = DATA_DIR / f"{company}_일별_기준주가.xlsx"
    raw_csv = DATA_DIR / f"{company}_원자료_임시.csv"

    if raw_csv.exists():
        calc_cmd = ["python3", str(SCRIPTS / "calculate_reference_price.py"),
                    "--company", company, "--new-data", str(raw_csv),
                    "--output", str(existing_xlsx), "--baseline-date", baseline_date]
        if existing_xlsx.exists():
            calc_cmd += ["--existing", str(existing_xlsx)]
        if not run(calc_cmd):
            print(f"[{company}] 계산 실패.")
            return False, False

    if not existing_xlsx.exists():
        print(f"[{company}] 누적 데이터 파일이 없습니다 (다운로드 실패 가능성).")
        return False, False

    today = datetime.now(tz=KST).strftime("%Y-%m-%d")
    updated = pd.read_excel(existing_xlsx, sheet_name="계산용데이터")
    latest_date = pd.to_datetime(updated["날짜"]).max()
    has_today = latest_date.strftime("%Y-%m-%d") == today
    return True, has_today


def send_individual_report(company: str, baseline_date: str) -> bool:
    existing_xlsx = DATA_DIR / f"{company}_일별_기준주가.xlsx"
    report_path = DATA_DIR / f"{company}_일별_기준주가_보고서.pdf"

    if not run(["python3", str(SCRIPTS / "generate_report.py"),
                "--company", company, "--input", str(existing_xlsx),
                "--output", str(report_path), "--baseline-date", baseline_date]):
        print(f"[{company}] 개별 보고서 생성 실패.")
        return False

    if not run(["python3", str(SCRIPTS / "send_email.py"),
                "--company", company, "--attachment", str(report_path)]):
        print(f"[{company}] 개별 이메일 발송 실패.")
        return False
    return True


def send_combined_report(companies: list[tuple[str, str]]) -> bool:
    combined_path = DATA_DIR / "삼성그룹_통합_보고서.pdf"
    input_args = []
    for company, baseline_date in companies:
        xlsx_path = DATA_DIR / f"{company}_일별_기준주가.xlsx"
        if xlsx_path.exists():
            input_args.append(f"{company}:{xlsx_path}:{baseline_date}")

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

    manifest = build_manifest(config["companies"], today)
    if manifest:
        manifest_path = DATA_DIR / "download_manifest.json"
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)

        if not run(["python3", str(SCRIPTS / "krx_playwright_download.py"),
                    "--manifest", str(manifest_path)]):
            print("경고: 일부 또는 전체 회사의 KRX 다운로드가 실패했습니다.")
            all_ok = False

    ready_companies = []
    individual_targets = []
    for entry in config["companies"]:
        company = entry["company"]
        baseline_date = entry.get("baseline_date", "2025-10-14")
        ok, has_today = update_company_data(company, baseline_date)
        if not ok:
            all_ok = False
            continue
        if has_today:
            ready_companies.append((company, baseline_date))
            if entry.get("individual_email"):
                individual_targets.append((company, baseline_date))
        else:
            print(f"[{company}] 오늘({today}) 신규 데이터 없음 (휴장일 등) - 보고서 대상에서 제외.")

    for company, baseline_date in individual_targets:
        if not send_individual_report(company, baseline_date):
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
