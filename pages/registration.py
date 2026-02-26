import dash
from dash import html, dcc, callback, Input, Output, State

dash.register_page(__name__, path='/registration')


def layout():
    return html.Div([
        html.Div([
            html.Div([
                html.Img(src=dash.get_asset_url('logo.svg'), className='logo-img'),
            ], style={'display': 'flex', 'justifyContent': 'center', 'marginBottom': '2.5rem'}),
            html.H2("Create Account", className='login-title'),
            dcc.Input(id='reg-username', type='text', placeholder='Username', className='form-input',
                      autoComplete='off'),
            dcc.Input(id='reg-password', type='password', placeholder='Password', className='form-input'),
            html.Button('Register', id='register-button', n_clicks=0, className='login-button'),
            html.Div(id='register-output', className='login-error'),
            html.Div([
                html.A("Back to Sign In", href="/",
                       style={'color': 'var(--accent)', 'fontSize': '0.9rem', 'textDecoration': 'none'})
            ], style={'textAlign': 'center', 'marginTop': '1.5rem'})
        ], className='login-card')
    ], className='login-container')


from logic.supabase_client import supabase

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

        if not supabase:
            return "System error: Supabase connection not established.", {}

        try:
            # Check if username exists
            print(f"--- Registration: Checking if username '{username}' exists ---")
            response = supabase.table('users').select("username").eq('username', str(username)).execute()
            
            if response.data:
                print(f"--- Registration: Username '{username}' already exists ---")
                return "Username already exists. Please choose another one.", {}

            # Insert new user
            print(f"--- Registration: Inserting new user '{username}' ---")
            supabase.table('users').insert({
                "username": str(username), 
                "password": str(password)
            }).execute()

            print(f"--- Registration: Successfully inserted user '{username}' ---")
            return "Registration successful! You can now log in.", {
                'color': '#4ade80',
                'background': 'rgba(34, 197, 94, 0.1)',
                'border': '1px solid rgba(34, 197, 94, 0.2)'
            }
        except Exception as e:
            print(f"--- Registration Error: {str(e)} ---")
            return f"System error: {str(e)}", {}

    return "", {}