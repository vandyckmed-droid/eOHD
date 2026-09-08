# eOHD

Data lake and backtesting repo for a personal investment portfolio. The current app is built on this data.

## Repos
- **eOHD** (this repo): data lake. Prices, splits, dividends, index membership, trust list. Backtests live here.
- **e2**: creative front end. Designs and tests the best way to display this data.

## Data
- EODHD.com (https://eodhd.com). Key: `EODHD_KEY` environment variable (also available as the eODHD connector).
- FMP is also available via the connector or `FMP_KEY`.
- Never commit an API key.
- Reuse saved files. Do not re-download data that already exists here.

## Building
- Wait for authorization before building each step. Say clearly when a step is done.
- Auto-merge to `main` is authorized. Do not monitor or poll after merging.
- `main` must always be something the owner can open and interact with to test.

## Quotes and scope
When asked for a quote or scope, answer in this order:
1. Difficulty (easy / medium / hard).
2. Suggestion: build or don't build.
3. Risks or suggestions, if any.

## Response style
- Keep responses short and simple, always.
- The owner is not a programmer. No code, commands, file paths, or technical jargon unless explicitly asked.
- Explain in plain English what was done, what changed, and why it matters to the owner.
- Fewest words possible. No preamble, summaries, or pleasantries.
- Answer yes/no questions with "Yes" or "No" alone.
- If something could cost money or break the app, say so plainly.
- Before any risky action (deleting, overwriting, spending), stop and ask first.
- Nothing may run longer than 10 minutes without checking in first. Never plan or start multi-hour work. If a job needs more, ask for more time and say how long; permission applies to that run only.
- One step at a time. Ask before each step that downloads, changes files, or schedules anything.
