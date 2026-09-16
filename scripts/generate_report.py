#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
계산 결과(누적 xlsx)로부터 A4 1장 기준주가 보고서(.pdf)를 생성한다.

표: 기준일 행(굵은 구분선) + 기준일~최근 1개월 이전까지의 월말 요약 행들
    (굵은 구분선) + 최근 1개월 일별 데이터 (최신 날짜가 맨 아래)
그래프: 종가 추이(기준일부터), 최고점(빨강)/최저점(파랑)/마지막점(검정) 강조 표시
기준일은 회사마다 다를 수 있음 (--baseline-date, 기본값 2025-10-14)

사용법:
    python3 generate_report.py --company "삼성전자" \
        --input 삼성전자_일별_기준주가.xlsx \
        --output 삼성전자_일별_기준주가_보고서.pdf
"""
import argparse
from datetime import datetime, timedelta, timezone

import matplotlib
matplotlib.use("Agg")
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
import pandas as pd

# 한글 폰트 등록 (GitHub Actions 러너에는 한글 폰트가 기본 설치되어 있지 않으므로,
# apt로 설치한 나눔 폰트 중 명조(세리프) 계열을 우선 찾아 등록한다 - 참고 양식과
# 비슷한 느낌을 위함. 명조가 없으면 고딕 계열로 대체.
try:
    import glob

    _priority = [
        "/usr/share/fonts/**/NanumMyeongjo.ttf",
        "/usr/share/fonts/**/NanumMyeongjo*.ttf",
        "/usr/share/fonts/**/*Batang*.ttf",
        "/usr/share/fonts/**/*CJK*Serif*.ttc",
        "/usr/share/fonts/**/NanumGothic.ttf",
        "/usr/share/fonts/**/Nanum*.ttf",
        "/usr/share/fonts/**/*CJK*.ttc",
        "/usr/share/fonts/**/*CJK*.otf",
    ]
    _candidates = []
    for pattern in _priority:
        _candidates.extend(glob.glob(pattern, recursive=True))
    if _candidates:
        fm.fontManager.addfont(_candidates[0])
        plt.rc("font", family=fm.FontProperties(fname=_candidates[0]).get_name())
except Exception:
    pass  # 폰트 등록에 실패해도 보고서 생성 자체는 계속 진행 (라벨이 깨질 수 있음)
plt.rcParams["axes.unicode_minus"] = False

KST = timezone(timedelta(hours=9))
DEFAULT_BASELINE_DATE = pd.Timestamp("2025-10-14")

HEADERS = ["날짜", "종가", "2개월", "1개월", "1주일", "기준 주가", "상승률"]


def fmt_won(v):
    return "-" if pd.isna(v) else f"{int(round(v)):,}"


def fmt_pct(v):
    return "-" if pd.isna(v) else f"{v * 100:.1f}%"


def build_table_rows(df: pd.DataFrame, calc_date: pd.Timestamp, baseline_date: pd.Timestamp = DEFAULT_BASELINE_DATE):
    """기준일 행 + (기준일~최근1개월 이전) 월말 요약 행 + 최근 1개월 일별 행을 만들고,
    굵은 구분선을 그어야 할 위치(0-base, 헤더 제외 데이터 행 인덱스)를 함께 반환한다."""
    baseline_row = df[df["날짜"] == baseline_date]

    one_month_start = (calc_date.replace(day=1) if calc_date.day == calc_date.days_in_month
                        else calc_date - pd.DateOffset(months=1) + pd.Timedelta(days=1))
    recent = df[(df["날짜"] >= one_month_start) & (df["날짜"] <= calc_date)]

    hist = df[(df["날짜"] > baseline_date) & (df["날짜"] < one_month_start)].copy()
    if not hist.empty:
        hist["ym"] = hist["날짜"].dt.to_period("M")
        monthly = hist.groupby("ym").tail(1).drop(columns="ym")
    else:
        monthly = hist

    table_df = pd.concat([baseline_row, monthly, recent]).drop_duplicates(subset="날짜").sort_values("날짜")
    table_df = table_df.reset_index(drop=True)

    # 굵은 구분선 위치: 기준일 행 다음, 월말 요약 구간 끝난 다음
    n_baseline = len(baseline_row)
    n_monthly = len(monthly)
    bold_after = set()
    if n_baseline:
        bold_after.add(n_baseline - 1)
    if n_monthly:
        bold_after.add(n_baseline + n_monthly - 1)

    return table_df, bold_after


def draw_table(ax, table_df: pd.DataFrame, bold_after: set):
    cell_text = [
        [
            row["날짜"].strftime("%Y-%m-%d"),
            fmt_won(row["종가"]),
            fmt_won(row["2개월VWAP"]),
            fmt_won(row["1개월VWAP"]),
            fmt_won(row["5영업일VWAP"]),
            fmt_won(row["기준주가"]),
            fmt_pct(row["기준일_대비_증가율"]),
        ]
        for _, row in table_df.iterrows()
    ]
    tbl = ax.table(cellText=cell_text, colLabels=HEADERS, loc="upper center", cellLoc="center")
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(8.5)
    tbl.scale(1.02, 1.0)  # y는 1.0 유지 - 행이 많아도 표 영역(axes) 밖으로 넘치지 않게 함

    n_cols = len(HEADERS)
    for (r, _c), cell in tbl.get_celld().items():
        cell.set_edgecolor("#999999")
        cell.set_linewidth(0.6)
        if r == 0:
            cell.set_text_props(fontweight="bold")
            cell.set_facecolor("#E9EEF5")
            cell.set_linewidth(1.4)

    # 헤더 위 + 표 맨 아래 + 지정된 구간 사이에 굵은 선
    bold_rows = {0}  # 헤더 아래
    bold_rows |= {i + 1 for i in bold_after}  # 데이터 행은 헤더가 0행이므로 +1
    bold_rows.add(len(table_df))  # 표 맨 아래
    for r in bold_rows:
        for c in range(n_cols):
            try:
                cell = tbl[(r, c)]
            except KeyError:
                continue
            cell.set_linewidth(1.4)
    return tbl


def build_chart(df: pd.DataFrame, ax, baseline_date: pd.Timestamp = DEFAULT_BASELINE_DATE) -> bool:
    """전달받은 Axes 위에 종가 추이 그래프를 그린다 (기준일부터, 최고/최저/마지막 강조)."""
    plot_df = df[df["날짜"] >= baseline_date].dropna(subset=["종가"]).reset_index(drop=True)
    if plot_df.empty:
        return False

    ax.set_title(
        f"일별 종가 추이({plot_df['날짜'].iloc[0].strftime('%Y-%m-%d')} ~ {plot_df['날짜'].iloc[-1].strftime('%Y-%m-%d')})",
        fontsize=10,
    )
    ax.plot(plot_df["날짜"], plot_df["종가"], color="#2E6E9E", linewidth=1.2)
    ax.grid(True, axis="y", linestyle="--", linewidth=0.5, color="#cccccc")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    # x축: 월 단위 눈금, 45도 회전
    plot_df["ym"] = plot_df["날짜"].dt.to_period("M")
    month_first = plot_df.groupby("ym").head(1)
    ax.set_xticks(month_first["날짜"])
    ax.set_xticklabels(month_first["날짜"].dt.strftime("%Y-%m"), rotation=45, ha="right", fontsize=7.5)

    max_idx = plot_df["종가"].idxmax()
    min_idx = plot_df["종가"].idxmin()
    last_idx = plot_df.index[-1]

    def _annotate(idx, color, prefix):
        row = plot_df.loc[idx]
        d = row["날짜"]
        ax.scatter([d], [row["종가"]], color=color, zorder=5, s=28)
        ax.annotate(
            f"{prefix} {int(row['종가']):,}원({d.strftime('%Y.%m.%d')}일)",
            (d, row["종가"]),
            textcoords="offset points",
            xytext=(0, 10),
            fontsize=7.5,
            ha="center",
            color=color,
        )

    _annotate(max_idx, "#C0392B", "최고")
    if min_idx != max_idx:
        _annotate(min_idx, "#2E6E9E", "최저")
    if last_idx not in (max_idx, min_idx):
        _annotate(last_idx, "#222222", "")

    ax.set_ylabel("종가(원)", fontsize=8)
    ax.tick_params(axis="y", labelsize=8)
    ax.yaxis.set_major_formatter(lambda v, _pos: f"{int(v):,}")
    return True


def render_report_page(fig, company: str, calc_date: pd.Timestamp, table_df: pd.DataFrame,
                        bold_after: set, full_df: pd.DataFrame, baseline_date: pd.Timestamp = DEFAULT_BASELINE_DATE):
    """A4 한 페이지(제목 + 표 + 그래프)를 주어진 figure 위에 그린다.
    개별 보고서(페이지 1장짜리 fig)와 통합 보고서(회사별로 반복 호출)에서 공용으로 쓴다."""
    gs = fig.add_gridspec(nrows=3, ncols=1, height_ratios=[0.07, 0.42, 0.48],
                           top=0.96, bottom=0.05, left=0.08, right=0.94, hspace=0.12)

    ax_title = fig.add_subplot(gs[0])
    ax_title.axis("off")
    ax_title.text(0.5, 0.5, f"{company} 기준주가({calc_date.strftime('%Y.%m.%d')})",
                  ha="center", va="center", fontsize=17, fontweight="bold")

    ax_table = fig.add_subplot(gs[1])
    ax_table.axis("off")
    draw_table(ax_table, table_df, bold_after)

    ax_chart = fig.add_subplot(gs[2])
    chart_ok = build_chart(full_df, ax_chart, baseline_date)
    if not chart_ok:
        ax_chart.axis("off")


def build_pdf(company: str, calc_date: pd.Timestamp, table_df: pd.DataFrame,
              bold_after: set, full_df: pd.DataFrame, out_path: str,
              baseline_date: pd.Timestamp = DEFAULT_BASELINE_DATE):
    fig = plt.figure(figsize=(210 / 25.4, 297 / 25.4))  # A4 (mm -> inch)
    render_report_page(fig, company, calc_date, table_df, bold_after, full_df, baseline_date)
    fig.savefig(out_path, format="pdf")
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description="기준주가 A4 보고서 생성")
    ap.add_argument("--company", required=True)
    ap.add_argument("--input", required=True, help="계산 결과 누적 xlsx 경로")
    ap.add_argument("--output", required=True, help="출력 pdf 경로")
    ap.add_argument("--baseline-date", default="2025-10-14",
                    help="상승률 산정 기준일 (YYYY-MM-DD). 회사별로 다를 수 있음")
    args = ap.parse_args()

    baseline_date = pd.Timestamp(args.baseline_date)

    df = pd.read_excel(args.input, sheet_name="계산용데이터")
    df["날짜"] = pd.to_datetime(df["날짜"])
    df = df.sort_values("날짜").reset_index(drop=True)

    latest = df.dropna(subset=["기준주가"]).iloc[-1]
    calc_date = latest["날짜"]

    table_df, bold_after = build_table_rows(df, calc_date, baseline_date)

    build_pdf(args.company, calc_date, table_df, bold_after, df, args.output, baseline_date)
    print(f"보고서 생성 완료: {args.output}")


if __name__ == "__main__":
    main()
