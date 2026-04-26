"""World Bank gold-price scrape, with bounded download + parse.

The legacy `pd.read_excel(live_url, ...)` had no timeout — pandas hands
the URL straight to urllib, which can hang forever. We download via
requests.get(timeout=20), then parse from BytesIO.
"""
from __future__ import annotations
import io
import logging
import re
import urllib.parse

import pandas as pd
import requests

logger = logging.getLogger(__name__)

PAGE_TIMEOUT_SECONDS = 15
WORKBOOK_TIMEOUT_SECONDS = 20
PAGE_URL = "https://www.worldbank.org/en/research/commodity-markets"


def _resolve_workbook_url() -> str | None:
    try:
        resp = requests.get(PAGE_URL, timeout=PAGE_TIMEOUT_SECONDS)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.warning("worldbank: page fetch failed: %s", e)
        return None

    match = re.search(
        r'href=["\']([^"\']*CMO-Historical-Data-Monthly\.xlsx(?:\?[^"\']*)?)["\']',
        resp.text, flags=re.IGNORECASE,
    )
    if not match:
        logger.warning("worldbank: workbook link not found on page.")
        return None

    href = match.group(1).strip()
    if href.startswith("//"):
        return f"https:{href}"
    if href.startswith("http"):
        return href
    if href.startswith("/"):
        return f"https://thedocs.worldbank.org{href}"
    return urllib.parse.urljoin(PAGE_URL, href)


def fetch_world_bank_gold_data(start_date: str = "2009-12-31", end_date=None) -> pd.Series:
    """Return a pd.Series of monthly gold prices keyed by date, or empty on failure.

    `start_date` / `end_date` preserve the legacy signature; the returned
    series is filtered to that window.
    """
    url = _resolve_workbook_url()
    if not url:
        return pd.Series(dtype="float64")

    try:
        resp = requests.get(url, timeout=WORKBOOK_TIMEOUT_SECONDS)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.warning("worldbank: workbook download failed: %s", e)
        return pd.Series(dtype="float64")

    try:
        df = pd.read_excel(io.BytesIO(resp.content), sheet_name="Monthly Prices", header=4)
    except Exception as e:
        logger.warning("worldbank: workbook parse failed: %s", e)
        return pd.Series(dtype="float64")

    if df is None or df.empty:
        return pd.Series(dtype="float64")

    df.columns = df.columns.astype(str).str.strip()
    df.rename(columns={df.columns[0]: "Date"}, inplace=True)

    gold_col = next((c for c in df.columns if str(c).strip().lower() == "gold"), None)
    if gold_col is None:
        logger.warning("worldbank: 'Gold' column missing from workbook.")
        return pd.Series(dtype="float64")

    out = df[["Date", gold_col]].iloc[1:].dropna(subset=[gold_col]).copy()
    out["Date"] = (
        out["Date"].astype(str).str.strip().str.replace("M", "-", regex=False)
    )
    out[gold_col] = pd.to_numeric(out[gold_col], errors="coerce")
    out["Date"] = pd.to_datetime(out["Date"], errors="coerce")
    out = out.dropna(subset=["Date", gold_col]).sort_values("Date")
    if out.empty:
        return pd.Series(dtype="float64")

    series = out.set_index("Date")[gold_col].rename("GOLD_PRICE")

    # Resample to month-end (legacy parity)
    try:
        series = series.resample("ME").last()
    except ValueError:
        series = series.resample("M").last()
    series = series.dropna()

    if end_date is None:
        end_date = pd.Timestamp.now().strftime("%Y-%m-%d")
    series = series.loc[start_date:end_date]
    series.name = "GOLD_PRICE"
    return series
