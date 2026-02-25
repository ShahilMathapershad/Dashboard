import dash
from dash import Dash, html, dcc
import dash_bootstrap_components as dbc
from flask import Flask
import os
from dotenv import load_dotenv

load_dotenv()

server = Flask(__name__)
app = Dash(
    __name__,
    server=server,
    use_pages=True,
    external_stylesheets=[dbc.themes.BOOTSTRAP],
    suppress_callback_exceptions=True
)

app.layout = html.Div([
    dcc.Location(id='url', refresh=False),
    dcc.Store(id='user-session', storage_type='session'),
    dash.page_container
])

if __name__ == '__main__':
    app.run(debug=True)
