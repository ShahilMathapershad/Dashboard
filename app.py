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
        {'src': '/assets/interactions.js', 'type': 'module'}
    ],
    suppress_callback_exceptions=True,
    background_callback_manager=background_callback_manager,
    meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1"}]
)

app.layout = html.Div(id='theme-main-container', children=[
    dcc.Store(id='user-session', storage_type='session'),
    dcc.Store(id='theme-store', storage_type='local', data='dark'),
    
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

    dash.page_container,
    html.Button(
        "🌙",
        id='theme-switch-button',
        className='theme-switch-btn',
        n_clicks=0
    )
])


@callback(
    Output('theme-main-container', 'className'),
    Output('theme-switch-button', 'children'),
    Output('theme-store', 'data'),
    Input('theme-switch-button', 'n_clicks'),
    State('theme-store', 'data')
)
def update_theme(n_clicks, stored_theme):
    ctx = callback_context
    theme = stored_theme or 'dark'
    
    if ctx.triggered:
        trigger_id = ctx.triggered[0]['prop_id'].split('.')[0]
        if trigger_id == 'theme-switch-button' and n_clicks > 0:
            theme = 'light' if stored_theme == 'dark' else 'dark'

    icon = "☀️" if theme == 'light' else "🌙"
    class_name = 'light-theme' if theme == 'light' else ''
    return class_name, icon, theme


# Clientside callback to sync theme to body class for portals (like dropdown menus)
app.clientside_callback(
    """
    function(theme) {
        if (theme === 'light') {
            document.body.classList.add('light-theme');
        } else {
            document.body.classList.remove('light-theme');
        }
        return window.dash_clientside.no_update;
    }
    """,
    Output('theme-switch-button', 'id'), # Dummy output
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

server = app.server
if __name__ == '__main__':
    # Render ignores this block, but it's good practice
    app.run(debug=True, port=int(os.environ.get("PORT", 10000)))