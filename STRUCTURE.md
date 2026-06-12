# Project Structure

This repo now has a lightweight, clearer layout without breaking existing imports.

Top-level (original):
- `app/` core backend logic and data access
- `web/` FastAPI app + HTML templates for the portfolio page
- `third_party/daily_stock_analysis/` DSA backend + SPA build output
- `data/`, `logs/`, `cache/` runtime data

Convenience views:
- `backend/app/` -> symlink to `app/`
- `backend/web/` -> symlink to `web/`
- `vendor/dsa/` -> symlink to `third_party/daily_stock_analysis/`

This keeps all existing imports/entrypoints working while presenting a cleaner
logical structure for navigation.
