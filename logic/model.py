import os
import logging
import threading
import time
import diskcache

from logic.supabase_client import get_supabase

# Persistent cache for Supabase data to share across separate background processes
_persistent_cache = diskcache.Cache("./.cache/data", size_limit=2**25) # 32MB limit

try:
    import joblib
    JOBLIB_IMPORT_ERROR = None
except ModuleNotFoundError as exc:
    joblib = None
    JOBLIB_IMPORT_ERROR = exc

logger = logging.getLogger("ModelPredictor")

MODEL_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          'models', 'zar_usd_forecast_model.pkl')
TRAIN_ONLY_MODEL_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                     'models', 'zar_usd_forecast_model_train_only.pkl')

# The 11 features in the order the pipeline expects
FEATURE_LIST = [
    'ZAR_USD_lag1', 'ZAR_USD_change3', 'EPU_USA', 'VIX', 'VIX_zscore12',
    'ZAR_USD_logret1', 'VIX_change1', 'WUIZAF_SA', 'GOLD_PRICE_logret1',
    'bond_spread_change1', 'ZAR_USD_zscore12',
]

# Friendly display names for each feature
BASE_FEATURE_NAMES = {
    'ZAR_USD_lag1': 'ZAR/USD (Prev. Month)',
    'ZAR_USD_logret1': 'ZAR/USD Momentum (1M)',
    'ZAR_USD_change3': 'ZAR/USD Trend (3M)',
    'ZAR_USD_zscore12': 'ZAR/USD Mean-Reversion',
    'VIX': 'VIX Level',
    'VIX_change1': 'VIX Change (1M)',
    'VIX_zscore12': 'VIX Stress Signal',
    'EPU_USA': 'US Policy Uncertainty',
    'WUIZAF_SA': 'SA Uncertainty Index',
    'bond_spread_change1': 'Bond Spread Change',
    'GOLD_PRICE_logret1': 'Gold Return (1M)',
}

# Feature categories for coefficient interpretation
FEATURE_CATEGORIES = {
    'ZAR_USD_lag1': 'passthrough',
    'ZAR_USD_logret1': 'log_return',
    'ZAR_USD_change3': 'level_change',
    'ZAR_USD_zscore12': 'zscore',
    'VIX': 'level',
    'VIX_change1': 'level_change',
    'VIX_zscore12': 'zscore',
    'EPU_USA': 'level',
    'WUIZAF_SA': 'level',
    'bond_spread_change1': 'spread_change',
    'GOLD_PRICE_logret1': 'log_return',
}

# Raw Supabase columns that feed into scenario sliders (excluding ZAR_USD)
SCENARIO_RAW_PREDICTORS = [
    'VIX', 'EPU(USA)', 'WUIZAF(SA)', 'GOLD_PRICE',
    '10_YEAR_BOND_RATES(SA)', '10_YEAR_BOND_RATES(USA)',
]

_model_cache = {}
_supabase_data_cache = {'df': None, 'time': 0}
_engineered_features_cache = {'df_features': None, 'df_raw': None, 'input_hash': None, 'time': 0}
_predict_next_month_cache = {'result': None, 'time': 0}
_cache_lock = threading.Lock()


def get_friendly_feature_name(feature_name, _transform_type=None):
    """Return a human-readable name for a feature."""
    return BASE_FEATURE_NAMES.get(feature_name, feature_name)


def get_feature_category(feature_name):
    """Return the category of a feature for coefficient interpretation."""
    return FEATURE_CATEGORIES.get(feature_name, 'unknown')


def get_coefficient_unit(feature_name):
    """Return appropriate unit label for interpretable coefficients."""
    cat = get_feature_category(feature_name)
    if cat == 'passthrough':
        return 'ZAR per 1 ZAR in prev. rate'
    elif cat == 'level':
        return 'ZAR per 1-unit increase'
    elif cat == 'level_change':
        return 'ZAR per 1-unit change'
    elif cat == 'log_return':
        return 'ZAR per 1% move'
    elif cat == 'zscore':
        return 'ZAR per 1-std deviation'
    elif cat == 'spread_change':
        return 'ZAR per 1pp spread change'
    return 'ZAR per unit'


