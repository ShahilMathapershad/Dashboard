import dash
from dash import Dash, html, dcc, Input, Output, State, callback, callback_context, DiskcacheManager
import dash_bootstrap_components as dbc
from flask import Flask
from dotenv import load_dotenv
import os
import sys
import threading
import diskcache
import multiprocess
import pandas as pd

# On Render (Linux), fork is much faster and more memory-efficient.
# On macOS, spawn is often safer for complex libraries.
try:
    if multiprocess.get_start_method(allow_none=True) is None:
        if sys.platform == 'darwin':
            multiprocess.set_start_method('spawn')
        else:
            # Default to fork for Linux (Render) to save RAM and start faster
            multiprocess.set_start_method('fork')
except RuntimeError:
    # Already set
    pass

# DiskCache for background callbacks
# Use a smaller cache size to avoid disk/RAM pressure
cache = diskcache.Cache("./.cache", size_limit=2**27) # 128MB limit
background_callback_manager = DiskcacheManager(cache)

# Ensure project root is in sys.path for Render
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

load_dotenv()

from logic.session import make_session_token, verify_session, _SESSION_SECRET

server = Flask(__name__)
server.secret_key = _SESSION_SECRET


from flask import request as _flask_request


# Cache-Control on /assets/* — lets the browser reuse style.css, interactions.js
# and three-scenes.js across page navs. Dash already appends an `?m=<mtime>`
# query-string busting param to asset URLs, so it's safe to override the
# default `no-cache` and let the browser actually cache them for an hour.
@server.after_request
def _cache_static_assets(response):
    if response.status_code < 400 and _flask_request.path.startswith('/assets/'):
        response.headers['Cache-Control'] = 'public, max-age=3600'
    return response


# Pre-warm Supabase + model caches in a background thread so the first user
# request hits hot caches instead of paying the ~500ms Supabase round-trip
# and ~50ms joblib.load. Runs under gunicorn's --preload so all workers benefit.
def _warm_caches():
    try:
        from logic.model import fetch_data_from_supabase, load_model
        load_model()
        fetch_data_from_supabase()
        print("--- Cache warm: complete ---")
    except Exception as e:
        print(f"--- Cache warm: failed ({e}) — first request will populate ---")


# Only warm in the actual serving process. Skip in:
#   - DiskcacheManager spawn workers (would race the worker's own Supabase
#     call, two threads sharing the singleton client → EAGAIN on SSL socket)
#   - Flask dev-mode reloader's parent watcher (it doesn't serve requests, so
#     warming there just doubles network traffic on every restart).
if multiprocess.parent_process() is None:
    threading.Thread(target=_warm_caches, daemon=True).start()
app = Dash(
    __name__,
    server=server,
    use_pages=True,
    external_stylesheets=[dbc.themes.BOOTSTRAP],
    # Exclude Three.js (interactions.js loads it conditionally, desktop-only)
    # and critical.css (inlined via index_string for fast first paint).
    assets_ignore=r"(three-scenes\.js|critical\.css)",
    suppress_callback_exceptions=True,
    background_callback_manager=background_callback_manager,
    meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1, maximum-scale=5, viewport-fit=cover"}]
)

from flask_compress import Compress
Compress(server)

import pathlib
_CRITICAL_CSS = (pathlib.Path(__file__).parent / "assets" / "critical.css").read_text()
app.index_string = f"""<!DOCTYPE html>
<html>
  <head>
    {{%metas%}}
    <title>{{%title%}}</title>
    {{%favicon%}}
    {{%css%}}
    <style>{_CRITICAL_CSS}</style>
  </head>
  <body>
    {{%app_entry%}}
    <footer>
      {{%config%}}
      {{%scripts%}}
      {{%renderer%}}
    </footer>
  </body>
</html>"""

app.layout = html.Div(id='theme-main-container', children=[
    dcc.Store(id='user-session', storage_type='session'),
    dcc.Store(id='theme-store', storage_type='local'),
    
    # Global stores for prerendering (moved from dashboard.py)
    dcc.Store(id='dashboard-tab', data='data', storage_type='session'),
    dcc.Store(id='sidebar-state', data='collapsed', storage_type='local'),
    dcc.Store(id='fetched-data', storage_type='session'),
    dcc.Store(id='model-prediction-data', storage_type='session'),
    dcc.Store(id='fetch-trigger', data=0, storage_type='session'),
    dcc.Store(id='model-prediction-trigger', data=0, storage_type='session'),
    dcc.Store(id='predictor-dropdown-options-store', storage_type='session'),
    dcc.Store(id='selected-predictors', data=[], storage_type='session'),
    dcc.Store(id='fetched-data-status', storage_type='session'),
    dcc.Store(id='scenario-baseline-data', storage_type='session'),
    dcc.Store(id='scenario-trigger', data=0, storage_type='session'),
    dcc.Store(id='scenario-current-values', storage_type='session'),
    dcc.Store(id='saved-scenarios', data=[], storage_type='session'),
    dcc.Store(id='chat-history', data=[], storage_type='session'),
    dcc.Store(id='plot-mode', data='timeseries', storage_type='session'),
    dcc.Store(id='selected-compare-vars', data=[], storage_type='session'),
    dcc.Store(id='force-refresh-trigger', data=0, storage_type='memory'),
    dcc.Store(id='table-view-mode', data='raw', storage_type='session'),
    dcc.Store(id='model-sub-tab', data='predictions', storage_type='session'),
    dcc.Store(id='agent-mode-store', data=False, storage_type='session'),
    dcc.Store(id='agent-action-store', storage_type='memory'),
    dcc.Store(id='agent-slider-sync', data=0, storage_type='memory'),
    dcc.Store(id='agent-highlight-store', storage_type='memory'),

    # Cache hydration stores (Wave 2 — predictions cache pipeline).
    dcc.Store(id='cache-metadata-store', storage_type='session'),
    dcc.Store(id='cache-status-store', data='miss', storage_type='session'),
    # Prewarm-on-Get-Started: populates the diskcaches behind
    # fetch_data_from_supabase / predict_next_month / get_scenario_baseline
    # while the user is filling the login form, so post-login hydrate is hot.
    dcc.Store(id='prewarm-status-store', data='idle', storage_type='memory'),
    html.Div(id='cache-refresh-spinner', style={'display': 'none'}),

    dash.page_container,

    # Global error-message stubs. These must always exist in the layout so that
    # dashboard background callbacks (registered globally via @callback) can
    # resolve their `allow_duplicate=True` Outputs on non-dashboard pages
    # (e.g. /login) without emitting "nonexistent object" warnings.
    html.Div(id='data-error', className='error-message'),
    html.Div(id='model-error', className='error-message'),
    html.Div(id='scenario-error', className='error-message'),
    # Hidden stubs for dashboard-only IDs that globally-registered callbacks
    # write to. Without these, dash-renderer logs "nonexistent object" warnings
    # in the browser console whenever the user is on /login or /registration.
    # Wrapped in a display:none parent so even when a callback overwrites the
    # stub's `style` prop, the element stays visually hidden — the real element
    # in the dashboard layout still gets dispatched to and renders normally.
    html.Div(style={'display': 'none'}, children=[
        html.Div(id='data-loading'),
        html.Div(id='model-loading'),
        html.Div(id='scenario-loading'),
        html.Div(id='model-results-container'),
        html.Div(id='scenario-content'),
        html.Div(id='visualization-container'),
        html.Div(id='fetch-status-display'),
        html.Div(id='data-table-body'),
        html.Div(id='forecast-table-container'),
        html.Div(id='feature-contributions'),
        html.Div(id='model-info-content'),
        html.Div(id='model-description-content'),
        html.Div(id='scenario-sliders-container'),
        html.Div(id='scenario-base-value'),
        html.Div(id='scenario-base-change'),
        html.Span(id='topbar-avatar'),
        html.Span(id='topbar-username'),
        html.Button(id='refresh-data-btn', n_clicks=0),
    ]),

    # ── Global AI Chat Panel (available on all pages) ──
    html.Div(id='chat-panel', className='chat-panel', children=[
        html.Div(className='chat-header', children=[
            html.Div(className='chat-header-left', children=[
                html.Span('✦', className='chat-header-icon'),
                html.Span('AI Assistant', id='chat-header-title', className='chat-header-title'),
            ]),
            html.Div(className='chat-header-right', children=[
                html.Div(className='agent-mode-toggle', id='agent-mode-toggle', children=[
                    html.Span('Chat', className='agent-mode-label agent-mode-label-chat agent-mode-label-active'),
                    html.Div(className='agent-mode-switch', id='agent-mode-switch', n_clicks=0, children=[
                        html.Div(className='agent-mode-knob'),
                    ]),
                    html.Span('Agent', className='agent-mode-label agent-mode-label-agent'),
                ]),
                html.Button('✕', id='chat-close-btn', className='chat-close-btn', n_clicks=0),
            ]),
        ]),
        html.Div(id='chat-messages', className='chat-messages', children=[
            html.Div(className='chat-message chat-message-ai', children=[
                html.Div("Ask me about ZAR/USD dynamics, model predictions, fair value estimates, scenario analysis, or the macroeconomic data in this dashboard.",
                         className='chat-bubble chat-bubble-ai')
            ])
        ]),
        html.Div(className='chat-input-area', children=[
            dcc.Input(
                id='chat-input',
                type='text',
                placeholder='Ask about ZAR/USD or economics...',
                className='chat-input',
                debounce=False,
                n_submit=0,
            ),
            html.Button('→', id='chat-send-btn', className='chat-send-btn', n_clicks=0),
        ]),
    ]),
    html.Button(
        html.Span('✦', className='chat-fab-icon'),
        id='chat-toggle-btn',
        className='chat-fab',
        n_clicks=0,
    ),
    html.Div(id='chat-loading-trigger', style={'display': 'none'}),
])


