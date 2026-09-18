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
    n_rows = len(table_df)
    n_cols = len(HEADERS)

    tbl = ax.table(cellText=cell_text, colLabels=HEADERS, loc="upper center", cellLoc="center")
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(8.5)
    tbl.scale(1.02, 1.0)  # y는 1.0 유지 - 행이 많아도 표 영역(axes) 밖으로 넘치지 않게 함

    # 기본은 전부 얇은 한 줄 테두리 (헤더 포함, 특별 취급 없음)
    for (r, _c), cell in tbl.get_celld().items():
        cell.set_edgecolor("#999999")
        cell.set_linewidth(0.6)
        if r == 0:
            cell.set_text_props(fontweight="bold")
            cell.set_facecolor("#E9EEF5")

    # 마지막(최신) 행은 굵게 표시
    last_row_idx = n_rows  # 헤더가 0행이므로 데이터 마지막 행은 n_rows
    for c in range(n_cols):
        try:
            tbl[(last_row_idx, c)].set_text_props(fontweight="bold")
        except KeyError:
            pass

    # 셀의 실제 x/y/width/height는 그림이 한 번 렌더링되기 전까지 계산되지 않으므로
    # (기본값 0), 강제로 한 번 그려서 레이아웃을 확정한 뒤 좌표를 읽는다.
    ax.figure.canvas.draw()

    # 지정된 두 경계 위치에 이중선을 실제 셀 좌표 기준으로 그린다
    for data_idx in bold_after:  # 이 데이터 행(0-base) '아래'를 굵은 선으로 구분
        table_row = data_idx + 1  # 헤더가 0행이므로 데이터 행은 +1
        try:
            cell = tbl[(table_row, 0)]
        except KeyError:
            continue
        y = cell.get_y()  # 이 행의 아래쪽 경계 = 다음 행과의 경계선
        ax.plot([-0.01, 1.01], [y, y], transform=ax.transAxes,
                color="#222222", linewidth=1.8, solid_capstyle="butt", clip_on=False, zorder=10)

    # 마지막 행 '상승률' 값 위에 파란 동그라미 표시
    try:
        last_pct_cell = tbl[(last_row_idx, n_cols - 1)]
        cx = last_pct_cell.get_x() + last_pct_cell.get_width() / 2
        cy = last_pct_cell.get_y() + last_pct_cell.get_height()  # 셀 상단
        ax.scatter([cx], [cy], transform=ax.transAxes, s=40, marker="o",
                   facecolor="none", edgecolor="#1F5FBF", linewidth=1.6,
                   zorder=6, clip_on=False)
    except KeyError:
        pass

    return tbl
    
