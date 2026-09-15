#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
계산 결과(누적 xlsx)로부터 A4 1장 기준주가 보고서(.docx)를 생성한다.
표: 2025-10-14 고정 1행 + 최근 1개월 데이터 (최신 날짜가 맨 아래)
그래프: 기준주가 선만 표시, 2025-10-14부터, 시작/최고/최저/마지막 4개 시점 표시

사용법:
    python3 generate_report.py --company "삼성전자" \
        --input 삼성전자_일별_기준주가.xlsx \
        --output 삼성전자_일별_기준주가_보고서.docx
"""
import argparse
from datetime import datetime, timedelta, timezone

import matplotlib
matplotlib.use("Agg")
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
import pandas as pd

# 한글 폰트 등록 (GitHub Actions의 신규 리눅스 러너에는 한글 폰트가 기본 설치되어 있지
# 않으므로, pykrx 패키지에 이미 번들된 나눔바른고딕 폰트를 직접 찾아 등록한다.
try:
    import glob

    _candidates = (
        glob.glob("/usr/share/fonts/**/Nanum*.ttf", recursive=True)
        + glob.glob("/usr/share/fonts/**/NanumGothic*.otf", recursive=True)
        + glob.glob("/usr/share/fonts/**/*CJK*.ttc", recursive=True)
        + glob.glob("/usr/share/fonts/**/*CJK*.otf", recursive=True)
    )
    if _candidates:
        fm.fontManager.addfont(_candidates[0])
        plt.rc("font", family=fm.FontProperties(fname=_candidates[0]).get_name())
except Exception:
    pass  # 폰트 등록에 실패해도 보고서 생성 자체는 계속 진행 (라벨이 깨질 수 있음)
plt.rcParams["axes.unicode_minus"] = False
from docx import Document
from docx.shared import Mm, Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH

KST = timezone(timedelta(hours=9))
BASELINE_DATE = pd.Timestamp("2025-10-14")


def fmt_won(v):
    return "-" if pd.isna(v) else f"{int(round(v)):,}"


def fmt_pct(v):
    return "-" if pd.isna(v) else f"{v * 100:.1f}%"


def build_chart(df: pd.DataFrame, out_path: str):
    plot_df = df[df["날짜"] >= BASELINE_DATE].dropna(subset=["기준주가"]).reset_index(drop=True)
    if plot_df.empty:
        return False

    fig, ax = plt.subplots(figsize=(7.4, 3.0))
    ax.plot(plot_df["날짜"], plot_df["기준주가"], color="#2E6E9E", linewidth=1.6)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(False)

    # 월별 마지막 데이터에 월 표기, 최종 데이터에는 일자까지 표기
    plot_df["ym"] = plot_df["날짜"].dt.to_period("M")
    month_last = plot_df.groupby("ym").tail(1)
    last_idx = plot_df.index[-1]
    tick_pos, tick_labels = [], []
    for idx, row in month_last.iterrows():
        if idx == last_idx:
            continue
        tick_pos.append(row["날짜"])
        tick_labels.append(f"'{row['날짜'].strftime('%y')}.{row['날짜'].month}")
    last_row = plot_df.loc[last_idx]
    # 마지막 라벨과 너무 가까운(15일 이내) 월말 라벨은 겹치므로 제거
    while tick_pos and (last_row["날짜"] - tick_pos[-1]).days < 15:
        tick_pos.pop()
        tick_labels.pop()
    tick_pos.append(last_row["날짜"])
    tick_labels.append(f"'{last_row['날짜'].strftime('%y')}.{last_row['날짜'].month}.{last_row['날짜'].day}일")
    ax.set_xticks(tick_pos)
    ax.set_xticklabels(tick_labels, fontsize=8)

    start_idx = plot_df.index[0]
    max_idx = plot_df["기준주가"].idxmax()
    min_idx = plot_df["기준주가"].idxmin()

    points = {}
    points.setdefault(start_idx, []).append("시작")
    points.setdefault(max_idx, []).append("최고")
    points.setdefault(min_idx, []).append("최저")
    points.setdefault(last_idx, []).append("마지막")

    for idx, labels in points.items():
        row = plot_df.loc[idx]
        label = "/".join(labels) + "시점"
        ax.scatter([row["날짜"]], [row["기준주가"]], color="gray", zorder=5, s=35)
        d = row["날짜"]
        ax.annotate(
            f"{label}\n'{d.strftime('%y')}.{d.month}.{d.day} {int(row['기준주가']):,}원",
            (row["날짜"], row["기준주가"]),
            textcoords="offset points",
            xytext=(0, 10),
            fontsize=7,
            ha="center",
        )

    ax.set_ylabel("기준주가(원)", fontsize=8)
    ax.tick_params(axis="y", labelsize=8)
    fig.tight_layout()
    fig.savefig(out_path, dpi=170)
    plt.close(fig)
    return True


def build_docx(company: str, calc_date: pd.Timestamp, table_df: pd.DataFrame, chart_path: str | None, out_path: str):
    doc = Document()
    section = doc.sections[0]
    section.page_width = Mm(210)
    section.page_height = Mm(297)
    section.top_margin = Mm(15)
    section.bottom_margin = Mm(15)
    section.left_margin = Mm(18)
    section.right_margin = Mm(18)

    title = doc.add_heading(f"{company} 일별 기준주가 보고서", level=1)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER

    now_kst = datetime.now(tz=KST)
    sub = doc.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = sub.add_run(
        f"산정기준일: {calc_date.strftime('%Y-%m-%d')}   |   생성시각(KST): {now_kst.strftime('%Y-%m-%d %H:%M')}"
    )
    run.font.size = Pt(9)

    headers = ["날짜", "종가", "2개월 VWAP", "1개월 VWAP", "1주일 VWAP", "기준주가", "10/14일 대비"]
    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Light Grid Accent 1"
    for i, h in enumerate(headers):
        cell = table.rows[0].cells[i]
        cell.text = h
        cell.paragraphs[0].runs[0].font.size = Pt(9)
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
            cells[i].paragraphs[0].runs[0].font.size = Pt(9)

    if chart_path:
        doc.add_paragraph()
        doc.add_picture(chart_path, width=Mm(170))

    doc.save(out_path)


def main():
    ap = argparse.ArgumentParser(description="기준주가 A4 보고서 생성")
    ap.add_argument("--company", required=True)
    ap.add_argument("--input", required=True, help="계산 결과 누적 xlsx 경로")
    ap.add_argument("--output", required=True, help="출력 docx 경로")
    ap.add_argument("--chart-output", default="/tmp/reference_price_chart.png")
    args = ap.parse_args()

    df = pd.read_excel(args.input, sheet_name="계산용데이터")
    df["날짜"] = pd.to_datetime(df["날짜"])
    df = df.sort_values("날짜").reset_index(drop=True)

    latest = df.dropna(subset=["기준주가"]).iloc[-1]
    calc_date = latest["날짜"]

    # 표: 2025-10-14 고정 1행 + 최근 1개월(달력 기준) 데이터
    one_month_start = (calc_date.replace(day=1) if calc_date.day == calc_date.days_in_month
                        else calc_date - pd.DateOffset(months=1) + pd.Timedelta(days=1))
    recent = df[(df["날짜"] >= one_month_start) & (df["날짜"] <= calc_date)]
    baseline_row = df[df["날짜"] == BASELINE_DATE]
    table_df = pd.concat([baseline_row, recent]).drop_duplicates(subset="날짜").sort_values("날짜")

    chart_ok = build_chart(df, args.chart_output)

    build_docx(
        args.company,
        calc_date,
        table_df,
        args.chart_output if chart_ok else None,
        args.output,
    )
    print(f"보고서 생성 완료: {args.output}")


if __name__ == "__main__":
    main()
