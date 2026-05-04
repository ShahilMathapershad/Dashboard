# logic/explainable_registry.py
"""Single source of truth for ✦-explainable values and AI-citable IDs.

Both the hover ✦ deep-link feature and inline-citation chips read from
this registry. See docs/superpowers/specs/2026-05-03-explainable-numbers-
and-citations-design.md for the design.
"""

from __future__ import annotations
from typing import Any

# Each entry maps an ID to a metadata dict with:
#   label           — human-readable name (used in starter Q + chip tooltip)
#   tab             — "data" | "model" | "scenario"
#   sub_tab         — optional model sub-tab ("predictions" | "specifications")
#   dom_target      — CSS selector the ✦ attaches next to / citation jumps to
#                     (None for Plotly-rendered cells; uses navigate_actions only)
#   starter_question — template with {value} placeholder
#   value_source    — dotted path into a dcc.Store for live value lookup
#                     ("none" if value is static or comes from chart)
#   navigate_actions — list of agent-action-store actions for citation click

EXPLAINABLE_VALUES: dict[str, dict[str, Any]] = {
    # ── Model tab — Forecast point estimates ──
    "forecast_1m": {
        "label": "1-month forecast",
        "tab": "model",
        "sub_tab": "predictions",
        "dom_target": "#ev-row-1m .ev-cell-spot",
        "starter_question": "Explain the 1-month forecast ({value}). What's driving it?",
        "value_source": "model-prediction-data.raw_result.forecasts.1m.point_estimate",
        "navigate_actions": [
            {"type": "navigate_tab", "tab": "model"},
            {"type": "highlight_model", "sub_tab": "predictions", "targets": ["forecast_1m"]},
        ],
    },
    "forecast_3m": {
        "label": "3-month forecast",
        "tab": "model",
        "sub_tab": "predictions",
        "dom_target": "#ev-row-3m .ev-cell-spot",
        "starter_question": "Explain the 3-month forecast ({value}). What's driving it?",
        "value_source": "model-prediction-data.raw_result.forecasts.3m.point_estimate",
        "navigate_actions": [
            {"type": "navigate_tab", "tab": "model"},
            {"type": "highlight_model", "sub_tab": "predictions", "targets": ["forecast_3m"]},
        ],
    },
    "forecast_6m": {
        "label": "6-month forecast",
        "tab": "model",
        "sub_tab": "predictions",
        "dom_target": "#ev-row-6m .ev-cell-spot",
        "starter_question": "Explain the 6-month forecast ({value}). What's driving it?",
        "value_source": "model-prediction-data.raw_result.forecasts.6m.point_estimate",
        "navigate_actions": [
            {"type": "navigate_tab", "tab": "model"},
            {"type": "highlight_model", "sub_tab": "predictions", "targets": ["forecast_6m"]},
        ],
    },
    "fair_value_now": {
        "label": "Fair value (current)",
        "tab": "model",
        "sub_tab": "predictions",
        "dom_target": "#ev-row-current .ev-cell-fv",
        "starter_question": "Explain the current fair value of {value}. What does it mean and how is it computed?",
        "value_source": "model-prediction-data.raw_result.fair_value",
        "navigate_actions": [
            {"type": "navigate_tab", "tab": "model"},
            {"type": "highlight_model", "sub_tab": "predictions", "targets": ["fair_value_now"]},
        ],
    },

    # ── Model tab — Feature contributions (11 features) ──
    # Generated programmatically below to avoid duplication.

    # ── Model tab — Performance metrics ──
    "metric_mae": {
        "label": "MAE (Mean Absolute Error)",
        "tab": "model",
        "sub_tab": "specifications",
        "dom_target": "#metric-mae",
        "starter_question": "What does the MAE of {value} tell us about this forecasting model?",
        "value_source": "model-prediction-data.raw_result.metrics.mae",
        "navigate_actions": [
            {"type": "navigate_tab", "tab": "model"},
            {"type": "highlight_model", "sub_tab": "specifications", "targets": ["metric_mae"]},
        ],
    },
    "metric_rmse": {
        "label": "RMSE",
        "tab": "model",
        "sub_tab": "specifications",
        "dom_target": "#metric-rmse",
        "starter_question": "Explain the RMSE of {value} and how it differs from MAE here.",
        "value_source": "model-prediction-data.raw_result.metrics.rmse",
        "navigate_actions": [
            {"type": "navigate_tab", "tab": "model"},
            {"type": "highlight_model", "sub_tab": "specifications", "targets": ["metric_rmse"]},
        ],
    },
    "metric_r2": {
        "label": "R² (out-of-sample)",
        "tab": "model",
        "sub_tab": "specifications",
        "dom_target": "#metric-r2",
        "starter_question": "Is an R² of {value} good for an FX model? Why is FX hard to forecast?",
        "value_source": "model-prediction-data.raw_result.metrics.r2",
        "navigate_actions": [
            {"type": "navigate_tab", "tab": "model"},
            {"type": "highlight_model", "sub_tab": "specifications", "targets": ["metric_r2"]},
        ],
    },
    "metric_mape": {
        "label": "MAPE",
        "tab": "model",
        "sub_tab": "specifications",
        "dom_target": "#metric-mape",
        "starter_question": "Explain what a MAPE of {value} means in practice for forecast accuracy.",
        "value_source": "model-prediction-data.raw_result.metrics.mape",
        "navigate_actions": [
            {"type": "navigate_tab", "tab": "model"},
            {"type": "highlight_model", "sub_tab": "specifications", "targets": ["metric_mape"]},
        ],
    },
    "metric_theils_u": {
        "label": "Theil's U",
        "tab": "model",
        "sub_tab": "specifications",
        "dom_target": "#metric-theils-u",
        "starter_question": "Theil's U is {value}. Does this model beat a random walk?",
        "value_source": "model-prediction-data.raw_result.metrics.theils_u",
        "navigate_actions": [
            {"type": "navigate_tab", "tab": "model"},
            {"type": "highlight_model", "sub_tab": "specifications", "targets": ["metric_theils_u"]},
        ],
    },
    "metric_directional_accuracy": {
        "label": "Directional Accuracy",
        "tab": "model",
        "sub_tab": "specifications",
        "dom_target": "#metric-directional-accuracy",
        "starter_question": "Directional accuracy is {value}. How does that compare to random guessing and why does it matter?",
        "value_source": "model-prediction-data.raw_result.metrics.directional_accuracy",
        "navigate_actions": [
            {"type": "navigate_tab", "tab": "model"},
            {"type": "highlight_model", "sub_tab": "specifications", "targets": ["metric_directional_accuracy"]},
        ],
    },

    # ── Scenario tab ──
    "scenario_base_value": {
        "label": "Base forecast",
        "tab": "scenario",
        "dom_target": "#scenario-base-value",
        "starter_question": "Explain the base forecast of {value} and how the scenario tab works.",
        "value_source": "scenario-baseline-data.next_month_predicted_level",
        "navigate_actions": [{"type": "navigate_tab", "tab": "scenario"}],
    },
    "scenario_result_value": {
        "label": "Scenario forecast",
        "tab": "scenario",
        "dom_target": "#scenario-result-value",
        "starter_question": "The scenario forecast is {value}. What does it imply given the current slider settings?",
        "value_source": "none",
        "navigate_actions": [{"type": "navigate_tab", "tab": "scenario"}],
    },
    "scenario_delta_value": {
        "label": "Scenario delta vs base",
        "tab": "scenario",
        "dom_target": "#scenario-delta-value",
        "starter_question": "The scenario differs from the base forecast by {value}. Is this a meaningful move?",
        "value_source": "none",
        "navigate_actions": [{"type": "navigate_tab", "tab": "scenario"}],
    },
}