from core import cache_callbacks
cache_callbacks.register(app)


# Clientside callback: detect system color scheme and apply theme class
app.clientside_callback(
    """
    function(themeStoreData) {
        function applyTheme(theme) {
            var container = document.getElementById('theme-main-container');
            if (theme === 'light') {
                document.body.classList.add('light-theme');
                if (container) container.className = 'light-theme';
            } else {
                document.body.classList.remove('light-theme');
                if (container) container.className = '';
            }
        }

        // Detect system preference
        var mq = window.matchMedia('(prefers-color-scheme: light)');
        var theme = mq.matches ? 'light' : 'dark';
        applyTheme(theme);

        // Listen for future changes
        if (!window._themeListenerAttached) {
            window._themeListenerAttached = true;
            mq.addEventListener('change', function(e) {
                var t = e.matches ? 'light' : 'dark';
                applyTheme(t);
            });
        }

        return theme;
    }
    """,
    Output('theme-store', 'data'),
    Input('theme-store', 'data'),
)


# Hydrate of fetched-data / model-prediction-data / scenario-baseline-data is
# handled by core.cache_callbacks.hydrate_dashboard (registered above). The
# legacy three-step trigger chain that lived here was removed in the cache-first
# cutover.

# Global auth and navigation guard
@callback(
    Output('_pages_location', 'pathname'),
    Input('_pages_location', 'pathname'),
    Input('user-session', 'data'),
    prevent_initial_call=True
)
def auth_redirection(current_path, session_data):
    # Determine if user is logged in (verified via HMAC token)
    logged_in = verify_session(session_data)
    
    # We want to know what triggered the callback
    ctx = dash.callback_context
    trigger_id = ctx.triggered[0]['prop_id'].split('.')[0] if ctx.triggered else 'initial'
    
    try:
        if not logged_in:
            if current_path not in ['/', '/registration', None]:
                return '/'
        else:
            if current_path in ['/', '/registration', None]:
                return '/dashboard'
            # /profile and /dashboard are valid authenticated routes — no redirect needed
    except Exception:
        pass
            
    return dash.no_update


# Wipe user-specific session data on logout. We deliberately DON'T touch
# fetched-data / model-prediction-data / scenario-baseline-data: those are
# derived from public macro data (same for every user) and clearing them
# would cascade through render_model_ui / sync_scenario_ui and emit
# "nonexistent object" warnings on /login. Chat history and saved scenarios
# are the only genuinely per-user state.
@callback(
    Output('chat-history', 'data', allow_duplicate=True),
    Output('saved-scenarios', 'data', allow_duplicate=True),
    Output('scenario-current-values', 'data', allow_duplicate=True),
    Input('user-session', 'data'),
    prevent_initial_call=True,
)
def clear_data_on_logout(session_data):
    if session_data is None:
        return [], [], None
    return dash.no_update, dash.no_update, dash.no_update


# ═══════════════════════════════════════════
#   Global AI Chatbot — Clientside Callbacks
# ═══════════════════════════════════════════

# Toggle agent mode on/off
app.clientside_callback(
    """
    function(n_clicks, currentMode) {
        if (!n_clicks) return window.dash_clientside.no_update;
        const newMode = !currentMode;

        const toggle = document.getElementById('agent-mode-toggle');
        const panel = document.getElementById('chat-panel');
        const input = document.getElementById('chat-input');
        const title = document.getElementById('chat-header-title');

        if (toggle) {
            if (newMode) {
                toggle.classList.add('agent-mode-active');
                if (panel) panel.classList.add('chat-agent-mode');
                if (input) input.placeholder = 'Ask the agent to do something...';
                if (title) title.textContent = 'AI Agent';
            } else {
                toggle.classList.remove('agent-mode-active');
                if (panel) panel.classList.remove('chat-agent-mode');
                if (input) input.placeholder = 'Ask about ZAR/USD or economics...';
                if (title) title.textContent = 'AI Assistant';
            }
        }
        return newMode;
    }
    """,
    Output('agent-mode-store', 'data'),
    Input('agent-mode-switch', 'n_clicks'),
    State('agent-mode-store', 'data'),
    prevent_initial_call=True
)

# Execute agent actions — watches agent-action-store and updates dashboard stores
@callback(
    Output('dashboard-tab', 'data', allow_duplicate=True),
    Output('scenario-current-values', 'data', allow_duplicate=True),
    Output('selected-predictors', 'data', allow_duplicate=True),
    Output('plot-mode', 'data', allow_duplicate=True),
    Output('agent-slider-sync', 'data'),
    Output('selected-compare-vars', 'data', allow_duplicate=True),
    Output('_pages_location', 'pathname', allow_duplicate=True),
    Output('agent-highlight-store', 'data'),
    Input('agent-action-store', 'data'),
    State('scenario-baseline-data', 'data'),
    State('agent-slider-sync', 'data'),
    State('_pages_location', 'pathname'),
    prevent_initial_call=True
)
def execute_agent_actions(action_data, baseline_data, slider_sync, current_path):
    if not action_data or not isinstance(action_data, dict):
        return (dash.no_update,) * 8

    actions = action_data.get('actions', [])
    if not actions:
        return (dash.no_update,) * 8

    tab_out = dash.no_update
    scenario_vals_out = dash.no_update
    predictors_out = dash.no_update
    plot_mode_out = dash.no_update
    slider_sync_out = dash.no_update
    compare_vars_out = dash.no_update
    path_out = dash.no_update
    highlight_out = dash.no_update

    # Collect highlight targets
    highlight_data = {}

    for action in actions:
        atype = action.get('type', '')

        if atype == 'navigate_tab':
            tab_name = action.get('tab', '')
            if tab_name in ('data', 'model', 'scenario'):
                tab_out = tab_name
                # If user asked about specific model metrics/sections, highlight them
                highlight_keys = action.get('highlight', [])
                if highlight_keys:
                    highlight_data = {'type': 'model', 'keys': highlight_keys}

        elif atype == 'highlight_model':
            # Dedicated action to highlight model tab elements
            tab_out = 'model'
            targets = action.get('targets', [])
            sub_tab = action.get('sub_tab', '')
            if targets:
                highlight_data = {'type': 'model', 'keys': targets, 'sub_tab': sub_tab}

        elif atype == 'set_scenario_sliders':
            slider_vals = action.get('values', {})
            if slider_vals and baseline_data:
                # Always reset to baseline first so each agent scenario starts clean
                new_vals = {}
                for pred in baseline_data.get('predictors', []):
                    new_vals[pred.get('raw_col', '')] = pred.get('current_value', 0)

                changed_keys = []
                known_keys = {p.get('raw_col') for p in baseline_data.get('predictors', [])}
                for key, val in slider_vals.items():
                    if key not in known_keys:
                        continue
                    try:
                        # Support percentage changes like {"VIX": "+10%"}
                        if isinstance(val, str) and '%' in val:
                            pct = float(val.replace('%', '').replace('+', ''))
                            base_val = new_vals.get(key, 0)
                            new_vals[key] = base_val * (1 + pct / 100)
                        else:
                            new_vals[key] = float(val)
                    except (ValueError, TypeError):
                        continue

                    changed_keys.append(key)

                    # Clamp to slider range
                    for pred in baseline_data.get('predictors', []):
                        if pred.get('raw_col') == key:
                            new_vals[key] = max(pred.get('range_low', new_vals[key]),
                                                min(pred.get('range_high', new_vals[key]), new_vals[key]))
                            break

                scenario_vals_out = new_vals
                tab_out = 'scenario'
                slider_sync_out = (slider_sync or 0) + 1
                if changed_keys:
                    highlight_data = {'type': 'sliders', 'keys': changed_keys}

        elif atype == 'select_predictors':
            variables = action.get('variables', [])
            if variables:
                predictors_out = variables
                plot_mode_out = 'timeseries'
                tab_out = 'data'
                highlight_data = {'type': 'predictors', 'keys': variables}

        elif atype == 'set_compare_variables':
            variables = action.get('variables', [])
            if variables and 2 <= len(variables) <= 3:
                compare_vars_out = variables[:3]
                plot_mode_out = 'compare'
                tab_out = 'data'
                highlight_data = {'type': 'predictors', 'keys': variables}

        elif atype == 'set_plot_mode':
            mode = action.get('mode', '')
            if mode in ('timeseries', 'compare', 'correlation'):
                plot_mode_out = mode
                tab_out = 'data'

        elif atype == 'reset_scenario':
            if baseline_data:
                reset_vals = {}
                for pred in baseline_data.get('predictors', []):
                    reset_vals[pred['raw_col']] = pred['current_value']
                scenario_vals_out = reset_vals
                tab_out = 'scenario'
                slider_sync_out = (slider_sync or 0) + 1

    # Navigate to /dashboard if on a different page and actions target the dashboard
    if tab_out is not dash.no_update and current_path != '/dashboard':
        path_out = '/dashboard'

    # Build highlight output with timestamp for change detection
    if highlight_data:
        import time
        highlight_data['ts'] = time.time()
        highlight_out = highlight_data

    return (tab_out, scenario_vals_out, predictors_out, plot_mode_out,
            slider_sync_out, compare_vars_out, path_out, highlight_out)

