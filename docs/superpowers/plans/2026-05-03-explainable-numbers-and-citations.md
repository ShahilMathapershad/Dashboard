# Explainable Numbers + Inline Citations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add ✦ hover-to-explain icons next to high-value dashboard numbers (preloads chat input with a starter question), plus clickable inline citation chips in AI replies that navigate to the cited value and flash a highlight.

**Architecture:** A single shared registry (`logic/explainable_registry.py`) defines ~50 explainable values with their DOM targets, starter prompts, and citation `navigate_actions`. The browser holds a JSON copy of the registry; pattern-matching clientside callbacks handle both ✦ clicks (open chat + preload input) and citation chip clicks (write to existing `agent-action-store` for navigation + highlight). System prompt is augmented with a `[[id|value]]` markup catalog so Gemini emits structured citations in replies; `handle_chat_send` post-processes that markup into Dash chip components.

**Tech Stack:** Dash, Plotly, Gemini 2.5 Flash via `google.genai`, vanilla JS in clientside callbacks. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-05-03-explainable-numbers-and-citations-design.md`

**Testing approach:** This codebase has no test framework. Per the spec, verification is manual. Each task ends with concrete verification steps to run in a browser against `python app.py`.

**Plotly-rendered values:** Correlation heatmap cells and scenario waterfall bars are inside Plotly graphs (no stable HTML siblings). For these, the ✦ affordance is replaced by the chart's natural cell/bar click — handled via Plotly `clickData` callbacks. This is a documented v1 deviation from hover-only ✦; citation chips targeting these values still work via `navigate_actions`.

**v1 scope trim:** Per-series "latest value" labels, compare-mode `r` annotations, and the scenario summary table rows are dropped from v1 — they're either not stable HTML elements (latest-value, `r`) or already accessible via the scenario cards/waterfall (summary rows duplicate them). Citations targeting heatmap entries can still reach them via `navigate_actions`.

---

## File Structure

**New files:**
- `logic/explainable_registry.py` — single source of truth for explainable values

**Modified files:**
- `app.py` — global store, registry-populating callback, system-prompt augmentation, citation post-processor in `handle_chat_send`, ✦/citation clientside callbacks
- `pages/dashboard.py` — inject `.explain-trigger` siblings + `.explainable-parent` parent classes around forecast cells, contribution rows, `_info_pill` cards, scenario cards, summary table rows. Add Plotly clickData callbacks for heatmap and waterfall.
- `assets/style.css` — `.explain-trigger`, `.explainable-parent`, `.chat-citation-chip`, `.chat-citation-arrow`, `.explain-onboarding-tooltip` rules

---

## Task 1: Create the registry module

**Files:**
- Create: `logic/explainable_registry.py`

- [ ] **Step 1: Create the module skeleton with static entries**

```python
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
```

- [ ] **Step 2: Manually verify the module imports cleanly and produces sensible output**

Run:
```bash
python -c "from logic.explainable_registry import EXPLAINABLE_VALUES, expand_dynamic_entries, build_system_prompt_snippet; print(f'static entries: {len(EXPLAINABLE_VALUES)}'); print(f'dynamic for 4 vars: {len(expand_dynamic_entries([\"VIX\",\"ZAR_USD\",\"EPU_USA\",\"GOLD_PRICE\"]))}'); print('---SNIPPET---'); print(build_system_prompt_snippet([\"VIX\",\"ZAR_USD\"])[:600])"
```

Expected: shows ~25 static entries, 12 dynamic entries (6 unordered pairs × 2 alias orderings), and the first 600 chars of the system prompt snippet listing citable IDs.

- [ ] **Step 3: Commit**

```bash
git add logic/explainable_registry.py
git commit -m "add explainable values registry for AI chat features

Defines the EXPLAINABLE_VALUES dict mapping IDs to DOM targets, starter
questions, value sources, and navigate_actions. Helpers expand_dynamic_
entries() and build_system_prompt_snippet() generate the dynamic
heatmap cells and the citation-markup catalog for the chat system prompt.

