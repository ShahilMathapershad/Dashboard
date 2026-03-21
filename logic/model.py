import numpy as np
import pandas as pd
import os
import logging

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
    """Fetch all rows from the Supabase 'data' table, return a DatetimeIndex DataFrame."""
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
    return df


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
    Input df must have columns: EPU(USA), VIX, GOLD_PRICE, BRENT_OIL_PRICE,
    WUIZAF(SA), 10_YEAR_BOND_RATES(USA), 10_YEAR_BOND_RATES(SA),
    SA_INFLATION, US_CPI, ZAR_USD
    """
    df = df.copy()

    # Inflation YoY & Differencing
    df['SA_INFLATION_YOY'] = df['SA_INFLATION'].pct_change(periods=12) * 100
    df['US_CPI_YOY'] = df['US_CPI'].pct_change(periods=12) * 100
    df['INFLATION_DIFF'] = df['SA_INFLATION_YOY'] - df['US_CPI_YOY']
    df = df.drop(columns=['SA_INFLATION', 'US_CPI'], errors='ignore').dropna()

    log_cols = ['EPU(USA)', 'VIX', 'GOLD_PRICE', 'BRENT_OIL_PRICE', 'ZAR_USD']
    diff_cols = ['WUIZAF(SA)', '10_YEAR_BOND_RATES(USA)', '10_YEAR_BOND_RATES(SA)',
                 'SA_INFLATION_YOY', 'US_CPI_YOY', 'INFLATION_DIFF']

    df_transformed = pd.DataFrame(index=df.index)
    for col in log_cols:
        if col in df.columns:
            df_transformed[col] = np.log(df[col]).diff() * 100
    for col in diff_cols:
        if col in df.columns:
            df_transformed[col] = df[col].diff()
    df_transformed = df_transformed.dropna()

    df_features = df_transformed.copy()

    # Lags
    # Note: ZAR_USD_Lag1 is engineered from df_features (which is diff'd)
    # The training code has: df_features['ZAR_USD_Lag1'] = df_features['ZAR_USD'].shift(1)
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
            df_features[f'{col}_3M_Trend'] = (
                df_transformed[col].shift(1).rolling(window=3).mean()
            )

    # The target variable for prediction is ZAR_USD in df_features (which is log return * 100)
    # We keep it for now as 'ZAR_USD' and drop it before feeding to model.
    df_features = df_features.dropna()
    return df_features, df


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

    # Engineer features
    df_features, df_raw = engineer_features(raw_df)

    if df_features.empty:
        raise ValueError("Not enough data to compute features.")

    # Prepare the latest row for prediction
    latest_row = df_features.iloc[[-1]]
    X_latest = latest_row.drop(columns=['ZAR_USD'], errors='ignore')

    # Ensure column order matches training
    missing = [f for f in feature_names if f not in X_latest.columns]
    for col in missing:
        X_latest[col] = 0.0
    X_latest = X_latest[feature_names]

    # Scale and predict
    X_scaled = scaler.transform(X_latest)
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
    # Use only last 50 observations for chart to avoid showing training performance
    recent_features = df_features.tail(50)
    X_recent = recent_features.drop(columns=['ZAR_USD'], errors='ignore')
    for col in missing:
        X_recent[col] = 0.0
    X_recent = X_recent[feature_names]
    X_recent_scaled = scaler.transform(X_recent)
    recent_predicted_returns = model.predict(X_recent_scaled)
    
    # Convert to levels for recent data only
    # Alignment fix: recent_predicted_returns corresponds to recent_features.index
    # recent_actual_prev should align with the index and shift
    recent_actual_prev = raw_df['ZAR_USD'].shift(1).reindex(recent_features.index)
    
    # Filter for non-NaN indices where both previous value and prediction exist
    valid_mask = recent_actual_prev.notna()
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
        # Convert to numpy arrays consistently
        
        # Get values as numpy arrays
        if isinstance(hist_actual_levels, pd.Series):
            actual_values = hist_actual_levels.values
        else:
            actual_values = np.array(hist_actual_levels)
            
        if isinstance(hist_pred_levels, pd.Series):
            pred_values = hist_pred_levels.values
        else:
            pred_values = np.array(hist_pred_levels)
        
        # Create boolean mask
        valid_mask = ~(np.isnan(actual_values) | np.isnan(pred_values))
        
        # Apply mask to both arrays
        actual_values = actual_values[valid_mask]
        pred_values = pred_values[valid_mask]
        
        # Update index to match filtered data
        valid_indices = [i for i, valid in enumerate(valid_mask) if valid]
        recent_common_idx = [recent_common_idx[i] for i in valid_indices]
        
        # Convert back to pandas Series for consistency with downstream code
        if isinstance(hist_actual_levels, pd.Series):
            hist_actual_levels = pd.Series(actual_values)
        else:
            hist_actual_levels = actual_values
        hist_pred_levels = pred_values
    else:
        recent_common_idx = []

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
    from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
    if len(validation_actual_levels) > 0 and len(validation_pred_levels) > 0:
        mae = mean_absolute_error(validation_actual_levels, validation_pred_levels)
        rmse = np.sqrt(mean_squared_error(validation_actual_levels, validation_pred_levels))
        r2 = r2_score(validation_actual_levels, validation_pred_levels)
        mape = np.mean(np.abs((validation_actual_levels.values - validation_pred_levels) / validation_actual_levels.values)) * 100
        
        # Directional accuracy using out-of-sample data
        if len(validation_actual_levels) > 1:
            actual_changes = np.sign(validation_actual_levels.values[1:] - validation_actual_levels.values[:-1])
            pred_changes = np.sign(validation_pred_levels[1:] - validation_actual_levels.values[:-1])
            directional_accuracy = (actual_changes == pred_changes).mean() * 100
        else:
            directional_accuracy = 0.0
    else:
        # Metrics already set to 0.0 in fallback section above
        pass

    # Last date and next month date
    last_date = raw_df.index[-1]
    next_month_date = last_date + pd.offsets.MonthEnd(1)

    # Calculate residuals for diagnostic plots (only for validation data)
    residuals = []
    qq_data = {}
    partial_plots = {}
    
    if len(validation_actual_levels) > 0 and len(validation_pred_levels) > 0:
        # Calculate residuals in level space
        residuals_array = validation_actual_levels.values - validation_pred_levels
        
        # QQ plot data (theoretical quantiles vs sample quantiles)
        from scipy import stats
        residuals_sorted = np.sort(residuals_array)
        theoretical_quantiles = stats.norm.ppf(np.linspace(0.01, 0.99, len(residuals_sorted)))
        
        qq_data = {
            'theoretical': [float(q) for q in theoretical_quantiles],
            'sample': [float(r) for r in residuals_sorted],
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
            'mae': round(mae, 4),
            'rmse': round(rmse, 4),
            'r2': round(r2, 4),
            'mape': round(mape, 2),
            'directional_accuracy': round(directional_accuracy, 1),
        },
        'history': {
            'dates': [d.strftime('%Y-%m-%d') for d in recent_common_idx],
            'actual': [float(v) for v in hist_actual_levels],
            'predicted': [float(v) for v in hist_pred_levels],
        },
        'diagnostics': {
            'qq_plot': qq_data,
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
