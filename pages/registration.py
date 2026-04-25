import dash
from dash import html, dcc, callback, Input, Output, State

dash.register_page(__name__, path='/registration')


def layout():
    return html.Div(className='login-container', children=[
        # 3D Three.js Canvas background (shared with login)
        html.Div(id='three-canvas-landing'),

        html.Div(className='bg-trendline-svg'),

        # Registration card (stage-active so it's visible immediately)
        html.Div(className='login-stage stage-active', children=[
            html.Div(className='login-card-glass', children=[
                html.Div([
                    html.Img(src=dash.get_asset_url('logo_light.svg'), className='logo-img logo-light'),
                    html.Img(src=dash.get_asset_url('logo_dark.svg'), className='logo-img logo-dark'),
                ], style={'display': 'flex', 'justifyContent': 'center', 'marginBottom': '2.5rem'}),

                html.H2("Create Account", className='login-title'),

                html.Form(id='register-form', children=[
                    dcc.Input(id='reg-username', type='text', placeholder='Username',
                              className='form-input', autoComplete='username',
                              name='username'),
                    dcc.Input(id='reg-password', type='password', placeholder='Password',
                              className='form-input', autoComplete='new-password',
                              name='password'),

                    html.Button('Register', id='register-button', n_clicks=0,
                                className='login-button', type='button'),
                ], style={'margin': '0'}),

                html.Div(id='register-output', className='login-error'),

                html.Div([
                    html.Span("Already have an account? ",
                              style={'color': 'var(--text-2)', 'fontSize': '0.9rem'}),
                    html.A("Sign in", href="/",
                           style={'color': 'var(--accent)', 'fontSize': '0.9rem', 'textDecoration': 'none'})
                ], style={'textAlign': 'center', 'marginTop': '1.5rem'}),

                html.Div("Authorized access for economicsweekly.co.za stakeholders.",
                         className='login-card-footer'),
            ])
        ])
    ])


import logging
from logic.supabase_client import get_supabase

logger = logging.getLogger("Registration")


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

        username = username.strip()

        if len(username) < 3:
            return "Username must be at least 3 characters.", {}

        if len(password) < 6:
            return "Password must be at least 6 characters.", {}

        supabase = get_supabase()
        if not supabase:
            return "Unable to connect. Please try again later.", {}

        try:
            response = supabase.table('users').select("username").eq('username', str(username)).execute()

            if response.data:
                return "Username already exists. Please choose another one.", {}

            supabase.table('users').insert({
                "username": str(username),
                "password": str(password)
            }).execute()

            logger.info("Registration successful for '%s'", username)
            return "Registration successful! You can now log in.", {
                'color': '#4ade80',
                'background': 'rgba(34, 197, 94, 0.1)',
                'border': '1px solid rgba(34, 197, 94, 0.2)'
            }
        except Exception as e:
            logger.error("Registration error: %s", e)
            return "Unable to complete registration. Please try again later.", {}

    return "", {}