def load_model():
    """Load the frozen HuberRegressor pipeline from disk (cached)."""
    if JOBLIB_IMPORT_ERROR is not None:
        raise RuntimeError(
            "Model dependencies are unavailable. "
            "Install joblib and sklearn to use the Model page."
        ) from JOBLIB_IMPORT_ERROR

    cache_key = 'model_data'
    if not os.path.exists(MODEL_PATH):
        raise FileNotFoundError(f"Model file not found: {MODEL_PATH}")

    mtime = os.path.getmtime(MODEL_PATH)
    if cache_key not in _model_cache or _model_cache[cache_key].get('mtime') != mtime:
        loaded = joblib.load(MODEL_PATH)

        pipeline = loaded['pipeline']
        feature_names = loaded['feature_list']
        preprocessor = pipeline.named_steps['preprocessor']
        regressor = pipeline.named_steps['model']

        # Extract the StandardScaler from the ColumnTransformer
        scaler = None
        for name, transformer, cols in preprocessor.transformers_:
            if name == 'scaler':
                scaler = transformer
                break

        data = {
            'pipeline': pipeline,
            'regressor': regressor,
            'preprocessor': preprocessor,
            'scaler': scaler,
            'feature_names': feature_names,
            'evaluation_metrics': loaded.get('evaluation_metrics', {}),
            'hyperparameters': loaded.get('hyperparameters', {}),
            'training_date_range': loaded.get('training_date_range'),
            'model_type': loaded.get('model_type', 'HuberRegressor'),
            'mtime': mtime,
        }
        _model_cache[cache_key] = data
        logger.info("Loaded ZAR/USD HuberRegressor pipeline from %s (mtime: %s)", MODEL_PATH, mtime)

    return _model_cache[cache_key]


def fetch_data_from_supabase():
    """Fetch recent rows from the Supabase 'data' table (with 5-min caching)."""
    import pandas as pd
    global _supabase_data_cache
    now = time.time()

    if _supabase_data_cache['df'] is not None and (now - _supabase_data_cache['time'] < 300):
        return _supabase_data_cache['df'].copy()

    cache_key = "supabase_data_df"
    cached_df = _persistent_cache.get(cache_key)
    if cached_df is not None:
        _supabase_data_cache = {'df': cached_df, 'time': now}
        return cached_df.copy()

    supabase = get_supabase()
    if not supabase:
        raise RuntimeError("Supabase client not initialised.")

    resp = supabase.table('data').select('*').order('Date', desc=True).limit(500).execute()
    rows = resp.data or []
    if not rows:
        raise ValueError("No data returned from Supabase.")
    df = pd.DataFrame(rows)
    df['Date'] = pd.to_datetime(df['Date'])
    df.set_index('Date', inplace=True)
    df = df.apply(pd.to_numeric, errors='coerce')
    df = df.sort_index()

    _supabase_data_cache = {'df': df, 'time': now}
    _persistent_cache.set(cache_key, df, expire=300)

    return df.copy()


