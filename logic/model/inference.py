"""Single-step inference + the legacy `predict_next_month` orchestrator.

`predict_next_month()` is the historical god-function: one prediction call
plus contributions, historical fit, diagnostics, multi-horizon forecasts,
and fair-value computation. Splitting it would change behaviour, so it
lives here intact (Task 4 instructions: do not split functions silently).

`predict_one()` is the small new-API helper Task 5 expects: take an
already-engineered feature row, return the predicted level as a float.
"""
import os
import time

import logging

from logic.model.loading import (
    JOBLIB_IMPORT_ERROR,
    TRAIN_ONLY_MODEL_PATH,
    _persistent_cache,
    fetch_data_from_supabase,
    joblib,
    load_model,
)
from logic.model.features import (
    engineer_features,
    get_feature_category,
    get_friendly_feature_name,
)

logger = logging.getLogger("ModelPredictor")

_predict_next_month_cache = {'result': None, 'time': 0}
_test_set_cache = {'result': None, 'time': 0}


def predict_one(features_row):
    """Predict the next-month ZAR/USD level for a single engineered feature row.

    Args:
        features_row: A pandas DataFrame with a single row containing the 11
        columns in `FEATURE_LIST`, OR a full feature DataFrame (the last row
        is taken).

    Returns:
        float — predicted next-month ZAR/USD level.
    """
    model_data = load_model()
    pipeline = model_data['pipeline']
    feature_names = model_data['feature_names']

    if features_row.shape[0] != 1:
        features_row = features_row.iloc[[-1]]

    X = features_row[feature_names]
    return float(pipeline.predict(X)[0])


