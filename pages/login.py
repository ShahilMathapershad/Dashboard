import dash
from dash import html, dcc, callback, Input, Output, State
from logic.supabase_client import supabase

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

        if not supabase:
            return None, "System error: Supabase connection not established.", dash.no_update

        try:
            # Check credentials in Supabase
            print(f"--- Login: Checking credentials for '{username}' ---")
            response = supabase.table('users').select("username").eq('username', str(username)).eq('password', str(password)).execute()

            if response.data:
                print(f"--- Login: Successful for '{username}' ---")
                return {'username': username}, "", '/dashboard'
            else:
                print(f"--- Login: Failed for '{username}' ---")
                return None, "Invalid credentials. Please try again.", dash.no_update
        except Exception as e:
            print(f"--- Login Error: {str(e)} ---")
            return None, f"System error: {str(e)}", dash.no_update

    return None, "", dash.no_update