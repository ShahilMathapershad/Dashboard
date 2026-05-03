# Explainable Numbers (✦ deep links) + Inline Citations — Design

**Date:** 2026-05-03
**Scope:** Two new AI-chat features that bind the chatbot more tightly to the dashboard surface.

## Goal

Turn the AI chat from a side panel into the dashboard's connective tissue. Two coordinated features:

1. **Explainable Numbers (✦ deep links)** — hover any high-value number on the dashboard, click a ✦ icon, and the chat panel opens with a starter question pre-filled. Surgical contextual help, replacing today's "type from scratch" UX.
2. **Inline Citations** — when the AI mentions a value in its replies, render it as a small clickable chip. Clicking the chip switches to the relevant tab/mode, scrolls to the value, and flashes a highlight. Citations make claims auditable and turn replies into navigation.

Both features share a single registry of "explainable values" so they stay in sync.

## Non-goals

- Citations on agent-mode action summaries (only on AI text replies)
- Multi-citation in a single token (`[[id1+id2|combined]]`) — model emits two adjacent chips instead
- Click-analytics or "most-asked" tracking
- Mobile-first — hover affordances are desktop-primary; touch devices get a fallback (always-visible ✦ at lower opacity)

## Architecture

A single shared module — `logic/explainable_registry.py` — owns the curated list of ~40-60 explainable values. Both features consume it.

### Data flow — ✦ deep links

1. Dashboard renders. Where the registry says "value X lives at this DOM target," a sibling `<span class="explain-trigger" data-explain-id="…">✦</span>` is added next to the value.
2. CSS makes the ✦ visible only on parent hover.
3. Click → clientside callback opens the chat panel (reusing existing toggle logic), sets `chat-input.value` to the registry's starter-question template (with the live value substituted from the relevant `dcc.Store`), and focuses the input.
4. User edits if they want, hits send. The existing `handle_chat_send` callback handles the rest. The starter-question text *is* the prompt — no special context injection beyond what already flows through `_build_chat_context`.

### Data flow — inline citations

1. The chat system prompts (`CHAT_SYSTEM_PROMPT`, `AGENT_SYSTEM_PROMPT`) are augmented at import time with a registry snippet listing valid citation IDs and the `[[id|value]]` markup syntax.
2. Model emits text like `"VIX is at [[VIX_latest|18.4]] vs the 12-month z-score of [[VIX_zscore12|1.2]]"`.
3. After the response comes back, a Python post-processor parses `[[id|value]]` tokens against the registry. Unknown IDs gracefully degrade to plain values.
4. Recognised tokens become Dash chip components inside the chat bubble.
5. Clicking a chip writes to `agent-action-store` with the registry entry's `navigate_actions`. The existing `execute_agent_actions` callback (`app.py:397`) handles tab/mode navigation, slider sets, and highlight flashes. **No new action handlers required.**

### Why a shared registry

Every ✦ trigger and every citation chip needs the same metadata: what the value is, what tab it lives on, and what action gets you to it. Splitting that across two implementations would force keeping two lists in sync forever.

## Registry schema

`logic/explainable_registry.py` exports a single `EXPLAINABLE_VALUES` dict mapping ID → entry:

```python
{
    "forecast_6M": {
        "label": "6-month forecast",
        "tab": "model",
        "sub_tab": "predictions",
        "dom_target": "#forecast-table-container .forecast-row-6m",
        "starter_question": "Explain the 6-month forecast ({value}). What's driving this number?",
        "value_source": "model-prediction-data.horizon_6M",
        "navigate_actions": [
            {"type": "navigate_tab", "tab": "model"},
            {"type": "highlight_model", "sub_tab": "predictions", "targets": ["forecast_6M"]},
        ],
    },
    ...
}
```

### Per-entry fields

- `label` — human-readable name used in starter prompt + chip tooltip
- `tab` / `sub_tab` — which dashboard section this value lives on
- `dom_target` — CSS selector. The ✦ icon attaches as a sibling next to this element; citation-jump scrolls *to* this element.
- `starter_question` — template with `{value}` placeholder, used by ✦ click
- `value_source` — dotted path into a `dcc.Store`, so the live value is read at click time. The registry doesn't need to know the *current* number, only where to find it.
- `navigate_actions` — list of agent actions in the existing `agent-action-store` schema. Citation-clicks write this directly to the store.

### Categories and counts

- **Model tab:** 3 forecast cells + 11 feature contributions + 6 performance metrics = ~20
- **Data tab:** 1 `r` value (compare mode) + ~20 heatmap cells (upper triangle, IDs synthesised like `corr_VIX_ZAR_USD`) + 1 per-series latest value = ~30 dynamic + a handful of static
- **Scenario tab:** 3 cards (base / scenario / delta) + waterfall rows (1 per active feature) + summary table rows = ~10

