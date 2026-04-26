"""Opportunistic background refresh of the predictions cache.

Single-flight via threading.Lock — concurrent callers see status='skipped'
and return immediately. The lock is process-local; under gunicorn with
workers=1 (current Render config) that's fine. With workers>1 the worst
case is a few duplicate refreshes — still idempotent thanks to UPSERT.
"""
from __future__ import annotations
import concurrent.futures
import logging
import threading
import time

from logic.cache_contract import RefreshResult
from logic.data import (
    fetch_fred_data,
    fetch_world_bank_gold_data,
    get_sa_inflation,
    process_to_monthly,
    save_to_supabase,
    replace_gold_price_column_in_supabase,
)
from logic.model import compute_full_predictions_payload
from logic.predictions_cache.write import write_payload

logger = logging.getLogger(__name__)
_REFRESH_LOCK = threading.Lock()

FRED_RESULT_TIMEOUT = 20    # 15s internal + buffer
WB_RESULT_TIMEOUT = 25      # 20s internal + buffer


def refresh_async() -> RefreshResult:
    """Trigger a refresh. Returns immediately if one is already running."""
    if not _REFRESH_LOCK.acquire(blocking=False):
        logger.info("cache.refresh.skipped lock_held")
        return RefreshResult(status="skipped", reason="lock_held", payload=None, elapsed_ms=0)

    started = time.monotonic()
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
            fred_future = ex.submit(fetch_fred_data)
            wb_future = ex.submit(fetch_world_bank_gold_data)
            sa_data = get_sa_inflation()

            try:
                fred_df = fred_future.result(timeout=FRED_RESULT_TIMEOUT)
            except concurrent.futures.TimeoutError:
                logger.warning("cache.refresh.failed reason=fred_timeout")
                return RefreshResult(
                    status="failed", reason="fred_timeout", payload=None,
                    elapsed_ms=int((time.monotonic() - started) * 1000),
                )

            try:
                wb_series = wb_future.result(timeout=WB_RESULT_TIMEOUT)
            except concurrent.futures.TimeoutError:
                logger.warning("cache.refresh.failed reason=worldbank_timeout")
                return RefreshResult(
                    status="failed", reason="worldbank_timeout", payload=None,
                    elapsed_ms=int((time.monotonic() - started) * 1000),
                )

        if fred_df.empty:
            logger.warning("cache.refresh.failed reason=fred_empty")
            return RefreshResult(
                status="failed", reason="fred_empty", payload=None,
                elapsed_ms=int((time.monotonic() - started) * 1000),
            )

        monthly = process_to_monthly(fred_df, wb_series, sa_data)
        save_to_supabase(monthly)
        if not wb_series.empty:
            replace_gold_price_column_in_supabase(wb_series)

        payload = compute_full_predictions_payload(monthly)
        ok = write_payload(payload)
        if not ok:
            return RefreshResult(
                status="failed", reason="cache_write_failed", payload=None,
                elapsed_ms=int((time.monotonic() - started) * 1000),
            )

        elapsed_ms = int((time.monotonic() - started) * 1000)
        logger.info("cache.refresh.complete elapsed_ms=%d status=success", elapsed_ms)
        return RefreshResult(status="success", reason=None, payload=payload, elapsed_ms=elapsed_ms)
    finally:
        _REFRESH_LOCK.release()
