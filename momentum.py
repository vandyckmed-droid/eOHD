#!/usr/bin/env python3
"""Study 1: 12-1 month momentum within the S&P 500, monthly rebalance, equal weight.

Universe: point-in-time S&P 500 members (indexes/sp500_monthly.csv), clean trust segments only.
Signal: adjusted close 1 month ago / adjusted close 12 months ago - 1.
Portfolios: top 50, bottom 50, equal-weight all members; plus SPY.
Returns: total return via adjusted_close. A stock with no month-end price exits at its
last available price that month. Costs: 0.2% on each dollar traded (applied to top/bottom only).
"""
import csv
import gzip
import json
import math
from collections import defaultdict

TOP_N = 50
COST = 0.002
START = "1996-01"


def load_gz(p):
    with gzip.open(p, "rt") as f:
        return json.load(f)


def main():
    members = defaultdict(set)  # month -> {code}
    for r in csv.DictReader(open("indexes/sp500_monthly.csv")):
        members[r["month"]].add(r["symbol"])
    months = sorted(m for m in members if m >= START)
    clean = defaultdict(list)  # code -> [(start, end)]
    for r in csv.DictReader(open("indexes/trust.csv")):
        if r["status"] == "clean":
            clean[r["code"]].append((r["start"], r["end"]))
    codes = {c for ms in members.values() for c in ms if c in clean}

    def next_month(m):
        y, mo = int(m[:4]), int(m[5:7])
        return f"{y + (mo == 12):04d}-{mo % 12 + 1:02d}"

    # month -> last adjusted close in that calendar month, for each code.
    # Cross-check: the adjusted-close return must agree with the raw close return
    # (raw close x split factor + dividends). A stock-month that disagrees by more
    # than TOL is dropped; a series with many disagreements is dropped entirely.
    TOL = 0.15
    px, bad_months, dropped = {}, {}, []
    for c in codes:
        rows = load_gz(f"data/eod/{c}.json.gz")
        adj, raw = {}, {}
        for r in rows:
            dt_ = r["date"]
            if any(s <= dt_ <= e for s, e in clean[c]) and r.get("adjusted_close") and r.get("close"):
                adj[dt_[:7]] = float(r["adjusted_close"])
                raw[dt_[:7]] = float(r["close"])
        divs, splits = defaultdict(float), defaultdict(lambda: 1.0)
        for r in load_gz(f"data/corp/{c}.div.json.gz"):
            if r.get("date"):
                divs[r["date"][:7]] += float(r.get("unadjustedValue") or r.get("value") or 0)
        for r in load_gz(f"data/corp/{c}.splits.json.gz"):
            if r.get("date") and "/" in str(r.get("split", "")):
                a, b = r["split"].split("/")
                if float(b) > 0:
                    splits[r["date"][:7]] *= float(a) / float(b)
        bad = set()
        ms = sorted(adj)
        for m, nxt in zip(ms, ms[1:]):
            if nxt != next_month(m):
                continue
            ra = adj[nxt] / adj[m] - 1
            rr = (raw[nxt] * splits[nxt] + divs[nxt]) / raw[m] - 1
            if abs(ra - rr) > TOL:
                bad.add(nxt)
        if len(bad) >= 4:
            dropped.append(c)
            continue
        for m in bad:
            adj.pop(m, None)
        bad_months[c] = bad
        px[c] = adj
    print(f"consistency check: dropped {len(dropped)} series entirely ({', '.join(sorted(dropped))}); "
          f"dropped {sum(len(b) for b in bad_months.values())} single stock-months")
    spy = {}
    for r in json.load(open("data/calendar.json")):
        spy[r["date"][:7]] = float(r["adjusted_close"])

    def next_month(m):
        y, mo = int(m[:4]), int(m[5:7])
        return f"{y + (mo == 12):04d}-{mo % 12 + 1:02d}"

    def prev_month(m, k):
        y, mo = int(m[:4]), int(m[5:7])
        mo -= k
        while mo <= 0:
            mo += 12
            y -= 1
        return f"{y:04d}-{mo:02d}"

    series = {"top": [], "bottom": [], "equal": [], "spy": []}
    hold = {"top": set(), "bottom": set()}
    for m, nxt in zip(months, months[1:]):
        m1, m12 = prev_month(m, 1), prev_month(m, 12)
        scored = []
        rets = {}
        for c in members[m]:
            p = px.get(c)
            if not p or m not in p:
                continue
            exit_px = p.get(nxt, p[m])  # dead mid-month: exits at last price seen (== entry if none)
            rets[c] = exit_px / p[m] - 1
            if m1 in p and m12 in p and p[m12] > 0:
                scored.append((p[m1] / p[m12] - 1, c))
        if len(scored) < 100:
            continue
        scored.sort()
        picks = {"top": {c for _, c in scored[-TOP_N:]}, "bottom": {c for _, c in scored[:TOP_N]}}
        for k, sel in picks.items():
            gross = sum(rets[c] for c in sel) / len(sel)
            replaced = len(sel - hold[k]) if hold[k] else len(sel)
            cost = COST * 2 * replaced / len(sel)
            series[k].append((nxt, gross, gross - cost))
            hold[k] = sel
        ew = sum(rets.values()) / len(rets)
        series["equal"].append((nxt, ew, ew))
        s = spy.get(nxt, 0) / spy.get(m, 1) - 1 if m in spy and nxt in spy else 0.0
        series["spy"].append((nxt, s, s))

    def stats(rows, net=False):
        r = [x[2] if net else x[1] for x in rows]
        n = len(r)
        growth = 1.0
        peak, mdd = 1.0, 0.0
        for x in r:
            growth *= 1 + x
            peak = max(peak, growth)
            mdd = min(mdd, growth / peak - 1)
        cagr = growth ** (12 / n) - 1
        mean = sum(r) / n
        vol = math.sqrt(sum((x - mean) ** 2 for x in r) / (n - 1)) * math.sqrt(12)
        return growth, cagr, vol, mdd, cagr / vol if vol else 0

    print(f"{len(series['top'])} months, {series['top'][0][0]} to {series['top'][-1][0]}\n")
    print(f"{'':22}{'growth of $1':>14}{'yearly':>9}{'volatility':>12}{'worst drop':>12}{'return/vol':>12}")
    for name, key, net in (("Top 50 momentum", "top", False), ("Top 50 after costs", "top", True),
                           ("Bottom 50", "bottom", False), ("Bottom 50 after costs", "bottom", True),
                           ("Equal-weight S&P 500", "equal", False), ("SPY", "spy", False)):
        g, c, v, d, sr = stats(series[key], net)
        print(f"{name:22}{g:14.2f}{c:9.1%}{v:12.1%}{d:12.1%}{sr:12.2f}")

    top = {m: x for m, _, x in series["top"]}
    eq = {m: x for m, _, x in series["equal"]}
    wins = sum(1 for m in top if top[m] > eq[m])
    print(f"\nTop 50 (after costs) beat equal-weight in {wins} of {len(top)} months ({wins / len(top):.0%})")
    print("\nBy period (yearly return, top 50 after costs vs equal-weight vs SPY):")
    spy_d = {m: x for m, x, _ in series["spy"]}
    for a, b in (("1996", "2000"), ("2001", "2007"), ("2008", "2009"), ("2010", "2019"), ("2020", "2026")):
        ms = [m for m in top if a <= m[:4] <= b]
        def cagr(d):
            g = 1.0
            for m in ms:
                g *= 1 + d[m]
            return g ** (12 / len(ms)) - 1
        print(f"  {a}-{b}: {cagr(top):7.1%} {cagr(eq):8.1%} {cagr(spy_d):8.1%}")
    # calendar-year table of top-50 net minus equal-weight
    print("\nTop 50 after costs minus equal-weight, by calendar year:")
    years = sorted({m[:4] for m in top})
    line = []
    for y in years:
        ms = [m for m in top if m[:4] == y]
        gt = ge = 1.0
        for m in ms:
            gt *= 1 + top[m]
            ge *= 1 + eq[m]
        line.append(f"{y}:{gt - ge:+.0%}")
    for i in range(0, len(line), 8):
        print("  " + "  ".join(line[i:i + 8]))


if __name__ == "__main__":
    main()