Total: roughly 40-60 entries. Heatmap and waterfall entries are generated programmatically by `expand_dynamic_entries(...)` rather than hand-listed.

## Feature 1 — ✦ hover triggers

### Rendering

A small Dash callback runs on dashboard layout (or per-tab render), walks the registry, and injects:

```html
<span class="explain-trigger" data-explain-id="forecast_6M" data-target="#forecast-table-container .forecast-row-6m">✦</span>
```

next to each `dom_target`. For dynamically-rendered things (forecast cells, contribution bars, heatmap cells, waterfall rows), the trigger is added in the same callback that builds them — see *Files touched* below for the exact list.

### CSS

```css
.explain-trigger {
  opacity: 0;
  transition: opacity 0.15s;
  cursor: pointer;
  margin-left: 4px;
  color: var(--accent-purple);
}
.explainable-parent:hover .explain-trigger { opacity: 0.7; }
.explain-trigger:hover { opacity: 1; }
@media (hover: none) {
  .explain-trigger { opacity: 0.4; }
}
```

### Click handler

Each ✦ trigger is a Dash component with a pattern-matching ID — `html.Span(id={'type': 'explain-trigger', 'index': eid}, ...)` — matching the existing convention in `pages/dashboard.py:1071`. A single Dash clientside callback handles all triggers via `MATCH`/`ALL`:

```python
clientside_callback(
    "...",
    Output('chat-input', 'value'),
    Output('chat-panel', 'className'),  # to open the panel
    Input({'type': 'explain-trigger', 'index': ALL}, 'n_clicks'),
    State('explainable-registry-store', 'data'),
    State('model-prediction-data', 'data'),
    State('fetched-data', 'data'),
    State('scenario-current-values', 'data'),
    State('scenario-baseline-data', 'data'),
    prevent_initial_call=True,
)
```

The JS body:
1. Use `dash_clientside.callback_context.triggered_id.index` to identify which ✦ was clicked.
2. Look up the entry from `explainable-registry-store`.
3. Read the live value from the relevant State Store, traversing `value_source` (e.g. `"model-prediction-data.horizon_6M"`).
4. Substitute `{value}` into `starter_question`. Set `chat-input.value`. Open the chat panel (add `chat-panel-open` class). Focus the input.
5. **Do not auto-send.** User edits if they want, then hits enter.

### Onboarding tooltip

On first dashboard load after this ships, show a one-time tooltip near the first explainable value (the 6M forecast cell): *"Hover any number to ask the AI to explain it."* Dismissed state stored in `localStorage` under `dash.onboarding.explainSeen`. Clientside only — no server roundtrip.

## Feature 2 — inline citations

### Prompt augmentation

Both `CHAT_SYSTEM_PROMPT` and `AGENT_SYSTEM_PROMPT` get a new section appended at module import time, built from the registry:

```
== CITATION MARKUP ==
When you reference any of these values in your reply, wrap them in [[id|value]]:
- forecast_6M — 6-month forecast (Model tab)
- VIX_latest — latest VIX value (Data tab)
- corr_VIX_ZAR_USD — correlation r between VIX and ZAR/USD
... (full list, generated from registry)
Example: "VIX is at [[VIX_latest|18.4]], correlated r=[[corr_VIX_ZAR_USD|0.42]] with the Rand."
Only cite values from the list. For other numbers, write them plainly.
```

### Post-processing

In `handle_chat_send`, after `ai_text` is built but before it's wrapped in the typewriter element:

1. Run regex `r'\[\[([a-zA-Z0-9_]+)\|([^\]]+)\]\]'` over `ai_text`.
2. For each match: if `id` is in registry → emit a Dash `html.Span` chip; else → emit the plain value text (graceful degradation).
3. Build a list of children alternating raw-text spans and chip spans.
4. Replace the `data-fulltext` typewriter approach **for messages that contain citations** with a pre-rendered children list. Messages without citations still use the typewriter unchanged.

### Typewriter compromise

Mixing Dash components with character-by-character animation is awkward. Decision: the typewriter animates plain text only. AI replies containing citations skip the typewriter and appear instantly. Acceptable trade — citation messages are still fast and the chips themselves are the new visual interest.

### Citation chip component

```python
html.Span(
    id={'type': 'citation-chip', 'index': f"{eid}::{message_idx}::{occurrence_idx}"},
    className='chat-citation-chip',
    title=entry['label'],
    n_clicks=0,
    children=[
        html.Span(value),
        html.Span('↗', className='chat-citation-arrow'),
    ],
)
```

