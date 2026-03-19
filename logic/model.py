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

MODEL_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'zar_usd_model_v1.pkl')

_model_cache = {}


def load_model():
    """Load the frozen ElasticNet model from disk (cached)."""
    if JOBLIB_IMPORT_ERROR is not None:
        raise RuntimeError(
            "Model dependencies are unavailable in this Python environment. "
            "Install joblib (and the model's sklearn-compatible dependencies) in .venv to use the Model page."
        ) from JOBLIB_IMPORT_ERROR
    if 'model_data' not in _model_cache:
        if not os.path.exists(MODEL_PATH):
            raise FileNotFoundError(f"Model file not found: {MODEL_PATH}")
        _model_cache['model_data'] = joblib.load(MODEL_PATH)
        logger.info("Loaded ZAR/USD ElasticNet model from %s", MODEL_PATH)
    return _model_cache['model_data']


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

    df_features = df_features.dropna()
    return df_features, df


def predict_next_month():
    """
    Generate a ZAR/USD prediction for the next month using the frozen model.
    Returns a dict with prediction details.
    """
    model_data = load_model()
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

    # Build historical predictions for the chart
    X_all = df_features.drop(columns=['ZAR_USD'], errors='ignore')
    for col in missing:
        X_all[col] = 0.0
    X_all = X_all[feature_names]
    X_all_scaled = scaler.transform(X_all)
    predicted_returns = model.predict(X_all_scaled)

    # Convert to levels
    actual_prev = raw_df['ZAR_USD'].shift(1).reindex(df_features.index).dropna()
    common_idx = actual_prev.index.intersection(df_features.index)
    hist_pred_levels = actual_prev.loc[common_idx] * np.exp(
        predicted_returns[:len(common_idx)] / 100
    )
    hist_actual_levels = raw_df['ZAR_USD'].reindex(common_idx)

    # Clean data: remove any NaN values
    valid_mask = ~(hist_actual_levels.isna() | hist_pred_levels.isna())
    common_idx = common_idx[valid_mask]
    hist_actual_levels = hist_actual_levels[valid_mask]
    hist_pred_levels = hist_pred_levels[valid_mask]

    # Calculate in-sample metrics (full dataset performance)
    from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
    mae = mean_absolute_error(hist_actual_levels, hist_pred_levels)
    rmse = np.sqrt(mean_squared_error(hist_actual_levels, hist_pred_levels))
    r2 = r2_score(hist_actual_levels, hist_pred_levels)
    mape = np.mean(np.abs((hist_actual_levels.values - hist_pred_levels.values) / hist_actual_levels.values)) * 100

    # Directional accuracy
    actual_changes = np.sign(hist_actual_levels.values[1:] - hist_actual_levels.values[:-1])
    pred_changes = np.sign(hist_pred_levels.values[1:] - hist_actual_levels.values[:-1])
    directional_accuracy = (actual_changes == pred_changes).mean() * 100

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
            'dates': [d.strftime('%Y-%m-%d') for d in common_idx],
            'actual': [float(v) for v in hist_actual_levels.values],
            'predicted': [float(v) for v in hist_pred_levels.values],
        }
    }
