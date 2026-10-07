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
# 매수 하한가(참고선) = 매수 상한가 - 1 × ATR. 규칙에는 쓰지 않고 화면에만 보여 준다.
# 2010~2026 백테스트에서 시가가 이보다 낮게 시작해 체결된 거래는 7건, 평균 -4.7%, 승률 29%였다.
FLOOR_ATR = 1.0


def load_ohlc():
    import yfinance as yf
    df = yf.download("SOXL", period="max", auto_adjust=True, progress=False)
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


def gap_q(df):
    """시가가 매수 상한가보다 낮게 열린 날들에서, 시가가 상한가보다 얼마나 낮았는지의 하위 10% 값 (예: -0.048).

    '보통 체결되는 범위'의 아래쪽을 정하는 데 쓴다: 그런 날의 90%는 이보다 덜 낮게 열렸다.
    """
    limit = (df["Close"] - K * atr(df)).shift()      # 전날 종가로 정한 상한가
    gap = (df["Open"] / limit - 1).dropna()
    gap = gap[gap < 0]
    return float(np.percentile(gap, 10)) if len(gap) else 0.0


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
        order = dict(skip=False, limit=round(limit, 2), floor=round(limit - FLOOR_ATR * a[j], 2),
                     range_low=round(limit * (1 + gap_q(df)), 2),
                     target=round(limit + M * a[j], 2),
                     stop=round(limit - S * a[j], 2), atr=round(a[j], 2), close=round(c[j], 2))
    return trades, open_pos, order, dates[-1].date()


def _minutes():
    """SOXL 1분봉 (전체, 오늘 정규장 09:30~16:00 부분). 못 받으면 (None, None)."""
    try:
        import yfinance as yf
        m = yf.download("SOXL", period="1d", interval="1m", prepost=True, auto_adjust=True, progress=False)
        if isinstance(m.columns, pd.MultiIndex):
            m.columns = m.columns.get_level_values(0)
        m = m[["Open", "High", "Low", "Close"]].dropna().astype(float)
        if m.empty:
            return None, None
        m.index = m.index.tz_convert("America/New_York")
    except Exception:
        return None, None
    now_ny = pd.Timestamp.now(tz="America/New_York")
    hhmm = m.index.strftime("%H:%M")
    return m, m[(m.index.date == now_ny.date()) & (hhmm >= "09:30") & (hhmm < "16:00")]


def today_fill(order, reg=None):
    """오늘 장에서 매수 지정가가 이미 체결된 것으로 보이면 실제 체결가 기준 가격을 돌려준다.

    시가가 매수 지정가보다 낮게 시작하면 지정가가 아니라 시가에 체결된다(run()과 같은 규칙).
    장 마감(16:15) 뒤에는 일봉 기록에 반영되므로 None.
    """
    now_ny = pd.Timestamp.now(tz="America/New_York")
    if not order or order["skip"] or now_ny.strftime("%H:%M") >= "16:15":
        return None
    if reg is None:
        reg = _minutes()[1]
    if reg is None or reg.empty or float(reg["Low"].min()) > order["limit"]:
        return None
    opened = float(reg["Open"].iloc[0])
    fill = min(opened, order["limit"])
    return dict(fill=round(fill, 2), target=round(fill + M * order["atr"], 2), stop=round(fill - S * order["atr"], 2),
                open=round(opened, 2), limit=order["limit"], gapped=opened < order["limit"],
                below_floor=opened < order["floor"],
                date=reg.index[0].date())


