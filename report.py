"""
SOXL 신호/백테스트 결과를 HTML 한 페이지로 만든다. (표준 라이브러리만 사용)
soxl_signal.py --report 에서 불러 쓴다.
"""

import datetime
import html
import math
from pathlib import Path

# ---------------------------------------------------------------- 표시용 설정
STATE = {  # 상태: (큰 글씨, 설명, 색)
    "buy": ("매수 신호", "오늘 새로 진입", "#12a36d"),
    "sell": ("매도 신호", "오늘 청산", "#d0453a"),
    "hold": ("보유 유지", "이미 갖고 있다면 계속 보유", "#2f6fd0"),
    "cash": ("현금 대기", "사지 않고 기다림", "#8a94a6"),
}
LINE_COLORS = ["#8a94a6", "#e08a1e", "#12a36d", "#d0453a", "#7a5cd6", "#2f6fd0"]
DISCLAIMER = "공부용 참고 신호이며 투자 조언이 아닙니다. SOXL은 3배 레버리지라 손실이 매우 클 수 있습니다."

CSS = """
:root { --bg:#f1f3f6; --card:#ffffff; --text:#1c2330; --sub:#667085; --line:#e3e7ee; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#14171c; --card:#1e232b; --text:#e8ebf0; --sub:#98a2b3; --line:#2e3540; }
}
* { box-sizing:border-box; }
body { margin:0; padding:24px 16px 40px; background:var(--bg); color:var(--text);
       font-family:"Malgun Gothic","맑은 고딕","Apple SD Gothic Neo",sans-serif; line-height:1.5; }
.wrap { max-width:880px; margin:0 auto; }
.card { background:var(--card); border-radius:14px; padding:20px 22px; margin-bottom:16px;
        box-shadow:0 1px 3px rgba(0,0,0,.06); }
h2 { font-size:16px; margin:0 0 12px; }
.small { font-size:13px; color:var(--sub); }
.hero { border-left:8px solid var(--c); }
.hero .state { font-size:40px; font-weight:800; color:var(--c); margin:4px 0 0; }
.hero .desc { font-size:15px; color:var(--sub); margin-bottom:16px; }
.prices { display:flex; flex-wrap:wrap; gap:10px 28px; border-top:1px solid var(--line); padding-top:14px; }
.prices div span { display:block; font-size:12px; color:var(--sub); }
.prices div b { font-size:18px; }
.grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr)); gap:12px; margin-bottom:16px; }
.grid .card { margin:0; padding:14px 16px; border-top:5px solid var(--c); }
.grid .name { font-size:13px; color:var(--sub); }
.grid .state { font-size:18px; font-weight:700; color:var(--c); }
.grid .desc { font-size:12px; color:var(--sub); }
svg { width:100%; height:auto; display:block; }
svg text { fill:var(--sub); font-size:12px; font-family:inherit; }
svg .gridline { stroke:var(--line); stroke-width:1; }
.legend { display:flex; flex-wrap:wrap; gap:6px 18px; margin-top:10px; font-size:13px; }
.legend i { display:inline-block; width:18px; height:4px; border-radius:2px; vertical-align:middle; margin-right:6px; }
.scroll { overflow-x:auto; }
table { border-collapse:collapse; width:100%; font-size:14px; white-space:nowrap; }
th, td { padding:8px 10px; border-bottom:1px solid var(--line); text-align:right; }
th:first-child, td:first-child { text-align:left; }
th { font-size:12px; color:var(--sub); font-weight:600; }
tr.default td { font-weight:700; }
.paper .nums { display:flex; flex-wrap:wrap; gap:10px 36px; margin:12px 0 6px; }
.paper .nums span { display:block; font-size:12px; color:var(--sub); }
.paper .nums b { font-size:30px; }
.paper .line { margin:10px 0 6px; }
.paper .rule { border-top:1px solid var(--line); margin-top:12px; padding-top:10px; }
table.plan { white-space:normal; }
table.plan td { text-align:left; vertical-align:top; }
table.plan td:first-child { white-space:nowrap; color:var(--sub); }
table.plan td.val { white-space:nowrap; font-weight:700; font-size:16px; }
table.plan td.why { font-size:13px; color:var(--sub); }
.help { font-size:13px; color:var(--sub); margin:-6px 0 12px; }
.sec { font-size:14px; font-weight:700; margin:22px 6px 4px; }
.sec + .help { margin:0 6px 10px; }
.order { border-left:8px solid var(--c); }
.order h1 { font-size:22px; margin:0 0 2px; }
.order .nums { display:flex; flex-wrap:wrap; gap:10px 44px; margin:14px 0 8px; }
.order .nums span { display:block; font-size:13px; color:var(--sub); }
.order .nums b { font-size:40px; line-height:1.15; }
.order .big { font-size:34px; font-weight:800; color:var(--c); margin:10px 0 4px; }
.order .line { margin:8px 0 0; }
table.howto td.val { white-space:normal; font-size:14px; }
ul.checks { margin:0; padding-left:20px; font-size:14px; }
ul.checks li { margin-bottom:6px; }
.record { font-size:14px; padding:0 8px; margin:-4px 0 16px; }
details.more { margin-top:8px; }
details.more > summary { cursor:pointer; font-weight:700; padding:14px 8px; }
.foot { font-size:13px; color:var(--sub); padding:4px 6px; }
"""


