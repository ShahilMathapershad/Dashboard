"""Unified hydrate from predictions cache + opportunistic refresh.

Wave 4 cutover: this REPLACES the legacy three-step trigger chain
(global_prerender_trigger -> chain_model_prediction -> chain_scenario_baseline)
that lived in app.py. On dashboard nav, the unified hydrate populates ALL
stores the dashboard tabs read from in one background pass.

Stores written by hydrate:
  - fetched-data                       df.to_dict('records'), Date as ISO string
  - fetched-data-status                {'text': ..., 'color': ...}
  - predictor-dropdown-options-store   [{'label', 'value'}]
  - selected-predictors                ['ZAR_USD', <first other>]
  - model-prediction-data              {'raw_result': predict_next_month()}
  - scenario-baseline-data             get_scenario_baseline()
  - cache-metadata-store               CachePayload['metadata']
  - cache-status-store                 'hit' | 'miss' | 'refreshing' | 'stale'
"""
from __future__ import annotations
import logging

import dash
from dash import Input, Output, State, callback

from logic.predictions_cache import read_cached, refresh_async, is_stale
from logic.model import (
    predict_next_month,
    fetch_data_from_supabase,
    get_scenario_baseline,
)
from logic.data_fetcher import SERIES_CONFIG

logger = logging.getLogger(__name__)

_NO_UPDATES_8 = tuple(dash.no_update for _ in range(8))


def register(app: dash.Dash) -> None:
    """Wire cache callbacks into the given Dash app."""

    @callback(
        Output("fetched-data",                     "data", allow_duplicate=True),
        Output("fetched-data-status",              "data", allow_duplicate=True),
        Output("predictor-dropdown-options-store", "data", allow_duplicate=True),
        Output("selected-predictors",              "data", allow_duplicate=True),
        Output("model-prediction-data",            "data", allow_duplicate=True),
        Output("scenario-baseline-data",           "data", allow_duplicate=True),
        Output("cache-metadata-store",             "data", allow_duplicate=True),
        Output("cache-status-store",               "data", allow_duplicate=True),
        Input("_pages_location", "pathname"),
        Input("user-session", "data"),
        State("fetched-data", "data"),
        prevent_initial_call="initial_duplicate",
        background=True,
    )
    def hydrate_dashboard(pathname, session_data, existing_fetched):
        """Single-shot hydrate of every dashboard store on /dashboard nav."""
        if pathname != "/dashboard":
            return _NO_UPDATES_8
        if existing_fetched:
            return _NO_UPDATES_8

        import pandas as pd

        payload = read_cached()
        cache_metadata = payload["metadata"] if payload else None
        cache_status = "hit" if payload else "miss"

        try:
            df = fetch_data_from_supabase()
        except Exception:
            logger.exception("hydrate.fetch_data_from_supabase failed")
            return _NO_UPDATES_8

        if df is None or df.empty:
            logger.warning("hydrate: empty df from supabase")
            return _NO_UPDATES_8

        df_all = df.reset_index()
        df_all["Date"] = pd.to_datetime(df_all["Date"]).dt.strftime("%Y-%m-%d")
        numeric_cols = df_all.select_dtypes(include="number").columns
        df_all[numeric_cols] = df_all[numeric_cols].round(6)

        all_vars = [c for c in df_all.columns if c != "Date"]
        if "ZAR_USD" in all_vars:
            all_vars.remove("ZAR_USD")
            all_vars.insert(0, "ZAR_USD")

        dropdown_options = [
            {
                "label": (
                    "ZAR/USD Exchange Rate"
                    if p == "ZAR_USD"
                    else SERIES_CONFIG.get(p, {}).get("label", p)
                ),
                "value": p,
            }
            for p in all_vars
        ]
        default_predictors = (
            ["ZAR_USD"] + all_vars[1:2] if len(all_vars) >= 2 else all_vars[:1]
        )
        fetched = df_all.to_dict("records")
        fetched_status = {"text": "● Live (Supabase)", "color": "#10B981"}

        try:
            model_pred = {"raw_result": predict_next_month()}
        except Exception:
            logger.exception("hydrate.predict_next_month failed")
            model_pred = dash.no_update

        try:
            scenario_base = get_scenario_baseline()
        except Exception:
            logger.exception("hydrate.get_scenario_baseline failed")
            scenario_base = dash.no_update

        logger.info(
            "cache.hydrate.complete cache_status=%s rows=%d",
            cache_status, len(fetched),
        )
        return (
            fetched,
            fetched_status,
            dropdown_options,
            default_predictors,
            model_pred,
            scenario_base,
            cache_metadata,
            cache_status,
        )

    @callback(
        Output("prewarm-status-store", "data"),
        Input("get-started-button", "n_clicks"),
        prevent_initial_call=True,
        background=True,
    )
    def prewarm_on_get_started(n_clicks):
        """Pre-populate the dashboard diskcaches the moment the user clicks
        'Get Started' on the landing hero. By the time they finish filling the
        login form, fetch_data_from_supabase / predict_next_month /
        get_scenario_baseline are all hot — the post-login /dashboard hydrate
        becomes nearly instant.

        These functions are individually diskcached, so calling them here is
        a no-op on a warm cache and ~600-800ms total on a cold one. Any
        exception is swallowed: prewarm is best-effort, hydrate will retry.
        """
        if not n_clicks:
            return dash.no_update
        try:
            fetch_data_from_supabase()
        except Exception:
            logger.exception("prewarm.fetch_data_from_supabase failed")
        try:
            predict_next_month()
        except Exception:
            logger.exception("prewarm.predict_next_month failed")
        try:
            get_scenario_baseline()
        except Exception:
            logger.exception("prewarm.get_scenario_baseline failed")
        logger.info("cache.prewarm.complete")
        return "warm"

    @callback(
        Output("cache-status-store",   "data", allow_duplicate=True),
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