def engineer_features(df, bypass_cache=False):
    """
    Build the 11 features for the HuberRegressor model from raw data.

    Features (all use only information available at time t):
      1. ZAR_USD_lag1       = S_{t-1}                           (passthrough)
      2. ZAR_USD_logret1    = ln(S_t / S_{t-1})                 (momentum)
      3. ZAR_USD_change3    = S_t - S_{t-3}                     (3-month trend)
      4. ZAR_USD_zscore12   = z-score of S_{t-1} over 12 months (mean-reversion)
      5. VIX                = VIX_t                             (risk level)
      6. VIX_change1        = VIX_t - VIX_{t-1}                (risk direction)
      7. VIX_zscore12       = z-score of VIX_{t-1} over 12 mo   (stress regime)
      8. EPU_USA            = EPU(USA)_t                        (policy uncertainty)
      9. WUIZAF_SA          = WUIZAF(SA)_t                      (SA uncertainty)
     10. bond_spread_change1= delta(SA_10Y - US_10Y)            (carry trade signal)
     11. GOLD_PRICE_logret1 = ln(G_t / G_{t-1})                (commodity signal)

    Returns (df_features, df_raw) where df_features has these 11 columns.
    """
    import pandas as pd
    import numpy as np
    global _engineered_features_cache
    now = time.time()

    # Cache check (lock-protected). Skip entirely when caller asks to bypass —
    # used by scenario/iterative paths that mutate the input row and shouldn't
    # share cache state with the base prediction.
    if not df.empty:
        current_hash = (df.shape, df.iloc[-1].sum(), df.index[-1])
        if not bypass_cache:
            with _cache_lock:
                cached = _engineered_features_cache
                if (cached['df_features'] is not None and
                        cached['input_hash'] == current_hash and
                        (now - cached['time'] < 300)):
                    return cached['df_features'].copy(), cached['df_raw'].copy()
    else:
        current_hash = None

    df = df.copy()
    for col in df.columns:
        if pd.api.types.is_numeric_dtype(df[col]):
            df[col] = df[col].astype('float64')

    features = pd.DataFrame(index=df.index)

    # 1. ZAR_USD_lag1 = S_{t-1}
    features['ZAR_USD_lag1'] = df['ZAR_USD'].shift(1)

    # 2. ZAR_USD_logret1 = ln(S_t / S_{t-1})
    features['ZAR_USD_logret1'] = np.log(df['ZAR_USD'] / df['ZAR_USD'].shift(1))

    # 3. ZAR_USD_change3 = S_t - S_{t-3}
    features['ZAR_USD_change3'] = df['ZAR_USD'] - df['ZAR_USD'].shift(3)

    # 4. ZAR_USD_zscore12 = (S_{t-1} - mean_12) / std_12
    zar_lagged = df['ZAR_USD'].shift(1)
    zar_roll_mean = zar_lagged.rolling(12).mean()
    zar_roll_std = zar_lagged.rolling(12).std(ddof=1)
    features['ZAR_USD_zscore12'] = (zar_lagged - zar_roll_mean) / zar_roll_std

    # 5. VIX level
    features['VIX'] = df['VIX']

    # 6. VIX_change1 = VIX_t - VIX_{t-1}
    features['VIX_change1'] = df['VIX'].diff(1)

    # 7. VIX_zscore12 = z-score of VIX_{t-1}
    vix_lagged = df['VIX'].shift(1)
    vix_roll_mean = vix_lagged.rolling(12).mean()
    vix_roll_std = vix_lagged.rolling(12).std(ddof=1)
    features['VIX_zscore12'] = (vix_lagged - vix_roll_mean) / vix_roll_std

    # 8. EPU_USA
    features['EPU_USA'] = df['EPU(USA)']

    # 9. WUIZAF_SA
    features['WUIZAF_SA'] = df['WUIZAF(SA)']

    # 10. bond_spread_change1 = delta(SA_10Y - US_10Y)
    spread = df['10_YEAR_BOND_RATES(SA)'] - df['10_YEAR_BOND_RATES(USA)']
    features['bond_spread_change1'] = spread.diff(1)

    # 11. GOLD_PRICE_logret1 = ln(G_t / G_{t-1})
    features['GOLD_PRICE_logret1'] = np.log(df['GOLD_PRICE'] / df['GOLD_PRICE'].shift(1))

    # Drop rows with NaN (need ~13 months of history for z-score features)
    features.dropna(inplace=True)

    if not bypass_cache:
        with _cache_lock:
            _engineered_features_cache = {
                'df_features': features,
                'df_raw': df,
                'input_hash': current_hash,
                'time': now,
            }

    return features.copy(), df.copy()


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

    # Chart dates = prediction dates (one month after feature date)
    hist_chart_dates = []
    for d in hist_feature_dates:
        loc = raw_df.index.get_loc(d)
        if loc + 1 < len(raw_df):
            hist_chart_dates.append(raw_df.index[loc + 1])
        else:
            hist_chart_dates.append(d + pd.offsets.MonthEnd(1))

    # Limit to 60 months for UI
    chart_limit = 60
    if len(hist_chart_dates) > chart_limit:
        hist_chart_dates = hist_chart_dates[-chart_limit:]
        hist_actual_levels = hist_actual_levels[-chart_limit:]
        hist_pred_levels = hist_pred_levels[-chart_limit:]

    # ── VALIDATION METRICS ──
    # Use stored test metrics from the model report (proper out-of-sample evaluation)
    test_metrics = stored_metrics.get('test', {})
    mae = float(test_metrics.get('MAE', 0))
    rmse = float(test_metrics.get('RMSE', 0))
    r2 = float(test_metrics.get('R2', 0))
    adjusted_r2 = float(stored_metrics.get('adjusted_r2_test', 0))
    directional_accuracy = float(stored_metrics.get('directional_accuracy_test', 0)) * 100
    theils_u = float(stored_metrics.get('theils_u_test', 0))

    # Compute MAPE from historical predictions for display
    if len(hist_actual_levels) > 0:
        mape = float(np.mean(np.abs((hist_actual_levels - hist_pred_levels) / hist_actual_levels)) * 100)
    else:
        mape = 0.0

    # ── DIAGNOSTIC PLOTS DATA ──
    # Use last 20% of data for validation diagnostics
    n_total = len(target_aligned)
    val_start = int(n_total * 0.8)
    val_target = target_aligned.iloc[val_start:]
    val_features = df_features.loc[val_target.index, feature_names]
    val_pred = pipeline.predict(val_features)

    actual_vs_predicted = {}
    partial_plots = {}

    if len(val_target) > 0:
        val_actual_arr = val_target.values
        val_pred_arr = val_pred
        valid_diag = ~(np.isnan(val_actual_arr) | np.isnan(val_pred_arr))
        val_actual_arr = val_actual_arr[valid_diag]
        val_pred_arr = val_pred_arr[valid_diag]

        val_dates_raw = val_target.index[valid_diag]
        val_chart_dates = []
        for d in val_dates_raw:
            loc = raw_df.index.get_loc(d)
            if loc + 1 < len(raw_df):
                val_chart_dates.append(raw_df.index[loc + 1].strftime('%Y-%m-%d'))
            else:
                val_chart_dates.append((d + pd.offsets.MonthEnd(1)).strftime('%Y-%m-%d'))

        actual_vs_predicted = {
            'dates': val_chart_dates,
            'actual': [float(a) for a in val_actual_arr],
            'predicted': [float(p) for p in val_pred_arr],
        }

        # Partial residual plots for top 5 features
        residuals = val_actual_arr - val_pred_arr
        X_val_transformed = preprocessor.transform(val_features)

        sorted_contribs = sorted(contributions, key=lambda x: abs(x['coefficient']), reverse=True)
        for c in sorted_contribs[:5]:
            feat = c['feature']
            j = feature_names.index(feat)
            feat_vals_transformed = X_val_transformed[valid_diag, j]
            feat_coef = regressor.coef_[j]
            partial_residuals = residuals + (feat_coef * feat_vals_transformed)

            partial_plots[feat] = {
                'x': [float(v) for v in feat_vals_transformed],
                'y': [float(r) for r in partial_residuals],
            }

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
                fv_row = fv_df.iloc[-1].copy()
                fv_row.name = fv_date
                fv_row['ZAR_USD'] = fv_level
                fv_df = pd.concat([fv_df, pd.DataFrame([fv_row])])
            except Exception:
                break
        return fv_level

    # Current fair value (converge from today's state)
    fair_value_level = _converge_from(iterative_df, feature_names, pipeline)

    # Iterate up to max horizon, forking at each checkpoint
    max_h = max(horizons.values())
    for i in range(1, max_h + 1):
        try:
            df_feat_iter, _ = engineer_features(iterative_df, bypass_cache=True)
            if df_feat_iter.empty:
                break

            X_iter = df_feat_iter.iloc[[-1]][feature_names]
            next_level = float(pipeline.predict(X_iter)[0])

            next_date_iter = iterative_df.index[-1] + pd.offsets.MonthEnd(1)
            new_row = iterative_df.iloc[-1].copy()
            new_row.name = next_date_iter
            new_row['ZAR_USD'] = next_level
            iterative_df = pd.concat([iterative_df, pd.DataFrame([new_row])])

            for label, h_val in horizons.items():
                if i == h_val:
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
            'dates': [d.strftime('%Y-%m-%d') for d in hist_chart_dates],
            'actual': [float(v) for v in hist_actual_levels],
            'predicted': [float(v) for v in hist_pred_levels],
        },
        'diagnostics': {
            'actual_vs_predicted': actual_vs_predicted,
            'partial_plots': partial_plots,
        },
    }

    _predict_next_month_cache = {'result': _result, 'time': time.time()}
    _persistent_cache.set(_pnm_cache_key, _result, expire=300)
    logger.info("predict_next_month: computed and cached new result")

    return _result


