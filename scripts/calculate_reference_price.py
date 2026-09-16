#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
기준주가 계산 스크립트

입력: 날짜/종가/거래량 컬럼을 가진 원자료(신규 다운로드분) + (선택) 기존 누적 파일
처리: 문서 기준(2개월/1개월/5영업일 VWAP 평균 -> 반올림)에 따라 전체 이력에 대해
      기준주가와 기준일 대비 증가율을 계산 (기준일은 회사별로 다를 수 있음)
출력: 누적 계산용 엑셀 파일(.xlsx) + 최신 기준일 요약 JSON(stdout)

의존성: pandas, openpyxl, python-dateutil
"""
import argparse
import json
import sys
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

import pandas as pd
from dateutil.relativedelta import relativedelta

DEFAULT_BASELINE_DATE = pd.Timestamp("2025-10-14")

REQUIRED_COLS = ["날짜", "종가", "거래량"]


def round_half_up(value: float) -> int:
    """원 단위 반올림 (0.5는 항상 올림 — 은행반올림 방지)."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def load_raw_table(path: str) -> pd.DataFrame:
    """날짜/종가/거래량 컬럼을 가진 csv 또는 xlsx를 읽어 표준화한다."""
    if path.lower().endswith(".csv"):
        df = pd.read_csv(path)
    else:
        df = pd.read_excel(path)

    # 컬럼명 유연 매칭 (KRX 원자료는 '일자', '종가', '거래량' 등으로 내려오는 경우가 많음)
    rename_map = {}
    for col in df.columns:
        c = str(col).strip()
        if c in ("일자", "날짜", "date", "Date"):
            rename_map[col] = "날짜"
        elif c in ("종가", "close", "Close"):
            rename_map[col] = "종가"
        elif c in ("거래량", "volume", "Volume"):
            rename_map[col] = "거래량"
    df = df.rename(columns=rename_map)

    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"필수 컬럼 누락: {missing} (있는 컬럼: {list(df.columns)})")

    df = df[REQUIRED_COLS].copy()
    df["날짜"] = pd.to_datetime(df["날짜"])
    df["종가"] = pd.to_numeric(
        df["종가"].astype(str).str.replace(",", "", regex=False), errors="coerce"
    )
    df["거래량"] = pd.to_numeric(
        df["거래량"].astype(str).str.replace(",", "", regex=False), errors="coerce"
    )
    df = df.dropna(subset=["날짜", "종가", "거래량"])
    return df


def merge_data(existing: pd.DataFrame | None, new: pd.DataFrame | None) -> pd.DataFrame:
    """기존 누적 데이터 + 신규 데이터를 날짜 기준으로 병합(중복 날짜는 신규 값으로 정정)."""
    frames = [f for f in (existing, new) if f is not None and not f.empty]
    if not frames:
        raise ValueError("입력 데이터가 없습니다.")
    combined = pd.concat(frames, ignore_index=True)
    # 같은 날짜가 여러 번 있으면 마지막(신규) 값을 채택
    combined = combined.drop_duplicates(subset="날짜", keep="last")
    combined = combined.sort_values("날짜").reset_index(drop=True)
    return combined


def period_bounds(calc_date: pd.Timestamp, months: int) -> tuple[pd.Timestamp, pd.Timestamp]:
    """문서 4장 규칙에 따른 달력 기준 산정기간 산출."""
    next_day = calc_date + timedelta(days=1)
    is_month_end = next_day.month != calc_date.month  # 다음날이 다른 달이면 월말

    if is_month_end:
        if months == 2:
            start = (calc_date.replace(day=1) - relativedelta(months=1)).replace(day=1)
        else:  # months == 1
            start = calc_date.replace(day=1)
        end = calc_date
    else:
        start = calc_date - relativedelta(months=months) + timedelta(days=1)
        end = calc_date
    return start, end


