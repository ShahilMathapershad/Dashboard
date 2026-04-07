import dash
from dash import Dash, html, dcc, Input, Output, State, callback, callback_context, DiskcacheManager
import dash_bootstrap_components as dbc
from flask import Flask
from dotenv import load_dotenv
import os
import sys
import diskcache
import multiprocess
import threading
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

server = Flask(__name__)
app = Dash(
    __name__,
    server=server,
    use_pages=True,
    external_stylesheets=[dbc.themes.BOOTSTRAP],
    external_scripts=[
        {'src': '/assets/interactions.js', 'type': 'module'},
        {'src': '/assets/three-scenes.js'},
    ],
    suppress_callback_exceptions=True,
    background_callback_manager=background_callback_manager,
    meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1"}]
)

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

    dash.page_container,

    # ── Global AI Chat Panel (available on all pages) ──
    html.Div(id='chat-panel', className='chat-panel', children=[
        html.Div(className='chat-header', children=[
            html.Div(className='chat-header-left', children=[
                html.Span('✦', className='chat-header-icon'),
                html.Span('AI Assistant', className='chat-header-title'),
            ]),
            html.Button('✕', id='chat-close-btn', className='chat-close-btn', n_clicks=0),
        ]),
        html.Div(id='chat-messages', className='chat-messages', children=[
            html.Div(className='chat-message chat-message-ai', children=[
                html.Div("Ask me about ZAR/USD dynamics, macroeconomic indicators, or the data in this dashboard.",
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

# Simplified clientside callback - let JavaScript handle most resize logic
app.clientside_callback(
    """
    function(modelResultsStyle) {
        // Minimal trigger - let the main JavaScript handler do the work
        if (modelResultsStyle && modelResultsStyle.display !== 'none') {
            setTimeout(() => {
                window.dispatchEvent(new Event('plotlyResize'));
            }, 100);
        }
        return window.dash_clientside.no_update;
    }
    """,
    Output('model-results-container', 'id'), # Dummy output
    Input('model-results-container', 'style'),
)

# Simplified clientside callback for data visualization
app.clientside_callback(
    """
    function(dataVizStyle) {
        // Minimal trigger - let the main JavaScript handler do the work
        if (dataVizStyle && dataVizStyle.display !== 'none') {
            setTimeout(() => {
                window.dispatchEvent(new Event('plotlyResize'));
            }, 100);
        }
        return window.dash_clientside.no_update;
    }
    """,
    Output('zar-graph', 'id'), # Dummy output
    Input('visualization-container', 'style'),
)


# Global prerender trigger - starts fetching data as soon as the app is accessed
@callback(
    Output('fetch-trigger', 'data', allow_duplicate=True),
    Output('model-prediction-trigger', 'data', allow_duplicate=True),
    Output('scenario-trigger', 'data', allow_duplicate=True),
    Input('_pages_location', 'pathname'),
    State('fetch-trigger', 'data'),
    State('model-prediction-trigger', 'data'),
    State('scenario-trigger', 'data'),
    prevent_initial_call=True
)
def global_prerender_trigger(pathname, f_trig, m_trig, s_trig):
    if pathname == '/dashboard' and (f_trig or 0) == 0:
        return 1, dash.no_update, dash.no_update
    return dash.no_update, dash.no_update, dash.no_update


# Sequential background callback chaining - reduces peak memory spikes on Render (512MB)
@callback(
    Output('model-prediction-trigger', 'data', allow_duplicate=True),
    Input('fetched-data', 'data'),
    State('model-prediction-trigger', 'data'),
    prevent_initial_call=True
)
def chain_model_prediction(fetched_data, current_trigger):
    if fetched_data and (current_trigger or 0) == 0:
        return 1
    return dash.no_update


@callback(
    Output('scenario-trigger', 'data', allow_duplicate=True),
    Input('model-prediction-data', 'data'),
    State('scenario-trigger', 'data'),
    prevent_initial_call=True
)
def chain_scenario_baseline(model_data, current_trigger):
    if model_data and (current_trigger or 0) == 0:
        return 1
    return dash.no_update

# Simplized clientside callback for figure changes
app.clientside_callback(
    """
    function(figure) {
        // Minimal trigger for figure changes
        if (figure && figure.data && figure.data.length > 0) {
            setTimeout(() => {
                window.dispatchEvent(new Event('plotlyResize'));
            }, 50);
        }
        return window.dash_clientside.no_update;
    }
    """,
    Output('prediction-value', 'id'), # Dummy output
    Input('model-history-chart', 'figure'),
)


# Global auth and navigation guard
@callback(
    Output('_pages_location', 'pathname'),
    Input('_pages_location', 'pathname'),
    Input('user-session', 'data'),
    prevent_initial_call=True
)
def auth_redirection(current_path, session_data):
    # Determine if user is logged in
    logged_in = session_data and session_data.get('username')
    
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

# ═══════════════════════════════════════════
#   Global AI Chatbot — Clientside Callbacks
# ═══════════════════════════════════════════

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
            el.scrollTop = el.scrollHeight;

            const bubbles = el.querySelectorAll('.chat-typewriter:not(.chat-tw-started)');
            bubbles.forEach(bubble => {
                bubble.classList.add('chat-tw-started');
                const fullText = bubble.getAttribute('data-fulltext');
                if (!fullText) return;

                const words = fullText.split(/( +)/);
                let idx = 0;
                bubble.textContent = '';

                const interval = setInterval(() => {
                    if (idx < words.length) {
                        bubble.textContent += words[idx];
                        idx++;
                        el.scrollTop = el.scrollHeight;
                    } else {
                        clearInterval(interval);
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

        const userDiv = document.createElement('div');
        userDiv.className = 'chat-message chat-message-user';
        const bubble = document.createElement('div');
        bubble.className = 'chat-bubble chat-bubble-user';
        bubble.textContent = inputValue.trim();
        userDiv.appendChild(bubble);
        messages.appendChild(userDiv);

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


def _build_chat_context(fetched_data, selected_predictors, predictor_options, plot_mode, compare_vars):
    """Build text summary of dashboard data for the AI chatbot."""
    if not fetched_data:
        return "No dashboard data is loaded yet. The user may be on a non-data page."

    import numpy as np

    df = pd.DataFrame(fetched_data)
    df['Date'] = pd.to_datetime(df['Date'])
    df = df.sort_values('Date')

    label_map = {opt['value']: opt['label'] for opt in (predictor_options or [])}
    numeric_cols = [c for c in df.columns if c != 'Date' and df[c].dtype in ['float64', 'int64', 'float32']]

    lines = []
    lines.append(f"=== DATASET OVERVIEW ===")
    lines.append(f"Date range: {df['Date'].min().strftime('%Y-%m')} to {df['Date'].max().strftime('%Y-%m')}")
    lines.append(f"Data points: {len(df)} monthly observations")
    lines.append(f"Active plot mode: {plot_mode or 'timeseries'}")

    if plot_mode == 'compare' and compare_vars:
        cmp_names = [label_map.get(v, v) for v in compare_vars]
        if len(compare_vars) == 2:
            lines.append(f"Compare mode: 2D line plot — X={cmp_names[0]}, Y={cmp_names[1]}")
        elif len(compare_vars) >= 3:
            lines.append(f"Compare mode: 3D surface — X={cmp_names[0]}, Y={cmp_names[1]}, Z(surface)={cmp_names[2]}")
    if selected_predictors:
        sel_names = [label_map.get(v, v) for v in selected_predictors]
        lines.append(f"Variables on time series chart: {', '.join(sel_names)}")

    lines.append(f"\n=== ALL VARIABLES (summary stats) ===")
    for col in numeric_cols:
        s = df[col].dropna()
        if s.empty:
            continue
        friendly = label_map.get(col, col)
        latest = s.iloc[-1]
        lines.append(f"• {friendly}: latest={latest:.4f}, min={s.min():.4f}, max={s.max():.4f}, mean={s.mean():.4f}")
        if len(s) >= 2:
            pct_m = ((s.iloc[-1] - s.iloc[-2]) / abs(s.iloc[-2])) * 100 if s.iloc[-2] != 0 else 0
            lines.append(f"    MoM: {pct_m:+.2f}%")
        if len(s) >= 12:
            yoy = ((s.iloc[-1] - s.iloc[-12]) / abs(s.iloc[-12])) * 100 if s.iloc[-12] != 0 else 0
            lines.append(f"    YoY: {yoy:+.2f}%")

    lines.append(f"\n=== KEY CORRELATIONS ===")
    if 'ZAR_USD' in numeric_cols and len(numeric_cols) > 1:
        corr = df[numeric_cols].corr()
        zar_corr = corr['ZAR_USD'].drop('ZAR_USD').sort_values(key=abs, ascending=False)
        lines.append("Correlations with ZAR/USD (ranked by strength):")
        for var, r in zar_corr.items():
            friendly = label_map.get(var, var)
            direction = "positive" if r > 0 else "negative"
            strength = "strong" if abs(r) > 0.7 else "moderate" if abs(r) > 0.4 else "weak"
            lines.append(f"  • {friendly}: r={r:.3f} ({strength} {direction})")

    return "\n".join(lines)


@callback(
    Output('chat-messages', 'children'),
    Output('chat-input', 'value'),
    Output('chat-history', 'data'),
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
    prevent_initial_call=True
)
def handle_chat_send(send_clicks, n_submit, user_msg, current_messages, chat_history,
                     fetched_data, selected_predictors, predictor_options, plot_mode, compare_vars):
    import traceback

    if not user_msg or not user_msg.strip():
        return dash.no_update, dash.no_update, dash.no_update

    user_msg = user_msg.strip()
    current_messages = current_messages or []
    chat_history = chat_history or []

    current_messages.append(
        html.Div(className='chat-message chat-message-user', children=[
            html.Div(user_msg, className='chat-bubble chat-bubble-user')
        ])
    )

    plot_context = _build_chat_context(fetched_data, selected_predictors, predictor_options, plot_mode, compare_vars)

    chat_history.append({'role': 'user', 'parts': [user_msg]})

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=GOOGLE_API_KEY)

        system_instruction = (
            "You are an economics assistant embedded in a ZAR/USD exchange rate dashboard. "
            "You have full access to the dataset context below, including all variables, their latest values, "
            "month-over-month and year-over-year changes, and the full correlation matrix between all variables. "
            "You ONLY answer questions about: the data in the dashboard, ZAR/USD exchange rate dynamics, "
            "macroeconomic indicators (interest rates, inflation, oil prices, gold, VIX, economic policy uncertainty), "
            "South African and US economics, correlations between variables, and how these factors relate to the Rand. "
            "If the user asks about anything unrelated, politely decline and redirect them to data or economics questions. "
            "When discussing correlations, cite the actual r values from the data. "
            "Keep answers concise (2-4 sentences) unless the user asks for detail. "
            "The dashboard has three plot modes: Time Series (normalized 0-100), Compare (2D scatter or 3D), "
            "and Correlation (heatmap). Reference these when relevant.\n\n"
            f"DASHBOARD DATA CONTEXT:\n{plot_context}"
        )

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

    return current_messages, '', chat_history


server = app.server
if __name__ == '__main__':
    app.run(debug=True, port=int(os.environ.get("PORT", 10000)))