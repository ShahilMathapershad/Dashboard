"""Scenario / what-if analysis.

Owns:
  - `get_scenario_baseline()` — current predictor values + historical ranges
    for slider config + base prediction (legacy public API).
  - `scenario_predict()` — predict under modified raw predictors (legacy).
  - `find_scenario_for_target()` — reverse search: find slider settings
    that hit a target ZAR/USD level (legacy).
  - `predict_scenario()` and `compute_scenario_baseline()` — new-API
    aliases Task 5 expects.
"""
import logging

from logic.model.loading import (
    _persistent_cache,
    fetch_data_from_supabase,
    load_model,
)
from logic.model.features import (
    SCENARIO_RAW_PREDICTORS,
    engineer_features,
)

logger = logging.getLogger("ModelPredictor")


def get_scenario_baseline():
    """
    Return the baseline data needed for scenario analysis:
    - Current raw predictor values and historical ranges for sliders
    - Base prediction (current values)
    """
    import pandas as pd

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


# ── New-API aliases Task 5 expects ──

def predict_scenario(scenario_values):
    """New-API alias for legacy `scenario_predict`. See `scenario_predict`
    for the full docstring."""
    return scenario_predict(scenario_values)


def compute_scenario_baseline(*args, **kwargs):
    """New-API alias for legacy `get_scenario_baseline`.

    Accepts an optional engineered-features DataFrame for forward-compat
    with Task 5's signature (`compute_scenario_baseline(features)`), but
    the current implementation always pulls fresh from Supabase.
    """
    return get_scenario_baseline()
