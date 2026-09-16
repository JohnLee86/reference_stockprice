#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
여러 회사의 계산 결과(누적 xlsx)를 하나의 PDF로 묶어서 생성한다.
회사별로 별도 페이지(제목+표+그래프)로 구성된다.

사용법:
    python3 generate_combined_report.py \
        --input "삼성전자:data/삼성전자_일별_기준주가.xlsx" \
                "삼성전기:data/삼성전기_일별_기준주가.xlsx" \
        --output data/삼성그룹_통합_보고서.pdf
"""
import argparse
from datetime import datetime, timedelta, timezone

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.backends.backend_pdf import PdfPages

from generate_report import build_table_rows, render_report_page

KST = timezone(timedelta(hours=9))


def add_company_page(pdf: PdfPages, company: str, xlsx_path: str):
    df = pd.read_excel(xlsx_path, sheet_name="계산용데이터")
    df["날짜"] = pd.to_datetime(df["날짜"])
    df = df.sort_values("날짜").reset_index(drop=True)

    latest = df.dropna(subset=["기준주가"]).iloc[-1]
    calc_date = latest["날짜"]

    table_df, bold_after = build_table_rows(df, calc_date)

    fig = plt.figure(figsize=(210 / 25.4, 297 / 25.4))  # A4 (mm -> inch)
    render_report_page(fig, company, calc_date, table_df, bold_after, df)
    pdf.savefig(fig)
    plt.close(fig)


def add_error_page(pdf: PdfPages, company: str, error: str):
    fig = plt.figure(figsize=(210 / 25.4, 297 / 25.4))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.axis("off")
    ax.text(0.5, 0.5, f"[{company}] 데이터 처리 실패\n{error}", ha="center", va="center", fontsize=11)
    pdf.savefig(fig)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description="삼성그룹 통합 기준주가 보고서 생성")
    ap.add_argument(
        "--input",
        nargs="+",
        required=True,
        help="'회사명:xlsx경로' 형식을 공백으로 구분해서 여러 개 전달",
    )
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    failed = []
    with PdfPages(args.output) as pdf:
        # 표지 페이지
        fig = plt.figure(figsize=(210 / 25.4, 297 / 25.4))
        ax = fig.add_axes([0, 0, 1, 1])
        ax.axis("off")
        now_kst = datetime.now(tz=KST)
        ax.text(0.5, 0.55, "삼성그룹 상장사 일별 기준주가 통합 보고서",
                ha="center", va="center", fontsize=18, fontweight="bold")
        ax.text(0.5, 0.48, f"생성시각(KST): {now_kst.strftime('%Y-%m-%d %H:%M')}",
                ha="center", va="center", fontsize=10)
        pdf.savefig(fig)
        plt.close(fig)

        for item in args.input:
            company, xlsx_path = item.split(":", 1)
            try:
                add_company_page(pdf, company, xlsx_path)
            except Exception as e:
                failed.append(company)
                add_error_page(pdf, company, str(e))

    print(f"통합 보고서 생성 완료: {args.output} (총 {len(args.input)}개 회사)")
    if failed:
        print(f"처리 실패한 회사: {failed}")


if __name__ == "__main__":
    main()
