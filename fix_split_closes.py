"""Repair cached closing prices for stocks that have split.

Cached closes can be on different split bases for the same symbol (see
adjust_closes_for_splits in finra.py). This re-pulls adjusted prices for
every affected symbol.

  python fix_split_closes.py --dry-run          # see what it would do
  python fix_split_closes.py                    # the whole backlog (hours)
  python fix_split_closes.py --symbols TLRY,LCID --max-symbols 2

The full backlog is ~1 Polygon call per affected symbol at the shared
5/min limit, so it takes hours -- run it like backfill_history.py (point
the Cron Job's Start Command at it for one manual run, then switch back
to `python prewarm_cache.py`). It's resumable: handled splits are recorded
and skipped on re-run. prewarm_cache.py keeps up with new splits daily.
"""
import argparse

from finra import adjust_closes_for_splits


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--lookback-days", type=int, default=None,
                        help="only splits executed in the last N days (default: all stored history)")
    parser.add_argument("--symbols", default=None, help="comma-separated tickers to restrict to")
    parser.add_argument("--max-symbols", type=int, default=None)
    args = parser.parse_args()
    adjust_closes_for_splits(
        lookback_days=args.lookback_days,
        symbols=args.symbols.split(",") if args.symbols else None,
        dry_run=args.dry_run,
        max_symbols=args.max_symbols,
    )


if __name__ == '__main__':
    main()
