import dash
import logging
import time
from collections import defaultdict
from dash import html, dcc, callback, Input, Output, State
from logic.supabase_client import get_supabase

logger = logging.getLogger("Login")

dash.register_page(__name__, path='/')

# ── Rate limiting (per-username, in-memory) ──
_login_attempts = defaultdict(list)
_MAX_ATTEMPTS = 5
_WINDOW_SECONDS = 300  # 5 minutes


def _check_rate_limit(username):
    """Return True if the user is allowed to try again. Purges expired/empty entries."""
    now = time.time()
    if username in _login_attempts:
        fresh = [t for t in _login_attempts[username] if now - t < _WINDOW_SECONDS]
        if fresh:
            _login_attempts[username] = fresh
        else:
            del _login_attempts[username]
    return len(_login_attempts.get(username, [])) < _MAX_ATTEMPTS


def _record_failed_attempt(username):
    _login_attempts[username].append(time.time())


def _clear_attempts(username):
    _login_attempts.pop(username, None)


def layout():
    return html.Div(className='login-container', children=[
        dcc.Store(id='login-stage-store', data=1),

        # 3D Three.js Canvas — renders particle globe + flowing mesh
        html.Div(id='three-canvas-landing'),

        # Background Trendline Container (SVG injected via JS — subtle fallback behind 3D)
        html.Div(id='bg-trendline-container', className='bg-trendline-svg'),

        # Particles — subtle floating labels behind the 3D scene
        html.Div(className='particles-container', children=[
            html.Div('GDP', className='particle-node', style={'top': '25%', 'left': '15%', 'animationDelay': '0s'}),
            html.Div('VIX', className='particle-node', style={'top': '65%', 'left': '80%', 'animationDelay': '-5s'}),
            html.Div('Gold', className='particle-node', style={'top': '20%', 'left': '70%', 'animationDelay': '-10s'}),
            html.Div('CPI', className='particle-node', style={'top': '75%', 'left': '20%', 'animationDelay': '-3s'}),
            html.Div('LIBOR', className='particle-node', style={'top': '40%', 'left': '88%', 'animationDelay': '-8s'}),
            html.Div('PMI', className='particle-node', style={'top': '10%', 'left': '45%', 'animationDelay': '-6s'}),
            html.Div('USD', className='particle-node', style={'top': '85%', 'left': '55%', 'animationDelay': '-12s'}),
        ]),

        # Stage 1: Landing Page
        html.Div(id='landing-stage', className='landing-stage', children=[
            html.H1([
                "Understand the Forces Driving the ",
                html.Span("ZAR/USD", className='landing-headline-accent'),
                " Exchange Rate",
            ], className='landing-headline'),
            html.P(
                "A transparent, data-driven forecasting tool built for South African agribusiness to navigate ZAR/USD exchange rate volatility with clarity",
                className='landing-subheadline'
            ),

            # Glowing divider
            html.Div(className='landing-divider'),

            # Stat pills
            html.Div(className='stat-pills', children=[
                html.Div(className='stat-pill', children=[
                    html.Span('11', className='stat-pill-number'),
                    html.Span('Features', className='stat-pill-label'),
                ]),
                html.Div(className='stat-pill', children=[
                    html.Span('3', className='stat-pill-number'),
                    html.Span('Horizons', className='stat-pill-label'),
                ]),
                html.Div(className='stat-pill', children=[
                    html.Span('Monthly', className='stat-pill-number'),
                    html.Span('Data Refresh', className='stat-pill-label'),
                ]),
                html.Div(className='stat-pill', children=[
                    html.Span('HuberRegressor', className='stat-pill-number'),
                    html.Span('Algorithm', className='stat-pill-label'),
                ]),
            ]),

            html.Div(className='feature-cards', children=[
                html.Div(className='feature-card', children=[
                    html.Div("◈", className='feature-icon-wrap'),
                    html.Div("Macroeconomic Drivers", className='feature-title'),
                    html.Div("Track how commodity prices, interest rate spreads, and volatility indices shape the Rand in real time.", className='feature-desc'),
                ]),
                html.Div(className='feature-card', children=[
                    html.Div("⬡", className='feature-icon-wrap'),
                    html.Div("Scenario Modeling", className='feature-title'),
                    html.Div("Adjust macro variables and instantly see how the ZAR/USD would respond under different conditions.", className='feature-desc'),
                ]),
                html.Div(className='feature-card', children=[
                    html.Div("◉", className='feature-icon-wrap'),
                    html.Div("Automated Precision", className='feature-title'),
                    html.Div("Data refreshes monthly from FRED and Stats SA, feeding a robust ML model with 11 engineered features.", className='feature-desc'),
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

                html.Form(id='login-form', children=[
                    dcc.Input(id='username', type='text', placeholder='Username',
                              className='form-input', autoComplete='username',
                              name='username'),
                    dcc.Input(id='password', type='password', placeholder='Password',
                              className='form-input', autoComplete='current-password',
                              name='password'),

                    html.Button('Sign In', id='login-button', n_clicks=0,
                                className='login-button data-pulse-btn',
                                type='button'),
                ], style={'margin': '0'}),

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
    if n_clicks > 0:
        if not username or not password:
            return None, "Please enter both username and password"

        username = username.strip()

        # Rate limiting: only blocks if too many recent FAILURES.
        if not _check_rate_limit(username):
            return None, "Too many login attempts. Please try again in a few minutes."

        supabase = get_supabase()
        if not supabase:
            return None, "Unable to connect. Please try again later."

        try:
            response = supabase.table('users').select("username").eq('username', str(username)).eq('password', str(password)).execute()

            if response.data:
                logger.info("Login successful for '%s'", username)
                _clear_attempts(username)
                from logic.session import make_session_token
                return {'username': username, 'token': make_session_token(username)}, ""
            else:
                logger.info("Login failed for '%s'", username)
                _record_failed_attempt(username)
                return None, "Invalid credentials. Please try again."
        except Exception as e:
            logger.error("Login error: %s", e)
            return None, "Unable to connect. Please try again later."

    return dash.no_update, dash.no_update