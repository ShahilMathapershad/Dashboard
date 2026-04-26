"""Model loading + shared cache primitives + Supabase data fetch fallback.

Owns:
  - The frozen HuberRegressor pipeline loader (`load_model`).
  - The shared diskcache (`_persistent_cache`) used by every other model
    sub-module for cross-process result caching.
  - A local rehost of `fetch_data_from_supabase` so this package keeps
    working before Task 3 (logic/data split) lands. Once Task 3 ships
    the canonical implementation in `logic.data`, the package `__init__`
    re-exports from there preferentially.
"""
import logging
import os
import threading
import time

import diskcache

from logic.supabase_client import get_supabase

# Persistent cache for Supabase data + model results. Shared across separate
# background processes (gunicorn workers + Dash background callbacks).
_persistent_cache = diskcache.Cache("./.cache/data", size_limit=2**25)  # 32MB

try:
    import joblib
    JOBLIB_IMPORT_ERROR = None
except ModuleNotFoundError as exc:  # pragma: no cover - exercised at deploy time
    joblib = None
    JOBLIB_IMPORT_ERROR = exc

logger = logging.getLogger("ModelPredictor")

MODEL_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'models', 'zar_usd_forecast_model.pkl',
)
TRAIN_ONLY_MODEL_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'models', 'zar_usd_forecast_model_train_only.pkl',
)

_MODEL_CACHE_KEY = 'model_data'
_model_cache = {}

# In-memory cache for `fetch_data_from_supabase` (5-minute TTL). Lives here so
# every consumer in the package shares one cache.
_supabase_data_cache = {'df': None, 'time': 0}
_supabase_data_lock = threading.Lock()


def load_model():
    """Load the frozen HuberRegressor pipeline from disk (cached)."""
    if JOBLIB_IMPORT_ERROR is not None:
        raise RuntimeError(
            "Model dependencies are unavailable. "
            "Install joblib and sklearn to use the Model page."
        ) from JOBLIB_IMPORT_ERROR

    if not os.path.exists(MODEL_PATH):
        raise FileNotFoundError(f"Model file not found: {MODEL_PATH}")

    mtime = os.path.getmtime(MODEL_PATH)
    if _MODEL_CACHE_KEY not in _model_cache or _model_cache[_MODEL_CACHE_KEY].get('mtime') != mtime:
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
        _model_cache[_MODEL_CACHE_KEY] = data
        logger.info("Loaded ZAR/USD HuberRegressor pipeline from %s (mtime: %s)", MODEL_PATH, mtime)

    return _model_cache[_MODEL_CACHE_KEY]


def fetch_data_from_supabase():
    """Fetch recent rows from the Supabase 'data' table (with 5-min caching).

    NOTE: This is a local rehost. Task 3 moves the canonical implementation
    into `logic.data.storage` with hard timeouts. Once Task 3 lands, the
    package `__init__` prefers `logic.data.fetch_data_from_supabase`.
    """
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