The `index` is composite (id + message + occurrence) so the same value cited multiple times in the same reply each gets a unique Dash component ID. The `eid` is recoverable by splitting `index` on `::`.

CSS: small purple-tinted pill matching the existing `chat-action-chip` styling so it feels native rather than tacked on.

### Click handler

A Dash pattern-matching clientside callback:

```python
clientside_callback(
    "...",
    Output('agent-action-store', 'data', allow_duplicate=True),
    Input({'type': 'citation-chip', 'index': ALL}, 'n_clicks'),
    State('explainable-registry-store', 'data'),
    prevent_initial_call=True,
)
```

The JS body:
1. Identify the clicked chip via `triggered_id.index`, split on `::` to recover `eid`.
2. Look up `navigate_actions` from `explainable-registry-store`.
3. Write to `agent-action-store` with the same shape agent mode already uses: `{actions: [...], ts: Date.now()}`.
4. The existing `execute_agent_actions` callback (`app.py:397`) handles tab navigation, plot mode, slider sets, and highlighting. The existing `agent-highlight-store` flash effect provides the scroll-to + flash feedback for free.

## Files touched

### New

- `logic/explainable_registry.py` — `EXPLAINABLE_VALUES` dict, `get_entry(id)`, `expand_dynamic_entries(corr_matrix_vars, scenario_features)`, `serialize_for_store()`, `build_system_prompt_snippet()`.

### Modified

- **`app.py`**
  - Add `dcc.Store(id='explainable-registry-store')` to global stores
  - Add a callback that populates the registry store on dashboard load (with dynamic entries expanded based on currently-available data)
  - Augment `CHAT_SYSTEM_PROMPT` and `AGENT_SYSTEM_PROMPT` with the registry snippet (built once at import time)
  - Modify `handle_chat_send` to post-process `[[id|value]]` markup into chip children for AI messages
  - Add two clientside callbacks: ✦ click delegation, citation-chip click delegation
- **`pages/dashboard.py`**
  - Where forecast cells, contribution bars, metric cards, the correlation heatmap, scenario cards, and waterfall rows are built, add the `.explain-trigger` span sibling and ensure the parent element has the `.explainable-parent` class
  - Add the one-time onboarding tooltip element (hidden by default, shown via clientside callback reading `localStorage`)
- **`assets/style.css`** — new rules for `.explain-trigger`, `.explainable-parent`, `.chat-citation-chip`, `.chat-citation-arrow`, and the onboarding tooltip
- **`assets/interactions.js`** — optional helper for the `localStorage` onboarding flag (may also live inline in the clientside callback)

## Edge cases

- **Model invents an ID** → post-processor strips markup, value renders plain. Logged for prompt-tuning visibility.
- **Value source missing/null at ✦-click time** → starter question falls back to label only (`"Explain the 6-month forecast"`).
- **Heatmap cell ordering** → both `corr_A_B` and `corr_B_A` resolve to the same entry, so the model isn't penalised for ordering.
- **Tab not yet rendered when citation clicked** → `navigate_actions` includes `navigate_tab` first, then highlight runs after tab content mounts. The existing agent flow already handles this delay.
- **User clicks ✦ while chat panel is closed** → toggle logic opens it first; a single tick delay before focusing the input.
- **Mobile / touch devices** → `@media (hover: none)` shows ✦ at lower opacity always.
- **Citation in a code block or quoted text** → post-processor still parses; if undesirable in practice, the regex can be scoped to ignore content inside backticks. Defer this judgement until v1 is in front of users.

## Testing

The repo has no test framework today. Verification is manual:
- Hover each registered value, confirm ✦ appears, click opens chat with correct starter prompt.
- Ask the model questions that should produce citations, confirm chips render and click jumps + highlights correctly.
- Spot-check graceful degradation: ask the model to invent a fake number to confirm unknown IDs render as plain text.
- Confirm onboarding tooltip shows once and never again on the same browser.

## Risks

- **Token cost of registry in system prompt.** ~40-60 entries × ~80 chars = ~5KB added to every chat turn. Mitigation: future Gemini context-cache integration (out of scope here, but the registry snippet is a perfect cache candidate since it's stable per session).
- **Model citation discipline.** Gemini may forget to cite, or cite values not in the registry. Mitigation: graceful fallback (already designed), and the registry snippet's example pattern in the system prompt.
- **DOM target drift.** If `pages/dashboard.py` is refactored and a registered selector breaks, ✦ injection silently fails for that entry. Mitigation: the populating callback can warn on missing selectors when the page mounts.
