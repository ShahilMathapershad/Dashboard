import dash
from dash import html, dcc, callback, Input, Output, State
from logic.supabase_client import supabase

dash.register_page(__name__, path='/')


def layout():
    return html.Div(className='login-container', children=[
        dcc.Store(id='login-stage-store', data=1),
        
        # Background Trendline Container (SVG injected via JS due to dash.html limitations)
        html.Div(id='bg-trendline-container', className='bg-trendline-svg'),

        # Particles
        html.Div(className='particles-container', children=[
            html.Div('GDP', className='particle-node', style={'top': '25%', 'left': '15%', 'animationDelay': '0s'}),
            html.Div('VIX', className='particle-node', style={'top': '65%', 'left': '80%', 'animationDelay': '-5s'}),
            html.Div('Gold', className='particle-node', style={'top': '20%', 'left': '70%', 'animationDelay': '-10s'}),
        ]),

        # Stage 1: Landing Page
        html.Div(id='landing-stage', className='landing-stage', children=[
            html.H1("Understand the Forces Driving the ZAR/USD Exchange Rate", className='landing-headline'),
            html.P(
                "A transparent, data-driven forecasting tool built for South African agribusiness to navigate ZAR/USD exchange rate volatility with clarity",
                className='landing-subheadline'
            ),
            
            html.Div(className='feature-cards', children=[
                html.Div(className='feature-card', children=[
                    html.Div("Macroeconomic Drivers", className='feature-title'),
                    html.Div("Highlighting how variables like commodity prices and interest rate differentials impact the ZAR.", className='feature-desc'),
                ]),
                html.Div(className='feature-card', children=[
                    html.Div("Scenario Modeling", className='feature-title'),
                    html.Div("Explaining the ability to test hypothetical changes in underlying factors.", className='feature-desc'),
                ]),
                html.Div(className='feature-card', children=[
                    html.Div("Automated Precision", className='feature-title'),
                    html.Div("Showcasing monthly updates synced with FRED and Statistics South Africa.", className='feature-desc'),
                ]),
            ]),
            
            html.Button('Get Started', id='get-started-button', n_clicks=0, className='btn-get-started'),
        ]),

        # Stage 2: Login Page
        html.Div(id='login-stage', className='login-stage', children=[
            html.Div(className='login-card-glass', children=[
                html.Div([
                    html.Img(src=dash.get_asset_url('logo_light.svg'), className='logo-img logo-light'),
                    html.Img(src=dash.get_asset_url('logo_dark.svg'), className='logo-img logo-dark'),
                ], style={'display': 'flex', 'justifyContent': 'center', 'marginBottom': '2.5rem'}),
                
                html.H2("Welcome Back", className='login-title'),
                
                dcc.Input(id='username', type='text', placeholder='Username', className='form-input', autoComplete='off'),
                dcc.Input(id='password', type='password', placeholder='Password', className='form-input'),
                
                html.Button('Sign In', id='login-button', n_clicks=0, className='login-button data-pulse-btn'),
                
                html.Div(id='login-output', className='login-error'),
                
                html.Div([
                    html.Span("Don't have an account? ", style={'color': 'var(--text-secondary)', 'fontSize': '0.9rem'}),
                    html.A("Register here", href="/registration",
                           style={'color': 'var(--accent)', 'fontSize': '0.9rem', 'textDecoration': 'none'})
                ], style={'textAlign': 'center', 'marginTop': '1.5rem'}),
                
                html.Div("Authorized access for economicsweekly.co.za stakeholders.", className='login-card-footer')
            ])
        ])
    ])


@callback(
    Output('login-stage-store', 'data'),
    Input('get-started-button', 'n_clicks'),
    prevent_initial_call=True
)
def transition_to_login(n_clicks):
    if n_clicks > 0:
        return 2
    return 1


@callback(
    Output('landing-stage', 'className'),
    Output('login-stage', 'className'),
    Input('login-stage-store', 'data')
)
def update_stage_classes(stage):
    if stage == 2:
        return 'landing-stage stage-hidden', 'login-stage stage-active'
    return 'landing-stage stage-active', 'login-stage stage-hidden'


@callback(
    Output('user-session', 'data', allow_duplicate=True),
    Output('login-output', 'children'),
    Input('login-button', 'n_clicks'),
    State('username', 'value'),
    State('password', 'value'),
    prevent_initial_call=True
)
def login_auth(n_clicks, username, password):
    print(f"DEBUG: login_auth triggered with n_clicks={n_clicks}")
    if n_clicks > 0:
        if not username or not password:
            return None, "Please enter both username and password"

        if not supabase:
            return None, "System error: Supabase connection not established."

        try:
            # Check credentials in Supabase
            print(f"--- Login: Checking credentials for '{username}' ---")
            response = supabase.table('users').select("username").eq('username', str(username)).eq('password', str(password)).execute()

            if response.data:
                print(f"--- Login: Successful for '{username}' ---")
                return {'username': username}, ""
            else:
                print(f"--- Login: Failed for '{username}' ---")
                return None, "Invalid credentials. Please try again."
        except Exception as e:
            print(f"--- Login Error: {str(e)} ---")
            return None, f"System error: {str(e)}"

    return dash.no_update, dash.no_update