def predict_next_month():
    """
    Generate a ZAR/USD prediction for the next month using the frozen HuberRegressor pipeline.
    The model predicts the ZAR/USD level directly (error-correction framework).
    Returns a dict with prediction details.
    """
    import pandas as pd
    import numpy as np
    global _predict_next_month_cache
    now = time.time()

    # Check in-memory cache
    if _predict_next_month_cache['result'] is not None and (now - _predict_next_month_cache['time'] < 300):
        logger.info("predict_next_month: returning in-memory cached result")
        return _predict_next_month_cache['result']

    # Check persistent disk cache
    _pnm_cache_key = "predict_next_month_result"
    _cached = _persistent_cache.get(_pnm_cache_key)
    if _cached is not None:
        _predict_next_month_cache = {'result': _cached, 'time': now}
        logger.info("predict_next_month: returning disk-cached result")
        return _cached

    model_data = load_model()
    pipeline = model_data['pipeline']
    regressor = model_data['regressor']
    preprocessor = model_data['preprocessor']
    feature_names = model_data['feature_names']
    stored_metrics = model_data['evaluation_metrics']

    raw_df = fetch_data_from_supabase()
    df_features, df_raw = engineer_features(raw_df)

    if df_features.empty:
        raise ValueError("Not enough data to compute features.")

    # ── NEXT MONTH PREDICTION ──
    # Features at time T predict S_{T+1}
    X_latest = df_features.iloc[[-1]][feature_names]
    predicted_level = float(pipeline.predict(X_latest)[0])

    last_zar_usd = float(raw_df['ZAR_USD'].dropna().iloc[-1])
    predicted_change = predicted_level - last_zar_usd
    predicted_change_pct = (predicted_change / last_zar_usd) * 100

    if predicted_change_pct > 0.05:
        direction = 'weaken'
    elif predicted_change_pct < -0.05:
        direction = 'strengthen'
    else:
        direction = 'stable'

    # ── FEATURE CONTRIBUTIONS ──
    # Transform features through preprocessor to get scaled values
    X_transformed = preprocessor.transform(X_latest)
    contributions = []
    for j, feat in enumerate(feature_names):
        coef = float(regressor.coef_[j])
        scaled_val = float(X_transformed[0, j])
        contribution = coef * scaled_val
        category = get_feature_category(feat)

        # Unscaled coefficient: effect per 1-unit change in raw feature
        if category == 'passthrough':
            unscaled_coef = coef
        elif model_data['scaler'] is not None:
            # Passthrough is index 0, scaler handles indices 1-10
            # The scaler column index is j-1 (since passthrough takes index 0)
            scaler_idx = j - 1
            if 0 <= scaler_idx < len(model_data['scaler'].scale_):
                unscaled_coef = coef / model_data['scaler'].scale_[scaler_idx]
            else:
                unscaled_coef = coef
        else:
            unscaled_coef = coef

        contributions.append({
            'feature': feat,
            'coefficient': coef,
            'unscaled_coefficient': float(unscaled_coef),
            'category': category,
            'scaled_value': scaled_val,
            'contribution': contribution,
        })

    contributions.sort(key=lambda x: abs(x['contribution']), reverse=True)

    # ── HISTORICAL FIT ──
    # Features at time t predict S_{t+1}; actual S_{t+1} = raw_df['ZAR_USD'].shift(-1)
    target = raw_df['ZAR_USD'].shift(-1)
    target_aligned = target.reindex(df_features.index).dropna()

    # Limit to last 120 data points for chart
    recent_count = min(120, len(target_aligned))
    target_recent = target_aligned.tail(recent_count)
    features_recent = df_features.loc[target_recent.index, feature_names]

    hist_pred_levels = pipeline.predict(features_recent)
    hist_actual_levels = target_recent.values

    # Clean NaN
    valid_mask = ~(np.isnan(hist_actual_levels) | np.isnan(hist_pred_levels))
    hist_actual_levels = hist_actual_levels[valid_mask]
    hist_pred_levels = hist_pred_levels[valid_mask]
    hist_feature_dates = target_recent.index[valid_mask]

    # Chart dates = prediction dates (one month after feature date).
    # Use vectorized get_indexer instead of per-element get_loc (O(n) vs O(n²)).
    raw_index = raw_df.index
    raw_len = len(raw_index)
    positions = raw_index.get_indexer(hist_feature_dates)
    hist_chart_dates = [
        raw_index[p + 1] if (p >= 0 and p + 1 < raw_len)
        else (hist_feature_dates[i] + pd.offsets.MonthEnd(1))
        for i, p in enumerate(positions)
    ]

    # Limit to 60 months for UI
    chart_limit = 60
    if len(hist_chart_dates) > chart_limit:
        hist_chart_dates = hist_chart_dates[-chart_limit:]
        hist_actual_levels = hist_actual_levels[-chart_limit:]
        hist_pred_levels = hist_pred_levels[-chart_limit:]

    # ── VALIDATION METRICS ──
    # All metrics loaded from pkl (computed on the proper OOS test split at train time).
    test_metrics = stored_metrics.get('test', {})
    mae = float(test_metrics.get('MAE', 0))
    rmse = float(test_metrics.get('RMSE', 0))
    r2 = float(test_metrics.get('R2', 0))
    adjusted_r2 = float(stored_metrics.get('adjusted_r2_test', 0))
    directional_accuracy = float(stored_metrics.get('directional_accuracy_test', 0)) * 100
    theils_u = float(stored_metrics.get('theils_u_test', 0))
    mape = float(test_metrics.get('MAPE', 0))

    # ── DIAGNOSTIC PLOTS DATA ──
    # Use the train-only model evaluated on its held-out test set (post-train_end rows).
    # This is the only correct way to produce an OOS actual-vs-predicted diagnostic:
    # the production model was refit on all data, so any window overlapping its training
    # period would be in-sample and artificially tight.
    partial_plots = {}

    try:
        loaded_to = joblib.load(TRAIN_ONLY_MODEL_PATH)
        to_pipeline    = loaded_to['pipeline']
        to_feat_names  = loaded_to['feature_list']
        to_regressor   = to_pipeline.named_steps['model']
        to_preprocessor = to_pipeline.named_steps['preprocessor']
        to_train_range = loaded_to.get('training_date_range', ())
        to_train_end   = (pd.Timestamp(to_train_range[1])
                          if to_train_range and len(to_train_range) >= 2
                          else pd.Timestamp('2023-04-30'))
        if to_train_end.tzinfo is None and target_aligned.index.tzinfo is not None:
            to_train_end = to_train_end.tz_localize(target_aligned.index.tzinfo)
        elif to_train_end.tzinfo is not None and target_aligned.index.tzinfo is None:
            to_train_end = to_train_end.tz_convert(None)

        val_target   = target_aligned[target_aligned.index > to_train_end]
        val_features = df_features.loc[val_target.index, to_feat_names]
        val_pred     = to_pipeline.predict(val_features)

        if len(val_target) > 0:
            val_actual_arr = val_target.values
            val_pred_arr   = val_pred
            valid_diag = ~(np.isnan(val_actual_arr) | np.isnan(val_pred_arr))
            val_actual_arr = val_actual_arr[valid_diag]
            val_pred_arr   = val_pred_arr[valid_diag]

            # Partial residual plots for top 5 features. Both the ranking and
            # the coefficient must come from the train-only model — the
            # residuals are this model's residuals, so mixing in the production
            # model's ranking would pair train-only residuals with features
            # that are merely the most influential under the production fit.
            residuals = val_actual_arr - val_pred_arr
            X_val_transformed = to_preprocessor.transform(val_features)
            to_sorted = sorted(
                enumerate(to_feat_names),
                key=lambda ij: abs(float(to_regressor.coef_[ij[0]])),
                reverse=True,
            )
            for j, feat in to_sorted[:5]:
                feat_vals_transformed = X_val_transformed[valid_diag, j]
                feat_coef = float(to_regressor.coef_[j])
                partial_residuals = residuals + (feat_coef * feat_vals_transformed)
                partial_plots[feat] = {
                    'x': feat_vals_transformed.tolist(),
                    'y': partial_residuals.tolist(),
                }
    except Exception:
        logger.exception("diagnostics: failed to build OOS diagnostic plots")

    # ── MULTI-HORIZON FORECASTS ──
    last_date = raw_df.index[-1]
    next_month_date = last_date + pd.offsets.MonthEnd(1)

    # Top drivers exclude the lag anchor — only correction features
    correction_contribs = [c for c in contributions if c['feature'] != 'ZAR_USD_lag1']
    top_drivers = []
    for c in correction_contribs[:3]:
        feat_name = get_friendly_feature_name(c['feature'])
        impact = "upward" if c['contribution'] > 0 else "downward"
        top_drivers.append(f"{feat_name} ({impact})")

    horizons = {'1m': 1, '3m': 3, '6m': 6}
    max_h = max(horizons.values())

    # Iterative multi-horizon prediction + per-horizon fair value
    iterative_df = raw_df.tail(30).copy()
    h_levels = {}
    h_fair_values = {}

    def _converge_from(fork_df, feature_names, pipeline, lookahead=3):
        """
        Fair value at a given horizon = where the model projects the rate will be
        after `lookahead` additional months from that horizon's state.

        This captures the transitional equilibrium — where ZAR-derived features
        (momentum, z-score, trend) are still unwinding from the horizon's specific
        dynamics. A 3-month lookahead balances responsiveness (different per horizon)
        with stability (smoothed past the initial overshoot).
        """
        fv_df = fork_df.copy()
        fv_level = float(fv_df['ZAR_USD'].iloc[-1])
        for _ in range(lookahead):
            try:
                fv_feat, _ = engineer_features(fv_df, bypass_cache=True)
                if fv_feat.empty:
                    break
                fv_level = float(pipeline.predict(fv_feat.iloc[[-1]][feature_names])[0])
                fv_date = fv_df.index[-1] + pd.offsets.MonthEnd(1)
                # In-place row append (avoids the pd.DataFrame([row]) wrapper +
                # full concat on every iteration).
                fv_df.loc[fv_date] = fv_df.iloc[-1]
                fv_df.loc[fv_date, 'ZAR_USD'] = fv_level
            except Exception:
                break
        return fv_level

    # Current fair value (converge from today's state)
    fair_value_level = _converge_from(iterative_df, feature_names, pipeline)

    # Iterate up to max horizon, forking at each checkpoint
    max_h = max(horizons.values())
    # Invert horizons map once for O(1) checkpoint lookup instead of scanning each iteration.
    horizon_at = {h_val: label for label, h_val in horizons.items()}
    for i in range(1, max_h + 1):
        try:
            df_feat_iter, _ = engineer_features(iterative_df, bypass_cache=True)
            if df_feat_iter.empty:
                break

            X_iter = df_feat_iter.iloc[[-1]][feature_names]
            next_level = float(pipeline.predict(X_iter)[0])

            next_date_iter = iterative_df.index[-1] + pd.offsets.MonthEnd(1)
            # In-place row append (avoids pd.DataFrame([row]) + concat each step).
            iterative_df.loc[next_date_iter] = iterative_df.iloc[-1]
            iterative_df.loc[next_date_iter, 'ZAR_USD'] = next_level

            label = horizon_at.get(i)
            if label is not None:
                h_levels[label] = (next_level, next_date_iter)
                # Fork: converge from THIS horizon's state
                h_fair_values[label] = _converge_from(iterative_df, feature_names, pipeline)
        except Exception:
            break

    forecasts = {}
    for label, h_val in horizons.items():
        if label not in h_levels:
            continue

        final_level, final_date = h_levels[label]
        diff = final_level - last_zar_usd
        pct_diff = (diff / last_zar_usd) * 100

        if abs(pct_diff) < 0.5:
            reason = "Fair value is aligned with current spot; macro drivers are largely priced in."
        elif diff > 0:
            driver = top_drivers[0] if top_drivers else "macro factors"
            reason = f"Error-correction model identifies undervaluation; {driver} suggest a weaker ZAR than current spot."
        else:
            driver = top_drivers[0] if top_drivers else "macro factors"
            reason = f"Error-correction model identifies overvaluation; {driver} suggest ZAR should be stronger than current spot."

        horizon_fv = h_fair_values.get(label, fair_value_level)

        forecasts[label] = {
            'point_estimate': round(final_level, 4),
            'fair_value': round(horizon_fv, 4),
            'actual_estimate': round(last_zar_usd, 4),
            'date': final_date.strftime('%Y-%m-%d'),
            'reason': reason,
        }

    # ── MODEL INFO ──
    hyperparams = model_data['hyperparameters']
    training_range = model_data.get('training_date_range')
    if training_range and isinstance(training_range, (list, tuple)) and len(training_range) >= 2:
        training_range_str = f"{training_range[0]} to {training_range[1]}"
    else:
        training_range_str = "Unknown"

    # ── FAIR VALUE & MISALIGNMENT ──
    fv_misalignment = fair_value_level - last_zar_usd
    fv_misalignment_pct = (fv_misalignment / last_zar_usd) * 100
    if fv_misalignment_pct > 0.5:
        fv_signal = 'undervalued'  # ZAR is too strong relative to fair value → should be weaker
    elif fv_misalignment_pct < -0.5:
        fv_signal = 'overvalued'   # ZAR is too weak relative to fair value → should be stronger
    else:
        fv_signal = 'fairly_valued'

    _result = {
        'predicted_level': round(predicted_level, 4),
        'predicted_change': round(predicted_change, 4),
        'predicted_change_pct': round(float(predicted_change_pct), 2),
        'direction': direction,
        'last_zar_usd': round(last_zar_usd, 4),
        'last_date': last_date.strftime('%Y-%m-%d'),
        'next_month_date': next_month_date.strftime('%Y-%m-%d'),
        'fair_value': round(fair_value_level, 4),
        'fair_value_misalignment': round(fv_misalignment, 4),
        'fair_value_misalignment_pct': round(fv_misalignment_pct, 2),
        'fair_value_signal': fv_signal,
        'contributions': contributions,
        'selected_features': feature_names,
        'forecasts': forecasts,
        'model_info': {
            'model_type': 'HuberRegressor',
            'alpha': float(hyperparams.get('alpha', regressor.alpha)),
            'epsilon': float(hyperparams.get('epsilon', regressor.epsilon)),
            'intercept': float(regressor.intercept_),
            'scale': float(regressor.scale_) if hasattr(regressor, 'scale_') else None,
            'training_observations': 134,
            'test_observations': 34,
            'training_date_range': training_range_str,
            'n_features': len(feature_names),
            'n_selected': len(feature_names),  # All 11 features are non-zero
        },
        'metrics': {
            'mae': mae,
            'rmse': rmse,
            'r2': r2,
            'adjusted_r2': adjusted_r2,
            'mape': mape,
            'theils_u': theils_u,
            'directional_accuracy': directional_accuracy,
        },
        'history': {
            'dates': pd.DatetimeIndex(hist_chart_dates).strftime('%Y-%m-%d').tolist(),
            'actual': hist_actual_levels.tolist(),
            'predicted': hist_pred_levels.tolist(),
        },
        'diagnostics': {
            'partial_plots': partial_plots,
        },
    }

    _predict_next_month_cache = {'result': _result, 'time': time.time()}
    _persistent_cache.set(_pnm_cache_key, _result, expire=300)
    logger.info("predict_next_month: computed and cached new result")

    return _result


