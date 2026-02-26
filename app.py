import dash
from dash import Dash, html, dcc, Input, Output, State, callback, callback_context
import dash_bootstrap_components as dbc
from flask import Flask
from dotenv import load_dotenv
import os
import sys

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
    suppress_callback_exceptions=True
)

app.layout = html.Div(id='theme-main-container', children=[
    dcc.Location(id='url', refresh=False),
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
    Input('theme-store', 'data')
)
def update_theme(n_clicks, stored_theme):
    ctx = callback_context
    if not ctx.triggered:
        theme = stored_theme or 'dark'
    else:
        trigger_id = ctx.triggered[0]['prop_id'].split('.')[0]
        if trigger_id == 'theme-switch-button' and n_clicks > 0:
            theme = 'light' if stored_theme == 'dark' else 'dark'
        else:
            theme = stored_theme or 'dark'

    icon = "☀️" if theme == 'light' else "🌙"
    class_name = 'light-theme' if theme == 'light' else ''
    return class_name, icon, theme


if __name__ == '__main__':
    app.run(debug=True)