# ── 11 feature contribution entries (generated to avoid copy-paste) ──

_FEATURE_LIST = [
    ("ZAR_USD_lag1", "ZAR/USD lag-1 (random-walk anchor)"),
    ("ZAR_USD_logret1", "ZAR/USD 1-month log return"),
    ("ZAR_USD_change3", "ZAR/USD 3-month change"),
    ("ZAR_USD_zscore12", "ZAR/USD 12-month z-score"),
    ("VIX", "VIX (current level)"),
    ("VIX_change1", "VIX 1-month change"),
    ("VIX_zscore12", "VIX 12-month z-score"),
    ("EPU_USA", "US Economic Policy Uncertainty"),
    ("WUIZAF_SA", "SA World Uncertainty Index"),
    ("bond_spread_change1", "Bond spread 1-month change"),
    ("GOLD_PRICE_logret1", "Gold price 1-month log return"),
]

for _feat_id, _feat_label in _FEATURE_LIST:
    EXPLAINABLE_VALUES[f"contrib_{_feat_id}"] = {
        "label": f"Contribution from {_feat_label}",
        "tab": "model",
        "sub_tab": "predictions",
        "dom_target": f"#contrib-row-{_feat_id}",
        "starter_question": f"The {_feat_label} feature contributes {{value}} to the forecast. What does that signal?",
        "value_source": "none",  # Bar values are derived; the model already has them in context.
        "navigate_actions": [
            {"type": "navigate_tab", "tab": "model"},
            {"type": "highlight_model", "sub_tab": "predictions", "targets": [f"contrib_{_feat_id}"]},
        ],
    }


