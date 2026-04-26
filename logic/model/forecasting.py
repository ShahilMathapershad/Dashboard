"""Multi-horizon iterative forecasting.

`multi_horizon_forecast()` projects ZAR/USD forward 1, 3, and 6 months by
iteratively re-engineering features after each predicted step (assuming
macro drivers persist at their last observed values).

`_iterate_forecast()` is a thin reusable helper that runs the iteration
loop on an arbitrary raw DataFrame — used both by this module and the
fair-value computation in `inference.predict_next_month`.

NOTE: The legacy `predict_next_month()` (in `inference.py`) computes the
horizon forecasts inline as part of its god-function payload. This module
exposes the same logic under the new-API name Task 5 expects, plus a thin
adapter that keeps the legacy behaviour reachable.
"""
from logic.model.inference import predict_next_month
from logic.model.loading import load_model
from logic.model.features import engineer_features


def _iterate_forecast(raw_df, horizons=(1, 3, 6)):
    """Iteratively predict ZAR/USD for each horizon by appending each step's
    prediction back into the DataFrame and re-engineering features.

    Args:
        raw_df: pandas DataFrame with at least the last ~30 months of raw
            macro columns (ZAR_USD, VIX, EPU(USA), etc.).
        horizons: iterable of integer horizons (months ahead).

    Returns:
        dict {h: {"forecast": float, "forecast_date": Timestamp}} for each
        horizon in `horizons` that was reached.
    """
    import pandas as pd

    model_data = load_model()
    pipeline = model_data['pipeline']
    feature_names = model_data['feature_names']

    iterative_df = raw_df.tail(30).copy()
    h_levels = {}
    horizon_set = set(horizons)
    max_h = max(horizons) if horizons else 0

    for i in range(1, max_h + 1):
        try:
            df_feat_iter, _ = engineer_features(iterative_df, bypass_cache=True)
            if df_feat_iter.empty:
                break
            X_iter = df_feat_iter.iloc[[-1]][feature_names]
            next_level = float(pipeline.predict(X_iter)[0])
            next_date = iterative_df.index[-1] + pd.offsets.MonthEnd(1)
            iterative_df.loc[next_date] = iterative_df.iloc[-1]
            iterative_df.loc[next_date, 'ZAR_USD'] = next_level

            if i in horizon_set:
                h_levels[i] = {"forecast": next_level, "forecast_date": next_date}
        except Exception:
            break

    return h_levels


def multi_horizon_forecast(features=None, horizons=(1, 3, 6)):
    """Return the legacy `predict_next_month` forecasts dict, keyed by
    integer horizon for the new-API contract Task 5 expects.

    When `features` is None, falls back to the cached `predict_next_month`
    result (which iterates on the live Supabase data internally). When a
    raw DataFrame is supplied, runs `_iterate_forecast` directly so callers
    can forecast from arbitrary input.

    Returns:
        dict {h: {"forecast": float, "forecast_date": Timestamp}}
    """
    if features is not None and hasattr(features, 'iloc') and 'ZAR_USD' in features.columns:
        # Caller passed a raw monthly DataFrame — iterate from it directly.
        return _iterate_forecast(features, horizons=horizons)

    # Default path: piggy-back on the cached `predict_next_month` result.
    import pandas as pd
    result = predict_next_month()
    forecasts = result.get('forecasts', {})
    label_to_h = {'1m': 1, '3m': 3, '6m': 6}
    out = {}
    for label, h in label_to_h.items():
        if h not in horizons:
            continue
        if label not in forecasts:
            continue
        f = forecasts[label]
        out[h] = {
            "forecast": float(f['point_estimate']),
            "forecast_date": pd.Timestamp(f['date']),
        }
    return out
