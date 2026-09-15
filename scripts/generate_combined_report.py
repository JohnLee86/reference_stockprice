#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
여러 회사의 계산 결과(누적 xlsx)를 하나의 docx 문서로 묶어서 생성한다.
회사별로 표 + 그래프 섹션이 이어지며, 회사 사이에 페이지를 나눈다.

사용법:
    python3 generate_combined_report.py \
        --input "삼성전자:data/삼성전자_일별_기준주가.xlsx" \
                "삼성전기:data/삼성전기_일별_기준주가.xlsx" \
        --output data/삼성그룹_통합_보고서.docx
"""
import argparse
from datetime import datetime, timedelta, timezone

import pandas as pd
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Mm, Pt

from generate_report import BASELINE_DATE, build_chart, fmt_pct, fmt_won

KST = timezone(timedelta(hours=9))


def add_company_section(doc: Document, company: str, xlsx_path: str, chart_path: str):
    df = pd.read_excel(xlsx_path, sheet_name="계산용데이터")
    df["날짜"] = pd.to_datetime(df["날짜"])
    df = df.sort_values("날짜").reset_index(drop=True)

    latest = df.dropna(subset=["기준주가"]).iloc[-1]
    calc_date = latest["날짜"]

    one_month_start = (
        calc_date.replace(day=1)
        if calc_date.day == calc_date.days_in_month
        else calc_date - pd.DateOffset(months=1) + pd.Timedelta(days=1)
    )
    recent = df[(df["날짜"] >= one_month_start) & (df["날짜"] <= calc_date)]
    baseline_row = df[df["날짜"] == BASELINE_DATE]
    table_df = pd.concat([baseline_row, recent]).drop_duplicates(subset="날짜").sort_values("날짜")

    heading = doc.add_heading(f"{company} 일별 기준주가", level=2)
    sub = doc.add_paragraph()
    sub.add_run(f"산정기준일: {calc_date.strftime('%Y-%m-%d')}").font.size = Pt(9)

    headers = ["날짜", "종가", "2개월 VWAP", "1개월 VWAP", "1주일 VWAP", "기준주가", "10/14일 대비"]
    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Light Grid Accent 1"
    for i, h in enumerate(headers):
        cell = table.rows[0].cells[i]
        cell.text = h
        cell.paragraphs[0].runs[0].font.size = Pt(8)
        cell.paragraphs[0].runs[0].font.bold = True

    for _, row in table_df.iterrows():
        cells = table.add_row().cells
        values = [
            row["날짜"].strftime("%Y-%m-%d"),
            fmt_won(row["종가"]),
            fmt_won(row["2개월VWAP"]),
            fmt_won(row["1개월VWAP"]),
            fmt_won(row["5영업일VWAP"]),
            fmt_won(row["기준주가"]),
            fmt_pct(row["10/14일_대비_증가율"]),
        ]
        for i, v in enumerate(values):
            cells[i].text = str(v)
            cells[i].paragraphs[0].runs[0].font.size = Pt(8)

    chart_ok = build_chart(df, chart_path)
    if chart_ok:
        doc.add_paragraph()
        doc.add_picture(chart_path, width=Mm(160))


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

    doc = Document()
    section = doc.sections[0]
    section.page_width = Mm(210)
    section.page_height = Mm(297)
    section.top_margin = Mm(15)
    section.bottom_margin = Mm(15)
    section.left_margin = Mm(18)
    section.right_margin = Mm(18)

    title = doc.add_heading("삼성그룹 상장사 일별 기준주가 통합 보고서", level=1)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    now_kst = datetime.now(tz=KST)
    sub = doc.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sub.add_run(f"생성시각(KST): {now_kst.strftime('%Y-%m-%d %H:%M')}").font.size = Pt(9)

    failed = []
    for i, item in enumerate(args.input):
        company, xlsx_path = item.split(":", 1)
        doc.add_page_break()
        try:
            add_company_section(doc, company, xlsx_path, f"/tmp/chart_{i}.png")
        except Exception as e:
            failed.append(company)
            doc.add_paragraph(f"[{company}] 데이터 처리 실패: {e}")

    doc.save(args.output)
    print(f"통합 보고서 생성 완료: {args.output} (총 {len(args.input)}개 회사)")
    if failed:
        print(f"처리 실패한 회사: {failed}")


if __name__ == "__main__":
    main()