def get_test_set_predictions():
    """
    Load the train-only model and generate actual vs predicted on the held-out test set.
    The train-only model was trained on 2012-03-31 to 2023-04-30, so the test set
    is everything from 2023-05-31 onwards.

    Returns a dict with 'dates', 'actual', 'predicted' lists.
    """
    import pandas as pd
    import numpy as np
    global _test_set_cache
    now = time.time()

    if _test_set_cache['result'] is not None and (now - _test_set_cache['time'] < 300):
        return _test_set_cache['result']

    cache_key = "test_set_predictions"
    cached = _persistent_cache.get(cache_key)
    if cached is not None:
        _test_set_cache = {'result': cached, 'time': now}
        return cached

    if JOBLIB_IMPORT_ERROR is not None:
        raise RuntimeError("Model dependencies unavailable.") from JOBLIB_IMPORT_ERROR
    if not os.path.exists(TRAIN_ONLY_MODEL_PATH):
        raise FileNotFoundError(f"Train-only model not found: {TRAIN_ONLY_MODEL_PATH}")

    loaded = joblib.load(TRAIN_ONLY_MODEL_PATH)
    pipeline = loaded['pipeline']
    feature_names = loaded['feature_list']
    training_range = loaded.get('training_date_range', ())

    if training_range and len(training_range) >= 2:
        train_end = pd.Timestamp(training_range[1])
    else:
        train_end = pd.Timestamp('2023-04-30')

    raw_df = fetch_data_from_supabase()
    df_features, _ = engineer_features(raw_df)

    target = raw_df['ZAR_USD'].shift(-1)
    target_aligned = target.reindex(df_features.index).dropna()

    # Ensure timezone consistency for comparison
    if train_end.tzinfo is None and target_aligned.index.tzinfo is not None:
        train_end = train_end.tz_localize(target_aligned.index.tzinfo)
    elif train_end.tzinfo is not None and target_aligned.index.tzinfo is None:
        train_end = train_end.tz_convert(None)

    test_mask = target_aligned.index > train_end
    test_target = target_aligned[test_mask]

    if test_target.empty:
        raise ValueError("No test data available after training period.")

    test_features = df_features.loc[test_target.index, feature_names]
    test_pred = pipeline.predict(test_features)
    test_actual = test_target.values

    valid = ~(np.isnan(test_actual) | np.isnan(test_pred))
    test_actual = test_actual[valid]
    test_pred = test_pred[valid]
    test_dates_raw = test_target.index[valid]

    raw_index = raw_df.index
    raw_len = len(raw_index)
    test_positions = raw_index.get_indexer(test_dates_raw)
    chart_dates = [
        raw_index[p + 1] if (p >= 0 and p + 1 < raw_len)
        else (test_dates_raw[i] + pd.offsets.MonthEnd(1))
        for i, p in enumerate(test_positions)
    ]

    mae = float(np.mean(np.abs(test_actual - test_pred)))
    resid = test_actual - test_pred
    sq_resid = resid * resid
    rmse = float(np.sqrt(sq_resid.mean()))
    ss_res = sq_resid.sum()
    test_actual_centered = test_actual - test_actual.mean()
    ss_tot = (test_actual_centered * test_actual_centered).sum()
    r2 = float(1 - ss_res / ss_tot) if ss_tot > 0 else 0.0

    result = {
        'dates': pd.DatetimeIndex(chart_dates).strftime('%Y-%m-%d').tolist(),
        'actual': test_actual.tolist(),
        'predicted': test_pred.tolist(),
        'n_obs': len(test_actual),
        'train_end': train_end.strftime('%Y-%m-%d'),
        'mae': round(mae, 4),
        'rmse': round(rmse, 4),
        'r2': round(r2, 4),
    }

    _test_set_cache = {'result': result, 'time': now}
    _persistent_cache.set(cache_key, result, expire=300)
    logger.info("get_test_set_predictions: computed %d test observations", len(test_actual))
    return result
