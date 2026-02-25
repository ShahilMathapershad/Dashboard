import dash
from dash import html, dcc, callback, Input, Output, State
import pandas as pd
import os

dash.register_page(__name__, path='/registration')

def layout():
    return html.Div([
        html.Div([
            html.Div([
                html.Img(src=dash.get_asset_url('logo.svg'), className='logo-img'),
            ], style={'display': 'flex', 'justifyContent': 'center', 'marginBottom': '2.5rem'}),
            html.H2("Create Account", className='login-title'),
            html.P("Enter a username and password to register", 
                   style={'textAlign': 'center', 'color': 'var(--text-secondary)', 'marginBottom': '2rem', 'fontSize': '0.95rem'}),
            dcc.Input(id='reg-username', type='text', placeholder='Username', className='form-input', autoComplete='off'),
            dcc.Input(id='reg-password', type='password', placeholder='Password', className='form-input'),
            html.Button('Register', id='register-button', n_clicks=0, className='login-button'),
            html.Div(id='register-output', className='login-error'),
            html.Div([
                html.A("Back to Sign In", href="/", style={'color': 'var(--accent)', 'fontSize': '0.9rem', 'textDecoration': 'none'})
            ], style={'textAlign': 'center', 'marginTop': '1.5rem'})
        ], className='login-card')
    ], className='login-container')

@callback(
    Output('register-output', 'children'),
    Output('register-output', 'style'),
    Input('register-button', 'n_clicks'),
    State('reg-username', 'value'),
    State('reg-password', 'value'),
    prevent_initial_call=True
)
def register_user(n_clicks, username, password):
    if n_clicks > 0:
        if not username or not password:
            return "Please enter both username and password", {}
        
        try:
            if not os.path.exists('data/users.csv'):
                os.makedirs('data', exist_ok=True)
                df = pd.DataFrame(columns=['username', 'password'])
                df.to_csv('data/users.csv', index=False)

            users_df = pd.read_csv('data/users.csv')
            
            # Check if username already exists
            if username in users_df['username'].values.astype(str):
                return "Username already exists. Please choose another one.", {}
            
            # Create new user dataframe row
            new_user = pd.DataFrame([[username, password]], columns=['username', 'password'])
            
            # Append new user and save back to csv
            users_df = pd.concat([users_df, new_user], ignore_index=True)
            users_df.to_csv('data/users.csv', index=False)
            
            return "Registration successful! You can now log in.", {
                'color': '#4ade80', 
                'background': 'rgba(34, 197, 94, 0.1)', 
                'border': '1px solid rgba(34, 197, 94, 0.2)'
            }
            
        except Exception as e:
            return f"System error: {str(e)}", {}
            
    return "", {}
