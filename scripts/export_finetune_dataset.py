#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.training_data import build_watchlist_finetune_records, write_jsonl


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export provider-neutral JSONL fine-tuning records from stock_agent memory."
    )
    parser.add_argument(
        "--output",
        default="data/finetune/watchlist_decisions.jsonl",
        help="Output JSONL path. Defaults to data/finetune/watchlist_decisions.jsonl",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=500,
        help="Maximum notes to inspect per category.",
    )
    args = parser.parse_args()

    records = build_watchlist_finetune_records(limit=args.limit)
    result = write_jsonl(records, Path(args.output))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