def get_scenario_baseline():
    """
    Return the baseline data needed for scenario analysis:
    - Current raw predictor values and historical ranges for sliders
    - Base prediction (current values)
    """
    import pandas as pd
    import numpy as np

    _sb_cache_key = "scenario_baseline_result"
    _cached = _persistent_cache.get(_sb_cache_key)
    if _cached is not None:
        logger.info("get_scenario_baseline: returning cached result")
        return _cached

    model_data = load_model()
    pipeline = model_data['pipeline']
    feature_names = model_data['feature_names']

    raw_df = fetch_data_from_supabase()
    df_features, df_raw = engineer_features(raw_df)

    if df_features.empty:
        raise ValueError("Not enough data to compute features.")

    # Base prediction (latest features → next month level)
    X_latest = df_features.iloc[[-1]][feature_names]
    base_level = float(pipeline.predict(X_latest)[0])
    last_zar_usd = float(raw_df['ZAR_USD'].dropna().iloc[-1])

    last_date = raw_df.index[-1]
    next_month_date = last_date + pd.offsets.MonthEnd(1)

    # Build slider config for each adjustable raw predictor
    predictors_config = []
    for raw_col in SCENARIO_RAW_PREDICTORS:
        if raw_col not in raw_df.columns:
            continue

        current_val = float(raw_df[raw_col].dropna().iloc[-1])
        hist_series = raw_df[raw_col].dropna()
        hist_min = float(hist_series.min())
        hist_max = float(hist_series.max())
        hist_std = float(hist_series.std())

        # Slider range: ±4 std from current, bounded by expanded historical range
        range_low = max(hist_min * 0.3, current_val - 4 * hist_std)
        range_high = min(hist_max * 2.0, current_val + 4 * hist_std)
        if range_low >= range_high:
            range_low = hist_min * 0.5
            range_high = hist_max * 1.8

        predictors_config.append({
            'raw_col': raw_col,
            'current_value': round(current_val, 4),
            'hist_min': round(hist_min, 4),
            'hist_max': round(hist_max, 4),
            'range_low': round(range_low, 4),
            'range_high': round(range_high, 4),
        })

    _sb_result = {
        'predictors': predictors_config,
        'base_prediction': round(base_level, 4),
        'last_zar_usd': round(last_zar_usd, 4),
        'last_date': last_date.strftime('%Y-%m-%d'),
        'next_month_date': next_month_date.strftime('%Y-%m-%d'),
        'feature_names': feature_names,
    }

    _persistent_cache.set(_sb_cache_key, _sb_result, expire=300)
    logger.info("get_scenario_baseline: computed and cached new result")
    return _sb_result


