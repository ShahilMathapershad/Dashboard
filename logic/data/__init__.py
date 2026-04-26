"""Compatibility shim: legacy callers import from `logic.data_fetcher`.

The split into submodules is invisible to callers because this package
re-exports the same names the old single file exposed (plus the
plan's modular aliases).
"""
from __future__ import annotations
import logging
import os

import pandas as pd

from logic.data.fred_source import (
    fetch_fred_data,
    FRED_SERIES,
    _unverified_ssl,
)
from logic.data.worldbank_source import fetch_world_bank_gold_data
from logic.data.static_inputs import (
    fetch_sa_inflation_hardcoded,
    get_sa_inflation,
)
from logic.data.processing import (
    process_data,
    process_to_monthly,
    merge_sources,
)
from logic.data.storage import (
    save_to_supabase,
    replace_gold_price_column_in_supabase,
    fetch_data_from_supabase,
)
from logic.data.freshness import (
    should_update_from_api,
    is_last_day_of_month,
)

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Legacy module-level constants (re-exported so existing callers keep working).
# ─────────────────────────────────────────────────────────────────────────────

FRED_API_KEY = os.environ.get("FRED_API_KEY")

SERIES_CONFIG = {
    "EPU(USA)": {"source": "FRED", "id": "USEPUINDXM", "label": "Economic Policy Uncertainty Index for USA"},
    "WUIZAF(SA)": {"source": "FRED", "id": "WUIZAF", "label": "World Uncertainty Index for South Africa"},
    "10_YEAR_BOND_RATES(USA)": {"source": "FRED", "id": "GS10", "label": "10-Year Treasury Constant Maturity Rate (USA)"},
    "10_YEAR_BOND_RATES(SA)": {"source": "FRED", "id": "IRLTLT01ZAM156N", "label": "10-Year Bond Rate (South Africa)"},
    "VIX": {"source": "FRED", "id": "VIXCLS", "label": "CBOE Volatility Index (VIX)"},
    "GOLD_PRICE": {"source": "WORLD_BANK", "id": "CMO-Historical-Data-Monthly.xlsx", "label": "World Bank Commodity Markets Monthly Gold Price"},
    "BRENT_OIL_PRICE": {"source": "FRED", "id": "POILBREUSDM", "label": "Global Price of Brent Crude"},
    "US_CPI": {"source": "FRED", "id": "CPIAUCSL", "label": "Consumer Price Index for All Urban Consumers (USA)"},
    "SA_INFLATION": {"source": "HARDCODED", "id": "SA_CPI_INDEX", "label": "South African Headline CPI Index"},
    "ZAR_USD": {"source": "FRED", "id": "DEXSFUS", "label": "ZAR/USD Exchange Rate"},
}


def fetch_and_save_data():
    """Main legacy orchestrator: fetch FRED + World Bank + SA inflation,
    process, then save to Supabase. Preserved for `python -m logic.data_fetcher`
    and for anything that imports `fetch_and_save_data` directly."""
    logger.info("Starting main data fetch and save workflow.")

    fred_series = {name: cfg["id"] for name, cfg in SERIES_CONFIG.items() if cfg["source"] == "FRED"}
    logger.info(f"Fetching {len(fred_series)} series from FRED.")
    raw_df = fetch_fred_data(fred_series)

    wb_gold = fetch_world_bank_gold_data(start_date="2009-12-31")
    sa_inflation = fetch_sa_inflation_hardcoded()

    raw_df = merge_sources(raw_df, wb_gold, sa_inflation)
    if raw_df.empty:
        logger.error("Failed to fetch any data from FRED.")
        return

    logger.info("Processing data.")
    processed_df = process_data(raw_df)

    logger.info(f"Processed data with {len(processed_df.columns)} factors.")
    logger.info(f"Columns included: {processed_df.columns.tolist()}")

    logger.info("Saving to Supabase.")
    save_resp = save_to_supabase(processed_df)
    replace_gold_price_column_in_supabase(wb_gold)
    return save_resp


__all__ = [
    # Plan-named API
    "fetch_fred_data",
    "FRED_SERIES",
    "fetch_world_bank_gold_data",
    "get_sa_inflation",
    "process_to_monthly",
    "merge_sources",
    "save_to_supabase",
    "replace_gold_price_column_in_supabase",
    "fetch_data_from_supabase",
    "should_update_from_api",
    # Legacy names (preserved verbatim from logic/data_fetcher.py)
    "fetch_sa_inflation_hardcoded",
    "process_data",
    "fetch_and_save_data",
    "is_last_day_of_month",
    "SERIES_CONFIG",
    "FRED_API_KEY",
    "_unverified_ssl",
]