# ── Helper functions ──

def get_entry(eid: str) -> dict[str, Any] | None:
    """Return the registry entry for an ID, or None if not found."""
    return EXPLAINABLE_VALUES.get(eid)


def expand_dynamic_entries(corr_matrix_vars: list[str]) -> dict[str, dict[str, Any]]:
    """Generate heatmap-cell entries for the upper triangle of the correlation matrix.

    Returns a dict like {'corr_VIX_ZAR_USD': {...}}. IDs are unordered, i.e. both
    ``corr_VIX_ZAR_USD`` and ``corr_ZAR_USD_VIX`` are produced and resolve to the
    same cell so the model isn't penalised for ordering.
    """
    out: dict[str, dict[str, Any]] = {}
    for i, a in enumerate(corr_matrix_vars):
        for b in corr_matrix_vars[i + 1:]:
            entry = {
                "label": f"Correlation r({a}, {b})",
                "tab": "data",
                "dom_target": None,  # Plotly cell — clickData handler instead
                "starter_question": f"The correlation between {a} and {b} is {{value}}. Is that strong, and what's the economic intuition?",
                "value_source": "none",
                "navigate_actions": [
                    {"type": "navigate_tab", "tab": "data"},
                    {"type": "set_plot_mode", "mode": "compare"},
                    {"type": "set_compare_variables", "variables": [a, b]},
                ],
            }
            out[f"corr_{a}_{b}"] = entry
            out[f"corr_{b}_{a}"] = entry  # alias for opposite ordering
    return out


def serialize_for_store(corr_matrix_vars: list[str] | None = None) -> dict[str, dict[str, Any]]:
    """Build the full registry (static + dynamic) for shipping to the browser as JSON."""
    full = dict(EXPLAINABLE_VALUES)
    if corr_matrix_vars:
        full.update(expand_dynamic_entries(corr_matrix_vars))
    return full


def build_system_prompt_snippet(corr_matrix_vars: list[str] | None = None) -> str:
    """Generate the citation-markup section for CHAT_SYSTEM_PROMPT/AGENT_SYSTEM_PROMPT.

    Lists every citable ID with a brief label so Gemini knows what's available.
    Heatmap entries are folded into a single example line to keep token cost down.
    """
    lines = [
        "== CITATION MARKUP ==",
        "When you reference any of these values in your reply, wrap them in [[id|value]]:",
    ]
    for eid, entry in EXPLAINABLE_VALUES.items():
        tab = entry.get("sub_tab") or entry["tab"]
        lines.append(f"- {eid} — {entry['label']} ({tab})")
    if corr_matrix_vars:
        sample = corr_matrix_vars[:2]
        if len(sample) == 2:
            lines.append(
                f"- corr_<A>_<B> — correlation r between any two data variables, e.g. corr_{sample[0]}_{sample[1]}"
            )
    lines.extend([
        'Example: "VIX is at [[VIX_latest|18.4]], correlated r=[[corr_VIX_ZAR_USD|0.42]] with the Rand."',
        "Only cite values from the list. For other numbers, write them plainly.",
    ])
    return "\n".join(lines)
