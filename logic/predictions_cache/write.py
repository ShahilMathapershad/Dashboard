"""Persist a CachePayload via UPSERT on (model_version)."""
from __future__ import annotations
import logging

from logic.cache_contract import CachePayload
from logic.supabase_client import get_supabase

logger = logging.getLogger(__name__)


def write_payload(payload: CachePayload) -> bool:
    """UPSERT the payload. Returns True on success, False on failure."""
    sb = get_supabase()
    if sb is None:
        logger.warning("predictions_cache.write: Supabase unavailable")
        return False

    row = {
        "model_version": payload["metadata"]["model_version"],
        "cache_contract_version": payload["metadata"]["cache_contract_version"],
        "computed_at": payload["metadata"]["computed_at"],
        "data_through": payload["metadata"]["data_through"],
        "refresh_status": payload["metadata"]["refresh_status"],
        "forecasts": payload["forecasts"],
        "feature_contributions": payload["feature_contributions"],
        "fit_history": payload["fit_history"],
        "scenario_baseline": payload["scenario_baseline"],
    }
    try:
        sb.table("predictions").upsert(row, on_conflict="model_version").execute()
    except Exception as exc:
        logger.warning("predictions_cache.write: upsert failed: %s", exc)
        return False

    logger.info(
        "predictions_cache.write: stored payload (data_through=%s)",
        payload["metadata"]["data_through"],
    )
    return True
