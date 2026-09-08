#!/usr/bin/env python3
"""Study 2: where does the momentum information live?

Each month, sort point-in-time S&P 500 members into 10 equal buckets by past return
(lookback L months, skipping the most recent month) and record each bucket's
next-month equal-weight return. Reported as yearly return per bucket, for
lookbacks 12/6/3 and for two periods. No costs.
"""
from collections import defaultdict
from mlib import members_by_month, monthly_prices, prev_month, cagr

START = "1996-01"
BUCKETS = 10
LOOKBACKS = (12, 6, 3)
PERIODS = (("1996", "2009"), ("2010", "2026"), ("1996", "2026"))


def main():
    members = members_by_month()
    months = sorted(m for m in members if m >= START)
    codes = {c for ms in members.values() for c in ms}
    px, dropped = monthly_prices(codes)
    print(f"{len(px)} series loaded, {len(dropped)} dropped by consistency check\n")

    # bucket returns: lookback -> bucket -> [(month, ret)]
    out = {L: defaultdict(list) for L in LOOKBACKS}
    for m, nxt in zip(months, months[1:]):
        rets = {}
        for c in members[m]:
            p = px.get(c)
            if p and m in p:
                rets[c] = p.get(nxt, p[m]) / p[m] - 1
        for L in LOOKBACKS:
            m1, mL = prev_month(m, 1), prev_month(m, L)
            scored = sorted((px[c][m1] / px[c][mL] - 1, c) for c in rets
                            if m1 in px[c] and mL in px[c] and px[c][mL] > 0)
            if len(scored) < 200:
                continue
            n = len(scored)
            for b in range(BUCKETS):
                grp = scored[b * n // BUCKETS:(b + 1) * n // BUCKETS]
                out[L][b].append((nxt, sum(rets[c] for _, c in grp) / len(grp)))

    for L in LOOKBACKS:
        print(f"Lookback {L} months (bucket 1 = worst past return, {BUCKETS} = best). Yearly return:")
        print(f"{'period':12}" + "".join(f"{b + 1:>7}" for b in range(BUCKETS)) + f"{'10 minus 1':>12}")
        for a, z in PERIODS:
            row = []
            for b in range(BUCKETS):
                row.append(cagr([r for m, r in out[L][b] if a <= m[:4] <= z]))
            print(f"{a}-{z:8}" + "".join(f"{x:7.1%}" for x in row) + f"{row[-1] - row[0]:12.1%}")
        print()


if __name__ == "__main__":
    main()
