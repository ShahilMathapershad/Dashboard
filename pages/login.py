import dash
from dash import html, dcc, callback, Input, Output, State
from supabase import create_client
import os

dash.register_page(__name__, path='/')

# Initialize Supabase client using environment variables
url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")
supabase = create_client(url, key) if url and key else None


def layout():
    return html.Div([
        html.Div([
            html.Div([
                # Helper for your transparent logo
                html.Img(src=dash.get_asset_url('logo.svg'), className='logo-img'),
            ], style={'display': 'flex', 'justifyContent': 'center', 'marginBottom': '2.5rem'}),
            html.H2("Welcome Back", className='login-title'),
            html.P("Enter your credentials to access the ZAR/USD dashboard",
                   style={'textAlign': 'center', 'color': 'var(--text-secondary)', 'marginBottom': '2rem',
                          'fontSize': '0.95rem'}),
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

        if not supabase:
            return None, "Database connection not configured in .env", dash.no_update

        try:
            # Query Supabase for the specific user
            response = supabase.table("users").select("*").eq("username", username).eq("password", password).execute()

            if response.data:
                return {'username': username}, "", '/dashboard'
            else:
                return None, "Invalid credentials. Please try again.", dash.no_update
        except Exception as e:
            return None, f"System error: {str(e)}", dash.no_update

    return None, "", dash.no_update