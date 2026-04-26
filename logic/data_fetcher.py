"""Backwards-compat shim. The implementation now lives in `logic.data`.

Existing imports like `from logic.data_fetcher import fetch_fred_data`
continue to work unchanged. New code should import from `logic.data`.
"""
from __future__ import annotations
import argparse

from logic.data import *  # noqa: F401,F403
from logic.data import (  # noqa: F401  explicit re-exports
    fetch_fred_data,
    fetch_world_bank_gold_data,
    fetch_sa_inflation_hardcoded,
    get_sa_inflation,
    process_data,
    process_to_monthly,
    merge_sources,
    save_to_supabase,
    replace_gold_price_column_in_supabase,
    fetch_data_from_supabase,
    should_update_from_api,
    is_last_day_of_month,
    fetch_and_save_data,
    FRED_SERIES,
    SERIES_CONFIG,
    FRED_API_KEY,
)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Data fetch and Supabase sync")
    parser.add_argument(
        "--replace-gold-only",
        action="store_true",
        help="Fetch latest World Bank gold series and replace only GOLD_PRICE in Supabase.",
    )
    parser.add_argument(
        "--start-date",
        default="2009-12-31",
        help="Start date for gold replacement mode (YYYY-MM-DD).",
    )
    args = parser.parse_args()

    if args.replace_gold_only:
        gold_series = fetch_world_bank_gold_data(start_date=args.start_date)
        replace_gold_price_column_in_supabase(gold_series)
    else:
        fetch_and_save_data()