# Sync plot-mode button UI when agent changes the store directly
# (The dashboard's switch_plot_mode callback only fires on button clicks, not store changes)
app.clientside_callback(
    """
    function(mode) {
        if (!mode) return window.dash_clientside.no_update;
        var base = 'plot-mode-btn';
        var active = 'plot-mode-btn plot-mode-active';

        /* Button highlight */
        var ts = document.getElementById('mode-timeseries');
        var cmp = document.getElementById('mode-compare');
        var cor = document.getElementById('mode-correlation');
        if (ts) ts.className = (mode === 'timeseries') ? active : base;
        if (cmp) cmp.className = (mode === 'compare') ? active : base;
        if (cor) cor.className = (mode === 'correlation') ? active : base;

        /* Container visibility */
        var predBox = document.getElementById('predictor-checkboxes-container');
        var cmpBox  = document.getElementById('compare-checkboxes-container');
        var cmpHint = document.getElementById('compare-hint');
        var hide = 'none', show = '';

        if (mode === 'timeseries') {
            if (predBox) predBox.style.display = show;
            if (cmpBox)  cmpBox.style.display  = hide;
            if (cmpHint) cmpHint.style.display  = hide;
        } else if (mode === 'compare') {
            if (predBox) predBox.style.display = hide;
            if (cmpBox)  cmpBox.style.display  = show;
            if (cmpHint) cmpHint.style.display  = show;
        } else if (mode === 'correlation') {
            if (predBox) predBox.style.display = hide;
            if (cmpBox)  cmpBox.style.display  = hide;
            if (cmpHint) cmpHint.style.display  = hide;
        }
        return window.dash_clientside.no_update;
    }
    """,
    Output('plot-mode', 'id'),
    Input('plot-mode', 'data'),
    prevent_initial_call=True
)

# Apply purple highlights when agent executes actions
app.clientside_callback(
    """
    function(highlightData) {
        if (!highlightData || !highlightData.keys) return window.dash_clientside.no_update;

        var HIGHLIGHT_CLASS = 'agent-highlight';
        var HIGHLIGHT_DURATION = 4000;

        /* Clear any existing highlights first */
        document.querySelectorAll('.' + HIGHLIGHT_CLASS).forEach(function(el) {
            el.classList.remove(HIGHLIGHT_CLASS);
        });

        /* Delay to let tab switch + render complete */
        setTimeout(function() {
            var type = highlightData.type;
            var keys = highlightData.keys || [];

            if (type === 'sliders') {
                /* Highlight scenario slider groups by scanning all slider containers */
                var sliderGroups = document.querySelectorAll('.scenario-slider-group');
                sliderGroups.forEach(function(group) {
                    var idEl = group.querySelector('[id]');
                    if (!idEl) return;
                    var idStr = idEl.id || '';
                    for (var i = 0; i < keys.length; i++) {
                        if (idStr.indexOf(keys[i]) !== -1 && idStr.indexOf('scenario') !== -1) {
                            group.classList.add(HIGHLIGHT_CLASS);
                            break;
                        }
                    }
                });
            }

            else if (type === 'predictors') {
                /* Highlight predictor checkbox chips by scanning items */
                var items = document.querySelectorAll('.predictor-checkbox-item');
                items.forEach(function(item) {
                    var idEl = item.querySelector('[id]');
                    if (!idEl) return;
                    var idStr = idEl.id || '';
                    for (var i = 0; i < keys.length; i++) {
                        if (idStr.indexOf(keys[i]) !== -1) {
                            item.classList.add(HIGHLIGHT_CLASS);
                            break;
                        }
                    }
                });
            }

            else if (type === 'model') {
                /* Switch sub-tab if requested */
                if (highlightData.sub_tab === 'specifications') {
                    var specBtn = document.getElementById('model-sub-specifications');
                    if (specBtn) specBtn.click();
                } else if (highlightData.sub_tab === 'predictions') {
                    var predBtn = document.getElementById('model-sub-predictions');
                    if (predBtn) predBtn.click();
                }

                /* Wait for sub-tab switch animation */
                setTimeout(function() {
                    /* Search info-pills by their label text */
                    var pills = document.querySelectorAll('.info-pill');
                    pills.forEach(function(pill) {
                        var label = pill.querySelector('.info-pill-label');
                        if (!label) return;
                        var labelText = label.textContent.trim().toLowerCase();
                        for (var i = 0; i < keys.length; i++) {
                            if (labelText === keys[i].toLowerCase() ||
                                labelText.indexOf(keys[i].toLowerCase()) !== -1) {
                                pill.classList.add(HIGHLIGHT_CLASS);
                                break;
                            }
                        }
                    });

                    /* Also search model cards for section-level highlights */
                    var cards = document.querySelectorAll('.model-card');
                    cards.forEach(function(card) {
                        var title = card.querySelector('.card-title');
                        if (!title) return;
                        var titleText = title.textContent.trim().toLowerCase();
                        for (var i = 0; i < keys.length; i++) {
                            var k = keys[i].toLowerCase();
                            if (k === 'forecast' && titleText.indexOf('forecast') !== -1) {
                                card.classList.add(HIGHLIGHT_CLASS); break;
                            }
                            if (k === 'contributions' && titleText.indexOf('driving') !== -1) {
                                card.classList.add(HIGHLIGHT_CLASS); break;
                            }
                            if (k === 'diagnostics' && titleText.indexOf('diagnostic') !== -1) {
                                card.classList.add(HIGHLIGHT_CLASS); break;
                            }
                            if (k === 'specification' && titleText.indexOf('specification') !== -1) {
                                card.classList.add(HIGHLIGHT_CLASS); break;
                            }
                        }
                    });

                    /* Scroll to first highlighted element */
                    var first = document.querySelector('.' + HIGHLIGHT_CLASS);
                    if (first) {
                        first.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    }
                }, 400);
            }

            /* Auto-remove highlights after duration */
            setTimeout(function() {
                document.querySelectorAll('.' + HIGHLIGHT_CLASS).forEach(function(el) {
                    el.classList.add('agent-highlight-fade');
                    setTimeout(function() {
                        el.classList.remove(HIGHLIGHT_CLASS, 'agent-highlight-fade');
                    }, 500);
                });
            }, HIGHLIGHT_DURATION);

            /* Scroll to first highlighted element (for non-model types) */
            if (type !== 'model') {
                setTimeout(function() {
                    var first = document.querySelector('.' + HIGHLIGHT_CLASS);
                    if (first) first.scrollIntoView({ behavior: 'smooth', block: 'center' });
                }, 200);
            }
        }, 600);

        return window.dash_clientside.no_update;
    }
    """,
    Output('agent-highlight-store', 'id'),
    Input('agent-highlight-store', 'data'),
    prevent_initial_call=True
)

# Toggle chat panel open/closed
app.clientside_callback(
    """
    function(toggleClicks, closeClicks) {
        const panel = document.getElementById('chat-panel');
        const fab = document.getElementById('chat-toggle-btn');
        if (!panel) return window.dash_clientside.no_update;

        const isOpen = panel.classList.contains('chat-panel-open');
        if (isOpen) {
            panel.classList.remove('chat-panel-open');
            if (fab) fab.classList.remove('chat-fab-hidden');
        } else {
            panel.classList.add('chat-panel-open');
            if (fab) fab.classList.add('chat-fab-hidden');
            setTimeout(() => {
                const input = document.getElementById('chat-input');
                if (input) input.focus();
            }, 300);
        }
        return window.dash_clientside.no_update;
    }
    """,
    Output('chat-panel', 'id'),
    Input('chat-toggle-btn', 'n_clicks'),
    Input('chat-close-btn', 'n_clicks'),
    prevent_initial_call=True
)

# Auto-scroll + typewriter animation on new messages
app.clientside_callback(
    """
    function(children) {
        setTimeout(() => {
            const el = document.getElementById('chat-messages');
            if (!el) return;

            /* Clean up optimistic DOM elements — React has reconciled with server children */
            el.querySelectorAll('[data-optimistic]').forEach(n => n.remove());
            const loadEl = document.getElementById('chat-loading-indicator');
            if (loadEl) loadEl.remove();

            el.scrollTop = el.scrollHeight;

            const bubbles = el.querySelectorAll('.chat-typewriter:not(.chat-tw-started)');
            bubbles.forEach(bubble => {
                bubble.classList.add('chat-tw-started');
                const fullText = bubble.getAttribute('data-fulltext');
                if (!fullText) return;

                const words = fullText.split(/( +)/);
                let idx = 0;
                bubble.textContent = '';

                const iv = setInterval(() => {
                    if (idx < words.length) {
                        bubble.textContent += words[idx];
                        idx++;
                        el.scrollTop = el.scrollHeight;
                    } else {
                        clearInterval(iv);
                        bubble.classList.add('chat-tw-done');
                    }
                }, 30);
            });
        }, 60);
        return window.dash_clientside.no_update;
    }
    """,
    Output('chat-send-btn', 'id'),
    Input('chat-messages', 'children'),
    prevent_initial_call=True
)

# Instant loading state — shows user bubble + typing dots before server responds
app.clientside_callback(
    """
    function(sendClicks, nSubmit, inputValue) {
        if (!inputValue || !inputValue.trim()) return window.dash_clientside.no_update;

        const messages = document.getElementById('chat-messages');
        if (!messages) return window.dash_clientside.no_update;

        /* Remove any existing loading indicator from a prior request */
        const oldLoad = document.getElementById('chat-loading-indicator');
        if (oldLoad) oldLoad.remove();

        /* Show user message optimistically (marked so we can remove before React reconciles) */
        const userDiv = document.createElement('div');
        userDiv.className = 'chat-message chat-message-user';
        userDiv.setAttribute('data-optimistic', 'true');
        const bubble = document.createElement('div');
        bubble.className = 'chat-bubble chat-bubble-user';
        bubble.textContent = inputValue.trim();
        userDiv.appendChild(bubble);
        messages.appendChild(userDiv);

        /* Show loading dots */
        const loadDiv = document.createElement('div');
        loadDiv.className = 'chat-message chat-message-ai';
        loadDiv.id = 'chat-loading-indicator';
        loadDiv.innerHTML = '<div class="chat-bubble chat-bubble-ai"><div class="chat-loading-dots"><span></span><span></span><span></span></div></div>';
        messages.appendChild(loadDiv);

        messages.scrollTop = messages.scrollHeight;

        const input = document.getElementById('chat-input');
        if (input) input.value = '';

        return window.dash_clientside.no_update;
    }
    """,
    Output('chat-loading-trigger', 'children'),
    Input('chat-send-btn', 'n_clicks'),
    Input('chat-input', 'n_submit'),
    State('chat-input', 'value'),
    prevent_initial_call=True
)


