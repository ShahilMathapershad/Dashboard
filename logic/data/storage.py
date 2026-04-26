"""Supabase persistence with hard timeouts.

Every `supabase.table(...).execute()` site is wrapped in
`_with_supabase_timeout(...)` so a hung Supabase call can't wedge the
worker — it returns None within SUPABASE_TIMEOUT_SECONDS instead.
"""
from __future__ import annotations
import concurrent.futures
import logging
import time

import pandas as pd

from logic.supabase_client import get_supabase

logger = logging.getLogger(__name__)

SUPABASE_TIMEOUT_SECONDS = 10


def _with_supabase_timeout(fn, *args, **kwargs):
    """Run a Supabase call with a hard timeout. Returns None on timeout/error."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        future = ex.submit(fn, *args, **kwargs)
        try:
            return future.result(timeout=SUPABASE_TIMEOUT_SECONDS)
        except concurrent.futures.TimeoutError:
            logger.warning("supabase: TIMEOUT after %ds — returning None", SUPABASE_TIMEOUT_SECONDS)
            return None
        except Exception as exc:
            logger.warning("supabase: call failed: %s", exc)
            return None


# In-process cache for fetch_data_from_supabase (mirrors the model.py cache,
# but keeps storage self-contained).
_fetched_cache: dict = {"df": None, "time": 0.0}
_FETCH_CACHE_TTL_SECONDS = 300


def fetch_data_from_supabase() -> pd.DataFrame:
    """Fetch recent rows from the Supabase 'data' table.

    NEW in the split: this function did not exist on the legacy
    logic/data_fetcher module — it lived only in logic/model.py. We expose
    it here too so callers can grab data without pulling the model module.
    Wrapped with a hard timeout so a hung Supabase request cannot wedge
    the worker.
    """
    now = time.time()
    if _fetched_cache["df"] is not None and (now - _fetched_cache["time"] < _FETCH_CACHE_TTL_SECONDS):
        return _fetched_cache["df"].copy()

    supabase = get_supabase()
    if not supabase:
        logger.warning("fetch_data_from_supabase: Supabase client not initialised.")
        return pd.DataFrame()

    resp = _with_supabase_timeout(
        lambda: supabase.table("data").select("*").order("Date", desc=True).limit(500).execute()
    )
    if resp is None:
        return pd.DataFrame()
    rows = resp.data or []
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df["Date"] = pd.to_datetime(df["Date"])
    df.set_index("Date", inplace=True)
    df = df.apply(pd.to_numeric, errors="coerce")
    df = df.sort_index()

    _fetched_cache["df"] = df
    _fetched_cache["time"] = now
    return df.copy()


def save_to_supabase(df):
    """Saves the processed DataFrame to the Supabase 'data' table."""
    if df.empty:
        logger.warning("No data to save.")
        return

    df_to_save = df.reset_index()
    df_to_save["Date"] = df_to_save["Date"].dt.strftime("%Y-%m-%d")
    df_to_save = df_to_save.where(pd.notnull(df_to_save), None)
    records = df_to_save.to_dict("records")

    for record in records:
        for key, value in record.items():
            if pd.isna(value):
                record[key] = None

    logger.info(f"Saving {len(records)} records to Supabase 'data' table...")

    supabase = get_supabase()
    if not supabase:
        logger.error("Supabase client not initialized.")
        return None

    try:
        valid_columns = {
            "Date", "EPU(USA)", "WUIZAF(SA)", "10_YEAR_BOND_RATES(USA)",
            "10_YEAR_BOND_RATES(SA)", "VIX",
            "GOLD_PRICE", "BRENT_OIL_PRICE", "US_CPI", "SA_INFLATION", "ZAR_USD",
        }

        filtered_records = []
        for record in records:
            filtered_record = {k: v for k, v in record.items() if k in valid_columns}
            filtered_records.append(filtered_record)

        logger.info("Upserting data into Supabase...")
        chunk_size = 500
        for i in range(0, len(filtered_records), chunk_size):
            chunk = filtered_records[i:i + chunk_size]
            _with_supabase_timeout(lambda c=chunk: supabase.table("data").upsert(c).execute())

        # Bounded prune: drop rows older than the 15-year lookback window.
        try:
            cutoff = (pd.Timestamp.now() - pd.DateOffset(years=15)).strftime("%Y-%m-%d")
            _with_supabase_timeout(lambda: supabase.table("data").delete().lt("Date", cutoff).execute())
            logger.info(f"Pruned rows older than {cutoff}.")
        except Exception as prune_err:
            logger.warning(f"Could not prune old rows: {prune_err}")

        logger.info("Successfully saved data to Supabase.")
        return None
    except Exception as e:
        logger.error(f"Error saving to Supabase: {e}")
        return None


def replace_gold_price_column_in_supabase(gold_series):
    """Upsert only Date + GOLD_PRICE into Supabase, replacing GOLD_PRICE for existing dates."""
    if gold_series is None or gold_series.empty:
        logger.warning("No GOLD_PRICE series provided for Supabase replacement.")
        return None

    supabase = get_supabase()
    if not supabase:
        logger.error("Supabase client not initialized.")
        return None

    gold_df = gold_series.dropna().to_frame(name="GOLD_PRICE").reset_index()
    gold_df.rename(columns={gold_df.columns[0]: "Date"}, inplace=True)
    gold_df["Date"] = pd.to_datetime(gold_df["Date"], errors="coerce")
    gold_df["DateKey"] = gold_df["Date"].dt.strftime("%Y-%m-%d")
    gold_df["Date"] = gold_df["Date"].dt.strftime("%Y-%m-%d")
    gold_df["GOLD_PRICE"] = pd.to_numeric(gold_df["GOLD_PRICE"], errors="coerce")
    gold_df = gold_df.dropna(subset=["Date", "DateKey", "GOLD_PRICE"])

    records = gold_df.to_dict("records")
    if not records:
        logger.warning("No valid GOLD_PRICE records to upsert.")
        return None

    # Keep updates scoped to rows that already exist in the data table.
    try:
        existing_resp = _with_supabase_timeout(
            lambda: supabase.table("data").select("Date").gte("Date", "1900-01-01").execute()
        )
        existing_rows = (existing_resp.data if existing_resp is not None else []) or []
        existing_dates = {
            str(row.get("Date"))[:10]
            for row in existing_rows
            if row.get("Date")
        }
        if existing_dates:
            records = [row for row in records if row["DateKey"] in existing_dates]
    except Exception as e:
        logger.warning(f"Could not prefetch existing dates for GOLD_PRICE replacement: {e}")

    if not records:
        logger.warning("No matching Supabase dates found for GOLD_PRICE replacement.")
        return None

    for row in records:
        row.pop("DateKey", None)

    logger.info(f"Replacing GOLD_PRICE in Supabase for {len(records)} dates.")
    try:
        chunk_size = 500
        for i in range(0, len(records), chunk_size):
            chunk = records[i:i + chunk_size]
            _with_supabase_timeout(lambda c=chunk: supabase.table("data").upsert(c).execute())
        logger.info("Successfully replaced GOLD_PRICE column in Supabase.")
        return {"updated_rows": len(records)}
    except Exception as e:
        logger.error(f"Error replacing GOLD_PRICE in Supabase: {e}")
        return None
