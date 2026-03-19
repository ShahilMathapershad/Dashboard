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
    
    if cache_key not in _model_cache:
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"Model file not found: {model_path}")
        _model_cache[cache_key] = joblib.load(model_path)
        logger.info("Loaded ZAR/USD ElasticNet model from %s", model_path)
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
    feature_names = model_data['feature_names']
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
            contributions.append({
                'feature': feat,
                'coefficient': coef,
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
    trainset_feature_names = trainset_model_data['feature_names']
    
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

    return {
        'predicted_level': round(predicted_level, 4),
        'predicted_change_pct': round(predicted_change_pct, 2),
        'predicted_log_return': round(predicted_log_return, 4),
        'direction': direction,
        'last_zar_usd': round(last_zar_usd, 4),
        'last_date': last_date.strftime('%Y-%m-%d'),
        'next_month_date': next_month_date.strftime('%Y-%m-%d'),
        'contributions': contributions,
        'selected_features': selected_features,
        'model_info': {
            'alpha': model_data.get('alpha'),
            'l1_ratio': model_data.get('l1_ratio'),
            'intercept': model_data.get('intercept'),
            'training_observations': model_data.get('training_observations'),
            'training_date_range': model_data.get('training_date_range'),
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
        }
    }
