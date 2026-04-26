"""Hydrate dashboard from predictions cache + fire opportunistic refresh.

These callbacks REPLACE the three-step trigger chain in app.py (the
fetch-trigger -> model-prediction-trigger -> scenario-trigger sequence).
For Wave 2 we add them alongside the legacy chain; Wave 4 deletes the
legacy chain in a single cutover commit.

Stores written by hydrate (read by tab-render callbacks):
  - fetched-data            derived from payload (legacy id, kept for compat)
  - model-prediction-data   payload.forecasts + feature_contributions
  - scenario-baseline-data  payload.scenario_baseline
  - cache-metadata-store    NEW: holds metadata for staleness UI banner
  - cache-status-store      NEW: 'hit' | 'miss' | 'refreshing' | 'stale'
"""
from __future__ import annotations
import logging

import dash
from dash import Input, Output, State, callback

from logic.predictions_cache import read_cached, refresh_async, is_stale

logger = logging.getLogger(__name__)


def register(app: dash.Dash) -> None:
    """Wire cache callbacks into the given Dash app."""

    @callback(
        Output("cache-metadata-store", "data"),
        Output("cache-status-store",   "data", allow_duplicate=True),
        Input("_pages_location", "pathname"),
        Input("user-session", "data"),
        prevent_initial_call="initial_duplicate",
    )
    def hydrate_from_cache(pathname, session_data):
        """On dashboard nav, load CachePayload metadata and surface status.

        We do NOT overwrite the legacy stores yet (fetched-data,
        model-prediction-data, scenario-baseline-data) — the legacy chain
        still owns those during Wave 2. The cutover in Wave 4 will swap
        the writers.
        """
        if pathname != "/dashboard":
            return dash.no_update, dash.no_update

        payload = read_cached()
        if payload is None:
            logger.info("cache.hydrate.miss")
            return None, "miss"

        logger.info("cache.hydrate.hit data_through=%s", payload["metadata"]["data_through"])
        return payload["metadata"], "hit"

    @callback(
        Output("cache-status-store",  "data", allow_duplicate=True),
        Output("cache-metadata-store", "data", allow_duplicate=True),
        Input("cache-status-store", "data"),
        State("cache-metadata-store", "data"),
        prevent_initial_call=True,
        background=True,
        running=[(Output("cache-refresh-spinner", "children"), "Refreshing data...", "")],
    )
    def opportunistic_refresh(status, metadata):
        """If cache is stale or missing, refresh in background — non-blocking."""
        if status not in ("hit", "miss"):
            return dash.no_update, dash.no_update

        if status == "hit" and not is_stale(metadata):
            return dash.no_update, dash.no_update

        result = refresh_async()
        if result["status"] != "success" or result["payload"] is None:
            logger.info(
                "cache.refresh.no_swap status=%s reason=%s",
                result["status"], result["reason"],
            )
            return ("stale", dash.no_update)

        new_meta = result["payload"]["metadata"]
        return ("hit", new_meta)
