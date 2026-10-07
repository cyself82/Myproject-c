"""
SOXL 매매 신호 + 백테스트 프로그램
=================================

사용법 (내 PC에서):
    pip install yfinance pandas
    python soxl_signal.py              # 백테스트 결과 + 오늘의 신호
    python soxl_signal.py --signal     # 오늘의 신호만
    python soxl_signal.py --csv SOXL.csv --csv-soxx SOXX.csv   # 인터넷 대신 CSV 파일 사용

주의: SOXL은 반도체 지수(SOX)의 하루 수익률을 3배로 따라가는 레버리지 ETF입니다.
고점 대비 -90% 가까이 떨어진 적도 있습니다. 이 코드는 공부용이며 투자 조언이 아닙니다.
"""

import argparse
import sys

import numpy as np
import pandas as pd

# ---------------------------------------------------------------- 설정값
FEE = 0.001          # 한 번 사고팔 때마다 드는 비용(수수료+슬리피지) 0.1%
STOP_LOSS = 0.20     # 산 가격보다 20% 빠지면 손절
TRADING_DAYS = 252


# ---------------------------------------------------------------- 데이터
def load_prices(ticker, csv_path=None):
    """종가(수정주가) 시리즈를 돌려준다. CSV가 있으면 CSV, 없으면 Yahoo Finance."""
    if csv_path:
        df = pd.read_csv(csv_path, index_col=0, parse_dates=True)
        col = "Adj Close" if "Adj Close" in df.columns else "Close"
        return df[col].dropna().astype(float).rename(ticker)

    import yfinance as yf
    df = yf.download(ticker, period="max", auto_adjust=True, progress=False)
    if df.empty:
        sys.exit(f"{ticker} 데이터를 받지 못했습니다. 인터넷 연결을 확인하세요.")
    close = df["Close"]
    if isinstance(close, pd.DataFrame):  # yfinance 신버전은 열이 2단으로 나옴
        close = close.iloc[:, 0]
    return close.dropna().astype(float).rename(ticker)


# ---------------------------------------------------------------- 지표
def sma(s, n):
    return s.rolling(n).mean()


def rsi(s, n=14):
    diff = s.diff()
    up = diff.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    down = (-diff.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / down)


# ---------------------------------------------------------------- 전략
# 각 전략은 "그날 장 마감 기준으로 들고 있어야 하나?"를 True/False로 만든다.
# entry: 사도 되는 조건, exit: 팔아야 하는 조건

def strategy_rules(soxl, soxx):
    ma200_soxx = sma(soxx, 200)
    r = rsi(soxl, 14)
    return {
        "SOXL 200일선": dict(
            entry=soxl > sma(soxl, 200),
            exit=soxl < sma(soxl, 200),
            desc="SOXL 종가가 200일 평균 위면 보유, 아래면 현금"),
        "SOXX 200일선": dict(
            entry=soxx > ma200_soxx,
            exit=soxx < ma200_soxx,
            desc="1배 반도체 ETF(SOXX)가 200일 평균 위면 SOXL 보유"),
        "골든/데드크로스 50·200 (기본)": dict(
            entry=sma(soxl, 50) > sma(soxl, 200),
            exit=sma(soxl, 50) < sma(soxl, 200),
            desc="50일 평균이 200일 평균 위로 가면 매수, 아래로 가면 매도"),
        "RSI 역추세 30/70": dict(
            entry=r < 30,
            exit=r > 70,
            desc="RSI 30 아래(과매도)에서 매수, 70 위(과매수)에서 매도"),
    }


def run_positions(close, entry, exit_, stop_loss=STOP_LOSS):
    """매일의 보유 여부를 계산. 손절이 나면 진입 조건이 한 번 꺼졌다 다시 켜질 때까지 쉰다."""
    pos = np.zeros(len(close), dtype=bool)
    holding, entry_px, wait_reset = False, 0.0, False
    c, en, ex = close.values, entry.fillna(False).values, exit_.fillna(False).values
    for i in range(len(c)):
        if holding:
            if ex[i]:
                holding = False
            elif stop_loss and c[i] <= entry_px * (1 - stop_loss):
                holding, wait_reset = False, True
        else:
            if wait_reset and not en[i]:
                wait_reset = False
            if en[i] and not wait_reset:
                holding, entry_px = True, c[i]
        pos[i] = holding
    return pd.Series(pos, index=close.index)


