"""
매매일지 (매매일지.csv)

날마다 규칙이 내놓은 가격(매수 상한가, 보통 체결 범위, 매수 하한가, 익절가, 손절가)과 연습 기록 결과를 한 줄씩 쌓는다.
'실제 체결가', '실제 수량', '실제 매도가', '메모' 칸은 사용자가 엑셀에서 직접 적는 칸이라, 다시 실행해도 지우지 않는다.
"""

import csv
from pathlib import Path

FILE = "매매일지.csv"
AUTO = ["날짜(미국장)", "상태", "매수 상한가", "보통 체결 범위 아래쪽", "매수 하한가(참고)", "익절가", "손절가",
        "연습 체결가", "연습 익절가", "연습 손절가", "연습 매도일", "연습 매도가", "연습 결과"]
MINE = ["실제 체결가", "실제 수량", "실제 매도가", "메모"]   # 사용자가 직접 적는 칸
COLS = AUTO + MINE


def update(path, rows, trades, open_pos):
    """매매일지를 새로 계산한 값으로 갱신하고 전체 줄을 돌려준다.

    rows: paper.history() 결과. 파일이 엑셀에 열려 있어 못 쓰면 None.
    """
    path = Path(path)
    old = {}
    if path.exists():
        with path.open(encoding="utf-8-sig", newline="") as f:
            old = {r.get(COLS[0], ""): r for r in csv.DictReader(f)}

    done = {t["entry_date"]: t for t in trades}
    out = []
    for r in rows:
        key = str(r["date"])
        line = dict.fromkeys(COLS, "")
        if key in old:
            line.update({k: old[key].get(k) or "" for k in MINE})
        line[COLS[0]], line["상태"] = key, r["status"]
        if r["status"] == "주문":
            line.update({"매수 상한가": r["limit"], "보통 체결 범위 아래쪽": r["range_low"],
                         "매수 하한가(참고)": r["floor"], "익절가": r["target"], "손절가": r["stop"]})
            t = done.get(r["date"])
            p = open_pos if open_pos and open_pos["entry_date"] == r["date"] else None
            if t or p:   # 그날 체결된 것으로 기록된 경우: 실제 체결가 기준 익절·손절가
                entry = (t or p)["entry"]
                shift = entry - r["limit"]
                line.update({"상태": "체결", "연습 체결가": entry, "연습 익절가": round(r["target"] + shift, 2),
                             "연습 손절가": round(r["stop"] + shift, 2)})
            if t:
                line.update({"연습 매도일": t["exit_date"], "연습 매도가": t["exit"],
                             "연습 결과": f'{t["reason"]} {t["ret"]:+.1%}'})
        out.append(line)
    # 새 계산에 없는 옛 줄도 버리지 않는다
    keys = {l[COLS[0]] for l in out}
    out += [dict.fromkeys(COLS, "") | {k: v for k, v in r.items() if k in COLS} for k, r in old.items() if k not in keys]
    out.sort(key=lambda l: l[COLS[0]])
    try:
        with path.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=COLS)
            w.writeheader()
            w.writerows(out)
    except PermissionError:
        return None
    return out


def _num(x):
    try:
        return float(str(x).replace(",", ""))
    except ValueError:
        return None


def compare(log):
    """실제 체결가를 적은 날만 골라 '규칙대로 했을 때 vs 실제'를 돌려준다."""
    out = []
    for r in log or []:
        mine, rule = _num(r["실제 체결가"]), _num(r["연습 체결가"])
        if mine is None:
            continue
        row = dict(date=r[COLS[0]], rule=rule, mine=mine, diff=(mine / rule - 1) if rule else None, rule_ret=None, mine_ret=None)
        sold, rule_sold = _num(r["실제 매도가"]), _num(r["연습 매도가"])
        if sold is not None:
            row["mine_ret"] = sold / mine - 1
        if rule and rule_sold is not None:
            row["rule_ret"] = rule_sold / rule - 1
        out.append(row)
    return out
