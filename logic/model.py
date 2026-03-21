import numpy as np
import pandas as pd
import os
import logging
import time

from logic.supabase_client import supabase

try:
    import joblib
    JOBLIB_IMPORT_ERROR = None
except ModuleNotFoundError as exc:
    joblib = None
    JOBLIB_IMPORT_ERROR = exc

logger = logging.getLogger("ModelPredictor")

MODEL_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'frozen models', 'zar_usd_model_v1.pkl')
TRAINSET_MODEL_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'frozen models', 'zar_usd_trainsetmodel.pkl')

# Transform metadata for dynamic coefficient interpretation
LOG_DIFF_COLS = {'EPU(USA)', 'VIX', 'GOLD_PRICE', 'BRENT_OIL_PRICE', 'ZAR_USD'}
FIRST_DIFF_COLS = {'WUIZAF(SA)', '10_YEAR_BOND_RATES(USA)', '10_YEAR_BOND_RATES(SA)',
                   'SA_INFLATION_YOY', 'US_CPI_YOY', 'INFLATION_DIFF'}

_model_cache = {}
_supabase_data_cache = {'df': None, 'time': 0}
_engineered_features_cache = {'df_features': None, 'df_raw': None, 'input_hash': None, 'time': 0}
_predict_next_month_cache = {'result': None, 'time': 0}


# NWU Color Palette (from MSc research standard)
BASE_FEATURE_NAMES = {
    'VIX': 'Volatility Index (VIX)',
    '10_YEAR_BOND_RATES(USA)': 'US 10Y Bond Rate',
    '10_YEAR_BOND_RATES(SA)': 'SA 10Y Bond Rate',
    'GOLD_PRICE': 'Gold Price',
    'EPU(USA)': 'US Economic Policy Uncertainty',
    'INFLATION_DIFF': 'SA-US Inflation Differential',
    'WUIZAF(SA)': 'SA World Uncertainty Index',
    'ZAR_USD': 'ZAR per USD',
    'SA_INFLATION_YOY': 'SA Inflation (YoY)',
    'US_CPI_YOY': 'US CPI (YoY)',
}


def get_friendly_feature_name(feature_name, transform_type):
    """Dynamically build a friendly name reflecting the actual transform applied."""
    is_lag = feature_name.endswith('_Lag1')
    is_trend = feature_name.endswith('_3M_Trend')
    base = feature_name.replace('_Lag1', '').replace('_3M_Trend', '')

    display_name = BASE_FEATURE_NAMES.get(base, base)

    # Simplified names - now interpretable per unit change in original rate
    if is_lag:
        return f"{display_name} (Prev. Month)"
    elif is_trend:
        return f"{display_name} (3M Trend)"
    return display_name


def load_model(trainset_model=False):
    """Load the frozen ElasticNet model from disk (cached).
    
    Args:
        trainset_model (bool): If True, load the trainset model for validation metrics.
                              If False, load the main model for predictions.
    """
    if JOBLIB_IMPORT_ERROR is not None:
        raise RuntimeError(
            "Model dependencies are unavailable in this Python environment. "
            "Install joblib (and the model's sklearn-compatible dependencies) in .venv to use the Model page."
        ) from JOBLIB_IMPORT_ERROR
    
    cache_key = 'trainset_model_data' if trainset_model else 'model_data'
    model_path = TRAINSET_MODEL_PATH if trainset_model else MODEL_PATH
    
    if not os.path.exists(model_path):
        raise FileNotFoundError(f"Model file not found: {model_path}")
        
    mtime = os.path.getmtime(model_path)
    if cache_key not in _model_cache or _model_cache[cache_key].get('mtime') != mtime:
        loaded = joblib.load(model_path)
        if isinstance(loaded, dict):
            data = loaded
        else:
            data = {'model': loaded}
        data['mtime'] = mtime
        _model_cache[cache_key] = data
        logger.info("Loaded ZAR/USD ElasticNet model from %s (mtime: %s)", model_path, mtime)
    return _model_cache[cache_key]


def fetch_data_from_supabase():
    """Fetch all rows from the Supabase 'data' table, return a DatetimeIndex DataFrame (with 5-min caching)."""
    global _supabase_data_cache
    now = time.time()
    
    # 5-minute process-level cache to reduce redundant fetches across redundant calls
    if _supabase_data_cache['df'] is not None and (now - _supabase_data_cache['time'] < 300):
        return _supabase_data_cache['df'].copy()

    if not supabase:
        raise RuntimeError("Supabase client not initialised.")
    resp = supabase.table('data').select('*').order('Date').execute()
    rows = resp.data or []
    if not rows:
        raise ValueError("No data returned from Supabase.")
    df = pd.DataFrame(rows)
    df['Date'] = pd.to_datetime(df['Date'])
    df.set_index('Date', inplace=True)
    df = df.apply(pd.to_numeric, errors='coerce')
    df = df.sort_index()
    
    _supabase_data_cache = {'df': df, 'time': now}
    return df.copy()


def get_transform_type(feature_name):
    """Return 'log_diff' or 'first_diff' based on the feature's base column."""
    base = feature_name.replace('_Lag1', '').replace('_3M_Trend', '')
    if base in LOG_DIFF_COLS:
        return 'log_diff'
    elif base in FIRST_DIFF_COLS:
        return 'first_diff'
    return 'unknown'