def _is_default(name):
    return "(기본)" in name


def _chart(curves):
    """수익 곡선을 로그 눈금 SVG로 그린다. curves: {이름: 날짜 인덱스를 가진 시리즈}"""
    W, H, L, R, T, B = 840, 380, 58, 16, 14, 30
    data = {k: ([float(v) for v in s.values], list(s.index)) for k, s in curves.items()}
    vals = [v for ys, _ in data.values() for v in ys if v > 0]
    lo, hi = math.floor(math.log10(min(vals))), math.ceil(math.log10(max(vals)))
    if hi == lo:
        hi += 1
    n = max(len(ys) for ys, _ in data.values())

    def px(i):
        return L + (W - L - R) * i / max(n - 1, 1)

    def py(v):
        return T + (H - T - B) * (hi - math.log10(v)) / (hi - lo)

    out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="전략별 수익 곡선">']
    for k in range(lo, hi + 1):  # 10배 단위 가로줄
        y = py(10 ** k)
        out.append(f'<line class="gridline" x1="{L}" x2="{W - R}" y1="{y:.1f}" y2="{y:.1f}"/>')
        out.append(f'<text x="{L - 8}" y="{y + 4:.1f}" text-anchor="end">{10 ** k:g}배</text>')
    dates = max((d for _, d in data.values()), key=len)
    for j in range(5):  # 연도 눈금 5개
        i = round((n - 1) * j / 4)
        anchor = "start" if j == 0 else "end" if j == 4 else "middle"
        out.append(f'<text x="{px(i):.1f}" y="{H - 8}" text-anchor="{anchor}">{dates[i].year}</text>')

    step = max(1, n // 400)
    for idx, (name, (ys, _)) in enumerate(data.items()):
        picks = list(range(0, len(ys), step))
        if picks[-1] != len(ys) - 1:
            picks.append(len(ys) - 1)
        pts = " ".join(f"{px(i):.1f},{py(ys[i]):.1f}" for i in picks if ys[i] > 0)
        width = 3.2 if _is_default(name) else 1.4
        out.append(f'<polyline fill="none" stroke="{LINE_COLORS[idx % len(LINE_COLORS)]}" '
                   f'stroke-width="{width}" stroke-linejoin="round" points="{pts}"/>')
    out.append("</svg>")

    legend = "".join(
        f'<span><i style="background:{LINE_COLORS[i % len(LINE_COLORS)]}"></i>{html.escape(name)}</span>'
        for i, name in enumerate(data))
    return "\n".join(out) + f'\n<div class="legend">{legend}</div>'


PAPER_RULE = ("규칙: 종가가 200일선 위일 때만, 어제 종가 - 0.25×ATR에 매수, +2×ATR 익절, -3×ATR 손절, 최대 5일. "
              "2020년 이후 백테스트: 연 30회, 승률 58%, 평균 +1.9%/회, 최대낙폭 -59%. "
              "576개 조합 중 고른 규칙이라 우연일 수 있어 연습 기록으로 확인 중입니다.")


def _next_session(day):
    """기준일 다음 평일 (미국 휴장일은 따지지 않음)."""
    day += datetime.timedelta(days=1)
    while day.weekday() >= 5:
        day += datetime.timedelta(days=1)
    return day


def _order_card(paper_data, fill=None):
    """맨 위 카드: 단기 규칙이 계산한 다음 장의 매수·익절·손절 가격과 연습 기록 한 줄.

    fill: 오늘 장에서 이미 체결된 것으로 보일 때 paper.today_fill() 결과 (실제 체결가 기준 가격)
    """
    import paper
    e = html.escape
    trades, pos, order, last_date, fx = paper_data
    green, red, blue, grey = STATE["buy"][2], STATE["sell"][2], STATE["hold"][2], STATE["cash"][2]
    nxt = _next_session(last_date)

    def num(label, value, color):
        return f'<div><span>{label}</span><b style="color:{color}">{e(str(value))}</b></div>'

    if pos:
        color = blue
        inner = (f'<div class="big">연습 보유 중</div>'
                 f'<div class="line">{e(str(pos["entry_date"]))}에 {pos["entry"]}에 산 것으로 기록 · '
                 f'현재 {pos["last"]} ({pos["pnl"]:+.1%})</div>'
                 f'<div class="nums">{num("익절가", pos["target"], green)}{num("손절가", pos["stop"], red)}</div>'
                 f'<div class="small">남은 기한 {pos["days_left"]}거래일. 그때까지 둘 다 안 닿으면 종가에 팝니다.</div>')
    elif fill:
        color = blue
        how = (f'시가 {fill["open"]}가 매수 상한가 {fill["limit"]}보다 낮게 시작해, 시가에 체결' if fill["gapped"]
               else f'장중에 매수 상한가 {fill["limit"]}까지 내려와, 그 가격에 체결')
        if fill.get("below_floor"):
            how += f' (매수 하한가 {order["floor"]}보다도 낮게 시작한 드문 날)'
        inner = (f'<div class="nums">{num("체결가", fill["fill"], blue)}'
                 f'{num("익절가", fill["target"], green)}{num("손절가", fill["stop"], red)}</div>'
                 f'<div class="line small">{how} · 익절가와 손절가는 체결가 기준 · 최대 {paper.H}거래일 보유</div>')
    elif order["skip"]:
        color = grey
        inner = (f'<div class="big">오늘 밤은 매수 없음</div>'
                 f'<div class="line">종가 {order["close"]}가 200일 평균 {order["ma"]} 아래라서 쉬는 날입니다.</div>')
    else:
        color = blue
        qty = ""
        if fx:
            shares = paper.BUDGET_KRW / fx / order["limit"]
            qty = (f'<div class="line">{paper.BUDGET_KRW // 10000}만원이면 약 {shares:.2f}주 '
                   f'(1주 단위면 {int(shares)}주)</div>')
        inner = (f'<div class="nums">{num("매수 상한가", order["limit"], blue)}'
                 f'{num("보통 체결되는 범위", str(order["limit"]) + " ~ " + str(order["range_low"]), blue)}'
                 f'{num("매수 하한가 (참고)", order["floor"], grey)}'
                 f'{num("익절가", order["target"], green)}{num("손절가", order["stop"], red)}</div>'
                 f'{qty}'
                 f'<div class="line small">매수 상한가에 지정가로 걸어 둡니다. 그보다 싸게 시작하면 더 싼 시가에 체결됩니다. '
                 f'익절가와 손절가는 상한가에 체결됐을 때 기준이고, 더 싸게 체결되면 그만큼 함께 내려갑니다.</div>'
                 f'<div class="line small">보통 체결되는 범위: 과거에 시가가 상한가보다 낮게 열린 날의 90%가 이 범위 안이었어요.</div>'
                 f'<div class="line small">매수 하한가는 참고선입니다. 16년 동안 시가가 이보다 낮게 시작해 체결된 날은 7번뿐이었고, '
                 f'그 7번의 평균 결과는 -4.7%였습니다. 규칙은 그런 날에도 사는 것으로 계산합니다.</div>'
                 f'<div class="line small">체결된 뒤에는 익절가나 손절가에 닿을 때 팔고, '
                 f'{paper.H}거래일 안에 둘 다 안 닿으면 {paper.H}일째 종가에 팝니다.</div>')
    card = (f'<div class="card order" style="--c:{color}">'
            f'<h1>{"오늘 체결 후 가격" if (fill and not pos) else "오늘 밤 주문"} ({nxt.month}/{nxt.day:02d} 장)</h1>'
            f'<div class="small">{e(str(last_date))} 종가로 계산한 달러 가격 · 규칙이 계산한 값이며 추천이 아닙니다</div>'
            f'<div class="small">장 시작 전(한국 시간 밤 10시 30분, 겨울에는 11시 30분 전)에 미리 걸어 두는 가격입니다. '
            f'하루 동안 바뀌지 않으며, 장이 열린 뒤에 주문하면 연습 기록과 결과가 달라집니다.</div>'
            f'{inner}'
            f'<div class="line small">이 규칙의 과거 성적(2020년 이후): 승률 58%, 평균 +1.9%/회, 최대낙폭 -59%</div></div>')
    s = paper.stats(trades)
    start = datetime.date.fromisoformat(paper.START)
    record = (f'<div class="record">연습 기록 ({start.month}/{start.day}부터, 실제 돈 없이 이 가격대로 했다면): '
              f'완료 {s["count"]}건 · 승률 {s["win_rate"]:.0%} · 누적 {s["total"]:+.1%}</div>')
    return card + record


def _live_card(live):
    """지금 상황 (실시간) 카드. live = paper.live_status() 결과, 없으면 빈 문자열."""
    if not live:
        return ""
    e = html.escape
    warn = ('<div class="line" style="color:#d0453a">데이터를 못 받았어요, 다시 시도 중 (아래는 마지막으로 받은 숫자)</div>'
            if live.get("error") else "")
    ended = '<div class="line small">실시간 갱신이 끝났어요. 다시 보려면 run_soxl_live.bat을 실행하세요.</div>' if live.get("ended") else ""
    if live.get("price") is None:
        body = '<div class="line">아직 가격을 받지 못했어요.</div>'
    else:
        lines = "".join(f'<div class="line">{e(x)}</div>' for x in live["lines"])
        body = (f'<div class="nums"><div><span>SOXL 현재가 (달러)</span><b>{live["price"]}</b></div></div>'
                f'{lines}'
                f'<div class="line small">가져온 시각 {e(live["fetched"])} (한국 시간) · '
                f'야후 데이터라 몇 분에서 최대 15분쯤 늦을 수 있어요</div>')
    return (f'<div class="card order" style="--c:#e08a1e"><h1>지금 상황 (실시간)</h1>'
            f'<div class="small">가격 규칙은 그대로이고, 지금 가격이 어디쯤인지만 보여 줍니다</div>'
            f'{warn}{body}{ended}</div>')


HOWTO = [  # (할 일, 주문 종류, 설명)
    ("매수", "정규장 지정가 (당일, 예약주문 가능)", "매수 지정가에 걸어 둡니다. 가격이 거기까지 내려와야 체결됩니다."),
    ("익절", "지정가 매도", "매수가 체결된 뒤 익절가에 걸어 둡니다."),
    ("손절", "자동감시(스탑) 주문", "가격이 손절가까지 내려가면 매도 주문이 나가도록 걸어 둡니다."),
    ("5거래일째 정리", "장마감 시장가 또는 LOC 매도", "기한 마지막 날까지 익절·손절이 안 됐으면 그날 종가에 팝니다."),
]
CHECKS = [
    "개장 전(프리마켓) 가격이 손절가 아래이거나 익절가 위면, 규칙상 그날 시가에 정리한 것으로 봅니다.",
    "반도체 회사 실적 발표일, 미국 물가(CPI) 발표, 금리 결정(FOMC), 수출 규제 뉴스가 있는 날은 변동이 커서 손절가에 닿기 쉽습니다. "
    "이 규칙은 이런 일정을 반영하지 않으니 참고로만 보세요.",
]


def _howto_cards():
    e = html.escape
    rows = "".join(f'<tr><td>{e(a)}</td><td class="val">{e(b)}</td><td class="why">{e(c)}</td></tr>' for a, b, c in HOWTO)
    checks = "".join(f"<li>{e(x)}</li>" for x in CHECKS)
    return (f'<div class="card"><h2>주문 방법</h2>'
            f'<div class="help">나무증권 기준의 일반적인 표기입니다. 실제 메뉴 이름과 지원 여부는 앱에서 확인하세요.</div>'
            f'<div class="scroll"><table class="plan howto">{rows}</table></div>'
            f'<div class="help" style="margin:12px 0 0">장개시 시장가는 눌림 가격이 아니라 그날 시가에 무조건 사게 되어, 이 규칙과 달라집니다.</div></div>'
            f'<div class="card"><h2>오늘 점검할 일</h2><ul class="checks">{checks}</ul></div>')


def _log_card(log):
    """매일 기록 표 (최근 15줄). log = journal.update() 결과: 줄 목록, 못 썼으면 None, 기능을 안 쓰면 False."""
    if log is False:
        return ""
    import journal
    e = html.escape
    if log is None:
        return '<div class="card"><h2>매매일지</h2><div class="small">매매일지가 엑셀에 열려 있어 갱신 못 했어요</div></div>'
    cols = list(log[0].keys()) if log else []
    head = "".join(f"<th>{e(c)}</th>" for c in cols)
    rows = "".join("<tr>" + "".join(f"<td>{e(str(r[c]))}</td>" for c in cols) + "</tr>" for r in log[-15:])
    body = f'<div class="scroll"><table><tr>{head}</tr>{rows}</table></div>'

    cmp_html = ""
    cmp_rows = journal.compare(log)
    if cmp_rows:
        def pct(x):
            return f"{x:+.1%}" if x is not None else "-"
        trs = "".join(
            f'<tr><td>{e(r["date"])}</td><td>{r["rule"] if r["rule"] is not None else "기록 없음"}</td><td>{r["mine"]}</td>'
            f'<td>{pct(r["diff"])}</td><td>{pct(r["rule_ret"])}</td><td>{pct(r["mine_ret"])}</td></tr>'
            for r in cmp_rows[-10:])
        cmp_html = ('<h2 style="margin-top:18px">규칙대로 했을 때 vs 실제</h2>'
                    '<div class="scroll"><table><tr><th>날짜</th><th>규칙 체결가</th><th>실제 체결가</th>'
                    f'<th>차이</th><th>규칙 수익률</th><th>실제 수익률</th></tr>{trs}</table></div>'
                    '<div class="help" style="margin:8px 0 0">차이: 실제로 규칙보다 비싸게(+) 또는 싸게(-) 산 정도. '
                    '수익률은 매도가가 있는 경우에만 나오고, 수수료는 빼지 않은 값입니다.</div>')
    return (f'<div class="card"><h2>매매일지 (최근 15일)</h2>'
            f'<div class="help">파일 위치: 이 폴더의 {e(journal.FILE)} (엑셀로 열 수 있어요). 날마다 규칙이 내놓은 가격이 한 줄씩 쌓이고, '
            f'프로그램을 안 켠 날도 다음에 켤 때 채워집니다. "실제 체결가", "실제 수량", "실제 매도가", "메모" 칸은 직접 적는 칸이고 다시 실행해도 지워지지 않습니다.</div>'
            f'{body}{cmp_html}</div>')


def _paper_details(paper_data):
    """자세히 보기 안에 넣는 연습 기록 거래 내역과 규칙 설명."""
    e = html.escape
    trades = paper_data[0]
    if trades:
        body = "".join(
            f'<tr><td>{e(str(t["entry_date"]))}</td><td>{t["entry"]}</td><td>{e(str(t["exit_date"]))}</td>'
            f'<td>{t["exit"]}</td><td>{e(t["reason"])}</td><td>{t["ret"]:+.1%}</td></tr>'
            for t in trades[-10:])
        table = ('<div class="scroll"><table><tr><th>매수일</th><th>매수가</th><th>매도일</th><th>매도가</th>'
                 f'<th>사유</th><th>수익률</th></tr>{body}</table></div>')
    else:
        table = '<div class="small">아직 완료된 거래가 없습니다.</div>'
    return (f'<div class="card"><h2>연습 기록 거래 내역 (최근 10건)</h2>'
            f'<div class="help">프로그램은 실제 주문을 내지 않습니다. 맨 위 가격대로 주문했다면 어떻게 됐을지만 매일 적어 둡니다.</div>'
            f'{table}<div class="help" style="margin:12px 0 0">{e(PAPER_RULE)}</div></div>')


def build(path, last_date, prices, signals, rows, curves, period, note="", plan=None, paper_data=None,
          live=None, refresh=None, fill=None, log=False):
    """결과 페이지를 path에 쓰고, 그 경로(절대경로)를 돌려준다.

    prices: {이름: 값}, signals: [(전략 이름, buy/sell/hold/cash)],
    rows: {전략 이름: 통계 dict}, curves: {전략 이름: 수익 곡선 시리즈},
    plan: [(항목, 값, 설명)] 기본 전략이 정한 가격 기준 (없으면 생략),
    paper_data: paper.run() 결과와 환율 (없으면 맨 위 주문 카드 생략),
    live: paper.live_status() 결과 (있으면 맨 위에 '지금 상황' 카드), refresh: 자동 새로고침 간격(초)
    """
    e = html.escape
    d_name, d_state = next((s for s in signals if _is_default(s[0])), signals[0])
    title, desc, color = STATE[d_state]

    price_html = "".join(f"<div><span>{e(str(k))}</span><b>{e(str(v))}</b></div>" for k, v in prices.items())
    hero = (f'<div class="card hero" style="--c:{color}">'
            f'<div class="small">{e(str(last_date))} 종가 기준 · 기본 전략 {e(d_name)}</div>'
            f'<div class="state">{title}</div><div class="desc">{desc}</div>'
            f'<div class="help" style="margin:0 0 14px">장기 규칙(50일 평균과 200일 평균 비교)으로 본 지금 상태입니다. '
            f'몇 달에 한 번 바뀌는 큰 흐름 판정이고, 매일 사고파는 신호가 아닙니다. '
            f'아래 숫자에서 "200일선"은 최근 200거래일 종가의 평균, RSI는 0~100 사이 과열 정도(70 이상 과열, 30 이하 침체)입니다.</div>'
            f'<div class="prices">{price_html}</div></div>')

    trend_html = ""
    if "SOXL" in prices and "SOXL 200일선" in prices:
        px, ma = prices["SOXL"], prices["SOXL 200일선"]
        up = float(px) > float(ma)
        trend_html = (f'<div class="record">큰 흐름: <b>{"상승 (단기 매수 가능한 구간)" if up else "하락 (단기 매수 쉬는 구간)"}</b> '
                      f'<span class="small">종가 {e(str(px))} · 200일 평균 {e(str(ma))}</span></div>')

    plan_html = ""
    if plan:
        plan_rows = "".join(
            f'<tr><td>{e(label)}</td><td class="val">{e(value)}</td><td class="why">{e(why)}</td></tr>'
            for label, value, why in plan)
        plan_html = (f'<div class="card"><h2>기본 전략이 정한 가격 (언제 신호가 바뀌나)</h2>'
                     f'<div class="scroll"><table class="plan">{plan_rows}</table></div></div>')

    cards = "".join(
        f'<div class="card" style="--c:{STATE[st][2]}"><div class="name">{e(name)}</div>'
        f'<div class="state">{STATE[st][0]}</div><div class="desc">{STATE[st][1]}</div></div>'
        for name, st in signals)

    cols = list(next(iter(rows.values())).keys())
    head = "<tr><th>전략</th>" + "".join(f"<th>{e(str(c))}</th>" for c in cols) + "</tr>"
    body = "".join(
        f'<tr class="{"default" if _is_default(name) else ""}"><td>{e(name)}</td>'
        + "".join(f"<td>{e(str(r[c]))}</td>" for c in cols) + "</tr>"
        for name, r in rows.items())

    foot = (f"{e(note)}<br>" if note else "") + DISCLAIMER
    page = f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SOXL 매매 신호</title>
{f'<meta http-equiv="refresh" content="{int(refresh)}">' if refresh else ""}
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
{_live_card(live)}
{_order_card(paper_data, fill) if paper_data else hero}
{"" if paper_data else plan_html}
{trend_html if paper_data else ""}
{_howto_cards() if paper_data else ""}
{_log_card(log)}
<div class="card"><h2>전략별 수익 곡선 (로그 눈금, 1원이 몇 배가 됐는지)</h2>
{_chart(curves)}
</div>
<details class="more">
<summary>자세히 보기 (규칙 설명, 과거 성적, 거래 내역)</summary>
{_paper_details(paper_data) if paper_data else ""}
{hero if paper_data else ""}
{plan_html if paper_data else ""}
<div class="sec">비교용: 다른 규칙 4개의 현재 상태</div>
<div class="help">같은 가격을 서로 다른 규칙으로 판정한 결과입니다. "(기본)"이 장기 규칙이고, 나머지는 참고용입니다.</div>
<div class="grid">{cards}</div>
<div class="card"><h2>백테스트 {e(period)}</h2>
<div class="help">위 그래프를 숫자로 정리한 표입니다. 최종(1원→): 1원이 몇 원이 됐는지 · 연평균수익률: 1년에 평균 몇 % 불었는지 ·
최대낙폭: 가장 나빴을 때 고점 대비 얼마나 깨졌는지 · 샤프: 흔들림 대비 수익(클수록 좋음) · 매매횟수: 사고판 횟수 · 보유비중: 전체 기간 중 주식을 들고 있던 날의 비율</div>
<div class="scroll"><table>{head}{body}</table></div></div>
</details>
<div class="foot">{foot}</div>
</div>
</body>
</html>
"""
    path = Path(path).resolve()
    path.write_text(page, encoding="utf-8")
    return path
