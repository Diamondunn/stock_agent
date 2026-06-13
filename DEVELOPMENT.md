# Development Guide

## Local Workflow

1. Activate the virtual environment.

```bash
source .venv/bin/activate
```

2. Run the fast project checks.

```bash
python -m compileall -q app web scripts tests
python -m pytest -q tests
```

3. Run the full suite before publishing.

```bash
python -m pytest -q
```

## Privacy Checklist

Before uploading or sharing the project, confirm these are not included:

- real `.env` values
- SQLite databases such as `portfolio.db` or `data/*.db`
- `cache/`, `logs/`, `.venv/`, `.pytest_cache/`
- generated upload folders or zip files
- deploy/private keys

Use the fake `.env` values only for public demos. Rotate any token that was ever
copied into a public page, screenshot, issue, or chat.

## Release Checklist

- Update `README.md` when setup or routes change.
- Add or update tests for watchlist, portfolio, and market-time behavior.
- Run the full test suite.
- Verify `.env` contains only dummy values in the public repository.
- Confirm `third_party/daily_stock_analysis` is handled as third-party code, not
  mixed into local application edits unless intentionally vendored.

## GitHub Sync

When automated upload is unavailable, run:

```bash
bash scripts/sync_to_github.sh
```

The script clones the GitHub repository into `/tmp`, copies only safe project
files, commits the changes, and pushes them. It deliberately excludes real
`.env`, databases, caches, logs, virtual environments, and upload artifacts.

## Current Architecture Notes

- `app/` contains core portfolio, market-data, tool, and chat logic.
- `web/` contains the FastAPI integration and the portfolio dashboard template.
- `third_party/daily_stock_analysis/` is an upstream project used through
  `app/dsa_bridge.py`.
- `backend/` and `vendor/` are convenience symlinks for navigation.
