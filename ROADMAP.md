# Roadmap

## Next Fixes

- Improve mobile layout for the portfolio dashboard.
- Add a hosted demo deployment target for easier portfolio presentation.
- Add lightweight screenshots or a short demo script for interviews.
- Add an offline agent evaluation set for tool-selection accuracy.

## Nice To Have

- Add a small migration command for portfolio databases.
- Add structured logging configuration for production runs.
- Add a market-data cache health check with freshness and source metadata.
- Add configurable portfolio-level risk budgets by industry or strategy tag.

## Completed

- Add a one-command local bootstrap script.
- Add GitHub Actions for compile and test checks.
- Add a safer chat response when the LLM key is not configured.
- Add API-level tests for `/api/watchlist`, `/api/watchlist/quotes`, and
  `/api/holdings/rebuild`.
- Add agent showcase endpoints for profile, health, and demo prompts.
- Add LangChain tools for agent profile and secret-safe health checks.
- Add deterministic intent classification, trade parsing, and pre-trade risk
  guard tools.
- Add unit tests for trade parsing, risk blockers, and concentration warnings.

## Security Follow-Ups

- Keep real secrets only in local `.env`.
- Rotate any keys that may have appeared in local logs or screenshots.
- Remove deploy keys after one-off uploads unless they are still needed.
