"""Verify CachePayload roundtrips as JSON and has all required fields."""
import json
import sys
from datetime import datetime, timezone
from logic.cache_contract import (
    CACHE_CONTRACT_VERSION,
    CachePayload,
    CacheMetadata,
    HorizonForecast,
    FeatureContribution,
    FitHistoryPoint,
    ScenarioBaseline,
)

def _sample_payload() -> CachePayload:
    now = datetime.now(timezone.utc).isoformat()
    return CachePayload(
        metadata=CacheMetadata(
            cache_contract_version=CACHE_CONTRACT_VERSION,
            model_version="huber-v1-2026-03-29",
            computed_at=now,
            data_through="2026-03-31",
            refresh_status="success",
        ),
        forecasts=[
            HorizonForecast(horizon_months=1, forecast_zar_usd=18.55, forecast_date="2026-04-30"),
            HorizonForecast(horizon_months=3, forecast_zar_usd=18.71, forecast_date="2026-06-30"),
            HorizonForecast(horizon_months=6, forecast_zar_usd=19.02, forecast_date="2026-09-30"),
        ],
        feature_contributions=[
            FeatureContribution(feature="ZAR_USD_lag1", contribution=18.10, value=18.50),
            FeatureContribution(feature="VIX", contribution=0.08, value=15.2),
        ],
        fit_history=[
            FitHistoryPoint(date="2025-04-30", actual=18.30, predicted=18.27),
            FitHistoryPoint(date="2025-05-31", actual=18.42, predicted=18.39),
        ],
        scenario_baseline=ScenarioBaseline(
            feature_values={"VIX": 15.2, "EPU_USA": 120.5},
            baseline_forecast_1m=18.55,
            baseline_date="2026-04-30",
        ),
    )

def main() -> int:
    payload = _sample_payload()
    try:
        encoded = json.dumps(payload)
        decoded = json.loads(encoded)
    except (TypeError, ValueError) as e:
        print(f"FAIL: payload not JSON-roundtrippable: {e}")
        return 1

    required_top = {"metadata", "forecasts", "feature_contributions", "fit_history", "scenario_baseline"}
    if set(decoded.keys()) != required_top:
        print(f"FAIL: top-level keys {set(decoded.keys())} != {required_top}")
        return 1

    required_meta = {"cache_contract_version", "model_version", "computed_at", "data_through", "refresh_status"}
    if set(decoded["metadata"].keys()) != required_meta:
        print(f"FAIL: metadata keys {set(decoded['metadata'].keys())} != {required_meta}")
        return 1

    print(f"OK: CachePayload roundtripped, contract version={CACHE_CONTRACT_VERSION}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
