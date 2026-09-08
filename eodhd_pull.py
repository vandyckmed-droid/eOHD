#!/usr/bin/env python3
"""Pull EODHD US equity data, build a monthly universe, and run QA. Stdlib only.

Commands:
  probe             detect whether the API key has bulk access; writes state.json
  pull [--limit N]  download prices, splits, dividends (skips files already present)
  universe          write universe/{YYYY-MM}.csv for each month-end from 2007
  qa                write qa_report.md (+ qa/check*.csv)

Every command is resumable and idempotent: existing files are never rewritten
or deleted. Errors are appended to errors.log and the run continues.
"""
import csv
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque

BASE = "https://eodhd.com/api"
KEY = os.environ.get("EODHD_KEY")
FROM = "2005-01-01"
UNIVERSE_START = "2007-01"
SLEEP = 0.1
D = "data"
STATE = "state.json"
ERRLOG = "errors.log"
MIN_PRICE = 5.0
MIN_ADV = 25e6
MIN_HISTORY = 252
ADV_WINDOW = 20
REPORT_ROWS = 100


class QuotaExceeded(Exception):
    pass


# ---------------------------------------------------------------- helpers

def log_err(msg):
    with open(ERRLOG, "a") as f:
        f.write(f"{dt.datetime.now():%Y-%m-%d %H:%M:%S} {msg}\n")


def load_json(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path) as f:
        return json.load(f)


def save_json(path, obj):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f)
    os.replace(tmp, path)


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def get(path, params=None):
    """GET JSON. Retries twice on network/5xx errors, then logs and returns None.
    Raises HTTPError for 4xx (except quota codes, which raise QuotaExceeded)."""
    q = dict(params or {})
    q["api_token"] = KEY
    q["fmt"] = "json"
    url = f"{BASE}{path}?{urllib.parse.urlencode(q)}"
    err = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                data = json.loads(r.read().decode())
            time.sleep(SLEEP)
            return data
        except urllib.error.HTTPError as e:
            if e.code in (402, 429):
                raise QuotaExceeded(f"HTTP {e.code} on {path}")
            if 400 <= e.code < 500:
                raise
            err = f"HTTP {e.code}"
        except (urllib.error.URLError, OSError, ValueError) as e:
            err = repr(e)
        if attempt < 2:
            time.sleep(2 ** attempt)
    log_err(f"{path} {err}")
    return None


def fetch_to(path, target, params=None):
    """Download to target unless it already exists. 404 saves an empty list."""
    if os.path.exists(target):
        return False
    try:
        data = get(path, params)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            data = []
        else:
            log_err(f"{path} HTTP {e.code}")
            return False
    if data is None:
        return False
    save_json(target, data)
    return True


def get_mode():
    mode = (load_json(STATE) or {}).get("mode")
    if mode not in ("bulk", "symbol"):
        sys.exit("run `probe` first")
    return mode


def load_symbols():
    """Common Stock symbols (active + delisted), cached in data/symbols.json."""
    p = f"{D}/symbols.json"
    syms = load_json(p)
    if syms is None:
        seen = {}
        for delisted in (0, 1):
            rows = get("/exchange-symbol-list/US", {"delisted": delisted})
            if rows is None:
                sys.exit("symbol list fetch failed, see errors.log")
            for r in rows:
                if r.get("Type") == "Common Stock" and "/" not in r["Code"]:
                    seen.setdefault(r["Code"], {"code": r["Code"], "name": r.get("Name"),
                                                "delisted": bool(delisted)})
        syms = sorted(seen.values(), key=lambda s: s["code"])
        save_json(p, syms)
    return syms


def load_calendar():
    """SPY trading dates from 2005, cached in data/calendar.json."""
    p = f"{D}/calendar.json"
    fetch_to("/eod/SPY.US", p, {"from": FROM})
    rows = load_json(p)
    if not rows:
        sys.exit("SPY calendar fetch failed, see errors.log")
    return [r["date"] for r in rows]


def month_ends(cal):
    """{date: 'YYYY-MM'} for the last trading day of each complete month."""
    last = {}
    for d in cal:
        last[d[:7]] = d
    cur = f"{dt.date.today():%Y-%m}"
    return {d: m for m, d in last.items() if UNIVERSE_START <= m < cur}


def iter_rows(mode, codes):
    """Yield (code, row); rows are ascending by date within each code."""
    if mode == "bulk":
        for f in sorted(os.listdir(f"{D}/daily")):
            for r in load_json(f"{D}/daily/{f}") or []:
                c = r.get("code")
                if c in codes:
                    yield c, r
    else:
        for c in sorted(codes):
            for r in load_json(f"{D}/eod/{c}.json") or []:
                yield c, r


def progress(i, n, what):
    if i % 100 == 0 or i == n:
        print(f"{what}: {i}/{n}", flush=True)


# ---------------------------------------------------------------- commands

