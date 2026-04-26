"""Verify write_payload() → read_cached() roundtrip."""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from logic.cache_contract import (
    CACHE_CONTRACT_VERSION, CachePayload, CacheMetadata,
    HorizonForecast, FeatureContribution, FitHistoryPoint, ScenarioBaseline,
)
from logic.predictions_cache import write_payload, read_cached


def main() -> int:
    now = datetime.now(timezone.utc).isoformat()
    test_version = "verify-roundtrip-temp"
    payload = CachePayload(
        metadata=CacheMetadata(
            cache_contract_version=CACHE_CONTRACT_VERSION,
            model_version=test_version,
            computed_at=now,
            data_through="2026-03-31",
            refresh_status="success",
        ),
        forecasts=[HorizonForecast(horizon_months=1, forecast_zar_usd=18.5, forecast_date="2026-04-30")],
        feature_contributions=[FeatureContribution(feature="VIX", contribution=0.1, value=15.0)],
        fit_history=[FitHistoryPoint(date="2026-03-31", actual=18.3, predicted=18.27)],
        scenario_baseline=ScenarioBaseline(
            feature_values={"VIX": 15.0}, baseline_forecast_1m=18.5, baseline_date="2026-04-30"
        ),
    )

    import logic.predictions_cache.read as read_mod
    original = read_mod.MODEL_VERSION
    read_mod.MODEL_VERSION = test_version
    try:
        if not write_payload(payload):
            print("FAIL: write_payload returned False")
            return 1
        echo = read_cached()
        if echo is None:
            print("FAIL: read_cached returned None after write")
            return 1
        if echo["metadata"]["model_version"] != test_version:
            print("FAIL: model_version mismatch")
            return 1
        if echo["forecasts"][0]["forecast_zar_usd"] != 18.5:
            print("FAIL: forecast value mismatch")
            return 1
    finally:
        read_mod.MODEL_VERSION = original
        from logic.supabase_client import get_supabase
        sb = get_supabase()
        if sb is not None:
            try:
                sb.table("predictions").delete().eq("model_version", test_version).execute()
            except Exception:
                pass

    print("OK: write -> read roundtrip preserved payload")
    return 0


if __name__ == "__main__":
    sys.exit(main())
