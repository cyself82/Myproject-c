"""
SOXL 단기 규칙 모의 매매 (실제 돈 없이 기록만)

규칙 (shortterm_bt.py 백테스트에서 2010-19, 2020~ 두 기간 모두 플러스였던 조합):
  조건   : 어제 종가가 200일 평균 위일 때만 매수 주문
  매수가 : 어제 종가 - 0.25 × ATR(14)   → 오늘 저가가 닿으면 체결 (시가가 더 낮으면 시가)
  익절가 : 체결가 + 2 × ATR              (체결 다음 날부터)
  손절가 : 체결가 - 3 × ATR
  기한   : 체결일 포함 5거래일, 안 닿으면 5일째 종가에 정리
  같은 날 익절·손절이 둘 다 닿으면 손절로 기록 (보수적)

START 이후 데이터로 매번 처음부터 다시 계산하므로 따로 저장할 상태 파일이 없습니다.
"""

import numpy as np
import pandas as pd

START = "2026-10-06"      # 모의 기록 시작일 (미국 거래일 기준)
BUDGET_KRW = 1_000_000    # 한 번 매수에 쓰는 금액 (원)
K, M, S, H, TREND = 0.25, 2.0, 3.0, 5, 200
FEE = 0.0025              # 왕복 비용 0.25%


def load_ohlc():
    import yfinance as yf
    df = yf.download("SOXL", period="5y", auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df[["Open", "High", "Low", "Close"]].dropna().astype(float)
    now_ny = pd.Timestamp.now(tz="America/New_York")
    if df.index[-1].date() == now_ny.date() and now_ny.time() < pd.Timestamp("16:15").time():
        df = df.iloc[:-1]  # 장중 미확정 가격 제외
    return df


def usdkrw():
    try:
        import yfinance as yf
        fx = yf.download("KRW=X", period="5d", progress=False)["Close"]
        return float(np.asarray(fx).ravel()[-1])
    except Exception:
        return None


def atr(df, n=14):
    prev = df["Close"].shift()
    tr = pd.concat([df["High"] - df["Low"], (df["High"] - prev).abs(), (df["Low"] - prev).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def run(df, start=START):
    """모의 매매를 START부터 다시 돌려 (완료된 거래, 보유 중 포지션, 다음 거래일 주문)을 돌려준다."""
    o, hi, lo, c = (df[x].values for x in ("Open", "High", "Low", "Close"))
    a, ma = atr(df).values, df["Close"].rolling(TREND).mean().values
    dates, n = df.index, len(df)
    trades, open_pos = [], None
    i = int(np.searchsorted(dates, pd.Timestamp(start)))
    while i < n:
        j = i - 1
        if np.isnan(a[j]) or np.isnan(ma[j]) or c[j] <= ma[j]:
            i += 1
            continue
        limit = c[j] - K * a[j]
        if lo[i] > limit:
            i += 1
            continue
        entry = min(o[i], limit)
        target, stop = entry + M * a[j], entry - S * a[j]
        exit_px = reason = None
        last = min(i + H, n)
        for d in range(i, last):
            if d > i and o[d] <= stop:
                exit_px, reason = o[d], "손절(시가 갭)"
            elif d > i and o[d] >= target:
                exit_px, reason = o[d], "익절(시가 갭)"
            elif lo[d] <= stop:
                exit_px, reason = stop, "손절"
            elif d > i and hi[d] >= target:
                exit_px, reason = target, "익절"
            if exit_px is not None:
                break
        if exit_px is None and i + H <= n:
            d, exit_px, reason = i + H - 1, c[i + H - 1], "기한 정리"
        if exit_px is None:  # 아직 기한 안 끝남 → 보유 중
            open_pos = dict(entry_date=dates[i].date(), entry=round(entry, 2), target=round(target, 2),
                            stop=round(stop, 2), days_held=n - i, days_left=H - (n - i),
                            last=round(c[-1], 2), pnl=c[-1] / entry - 1)
            break
        trades.append(dict(entry_date=dates[i].date(), entry=round(entry, 2), exit_date=dates[d].date(),
                           exit=round(exit_px, 2), reason=reason, ret=exit_px / entry - 1 - FEE))
        i = d + 1

    j = n - 1
    if open_pos:
        order = None
    elif np.isnan(ma[j]) or c[j] <= ma[j]:
        order = dict(skip=True, close=round(c[j], 2), ma=round(ma[j], 2))
    else:
        limit = c[j] - K * a[j]
        order = dict(skip=False, limit=round(limit, 2), target=round(limit + M * a[j], 2),
                     stop=round(limit - S * a[j], 2), atr=round(a[j], 2), close=round(c[j], 2))
    return trades, open_pos, order, dates[-1].date()


def stats(trades):
    if not trades:
        return dict(count=0, wins=0, win_rate=0.0, total=0.0)
    r = np.array([t["ret"] for t in trades])
    return dict(count=len(r), wins=int((r > 0).sum()), win_rate=float((r > 0).mean()),
                total=float(np.prod(1 + r) - 1))


def print_paper(trades, open_pos, order, last_date, fx=None):
    print(f"\n=== 단기 규칙 연습 기록 ({START}부터, {last_date} 종가 기준) ===")
    if open_pos:
        p = open_pos
        print(f"[연습 보유 중] {p['entry_date']} {p['entry']}에 매수 · 현재 {p['last']} ({p['pnl']:+.1%})")
        print(f"    익절가 {p['target']} / 손절가 {p['stop']} · 남은 기한 {p['days_left']}거래일 (다 되면 종가에 정리)")
    elif order["skip"]:
        print(f"[다음 거래일] 매수 쉼: 종가 {order['close']}가 200일선 {order['ma']} 아래")
    else:
        shares = BUDGET_KRW / fx / order["limit"] if fx else None
        qty = f" · {BUDGET_KRW:,}원이면 약 {shares:.2f}주" if shares else ""
        print(f"[다음 거래일 주문] 매수 지정가 {order['limit']}{qty}")
        print(f"    체결되면 → 익절가 {order['target']} / 손절가 {order['stop']} · 최대 {H}거래일 보유")
    s = stats(trades)
    print(f"[기록] 완료 {s['count']}건 · 이익 {s['wins']}건 · 승률 {s['win_rate']:.0%} · 누적 {s['total']:+.1%}")
    for t in trades[-10:]:
        print(f"    {t['entry_date']} {t['entry']} → {t['exit_date']} {t['exit']} {t['reason']} {t['ret']:+.1%}")


if __name__ == "__main__":
    df = load_ohlc()
    print_paper(*run(df), fx=usdkrw())