def backtest(close, pos):
    """오늘 신호 → 내일 수익률에 적용 (미래를 미리 보지 않도록 하루 밀어줌)."""
    ret = close.pct_change().fillna(0)
    held = pos.shift(1, fill_value=False).astype(float)
    trades = held.diff().abs().fillna(held.iloc[0])
    strat = held * ret - trades * FEE
    return (1 + strat).cumprod(), int(trades.sum())


def stats(equity, n_trades, pos=None):
    years = len(equity) / TRADING_DAYS
    daily = equity.pct_change().dropna()
    cagr = equity.iloc[-1] ** (1 / years) - 1
    mdd = (equity / equity.cummax() - 1).min()
    sharpe = daily.mean() / daily.std() * np.sqrt(TRADING_DAYS) if daily.std() > 0 else 0
    return {
        "최종(1원→)": round(equity.iloc[-1], 2),
        "연평균수익률": f"{cagr:.1%}",
        "최대낙폭(MDD)": f"{mdd:.1%}",
        "샤프": round(sharpe, 2),
        "매매횟수": n_trades,
        "보유비중": f"{pos.mean():.0%}" if pos is not None else "100%",
    }


# ---------------------------------------------------------------- 실행
def main():
    p = argparse.ArgumentParser()
    p.add_argument("--signal", action="store_true", help="오늘의 신호만 출력")
    p.add_argument("--csv", help="SOXL 가격 CSV 경로(선택)")
    p.add_argument("--csv-soxx", help="SOXX 가격 CSV 경로(선택)")
    p.add_argument("--start", default=None, help="백테스트 시작일 예: 2015-01-01")
    p.add_argument("--stop", type=float, default=STOP_LOSS, help="손절 비율, 0이면 손절 없음")
    p.add_argument("--plot", action="store_true", help="수익 곡선 그림 저장(matplotlib 필요)")
    p.add_argument("--report", action="store_true", help="결과를 HTML 페이지로 만들어 브라우저로 열기")
    p.add_argument("--no-open", action="store_true", help="리포트 파일만 만들고 창은 열지 않기 (자동 실행용)")
    p.add_argument("--live", action="store_true", help="장중에 60초마다 지금 가격을 받아 리포트를 다시 쓰기")
    p.add_argument("--live-ticks", type=int, default=0, help="--live 를 몇 번만 갱신하고 끝내기 (점검용, 0이면 장 마감까지)")
    p.add_argument("--buy-price", type=float, default=None, help="내가 실제로 산 평균 가격(달러). 넣으면 내 손절 가격도 계산")
    a = p.parse_args()
    if a.live:
        a.report = True
    if a.report:
        a.signal = False  # 리포트에는 백테스트 표와 곡선이 필요

    soxl = load_prices("SOXL", a.csv)
    soxx = load_prices("SOXX", a.csv_soxx)
    df = pd.concat([soxl, soxx], axis=1, join="inner").dropna()
    note = ""
    if not a.csv:
        # 미국장이 아직 안 끝났으면 오늘 줄은 장중 가격이라 빼고, 확정된 전날 종가로 판단
        now_ny = pd.Timestamp.now(tz="America/New_York")
        if df.index[-1].date() == now_ny.date() and now_ny.time() < pd.Timestamp("16:15").time():
            df = df.iloc[:-1]
            note = f"(미국장 진행 중이라 {now_ny.date()} 장중 가격은 빼고 계산합니다)"
            print(note)
    soxl, soxx = df["SOXL"], df["SOXX"]

    rules = strategy_rules(soxl, soxx)
    positions = {k: run_positions(soxl, v["entry"], v["exit"], a.stop) for k, v in rules.items()}

    if not a.signal:
        start = a.start or soxl.index[200]  # 200일선 계산이 끝난 뒤부터 비교
        c = soxl[start:]
        print(f"\n=== 백테스트 {c.index[0].date()} ~ {c.index[-1].date()}  "
              f"(수수료 {FEE:.1%}, 손절 {a.stop:.0%}) ===")
        rows, curves = {}, {}
        bh = c / c.iloc[0]
        rows["그냥 사서 보유"] = stats(bh, 1)
        curves["그냥 사서 보유"] = bh
        for k, pos in positions.items():
            eq, n = backtest(c, pos[start:])
            rows[k] = stats(eq, n, pos[start:])
            curves[k] = eq
        print(pd.DataFrame(rows).T.to_string())

        if a.plot:
            import matplotlib.pyplot as plt
            from matplotlib import font_manager
            installed = {f.name for f in font_manager.fontManager.ttflist}
            for name in ["Malgun Gothic", "AppleGothic", "NanumGothic"]:  # 설치된 한글 글꼴 하나만 사용
                if name in installed:
                    plt.rcParams["font.family"] = name
                    break
            plt.rcParams["axes.unicode_minus"] = False  # 한글 글꼴에서 마이너스 기호 깨짐 방지
            pd.DataFrame(curves).plot(logy=True, figsize=(10, 5), title="SOXL 전략별 수익 곡선 (로그)")
            plt.savefig("soxl_backtest.png", dpi=120, bbox_inches="tight")
            print("그림 저장: soxl_backtest.png")

    # ---- 오늘의 신호
    last = soxl.index[-1].date()
    print(f"\n=== 오늘의 신호 ({last} 종가 기준) ===")
    print(f"SOXL {soxl.iloc[-1]:.2f}  /  200일선 {sma(soxl,200).iloc[-1]:.2f}  /  RSI {rsi(soxl).iloc[-1]:.0f}")
    print(f"SOXX {soxx.iloc[-1]:.2f}  /  200일선 {sma(soxx,200).iloc[-1]:.2f}")
    signals = []
    for k, pos in positions.items():
        now, prev = pos.iloc[-1], pos.iloc[-2]
        if now and not prev:
            state, msg = "buy", "🟢 매수 신호 (오늘 새로 진입)"
        elif prev and not now:
            state, msg = "sell", "🔴 매도 신호 (오늘 청산)"
        elif now:
            state, msg = "hold", "보유 유지"
        else:
            state, msg = "cash", "현금 대기"
        signals.append((k, state))
        print(f"- {k:<22} {msg}")
    print("\n※ 공부용 참고 신호이며 투자 조언이 아닙니다. SOXL은 3배 레버리지라 손실이 매우 클 수 있습니다.")

    # ---- 기본 전략이 정한 가격 기준 (매수·매도 신호가 바뀌는 지점)
    d_name = next((k for k in positions if "(기본)" in k), list(positions)[0])
    d_pos = positions[d_name]
    px, ma50, ma200 = soxl.iloc[-1], sma(soxl, 50).iloc[-1], sma(soxl, 200).iloc[-1]
    plan = [("50일선 / 200일선", f"{ma50:.2f} / {ma200:.2f}",
             f"간격 {ma50 / ma200 - 1:+.1%}. 50일선이 200일선 아래로 내려가면 매도, 위로 올라가면 매수 신호")]
    # 다음 거래일 종가가 얼마면 50일선과 200일선의 위아래가 바뀌는지 (두 평균이 같아지는 종가)
    v = soxl.values
    flip = (v[-199:].sum() / 200 - v[-49:].sum() / 50) / (1 / 50 - 1 / 200)
    side = "아래로 마감하면 매도" if ma50 > ma200 else "위로 마감하면 매수"
    if flip > 0:
        plan.append(("신호가 바뀌는 종가", f"{flip:.2f}",
                     f"다음 거래일 종가가 이 가격 {side} 쪽으로 선이 뒤집힙니다. 현재가 대비 {flip / px - 1:+.1%}"))
    else:
        plan.append(("신호가 바뀌는 종가", "하루로는 불가",
                     "두 평균선의 간격이 커서 다음 거래일 하루 종가만으로는 선이 뒤집히지 않습니다"))
    if d_pos.iloc[-1]:
        turned = d_pos & ~d_pos.shift(1, fill_value=False)
        entry_day = turned[turned].index[-1]
        entry_px = soxl[entry_day]
        plan.insert(0, ("규칙상 진입", f"{entry_day.date()} · {entry_px:.2f}",
                        "이 규칙이 마지막으로 매수 신호를 낸 날과 그날 종가 (내 실제 매수가와 다를 수 있음)"))
        if a.stop:
            stop_px = entry_px * (1 - a.stop)
            plan.append(("규칙상 손절 가격", f"{stop_px:.2f}",
                         f"종가가 이 가격 이하면 매도 신호. 현재가 대비 {stop_px / px - 1:+.1%}"))
    else:
        plan.append(("매수 조건", "아직 아님", "50일선이 200일선 위에 있고, 직전 손절 뒤라면 한 번 내려갔다 다시 올라와야 매수 신호"))
    if a.buy_price and a.stop:
        my_stop = a.buy_price * (1 - a.stop)
        plan.append(("내 손절 가격", f"{my_stop:.2f}",
                     f"내 매수가 {a.buy_price:.2f} 기준 -{a.stop:.0%}. 현재가 대비 {my_stop / px - 1:+.1%}, "
                     f"현재 수익률 {px / a.buy_price - 1:+.1%}"))
    plan.append(("추가 매수", "기준 없음", "이 규칙은 '전부 보유' 아니면 '전부 현금'만 정합니다. 나눠 사는 금액·가격은 규칙에 없습니다"))
    plan.append(("확인 시점", "미국장 마감 후", "신호는 하루 한 번, 종가로만 바뀝니다. 한국 시간 아침에 확인하고 바뀐 날에만 다음 장에서 매매"))

    print(f"\n=== 기본 전략({d_name})이 정한 가격 ===")
    for label, value, desc in plan:
        print(f"- {label}: {value}  ({desc})")

    # ---- 단기 규칙 모의 매매 (실제 돈 없이 기록)
    import paper
    pdf = paper.load_ohlc()
    ptr, ppos, pord, plast = paper.run(pdf)
    fx = paper.usdkrw()
    paper.print_paper(ptr, ppos, pord, plast, fx)

    # ---- 매매일지: 규칙이 내놓은 가격을 날마다 한 줄씩. '실제 체결가' 같은 칸은 사용자가 직접 적는다
    import journal
    from pathlib import Path
    log_path = Path(__file__).with_name(journal.FILE)
    log = journal.update(log_path, paper.history(pdf, ptr, ppos), ptr, ppos)
    print(f"매매일지: {log_path}" if log is not None else "매매일지가 엑셀에 열려 있어 갱신 못 했어요 (엑셀을 닫고 다시 실행).")

    if a.report:
        import webbrowser
        from pathlib import Path

        import report
        prices = {
            "SOXL": f"{soxl.iloc[-1]:.2f}",
            "SOXL 200일선": f"{sma(soxl, 200).iloc[-1]:.2f}",
            "RSI": f"{rsi(soxl).iloc[-1]:.0f}",
            "SOXX": f"{soxx.iloc[-1]:.2f}",
            "SOXX 200일선": f"{sma(soxx, 200).iloc[-1]:.2f}",
        }
        period = f"{c.index[0].date()} ~ {c.index[-1].date()} · 수수료 {FEE:.1%} · 손절 {a.stop:.0%}"
        def write(live=None, refresh=None):
            # 오늘 장에서 이미 체결된 것으로 보이면 주문 카드를 실제 체결가 기준으로 바꾼다
            if live and "fill" in live:
                fill = live["fill"]
            else:
                fill = None if ppos else paper.today_fill(pord)
            return report.build(Path(__file__).with_name("soxl_report.html"), last, prices,
                                signals, rows, curves, period, note, plan,
                                paper_data=(ptr, ppos, pord, plast, fx), live=live, refresh=refresh, fill=fill,
                                log=log)

        live = paper.live_status(ppos, pord) if a.live else None
        if a.live and live is None:
            live = dict(price=None, error=True)
        path = write(live, 60 if a.live else None)
        print(f"리포트 저장: {path}")
        # 주소창·탭 없는 창(앱 모드)으로 열기. Edge나 Chrome이 없으면 기본 브라우저로 연다.
        import os
        import subprocess
        roots = [os.environ.get(v, "") for v in ("ProgramFiles(x86)", "ProgramFiles", "LocalAppData")]
        apps = [Path(r) / sub for sub in (r"Google\Chrome\Application\chrome.exe",
                                          r"Microsoft\Edge\Application\msedge.exe") for r in roots if r]
        exe = next((x for x in apps if x.exists()), None)
        if a.no_open:
            pass
        elif exe:
            subprocess.Popen([str(exe), f"--app={path.as_uri()}", "--window-size=980,1100"])
        else:
            webbrowser.open(path.as_uri())

        if a.live:
            # 창은 위에서 한 번만 열고, 파일만 60초마다 다시 쓴다 (페이지가 스스로 새로고침).
            import time
            print("실시간 갱신 중입니다. 뉴욕 16:05 이후 자동으로 끝나고, Ctrl+C 로 바로 끝낼 수 있습니다.", flush=True)
            ticks = 0
            try:
                while True:
                    now_ny = pd.Timestamp.now(tz="America/New_York")
                    if now_ny.strftime("%H:%M") >= "16:05" or (a.live_ticks and ticks >= a.live_ticks):
                        break
                    time.sleep(60 if not a.live_ticks else 5)
                    new = paper.live_status(ppos, pord)
                    live = new if new else dict(live, error=True)  # 못 받으면 이전 숫자 유지
                    write(live, 60)
                    ticks += 1
            except KeyboardInterrupt:
                pass
            write(dict(live, ended=True))
            print("실시간 갱신을 끝냈습니다.")


if __name__ == "__main__":
    main()