# ═══════════════════════════════════════════
#   Global AI Chatbot — Server-side Handler
# ═══════════════════════════════════════════

GOOGLE_API_KEY = os.environ.get('GOOGLE_API_KEY')
if not GOOGLE_API_KEY:
    print("WARNING: GOOGLE_API_KEY not set — AI chat will be unavailable.")

_genai_client = None
_genai_client_lock = threading.Lock()


def _build_chat_context(fetched_data, selected_predictors, predictor_options, plot_mode, compare_vars,
                        prediction_data=None, scenario_data=None, active_tab=None,
                        scenario_current_vals=None):
    """Build comprehensive text summary of all dashboard state for the AI chatbot."""
    sections = []

    # ── Current page / tab context ──
    if active_tab:
        tab_desc = {'data': 'Data Tab (time series, variables, correlations)',
                    'model': 'Model Tab (forecasts, feature contributions, diagnostics)',
                    'scenario': 'Scenario Tab (what-if analysis with slider-driven sensitivity)'}
        sections.append(f"=== USER CONTEXT ===\nActive tab: {tab_desc.get(active_tab, active_tab)}")

    # ── Data tab context ──
    if fetched_data:
        df = pd.DataFrame(fetched_data)
        df['Date'] = pd.to_datetime(df['Date'])
        df = df.sort_values('Date')

        label_map = {opt['value']: opt['label'] for opt in (predictor_options or [])}
        numeric_cols = [c for c in df.columns if c != 'Date' and df[c].dtype in ['float64', 'int64', 'float32']]

        lines = ["=== DATASET OVERVIEW ==="]
        lines.append(f"Date range: {df['Date'].min().strftime('%Y-%m')} to {df['Date'].max().strftime('%Y-%m')}")
        lines.append(f"Data points: {len(df)} monthly observations")
        lines.append(f"Active plot mode: {plot_mode or 'timeseries'}")

        if plot_mode == 'compare' and compare_vars:
            cmp_names = [label_map.get(v, v) for v in compare_vars]
            if len(compare_vars) == 2:
                lines.append(f"Compare mode: 2D plot — X={cmp_names[0]} (col: {compare_vars[0]}), Y={cmp_names[1]} (col: {compare_vars[1]})")
            elif len(compare_vars) >= 3:
                lines.append(f"Compare mode: 3D surface — X={cmp_names[0]} (col: {compare_vars[0]}), Y={cmp_names[1]} (col: {compare_vars[1]}), Z={cmp_names[2]} (col: {compare_vars[2]})")
        if selected_predictors:
            sel_info = [f"{label_map.get(v, v)} (col: {v})" for v in selected_predictors]
            lines.append(f"Variables on time series chart: {', '.join(sel_info)}")

        lines.append(f"\n=== AVAILABLE VARIABLES ===")
        lines.append("Column name → Friendly label (use column names in actions):")
        for col in numeric_cols:
            friendly = label_map.get(col, col)
            lines.append(f"  {col} → {friendly}")

        lines.append(f"\n=== ALL VARIABLES — LATEST VALUES & TRENDS ===")
        for col in numeric_cols:
            s = df[col].dropna()
            if s.empty:
                continue
            friendly = label_map.get(col, col)
            n = len(s)
            # Compute summary stats in one vectorized pass (was 4 separate scans).
            s_min = s.min()
            s_max = s.max()
            latest = s.iloc[-1]
            parts = [f"• {friendly} ({col}): latest={latest:.4f}"]
            parts.append(f"min={s_min:.4f}, max={s_max:.4f}, mean={s.mean():.4f}, std={s.std():.4f}")

            trend_parts = []
            if n >= 2:
                prev = s.iloc[-2]
                pct_m = ((latest - prev) / abs(prev)) * 100 if prev != 0 else 0
                trend_parts.append(f"1M: {pct_m:+.2f}%")
            if n >= 3:
                prev = s.iloc[-3]
                pct_3m = ((latest - prev) / abs(prev)) * 100 if prev != 0 else 0
                trend_parts.append(f"3M: {pct_3m:+.2f}%")
            if n >= 6:
                prev = s.iloc[-6]
                pct_6m = ((latest - prev) / abs(prev)) * 100 if prev != 0 else 0
                trend_parts.append(f"6M: {pct_6m:+.2f}%")
            if n >= 12:
                prev = s.iloc[-12]
                yoy = ((latest - prev) / abs(prev)) * 100 if prev != 0 else 0
                trend_parts.append(f"12M: {yoy:+.2f}%")
            if trend_parts:
                parts.append(f"Changes: {', '.join(trend_parts)}")

            # Current position within historical range (reuse min/max from above).
            range_span = s_max - s_min
            if range_span > 0:
                percentile = (latest - s_min) / range_span * 100
                parts.append(f"Historical percentile: {percentile:.0f}%")

            lines.append("  ".join(parts))

        lines.append(f"\n=== KEY CORRELATIONS ===")
        if 'ZAR_USD' in numeric_cols and len(numeric_cols) > 1:
            corr = df[numeric_cols].corr(min_periods=12)
            zar_corr = corr['ZAR_USD'].drop('ZAR_USD').dropna().sort_values(key=abs, ascending=False)
            lines.append("Correlations with ZAR/USD (ranked by |r|):")
            for var, r in zar_corr.items():
                friendly = label_map.get(var, var)
                direction = "positive" if r > 0 else "negative"
                strength = "strong" if abs(r) > 0.7 else "moderate" if abs(r) > 0.4 else "weak"
                econ = ""
                if 'VIX' in var:
                    econ = " — higher VIX = risk-off, capital flees EM → weaker ZAR"
                elif 'GOLD' in var:
                    econ = " — gold rises in risk-off; ZAR is a gold exporter"
                elif 'EPU' in var:
                    econ = " — US policy uncertainty spills over to EM risk premia"
                elif 'WUIZAF' in var:
                    econ = " — domestic uncertainty raises SA risk premium"
                elif 'BOND' in var and 'USA' in var:
                    econ = " — higher US yields attract capital away from EM"
                elif 'BOND' in var and 'SA' in var:
                    econ = " — SA bond yield reflects risk premium + SARB policy"
                lines.append(f"  • {friendly}: r={r:.3f} ({strength} {direction}){econ}")

            # Cross-correlations between key pairs (not just ZAR)
            key_pairs = [('VIX', 'GOLD_PRICE'), ('VIX', 'EPU(USA)'),
                         ('10_YEAR_BOND_RATES(USA)', '10_YEAR_BOND_RATES(SA)')]
            cross_lines = []
            for a, b in key_pairs:
                if a in corr.columns and b in corr.columns:
                    r = corr.loc[a, b]
                    cross_lines.append(f"  • {label_map.get(a, a)} ↔ {label_map.get(b, b)}: r={r:.3f}")
            if cross_lines:
                lines.append("\nNotable cross-correlations:")
                lines.extend(cross_lines)

        sections.append("\n".join(lines))

    # ── Model tab context (predictions, fair value, contributions, metrics) ──
    if prediction_data:
        result = prediction_data.get('raw_result') if isinstance(prediction_data, dict) else None
        if result:
            m = []
            m.append("=== MODEL PREDICTIONS ===")
            m.append(f"Model: HuberRegressor (error-correction framework)")
            m.append(f"Current spot rate: R {result['last_zar_usd']:.4f} (as of {result['last_date']})")
            m.append(f"Point estimate (1M ahead): R {result['predicted_level']:.4f} ({result['predicted_change_pct']:+.2f}%)")

            direction = result['direction']
            if direction == 'weaken':
                dir_text = "ZAR weakening (rate going up = more ZAR per USD)"
            elif direction == 'strengthen':
                dir_text = "ZAR strengthening (rate going down = fewer ZAR per USD)"
            else:
                dir_text = "stable (negligible change expected)"
            m.append(f"Direction: {dir_text}")

            if result.get('fair_value'):
                fv = result['fair_value']
                mis_pct = result.get('fair_value_misalignment_pct', 0)
                signal = result.get('fair_value_signal', 'unknown')
                m.append(f"Fair value (long-run equilibrium): R {fv:.4f}")
                m.append(f"Misalignment: spot is {abs(mis_pct):.2f}% {'above' if mis_pct < 0 else 'below'} fair value → {signal}")
                if signal == 'undervalued':
                    m.append("  Interpretation: ZAR is currently stronger than fundamentals suggest; model expects weakening toward fair value.")
                elif signal == 'overvalued':
                    m.append("  Interpretation: ZAR is currently weaker than fundamentals suggest; model expects strengthening toward fair value.")

            forecasts = result.get('forecasts', {})
            if forecasts:
                m.append("\nMulti-horizon forecasts:")
                for key in ['1m', '3m', '6m']:
                    if key in forecasts:
                        f = forecasts[key]
                        pt = f.get('point_estimate', f.get('fair_value', 0))
                        fv = f.get('fair_value', 0)
                        gap = pt - fv
                        change_from_spot = ((pt - result['last_zar_usd']) / result['last_zar_usd']) * 100
                        m.append(f"  {key}: Point R {pt:.4f} ({change_from_spot:+.2f}% vs spot), Fair Value R {fv:.4f} (gap {gap:+.4f})")
                        m.append(f"       Reason: {f['reason']}")

            # Feature contributions with economic interpretation
            contribs = result.get('contributions', [])
            if contribs:
                m.append("\nFeature contributions to 1M prediction (sorted by |impact|):")
                m.append("(Positive contribution → pushes ZAR/USD rate UP = weakens ZAR)")
                m.append("(Negative contribution → pushes ZAR/USD rate DOWN = strengthens ZAR)")
                for c in contribs:
                    feat = c.get('feature', '')
                    contrib_val = c.get('contribution', 0)
                    coef = c.get('coefficient', 0)
                    scaled_val = c.get('scaled_value', 0)
                    unscaled_coef = c.get('unscaled_coefficient', 0)
                    if abs(contrib_val) < 0.0001:
                        continue

                    direction = "weakens ZAR" if contrib_val > 0 else "strengthens ZAR"
                    m.append(f"  • {feat}: {contrib_val:+.4f} ZAR ({direction})")
                    m.append(f"      coefficient={coef:+.4f}, scaled_input={scaled_val:.4f}, unscaled_coef={unscaled_coef:+.6f}")

            # Performance metrics
            metrics = result.get('metrics', {})
            if metrics:
                m.append(f"\nModel performance (out-of-sample test set, {result.get('model_info', {}).get('test_observations', '?')} obs):")
                m.append(f"  MAE: R {metrics.get('mae', 0):.4f} (avg error magnitude)")
                m.append(f"  RMSE: R {metrics.get('rmse', 0):.4f} (penalizes large errors)")
                m.append(f"  R²: {metrics.get('r2', 0):.4f} (variance explained, 1.0 = perfect)")
                theils = metrics.get('theils_u', 0)
                m.append(f"  Theil's U: {theils:.4f} ({'better than naive' if theils < 1 else 'worse than naive random walk'})")
                m.append(f"  Directional accuracy: {metrics.get('directional_accuracy', 0):.1f}% (correct up/down calls)")
                m.append(f"  MAPE: {metrics.get('mape', 0):.2f}% (mean absolute percentage error)")

            # Model info
            info = result.get('model_info', {})
            if info:
                m.append(f"\nModel specification:")
                m.append(f"  Type: HuberRegressor with ℓ₂ penalty (robust to outliers)")
                m.append(f"  Alpha (ℓ₂ regularization): {info.get('alpha', 'N/A')}")
                m.append(f"  Epsilon (Huber threshold): {info.get('epsilon', 'N/A')} — residuals below ε use squared loss, above use linear")
                m.append(f"  Intercept: {info.get('intercept', 'N/A')}")
                m.append(f"  Training: {info.get('training_observations', 'N/A')} obs, Test: {info.get('test_observations', 'N/A')} obs")
                m.append(f"  Date range: {info.get('training_date_range', 'N/A')}")
                m.append(f"  Excluded variables: SA Inflation, US CPI, Brent Oil (non-stationary, cause train-test distribution shift)")

            sections.append("\n".join(m))

    # ── Scenario tab context ──
    if scenario_data:
        baseline = scenario_data if isinstance(scenario_data, dict) else {}
        if baseline.get('predictors'):
            s = ["=== SCENARIO ANALYSIS ==="]
            if baseline.get('base_prediction'):
                s.append(f"Base prediction (all sliders at current values): R {baseline['base_prediction']:.4f}")
            if baseline.get('last_zar_usd'):
                s.append(f"Current spot: R {baseline['last_zar_usd']:.4f}")

            s.append("\nAdjustable predictors:")
            s.append(f"{'Predictor':<32} {'Current':>10} {'Slider Min':>12} {'Slider Max':>12} {'Hist Min':>10} {'Hist Max':>10}")
            s.append("-" * 90)
            for pred in baseline.get('predictors', []):
                name = pred.get('raw_col', '')
                current = pred.get('current_value', 0)
                rng_low = pred.get('range_low', 0)
                rng_high = pred.get('range_high', 0)
                hist_min = pred.get('hist_min', 0)
                hist_max = pred.get('hist_max', 0)
                s.append(f"  {name:<30} {current:>10.2f} {rng_low:>12.2f} {rng_high:>12.2f} {hist_min:>10.2f} {hist_max:>10.2f}")

            # Show current slider modifications if any
            if scenario_current_vals and baseline.get('predictors'):
                modified = []
                for pred in baseline['predictors']:
                    raw_col = pred['raw_col']
                    baseline_val = pred['current_value']
                    slider_val = scenario_current_vals.get(raw_col, baseline_val)
                    if abs(slider_val - baseline_val) > 0.001:
                        pct_change = ((slider_val - baseline_val) / abs(baseline_val)) * 100 if baseline_val != 0 else 0
                        modified.append(f"  {raw_col}: {baseline_val:.2f} → {slider_val:.2f} ({pct_change:+.1f}%)")
                if modified:
                    s.append("\n⚠ ACTIVE SCENARIO MODIFICATIONS (sliders moved from baseline):")
                    s.extend(modified)
                else:
                    s.append("\nSliders are at baseline (no modifications active).")
            else:
                s.append("\nSliders are at baseline (no modifications active).")

            s.append("\nEconomic intuition for scenario predictors:")
            s.append("  VIX ↑ → risk-off globally → capital leaves EM → ZAR weakens")
            s.append("  GOLD_PRICE ↑ → mixed: risk-off signal BUT SA is a gold exporter (improves trade balance)")
            s.append("  EPU(USA) ↑ → US policy uncertainty → risk aversion → EM currencies weaken")
            s.append("  WUIZAF(SA) ↑ → SA-specific uncertainty → higher risk premium → ZAR weakens")
            s.append("  10Y_BOND(USA) ↑ → higher US yields → carry trade unwinds → capital flows to US → ZAR weakens")
            s.append("  10Y_BOND(SA) ↑ → higher SA yields → could attract carry inflows BUT also signals risk/inflation")
            s.append("  Bond spread (SA−US) is a key derived feature: wider spread = higher SA risk premium")

            sections.append("\n".join(s))

    if not sections:
        return "No dashboard data is loaded yet. The user may be on the login or registration page, or data is still loading."

    return "\n\n".join(sections)


