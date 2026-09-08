"""Shared loaders for the studies: point-in-time S&P 500 membership and clean monthly prices."""
import csv
import gzip
import json
from collections import defaultdict

TOL = 0.15  # max allowed gap between adjusted-close return and raw-close+splits+dividends return


def load_gz(p):
    with gzip.open(p, "rt") as f:
        return json.load(f)


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


def members_by_month():
    members = defaultdict(set)
    for r in csv.DictReader(open("indexes/sp500_monthly.csv")):
        members[r["month"]].add(r["symbol"])
    return members


def monthly_prices(codes):
    """{code: {month: adjusted close at last trading day of month}} over clean segments,
    with stock-months failing the adjusted-vs-raw consistency check removed and
    series failing it repeatedly dropped. Returns (prices, dropped_codes)."""
    clean = defaultdict(list)
    for r in csv.DictReader(open("indexes/trust.csv")):
        if r["status"] == "clean":
            clean[r["code"]].append((r["start"], r["end"]))
    px, dropped = {}, []
    for c in codes:
        if c not in clean:
            continue
        adj, raw = {}, {}
        for r in load_gz(f"data/eod/{c}.json.gz"):
            d = r["date"]
            if any(s <= d <= e for s, e in clean[c]) and r.get("adjusted_close") and r.get("close"):
                adj[d[:7]] = float(r["adjusted_close"])
                raw[d[:7]] = float(r["close"])
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
        px[c] = adj
    return px, dropped


def spy_monthly():
    return {r["date"][:7]: float(r["adjusted_close"]) for r in json.load(open("data/calendar.json"))}


def cagr(rets):
    g = 1.0
    for x in rets:
        g *= 1 + x
    return g ** (12 / len(rets)) - 1 if rets else float("nan")