def scenario_predict(scenario_values):
    """
    Run a scenario prediction given modified raw predictor values.

    Args:
        scenario_values: dict mapping raw column names to new values,
                         e.g. {'VIX': 25.0, 'GOLD_PRICE': 2800.0}

    Returns:
        dict with scenario prediction, base prediction, waterfall contributions
    """
    import pandas as pd
    import numpy as np

    model_data = load_model()
    pipeline = model_data['pipeline']
    regressor = model_data['regressor']
    preprocessor = model_data['preprocessor']
    feature_names = model_data['feature_names']

    raw_df = fetch_data_from_supabase()

    # --- BASE prediction (unmodified) ---
    df_features_base, _ = engineer_features(raw_df)
    X_base = df_features_base.iloc[[-1]][feature_names]
    base_level = float(pipeline.predict(X_base)[0])
    last_zar_usd = float(raw_df['ZAR_USD'].dropna().iloc[-1])

    # --- SCENARIO prediction (with modified last row) ---
    raw_df_scenario = raw_df.copy()
    last_idx = raw_df_scenario.index[-1]
    for raw_col, new_val in scenario_values.items():
        if raw_col in raw_df_scenario.columns:
            raw_df_scenario.loc[last_idx, raw_col] = new_val

    # Bypass cache so the scenario row is freshly engineered without polluting
    # the shared cache used by the base prediction path.
    df_features_scen, _ = engineer_features(raw_df_scenario, bypass_cache=True)

    X_scen = df_features_scen.iloc[[-1]][feature_names]
    scen_level = float(pipeline.predict(X_scen)[0])

    # --- Waterfall: per-feature contribution difference ---
    X_base_transformed = preprocessor.transform(X_base)
    X_scen_transformed = preprocessor.transform(X_scen)

    waterfall = []
    for j, feat in enumerate(feature_names):
        coef = float(regressor.coef_[j])
        base_val = float(X_base_transformed[0, j])
        scen_val = float(X_scen_transformed[0, j])
        delta_contrib = coef * (scen_val - base_val)

        waterfall.append({
            'feature': feat,
            'base_contribution': round(coef * base_val, 6),
            'scenario_contribution': round(coef * scen_val, 6),
            'delta': round(delta_contrib, 6),
        })

    waterfall.sort(key=lambda x: abs(x['delta']), reverse=True)

    last_date = raw_df.index[-1]
    next_month_date = last_date + pd.offsets.MonthEnd(1)

    scen_change_pct = ((scen_level - last_zar_usd) / last_zar_usd) * 100
    base_change_pct = ((base_level - last_zar_usd) / last_zar_usd) * 100

    return {
        'base_level': round(base_level, 4),
        'base_change_pct': round(float(base_change_pct), 2),
        'scenario_level': round(scen_level, 4),
        'scenario_change_pct': round(float(scen_change_pct), 2),
        'delta_level': round(float(scen_level - base_level), 4),
        'last_zar_usd': round(last_zar_usd, 4),
        'last_date': last_date.strftime('%Y-%m-%d'),
        'next_month_date': next_month_date.strftime('%Y-%m-%d'),
        'waterfall': waterfall,
        'scenario_values': {k: round(float(v), 4) for k, v in scenario_values.items()},
    }