def cmd_probe():
    try:
        rows = get("/eod-bulk-last-day/US", {"date": "2010-06-15"})
        if rows is None:
            sys.exit("probe failed, see errors.log")
        mode = "bulk" if rows else "symbol"
    except urllib.error.HTTPError as e:
        if e.code != 403:
            raise
        mode = "symbol"
    save_json(STATE, {"mode": mode})
    print(f"mode={mode}")


def cmd_pull(limit=None):
    mode = get_mode()
    cal = load_calendar()
    syms = load_symbols()
    if limit:
        cal, syms = cal[:limit], syms[:limit]
    if mode == "bulk":
        for i, d in enumerate(cal, 1):
            fetch_to("/eod-bulk-last-day/US", f"{D}/daily/{d}.json", {"date": d})
            progress(i, len(cal), "daily")
    else:
        for i, s in enumerate(syms, 1):
            c = s["code"]
            fetch_to(f"/eod/{c}.US", f"{D}/eod/{c}.json", {"from": FROM})
            progress(i, len(syms), "eod")
    for i, s in enumerate(syms, 1):
        c = s["code"]
        fetch_to(f"/splits/{c}.US", f"{D}/corp/{c}.splits.json", {"from": FROM})
        fetch_to(f"/div/{c}.US", f"{D}/corp/{c}.div.json", {"from": FROM})
        progress(i, len(syms), "corp")
    print("pull complete")


