"""Hardcoded SA Headline CPI series (StatsSA).

Moved verbatim from logic/data_fetcher.py::fetch_sa_inflation_hardcoded.
"""
from __future__ import annotations
import logging

import pandas as pd

logger = logging.getLogger(__name__)


def fetch_sa_inflation_hardcoded() -> pd.DataFrame:
    """Returns the hardcoded SA_INFLATION data as a DataFrame starting from 2009-12-31."""
    # Official StatsSA Headline CPI (Base: Dec 2024 = 100)
    # 2009-2024 are published index values. 2025-2026 are derived from
    # StatsSA YoY % changes applied to the 2024 index
    # (YoY source: StatsSA P0141 — see SA_CPI_YOY_RATES below).
    cpi_values = [
        48.0,  # 2009 Dec
        48.1, 48.4, 48.8, 48.8, 48.9, 48.9, 49.3, 49.3, 49.4, 49.4, 49.5, 49.6,  # 2010
        49.9, 50.1, 50.7, 50.9, 51.2, 51.4, 51.9, 51.9, 52.2, 52.4, 52.5, 52.6,  # 2011
        53.0, 53.2, 53.8, 54.1, 54.1, 54.3, 54.3, 54.5, 55.0, 55.3, 55.5, 55.6,  # 2012
        55.8, 56.3, 57.0, 57.2, 57.0, 57.2, 57.8, 58.0, 58.3, 58.4, 58.5, 58.7,  # 2013
        59.0, 59.7, 60.5, 60.7, 60.8, 61.0, 61.5, 61.8, 61.8, 61.8, 61.8, 61.8,  # 2014
        61.6, 62.0, 62.9, 63.5, 63.7, 63.9, 64.6, 64.6, 64.6, 64.8, 64.8, 64.9,  # 2015
        65.5, 66.3, 66.8, 67.4, 67.5, 67.9, 68.5, 68.4, 68.5, 68.8, 69.1, 69.3,  # 2016
        69.8, 70.5, 71.0, 71.0, 71.2, 71.4, 71.6, 71.7, 72.0, 72.2, 72.3, 72.6,  # 2017
        72.8, 73.4, 73.6, 74.2, 74.3, 74.6, 75.3, 75.2, 75.5, 75.9, 76.0, 75.9,  # 2018
        75.7, 76.3, 77.0, 77.4, 77.7, 78.0, 78.2, 78.5, 78.6, 78.6, 78.7, 78.9,  # 2019
        79.2, 79.9, 80.2, 79.8, 79.2, 79.7, 80.7, 80.9, 81.0, 81.2, 81.2, 81.3,  # 2020
        81.7, 82.2, 82.8, 83.3, 83.4, 83.5, 84.5, 84.8, 85.0, 85.3, 85.6, 86.1,  # 2021
        86.3, 86.8, 87.7, 88.2, 88.8, 89.8, 91.1, 91.3, 91.4, 91.7, 92.0, 92.3,  # 2022
        92.2, 92.9, 93.9, 94.2, 94.4, 94.6, 95.4, 95.7, 96.3, 97.2, 97.1, 97.1,  # 2023
        97.2, 98.1, 98.9, 99.1, 99.3, 99.4, 99.8, 99.9, 100.0, 99.9, 99.9, 100.0,  # 2024
        # 2025: derived from 2024 index × (1 + YoY/100)
        # YoY rates: 5.3, 5.6, 5.3, 5.2, 4.6, 5.1, 4.8, 4.4, 3.8, 3.4, 3.5, 3.6
        102.4, 103.6, 104.1, 104.3, 103.9, 104.5, 104.6, 104.3, 103.8, 103.3, 103.4, 103.6,
        # 2026 Jan-Feb: YoY 3.5, 3.0
        106.0, 106.7,
    ]

    try:
        dates = pd.date_range(start="2009-12-31", end="2026-02-28", freq="ME")
    except ValueError:
        dates = pd.date_range(start="2009-12-31", end="2026-02-28", freq="M")

    df_cpi = pd.DataFrame({"SA_INFLATION": cpi_values}, index=dates)
    df_cpi.index.name = "Date"
    return df_cpi


# Plan-named alias (keeps the new modular API consistent).
def get_sa_inflation() -> pd.DataFrame:
    return fetch_sa_inflation_hardcoded()
