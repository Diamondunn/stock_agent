# stock_agent

`stock_agent` is a local A-share portfolio and watchlist assistant. It combines
portfolio accounting, market-data caching, a FastAPI dashboard, and AI-assisted
analysis tools into one personal research workspace.

> This project is for research and personal record keeping only. It is not
> financial advice.

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

Runtime data is intentionally kept out of version control:

```text
.env                         Local secrets and API keys
data/*.db                    SQLite databases
cache/                       Market and history caches
logs/                        Runtime logs
.venv/                       Local Python environment
portfolio.db                 Legacy local database
```

## Quick Start

Create a virtual environment and install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create local configuration:

```bash
cp .env.example .env
```

Edit `.env` and add your own values:

```bash
DEEPSEEK_API_KEY=your_deepseek_key
STOCK_LIST=600519,000001
DATABASE_PATH=./data/stock_analysis.db
```

## Run

Start the web app:

```bash
uvicorn web.main:app --reload
```

Open the portfolio dashboard:

```text
http://127.0.0.1:8000/portfolio/embed
```

Run the command-line assistant:

```bash
python -m app.main
```

## Configuration

Common `.env` values:

```bash
DEEPSEEK_API_KEY=
TAVILY_API_KEY=
TUSHARE_TOKEN=
PUSHPLUS_TOKEN=
STOCK_LIST=600519,000001
DATABASE_PATH=./data/stock_analysis.db
LOG_DIR=./logs
ALERT_ENABLED=false
ALERT_PCT=5
```

`STOCK_LIST` is used as an initial or fallback watchlist. Once the database
watchlist has entries, database values take priority so web add/remove actions
remain effective.

## Tests

Run the fast root tests:

```bash
python -m pytest -q tests
```

Run the full configured suite:

```bash
python -m pytest -q
```

Current local verification:

```text
553 passed, 37 warnings, 92 subtests passed
```

Most warnings come from the bundled third-party test suite and dependency
deprecations.

## Development

Useful local checks:

```bash
python -m compileall -q app web scripts tests
python -m pytest -q tests
```

See:

- `DEVELOPMENT.md` for workflow and privacy checklists.
- `ROADMAP.md` for planned improvements.
- `STRUCTURE.md` for the repository layout notes.

## GitHub Sync

If automated upload is unavailable, run:

```bash
bash scripts/sync_to_github.sh
```

The sync script copies only safe project files to a temporary clone and pushes
them. It deliberately excludes real `.env`, databases, caches, logs, virtual
environments, and upload artifacts.

## Privacy And Security

Never commit real secrets. Public repositories should only contain fake or empty
configuration values.

Before publishing, confirm these are excluded:

- real `.env`
- `.venv/`
- `cache/`
- `data/*.db`
- `logs/`
- `portfolio.db`
- deploy keys and private keys
- generated upload folders or zip files

If a real API key was ever exposed in a screenshot, chat, browser page, or
repository commit, rotate it immediately.

## Third-Party Integration

`third_party/daily_stock_analysis` is treated as an external project. The local
bridge lives in `app/dsa_bridge.py`.

When using a submodule-style checkout:

```bash
git submodule update --init --recursive
```

## License

No license has been selected yet. Add one before distributing this project
beyond personal use.
