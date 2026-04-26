"""Decide whether to hit the FRED/World-Bank APIs or read cached Supabase rows.

Moved from logic/data_fetcher.py — the Supabase select is wrapped in
`_with_supabase_timeout` so a hung roundtrip can't wedge the worker.
"""
from __future__ import annotations
import datetime
import logging
import time

import pandas as pd

from logic.data.storage import _with_supabase_timeout
from logic.supabase_client import get_supabase

logger = logging.getLogger(__name__)


def is_last_day_of_month() -> bool:
    """Check if today is the last day of the month."""
    today = datetime.date.today()
    next_day = today + datetime.timedelta(days=1)
    return next_day.month != today.month


_should_update_cache = {"value": None, "time": 0}


def should_update_from_api() -> bool:
    """
    Decide whether to fetch from APIs or pull from Supabase.
    Returns True if today is the last day of the month AND Supabase doesn't
    have today's month data yet.

    Result is cached in-process for 5 minutes — without this, every dashboard
    fetch_data invocation pays a ~100–300ms Supabase round-trip just to learn
    that the answer is "no, use cached data".
    """
    now_ts = time.time()
    if _should_update_cache["value"] is not None and (now_ts - _should_update_cache["time"] < 300):
        return _should_update_cache["value"]

    if not is_last_day_of_month():
        logger.info("should_update_from_api: False (not last day of month)")
        _should_update_cache.update({"value": False, "time": now_ts})
        return False

    supabase = get_supabase()
    if not supabase:
        logger.warning("should_update_from_api: True (no Supabase client)")
        _should_update_cache.update({"value": True, "time": now_ts})
        return True

    try:
        resp = _with_supabase_timeout(
            lambda: supabase.table("data").select("Date").order("Date", desc=True).limit(1).execute()
        )
        if resp is None:
            logger.warning("should_update_from_api: True (Supabase timed out)")
            _should_update_cache.update({"value": True, "time": now_ts})
            return True
        if not resp.data:
            logger.info("should_update_from_api: True (Supabase empty)")
            _should_update_cache.update({"value": True, "time": now_ts})
            return True

        latest_date_str = resp.data[0]["Date"]
        latest_date = pd.to_datetime(latest_date_str)

        today = pd.Timestamp.now()
        if latest_date.year == today.year and latest_date.month == today.month:
            logger.info(f"should_update_from_api: False (Latest date {latest_date.date()} is already from this month)")
            _should_update_cache.update({"value": False, "time": now_ts})
            return False

        logger.info(f"should_update_from_api: True (Latest date {latest_date.date()} is old)")
        _should_update_cache.update({"value": True, "time": now_ts})
        return True
    except Exception as e:
        logger.error(f"Error checking Supabase for latest date: {e}")
        return True
