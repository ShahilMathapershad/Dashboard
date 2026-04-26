"""Build a CachePayload from a fully-prepared monthly DataFrame.

Wraps `predict_next_month()` and `get_scenario_baseline()` to assemble
the structured cache payload that the dashboard hydrates from. The
`monthly_df` argument is honoured for the `data_through` metadata field;
the prediction logic itself reads from the cached `predict_next_month`
result (which fetches Supabase internally).
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone

import pandas as pd

from logic.cache_contract import (
    CACHE_CONTRACT_VERSION,
    CachePayload,
    CacheMetadata,
    HorizonForecast,
    FeatureContribution,
    FitHistoryPoint,
    ScenarioBaseline,
)
from logic.model.inference import predict_next_month
from logic.model.scenario import get_scenario_baseline

logger = logging.getLogger(__name__)
MODEL_VERSION = "huber-v1-2026-03-29"
FIT_HISTORY_MONTHS = 60

_HORIZON_LABEL_TO_INT = {"1m": 1, "3m": 3, "6m": 6}


def compute_full_predictions_payload(monthly_df: pd.DataFrame) -> CachePayload:
    """Compute the full dashboard cache payload.

    Args:
        monthly_df: DataFrame indexed by month-end Timestamp with all 11
            feature columns + ZAR_USD target. Used for `data_through`.

    Returns:
        CachePayload conforming to logic.cache_contract.
    """
    started = datetime.now(timezone.utc)

    pnm = predict_next_month()

    forecasts: list[HorizonForecast] = []
    for label, h in _HORIZON_LABEL_TO_INT.items():
        f = pnm.get("forecasts", {}).get(label)
        if not f:
            continue
        forecasts.append(
            HorizonForecast(
                horizon_months=h,
                forecast_zar_usd=float(f["point_estimate"]),
                forecast_date=f["date"],
            )
        )

    feature_contributions: list[FeatureContribution] = [
        FeatureContribution(
            feature=row["feature"],
            contribution=float(row["contribution"]),
            value=float(row.get("scaled_value", 0.0)),
        )
        for row in pnm.get("contributions", [])
    ]

    history = pnm.get("history", {})
    hist_dates = history.get("dates", [])
    hist_actual = history.get("actual", [])
    hist_predicted = history.get("predicted", [])
    fit_history: list[FitHistoryPoint] = [
        FitHistoryPoint(date=d, actual=float(a), predicted=float(p))
        for d, a, p in zip(hist_dates, hist_actual, hist_predicted)
    ][-FIT_HISTORY_MONTHS:]

    sb = get_scenario_baseline()
    feature_values = {
        p["raw_col"]: float(p["current_value"]) for p in sb.get("predictors", [])
    }
    scenario_baseline = ScenarioBaseline(
        feature_values=feature_values,
        baseline_forecast_1m=float(sb["base_prediction"]),
        baseline_date=sb["next_month_date"],
    )

    metadata = CacheMetadata(
        cache_contract_version=CACHE_CONTRACT_VERSION,
        model_version=MODEL_VERSION,
        computed_at=started.isoformat(),
        data_through=monthly_df.index[-1].strftime("%Y-%m-%d"),
        refresh_status="success",
    )

    return CachePayload(
        metadata=metadata,
        forecasts=forecasts,
        feature_contributions=feature_contributions,
        fit_history=fit_history,
        scenario_baseline=scenario_baseline,
    )
