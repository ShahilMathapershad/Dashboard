"""Read the latest CachePayload for the active model version."""
from __future__ import annotations
import logging
from typing import cast

from logic.cache_contract import CACHE_CONTRACT_VERSION, CachePayload, CacheMetadata
from logic.model import MODEL_VERSION
from logic.supabase_client import get_supabase

logger = logging.getLogger(__name__)


def read_cached() -> CachePayload | None:
    """Return the cached payload for the current model version, or None.

    None is returned for: empty table, contract-version mismatch, Supabase
    failure. Callers must treat None as "show skeleton + trigger refresh".
    """
    sb = get_supabase()
    if sb is None:
        logger.warning("predictions_cache.read: Supabase unavailable")
        return None
    try:
        resp = sb.table("predictions").select("*").eq("model_version", MODEL_VERSION).limit(1).execute()
    except Exception as exc:
        logger.warning("predictions_cache.read: query failed: %s", exc)
        return None

    if not resp.data:
        logger.info("predictions_cache.read: cache miss (no row for model_version=%s)", MODEL_VERSION)
        return None

    row = resp.data[0]
    if row.get("cache_contract_version") != CACHE_CONTRACT_VERSION:
        logger.info(
            "predictions_cache.read: contract version mismatch row=%s expected=%s",
            row.get("cache_contract_version"), CACHE_CONTRACT_VERSION,
        )
        return None

    payload = cast(CachePayload, {
        "metadata": CacheMetadata(
            cache_contract_version=row["cache_contract_version"],
            model_version=row["model_version"],
            computed_at=row["computed_at"],
            data_through=row["data_through"],
            refresh_status=row["refresh_status"],
        ),
        "forecasts": row["forecasts"],
        "feature_contributions": row["feature_contributions"],
        "fit_history": row["fit_history"],
        "scenario_baseline": row["scenario_baseline"],
    })
    return payload
