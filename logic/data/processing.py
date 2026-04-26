"""DataFrame processing helpers — moved from logic/data_fetcher.py.

`process_data` (legacy) handles sort/resample/ffill/bfill/window-trim and
returns the canonical column ordering. `merge_sources` is a thin
convenience wrapper used by the new orchestrator.
"""
from __future__ import annotations
import logging

import pandas as pd

logger = logging.getLogger(__name__)


def _to_monthly(series):
    """Normalize any date-indexed series to month-end frequency."""
    if series.empty:
        return series
    series = series.sort_index()
    try:
        monthly = series.resample("ME").last()
    except ValueError:
        monthly = series.resample("M").last()
    return monthly.dropna()


def process_data(final_df, start_date="2009-12-31", end_date=None):
    """Processes the raw data (sorting, resampling, filling, etc.).

    Moved verbatim from the legacy logic/data_fetcher.py — kept identical
    column-order and 15-year-window behaviour so existing dashboard code
    sees the same shape.
    """
    if end_date is None:
        now = pd.Timestamp.now()
        end_of_prev_month = (now.replace(day=1) - pd.Timedelta(days=1))
        end_date = end_of_prev_month.strftime("%Y-%m-%d")

    # LIMIT DATA RANGE: Render's 512MB limit. 15 years of monthly data is
    # plenty for the rolling/lag features.
    limit_date = (pd.to_datetime(end_date) - pd.DateOffset(years=15)).strftime("%Y-%m-%d")
    if start_date < limit_date:
        start_date = limit_date
        logger.info(f"Limiting start_date to {start_date} for memory efficiency.")

    final_df = final_df.sort_index()
    final_df = final_df.loc[start_date:]

    try:
        final_df_monthly = final_df.resample("ME").last()
    except ValueError:
        final_df_monthly = final_df.resample("M").last()

    final_df_monthly = final_df_monthly.ffill().bfill()
    final_df_monthly = final_df_monthly.loc[start_date:end_date]

    columns_to_keep = [
        "EPU(USA)",
        "WUIZAF(SA)",
        "10_YEAR_BOND_RATES(USA)",
        "10_YEAR_BOND_RATES(SA)",
        "VIX",
        "GOLD_PRICE",
        "BRENT_OIL_PRICE",
        "US_CPI",
        "SA_INFLATION",
        "ZAR_USD",
    ]
    existing_columns = [col for col in columns_to_keep if col in final_df_monthly.columns]
    final_df_monthly = final_df_monthly[existing_columns]

    if "ZAR_USD" in final_df_monthly.columns:
        final_df_monthly = final_df_monthly.dropna(subset=["ZAR_USD"])

    final_df_monthly.index.name = "Date"
    return final_df_monthly


def merge_sources(fred_df, gold_series, sa_inflation_df) -> pd.DataFrame:
    """Concat the three raw sources into one wide DataFrame (legacy parity).

    The orchestrator (fetch_and_save_data) used to do this inline; here we
    expose it as a named helper for cleaner unit testing.
    """
    df = fred_df.copy() if fred_df is not None else pd.DataFrame()
    if gold_series is not None and not gold_series.empty:
        df = pd.concat([df, gold_series.to_frame(name="GOLD_PRICE")], axis=1)
    else:
        logger.warning("GOLD_PRICE could not be loaded from World Bank.")
    if sa_inflation_df is not None and not sa_inflation_df.empty:
        df = pd.concat([df, sa_inflation_df], axis=1)
    return df


# Plan-named alias.
def process_to_monthly(final_df, start_date="2009-12-31", end_date=None):
    return process_data(final_df, start_date=start_date, end_date=end_date)
