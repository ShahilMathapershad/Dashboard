"""Compatibility shim: legacy callers import `from logic.model import X`.

`compute_full_predictions_payload` is added in Task 5 and re-exported here.
"""
from logic.model.loading import (
    load_model,
    JOBLIB_IMPORT_ERROR,
    MODEL_PATH,
    TRAIN_ONLY_MODEL_PATH,
)
from logic.model.features import (
    engineer_features,
    get_friendly_feature_name,
    get_feature_category,
    get_coefficient_unit,
)
from logic.model.inference import (
    predict_one,
    predict_next_month,
    get_test_set_predictions,
)
from logic.model.forecasting import multi_horizon_forecast
from logic.model.scenario import (
    predict_scenario,
    scenario_predict,
    compute_scenario_baseline,
    get_scenario_baseline,
    find_scenario_for_target,
)
from logic.model.explain import compute_feature_contributions

# Re-export Supabase fetch (used by app.py warmup) — actually lives in logic.data
# but historically callers imported it from logic.model. Preserve that.
from logic.data import fetch_data_from_supabase

__all__ = [
    "load_model",
    "engineer_features",
    "predict_one",
    "predict_next_month",
    "multi_horizon_forecast",
    "predict_scenario",
    "scenario_predict",
    "compute_scenario_baseline",
    "get_scenario_baseline",
    "find_scenario_for_target",
    "get_test_set_predictions",
    "compute_feature_contributions",
    "fetch_data_from_supabase",
    "get_friendly_feature_name",
    "get_feature_category",
    "get_coefficient_unit",
]
