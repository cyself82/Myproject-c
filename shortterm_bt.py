"""
SOXL 단기 매매 규칙 백테스트 (하루 단위 시가·고가·저가·종가 사용)

규칙 (매일 장 마감 후 계산 → 다음 날 지정가로 주문):
  매수가 = 어제 종가 - k × ATR(14)          → 다음 날 저가가 닿으면 체결
  익절가 = 체결가 + m × ATR                 → 닿으면 매도
  손절가 = 체결가 - s × ATR                 → 닿으면 매도
  보유 기한 = 최대 h일, 그때까지 안 닿으면 그날 종가에 정리
  추세 필터 = 종가가 n일 평균 위일 때만 매수 (선택)

체결 가정은 보수적으로: 같은 날 익절가와 손절가가 둘 다 닿으면 손절로 봅니다.
기간을 둘로 나눠, 앞 기간(학습)에서 고른 규칙이 뒤 기간(검증)에서도 통하는지 봅니다.

사용법:
    python shortterm_bt.py                 # Yahoo Finance에서 SOXL 받아서 실행
    python shortterm_bt.py --csv SOXL.csv  # Open,High,Low,Close 열이 있는 CSV
"""

import argparse
import itertools

import numpy as np
import pandas as pd

FEE = 0.0025      # 한 번 사고팔 때 총비용 0.25% (수수료 + 환전/호가 차이 대략치)
SPLIT = "2020-01-01"


def load(csv=None):
    if csv:
        df = pd.read_csv(csv, index_col=0, parse_dates=True)
    else:
        import yfinance as yf
        df = yf.download("SOXL", period="max", auto_adjust=True, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
    return df[["Open", "High", "Low", "Close"]].dropna().astype(float)


def atr(df, n=14):
    prev = df["Close"].shift()
    tr = pd.concat([df["High"] - df["Low"], (df["High"] - prev).abs(), (df["Low"] - prev).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def simulate(df, k, m, s, h, trend_n):
    """한 번에 한 포지션만. 거래별 수익률 리스트와 날짜를 돌려준다."""
    o, hi, lo, c = (df[x].values for x in ("Open", "High", "Low", "Close"))
    a = atr(df).values
    ma = df["Close"].rolling(trend_n).mean().values if trend_n else None
    trades, i, n = [], 1, len(df)
    while i < n:
        j = i - 1  # 어제 장 마감 기준으로 주문 가격 결정
        if np.isnan(a[j]) or (ma is not None and (np.isnan(ma[j]) or c[j] <= ma[j])):
            i += 1
            continue
        limit = c[j] - k * a[j]
        if lo[i] > limit:  # 매수 지정가 미체결
            i += 1
            continue
        entry = min(o[i], limit)
        target, stop = entry + m * a[j], entry - s * a[j]
        exit_px, d = None, i
        for d in range(i, min(i + h, n)):
            if d > i:  # 체결 다음 날부터는 시가 갭도 반영
                if o[d] <= stop:
                    exit_px = o[d]
                    break
                if o[d] >= target:
                    exit_px = o[d]
                    break
            if lo[d] <= stop:
                exit_px = stop
                break
            if d > i and hi[d] >= target:
                exit_px = target
                break
        if exit_px is None:
            d = min(i + h, n) - 1
            exit_px = c[d]
        trades.append((df.index[i], exit_px / entry - 1 - FEE))
        i = d + 1
    return trades


def summarize(trades, years):
    if not trades:
        return dict(매매수=0, 연간매매=0, 승률=0, 평균수익=0, 누적=1, 최대낙폭=0, 최다연속손실=0)
    r = np.array([t[1] for t in trades])
    eq = np.cumprod(1 + r)
    streak = best = 0
    for x in r:
        streak = streak + 1 if x <= 0 else 0
        best = max(best, streak)
    return dict(매매수=len(r), 연간매매=round(len(r) / years, 1), 승률=round((r > 0).mean(), 3),
                평균수익=round(r.mean(), 4), 누적=round(eq[-1], 2),
                최대낙폭=round((eq / np.maximum.accumulate(eq) - 1).min(), 3), 최다연속손실=best)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--csv")
    p.add_argument("--out", default="shortterm_results.csv")
    a = p.parse_args()
    df = load(a.csv)
    train, test = df[df.index < SPLIT], df[df.index >= SPLIT]
    yrs = lambda d: len(d) / 252
    grid = itertools.product([0.25, 0.5, 0.75, 1.0],      # k: 매수가 = 종가 - k·ATR
                             [0.5, 1.0, 1.5, 2.0],        # m: 익절 폭
                             [1.0, 1.5, 2.0, 3.0],        # s: 손절 폭
                             [1, 3, 5],                   # h: 최대 보유일
                             [0, 50, 200])                # 추세 필터 (0 = 없음)
    rows = []
    for k, m, s, h, t in grid:
        tr, te = summarize(simulate(train, k, m, s, h, t), yrs(train)), summarize(simulate(test, k, m, s, h, t), yrs(test))
        rows.append(dict(k=k, m=m, s=s, h=h, 추세=t, **{f"학습_{x}": v for x, v in tr.items()},
                         **{f"검증_{x}": v for x, v in te.items()}))
    res = pd.DataFrame(rows)
    res.to_csv(a.out, index=False, encoding="utf-8-sig")

    ok = res[(res["학습_연간매매"] >= 10) & (res["학습_평균수익"] > 0)]
    top = ok.sort_values("학습_평균수익", ascending=False).head(15)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 30)
    print(f"데이터 {df.index[0].date()} ~ {df.index[-1].date()} | 학습 ~{SPLIT} | 검증 {SPLIT}~ | 비용 {FEE:.2%}/회")
    print(f"조합 {len(res)}개 중 학습 기간에 연 10회 이상 매매하고 평균수익이 플러스인 조합: {len(ok)}개")
    cols = ["k", "m", "s", "h", "추세", "학습_연간매매", "학습_승률", "학습_평균수익", "학습_최대낙폭",
            "검증_연간매매", "검증_승률", "검증_평균수익", "검증_누적", "검증_최대낙폭", "검증_최다연속손실"]
    print("\n[학습 기간 평균수익 상위 15개와 검증 기간 성적]")
    print(top[cols].to_string(index=False))
    both = res[(res["학습_평균수익"] > 0) & (res["검증_평균수익"] > 0) & (res["검증_연간매매"] >= 10)]
    print(f"\n학습·검증 두 기간 모두 평균수익 플러스(연 10회 이상): {len(both)}개 / {len(res)}개")
    print(f"전체 결과 저장: {a.out}")


if __name__ == "__main__":
    main()