def convert_to_raw_space_coefficient(unscaled_coef, transform_type, feature_name, raw_df, current_zar_usd):
    """
    Convert coefficient from transformed space to raw space.
    
    Model is trained on:
    - Predictors: transformed (log-diff or first-diff)
    - Target: log-return (% change)
    
    We want coefficients that represent:
    - Predictors: raw levels
    - Target: raw ZAR per USD levels
    
    Args:
        unscaled_coef: Unscaled coefficient (effect on log-return in %)
        transform_type: 'log_diff' or 'first_diff'
        feature_name: Name of the feature
        raw_df: Original raw data
        current_zar_usd: Current ZAR per USD exchange rate level
    
    Returns:
        Coefficient in raw space (raw predictor → raw target)
        
    Mathematical derivation:
    
    Step 1: Convert target from log-return to level
    - Model: log_return = β * X_transformed
    - log_return ≈ ΔS / S * 100
    - Therefore: ΔS ≈ S * (β * X_transformed / 100)
    
    Step 2: Convert predictor from transformed to raw
    
    For log-diff predictors:
    - X_transformed = Δlog(X_raw) * 100 ≈ (ΔX_raw / X_raw) * 100
    - For a 1-unit increase in X_raw: ΔX_raw = 1
    - X_transformed ≈ (1 / X_raw) * 100
    - So: ΔS ≈ S * (β / 100) * (1 / X_raw) * 100 = S * β / X_raw
    - Raw coefficient: β_raw = S * β / X_raw
    
    For first-diff predictors:
    - X_transformed = ΔX_raw
    - For a 1-unit increase in X_raw: ΔX_raw = 1
    - X_transformed = 1
    - So: ΔS ≈ S * (β / 100)
    - Raw coefficient: β_raw = S * β / 100
    """
    # Step 1: Convert from log-return target to level target
    zar_level_coef = current_zar_usd * (unscaled_coef / 100)
    
    # Step 2: Convert from transformed predictor to raw predictor
    if transform_type == 'log_diff':
        # For log-differenced predictors
        # A 1-unit change in raw X creates a (100/X) change in log-diff space
        # So we need to divide by current raw level and multiply by 100
        base_feature = feature_name.replace('_Lag1', '').replace('_3M_Trend', '')
        if base_feature in raw_df.columns:
            current_raw_value = raw_df[base_feature].dropna().iloc[-1]
            # β_raw = (S * β / 100) / (100 / X) = S * β * X / 10000
            raw_space_coef = zar_level_coef / (100 / current_raw_value)
        else:
            raw_space_coef = zar_level_coef
        
    elif transform_type == 'first_diff':
        # For first-differenced predictors
        # A 1-unit change in raw X creates a 1-unit change in diff space
        # No additional conversion needed
        raw_space_coef = zar_level_coef
        
    else:
        raw_space_coef = zar_level_coef
    
    return raw_space_coef


def engineer_features(df):
    """
    Replicate the exact feature-engineering pipeline used during training.
    Optimised for memory: avoids unnecessary copies and caches results.
    """
    global _engineered_features_cache
    now = time.time()
    
    # Simple hash of the input dataframe to check if we can use cache
    # (Using shape and last few values as a proxy for 'same data')
    if not df.empty:
        current_hash = (df.shape, df.iloc[-1].sum(), df.index[-1])
        if (_engineered_features_cache['df_features'] is not None and 
            _engineered_features_cache['input_hash'] == current_hash and
            (now - _engineered_features_cache['time'] < 300)):
            return _engineered_features_cache['df_features'].copy(), _engineered_features_cache['df_raw'].copy()
    else:
        current_hash = None

    # Use float32 to save memory if precision allows (standard for these macro models)
    df = df.copy()
    for col in df.columns:
        if pd.api.types.is_numeric_dtype(df[col]):
            df[col] = df[col].astype('float32')

    # Inflation YoY & Differencing
    # We use a temporary series to avoid creating many intermediate columns in the main df
    sa_infl_yoy = df['SA_INFLATION'].pct_change(periods=12) * 100
    us_cpi_yoy = df['US_CPI'].pct_change(periods=12) * 100
    df['SA_INFLATION_YOY'] = sa_infl_yoy.astype('float32')
    df['US_CPI_YOY'] = us_cpi_yoy.astype('float32')
    df['INFLATION_DIFF'] = (sa_infl_yoy - us_cpi_yoy).astype('float32')
    df.drop(columns=['SA_INFLATION', 'US_CPI'], errors='ignore', inplace=True)
    df.dropna(inplace=True)

    log_cols = ['EPU(USA)', 'VIX', 'GOLD_PRICE', 'BRENT_OIL_PRICE', 'ZAR_USD']
    diff_cols = ['WUIZAF(SA)', '10_YEAR_BOND_RATES(USA)', '10_YEAR_BOND_RATES(SA)',
                 'SA_INFLATION_YOY', 'US_CPI_YOY', 'INFLATION_DIFF']

    # Pre-allocate df_transformed to avoid repeated growth
    df_transformed = pd.DataFrame(index=df.index)
    
    for col in log_cols:
        if col in df.columns:
            # Combined log and diff to reduce intermediate objects
            df_transformed[col] = (np.log(df[col]).diff() * 100).astype('float32')
            
    for col in diff_cols:
        if col in df.columns:
            df_transformed[col] = df[col].diff().astype('float32')
            
    df_transformed.dropna(inplace=True)

    # Use the transformed df as the base for features
    df_features = df_transformed.copy()

    # Lags - avoid loop if possible or keep it tight
    df_features['ZAR_USD_Lag1'] = df_features['ZAR_USD'].shift(1)
    lag_columns = ['VIX', '10_YEAR_BOND_RATES(SA)', 'INFLATION_DIFF',
                   'GOLD_PRICE', 'EPU(USA)', 'BRENT_OIL_PRICE']
    for col in lag_columns:
        if col in df_features.columns:
            df_features[f'{col}_Lag1'] = df_features[col].shift(1)

    # 3-Month Rolling Trends
    trend_columns = ['VIX', '10_YEAR_BOND_RATES(SA)', 'INFLATION_DIFF',
                     'GOLD_PRICE', 'BRENT_OIL_PRICE', 'ZAR_USD']
    for col in trend_columns:
        if col in df_transformed.columns:
            # Access shifted column directly to avoid extra copy
            df_features[f'{col}_3M_Trend'] = (
                df_transformed[col].shift(1).rolling(window=3).mean().astype('float32')
            )

    df_features.dropna(inplace=True)
    
    _engineered_features_cache = {
        'df_features': df_features,
        'df_raw': df,
        'input_hash': current_hash,
        'time': now
    }
    
    return df_features.copy(), df.copy()


