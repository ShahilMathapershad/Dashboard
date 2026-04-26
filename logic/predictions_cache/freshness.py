"""Decide whether the cache is stale enough to warrant a refresh."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone

from logic.cache_contract import CacheMetadata

STALE_AFTER = timedelta(hours=24)


def is_stale(metadata: CacheMetadata | None) -> bool:
    """True if cache is missing or older than STALE_AFTER."""
    if metadata is None:
        return True
    try:
        computed_at = datetime.fromisoformat(metadata["computed_at"])
        if computed_at.tzinfo is None:
            computed_at = computed_at.replace(tzinfo=timezone.utc)
    except ValueError:
        return True
    return datetime.now(timezone.utc) - computed_at > STALE_AFTER
