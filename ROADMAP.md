# Roadmap

## Next Fixes

- Add API-level tests for `/api/watchlist`, `/api/watchlist/quotes`, and
  `/api/holdings/rebuild`.
- Add a safer startup mode for users who only want the portfolio dashboard and
  have not configured an LLM key yet.
- Add explicit health checks for the DSA bridge and market-data cache.
- Improve mobile layout for the portfolio dashboard.

## Nice To Have

- Add GitHub Actions for compile and test checks.
- Add a small migration command for portfolio databases.
- Add structured logging configuration for production runs.
- Add a one-command local bootstrap script.

## Security Follow-Ups

- Keep real secrets only in local `.env`.
- Rotate any keys that may have appeared in local logs or screenshots.
- Remove deploy keys after one-off uploads unless they are still needed.
