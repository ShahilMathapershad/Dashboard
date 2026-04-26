"""Verify the package split preserves the legacy public surface."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

EXPECTED = [
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


def main() -> int:
    import logic.model as m
    missing = [name for name in EXPECTED if not hasattr(m, name)]
    if missing:
        print(f"FAIL: logic.model missing: {missing}")
        return 1

    pipeline = m.load_model()
    if pipeline is None:
        print("FAIL: load_model() returned None")
        return 1
    pipe = pipeline["pipeline"] if isinstance(pipeline, dict) else pipeline
    if not hasattr(pipe, "predict"):
        print("FAIL: load_model() returned object without .predict")
        return 1

    print(f"OK: logic.model package surface complete; pipeline={type(pipe).__name__}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
