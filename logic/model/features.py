"""Feature engineering for the ZAR/USD HuberRegressor pipeline.

Owns:
  - The 11-feature column list (`FEATURE_LIST`) and metadata
    (`BASE_FEATURE_NAMES`, `FEATURE_CATEGORIES`, `SCENARIO_RAW_PREDICTORS`).
  - Friendly-name / category / unit lookup helpers.
  - `engineer_features(raw_df)` — the lag / log-return / z-score builder.
"""
import threading
import time


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

_engineered_features_cache = {'df_features': None, 'df_raw': None, 'input_hash': None, 'time': 0}
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