_test_set_cache = {'result': None, 'time': 0}


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

    # Determine train end date
    if training_range and len(training_range) >= 2:
        train_end = pd.Timestamp(training_range[1])
    else:
        train_end = pd.Timestamp('2023-04-30')

    raw_df = fetch_data_from_supabase()
    df_features, _ = engineer_features(raw_df)

    # Target: S_{t+1} = raw_df['ZAR_USD'].shift(-1) aligned to feature dates
    target = raw_df['ZAR_USD'].shift(-1)
    target_aligned = target.reindex(df_features.index).dropna()

    # Filter to test set: feature dates after train_end
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

    # Chart dates = prediction dates (one month after feature date)
    chart_dates = []
    for d in test_dates_raw:
        loc = raw_df.index.get_loc(d)
        if loc + 1 < len(raw_df):
            chart_dates.append(raw_df.index[loc + 1])
        else:
            chart_dates.append(d + pd.offsets.MonthEnd(1))

    # Metrics on test set
    mae = float(np.mean(np.abs(test_actual - test_pred)))
    rmse = float(np.sqrt(np.mean((test_actual - test_pred) ** 2)))
    ss_res = np.sum((test_actual - test_pred) ** 2)
    ss_tot = np.sum((test_actual - np.mean(test_actual)) ** 2)
    r2 = float(1 - ss_res / ss_tot) if ss_tot > 0 else 0.0

    result = {
        'dates': [d.strftime('%Y-%m-%d') for d in chart_dates],
        'actual': [float(v) for v in test_actual],
        'predicted': [float(v) for v in test_pred],
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


def find_scenario_for_target(target_level):
    """
    Given a target ZAR/USD level, find plausible predictor values that would produce it.

    Strategy: since HuberRegressor is linear in the transformed feature space, we measure
    each predictor's per-unit sensitivity (d prediction / d raw_value) and iteratively
    nudge the most effective predictors toward the target. Much faster than black-box
    optimization because each sensitivity probe is a single scenario_predict call.

    Returns a dict with the found scenario values, the achieved prediction, and metadata.
    """
    import numpy as np

    baseline = get_scenario_baseline()
    predictors = baseline.get('predictors', [])

    if not predictors:
        raise ValueError("No baseline data available for reverse scenario search.")

    keys = [p['raw_col'] for p in predictors]
    current = {p['raw_col']: p['current_value'] for p in predictors}
    bounds = {p['raw_col']: (p['range_low'], p['range_high']) for p in predictors}

    # Start from current values
    best = dict(current)

    # Measure per-predictor sensitivity: how much does prediction change per unit of raw input?
    base_result = scenario_predict(best)
    base_level = base_result['scenario_level']

    sensitivities = {}
    for key in keys:
        lo, hi = bounds[key]
        span = hi - lo
        probe_delta = span * 0.01  # 1% of range
        if probe_delta == 0:
            continue
        probe = dict(best)
        probe[key] = min(best[key] + probe_delta, hi)
        probe_result = scenario_predict(probe)
        sens = (probe_result['scenario_level'] - base_level) / probe_delta
        sensitivities[key] = sens

    # Iterative greedy descent: nudge predictors proportionally to their sensitivity
    for iteration in range(30):
        result = scenario_predict(best)
        gap = target_level - result['scenario_level']

        if abs(gap) < 0.005:
            break  # Close enough

        # Rank predictors by how much they can help close the gap
        candidates = []
        for key in keys:
            sens = sensitivities.get(key, 0)
            if abs(sens) < 1e-8:
                continue
            lo, hi = bounds[key]
            # How much room is there to move in the direction that helps?
            if gap * sens > 0:
                # Need to increase this predictor
                room = hi - best[key]
            else:
                # Need to decrease this predictor
                room = best[key] - lo
            if room < 1e-6:
                continue
            # Desired delta to fully close gap via this predictor alone
            desired = gap / sens
            # Clamp to available room (with damping to avoid overshooting)
            actual = np.clip(desired * 0.6, -room, room) if gap * sens < 0 else np.clip(desired * 0.6, -room, room)
            candidates.append((key, actual, abs(sens * actual)))

        if not candidates:
            break  # No predictor can help further

        # Apply top contributors (spread the change across multiple predictors)
        candidates.sort(key=lambda x: x[2], reverse=True)
        n_apply = min(3, len(candidates))
        for key, delta, _ in candidates[:n_apply]:
            lo, hi = bounds[key]
            best[key] = float(np.clip(best[key] + delta, lo, hi))

        # Re-measure sensitivities every 10 iterations (feature engineering is nonlinear)
        if iteration % 10 == 9:
            ref_result = scenario_predict(best)
            ref_level = ref_result['scenario_level']
            for key in keys:
                lo, hi = bounds[key]
                span = hi - lo
                probe_delta = span * 0.01
                if probe_delta == 0:
                    continue
                probe = dict(best)
                probe[key] = min(best[key] + probe_delta, hi)
                pr = scenario_predict(probe)
                sensitivities[key] = (pr['scenario_level'] - ref_level) / probe_delta

    # Final result
    final_result = scenario_predict(best)

    # Build a summary of what changed
    changes = []
    for p in predictors:
        key = p['raw_col']
        cur = p['current_value']
        new_val = best[key]
        if abs(new_val - cur) > 0.001:
            pct = ((new_val - cur) / abs(cur)) * 100 if cur != 0 else 0
            changes.append({
                'predictor': key,
                'current': round(cur, 4),
                'scenario': round(new_val, 4),
                'change_pct': round(pct, 1),
            })

    return {
        'target_level': round(target_level, 4),
        'achieved_level': final_result['scenario_level'],
        'base_level': final_result['base_level'],
        'last_zar_usd': final_result['last_zar_usd'],
        'scenario_values': best,
        'changes': changes,
        'gap': round(abs(final_result['scenario_level'] - target_level), 4),
        'feasible': abs(final_result['scenario_level'] - target_level) < 0.5,
    }
