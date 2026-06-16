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

## Agent Showcase

This project is designed to be demo-friendly as an AI agent portfolio project.
The assistant has persistent memory, tool calls, risk analytics, and safe public
configuration practices:

- Persistent memory: holdings, trades, watchlist items, and investment plans are
  stored in SQLite.
- Agent tools: the LLM can call portfolio, watchlist, trade logging, account
  analytics, and deep-analysis tools.
- Deterministic trade workflow: natural-language trade text is parsed into
  structured fields, checked by a pre-trade risk guard, then persisted only when
  hard checks pass.
- Risk view: realized PnL, win rate, profit factor, equity curve, and drawdown
  are available without calling external market APIs.
- Self-learning review: closed trades are reconstructed into round trips, then
  used to extract win/loss patterns, weak symbols, risk-reward problems, and
  next-step strategy rules.
- Multi-agent committee: inspired by popular trading-agent systems, specialist
  agents produce technical, risk, and memory views, then a coordinator and critic
  reconcile conflicts before producing a BUY/WATCH/REDUCE-style decision.
- Watchlist research: cached quotes, local history, technical indicators, and
  trend signals support explainable stock observations.
- Dashboard committee panel: `/portfolio/embed` exposes the multi-role decision
  result directly in the web UI for demos.
- Privacy-first publishing: real `.env`, databases, caches, logs, and deploy
  keys are excluded from GitHub sync.

Useful demo endpoints:

```text
GET /api/agent/profile       JSON capability profile and current memory status
GET /api/agent/health        Operational checks without exposing secrets
GET /api/agent/demo-prompts  Suggested questions for live demos
GET /api/agent/trade-review  Historical trade review and learned lessons
GET /api/agent/strategy-advice
                             Strategy rules derived from past trades
POST /api/agent/daily-review Daily review with optional long-term memory write
GET /api/agent/committee/{symbol}
                             Multi-role investment committee decision
GET /agent/profile           Plain-text project profile
```

Example demo prompts:

```text
我的组合现在风险主要集中在哪里？
分析我的关注列表，给出今天最值得观察的三件事。
复盘我的历史交易胜率和最大回撤。
基于持仓和关注列表，生成下一周观察计划。
```

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

Use the bootstrap script for a first local setup:

```bash
bash scripts/bootstrap.sh
```

Or run the steps manually:

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

The portfolio dashboard can start without `DEEPSEEK_API_KEY`. The chat endpoint
will return a setup message until the key is configured.

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

Pre-trade guardrails:

```bash
MAX_TRADE_VALUE=100000
MAX_POSITION_WEIGHT=0.35
```

`MAX_TRADE_VALUE` blocks oversized single trades. `MAX_POSITION_WEIGHT` warns
when a new buy would make one symbol too concentrated in the cost-basis
portfolio. Sell orders are blocked when requested shares exceed current
holdings.

## Agent Internals

The assistant is intentionally split into deterministic components plus LLM
reasoning:

```text
User message
  -> classify_user_intent_tool
  -> parse_trade_instruction_tool, when trade-like
  -> portfolio_pretrade_check
  -> portfolio_record_trade, only when hard checks pass
  -> portfolio/watchlist/account analysis tools
  -> final answer
```

This keeps irreversible actions such as trade writes behind explicit structured
parsing and rule-based validation instead of relying only on model text.

The self-learning loop is deliberately explainable:

```text
Trade ledger
  -> FIFO round-trip reconstruction
  -> win/loss, profit factor, holding-period, and per-symbol statistics
  -> learned lessons and weak-pattern detection
  -> strategy rules for the next decision
  -> optional human-confirmed lessons saved as long-term memory
```

This is not a black-box predictive model. It is an auditable feedback loop that
helps the assistant avoid repeating the user's historically weak behaviors.

## What It Borrows From Popular Trading Agents

The project intentionally adapts practical ideas seen in active open-source
trading-agent projects without copying their code:

- Multi-agent investment committees from projects such as AutoHedge and
  TradingAgents-style systems.
- Layered memory from FinMem-style trading agents.
- Individual-stock plus portfolio context from TradingGoose-style research
  workflows.
- Risk-first decision gates before any persistent trade write.

In this project those ideas are implemented conservatively:

```text
Evidence collection
  -> technical analyst / risk manager / trade-memory reviewer
  -> cross-examination and risk veto checks
  -> coordinator arbitration
  -> critic review of missing evidence and execution risk
  -> BUY_CANDIDATE / WATCH / AVOID_OR_REDUCE
  -> pre-trade guard still required before any trade record
```

The committee is deterministic and testable. It provides decision evidence, not
automatic order execution.

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

GitHub Actions runs the same compile and fast test checks on pushes and pull
requests.

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
