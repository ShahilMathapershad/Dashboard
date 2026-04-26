"""Build a real payload from current Supabase data and verify shape."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from logic.cache_contract import CACHE_CONTRACT_VERSION
from logic.data import fetch_data_from_supabase
from logic.model import compute_full_predictions_payload, MODEL_VERSION


def main() -> int:
    df = fetch_data_from_supabase()
    if df is None or df.empty:
        print("FAIL: Supabase returned no data")
        return 1
    print(f"  fetched {len(df)} rows, latest={df.index[-1]}")

    payload = compute_full_predictions_payload(df)

    if payload["metadata"]["cache_contract_version"] != CACHE_CONTRACT_VERSION:
        print(f"FAIL: contract version mismatch")
        return 1
    if payload["metadata"]["model_version"] != MODEL_VERSION:
        print(f"FAIL: model version mismatch")
        return 1
    if len(payload["forecasts"]) != 3:
        print(f"FAIL: expected 3 horizon forecasts, got {len(payload['forecasts'])}")
        return 1
    if not payload["feature_contributions"]:
        print(f"FAIL: feature_contributions empty")
        return 1
    if len(payload["fit_history"]) > 60:
        print(f"FAIL: fit_history too long: {len(payload['fit_history'])}")
        return 1

    try:
        json.dumps(payload)
    except (TypeError, ValueError) as e:
        print(f"FAIL: payload not JSON-serializable: {e}")
        return 1

    print(
        f"OK: payload built, forecasts={len(payload['forecasts'])}, "
        f"contributions={len(payload['feature_contributions'])}, "
        f"fit_history={len(payload['fit_history'])}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
