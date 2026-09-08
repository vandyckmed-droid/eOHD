#!/usr/bin/env python3
"""Month-end snapshots of S&P 400 / S&P 600 membership from Wikipedia page history.

For each month-end, takes the last revision of the Wikipedia list page on or before
that date and extracts the ticker column. Writes indexes/{name}_monthly.csv with
columns month,symbol. Stdlib only. Re-running only fetches months not yet saved.
"""
import csv
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

API = "https://en.wikipedia.org/w/api.php"
UA = "eOHD-backtest/1.0 (contact: vandyck.med@gmail.com)"
PAGES = {
    "sp400": ("List of S&P 400 companies", "2011-01"),
    "sp600": ("List of S&P 600 companies", "2018-09"),
}
TICKER = re.compile(r"^[A-Z][A-Z0-9.\-]{0,6}$")


def api(params):
    params = dict(params, format="json")
    req = urllib.request.Request(f"{API}?{urllib.parse.urlencode(params)}", headers={"User-Agent": UA})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.loads(r.read().decode())
            time.sleep(0.7)  # stay well under Wikipedia's rate limit
            return data
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == 4:
                raise
            time.sleep(15 * (attempt + 1))
        except Exception:  # noqa: BLE001
            if attempt == 4:
                raise
            time.sleep(2 ** attempt)


def revisions(title):
    """All (timestamp, revid) for a page, oldest first."""
    out, cont = [], {}
    while True:
        d = api({"action": "query", "prop": "revisions", "titles": title, "rvlimit": 500,
                 "rvprop": "ids|timestamp", "rvdir": "newer", "redirects": 1, **cont})
        page = next(iter(d["query"]["pages"].values()))
        out += [(r["timestamp"][:10], r["revid"]) for r in page.get("revisions", [])]
        cont = d.get("continue")
        if not cont:
            return out


def wikitexts(revids):
    """{revid: wikitext} fetched in batches of 20 revisions per request."""
    out = {}
    revids = list(revids)
    for i in range(0, len(revids), 20):
        d = api({"action": "query", "prop": "revisions", "revids": "|".join(map(str, revids[i:i + 20])),
                 "rvprop": "ids|content", "rvslots": "main"})
        for page in d["query"]["pages"].values():
            for r in page.get("revisions", []):
                out[r["revid"]] = r["slots"]["main"]["*"]
    return out


def tickers(text):
    """Extract tickers from the constituents table."""
    found = []
    # exchange templates: {{NYSE|ABC}}, {{Nasdaq|ABC}}, {{NYSE American|ABC}} ...
    for m in re.finditer(r"\{\{\s*(?:nyse|nasdaq|bats|cboe)[a-z ]*\|\s*([A-Za-z0-9.\-]+)", text, re.I):
        found.append(m.group(1).upper())
    if len(found) < 300:
        # plain table: first cell of each row, possibly [[link|TEXT]] or a bare symbol
        found = []
        for row in text.split("|-"):
            cells = [c.strip() for c in re.split(r"\n\||\|\|", row) if c.strip()]
            if not cells:
                continue
            first = re.sub(r"\[\[[^\]|]*\|([^\]]*)\]\]", r"\1", cells[0])
            first = re.sub(r"\[\[([^\]]*)\]\]", r"\1", first).strip().strip("'").strip()
            first = re.sub(r"<[^>]+>", "", first).strip()
            if TICKER.match(first):
                found.append(first)
    return sorted(set(found))


def month_ends(start, end):
    y, m = map(int, start.split("-"))
    while f"{y:04d}-{m:02d}" <= end:
        last = (dt.date(y + (m == 12), m % 12 + 1, 1) - dt.timedelta(1))
        yield f"{y:04d}-{m:02d}", str(last)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def main():
    os.makedirs("indexes", exist_ok=True)
    today = dt.date.today()
    end = f"{today:%Y-%m}"
    for name, (title, start) in PAGES.items():
        out = f"indexes/{name}_monthly.csv"
        have = set()
        if os.path.exists(out):
            have = {r["month"] for r in csv.DictReader(open(out))}
        revs = revisions(title)
        new = not os.path.exists(out)
        with open(out, "a", newline="") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["month", "symbol"])
            pick = {}  # month -> (timestamp, revid)
            for month, last_day in month_ends(start, end):
                if month in have or month == end:
                    continue
                cands = [r for r in revs if r[0] <= last_day]
                if cands:
                    pick[month] = cands[-1]
            texts = wikitexts({revid for _, revid in pick.values()})
            for month, (ts, revid) in pick.items():
                syms = tickers(texts.get(revid, ""))
                print(f"{name} {month} rev {ts} -> {len(syms)} tickers", flush=True)
                if len(syms) < 300:
                    print(f"  WARNING: only {len(syms)} parsed, skipping month", flush=True)
                    continue
                w.writerows((month, s) for s in syms)
                f.flush()
    dedupe_sp600()
    print("done")


def dedupe_sp600():
    """Before 2021-03 the Wikipedia S&P 600 page listed the S&P 1000 (400 + 600);
    drop that month's S&P 400 members from the S&P 600 snapshot."""
    import collections
    a, b = collections.defaultdict(set), collections.defaultdict(set)
    for r in csv.DictReader(open("indexes/sp400_monthly.csv")):
        a[r["month"]].add(r["symbol"])
    for r in csv.DictReader(open("indexes/sp600_monthly.csv")):
        b[r["month"]].add(r["symbol"])
    with open("indexes/sp600_monthly.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["month", "symbol"])
        for m in sorted(b):
            syms = b[m] - a[m] if len(b[m]) > 700 else b[m]
            w.writerows((m, s) for s in sorted(syms))


if __name__ == "__main__":
    main()