def vwap(df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> float | None:
    mask = (df["날짜"] >= start) & (df["날짜"] <= end)
    sub = df.loc[mask]
    if sub.empty or sub["거래량"].sum() == 0:
        return None
    return float((sub["종가"] * sub["거래량"]).sum() / sub["거래량"].sum())


def vwap_last_n_trading_days(df: pd.DataFrame, calc_date: pd.Timestamp, n: int) -> float | None:
    sub = df.loc[df["날짜"] <= calc_date].tail(n)
    if len(sub) < n or sub["거래량"].sum() == 0:
        return None
    return float((sub["종가"] * sub["거래량"]).sum() / sub["거래량"].sum())


def compute_all(df: pd.DataFrame, baseline_date: pd.Timestamp = DEFAULT_BASELINE_DATE) -> pd.DataFrame:
    """전체 이력에 대해 VWAP·기준주가를 계산한다(데이터가 부족한 초기 구간은 NaN).
    baseline_date: 상승률 산정 기준일 (회사별로 다를 수 있음 - 예: 상장일이 늦은 회사)."""
    df = df.sort_values("날짜").reset_index(drop=True)
    rows = []
    for _, row in df.iterrows():
        calc_date = row["날짜"]
        start2, end2 = period_bounds(calc_date, 2)
        start1, end1 = period_bounds(calc_date, 1)

        vwap2 = vwap(df, start2, end2)
        vwap1 = vwap(df, start1, end1)
        vwap5 = vwap_last_n_trading_days(df, calc_date, 5)

        if None in (vwap2, vwap1, vwap5):
            ref_price = None
        else:
            ref_price = round_half_up((vwap2 + vwap1 + vwap5) / 3)

        rows.append(
            {
                "날짜": calc_date,
                "종가": row["종가"],
                "거래량": row["거래량"],
                "2개월VWAP": round_half_up(vwap2) if vwap2 is not None else None,
                "1개월VWAP": round_half_up(vwap1) if vwap1 is not None else None,
                "5영업일VWAP": round_half_up(vwap5) if vwap5 is not None else None,
                "기준주가": ref_price,
            }
        )
    result = pd.DataFrame(rows)

    # 기준일 대비 증가율 (기준일은 회사마다 다를 수 있음)
    baseline_rows = result.loc[result["날짜"] == baseline_date, "기준주가"]
    baseline_price = (
        float(baseline_rows.iloc[0])
        if not baseline_rows.empty and pd.notna(baseline_rows.iloc[0])
        else None
    )
    if baseline_price:
        result["기준일_대비_증가율"] = result["기준주가"].apply(
            lambda p: (p / baseline_price - 1) if pd.notna(p) else None
        )
    else:
        result["기준일_대비_증가율"] = None

    return result, baseline_price


def main():
    ap = argparse.ArgumentParser(description="기준주가 계산")
    ap.add_argument("--company", required=True, help="회사명 (파일명/요약에 사용)")
    ap.add_argument("--existing", help="기존 누적 파일 경로 (.xlsx), 없으면 생략")
    ap.add_argument("--new-data", help="신규 원자료 경로 (.csv/.xlsx), 없으면 생략")
    ap.add_argument("--output", required=True, help="출력 누적 엑셀 경로 (.xlsx)")
    ap.add_argument("--baseline-date", default="2025-10-14",
                    help="상승률 산정 기준일 (YYYY-MM-DD). 회사별로 다를 수 있음 (예: 상장일이 늦은 회사)")
    args = ap.parse_args()

    baseline_date = pd.Timestamp(args.baseline_date)

    if not args.existing and not args.new_data:
        print("오류: --existing 또는 --new-data 중 최소 하나는 필요합니다.", file=sys.stderr)
        sys.exit(1)

    existing_df = None
    if args.existing:
        existing_raw = pd.read_excel(args.existing, sheet_name="계산용데이터")
        existing_df = existing_raw[REQUIRED_COLS].copy()
        existing_df["날짜"] = pd.to_datetime(existing_df["날짜"])

    new_df = load_raw_table(args.new_data) if args.new_data else None

    merged = merge_data(existing_df, new_df)
    computed, baseline_price = compute_all(merged, baseline_date)

    with pd.ExcelWriter(args.output, engine="openpyxl") as writer:
        computed.to_excel(writer, sheet_name="계산용데이터", index=False)

    latest = computed.dropna(subset=["기준주가"]).iloc[-1] if computed["기준주가"].notna().any() else None

    summary = {
        "company": args.company,
        "output_file": args.output,
        "total_rows": int(len(computed)),
        "baseline_date": baseline_date.strftime("%Y-%m-%d"),
        "baseline_reference_price": baseline_price,
        "latest": None,
    }
    def _num(v):
        if v is None or pd.isna(v):
            return None
        return float(v)

    if latest is not None:
        summary["latest"] = {
            "날짜": latest["날짜"].strftime("%Y-%m-%d"),
            "종가": _num(latest["종가"]),
            "2개월VWAP": _num(latest["2개월VWAP"]),
            "1개월VWAP": _num(latest["1개월VWAP"]),
            "5영업일VWAP": _num(latest["5영업일VWAP"]),
            "기준주가": _num(latest["기준주가"]),
            "기준일_대비_증가율": _num(latest["기준일_대비_증가율"]),
        }

    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