AGENT_SYSTEM_PROMPT = (
    "You are an AI agent embedded in a ZAR/USD exchange rate forecasting dashboard built for South African "
    "agribusiness. You can both ANSWER questions AND EXECUTE actions on the dashboard.\n\n"

    "== MODEL KNOWLEDGE ==\n"
    "The core model is a HuberRegressor error-correction framework (robust to outliers, α=7.906, ε=1.1).\n"
    "Equation: Ŝ_{t+1} = β₀ + β₁·S_{t-1} + Σ β_j·x̃_j(t)\n"
    "β₁ ≈ 0.96 so it behaves as a random-walk anchor: next month's rate ≈ this month's rate, with small "
    "corrections from 10 macro signals.\n"
    "11 features (internal column names):\n"
    "  ZAR_USD_lag1 (passthrough), ZAR_USD_logret1, ZAR_USD_change3, ZAR_USD_zscore12,\n"
    "  VIX, VIX_change1, VIX_zscore12, EPU_USA, WUIZAF_SA, bond_spread_change1, GOLD_PRICE_logret1\n"
    "Pipeline: ColumnTransformer (passthrough for lag1, StandardScaler for remaining 10) → HuberRegressor.\n"
    "SA Inflation, US CPI, and Brent Oil are deliberately EXCLUDED (trending non-stationary series that "
    "cause train-test distribution shift).\n"
    "Test R²=0.6157, Theil's U=0.9969, Directional Accuracy=67.65%.\n"
    "Multi-horizon forecasts (1M, 3M, 6M) iterate predictions assuming macro drivers persist.\n\n"

    "== DASHBOARD TABS — DETAILED ==\n\n"

    "--- DATA TAB ---\n"
    "Three mutually exclusive plot modes, each with different variable selection mechanics:\n\n"
    "1. TIME SERIES mode (default):\n"
    "   - All selected variables plotted as normalized (0–100) lines over time on the SAME chart.\n"
    "   - X-axis is always Date. Each variable is min-max scaled so they share a common Y-axis.\n"
    "   - You can select ANY number of variables to overlay together.\n"
    "   - Use this when the user says: 'show me VIX and gold', 'plot ZAR and bond rates together',\n"
    "     'overlay all variables', 'show the time series of X and Y', 'put X and Y on the same chart'.\n"
    "   - Action: select_predictors — sets which variables appear on the shared time axis.\n\n"
    "2. COMPARE mode:\n"
    "   - Plots one variable AGAINST another (X vs Y), NOT over time.\n"
    "   - 2 variables → 2D scatter/line: X-axis is variable 1, Y-axis is variable 2. Shows r correlation.\n"
    "   - 3 variables → 3D surface: X=var1, Y=var2, Z=var3 (interpolated surface).\n"
    "   - Maximum 3 variables. This is a different selection from time series.\n"
    "   - Use this when the user says: 'plot VIX versus gold price', 'scatter X against Y',\n"
    "     'X vs Y', 'relationship between X and Y', '3D surface of X, Y, Z', 'plot X as a function of Y'.\n"
    "   - Action: set_compare_variables — sets the 2 or 3 variables for the compare axes.\n"
    "   - MUST also set plot mode to 'compare'.\n\n"
    "3. CORRELATION mode:\n"
    "   - Displays a heatmap matrix of Pearson correlations (r values) between ALL variables.\n"
    "   - No variable selection needed — it always shows the full matrix.\n"
    "   - Use this when the user says: 'show correlations', 'correlation matrix', 'heatmap',\n"
    "     'which variables are most correlated'.\n"
    "   - Action: set_plot_mode with mode='correlation'. No variable selection needed.\n\n"

    "CRITICAL DISTINCTION:\n"
    "  'Show VIX and gold on the chart' → TIME SERIES: both lines overlaid on a shared date axis.\n"
    "  'Plot VIX versus gold' / 'VIX vs gold' → COMPARE: X-axis=VIX, Y-axis=Gold, shows relationship.\n"
    "  'Correlation between VIX and gold' → Could be COMPARE (2D with r annotation) or just answer the r value from context.\n\n"

    "Available variable column names (use EXACTLY these strings):\n"
    "  ZAR_USD               — ZAR/USD Exchange Rate\n"
    "  VIX                   — CBOE Volatility Index\n"
    "  EPU(USA)              — US Economic Policy Uncertainty Index\n"
    "  WUIZAF(SA)            — SA World Uncertainty Index\n"
    "  GOLD_PRICE            — Gold Price (USD/oz)\n"
    "  10_YEAR_BOND_RATES(SA)  — SA 10-Year Bond Rate\n"
    "  10_YEAR_BOND_RATES(USA) — US 10-Year Treasury Rate\n"
    "  US_CPI                — US Consumer Price Index\n"
    "  SA_INFLATION          — SA Headline CPI Index\n"
    "  BRENT_OIL_PRICE       — Brent Crude Oil Price\n"
    "  USA_CPI               — US CPI Growth Rate\n"
    "  SA_CPI_FRED           — SA CPI Growth Rate (FRED)\n\n"

    "--- MODEL TAB ---\n"
    "Two sub-tabs (switching is automatic, you just navigate here):\n"
    "  Predictions sub-tab: Multi-horizon forecast table (1M/3M/6M point estimates + fair values),\n"
    "    feature contribution bar chart (what's pushing ZAR up/down), forecast summary narrative.\n"
    "  Specifications sub-tab: Model card (HuberRegressor params, α, ε, training/test split),\n"
    "    performance metrics (MAE, RMSE, R², Theil's U, directional accuracy, MAPE),\n"
    "    diagnostic plots (residual distribution, actual vs fitted, feature partial dependence).\n"
    "Use this when the user asks about: forecast, prediction, what the model says, model accuracy,\n"
    "  feature importance, what's driving the rate, diagnostics, residuals, model performance.\n\n"

    "--- SCENARIO TAB ---\n"
    "Slider-driven what-if analysis. Six adjustable macro predictors:\n"
    "  VIX             — Volatility Index (unitless, typically 10–80)\n"
    "  GOLD_PRICE      — Gold Price in USD/oz (typically 1200–2500)\n"
    "  EPU(USA)        — US Economic Policy Uncertainty (unitless, ~50–600)\n"
    "  WUIZAF(SA)      — SA World Uncertainty Index (unitless, ~0–0.5)\n"
    "  10_YEAR_BOND_RATES(USA) — US 10-Year Bond Rate (%, ~1.5–5)\n"
    "  10_YEAR_BOND_RATES(SA)  — SA 10-Year Bond Rate (%, ~7–12)\n\n"
    "When sliders are adjusted, the model re-engineers all derived features (log returns, z-scores,\n"
    "bond spread, etc.) and generates a new prediction. The dashboard shows:\n"
    "  - Base vs Scenario comparison cards (R value, % change)\n"
    "  - Impact waterfall chart (contribution delta per feature)\n"
    "  - Summary table (current vs scenario value per predictor, % change)\n"
    "  - Up to 5 saved scenario snapshots for comparison\n"
    "Use this when the user asks: 'what if VIX goes up', 'impact of higher gold',\n"
    "  'stress test bonds at X%', 'scenario where uncertainty doubles',\n"
    "  'what happens to the Rand if...', 'sensitivity to VIX'.\n\n"

    "== ACTIONS YOU CAN TAKE ==\n"
    "When the user asks you to DO something (show, navigate, adjust, compare, plot, set, change, etc.), "
    "respond with a JSON block containing actions, followed by your explanation.\n"
    "Actions work from ANY page — the agent will auto-navigate to /dashboard if needed.\n"
    "Elements affected by actions get a purple highlight so the user can immediately see what changed.\n\n"
    "Available action types:\n\n"
    "1. navigate_tab — Switch to a tab.\n"
    "   {\"type\": \"navigate_tab\", \"tab\": \"data|model|scenario\"}\n\n"
    "2. set_scenario_sliders — Adjust scenario slider values.\n"
    "   Values can be absolute numbers OR percentage changes from current (\"+10%\", \"-20%\").\n"
    "   IMPORTANT: Every set_scenario_sliders action automatically RESETS all sliders to baseline first,\n"
    "   then applies only the specified changes. This means each scenario request starts clean — you do NOT\n"
    "   need to emit a separate reset_scenario action before setting sliders.\n"
    "   Automatically navigates to Scenario tab. Changed sliders get a purple highlight.\n"
    "   {\"type\": \"set_scenario_sliders\", \"values\": {\"VIX\": \"+10%\", \"GOLD_PRICE\": 2500}}\n\n"
    "3. select_predictors — Select variables for the TIME SERIES chart (overlaid on shared date axis).\n"
    "   Always include ZAR_USD along with the requested variables so the user can see the exchange rate.\n"
    "   Automatically navigates to Data tab and sets plot mode to timeseries. Selected variables get highlighted.\n"
    "   {\"type\": \"select_predictors\", \"variables\": [\"ZAR_USD\", \"VIX\", \"GOLD_PRICE\"]}\n\n"
    "4. set_compare_variables — Select 2 or 3 variables for COMPARE mode (X vs Y, or 3D surface).\n"
    "   Automatically navigates to Data tab and sets plot mode to compare.\n"
    "   2 vars → 2D line (X vs Y with correlation annotation).\n"
    "   3 vars → 3D surface (X, Y → Z interpolated).\n"
    "   {\"type\": \"set_compare_variables\", \"variables\": [\"VIX\", \"GOLD_PRICE\"]}\n\n"
    "5. set_plot_mode — Change the data tab plot mode directly.\n"
    "   {\"type\": \"set_plot_mode\", \"mode\": \"timeseries|compare|correlation\"}\n\n"
    "6. reset_scenario — Reset all scenario sliders to current baseline values.\n"
    "   {\"type\": \"reset_scenario\"}\n\n"
    "7. find_scenario — Find predictor values that would produce a target ZAR/USD level.\n"
    "   Use this when the user asks 'what would it take for ZAR to reach X', 'scenario for R17',\n"
    "   'how could the rate get to X', 'give me a scenario where ZAR/USD is X', etc.\n"
    "   The system runs an optimizer to find plausible predictor adjustments. It automatically\n"
    "   sets the sliders and navigates to the Scenario tab so the user can see the result.\n"
    "   {\"type\": \"find_scenario\", \"target_level\": 17.0}\n\n"
    "8. highlight_model — Navigate to Model tab and highlight specific metrics, sections, or info pills.\n"
    "   Use this when the user asks about specific model performance, metrics, or sections.\n"
    "   sub_tab: 'predictions' or 'specifications' — auto-switches to the correct sub-tab.\n"
    "   targets: array of label strings to highlight. Matches against info-pill labels AND card titles.\n"
    "   Valid pill labels: 'MAE', 'RMSE', 'R²', 'Adjusted R²', 'MAPE', \"Theil's U\", 'Directional Accuracy',\n"
    "     'Type', 'Alpha (α)', 'Epsilon (ε)', 'Intercept (β₀)', 'Scale (σ̂)', 'Features', 'Training / Test',\n"
    "     'Target', 'Spot', 'Fair Value (Now)', '1M Pt / FV', '3M Pt / FV', '6M Pt / FV'.\n"
    "   Valid card-level targets: 'forecast', 'contributions', 'diagnostics', 'specification'.\n"
    "   {\"type\": \"highlight_model\", \"sub_tab\": \"specifications\", \"targets\": [\"MAE\", \"RMSE\", \"R²\"]}\n"
    "   {\"type\": \"highlight_model\", \"sub_tab\": \"predictions\", \"targets\": [\"forecast\"]}\n\n"

    "== RESPONSE FORMAT ==\n"
    "When executing actions, you MUST use this EXACT format:\n"
    "```json\n"
    "{\"actions\": [... array of action objects ...]}\n"
    "```\n"
    "Then on the next line after the closing ```, write your explanation to the user.\n\n"
    "When just answering a question (no action needed), respond with plain text (no JSON block).\n\n"

    "== EXAMPLES ==\n\n"
    "User: \"What happens if VIX increases by 10%?\"\n"
    "```json\n"
    "{\"actions\": [{\"type\": \"set_scenario_sliders\", \"values\": {\"VIX\": \"+10%\"}}]}\n"
    "```\n"
    "I've increased VIX by 10% on the Scenario tab. The waterfall chart now shows the isolated impact "
    "on ZAR/USD — a higher VIX signals risk aversion, typically weakening the Rand as capital flows to "
    "safe-haven assets.\n\n"

    "User: \"Show VIX and gold price on the chart\"\n"
    "```json\n"
    "{\"actions\": [{\"type\": \"select_predictors\", \"variables\": [\"ZAR_USD\", \"VIX\", \"GOLD_PRICE\"]}]}\n"
    "```\n"
    "I've overlaid VIX, Gold Price, and ZAR/USD on the time series chart. All three are normalized to a "
    "0–100 scale so you can compare their movements over the same time period.\n\n"

    "User: \"Plot VIX versus gold price\"\n"
    "```json\n"
    "{\"actions\": [{\"type\": \"set_compare_variables\", \"variables\": [\"VIX\", \"GOLD_PRICE\"]}]}\n"
    "```\n"
    "I've set up a 2D compare chart with VIX on the X-axis and Gold Price on the Y-axis. The correlation "
    "coefficient (r) is annotated on the plot, showing how these two variables relate to each other "
    "independent of time.\n\n"

    "User: \"Show me a 3D surface of VIX, gold, and ZAR\"\n"
    "```json\n"
    "{\"actions\": [{\"type\": \"set_compare_variables\", \"variables\": [\"VIX\", \"GOLD_PRICE\", \"ZAR_USD\"]}]}\n"
    "```\n"
    "I've created a 3D surface plot with VIX on the X-axis, Gold Price on the Y-axis, and ZAR/USD as the "
    "Z-surface. The interpolated surface shows how the exchange rate varies across different VIX and gold "
    "price combinations.\n\n"

    "User: \"Show the correlations\"\n"
    "```json\n"
    "{\"actions\": [{\"type\": \"set_plot_mode\", \"mode\": \"correlation\"}]}\n"
    "```\n"
    "I've switched to the correlation heatmap showing Pearson r values between all variables in the dataset.\n\n"

    "User: \"Show me the model predictions\"\n"
    "```json\n"
    "{\"actions\": [{\"type\": \"highlight_model\", \"sub_tab\": \"predictions\", \"targets\": [\"forecast\"]}]}\n"
    "```\n"
    "I've navigated to the Model tab and highlighted the forecast table. You can see the multi-horizon "
    "point estimates and fair values for 1M, 3M, and 6M horizons.\n\n"

    "User: \"What's the MAE and R² of the model?\"\n"
    "```json\n"
    "{\"actions\": [{\"type\": \"highlight_model\", \"sub_tab\": \"specifications\", \"targets\": [\"MAE\", \"R²\"]}]}\n"
    "```\n"
    "I've highlighted the MAE and R² metrics on the Specifications sub-tab. The out-of-sample MAE is "
    "R X.XXXX and R² is X.XXXX — use the actual values from context.\n\n"

    "User: \"What's driving the forecast?\"\n"
    "```json\n"
    "{\"actions\": [{\"type\": \"highlight_model\", \"sub_tab\": \"predictions\", \"targets\": [\"contributions\"]}]}\n"
    "```\n"
    "I've highlighted the feature contributions chart. It shows which macro signals are pushing ZAR/USD "
    "up (weakening ZAR) or down (strengthening ZAR) relative to the random-walk anchor.\n\n"

    "User: \"Give me a scenario for ZAR/USD to be 17 rand\"\n"
    "```json\n"
    "{\"actions\": [{\"type\": \"find_scenario\", \"target_level\": 17.0}]}\n"
    "```\n"
    "I've run the optimizer to find predictor values that would push ZAR/USD toward R 17.00. "
    "The sliders have been set to the found values on the Scenario tab — check the waterfall chart "
    "to see which drivers contribute most to this move.\n\n"

    "User: \"What would it take for the rand to reach 20?\"\n"
    "```json\n"
    "{\"actions\": [{\"type\": \"find_scenario\", \"target_level\": 20.0}]}\n"
    "```\n"
    "I've searched for a plausible combination of macro conditions that would push ZAR/USD to R 20.00. "
    "The scenario sliders now show the required changes.\n\n"

    "User: \"Stress test: VIX at 40 with gold dropping to 1800\"\n"
    "```json\n"
    "{\"actions\": [{\"type\": \"set_scenario_sliders\", \"values\": {\"VIX\": 40, \"GOLD_PRICE\": 1800}}]}\n"
    "```\n"
    "I've set VIX to 40 and Gold Price to $1,800/oz in the Scenario tab. This simulates a high-volatility "
    "environment with declining gold — check the waterfall chart for how each factor contributes to the "
    "ZAR/USD change.\n\n"

    "User: \"What is the one month ahead forecast?\"\n"
    "```json\n"
    "{\"actions\": [{\"type\": \"highlight_model\", \"sub_tab\": \"predictions\", \"targets\": [\"forecast\", \"1M Pt / FV\"]}]}\n"
    "```\n"
    "I've navigated to the Model tab and highlighted the forecast table. The 1-month ahead point estimate "
    "is R X.XXXX with a fair value of R X.XXXX — use actual numbers from context.\n\n"

    "User: \"How accurate is this model?\"\n"
    "```json\n"
    "{\"actions\": [{\"type\": \"highlight_model\", \"sub_tab\": \"specifications\", \"targets\": [\"MAE\", \"RMSE\", \"R²\", \"Directional Accuracy\"]}]}\n"
    "```\n"
    "I've highlighted the key accuracy metrics. The model achieves an MAE of R X.XXXX, R² of X.XXXX, "
    "and correctly predicts direction X% of the time — use actual values from context.\n\n"

    "User: \"What is the current ZAR/USD rate?\"\n"
    "(no JSON block — just answer using numbers from DASHBOARD STATE)\n\n"

    "== IMPORTANT RULES ==\n"
    "- ALWAYS emit actions when the user asks to DO something (show, navigate, adjust, set, compare, plot, "
    "change, reset, stress test, etc.)\n"
    "- ALWAYS emit a highlight_model action when the user ASKS ABOUT any model output, even as a question.\n"
    "  This includes: forecast, prediction, 1-month/3-month/6-month ahead, fair value, point estimate,\n"
    "  what the model says, MAE, RMSE, R², accuracy, Theil's U, feature contributions, what's driving,\n"
    "  diagnostics, residuals, model performance, model specification, intercept, coefficients.\n"
    "  You MUST navigate to the model tab AND highlight the relevant section — do NOT just answer in text.\n"
    "  Example: 'what is the 1 month forecast?' → highlight_model with sub_tab=predictions, targets=[forecast]\n"
    "  Example: 'how accurate is the model?' → highlight_model with sub_tab=specifications, targets=[MAE, R², Directional Accuracy]\n"
    "  Example: 'what's pushing the rate up?' → highlight_model with sub_tab=predictions, targets=[contributions]\n"
    "  After emitting the action, ALSO answer the question with specific numbers from DASHBOARD STATE.\n"
    "- When the user specifies a TARGET ZAR/USD level ('scenario for R17', 'what would it take to reach 20',\n"
    "  'how could the rate get to X', 'conditions for ZAR at X'), use find_scenario with that level.\n"
    "  This is different from set_scenario_sliders where the user specifies predictor values directly.\n"
    "- 'show X and Y' / 'overlay X and Y' → select_predictors (time series, shared date axis)\n"
    "- 'X vs Y' / 'X versus Y' / 'X against Y' / 'scatter X and Y' → set_compare_variables (compare mode)\n"
    "- 'correlation' / 'heatmap' / 'correlations' → set_plot_mode correlation\n"
    "- Use percentage changes (\"+10%\") when the user says increase/decrease by a percentage\n"
    "- Use absolute values when the user specifies an exact number (e.g. 'VIX at 40')\n"
    "- For select_predictors, ALWAYS include ZAR_USD so the user sees the exchange rate alongside\n"
    "- For set_compare_variables, use exactly 2 or 3 variables (max 3)\n"
    "- You can chain multiple actions (e.g. navigate + set sliders)\n"
    "- After setting scenario sliders, explain the economic reasoning behind the expected impact\n"
    "- Use specific numbers from the DASHBOARD STATE when discussing results\n"
    "- When discussing correlations, cite the actual r values if they are in the context\n"
    "- Keep explanations concise (2-4 sentences) but informative and economically grounded\n"
    "- You ONLY handle economics/ZAR/USD/dashboard topics. Politely decline anything else.\n"
)