Used by:
- ✦ deep-link triggers (rendered next to dashboard values)
- inline citation chips in AI replies"
```

---

## Task 2: Wire registry into app.py (global store + system prompt)

**Files:**
- Modify: `app.py` (around line 147 — global stores; around line 1374 — CHAT_SYSTEM_PROMPT)

- [ ] **Step 1: Add the registry store to global stores**

Find the global `dcc.Store` block in `app.py` (search for `dcc.Store(id='chat-history'`). Add this Store immediately after it:

```python
    dcc.Store(id='explainable-registry-store', storage_type='memory'),
```

- [ ] **Step 2: Import the registry helpers at the top of app.py**

Find the existing imports around the top of `app.py`. Add:

```python
from logic.explainable_registry import (
    EXPLAINABLE_VALUES,
    serialize_for_store,
    build_system_prompt_snippet,
)
```

- [ ] **Step 3: Add a callback that populates the registry store on dashboard load**

Find a sensible location among the existing global callbacks (after the chat panel toggle callback is fine). Add:

```python
@callback(
    Output('explainable-registry-store', 'data'),
    Input('fetched-data', 'data'),  # Fires once data is loaded; varies by tab
    prevent_initial_call=False,
)
def populate_explainable_registry(fetched_data):
    """Build the per-session registry (static entries + heatmap cells for the
    columns currently in the data store) and ship to the browser.

    `fetched-data` is a list of records (df.to_dict('records')), see
    pages/dashboard.py:877. We derive column names from the first record's keys.
    """
    corr_vars = []
    if fetched_data and isinstance(fetched_data, list) and fetched_data:
        corr_vars = [k for k in fetched_data[0].keys() if k != 'Date']
    return serialize_for_store(corr_vars)
```

Fallback behaviour: if `fetched-data` is empty or in an unexpected shape, only static entries ship and citations targeting heatmap cells gracefully degrade to plain text.

- [ ] **Step 4: Augment CHAT_SYSTEM_PROMPT and AGENT_SYSTEM_PROMPT with the citation snippet**

Find `CHAT_SYSTEM_PROMPT = (` (around line 1374). Below the existing definition, append:

```python
# Build once at import time. Heatmap entries are added per-session by the
# populate callback (system prompt is static, so we use a small placeholder).
_CITATION_SNIPPET = "\n\n" + build_system_prompt_snippet(
    corr_matrix_vars=["VIX", "ZAR_USD"],  # Placeholder — model just needs the pattern.
)

CHAT_SYSTEM_PROMPT = CHAT_SYSTEM_PROMPT + _CITATION_SNIPPET
```

Find `AGENT_SYSTEM_PROMPT = (` (search for it). Apply the same append:

```python
AGENT_SYSTEM_PROMPT = AGENT_SYSTEM_PROMPT + _CITATION_SNIPPET
```

- [ ] **Step 5: Manually verify the registry ships to the browser and the system prompt contains citation markup**

Run `python app.py`, log in, navigate to `/dashboard`. Open browser dev tools console, run:
```js
JSON.parse(document.querySelector('script[id="_dash-config"]')?.textContent || '{}');
// Then check Application → Local Storage / Session Storage / Memory for store contents,
// or simpler: temporarily add `print(CHAT_SYSTEM_PROMPT[-1500:])` after the augmentation
// in app.py and check stdout shows the citation section.
```

Easier verification path: in the chat, ask "What numbers can you cite in your replies?" — the model should reference `forecast_1m`, `metric_mae`, etc. from the registry catalog.

- [ ] **Step 6: Commit**

```bash
git add app.py
git commit -m "wire explainable registry into app: store + system prompt

Adds explainable-registry-store global Store, callback that populates
it (with heatmap entries derived from currently-fetched data), and
appends the citation-markup catalog to CHAT_SYSTEM_PROMPT and
AGENT_SYSTEM_PROMPT so Gemini knows the [[id|value]] syntax and the
list of citable IDs."
```

---

## Task 3: Citation post-processor + chip rendering in handle_chat_send

**Files:**
- Modify: `app.py` — add a helper near the top of the chat section, then use it in `handle_chat_send` (around line 1626 where AI text becomes a typewriter element)

- [ ] **Step 1: Add the citation parser helper**

Add this function in `app.py` right above `def _parse_agent_response` (around line 1413):

```python
import re

CITATION_PATTERN = re.compile(r'\[\[([a-zA-Z0-9_]+)\|([^\]]+)\]\]')


def _build_citation_children(text: str, registry: dict, message_idx: int) -> tuple[list, bool]:
    """Parse [[id|value]] markup in text and return (Dash children list, has_citations).

    If text contains no citations, returns ([text], False) so the caller can keep
    using the typewriter animation. If citations exist, returns a list of
    alternating html.Span text blocks and citation chip components, plus True.

    `message_idx` is the position of this message in chat-history; combined with
    eid + occurrence_idx it forms a globally-unique pattern-matching index so
    chips from older messages don't collide with new ones.

    Unknown IDs gracefully degrade to plain text.
    """
    if not text:
        return [text or ''], False

    matches = list(CITATION_PATTERN.finditer(text))
    if not matches:
        return [text], False

    children = []
    cursor = 0
    occurrence_idx = 0

    for m in matches:
        eid, value = m.group(1), m.group(2)
        # Plain text before this match
        if m.start() > cursor:
            children.append(text[cursor:m.start()])

        entry = registry.get(eid) if registry else None
        if entry:
            children.append(html.Span(
                id={'type': 'citation-chip',
                    'index': f'{eid}::{message_idx}::{occurrence_idx}'},
                className='chat-citation-chip',
                title=entry.get('label', eid),
                n_clicks=0,
                children=[
                    html.Span(value, className='chat-citation-value'),
                    html.Span('↗', className='chat-citation-arrow'),
                ],
            ))
            occurrence_idx += 1
        else:
            # Unknown ID — render the value as plain text
            children.append(value)

        cursor = m.end()

    # Trailing text
    if cursor < len(text):
        children.append(text[cursor:])

    return children, True
```

- [ ] **Step 2: Use the helper in handle_chat_send**

Find the AI-text rendering at the end of `handle_chat_send` (around line 1630):

```python
    current_messages.append(
        html.Div(className='chat-message chat-message-ai', children=[
            html.Div('', className='chat-bubble chat-bubble-ai chat-typewriter',
                     **{'data-fulltext': ai_text})
        ])
    )
```

Replace it with:

```python
    # Build the same registry the browser uses (static + dynamic heatmap cells)
    # so correlation citations parse correctly. fetched_data is already a State
    # of this callback (see app.py:1447).
    _corr_vars = []
    if fetched_data and isinstance(fetched_data, list) and fetched_data:
        _corr_vars = [k for k in fetched_data[0].keys() if k != 'Date']
    chat_registry = serialize_for_store(_corr_vars)

    # message_idx is the position this message will occupy in chat-history once
    # appended — used for unique chip pattern-matching indexes across history.
    message_idx = len(current_messages)
    citation_children, has_citations = _build_citation_children(
        ai_text, chat_registry, message_idx,
    )
    if has_citations:
        # Skip typewriter for citation messages — chips are real Dash components,
        # not animatable text.
        ai_bubble = html.Div(citation_children, className='chat-bubble chat-bubble-ai')
    else:
        ai_bubble = html.Div('', className='chat-bubble chat-bubble-ai chat-typewriter',
                             **{'data-fulltext': ai_text})
    current_messages.append(
        html.Div(className='chat-message chat-message-ai', children=[ai_bubble])
    )
```

- [ ] **Step 3: Manually verify citations parse correctly**

Run `python app.py`, log in, open `/dashboard`. In the chat, ask:
> "What's the latest 6-month forecast and the model's R²?"

Expected: the AI reply contains chip-styled values (you'll see them as inline elements once Task 4 ships the CSS — for now, in dev tools, inspect a reply and confirm `<span class="chat-citation-chip">` appears in the DOM where the model cites known IDs).

If the model isn't citing yet, the system prompt may need stronger phrasing — adjust Task 2 Step 4 to be more emphatic about always using `[[id|value]]` for the listed IDs.

- [ ] **Step 4: Commit**

```bash
git add app.py
git commit -m "post-process [[id|value]] markup into citation chips

Parses the citation markup the chat model emits using the catalog
shipped via the system prompt. Recognised IDs become Dash html.Span
chips with pattern-matching IDs (so the next task can wire click
handling). Unknown IDs degrade gracefully to plain text. Messages
containing citations skip the typewriter animation."
```

---

## Task 4: Citation chip styles + click handler

**Files:**
- Modify: `assets/style.css` — add chip styling
- Modify: `app.py` — add the citation-chip click clientside callback

- [ ] **Step 1: Add CSS for citation chips**

Append to the bottom of `assets/style.css`:

```css
/* ─────────────────────────────────────────────────────────────────
   AI Chat — Inline Citation Chips
   ───────────────────────────────────────────────────────────────── */
.chat-citation-chip {
    display: inline-flex;
    align-items: center;
    gap: 3px;
    padding: 1px 8px;
    margin: 0 2px;
    border-radius: 999px;
    background: rgba(155, 110, 245, 0.12);
    border: 1px solid rgba(155, 110, 245, 0.35);
    color: var(--accent-purple, #9b6ef5);
    font-size: 0.875em;
    font-weight: 500;
    cursor: pointer;
    transition: background 0.15s, transform 0.1s, box-shadow 0.15s;
    user-select: none;
    line-height: 1.3;
    vertical-align: baseline;
}

.chat-citation-chip:hover {
    background: rgba(155, 110, 245, 0.22);
    box-shadow: 0 0 0 2px rgba(155, 110, 245, 0.18);
}

.chat-citation-chip:active {
    transform: translateY(1px);
}

.chat-citation-arrow {
    font-size: 0.85em;
    opacity: 0.6;
}

.chat-citation-chip:hover .chat-citation-arrow {
    opacity: 1;
}
```

- [ ] **Step 2: Add the citation-chip click clientside callback in app.py**

Add this block among the existing `clientside_callback(...)` calls (e.g. near the other chat clientside callbacks around line 770):

```python
# Citation chip click → write to agent-action-store, reusing the existing
# execute_agent_actions plumbing for tab navigation + highlight.
app.clientside_callback(
    """
    function(n_clicks_list, registry) {
        const ctx = window.dash_clientside.callback_context;
        if (!ctx.triggered || !ctx.triggered.length) {
            return window.dash_clientside.no_update;
        }
        const triggered = ctx.triggered[0];
        if (!triggered.value) return window.dash_clientside.no_update;

        // triggered.prop_id is like '{"index":"forecast_6m::3::0","type":"citation-chip"}.n_clicks'
        // (index is composite: eid::message_idx::occurrence_idx — split below recovers eid)
        let triggeredId;
        try {
            triggeredId = JSON.parse(triggered.prop_id.split('.')[0]);
        } catch (e) { return window.dash_clientside.no_update; }

        const eid = (triggeredId.index || '').split('::')[0];
        if (!eid || !registry) return window.dash_clientside.no_update;
        const entry = registry[eid];
        if (!entry || !entry.navigate_actions) return window.dash_clientside.no_update;

        return {actions: entry.navigate_actions, ts: Date.now()};
    }
    """,
    Output('agent-action-store', 'data', allow_duplicate=True),
    Input({'type': 'citation-chip', 'index': ALL}, 'n_clicks'),
    State('explainable-registry-store', 'data'),
    prevent_initial_call=True,
)
```

You'll also need to import `ALL` from `dash`:

```python
from dash import ALL  # add to existing dash imports
```

- [ ] **Step 3: Manually verify citation chips render and clicking navigates**

Run `python app.py`, log in, ask the AI a question that should produce a citation (e.g. "What's the 6-month forecast?"). Confirm:

1. The chip renders with the purple-pill styling.
2. Hover shows the chip elevation + tooltip (`title` attribute).
3. Clicking the chip switches to the Model tab (if not already there) and the relevant element flashes the existing `agent-highlight` outline.

If clicking doesn't navigate, check browser console for JS errors in the clientside callback.

- [ ] **Step 4: Commit**

```bash
git add assets/style.css app.py
git commit -m "citation chips: styling + click navigation

Inline citation chips inherit a purple-tinted pill style matching the
existing chat-action-chip visual language. Clicking a chip recovers
the explainable ID from its pattern-matching index, looks up the
registry's navigate_actions, and dispatches into agent-action-store —
which the existing execute_agent_actions callback already handles for
tab navigation + flash-highlight."
```

---

## Task 5: ✦ trigger styles + click handler

**Files:**
- Modify: `assets/style.css` — add ✦ icon and parent-hover styles
- Modify: `app.py` — add ✦ click clientside callback that opens chat panel and preloads input

- [ ] **Step 1: Add CSS for the ✦ trigger and its parent**

Append to `assets/style.css`:

```css
/* ─────────────────────────────────────────────────────────────────
   ✦ Explain trigger — hover-revealed icon next to dashboard values
   ───────────────────────────────────────────────────────────────── */
.explainable-parent {
    position: relative;
}

.explain-trigger {
    display: inline-block;
    margin-left: 6px;
    color: var(--accent-purple, #9b6ef5);
    font-size: 0.85em;
    cursor: pointer;
    opacity: 0;
    transition: opacity 0.15s, transform 0.1s;
    user-select: none;
    vertical-align: baseline;
}

.explainable-parent:hover .explain-trigger,
.explain-trigger:focus-visible {
    opacity: 0.7;
}

.explain-trigger:hover {
    opacity: 1;
    transform: scale(1.15);
}

@media (hover: none) {
    /* On touch devices the ✦ stays subtly visible since hover doesn't fire. */
    .explain-trigger { opacity: 0.45; }
}
```

- [ ] **Step 2: Add the ✦ click clientside callback in app.py**

```python
# ✦ trigger click → open chat panel, preload input with starter question.
app.clientside_callback(
    """
    function(n_clicks_list, registry, predData, fetchedData, scenBaseline, scenCurrent) {
        const ctx = window.dash_clientside.callback_context;
        if (!ctx.triggered || !ctx.triggered.length) {
            return [window.dash_clientside.no_update, window.dash_clientside.no_update];
        }
        const triggered = ctx.triggered[0];
        if (!triggered.value) {
            return [window.dash_clientside.no_update, window.dash_clientside.no_update];
        }

        let triggeredId;
        try {
            triggeredId = JSON.parse(triggered.prop_id.split('.')[0]);
        } catch (e) {
            return [window.dash_clientside.no_update, window.dash_clientside.no_update];
        }
        const eid = triggeredId.index;
        if (!eid || !registry) {
            return [window.dash_clientside.no_update, window.dash_clientside.no_update];
        }
        const entry = registry[eid];
        if (!entry) {
            return [window.dash_clientside.no_update, window.dash_clientside.no_update];
        }

        // Resolve the live value via dotted value_source path against the relevant Store.
        const stores = {
            'model-prediction-data': predData,
            'fetched-data': fetchedData,
            'scenario-baseline-data': scenBaseline,
            'scenario-current-values': scenCurrent,
        };
        let liveValue = null;
        const src = entry.value_source;
        if (src && src !== 'none') {
            const [storeName, ...path] = src.split('.');
            let node = stores[storeName];
            for (const k of path) {
                if (node == null) break;
                node = node[k];
            }
            if (typeof node === 'number') liveValue = node.toFixed(4);
            else if (node != null) liveValue = String(node);
        }

        // Build the prompt. Fall back to label-only if value is missing.
        let prompt;
        if (liveValue != null && entry.starter_question.includes('{value}')) {
            prompt = entry.starter_question.replace('{value}', liveValue);
        } else {
            prompt = `Explain the ${entry.label}.`;
        }

        // Open the chat panel by adding the open class.
        const panel = document.getElementById('chat-panel');
        const fab = document.getElementById('chat-toggle-btn');
        if (panel && !panel.classList.contains('chat-panel-open')) {
            panel.classList.add('chat-panel-open');
            if (fab) fab.classList.add('chat-fab-hidden');
        }

        // Focus input on next tick so it's mounted.
        setTimeout(() => {
            const input = document.getElementById('chat-input');
            if (input) {
                input.focus();
                // Move caret to end so the user can append.
                const len = input.value.length;
                if (input.setSelectionRange) input.setSelectionRange(len, len);
            }
        }, 50);

        return [prompt, ''];  // Set chat-input.value, no-op return for chat-panel id.
    }
    """,
    Output('chat-input', 'value', allow_duplicate=True),
    Output('chat-panel', 'data-explain-tick'),  # write-only sink to silence Dash
    Input({'type': 'explain-trigger', 'index': ALL}, 'n_clicks'),
    State('explainable-registry-store', 'data'),
    State('model-prediction-data', 'data'),
    State('fetched-data', 'data'),
    State('scenario-baseline-data', 'data'),
    State('scenario-current-values', 'data'),
    prevent_initial_call=True,
)
```

Note: the `data-explain-tick` second output is a hack to give the callback a writable second target (Dash requires every clientside callback have at least one Output). The attribute is harmless and ignored. Alternatively, route a second meaningful output (e.g. update a logging Store).

- [ ] **Step 3: Manually verify the ✦ click handler is wired**

This won't be visible until ✦ icons are actually injected (Task 6). Just confirm `python app.py` runs without errors. Browser console should be silent.

- [ ] **Step 4: Commit**

```bash
git add assets/style.css app.py
git commit -m "✦ trigger: styling + click handler that preloads chat input

CSS reveals the ✦ on parent hover and bumps it to full opacity on
direct hover. Clientside callback resolves the live value via the
value_source dotted path against in-browser Stores, substitutes it
into the starter_question template, opens the chat panel, focuses the
input. Does not auto-send — user can edit before submitting."
```

---

## Task 6: Inject ✦ triggers into Model tab elements

**Files:**
- Modify: `pages/dashboard.py` — forecast table rows (around lines 1577-1598), contribution rows (around 1715-1733), `_info_pill` helper (around 2271)

- [ ] **Step 1: Add a small helper at the top of pages/dashboard.py**

Near the existing imports and helpers, add:

```python
def _explain_trigger(eid: str) -> html.Span:
    """Render a ✦ icon that pattern-matches the explain-trigger callback."""
    return html.Span(
        '✦',
        id={'type': 'explain-trigger', 'index': eid},
        className='explain-trigger',
        n_clicks=0,
    )
```

- [ ] **Step 2: Add IDs and ✦ to forecast table rows**

In `render_model_ui` (around line 1577), the loop that builds `table_rows` currently does:

```python
    for label, date_str, spot_val, fv_val in horizon_rows_data:
        ...
        is_current = (label == 'Current')

        table_rows.append(
            html.Tr(className='ev-row ev-row-current' if is_current else 'ev-row', children=[
                ...
            ])
        )
```

Replace with:

```python
    for label, date_str, spot_val, fv_val in horizon_rows_data:
        gap = spot_val - fv_val
        gap_pct = (gap / fv_val) * 100 if fv_val else 0
        gap_color = '#EF4444' if gap > 0.01 else '#10B981' if gap < -0.01 else '#6b6b6b'
        is_current = (label == 'Current')

        # Map the row's label to a registry ID.
        row_id_map = {
            'Current': 'ev-row-current',
            '1 Month': 'ev-row-1m',
            '3 Months': 'ev-row-3m',
            '6 Months': 'ev-row-6m',
        }
        row_html_id = row_id_map.get(label)
        explain_eid_map = {
            '1 Month': 'forecast_1m',
            '3 Months': 'forecast_3m',
            '6 Months': 'forecast_6m',
        }
        spot_explain_eid = explain_eid_map.get(label)
        fv_explain_eid = 'fair_value_now' if is_current else None

        spot_cell_children = [f'R {spot_val:.2f}']
        if spot_explain_eid:
            spot_cell_children.append(_explain_trigger(spot_explain_eid))

        fv_cell_children = [f'R {fv_val:.2f}']
        if fv_explain_eid:
            fv_cell_children.append(_explain_trigger(fv_explain_eid))

        table_rows.append(
            html.Tr(
                id=row_html_id,  # selectors target #ev-row-1m etc.
                className=('ev-row ev-row-current explainable-parent' if is_current
                           else 'ev-row explainable-parent'),
                children=[
                    html.Td(children=[
                        html.Div(label, className='ev-horizon-label'),
                        html.Div(date_str, className='ev-horizon-date'),
                    ], className='ev-cell-horizon'),
                    html.Td(spot_cell_children, className='ev-cell-spot'),
                    html.Td(fv_cell_children, className='ev-cell-fv'),
                    html.Td(children=[
                        html.Span(f'{gap:+.2f}', style={'color': gap_color}),
                        html.Span(f' ({gap_pct:+.1f}%)', className='ev-gap-pct', style={'color': gap_color}),
                    ], className='ev-cell-gap'),
                ],
            )
        )
```

- [ ] **Step 3: Add IDs and ✦ to contribution rows**

In the contribution-rows loop (around line 1718):

```python
        contrib_rows.append(
            html.Div(className='contrib-row', children=[
                ...
            ])
        )
```

Replace with:

```python
        contrib_rows.append(
            html.Div(
                id=f'contrib-row-{c["feature"]}',
                className='contrib-row explainable-parent',
                children=[
                    html.Div(className='contrib-info', children=[
                        html.Span(feat_name, className='contrib-name'),
                        html.Span(direction_label, className='contrib-direction'),
                    ]),
                    html.Div(className='contrib-bar-container', children=[
                        html.Div(className='contrib-bar', style={
                            'width': f'{max(bar_width, 2)}%',
                            'backgroundColor': bar_color,
                        }),
                    ]),
                    html.Span(
                        children=[
                            f'{contrib:+.4f} ZAR',
                            _explain_trigger(f'contrib_{c["feature"]}'),
                        ],
                        className='contrib-value',
                        style={'color': bar_color},
                    ),
                ],
            )
        )
```

Make sure to apply the equivalent treatment to the lag1 anchor row above this loop too — search a few lines up for `contrib_rows.append(` (the first occurrence, which renders the random-walk anchor). Wrap its value span the same way and use ID `contrib-row-ZAR_USD_lag1` plus eid `contrib_ZAR_USD_lag1`.

- [ ] **Step 4: Modify `_info_pill` to accept an optional explain_eid**

Find `_info_pill` (around line 2271). Replace it with:

```python
def _info_pill(label, value, description=None, explain_eid=None):
    """Render a labeled metric pill. If explain_eid is given, attach a ✦ trigger
    that opens the chat with a starter question about this metric."""
    pill_id = f'metric-{explain_eid.replace("metric_", "")}' if explain_eid else None
    inner = [
        html.Div(label, className='info-pill-label'),
        html.Div(
            children=[value, _explain_trigger(explain_eid)] if explain_eid else value,
            className='info-pill-value',
        ),
    ]
    if description:
        inner.append(html.Div(description, className='info-pill-description'))
    return html.Div(
        id=pill_id,
        children=inner,
        className='info-pill explainable-parent' if explain_eid else 'info-pill',
    )
```

Note the implicit `info-pill` class — verify it exists in `style.css`. If `_info_pill` previously rendered with a different className, preserve that and append `explainable-parent`.

- [ ] **Step 5: Wire eids into the metric pills**

Find each `_info_pill('MAE', ...)`, `_info_pill('RMSE', ...)` etc. (around lines 1765-1779 and 2245-2256). Add `explain_eid='metric_mae'` etc. matching the registry IDs:

```python
            _info_pill('MAE', f"ZAR {metrics.get('mae', 0):.4f}",
                       'Mean Absolute Error: Average forecast error in ZAR. Lower values indicate better precision.',
                       explain_eid='metric_mae'),
            _info_pill('RMSE', f"ZAR {metrics.get('rmse', 0):.4f}",
                       'Root Mean Squared Error: Similar to MAE but penalizes larger misses more heavily.',
                       explain_eid='metric_rmse'),
            _info_pill('R²', f"{metrics.get('r2', 0):.4f}",
                       'Out-of-sample R². Proportion of test-set variance explained — noteworthy for FX (Meese-Rogoff puzzle).',
                       explain_eid='metric_r2'),
            _info_pill('MAPE', f"{metrics.get('mape', 0):.2f}%",
                       'Mean Absolute Percentage Error: Average error relative to the exchange rate level.',
                       explain_eid='metric_mape'),
            _info_pill("Theil's U", f"{metrics.get('theils_u', 0):.4f}",
                       'Model RMSE / random-walk RMSE. U < 1 means the model beats the naïve forecast (U = 0.9969).',
                       explain_eid='metric_theils_u'),
            _info_pill('Directional Accuracy', f"{metrics.get('directional_accuracy', 0):.1f}%",
                       'Correctly predicted direction in 67.65% of test months (vs 50% random guessing).',
                       explain_eid='metric_directional_accuracy'),
```

Apply the same to the duplicate metric pills around line 2245-2256.

- [ ] **Step 6: Manually verify ✦ icons appear and clicking opens chat**

Run `python app.py`, log into dashboard, navigate to Model tab. Confirm:

1. Hovering a forecast row reveals a ✦ next to its `R {spot_val}` cell.
2. Clicking ✦ opens the chat panel with the input pre-filled (e.g. "Explain the 6-month forecast (R 18.4232). What's driving it?").
3. Cursor is in the input, focused.
4. User can edit and hit enter — message goes through normally.
5. Same hover → ✦ → preload behavior on each contribution row and each metric pill.

If ✦ doesn't appear: check that the `.explainable-parent` class is on the parent and the CSS made it through. If clicking does nothing: check browser console for callback errors and verify the pattern-matching ID structure.

- [ ] **Step 7: Commit**

```bash
git add pages/dashboard.py
git commit -m "inject ✦ explain triggers into Model tab elements

Forecast table rows get stable HTML IDs (#ev-row-1m, etc.), each
spot/fair-value cell gets a hover-revealed ✦ tied to the registry
ID. Contribution rows get #contrib-row-<feat> IDs and a ✦ in the
value span. _info_pill now accepts an optional explain_eid arg that
attaches the trigger and stamps a stable id like #metric-mae for
citation jump targets."
```

---

## Task 7: Heatmap click-to-explain (Plotly clickData)

**Files:**
- Modify: `app.py` (or `pages/dashboard.py` — wherever the time-series-plot's clickData is/should be wired)

Plotly heatmap cells aren't stable HTML, so the ✦-on-hover pattern doesn't apply. Instead, clicking any cell triggers the same explain flow.

- [ ] **Step 1: Locate the heatmap construction**

Find the heatmap figure construction in `pages/dashboard.py` around line 1218. Pre-checked: heatmap x/y axes use **friendly names** (from `label_map`, truncated to 20 chars), so `pt.x` / `pt.y` from `clickData` would NOT match registry IDs (which use raw column names). Solution: add `customdata` carrying raw column pairs so the click handler can recover them.

- [ ] **Step 2: Add `customdata` with raw column pairs to the heatmap trace**

Find the existing `go.Heatmap(...)` call (around `pages/dashboard.py:1218-1233`):

```python
        fig = go.Figure(data=go.Heatmap(
            z=z,
            x=friendly_names,
            y=friendly_names,
            colorscale=...,
            zmin=-1, zmax=1,
            text=text_grid,
            ...
        ))
```

Insert a `customdata` 2D array (one `[raw_x, raw_y]` pair per cell) and update `hovertemplate` to keep using friendly names:

```python
        # Build a 2D customdata array: customdata[i][j] = [raw_x, raw_y]
        # where i indexes y-axis cols (numeric_cols) and j indexes x-axis cols.
        customdata = [[[numeric_cols[j], numeric_cols[i]] for j in range(len(numeric_cols))]
                      for i in range(len(numeric_cols))]

        fig = go.Figure(data=go.Heatmap(
            z=z,
            x=friendly_names,
            y=friendly_names,
            customdata=customdata,
            colorscale=[[0, '#EF4444'], [0.5, '#1a1a2e' if is_dark else '#f8f8fc'], [1, '#10B981']],
            zmin=-1, zmax=1,
            text=text_grid,
            texttemplate='%{text}',
            textfont=dict(size=10, color=text_color),
            hovertemplate='%{x} vs %{y}<br>r = %{z:.3f}<extra></extra>',
            colorbar=dict(
                title=dict(text='r', font=dict(color=text_muted, size=11)),
                tickfont=dict(color=text_muted, size=10),
                outlinewidth=0,
            ),
        ))
```

- [ ] **Step 3: Add a clientside callback that listens for heatmap-cell clicks**

Pre-checked: no existing clickData callback on `time-series-plot`. In `app.py`, near the other clientside callbacks:

```python
# Heatmap cell click → trigger explain flow on the corresponding corr_<A>_<B> entry.
# Reads raw column pair from pt.customdata (added in the Heatmap trace construction).
app.clientside_callback(
    """
    function(clickData, plotMode, registry) {
        if (!clickData || !clickData.points || !clickData.points.length) {
            return [window.dash_clientside.no_update, window.dash_clientside.no_update];
        }
        if (plotMode !== 'correlation') {
            return [window.dash_clientside.no_update, window.dash_clientside.no_update];
        }
        const pt = clickData.points[0];
        // customdata is [raw_x, raw_y] — the raw column names for this cell.
        const cd = pt.customdata;
        if (!cd || !registry) {
            return [window.dash_clientside.no_update, window.dash_clientside.no_update];
        }
        const a = cd[0];
        const b = cd[1];
        if (!a || !b || a === b) {
            return [window.dash_clientside.no_update, window.dash_clientside.no_update];
        }
        const eid = `corr_${a}_${b}`;
        const entry = registry[eid];
        if (!entry) {
            return [window.dash_clientside.no_update, window.dash_clientside.no_update];
        }
        const r = (typeof pt.z === 'number') ? pt.z.toFixed(2) : String(pt.z);
        const prompt = entry.starter_question.replace('{value}', r);

        // Open chat panel + preload input
        const panel = document.getElementById('chat-panel');
        const fab = document.getElementById('chat-toggle-btn');
        if (panel && !panel.classList.contains('chat-panel-open')) {
            panel.classList.add('chat-panel-open');
            if (fab) fab.classList.add('chat-fab-hidden');
        }
        setTimeout(() => {
            const input = document.getElementById('chat-input');
            if (input) input.focus();
        }, 50);

        return [prompt, Date.now()];
    }
    """,
    Output('chat-input', 'value', allow_duplicate=True),
    Output('chat-panel', 'data-heatmap-tick'),
    Input('time-series-plot', 'clickData'),
    State('plot-mode', 'data'),
    State('explainable-registry-store', 'data'),
    prevent_initial_call=True,
)
```

- [ ] **Step 4: Manually verify heatmap clicks open chat**

Run `python app.py`, navigate to Data tab, switch to Correlation plot mode. Click any cell. Confirm:

1. Chat panel opens.
2. Input is preloaded with: "The correlation between A and B is X.XX. Is that strong, and what's the economic intuition?"
3. Hitting enter sends the message through normally.

- [ ] **Step 5: Commit**

```bash
git add app.py pages/dashboard.py
git commit -m "heatmap cells → click-to-explain via Plotly clickData

Plotly heatmap cells aren't HTML siblings, so the ✦-on-hover pattern
isn't viable. The heatmap trace now carries customdata 2D-array of
raw column pairs (axes still display friendly names). A new clientside
callback listens for clickData on time-series-plot in correlation mode,
recovers the raw cols from customdata, maps to a corr_<A>_<B> registry
entry, and triggers the same explain flow as the ✦ click handler."
```

---

## Task 8: Inject ✦ triggers into Scenario tab + waterfall click

**Files:**
- Modify: `pages/dashboard.py` — scenario cards (lines 387, 400, 410) already have IDs, just add `.explainable-parent` and a ✦ trigger
- Modify: `app.py` — waterfall clickData callback

- [ ] **Step 1: Wrap scenario cards with explainable-parent + ✦**

Find the scenario base/result/delta card definitions (around lines 380-415). The base value:

```python
                    html.Div(id='scenario-base-value', className='scenario-card-value'),
                    html.Div(id='scenario-base-change', className='scenario-card-change'),
```

Wrapping the values themselves is awkward because they're rendered as children by a callback. Easier: add the ✦ as a sibling that's revealed on parent-card hover. Add the `.explainable-parent` class to the **parent card** wrapper instead — find the surrounding card div (search for `scenario-card`-like classes around the value div).

For each of the three card divs (base, result, delta), add a ✦ inside the card wrapper:

```python
                # Base card (around line 385)
                html.Div(className='scenario-card scenario-card-base explainable-parent', children=[
                    ...,  # existing children
                    _explain_trigger('scenario_base_value'),
                ]),
```

Repeat with `scenario_result_value` and `scenario_delta_value`.

- [ ] **Step 2: Add `customdata` to the waterfall trace so click can recover raw feature IDs**

The waterfall is a horizontal bar chart (around `pages/dashboard.py:2552-2564`) with friendly names on the y-axis and deltas on x. To recover raw feature IDs on click, add a `customdata` array carrying the raw IDs. Replace:

```python
        labels = [get_friendly_feature_name(w['feature']) for w in active_waterfall]
        deltas = [w['delta'] for w in active_waterfall]
        colors = ['#EF4444' if d > 0 else '#10B981' for d in deltas]

        fig.add_trace(go.Bar(
            x=deltas,
            y=labels,
            orientation='h',
            marker=dict(color=colors, cornerradius=4),
            hovertemplate='%{y}<br>Δ Contribution: %{x:+.4f}<extra></extra>',
        ))
```

with:

```python
        labels = [get_friendly_feature_name(w['feature']) for w in active_waterfall]
        raw_feats = [w['feature'] for w in active_waterfall]
        deltas = [w['delta'] for w in active_waterfall]
        colors = ['#EF4444' if d > 0 else '#10B981' for d in deltas]

        fig.add_trace(go.Bar(
            x=deltas,
            y=labels,
            customdata=raw_feats,  # raw feature IDs for click→explain handler
            orientation='h',
            marker=dict(color=colors, cornerradius=4),
            hovertemplate='%{y}<br>Δ Contribution: %{x:+.4f}<extra></extra>',
        ))
```

- [ ] **Step 3: Add waterfall click handler**

In `app.py`:

```python
# Waterfall bar click → explain that feature's contribution.
# Pre-checked: no existing clickData callback on scenario-waterfall-chart.
# pt.customdata carries the raw feature ID (added in Step 2 above);
# pt.x is the delta value (horizontal bars).
app.clientside_callback(
    """
    function(clickData, registry) {
        if (!clickData || !clickData.points || !clickData.points.length) {
            return [window.dash_clientside.no_update, window.dash_clientside.no_update];
        }
        const pt = clickData.points[0];
        const featId = pt.customdata;
        if (!featId || !registry) {
            return [window.dash_clientside.no_update, window.dash_clientside.no_update];
        }
        const eid = `contrib_${featId}`;
        const entry = registry[eid];
        if (!entry) {
            return [window.dash_clientside.no_update, window.dash_clientside.no_update];
        }
        const v = (typeof pt.x === 'number') ? pt.x.toFixed(4) : String(pt.x);
        const prompt = entry.starter_question.replace('{value}', v);

        const panel = document.getElementById('chat-panel');
        const fab = document.getElementById('chat-toggle-btn');
        if (panel && !panel.classList.contains('chat-panel-open')) {
            panel.classList.add('chat-panel-open');
            if (fab) fab.classList.add('chat-fab-hidden');
        }
        setTimeout(() => {
            const input = document.getElementById('chat-input');
            if (input) input.focus();
        }, 50);

        return [prompt, Date.now()];
    }
    """,
    Output('chat-input', 'value', allow_duplicate=True),
    Output('chat-panel', 'data-waterfall-tick'),
    Input('scenario-waterfall-chart', 'clickData'),
    State('explainable-registry-store', 'data'),
    prevent_initial_call=True,
)
```

- [ ] **Step 4: Manually verify**

Run `python app.py`, log in, navigate to Scenario tab. Adjust a slider or two so the scenario differs from base. Confirm:

1. Hovering each card (base, scenario, delta) reveals a ✦.
2. Clicking opens the chat with the appropriate starter question.
3. Clicking a waterfall bar opens the chat with the corresponding feature contribution starter question.

- [ ] **Step 5: Commit**

```bash
git add pages/dashboard.py app.py
git commit -m "scenario tab ✦ triggers + waterfall click-to-explain

Each scenario card (base, result, delta) gets a hover-revealed ✦
linked to its registry entry. Waterfall bars listen for clickData
and trigger the contribution-feature explain flow."
```

---

## Task 9: Onboarding tooltip (one-time hint)

**Files:**
- Modify: `app.py` — add hidden tooltip element in the dashboard layout
- Modify: `assets/style.css` — tooltip styles
- Modify: `assets/interactions.js` — localStorage gating + reveal logic

- [ ] **Step 1: Add the tooltip element**

In `pages/dashboard.py`, near the top of the dashboard layout (or anywhere the user will see it), add:

```python
html.Div(
    id='explain-onboarding-tooltip',
    className='explain-onboarding-tooltip explain-onboarding-hidden',
    children=[
        html.Span('✦', className='explain-onboarding-icon'),
        html.Span('Hover any number to ask the AI to explain it.', className='explain-onboarding-text'),
        html.Button('×', id='explain-onboarding-close', className='explain-onboarding-close', n_clicks=0),
    ],
),
```

- [ ] **Step 2: Add tooltip CSS**

Append to `assets/style.css`:

```css
/* ✦ Onboarding — one-time hint shown to first-time users */
.explain-onboarding-tooltip {
    position: fixed;
    bottom: 88px;
    right: 24px;
    z-index: 9000;
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 12px 16px;
    background: var(--surface-2, #1a1a2e);
    color: var(--text-1, #ffffff);
    border: 1px solid rgba(155, 110, 245, 0.35);
    border-radius: 10px;
    box-shadow: 0 10px 40px rgba(0, 0, 0, 0.4);
    font-size: 0.875rem;
    max-width: 320px;
    animation: explainOnboardingFadeIn 0.4s ease-out;
}

.explain-onboarding-hidden { display: none !important; }

.explain-onboarding-icon { color: var(--accent-purple, #9b6ef5); font-size: 1.1rem; }
.explain-onboarding-text { flex: 1; }
.explain-onboarding-close {
    background: transparent;
    border: none;
    color: var(--text-2, #9c9cb0);
    font-size: 1.2rem;
    cursor: pointer;
    padding: 0 4px;
    line-height: 1;
}
.explain-onboarding-close:hover { color: var(--text-1, #fff); }

@keyframes explainOnboardingFadeIn {
    from { opacity: 0; transform: translateY(10px); }
    to { opacity: 1; transform: translateY(0); }
}
```

- [ ] **Step 3: Add localStorage gating + dismiss logic**

In `assets/interactions.js`, append at the bottom:

```javascript
// ✦ Onboarding tooltip — show once per browser
(function () {
    const KEY = 'dash.onboarding.explainSeen';

    function maybeShow() {
        try {
            if (localStorage.getItem(KEY) === '1') return;
        } catch (e) { return; }  // localStorage disabled
        const tip = document.getElementById('explain-onboarding-tooltip');
        if (tip && document.querySelector('.explain-trigger')) {
            tip.classList.remove('explain-onboarding-hidden');
        }
    }

    function dismiss() {
        try { localStorage.setItem(KEY, '1'); } catch (e) {}
        const tip = document.getElementById('explain-onboarding-tooltip');
        if (tip) tip.classList.add('explain-onboarding-hidden');
    }

    document.addEventListener('click', function (e) {
        if (e.target && e.target.id === 'explain-onboarding-close') {
            dismiss();
        }
        if (e.target && e.target.classList && e.target.classList.contains('explain-trigger')) {
            // First click on any ✦ counts as discovery; auto-dismiss.
            dismiss();
        }
    });

    // Re-check after Dash mounts (which happens after this script runs).
    // Poll briefly for the tooltip + at least one ✦ trigger to appear.
    let attempts = 0;
    const poll = setInterval(() => {
        attempts++;
        if (attempts > 40) { clearInterval(poll); return; }  // ~6s ceiling
        if (document.querySelector('.explain-trigger')) {
            maybeShow();
            clearInterval(poll);
        }
    }, 150);
})();
```

- [ ] **Step 4: Manually verify the tooltip flow**

1. Clear browser localStorage for the dashboard origin (DevTools → Application → Local Storage → delete `dash.onboarding.explainSeen` if present).
2. Refresh `/dashboard`. The tooltip should appear in the bottom-right ~once a ✦ has rendered.
3. Click `×` → tooltip disappears. Refresh — it should NOT come back.
4. Clear localStorage again. Refresh, this time hover and click a ✦ instead of the close button. Refresh — tooltip should also NOT come back (auto-dismissed on first explore).

- [ ] **Step 5: Commit**

```bash
git add pages/dashboard.py assets/style.css assets/interactions.js
git commit -m "add one-time onboarding tooltip for ✦ explain triggers

Bottom-right tooltip appears on first dashboard visit explaining the
hover-✦ affordance. Dismissed by clicking × or by clicking any ✦.
State persists in localStorage under dash.onboarding.explainSeen."
```

---

## Task 10: End-to-end manual verification pass

**Files:** none (verification only)

- [ ] **Step 1: Cold-start verification**

Stop the app. Clear browser cache + localStorage. Run `python app.py`. Log in. Open `/dashboard`. Wait for full data load.

Verify in order:
- ✦ icons appear on hover for: each forecast row's spot cell, current-row fair value, every contribution row, every metric pill (Specifications sub-tab), every scenario card.
- Onboarding tooltip appears once. Dismiss it.
- Click each kind of ✦ — chat panel opens, input is preloaded with a sensible starter question containing the live numeric value, focus is in the input, no auto-send.

- [ ] **Step 2: Citation roundtrip**

In the chat, ask: "What's the current 6-month forecast, the model's R², and the directional accuracy?"

Confirm:
- The AI reply renders with three citation chips (purple pills with ↗).
- Hover shows tooltips with full labels.
- Clicking each chip navigates to the cited element and flashes the highlight.

- [ ] **Step 3: Plotly clicks**

- Switch to Data tab → Correlation. Click any cell. Chat opens with the correlation starter question. Send. Reply should reference the variables.
- Switch to Scenario tab. Adjust VIX slider so waterfall bars are visible. Click a bar. Chat opens with the contribution starter question.

- [ ] **Step 4: Graceful degradation checks**

- Ask the AI: "Cite a fake number with ID `unicorn_xyz`." If it complies with `[[unicorn_xyz|42]]`, confirm the value renders as plain text (no chip, no error in console).
- Open chat with no `model-prediction-data` loaded (force by ctrl-clicking ✦ before predictions arrive — or just observe the cold-start window). The starter question should fall back to a label-only prompt rather than `Explain the 6-month forecast (null).`.

- [ ] **Step 5: Mobile fallback (touch device)**

If practical, open the dashboard on a phone/tablet. Confirm ✦ icons are visible (subtler) without hover. Tap one — chat opens.

- [ ] **Step 6: Commit any small fixes discovered, or close out**

If verification revealed bugs, file them as follow-up tasks and fix in a final commit. If clean:

```bash
git log --oneline | head -10  # confirm the feature's commits are coherent
```

End of plan.

---

## Risks / Open questions worth flagging at PR time

- **System prompt token cost.** The registry catalog adds ~3KB per chat turn. Worth measuring and considering Gemini context caching as a follow-up.
- **DOM target drift.** If `pages/dashboard.py` is refactored, registry `dom_target` selectors can silently break. The populating callback could log a warning when no element matches, but that requires DOM access from a server callback (not trivial). Document the dependency in `logic/explainable_registry.py` instead.
- **Citation discipline.** Gemini may forget the `[[id|value]]` syntax. The fallback (plain text) means worst-case the feature just doesn't fire — no broken UI. If discipline is poor, strengthening the prompt with a few-shot example is the lever.