def build_chart(df: pd.DataFrame, ax, baseline_date: pd.Timestamp = DEFAULT_BASELINE_DATE):
    """전달받은 Axes 위에 종가 추이 그래프를 그린다 (기준일부터, 최고/최저/마지막 강조).
    제목은 이 축 위에 직접 그리지 않고 문자열로 반환한다 (표-그래프 사이 여백에 별도 배치하기 위함)."""
    plot_df = df[df["날짜"] >= baseline_date].dropna(subset=["종가"]).reset_index(drop=True)
    if plot_df.empty:
        return False, None

    title_text = (
        f"일별 종가 추이({plot_df['날짜'].iloc[0].strftime('%Y-%m-%d')} ~ "
        f"{plot_df['날짜'].iloc[-1].strftime('%Y-%m-%d')})"
    )
    ax.plot(plot_df["날짜"], plot_df["종가"], color="#2E6E9E", linewidth=1.2)
    ax.grid(True, axis="y", linestyle="--", linewidth=0.5, color="#cccccc")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    # 최고점이 축 맨 꼭대기에 붙어있으면 그 위의 라벨이 축 밖(제목 영역)까지
    # 튀어나가버리므로, 위쪽에 미리 여유 공간을 확보해둔다.
    y_min, y_max = plot_df["종가"].min(), plot_df["종가"].max()
    y_range = y_max - y_min or y_max * 0.1
    ax.set_ylim(y_min - y_range * 0.08, y_max + y_range * 0.15)

    # x축: 월 단위 눈금, 45도 회전
    plot_df["ym"] = plot_df["날짜"].dt.to_period("M")
    month_first = plot_df.groupby("ym").head(1)
    ax.set_xticks(month_first["날짜"])
    ax.set_xticklabels(month_first["날짜"].dt.strftime("%Y-%m"), rotation=45, ha="right", fontsize=7.5)

    max_idx = plot_df["종가"].idxmax()
    min_idx = plot_df["종가"].idxmin()
    last_idx = plot_df.index[-1]
    n_points = len(plot_df)

    def _annotate(idx, color, prefix):
        row = plot_df.loc[idx]
        d = row["날짜"]
        ax.scatter([d], [row["종가"]], color=color, zorder=5, s=28)

        # 시작/끝 지점 근처에서는 라벨이 y축이나 그래프 밖으로 넘어가지 않도록
        # 가운데 정렬 대신 안쪽 방향으로 정렬을 바꾼다.
        rel_pos = idx / max(n_points - 1, 1)
        if rel_pos < 0.05:
            xytext, ha = (12, 10), "left"
        elif rel_pos > 0.95:
            xytext, ha = (-12, 10), "right"
        else:
            xytext, ha = (0, 10), "center"

        ax.annotate(
            f"{prefix} {int(row['종가']):,}원({d.strftime('%Y.%m.%d')}일)",
            (d, row["종가"]),
            textcoords="offset points",
            xytext=xytext,
            fontsize=7.5,
            ha=ha,
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
    return True, title_text


def render_report_page(fig, company: str, calc_date: pd.Timestamp, table_df: pd.DataFrame,
                        bold_after: set, full_df: pd.DataFrame, baseline_date: pd.Timestamp = DEFAULT_BASELINE_DATE):
    """A4 한 페이지(제목 + 표 + 그래프)를 주어진 figure 위에 그린다.
    개별 보고서(페이지 1장짜리 fig)와 통합 보고서(회사별로 반복 호출)에서 공용으로 쓴다."""
    n_rows = len(table_df)
    table_units = n_rows + 1  # +헤더
    title_units = 3
    chart_units = max(16, 34 - table_units)  # 표가 커져도 그래프 영역이 너무 작아지지 않게 최소값 보장
    gs = fig.add_gridspec(nrows=3, ncols=1, height_ratios=[title_units, table_units, chart_units],
                           top=0.96, bottom=0.05, left=0.08, right=0.94, hspace=0.09)

    ax_title = fig.add_subplot(gs[0])
    ax_title.axis("off")
    ax_title.text(0.5, 0.5, f"{company} 기준주가({calc_date.strftime('%Y.%m.%d')})",
                  ha="center", va="center", fontsize=17, fontweight="bold")

    ax_table = fig.add_subplot(gs[1])
    ax_table.axis("off")
    draw_table(ax_table, table_df, bold_after)

    ax_chart = fig.add_subplot(gs[2])
    chart_ok, chart_title = build_chart(full_df, ax_chart, baseline_date)
    if not chart_ok:
        ax_chart.axis("off")

    # 그래프의 '전체' 폭(y축 라벨 "종가(원)" + 눈금 숫자까지 포함)이 표의 전체 폭과
    # 정확히 같아지도록 맞춘다. y축 라벨/눈금은 축 상자(spine)보다 왼쪽으로 삐져나오므로,
    # 그 삐져나온 만큼 축 상자 자체를 오른쪽으로 밀어 넣어야 전체 폭이 표와 일치한다.
    if chart_ok:
        fig.canvas.draw()
        table_pos = ax_table.get_position()
        chart_pos = ax_chart.get_position()
        renderer = fig.canvas.get_renderer()
        yaxis_bbox = ax_chart.yaxis.get_tightbbox(renderer)
        yaxis_bbox_fig = yaxis_bbox.transformed(fig.transFigure.inverted())
        left_overhang = chart_pos.x0 - yaxis_bbox_fig.x0  # 라벨이 축 상자보다 왼쪽으로 튀어나온 양
        new_x0 = table_pos.x0 + max(left_overhang, 0)
        new_right = table_pos.x0 + table_pos.width  # 오른쪽 끝은 표와 동일하게 유지
        ax_chart.set_position([new_x0, ax_chart.get_position().y0, new_right - new_x0,
                                ax_chart.get_position().height])

        # 표 하단과 그래프 상단 사이 여백의 3/4 지점(그래프에 더 가까운 쪽)에
        # 그래프 제목을 굵게 배치한다.
        table_bottom = table_pos.y0
        chart_top = ax_chart.get_position().y1
        title_y = table_bottom - (table_bottom - chart_top) * 0.75
        title_x = table_pos.x0 + table_pos.width / 2
        fig.text(title_x, title_y, chart_title, ha="center", va="center",
                  fontsize=10, fontweight="bold")
    else:
        table_pos = ax_table.get_position()
        chart_pos = ax_chart.get_position()
        ax_chart.set_position([table_pos.x0, chart_pos.y0, table_pos.width, chart_pos.height])


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