def live_status(open_pos, order):
    """분봉으로 지금 가격을 받아, 어제 종가로 정해 둔 가격(매수가·익절가·손절가)과 비교한다.

    가격 규칙은 건드리지 않고 '지금 어디쯤인지'만 알려 준다. 못 받으면 None.
    """
    m, reg = _minutes()
    if m is None:
        return None
    now_ny = pd.Timestamp.now(tz="America/New_York")
    in_session = (now_ny.weekday() < 5 and "09:30" <= now_ny.strftime("%H:%M") < "16:00" and not reg.empty)
    price = float(m["Close"].iloc[-1])
    lines = []
    if not in_session:
        lines.append("지금은 미국 정규장이 아니에요 (정규장은 뉴욕 09:30~16:00). 아래 가격은 장 전·후 거래 가격일 수 있어요.")

    lo = float(reg["Low"].min()) if not reg.empty else None
    hi = float(reg["High"].max()) if not reg.empty else None
    if open_pos:
        p = open_pos
        lines.append(f"보유 중: 체결가 {p['entry']} 대비 지금 {price / p['entry'] - 1:+.1%}")
        lines.append(f"익절가까지 {p['target'] / price - 1:+.1%} · 손절가까지 {p['stop'] / price - 1:+.1%}")
        if lo is not None:
            hit_stop, hit_target = lo <= p["stop"], hi >= p["target"]
            if hit_stop and hit_target:
                lines.append("오늘 익절가와 손절가에 모두 닿아, 규칙상 손절되었을 것으로 보입니다.")
            elif hit_stop:
                lines.append(f"오늘 저가 {lo:.2f}가 손절가에 닿아, 손절되었을 것으로 보입니다.")
            elif hit_target:
                lines.append(f"오늘 고가 {hi:.2f}가 익절가에 닿아, 익절되었을 것으로 보입니다.")
            else:
                lines.append(f"오늘 저가 {lo:.2f} · 고가 {hi:.2f}: 익절가와 손절가 둘 다 아직 안 닿았어요")
    elif order["skip"]:
        lines.append("오늘은 매수 쉬는 날이에요 (어제 종가가 200일 평균 아래)")
    else:
        fill = today_fill(order, reg)
        if fill:
            lines.append(f"{fill['fill']}에 매수가 체결되었을 것으로 보입니다. 체결가 대비 지금 {price / fill['fill'] - 1:+.1%}")
            lines.append(f"익절가까지 {fill['target'] / price - 1:+.1%} · 손절가까지 {fill['stop'] / price - 1:+.1%}")
            if lo <= fill["stop"]:
                lines.append(f"오늘 저가 {lo:.2f}가 손절가에 닿아, 손절되었을 것으로 보입니다.")
        else:
            gap = price / order["limit"] - 1
            where = f"{gap:.1%} 위" if gap > 0 else f"{-gap:.1%} 아래"
            lines.append(f"현재가가 매수 상한가 {order['limit']}보다 {where}에 있어요")
            if lo is not None:
                lines.append(f"오늘 저가 {lo:.2f}: 아직 체결되지 않았을 것으로 보입니다.")
    fetched = pd.Timestamp.now(tz="Asia/Seoul").strftime("%m/%d %H:%M:%S")
    return dict(price=round(price, 2), fetched=fetched, in_session=in_session, lines=lines, error=False,
                fill=None if open_pos else today_fill(order, reg))


def next_session(day):
    """기준일 다음 평일 (미국 휴장일은 따지지 않음)."""
    day = pd.Timestamp(day) + pd.Timedelta(days=1)
    while day.weekday() >= 5:
        day += pd.Timedelta(days=1)
    return day.date()


def history(df, trades, open_pos, start=START):
    """START부터 다음 거래일까지, 날마다 규칙이 내놓은 가격을 다시 계산해 돌려준다 (매일 기록용).

    프로그램을 안 켠 날도 빠지지 않도록 저장해 둔 값이 아니라 가격 데이터로 매번 다시 계산한다.
    """
    c = df["Close"].values
    a, ma = atr(df).values, df["Close"].rolling(TREND).mean().values
    dates, n = df.index, len(df)
    q = gap_q(df)
    spans = [(t["entry_date"], t["exit_date"]) for t in trades]
    if open_pos:
        spans.append((open_pos["entry_date"], None))
    rows = []
    for i in range(int(np.searchsorted(dates, pd.Timestamp(start))), n + 1):
        day = dates[i].date() if i < n else next_session(dates[-1])
        j = i - 1
        if any(s < day and (e is None or day <= e) for s, e in spans):  # 산 다음 날부터 판 날까지
            rows.append(dict(date=day, status="보유 중"))
        elif np.isnan(a[j]) or np.isnan(ma[j]) or c[j] <= ma[j]:
            rows.append(dict(date=day, status="매수 쉼"))
        else:
            limit = c[j] - K * a[j]
            rows.append(dict(date=day, status="주문", limit=round(limit, 2), floor=round(limit - FLOOR_ATR * a[j], 2),
                             range_low=round(limit * (1 + q), 2),
                             target=round(limit + M * a[j], 2), stop=round(limit - S * a[j], 2)))
    return rows


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
        print(f"[다음 거래일 주문] 매수 상한가(지정가) {order['limit']} · 보통 체결되는 범위 {order['limit']} ~ {order['range_low']} · "
              f"매수 하한가(참고) {order['floor']}{qty}")
        print(f"    체결되면 → 익절가 {order['target']} / 손절가 {order['stop']} · 최대 {H}거래일 보유")
    s = stats(trades)
    print(f"[기록] 완료 {s['count']}건 · 이익 {s['wins']}건 · 승률 {s['win_rate']:.0%} · 누적 {s['total']:+.1%}")
    for t in trades[-10:]:
        print(f"    {t['entry_date']} {t['entry']} → {t['exit_date']} {t['exit']} {t['reason']} {t['ret']:+.1%}")


if __name__ == "__main__":
    df = load_ohlc()
    print_paper(*run(df), fx=usdkrw())
