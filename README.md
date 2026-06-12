# stock_agent

`stock_agent` is a local A-share portfolio and watchlist assistant. It combines portfolio accounting, market-data caching, a FastAPI dashboard, and AI-assisted analysis tools into one personal research workspace.

> This project is for research and personal record keeping only. It is not financial advice.

## Features

- Track holdings, trades, realized PnL, floating PnL, and account history.
- Manage a watchlist from the web UI or seed it from `STOCK_LIST`.
- Cache A-share market snapshots to reduce repeated remote data calls.
- Read local historical price data for technical and risk indicators.
- Ask an AI assistant about holdings, watchlists, plans, and market context.
- Bridge into `daily_stock_analysis` for deeper stock and market reports.
- View a lightweight portfolio dashboard at `/portfolio/embed`.

## Project Layout

```text
app/                         Core portfolio, market data, AI tools, storage
web/                         FastAPI integration and HTML dashboard
scripts/                     Utility scripts
tests/                       Root project tests
third_party/daily_stock_analysis/
                             External DSA project integration target
backend/                     Convenience symlinks to app/ and web/
vendor/                      Convenience symlink to third_party/
```

## Quick Start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` with your own local keys:

```bash
DEEPSEEK_API_KEY=your_deepseek_key
STOCK_LIST=600519,000001
DATABASE_PATH=./data/stock_analysis.db
```

## Run

```bash
uvicorn web.main:app --reload
```

Open:

```text
http://127.0.0.1:8000/portfolio/embed
```

Command-line assistant:

```bash
python -m app.main
```

## Tests

```bash
python -m pytest -q tests
python -m pytest -q
```

## Privacy And Security

Never commit real secrets. Public repositories should only contain fake or empty configuration values.

Before publishing, confirm these are excluded:

- real `.env`
- `.venv/`
- `cache/`
- `data/*.db`
- `logs/`
- `portfolio.db`
- deploy keys and private keys
- generated upload folders or zip files

If a real API key was ever exposed in a screenshot, chat, browser page, or repository commit, rotate it immediately.

## Development

See `DEVELOPMENT.md` and `ROADMAP.md` in the local project for workflow notes and planned improvements.
