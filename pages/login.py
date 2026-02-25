import dash
from dash import html, dcc, callback, Input, Output, State
import pandas as pd
import os

dash.register_page(__name__, path='/')


def layout():
    return html.Div([
        html.Div([
            html.Div([
                html.Img(src=dash.get_asset_url('logo.svg'), className='logo-img'),
            ], style={'display': 'flex', 'justifyContent': 'center', 'marginBottom': '2.5rem'}),
            html.H2("Welcome Back", className='login-title'),
            dcc.Input(id='username', type='text', placeholder='Username', className='form-input', autoComplete='off'),
            dcc.Input(id='password', type='password', placeholder='Password', className='form-input'),
            html.Button('Sign In', id='login-button', n_clicks=0, className='login-button'),
            html.Div(id='login-output', className='login-error'),
            html.Div([
                html.Span("Don't have an account? ", style={'color': 'var(--text-secondary)', 'fontSize': '0.9rem'}),
                html.A("Register here", href="/registration",
                       style={'color': 'var(--accent)', 'fontSize': '0.9rem', 'textDecoration': 'none'})
            ], style={'textAlign': 'center', 'marginTop': '1.5rem'})
        ], className='login-card')
    ], className='login-container')


@callback(
    Output('user-session', 'data'),
    Output('login-output', 'children'),
    Output('url', 'pathname'),
    Input('login-button', 'n_clicks'),
    State('username', 'value'),
    State('password', 'value'),
    prevent_initial_call=True
)
def login_auth(n_clicks, username, password):
    if n_clicks > 0:
        if not username or not password:
            return None, "Please enter both username and password", dash.no_update

        try:
            users_df = pd.read_csv('data/users.csv')
            user = users_df[(users_df['username'] == str(username)) & (users_df['password'] == str(password))]

            if not user.empty:
                return {'username': username}, "", '/dashboard'
            else:
                return None, "Invalid credentials. Please try again.", dash.no_update
        except Exception as e:
            return None, f"System error: {str(e)}", dash.no_update

    return None, "", dash.no_update