# eOHD

Backtesting data pipeline for US equities from [EODHD](https://eodhd.com). One script, stdlib only.

```
export EODHD_KEY=...
python3 eodhd_pull.py probe      # detect bulk vs symbol access -> state.json
python3 eodhd_pull.py pull       # download prices, splits, dividends -> data/
python3 eodhd_pull.py universe   # monthly universe -> universe/YYYY-MM.csv
python3 eodhd_pull.py qa         # data checks -> qa_report.md, qa/check*.csv
```

## Behaviour

- **Resumable / idempotent.** Existing files are skipped, never rewritten or deleted. Rerun any command to continue.
- **Errors** go to `errors.log`; the run continues. Quota errors (HTTP 402/429) stop the run cleanly; rerun later.
- **Rate limit:** 100 ms between requests, 2 retries.
- `pull --limit N` downloads only the first N days/symbols (for testing).

## Modes (set by `probe`)

- `bulk`: one `data/daily/{date}.json` per SPY trading day since 2005 via `/eod-bulk-last-day/US`.
  Each request costs 100 API calls, so a full pull needs several days of quota.
- `symbol`: one `data/eod/{code}.json` per Common Stock symbol via `/eod/`.

Both modes fetch `/splits/` and `/div/` per symbol into `data/corp/` (about 51k Common Stock symbols, active and delisted).

## Universe

For the last trading day of each month from 2007-01: Common Stock, close >= $5, 20-day average dollar volume >= $25M, >= 252 rows of history. Delisted symbols are included. Only months covered by downloaded data are written.

## QA checks

1. adjusted_close/close ratio change > 15% with no split within 1 day
2. symbols missing > 1% of SPY sessions, or a gap > 5 sessions
3. universe size at 2008-09, 2009-03, 2020-03, 2022-10
4. high < low, close outside [low, high], zero volume, > 50% move with no split
5. data ending > 30 days before delisting (needs the fundamentals endpoint; if the plan returns 403 this is reported as unavailable)

## Index membership (from FMP, saved 2026-09-08)

`indexes/` holds current members and the add/remove history for the S&P 500, Nasdaq 100, and Dow. Used to build point-in-time universes without survivorship bias. FMP is no longer required once these are saved.

`indexes/sp400_monthly.csv` and `indexes/sp600_monthly.csv` are month-end membership snapshots taken from the edit history of the Wikipedia list pages (`wiki_index_snapshots.py`). S&P 400 runs from 2011-01, S&P 600 from 2018-09. Volunteer-maintained, so changes can lag by days; a few months are slightly short of 400 / 600 names.

## Trust list

`trust.py` rebuilds month-end S&P 500 membership from the FMP change history (`indexes/sp500_monthly.csv`) and writes `indexes/trust.csv`: each ticker's price series cut at gaps (ticker reuse), dead tails trimmed, and each segment marked `clean`, `excluded` (bad data), or `unused` (never in an index while trading). Backtests should only use `clean` segments. About 99% of index-membership months are covered by clean data; the rest is old EODHD series that mix in unrelated securities.