def cmd_universe():
    mode = get_mode()
    codes = {s["code"] for s in load_symbols()}
    ends = month_ends(load_calendar())
    todo = {m for m in ends.values() if not os.path.exists(f"universe/{m}.csv")}
    if not todo:
        print("universe up to date")
        return
    out = {m: [] for m in todo}
    st = {}  # code -> [deque of dollar volume, row count]
    last_seen = ""
    for c, r in iter_rows(mode, codes):
        s = st.get(c)
        if s is None:
            s = st[c] = [deque(maxlen=ADV_WINDOW), 0]
        close = num(r.get("close"))
        s[0].append(close * num(r.get("volume")))
        s[1] += 1
        d = r.get("date") or ""
        last_seen = max(last_seen, d)
        m = ends.get(d)
        if m in out and close >= MIN_PRICE and s[1] >= MIN_HISTORY and len(s[0]) == ADV_WINDOW:
            adv = sum(s[0]) / ADV_WINDOW
            if adv >= MIN_ADV:
                out[m].append((c, close, round(adv), s[1]))
    # only write months the downloaded data actually covers, so a partial pull can resume
    end_date = {m: d for d, m in ends.items()}
    out = {m: rows for m, rows in out.items() if end_date[m] <= last_seen}
    os.makedirs("universe", exist_ok=True)
    for m in sorted(out):
        with open(f"universe/{m}.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["code", "close", "adv20", "history_days"])
            w.writerows(sorted(out[m]))
        print(f"universe/{m}.csv: {len(out[m])} symbols")


def load_delist_dates(syms, have_data):
    """Delisting dates from fundamentals, cached in data/corp/delist.json.
    Only symbols with downloaded data are queried. A 403 (plan lacks fundamentals)
    stops querying and is remembered under the "_unavailable" key."""
    p = f"{D}/corp/delist.json"
    cache = load_json(p, {})
    if cache.get("_unavailable"):
        return cache
    todo = [s["code"] for s in syms if s["delisted"] and s["code"] in have_data and s["code"] not in cache]
    try:
        for i, c in enumerate(todo, 1):
            try:
                v = get(f"/fundamentals/{c}.US", {"filter": "General::DelistedDate"})
            except urllib.error.HTTPError as e:
                if e.code == 403:
                    cache["_unavailable"] = True
                    log_err(f"/fundamentals/{c}.US HTTP 403: delisting dates unavailable on this plan")
                    break
                if e.code != 404:
                    log_err(f"/fundamentals/{c}.US HTTP {e.code}")
                    continue
                v = ""
            if v is None:
                continue
            cache[c] = v if isinstance(v, str) and v else None
            if i % 50 == 0:
                save_json(p, cache)
            progress(i, len(todo), "delist")
    finally:
        save_json(p, cache)
    return cache


def cmd_qa():
    mode = get_mode()
    syms = load_symbols()
    codes = {s["code"] for s in syms}
    cal = load_calendar()
    idx = {d: i for i, d in enumerate(cal)}
    splits = {}
    for c in codes:
        splits[c] = {r["date"] for r in load_json(f"{D}/corp/{c}.splits.json", []) if "date" in r}

    def near_split(c, d):
        day = dt.date.fromisoformat(d)
        return any(str(day + dt.timedelta(k)) in splits[c] for k in (-1, 0, 1))

    f1, f2, f4, f5 = [], [], [], []
    st = {}  # code -> {prev, first_i, last_i, n, maxgap, last_date}
    for c, r in iter_rows(mode, codes):
        d = r.get("date")
        close, adj = num(r.get("close")), num(r.get("adjusted_close"))
        high, low, vol = num(r.get("high")), num(r.get("low")), num(r.get("volume"))
        s = st.get(c)
        if s is None:
            s = st[c] = {"prev": None, "first_i": None, "last_i": None, "n": 0, "maxgap": 0, "last_date": None}
        p = s["prev"]
        if p and p["close"] > 0 and close > 0:
            r0, r1 = p["adj"] / p["close"], adj / close
            if r0 > 0 and abs(r1 / r0 - 1) > 0.15 and not near_split(c, d):
                f1.append((c, d, round(r0, 4), round(r1, 4)))
            if abs(close / p["close"] - 1) > 0.5 and not near_split(c, d):
                f4.append((c, d, "move>50%", p["close"], close))
        if high < low:
            f4.append((c, d, "high<low", high, low))
        if close < low or close > high:
            f4.append((c, d, "close outside range", low, high))
        if vol == 0:
            f4.append((c, d, "zero volume", close, vol))
        i = idx.get(d)
        if i is not None:
            if s["first_i"] is None:
                s["first_i"] = i
            elif i - s["last_i"] - 1 > s["maxgap"]:
                s["maxgap"] = i - s["last_i"] - 1
            s["last_i"] = i
            s["n"] += 1
        s["prev"] = {"close": close, "adj": adj}
        s["last_date"] = d

    for c, s in sorted(st.items()):
        if s["first_i"] is None:
            continue
        span = s["last_i"] - s["first_i"] + 1
        missing = span - s["n"]
        if missing / span > 0.01 or s["maxgap"] > 5:
            f2.append((c, cal[s["first_i"]], cal[s["last_i"]], missing, span, s["maxgap"]))

    sizes = []
    for m in ("2008-09", "2009-03", "2020-03", "2022-10"):
        p = f"universe/{m}.csv"
        n = sum(1 for _ in open(p)) - 1 if os.path.exists(p) else "missing (run universe)"
        sizes.append((m, n))

    delist = load_delist_dates(syms, st)
    if delist.get("_unavailable"):
        f5.append(("n/a", "delisting dates unavailable on this plan (fundamentals HTTP 403)", "", ""))
    for c, dd in sorted(delist.items()):
        s = st.get(c)
        if not dd or not s or not s["last_date"]:
            continue
        gap = (dt.date.fromisoformat(dd[:10]) - dt.date.fromisoformat(s["last_date"])).days
        if gap > 30:
            f5.append((c, s["last_date"], dd[:10], gap))

    checks = [
        (1, "adjusted_close/close ratio change >15% without split within 1 day",
         ["code", "date", "ratio_prev", "ratio"], f1),
        (2, "missing >1% of SPY sessions or gap >5 sessions",
         ["code", "first", "last", "missing", "sessions", "max_gap"], f2),
        (3, "universe size", ["month", "symbols"], sizes),
        (4, "bad rows: high<low, close outside range, zero volume, >50% move without split",
         ["code", "date", "issue", "a", "b"], f4),
        (5, "data ending >30 days before delisting",
         ["code", "last_data", "delisted", "days_early"], f5),
    ]
    os.makedirs("qa", exist_ok=True)
    lines = [f"# QA report ({dt.date.today()}, mode={mode}, {len(st)} symbols scanned)\n"]
    for n, title, cols, rows in checks:
        with open(f"qa/check{n}.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(cols)
            w.writerows(rows)
        lines.append(f"\n## {n}. {title}\n\n{len(rows)} rows (full list: qa/check{n}.csv)\n")
        if rows:
            lines.append("| " + " | ".join(cols) + " |")
            lines.append("|" + "---|" * len(cols))
            for row in rows[:REPORT_ROWS]:
                lines.append("| " + " | ".join(str(x) for x in row) + " |")
            if len(rows) > REPORT_ROWS:
                lines.append(f"\n... {len(rows) - REPORT_ROWS} more in qa/check{n}.csv")
    with open("qa_report.md", "w") as f:
        f.write("\n".join(lines) + "\n")
    print("wrote qa_report.md")


def main(argv):
    if not KEY:
        sys.exit("EODHD_KEY not set")
    cmd = argv[1] if len(argv) > 1 else ""
    limit = int(argv[argv.index("--limit") + 1]) if "--limit" in argv else None
    cmds = {"probe": cmd_probe, "pull": lambda: cmd_pull(limit),
            "universe": cmd_universe, "qa": cmd_qa}
    if cmd not in cmds:
        sys.exit(__doc__)
    try:
        cmds[cmd]()
    except QuotaExceeded as e:
        print(f"API quota exhausted ({e}); rerun later to resume")
        sys.exit(2)


if __name__ == "__main__":
    main(sys.argv)
