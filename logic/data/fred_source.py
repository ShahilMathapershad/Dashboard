"""FRED API fetch with bounded execution time.

The legacy code (logic/data_fetcher.py) called fred.get_series() without
a timeout — a wedged TCP connection could hang the whole process. We
wrap each series fetch in a ThreadPoolExecutor.future.result(timeout=15)
so a stuck call raises TimeoutError instead of hanging.
"""
from __future__ import annotations
import concurrent.futures
import logging
import os
import ssl
import threading
import time
from contextlib import contextmanager

import pandas as pd
from fredapi import Fred

logger = logging.getLogger(__name__)

PER_SERIES_TIMEOUT_SECONDS = 15

# Process-wide lock to serialize the global SSL-context mutation in
# `_unverified_ssl`. Without it, two concurrent calls would interleave their
# enter/exit and leave the global stuck in "unverified" mode permanently.
_ssl_lock = threading.Lock()

# Same series dict as logic/data_fetcher.py — kept here as the single source of truth.
FRED_SERIES: dict[str, str] = {
    "ZAR_USD": "DEXSFUS",
    "VIX": "VIXCLS",
    "EPU_USA": "USEPUINDXD",
    "WUIZAF_SA": "WUIZAF",
    "BRENT_OIL": "DCOILBRENTEU",
    "US_CPI": "CPIAUCSL",
    "ZA_10Y_BOND": "IRLTLT01ZAM156N",
    "US_10Y_BOND": "DGS10",
}


@contextmanager
def _unverified_ssl():
    """FRED occasionally serves with stale intermediate certs; legacy parity.
    Serialized via _ssl_lock so concurrent callers don't corrupt the global."""
    with _ssl_lock:
        old_default = ssl._create_default_https_context
        ssl._create_default_https_context = ssl._create_unverified_context
        try:
            yield
        finally:
            ssl._create_default_https_context = old_default


def _fetch_one(fred: Fred, name: str, series_id: str, start_date: str) -> pd.DataFrame:
    with _unverified_ssl():
        s = fred.get_series(series_id, observation_start=start_date)
    return s.to_frame(name=name)


def fetch_fred_data(series_dict=None, api_key=None, start_date: str = "2009-12-31", progress_callback=None) -> pd.DataFrame:
    """Fetch FRED series with a hard per-series timeout.

    Backwards-compatible signature — the legacy callers passed (series_dict,
    api_key, start_date, progress_callback). When `series_dict` is None we
    fall back to the module-level FRED_SERIES.
    """
    if api_key is None:
        api_key = os.getenv("FRED_API_KEY")
    if not api_key:
        logger.error("FRED_API_KEY not set; returning empty DataFrame.")
        return pd.DataFrame()

    if series_dict is None:
        series_dict = FRED_SERIES

    try:
        with _unverified_ssl():
            fred = Fred(api_key=api_key)
    except Exception as e:
        logger.error(f"Error initializing FRED with provided key: {e}")
        return pd.DataFrame()

    frames: list[pd.DataFrame] = []
    total = len(series_dict)
    for i, (name, series_id) in enumerate(series_dict.items()):
        percent_start = int((i / total) * 100) if total else 0
        if progress_callback:
            progress_callback(percent_start, f"Fetching {name}...")

        # Use a fresh executor per series so the timeout actually unblocks
        # us. With a shared executor's `with` block, __exit__ would wait
        # for the hung worker thread to finish before returning. Instead
        # we shutdown(wait=False) — the daemon thread is abandoned and
        # the process can move on. The thread is daemon-by-default in
        # ThreadPoolExecutor, so it dies with the process if it never
        # completes.
        ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        try:
            future = ex.submit(_fetch_one, fred, name, series_id, start_date)
            try:
                df = future.result(timeout=PER_SERIES_TIMEOUT_SECONDS)
                frames.append(df)
                logger.info("fetch_fred_data: got %s (%s) rows=%d", name, series_id, len(df))
                percent_done = int(((i + 1) / total) * 100) if total else 100
                if progress_callback:
                    progress_callback(percent_done, f"Fetched {name}")
            except concurrent.futures.TimeoutError:
                logger.warning(
                    "fetch_fred_data: TIMEOUT after %ds on %s (%s) — skipping",
                    PER_SERIES_TIMEOUT_SECONDS, name, series_id,
                )
                if progress_callback:
                    progress_callback(int(((i + 1) / total) * 100) if total else 100, f"Timeout: {name}")
            except Exception as exc:
                logger.warning("fetch_fred_data: error on %s: %s — skipping", name, exc)
                if progress_callback:
                    progress_callback(int(((i + 1) / total) * 100) if total else 100, f"Error: {name}")
        finally:
            # Don't wait for the worker thread to finish. cancel_futures
            # is Python 3.9+; if the future is already running it can't be
            # cancelled, but we still don't block.
            try:
                ex.shutdown(wait=False, cancel_futures=True)
            except TypeError:
                ex.shutdown(wait=False)
        time.sleep(0.5)  # avoid FRED rate-limit

    if progress_callback:
        progress_callback(100, "Processing data...")

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, axis=1, sort=True)
