#!/usr/bin/env python3
"""Build the trust list: which price series (or pieces of them) a backtest may use.

Writes:
  indexes/sp500_monthly.csv  month-end S&P 500 membership rebuilt from FMP change history
  indexes/trust.csv          one row per usable or rejected segment of each ticker

A ticker's series is cut into segments at gaps of more than GAP trading sessions
(ticker reuse). Trailing dead rows (no volume) are trimmed. A segment is rejected
when it is too short, has too many zero-volume days, or too many >50% one-day
moves not explained by a split. Stdlib only.
"""
import csv
import datetime as dt
import gzip
import json
import os
from collections import defaultdict

GAP = 20            # sessions; a longer hole means a different company reused the ticker
MIN_ROWS = 60
MAX_ZERO_VOL = 0.10  # share of zero-volume days
WILD_PER_1000 = 10   # >50% moves without a split, per 1000 rows


def norm(t):
    return t.strip().upper().replace(".", "-")


def load_gz(p):
    with gzip.open(p, "rt") as f:
        return json.load(f)


def sp500_monthly(cal_months):
    """Rebuild month-end S&P 500 membership by walking FMP's change list backwards."""
    cur = {norm(r["symbol"]) for r in json.load(open("indexes/sp500_current.json"))}
    hist = json.load(open("indexes/sp500_history.json"))
    changes = defaultdict(lambda: ([], []))  # date -> (added, removed)
    for r in hist:
        d = r.get("date") or ""
        if not d:
            continue
        if r.get("addedSecurity") and r.get("symbol"):
            changes[d][0].append(norm(r["symbol"]))
        if r.get("removedTicker"):
            changes[d][1].append(norm(r["removedTicker"]))
    dates = sorted(changes, reverse=True)
    out = {}
    members = set(cur)
    i = 0
    for month, last_day in sorted(cal_months.items(), reverse=True):
        while i < len(dates) and dates[i] > last_day:
            added, removed = changes[dates[i]]
            members -= set(added)
            members |= set(removed)
            i += 1
        out[month] = set(members)
    return out


def main():
    cal = [r["date"] for r in json.load(open("data/calendar.json"))]
    idx = {d: i for i, d in enumerate(cal)}
    cal_months = {}
    for d in cal:
        cal_months[d[:7]] = d
    today = f"{dt.date.today():%Y-%m}"
    cal_months = {m: d for m, d in cal_months.items() if m < today}

    members = defaultdict(lambda: defaultdict(set))  # code -> month -> {index}
    for m, syms in sp500_monthly(cal_months).items():
        for s in syms:
            members[s][m].add("sp500")
    with open("indexes/sp500_monthly.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["month", "symbol"])
        for m in sorted(cal_months):
            for s in sorted(x for x, mm in members.items() if m in mm):
                w.writerow((m, s))
    for name in ("sp400", "sp600"):
        for r in csv.DictReader(open(f"indexes/{name}_monthly.csv")):
            members[norm(r["symbol"])][r["month"]].add(name)

    syms = [s["code"] for s in json.load(open("data/symbols.json"))]
    rows_out = []
    for c in syms:
        rows = load_gz(f"data/eod/{c}.json.gz")
        rows = [r for r in rows if r.get("date") in idx]
        if not rows:
            rows_out.append((c, 0, "", "", 0, "excluded", "no data", 0))
            continue
        splits = {r["date"] for r in load_gz(f"data/corp/{c}.splits.json.gz") if "date" in r}
        # cut at gaps
        segs, cur = [], [rows[0]]
        for prev, r in zip(rows, rows[1:]):
            if idx[r["date"]] - idx[prev["date"]] - 1 > GAP:
                segs.append(cur)
                cur = []
            cur.append(r)
        segs.append(cur)
        for k, seg in enumerate(segs):
            # trim dead tail: cut after the last day whose trailing 20 sessions were mostly traded
            vols = [float(r.get("volume") or 0) > 0 for r in seg]
            end_i = 0
            for i in range(len(seg)):
                if sum(vols[max(0, i - 19):i + 1]) >= 15 and vols[i]:
                    end_i = i
            seg = seg[:end_i + 1]
            n = len(seg)
            zero = sum(1 for r in seg if float(r.get("volume") or 0) == 0)
            wild = 0
            for p, r in zip(seg, seg[1:]):
                pc, cc = float(p.get("close") or 0), float(r.get("close") or 0)
                if pc > 0 and abs(cc / pc - 1) > 0.5:
                    day = dt.date.fromisoformat(r["date"])
                    if not any(str(day + dt.timedelta(x)) in splits for x in (-1, 0, 1)):
                        wild += 1
            start, end = seg[0]["date"], seg[-1]["date"]
            im = sum(1 for m in members.get(c, {}) if start[:7] <= m <= end[:7])
            if n < MIN_ROWS:
                status, why = "excluded", f"only {n} rows"
            elif zero / n > MAX_ZERO_VOL:
                status, why = "excluded", f"{zero / n:.0%} zero-volume days"
            elif wild > max(3, WILD_PER_1000 * n / 1000):
                status, why = "excluded", f"{wild} unexplained >50% moves"
            elif im == 0:
                status, why = "unused", "never in an index while trading"
            else:
                status, why = "clean", ""
            rows_out.append((c, k, start, end, n, status, why, im))

    with open("indexes/trust.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["code", "segment", "start", "end", "rows", "status", "reason", "index_months"])
        w.writerows(rows_out)
    from collections import Counter
    print(Counter(r[5] for r in rows_out))
    sizes = {m: sum(1 for c in members if m in members[c] and "sp500" in members[c][m]) for m in ("1996-01", "2000-12", "2008-09", "2015-06", "2024-12")}
    print("rebuilt S&P 500 sizes:", sizes)


if __name__ == "__main__":
    main()
