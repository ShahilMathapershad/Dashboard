import dash
from dash import Dash, html, dcc, Input, Output, State, callback, callback_context, DiskcacheManager
import dash_bootstrap_components as dbc
from flask import Flask
from dotenv import load_dotenv
import os
import sys
import diskcache
import multiprocess

# On macOS, spawn is default but we want to be explicit and avoid crashes
# We use multiprocess because DiskcacheManager uses it if available
try:
    if multiprocess.get_start_method(allow_none=True) is None:
        multiprocess.set_start_method('spawn')
except RuntimeError:
    # Already set
    pass

# DiskCache for background callbacks
cache = diskcache.Cache("./.cache")
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
    suppress_callback_exceptions=True,
    background_callback_manager=background_callback_manager
)

app.layout = html.Div(id='theme-main-container', children=[
    dcc.Location(id='url', refresh=True),
    dcc.Store(id='user-session', storage_type='session'),
    dcc.Store(id='theme-store', storage_type='local', data='dark'),
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


# Auth guard: separate callbacks for clearer logic and to avoid circular loops
@callback(
    Output('url', 'pathname', allow_duplicate=True),
    Input('user-session', 'data'),
    State('url', 'pathname'),
    prevent_initial_call='initial_duplicate'
)
def redirect_on_session_change(session_data, current_path):
    logged_in = session_data and session_data.get('username')
    print(f"DEBUG: Session change. Path: {current_path}, Logged In: {logged_in}")
    if logged_in:
        if current_path in ['/', '/registration', None]:
            print("DEBUG: Logged in, redirecting to /dashboard")
            return '/dashboard'
    else:
        if current_path not in ['/', '/registration', None]:
            print("DEBUG: Logged out, redirecting to /")
            return '/'
    return dash.no_update


@callback(
    Output('url', 'pathname', allow_duplicate=True),
    Input('url', 'pathname'),
    State('user-session', 'data'),
    prevent_initial_call='initial_duplicate'
)
def redirect_on_path_change(current_path, session_data):
    logged_in = session_data and session_data.get('username')
    print(f"DEBUG: Path change. Path: {current_path}, Logged In: {logged_in}")
    if not logged_in:
        if current_path not in ['/', '/registration', None]:
            print("DEBUG: Unauthenticated access, redirecting to /")
            return '/'
    else:
        if current_path in ['/', '/registration']:
            print("DEBUG: Authenticated user on login page, redirecting to /dashboard")
            return '/dashboard'
    return dash.no_update


if __name__ == '__main__':
    app.run(debug=True)