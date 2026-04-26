"""Type contract for the predictions cache.

This module defines the JSON shape that:
  • logic.model.compute_full_predictions_payload() emits
  • logic.predictions_cache.write() persists to Supabase
  • logic.predictions_cache.read() returns
  • pages/dashboard_tabs/* read from dcc.Store hydration

Bumping CACHE_CONTRACT_VERSION forces all clients to treat existing
cache rows as a miss, triggering a fresh refresh under the new schema.
"""
from __future__ import annotations
from typing import TypedDict, Literal

CACHE_CONTRACT_VERSION = 1


class HorizonForecast(TypedDict):
    horizon_months: Literal[1, 3, 6]
    forecast_zar_usd: float
    forecast_date: str  # ISO date "YYYY-MM-DD"


class FeatureContribution(TypedDict):
    feature: str
    contribution: float
    value: float


class FitHistoryPoint(TypedDict):
    date: str        # ISO date
    actual: float
    predicted: float


class ScenarioBaseline(TypedDict):
    feature_values: dict[str, float]   # name → current value
    baseline_forecast_1m: float
    baseline_date: str


class CacheMetadata(TypedDict):
    cache_contract_version: int
    model_version: str               # e.g. "huber-v1-2026-03-29"
    computed_at: str                 # ISO datetime UTC
    data_through: str                # ISO date — newest data row included
    refresh_status: Literal["success", "stale", "bootstrap"]


class CachePayload(TypedDict):
    metadata: CacheMetadata
    forecasts: list[HorizonForecast]
    feature_contributions: list[FeatureContribution]
    fit_history: list[FitHistoryPoint]
    scenario_baseline: ScenarioBaseline


class RefreshResult(TypedDict):
    status: Literal["success", "failed", "skipped"]
    reason: str | None       # e.g. "lock_held", "fred_timeout"
    payload: CachePayload | None
    elapsed_ms: int