def predict_next_month():
    """
    Generate a ZAR/USD prediction for the next month using the frozen model.
    Returns a dict with prediction details.
    """
    # Load main model for prediction
    model_data = load_model(trainset_model=False)
    model = model_data['model']
    scaler = model_data['scaler']
    feature_names = model_data.get('feature_names', [])
    # Trust the model object's coefficients over the dictionary metadata if available
    if hasattr(model, 'coef_'):
        # Get feature names from model if possible
        actual_coefs = model.coef_
        # Derive selected features (non-zero coefficients)
        # Sort by absolute coefficient value
        pairs = []
        for i, feat in enumerate(feature_names):
            if i < len(actual_coefs) and actual_coefs[i] != 0:
                pairs.append((feat, abs(actual_coefs[i]), actual_coefs[i]))
        pairs.sort(key=lambda x: x[1], reverse=True)
        selected_features = [p[0] for p in pairs]
        # Build a coefficients mapping from the actual model
        coefficients = {p[0]: p[2] for p in pairs}
    else:
        coefficients = model_data.get('coefficients', {})
        selected_features = model_data.get('selected_features', [])

    # Fetch raw data
    raw_df = fetch_data_from_supabase()

    # Engineer features once
    df_features, df_raw = engineer_features(raw_df)

    if df_features.empty:
        raise ValueError("Not enough data to compute features.")

    # ── NEXT MONTH PREDICTION ──
    # To predict the NEXT month (T+1), we need features derived from the LATEST data (T).
    
    # Let's re-calculate unshifted features for the last period
    last_raw_date = raw_df.index[-1]
    
    # We'll build the feature vector for T+1 manually using data up to T
    # 1. Get latest returns (T)
    # We need the same logic as engineer_features but without the final shift
    log_cols = ['EPU(USA)', 'VIX', 'GOLD_PRICE', 'BRENT_OIL_PRICE', 'ZAR_USD']
    diff_cols = ['WUIZAF(SA)', '10_YEAR_BOND_RATES(USA)', '10_YEAR_BOND_RATES(SA)',
                 'SA_INFLATION_YOY', 'US_CPI_YOY', 'INFLATION_DIFF']
    
    # Use the df_transformed logic but specifically for the latest values
    # We can just use df_features without the dropna and before the shift if we were inside engineer_features
    # But since we are outside, let's just use the fact that df_features[col] (the un-lagged ones) 
    # are the current period returns.
    
    next_month_features = {}
    # Target in df_features is unshifted return. 
    # So df_features['VIX'] at index T is VIX return at T.
    # This will be 'VIX_Lag1' for T+1.
    for col in ['VIX', '10_YEAR_BOND_RATES(SA)', 'INFLATION_DIFF', 'GOLD_PRICE', 'EPU(USA)', 'BRENT_OIL_PRICE', 'ZAR_USD']:
        if col in df_features.columns:
            next_month_features[f'{col}_Lag1'] = df_features[col].iloc[-1]
            
    # 3M Trends for T+1 use T, T-1, T-2
    for col in ['VIX', '10_YEAR_BOND_RATES(SA)', 'INFLATION_DIFF', 'GOLD_PRICE', 'BRENT_OIL_PRICE', 'ZAR_USD']:
        if col in df_features.columns:
            next_month_features[f'{col}_3M_Trend'] = df_features[col].tail(3).mean()

    X_next = pd.DataFrame([next_month_features])
    
    # Ensure all required features are present and in correct order
    feature_set = set(X_next.columns)
    for col in feature_names:
        if col not in feature_set:
            X_next[col] = 0.0
    X_next = X_next[feature_names]

    # Scale and predict
    X_scaled = scaler.transform(X_next)
    predicted_log_return = model.predict(X_scaled)[0]

    # Convert to level: prediction is log-return in % terms
    last_zar_usd = raw_df['ZAR_USD'].dropna().iloc[-1]
    predicted_level = last_zar_usd * np.exp(predicted_log_return / 100)
    predicted_change_pct = ((predicted_level - last_zar_usd) / last_zar_usd) * 100

    # Direction
    if predicted_change_pct > 0.05:
        direction = 'weaken'
    elif predicted_change_pct < -0.05:
        direction = 'strengthen'
    else:
        direction = 'stable'

    # Feature contributions for the selected (non-zero) features
    contributions = []
    for feat in selected_features:
        if feat in feature_names:
            idx = feature_names.index(feat)
            coef = coefficients.get(feat, model.coef_[idx])
            feat_val = X_scaled[0][idx]
            contribution = coef * feat_val
            scale = scaler.scale_[idx]
            transform_type = get_transform_type(feat)
            
            # Get interpretable coefficient (raw predictor level → raw target level)
            # Step 1: Unscale the coefficient (removes StandardScaler effect)
            unscaled_coef = coef / scale
            
            # Step 2: Convert from transformed space to raw space
            # This accounts for both target transformation (log-return → level)
            # and predictor transformation (diff/log-diff → raw level)
            current_zar_usd = raw_df['ZAR_USD'].dropna().iloc[-1]
            zar_level_coef = convert_to_raw_space_coefficient(
                unscaled_coef, transform_type, feat, raw_df, current_zar_usd
            )
            
            contributions.append({
                'feature': feat,
                'coefficient': coef,
                'unscaled_coefficient': unscaled_coef,
                'zar_level_coefficient': zar_level_coef,
                'transform_type': transform_type,
                'scaled_value': feat_val,
                'contribution': contribution,
            })
    contributions.sort(key=lambda x: abs(x['contribution']), reverse=True)

    # Build historical predictions for display only (limited to recent data to avoid leakage)
    # Use only last 120 observations (10 years) for chart to show more context
    recent_features = df_features.tail(120)
    # Ensure column order matches training
    X_recent = recent_features.drop(columns=['ZAR_USD'], errors='ignore')
    feature_set_recent = set(X_recent.columns)
    for col in feature_names:
        if col not in feature_set_recent:
            X_recent[col] = 0.0
    X_recent = X_recent[feature_names]
    X_recent_scaled = scaler.transform(X_recent)
    recent_predicted_returns = model.predict(X_recent_scaled)
    
    # Convert to levels for recent data only
    # Alignment fix: recent_predicted_returns corresponds to recent_features.index (Target at T)
    # We need raw_df['ZAR_USD'] at T-1 to multiply by exp(Predicted_Return_at_T)
    # Since df_features index is T, we need raw_df['ZAR_USD'].shift(1) at those indices
    recent_actual_prev = raw_df['ZAR_USD'].shift(1).reindex(recent_features.index)
    recent_actual_current = raw_df['ZAR_USD'].reindex(recent_features.index)
    
    # Filter for non-NaN indices where both previous value and prediction exist
    valid_mask = recent_actual_prev.notna() & recent_actual_current.notna()
    recent_common_idx = recent_features.index[valid_mask]
    
    if len(recent_common_idx) > 0:
        aligned_recent_returns = recent_predicted_returns[valid_mask]
        aligned_recent_prev = recent_actual_prev.loc[recent_common_idx]
        hist_pred_levels = aligned_recent_prev.values * np.exp(aligned_recent_returns / 100)
        hist_actual_levels = raw_df['ZAR_USD'].reindex(recent_common_idx)
    else:
        hist_pred_levels = np.array([])
        hist_actual_levels = pd.Series([], dtype=float)
        recent_common_idx = []

    # Clean recent data: remove any NaN values
    if len(recent_common_idx) > 0 and len(hist_actual_levels) > 0:
        actual_values = hist_actual_levels.values
        pred_values = hist_pred_levels
        
        # Create boolean mask for NaNs
        final_valid_mask = ~(np.isnan(actual_values) | np.isnan(pred_values))
        
        actual_values = actual_values[final_valid_mask]
        pred_values = pred_values[final_valid_mask]
        recent_common_idx = [recent_common_idx[i] for i, valid in enumerate(final_valid_mask) if valid]
        
        hist_actual_levels = actual_values
        hist_pred_levels = pred_values
    else:
        recent_common_idx = []
        hist_actual_levels = np.array([])
        hist_pred_levels = np.array([])

    # Load trainset model for validation metrics
    trainset_model_data = load_model(trainset_model=True)
    trainset_model = trainset_model_data['model']
    trainset_scaler = trainset_model_data['scaler']
    trainset_feature_names = trainset_model_data.get('feature_names', [])
    
    # Robustly handle missing feature names for trainset
    if not trainset_feature_names and hasattr(trainset_scaler, 'feature_names_in_'):
        trainset_feature_names = list(trainset_scaler.feature_names_in_)

    # Extract selected features for the trainset model specifically for diagnostic plots
    # Trust the trainset_model's coefficients
    if hasattr(trainset_model, 'coef_'):
        pairs = []
        for i, feat in enumerate(trainset_feature_names):
            if i < len(trainset_model.coef_) and trainset_model.coef_[i] != 0:
                pairs.append((feat, abs(trainset_model.coef_[i])))
        pairs.sort(key=lambda x: x[1], reverse=True)
        trainset_selected = [p[0] for p in pairs]
    else:
        trainset_selected = trainset_model_data.get('selected_features', [])
    
    # Use trainset_selected for plots to ensure they reflect the actual trainset_model residuals
    plot_features = trainset_selected if trainset_selected else selected_features
    
    # Implement proper walk-forward validation to avoid leakage
    # Use only the last 20% of data for validation (out-of-sample)
    validation_split_idx = int(len(df_features) * 0.8)
    validation_features = df_features.iloc[validation_split_idx:]
    validation_actual = raw_df['ZAR_USD'].iloc[validation_split_idx:]
    
    # Prepare validation data for trainset model
    X_validation = validation_features.drop(columns=['ZAR_USD'], errors='ignore')
    trainset_missing = [f for f in trainset_feature_names if f not in X_validation.columns]
    for col in trainset_missing:
        X_validation[col] = 0.0
    X_validation = X_validation[trainset_feature_names]
    X_validation_scaled = trainset_scaler.transform(X_validation)
    validation_predicted_returns = trainset_model.predict(X_validation_scaled)
    
    # Convert validation predictions to levels
    validation_prev = validation_actual.shift(1).dropna()
    
    # Remove debug prints
    # print(f"DEBUG: validation_prev shape: {validation_prev.shape}")
    # print(f"DEBUG: validation_predicted_returns shape: {validation_predicted_returns.shape}")
    # print(f"DEBUG: validation_actual shape: {validation_actual.shape}")
    
    # Ensure we have valid data before proceeding
    # Alignment fix for walk-forward validation
    # validation_predicted_returns corresponds to validation_features.index
    # We need validation_actual.shift(1) to get the baseline for each prediction
    val_prev = raw_df['ZAR_USD'].shift(1).reindex(validation_features.index)
    val_actual = raw_df['ZAR_USD'].reindex(validation_features.index)
    
    # Filter for indices where we have both a previous value and an actual current value
    valid_val_mask = val_prev.notna() & val_actual.notna()
    val_valid_indices = validation_features.index[valid_val_mask]
    
    if len(val_valid_indices) == 0:
        # Fallback if no validation data
        mae = rmse = r2 = mape = directional_accuracy = 0.0
        validation_actual_levels = pd.Series([], dtype=float)
        validation_pred_levels = np.array([])
    else:
        # Calculate levels using the valid subset
        val_aligned_prev = val_prev.loc[val_valid_indices]
        val_aligned_returns = validation_predicted_returns[valid_val_mask]
        
        validation_pred_levels = val_aligned_prev.values * np.exp(val_aligned_returns / 100)
        validation_actual_levels = val_actual.loc[val_valid_indices]
    
    # Clean validation data
    if len(validation_actual_levels) > 0 and len(validation_pred_levels) > 0:
        actual_values = validation_actual_levels.values
        pred_values = validation_pred_levels
        
        # Create boolean mask for NaNs (should be clean now but double check)
        final_valid_mask = ~(np.isnan(actual_values) | np.isnan(pred_values))
        
        actual_values = actual_values[final_valid_mask]
        pred_values = pred_values[final_valid_mask]
        
        validation_actual_levels = pd.Series(actual_values)
        validation_pred_levels = pred_values
    else:
        validation_actual_levels = pd.Series([], dtype=float)
        validation_pred_levels = np.array([])
    
    # Calculate validation metrics using only out-of-sample data
    from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score, median_absolute_error, explained_variance_score
    if len(validation_actual_levels) > 0 and len(validation_pred_levels) > 0:
        actual_val_arr = validation_actual_levels.values
        pred_val_arr = validation_pred_levels
        
        mae = mean_absolute_error(actual_val_arr, pred_val_arr)
        rmse = np.sqrt(mean_squared_error(actual_val_arr, pred_val_arr))
        r2 = r2_score(actual_val_arr, pred_val_arr)
        mape = np.mean(np.abs((actual_val_arr - pred_val_arr) / actual_val_arr)) * 100
        medae = median_absolute_error(actual_val_arr, pred_val_arr)
        evs = explained_variance_score(actual_val_arr, pred_val_arr)
        max_err = np.max(np.abs(actual_val_arr - pred_val_arr))
        
        # Directional accuracy using out-of-sample data
        if len(actual_val_arr) > 1:
            actual_changes = np.sign(actual_val_arr[1:] - actual_val_arr[:-1])
            pred_changes = np.sign(pred_val_arr[1:] - actual_val_arr[:-1])
            directional_accuracy = (actual_changes == pred_changes).mean() * 100
        else:
            directional_accuracy = 0.0
    else:
        mae = rmse = r2 = mape = directional_accuracy = medae = evs = max_err = 0.0

    # Last date and next month date
    last_date = raw_df.index[-1]
    next_month_date = last_date + pd.offsets.MonthEnd(1)

    # Actual vs Predicted for diagnostic plots (only for validation data)
    actual_vs_predicted = {}
    partial_plots = {}
    
    if len(validation_actual_levels) > 0 and len(validation_pred_levels) > 0:
        # Calculate residuals in level space
        residuals_array = validation_actual_levels.values - validation_pred_levels
        
        # Actual vs Predicted data
        actual_vs_predicted = {
            'actual': [float(a) for a in validation_actual_levels.values],
            'predicted': [float(p) for p in validation_pred_levels],
        }
        
        # Partial plots for each selected feature
        # Show relationship between each predictor and target holding others constant
        for feat in plot_features[:5]:  # Limit to top 5 to avoid overwhelming
            if feat in trainset_feature_names:
                feat_idx = trainset_feature_names.index(feat)
                
                # Get feature values from validation set
                feat_values_scaled = X_validation_scaled[:, feat_idx]
                
                # Unscale feature values for interpretability
                feat_scale = trainset_scaler.scale_[feat_idx]
                feat_mean = trainset_scaler.mean_[feat_idx]
                feat_values_unscaled = feat_values_scaled * feat_scale + feat_mean
                
                # Get partial residuals: residual + feature contribution
                feat_coef = trainset_model.coef_[feat_idx]
                partial_residuals = residuals_array + (feat_coef * feat_values_scaled)
                
                partial_plots[feat] = {
                    'x': [float(v) for v in feat_values_unscaled],
                    'y': [float(r) for r in partial_residuals],
                    'transform_type': get_transform_type(feat),
                }

    # Extract model parameters robustly for the dashboard UI
    alpha = model_data.get('alpha')
    if alpha is None:
        alpha = getattr(model, 'alpha_', getattr(model, 'alpha', 0.0))
    if isinstance(alpha, (list, np.ndarray)) and len(alpha) > 0:
        alpha = alpha[0]

    l1_ratio = model_data.get('l1_ratio')
    if l1_ratio is None:
        l1_ratio = getattr(model, 'l1_ratio_', getattr(model, 'l1_ratio', 0.0))
    if isinstance(l1_ratio, (list, np.ndarray)) and len(l1_ratio) > 0:
        l1_ratio = l1_ratio[0]

    intercept = model_data.get('intercept')
    if intercept is None:
        intercept = getattr(model, 'intercept_', 0.0)
    if isinstance(intercept, (list, np.ndarray)) and len(intercept) > 0:
        intercept = intercept[0]

    training_obs = model_data.get('training_observations', len(df_features))
    training_range = model_data.get('training_date_range')
    if training_range is None:
        try:
            first_date = df_features.index[0].strftime('%Y-%m')
            last_date_str = df_features.index[-1].strftime('%Y-%m')
            training_range = f"{first_date} to {last_date_str}"
        except Exception:
            training_range = "Unknown"

    # Multi-horizon predictions (1m, 3m, 6m, 1y) with reasoning
    forecasts = {}
    current_idx = raw_df.index[-1]
    last_zar_usd = float(raw_df['ZAR_USD'].dropna().iloc[-1])
    
    # Get top 3 drivers for reasoning
    top_drivers = []
    for c in contributions[:3]:
        feat_name = get_friendly_feature_name(c['feature'], c['transform_type'])
        impact = "upward" if c['contribution'] > 0 else "downward"
        top_drivers.append(f"{feat_name} ({impact})")
    
    base_reason = "Mainly driven by " + ", ".join(top_drivers) if top_drivers else "Stabilized by offsetting macro factors."
    
    # Iteratively predict for 1m, 3m, 6m horizons
    # For a baseline forecast, we assume macro drivers stay at their last levels
    horizons = {'1m': 1, '3m': 3, '6m': 6}
    max_h = max(horizons.values())
    
    iterative_df = raw_df.copy()
    h_levels = {}
    
    # Pre-calculate engineer_features only once per step for all horizons combined
    for i in range(1, max_h + 1):
        try:
            # We only need the latest features, but engineer_features processes everything.
            # However, for 100 rows, it's faster to just call it than to re-implement.
            # We optimize by not doing it 10 times.
            df_feat_iter, _ = engineer_features(iterative_df)
            if df_feat_iter.empty: break
            
            X_iter = df_feat_iter.iloc[[-1]].drop(columns=['ZAR_USD'], errors='ignore')
            # Ensure columns match
            X_iter_aligned = pd.DataFrame(index=[0], columns=feature_names).fillna(0.0)
            for col in feature_names:
                if col in X_iter.columns:
                    X_iter_aligned.at[0, col] = X_iter[col].iloc[0]
            
            X_iter_scaled = scaler.transform(X_iter_aligned)
            pred_log_ret_iter = model.predict(X_iter_scaled)[0]
            
            last_level_iter = iterative_df['ZAR_USD'].iloc[-1]
            next_level_iter = last_level_iter * np.exp(pred_log_ret_iter / 100)
            
            next_date_iter = iterative_df.index[-1] + pd.offsets.MonthEnd(1)
            new_row = iterative_df.iloc[-1].copy()
            new_row.name = next_date_iter
            new_row['ZAR_USD'] = next_level_iter
            iterative_df = pd.concat([iterative_df, pd.DataFrame([new_row])])
            
            # Store levels for specific horizons
            for label, h_val in horizons.items():
                if i == h_val:
                    h_levels[label] = (float(next_level_iter), next_date_iter)
        except Exception:
            break

    for label, h_val in horizons.items():
        if label not in h_levels:
            continue
            
        final_level, final_date = h_levels[label]
        actual_est = last_zar_usd 
        diff = final_level - actual_est
        pct_diff = (diff / actual_est) * 100
        
        if abs(pct_diff) < 0.5:
            reason = "Fair value is aligned with current spot, suggesting the market has fully priced in macro drivers."
        elif diff > 0:
            driver = top_drivers[0] if top_drivers else "macro factors"
            reason = f"Model identifies undervaluation; {driver} suggest a fair value higher than current spot."
        else:
            driver = top_drivers[0] if top_drivers else "macro factors"
            reason = f"Model identifies overvaluation; strong fundamentals in {driver} suggest ZAR should be stronger than current spot."

        forecasts[label] = {
            'fair_value': round(final_level, 4),
            'actual_estimate': round(actual_est, 4),
            'date': final_date.strftime('%Y-%m-%d'),
            'reason': reason
        }

    # Limit history to 60 months for UI charts to save memory/bandwidth
    # The full history is still used for metrics, but we only send 5 years to the frontend
    chart_limit = 60
    if len(recent_common_idx) > chart_limit:
        hist_dates_json = [d.strftime('%Y-%m-%d') for d in recent_common_idx[-chart_limit:]]
        hist_actual_json = [float(v) for v in hist_actual_levels[-chart_limit:]]
        hist_pred_json = [float(v) for v in hist_pred_levels[-chart_limit:]]
    else:
        hist_dates_json = [d.strftime('%Y-%m-%d') for d in recent_common_idx]
        hist_actual_json = [float(v) for v in hist_actual_levels]
        hist_pred_json = [float(v) for v in hist_pred_levels]

    return {
        'predicted_level': round(float(predicted_level), 4),
        'predicted_change_pct': round(float(predicted_change_pct), 2),
        'predicted_log_return': round(float(predicted_log_return), 4),
        'direction': direction,
        'last_zar_usd': round(float(last_zar_usd), 4),
        'last_date': last_date.strftime('%Y-%m-%d'),
        'next_month_date': next_month_date.strftime('%Y-%m-%d'),
        'contributions': contributions,
        'selected_features': selected_features,
        'forecasts': forecasts,
        'model_info': {
            'alpha': float(alpha) if alpha is not None else None,
            'l1_ratio': float(l1_ratio) if l1_ratio is not None else None,
            'intercept': float(intercept) if intercept is not None else None,
            'training_observations': training_obs,
            'training_date_range': training_range,
            'n_features': len(feature_names),
            'n_selected': len(selected_features),
        },
        'metrics': {
            'mae': float(mae),
            'rmse': float(rmse),
            'r2': float(r2),
            'mape': float(mape),
            'medae': float(medae),
            'evs': float(evs),
            'max_error': float(max_err),
            'directional_accuracy': float(directional_accuracy),
        },
        'history': {
            'dates': hist_dates_json,
            'actual': hist_actual_json,
            'predicted': hist_pred_json,
        },
        'diagnostics': {
            'actual_vs_predicted': actual_vs_predicted,
            'partial_plots': partial_plots,
        }
    }