CHAT_SYSTEM_PROMPT = (
    "You are an economics assistant embedded in a ZAR/USD exchange rate forecasting dashboard built for "
    "South African agribusiness.\n\n"

    "== MODEL KNOWLEDGE ==\n"
    "The core model is a HuberRegressor error-correction framework (robust to outliers, α=7.906, ε=1.1).\n"
    "Equation: Ŝ_{t+1} = β₀ + β₁·S_{t-1} + Σ β_j·x̃_j(t). β₁ ≈ 0.96 so it behaves as a random-walk "
    "anchor with small corrections from 10 macro signals.\n"
    "11 features: ZAR_USD_lag1 (passthrough), ZAR_USD_logret1, ZAR_USD_change3, ZAR_USD_zscore12, "
    "VIX, VIX_change1, VIX_zscore12, EPU_USA, WUIZAF_SA, bond_spread_change1, GOLD_PRICE_logret1.\n"
    "SA Inflation, US CPI, and Brent Oil deliberately EXCLUDED (non-stationary, cause train-test shift).\n"
    "Test R²=0.6157, Theil's U=0.9969, Directional Accuracy=67.65%.\n"
    "Multi-horizon (1M/3M/6M) forecasts iterate predictions assuming macro drivers persist.\n\n"

    "== DASHBOARD TABS ==\n"
    "1. DATA TAB: Three plot modes — Time Series (normalized 0–100 overlaid lines over date), "
    "Compare (2 vars → 2D X-vs-Y scatter with r, 3 vars → 3D surface), Correlation (full heatmap).\n"
    "   Variables: ZAR_USD, VIX, EPU(USA), WUIZAF(SA), GOLD_PRICE, 10_YEAR_BOND_RATES(SA), "
    "10_YEAR_BOND_RATES(USA), US_CPI, SA_INFLATION, BRENT_OIL_PRICE, USA_CPI, SA_CPI_FRED.\n"
    "2. MODEL TAB: Predictions sub-tab (multi-horizon forecast table, feature contributions bar chart, "
    "forecast summary). Specifications sub-tab (model card with HuberRegressor params, performance "
    "metrics: MAE, RMSE, R², Theil's U, directional accuracy, MAPE, diagnostic plots).\n"
    "3. SCENARIO TAB: Slider-driven what-if analysis. 6 adjustable predictors: VIX, GOLD_PRICE, "
    "EPU(USA), WUIZAF(SA), 10_YEAR_BOND_RATES(USA), 10_YEAR_BOND_RATES(SA). Shows base vs scenario "
    "comparison, impact waterfall chart, summary table, and up to 5 saved scenario snapshots.\n\n"

    "== INSTRUCTIONS ==\n"
    "You have full access to the dashboard state below. Use specific numbers from the context.\n"
    "You ONLY answer questions about: the data in the dashboard, ZAR/USD exchange rate dynamics, "
    "macroeconomic indicators, South African and US economics, the model's predictions and methodology, "
    "scenario analysis, correlations between variables, and how these factors relate to the Rand.\n"
    "If the user asks about anything unrelated, politely decline and redirect.\n"
    "When discussing correlations, cite actual r values from the data.\n"
    "Tip the user that they can switch to Agent mode (toggle in the chat header) if they want you to "
    "execute dashboard actions like adjusting sliders, switching tabs, or setting up charts.\n"
    "Keep answers concise (2-4 sentences) unless the user asks for detail."
)