def get_scenario_baseline():
    """
    Return the baseline data needed for scenario analysis:
    - Current raw predictor values
    - Selected features and their coefficients
    - Base prediction (no changes)
    - Historical ranges for each raw predictor (for slider bounds)
    """
    model_data = load_model(trainset_model=False)
    model = model_data['model']
    scaler = model_data['scaler']
    feature_names = model_data['feature_names']
    selected_features = model_data.get('selected_features', [])

    raw_df = fetch_data_from_supabase()
    df_features, df_raw = engineer_features(raw_df)

    if df_features.empty:
        raise ValueError("Not enough data to compute features.")

    # Base prediction (current values)
    latest_row = df_features.iloc[[-1]]
    X_latest = latest_row.drop(columns=['ZAR_USD'], errors='ignore')
    missing = [f for f in feature_names if f not in X_latest.columns]
    for col in missing:
        X_latest[col] = 0.0
    X_latest = X_latest[feature_names]

    X_scaled = scaler.transform(X_latest)
    base_log_return = model.predict(X_scaled)[0]
    last_zar_usd = raw_df['ZAR_USD'].dropna().iloc[-1]
    base_level = last_zar_usd * np.exp(base_log_return / 100)

    last_date = raw_df.index[-1]
    next_month_date = last_date + pd.offsets.MonthEnd(1)

    # Identify which RAW predictors feed into selected features
    # Map selected engineered features back to their raw base columns
    raw_predictor_map = {}
    for feat in selected_features:
        base = feat.replace('_Lag1', '').replace('_3M_Trend', '')
        # Skip ZAR_USD variants — user can't control the target
        if base == 'ZAR_USD':
            continue
        if base not in raw_predictor_map:
            raw_predictor_map[base] = []
        raw_predictor_map[base].append(feat)

    # Build slider config for each raw predictor
    predictors_config = []
    for raw_col, eng_features in raw_predictor_map.items():
        # Get current raw value (latest)
        if raw_col in raw_df.columns:
            current_val = float(raw_df[raw_col].dropna().iloc[-1])
            hist_series = raw_df[raw_col].dropna()
            hist_min = float(hist_series.min())
            hist_max = float(hist_series.max())
            hist_mean = float(hist_series.mean())
            hist_std = float(hist_series.std())
        elif raw_col in df_raw.columns:
            current_val = float(df_raw[raw_col].dropna().iloc[-1])
            hist_series = df_raw[raw_col].dropna()
            hist_min = float(hist_series.min())
            hist_max = float(hist_series.max())
            hist_mean = float(hist_series.mean())
            hist_std = float(hist_series.std())
        else:
            continue

        # Determine slider range: ±4 std from current, bounded by expanded historical range
        range_low = max(hist_min * 0.3, current_val - 4 * hist_std)
        range_high = min(hist_max * 2.0, current_val + 4 * hist_std)
        # Ensure range is sensible
        if range_low >= range_high:
            range_low = hist_min * 0.5
            range_high = hist_max * 1.8

        transform_type = get_transform_type(raw_col)

        predictors_config.append({
            'raw_col': raw_col,
            'engineered_features': eng_features,
            'current_value': round(current_val, 4),
            'hist_min': round(hist_min, 4),
            'hist_max': round(hist_max, 4),
            'hist_mean': round(hist_mean, 4),
            'range_low': round(range_low, 4),
            'range_high': round(range_high, 4),
            'transform_type': transform_type,
        })

    return {
        'predictors': predictors_config,
        'base_prediction': round(float(base_level), 4),
        'base_log_return': round(float(base_log_return), 4),
        'last_zar_usd': round(float(last_zar_usd), 4),
        'last_date': last_date.strftime('%Y-%m-%d'),
        'next_month_date': next_month_date.strftime('%Y-%m-%d'),
        'selected_features': selected_features,
        'feature_names': feature_names,
    }


def scenario_predict(scenario_values):
    """
    Run a scenario prediction given modified raw predictor values.

    Args:
        scenario_values: dict mapping raw column names to new values,
                         e.g. {'VIX': 25.0, 'GOLD_PRICE': 2800.0}

    Returns:
        dict with scenario prediction, base prediction, waterfall contributions
    """
    model_data = load_model(trainset_model=False)
    model = model_data['model']
    scaler = model_data['scaler']
    feature_names = model_data['feature_names']
    selected_features = model_data.get('selected_features', [])

    raw_df = fetch_data_from_supabase()

    # --- BASE prediction (unmodified) ---
    df_features_base, df_raw_base = engineer_features(raw_df)
    latest_base = df_features_base.iloc[[-1]].drop(columns=['ZAR_USD'], errors='ignore')
    for col in [f for f in feature_names if f not in latest_base.columns]:
        latest_base[col] = 0.0
    latest_base = latest_base[feature_names]
    X_base_scaled = scaler.transform(latest_base)
    base_log_return = float(model.predict(X_base_scaled)[0])
    last_zar_usd = float(raw_df['ZAR_USD'].dropna().iloc[-1])
    base_level = last_zar_usd * np.exp(base_log_return / 100)

    # --- SCENARIO prediction (with modified last row) ---
    raw_df_scenario = raw_df.copy()
    last_idx = raw_df_scenario.index[-1]
    for raw_col, new_val in scenario_values.items():
        if raw_col in raw_df_scenario.columns:
            raw_df_scenario.loc[last_idx, raw_col] = new_val

    df_features_scen, df_raw_scen = engineer_features(raw_df_scenario)
    latest_scen = df_features_scen.iloc[[-1]].drop(columns=['ZAR_USD'], errors='ignore')
    for col in [f for f in feature_names if f not in latest_scen.columns]:
        latest_scen[col] = 0.0
    latest_scen = latest_scen[feature_names]
    X_scen_scaled = scaler.transform(latest_scen)
    scen_log_return = float(model.predict(X_scen_scaled)[0])
    scen_level = last_zar_usd * np.exp(scen_log_return / 100)

    # --- Waterfall: per-feature contribution difference ---
    waterfall = []
    for feat in selected_features:
        if feat in feature_names:
            idx = feature_names.index(feat)
            coef = float(model.coef_[idx])
            base_val = float(X_base_scaled[0][idx])
            scen_val = float(X_scen_scaled[0][idx])
            base_contrib = coef * base_val
            scen_contrib = coef * scen_val
            delta_contrib = scen_contrib - base_contrib

            waterfall.append({
                'feature': feat,
                'base_contribution': round(base_contrib, 6),
                'scenario_contribution': round(scen_contrib, 6),
                'delta': round(delta_contrib, 6),
                'transform_type': get_transform_type(feat),
            })

    waterfall.sort(key=lambda x: abs(x['delta']), reverse=True)

    last_date = raw_df.index[-1]
    next_month_date = last_date + pd.offsets.MonthEnd(1)

    scen_change_pct = ((scen_level - last_zar_usd) / last_zar_usd) * 100
    base_change_pct = ((base_level - last_zar_usd) / last_zar_usd) * 100

    return {
        'base_level': round(float(base_level), 4),
        'base_change_pct': round(float(base_change_pct), 2),
        'scenario_level': round(float(scen_level), 4),
        'scenario_change_pct': round(float(scen_change_pct), 2),
        'delta_level': round(float(scen_level - base_level), 4),
        'last_zar_usd': round(float(last_zar_usd), 4),
        'last_date': last_date.strftime('%Y-%m-%d'),
        'next_month_date': next_month_date.strftime('%Y-%m-%d'),
        'waterfall': waterfall,
        'scenario_values': {k: round(float(v), 4) for k, v in scenario_values.items()},
    }