def _parse_agent_response(response_text):
    """Parse agent response to extract actions JSON and display message."""
    import json
    import re

    actions = []
    message = response_text

    # Look for ```json ... ``` blocks
    json_match = re.search(r'```json\s*\n?(.*?)\n?\s*```', response_text, re.DOTALL)
    if json_match:
        try:
            parsed = json.loads(json_match.group(1))
            actions = parsed.get('actions', [])
        except (json.JSONDecodeError, AttributeError):
            pass
        # Message is everything outside the JSON block (prefer after, fall back to before)
        after = response_text[json_match.end():].strip()
        before = response_text[:json_match.start()].strip()
        message = after or before or "Done."

    return actions, message


@callback(
    Output('chat-messages', 'children'),
    Output('chat-input', 'value'),
    Output('chat-history', 'data'),
    Output('agent-action-store', 'data'),
    Input('chat-send-btn', 'n_clicks'),
    Input('chat-input', 'n_submit'),
    State('chat-input', 'value'),
    State('chat-messages', 'children'),
    State('chat-history', 'data'),
    State('fetched-data', 'data'),
    State('selected-predictors', 'data'),
    State('predictor-dropdown-options-store', 'data'),
    State('plot-mode', 'data'),
    State('selected-compare-vars', 'data'),
    State('model-prediction-data', 'data'),
    State('scenario-baseline-data', 'data'),
    State('dashboard-tab', 'data'),
    State('agent-mode-store', 'data'),
    State('scenario-current-values', 'data'),
    prevent_initial_call=True
)
def handle_chat_send(send_clicks, n_submit, user_msg, current_messages, chat_history,
                     fetched_data, selected_predictors, predictor_options, plot_mode, compare_vars,
                     prediction_data, scenario_data, active_tab, agent_mode, scenario_current_vals):
    import traceback

    if not user_msg or not user_msg.strip():
        return dash.no_update, dash.no_update, dash.no_update, dash.no_update

    user_msg = user_msg.strip()
    current_messages = current_messages or []
    chat_history = chat_history or []

    # Cap chat history to prevent unbounded growth in session storage
    if len(chat_history) > 40:
        chat_history = chat_history[-40:]

    current_messages.append(
        html.Div(className='chat-message chat-message-user', children=[
            html.Div(user_msg, className='chat-bubble chat-bubble-user')
        ])
    )

    full_context = _build_chat_context(
        fetched_data, selected_predictors, predictor_options, plot_mode, compare_vars,
        prediction_data=prediction_data, scenario_data=scenario_data, active_tab=active_tab,
        scenario_current_vals=scenario_current_vals,
    )

    chat_history.append({'role': 'user', 'parts': [user_msg]})

    agent_actions = dash.no_update

    try:
        from google import genai
        from google.genai import types

        global _genai_client
        if _genai_client is None:
            with _genai_client_lock:
                if _genai_client is None:  # double-checked under lock
                    if not GOOGLE_API_KEY:
                        raise ValueError("AI chat is unavailable — GOOGLE_API_KEY not configured.")
                    _genai_client = genai.Client(api_key=GOOGLE_API_KEY)
        client = _genai_client

        if agent_mode:
            system_instruction = AGENT_SYSTEM_PROMPT + f"\n\nDASHBOARD STATE:\n{full_context}"
        else:
            system_instruction = CHAT_SYSTEM_PROMPT + f"\n\nDASHBOARD STATE:\n{full_context}"

        contents = []
        for msg in chat_history:
            contents.append(types.Content(
                role=msg['role'],
                parts=[types.Part.from_text(text=msg['parts'][0])]
            ))

        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                max_output_tokens=2048,
                temperature=0.7,
            )
        )

        ai_text = (response.text or "I couldn't generate a response. Please try again.").strip()

        # In agent mode, parse out actions
        if agent_mode:
            actions, display_msg = _parse_agent_response(ai_text)

            # Handle find_scenario: run solver server-side, replace with set_scenario_sliders
            resolved_actions = []
            for a in actions:
                if a.get('type') == 'find_scenario':
                    try:
                        from logic.model import find_scenario_for_target
                        target = float(a.get('target_level', 0))
                        result = find_scenario_for_target(target)
                        # Replace with set_scenario_sliders using the found values
                        resolved_actions.append({
                            'type': 'set_scenario_sliders',
                            'values': {k: round(v, 4) for k, v in result['scenario_values'].items()},
                        })
                        # Enrich the display message with solver results
                        achieved = result['achieved_level']
                        gap = result['gap']
                        changes = result.get('changes', [])
                        solver_summary = f"Target: R {target:.2f} | Achieved: R {achieved:.4f}"
                        if gap > 0.01:
                            solver_summary += f" (gap: R {gap:.4f})"
                        if not result['feasible']:
                            solver_summary += " — this target may be outside the model's reachable range."
                        if changes:
                            parts = []
                            for ch in changes:
                                parts.append(f"{ch['predictor']}: {ch['current']:.2f} → {ch['scenario']:.2f} ({ch['change_pct']:+.1f}%)")
                            solver_summary += "\nKey changes: " + ", ".join(parts)
                        # Prepend solver results to display message
                        display_msg = solver_summary + "\n\n" + display_msg
                    except Exception as solver_err:
                        print(f"[Solver Error] {solver_err}")
                        display_msg = f"Could not find a scenario for that target: {solver_err}"
                else:
                    resolved_actions.append(a)
            actions = resolved_actions

            if actions:
                import time
                agent_actions = {'actions': actions, 'ts': time.time()}

                # Build action summary chips for the chat
                action_chips = []
                for a in actions:
                    atype = a.get('type', '')
                    if atype == 'navigate_tab':
                        action_chips.append(f"Navigate → {a.get('tab', '').title()} Tab")
                    elif atype == 'set_scenario_sliders':
                        vals = a.get('values', {})
                        parts = [f"{k}: {v}" for k, v in vals.items()]
                        action_chips.append(f"Set sliders: {', '.join(parts)}")
                    elif atype == 'select_predictors':
                        action_chips.append(f"Time series: {', '.join(a.get('variables', []))}")
                    elif atype == 'set_compare_variables':
                        vs = a.get('variables', [])
                        if len(vs) == 3:
                            action_chips.append(f"3D surface: {vs[0]} × {vs[1]} → {vs[2]}")
                        else:
                            action_chips.append(f"Compare: {' vs '.join(vs)}")
                    elif atype == 'set_plot_mode':
                        mode_labels = {'timeseries': 'Time Series', 'compare': 'Compare', 'correlation': 'Correlation Heatmap'}
                        action_chips.append(f"Plot mode → {mode_labels.get(a.get('mode', ''), a.get('mode', ''))}")
                    elif atype == 'reset_scenario':
                        action_chips.append("Reset scenario")
                    elif atype == 'highlight_model':
                        targets = a.get('targets', [])
                        sub = a.get('sub_tab', 'predictions').title()
                        action_chips.append(f"Model → {sub}: {', '.join(targets)}")
                    elif atype == 'find_scenario':
                        target = a.get('target_level', '?')
                        action_chips.append(f"Find scenario → R {target}")

                # Show action chips + message
                current_messages.append(
                    html.Div(className='chat-message chat-message-agent-action', children=[
                        html.Div(className='chat-agent-actions', children=[
                            html.Div(className='chat-action-chip', children=[
                                html.Span('⚡', className='chat-action-icon'),
                                html.Span(chip),
                            ]) for chip in action_chips
                        ])
                    ])
                )
                ai_text = display_msg
            else:
                # No actions parsed, keep full text
                pass

    except Exception as e:
        print(f"[Chatbot Error] {type(e).__name__}: {e}")
        traceback.print_exc()
        ai_text = f"Sorry, I couldn't process that request. ({type(e).__name__}: {e})"

    chat_history.append({'role': 'model', 'parts': [ai_text]})

    current_messages.append(
        html.Div(className='chat-message chat-message-ai', children=[
            html.Div('', className='chat-bubble chat-bubble-ai chat-typewriter',
                     **{'data-fulltext': ai_text})
        ])
    )

    return current_messages, '', chat_history, agent_actions


server = app.server
if __name__ == '__main__':
    app.run(debug=True, port=int(os.environ.get("PORT", 10000)))