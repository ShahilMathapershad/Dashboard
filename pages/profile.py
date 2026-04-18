import dash
from dash import html, dcc, callback, Input, Output, State
from logic.supabase_client import get_supabase
import datetime

dash.register_page(__name__, path='/profile')


def layout():
    now = datetime.datetime.now()
    date_str = f"{now.strftime('%B')} {now.day}, {now.year}"

    return html.Div(className='profile-container', children=[
        dcc.Store(id='profile-pw-store'),

        # Topbar
        html.Div(className='profile-topbar', children=[
            html.A('← Dashboard', href='/dashboard', className='profile-back-btn'),
            html.Div(className='profile-topbar-sep'),
            html.Span('Profile', className='profile-topbar-title'),
        ]),

        # Content
        html.Div(className='profile-content', children=[

            # Hero card
            html.Div(className='profile-hero-card', children=[
                html.Div('?', id='profile-avatar-large', className='profile-avatar-large'),
                html.Div(className='profile-hero-info', children=[
                    html.Div('Loading...', id='profile-hero-name', className='profile-hero-name'),
                    html.Div(
                        'Authorized User · economicsweekly.co.za',
                        className='profile-hero-role'
                    ),
                ]),
            ]),

            # Account info
            html.Div(className='profile-section-card', children=[
                html.Div('Account Information', className='profile-section-label'),
                html.Div(className='profile-info-row', children=[
                    html.Span('Username', className='profile-info-key'),
                    html.Span('—', id='profile-username-display', className='profile-info-val'),
                ]),
                html.Div(className='profile-info-row', children=[
                    html.Span('Access Level', className='profile-info-key'),
                    html.Span('Stakeholder', className='profile-info-val'),
                ]),
                html.Div(className='profile-info-row', children=[
                    html.Span('Data Sources', className='profile-info-key'),
                    html.Span('FRED · World Bank · Stats SA', className='profile-info-val'),
                ]),
                html.Div(className='profile-info-row', children=[
                    html.Span('Session Date', className='profile-info-key'),
                    html.Span(date_str, className='profile-info-val'),
                ]),
            ]),

            # Change password
            html.Div(className='profile-section-card', style={'animationDelay': '0.2s'}, children=[
                html.Div('Change Password', className='profile-section-label'),
                html.Div(className='profile-password-fields', children=[
                    dcc.Input(
                        id='profile-current-password',
                        type='password',
                        placeholder='Current password',
                        className='form-input',
                        autoComplete='current-password',
                    ),
                    dcc.Input(
                        id='profile-new-password',
                        type='password',
                        placeholder='New password (min. 6 characters)',
                        className='form-input',
                        autoComplete='new-password',
                    ),
                    dcc.Input(
                        id='profile-confirm-password',
                        type='password',
                        placeholder='Confirm new password',
                        className='form-input',
                        autoComplete='new-password',
                    ),
                ]),
                html.Div(className='profile-action-row', children=[
                    html.Span('', id='profile-msg', className='profile-msg'),
                    html.Button(
                        'Update Password',
                        id='profile-update-btn',
                        className='login-button',
                        n_clicks=0,
                        style={'width': 'auto', 'padding': '0 28px', 'minWidth': '160px', 'height': '44px'},
                    ),
                ]),
            ]),

            # Sign out
            html.Div(className='profile-section-card profile-signout-card',
                     style={'animationDelay': '0.3s'}, children=[
                html.Button('Sign Out', id='profile-signout-btn', n_clicks=0, className='profile-signout-link'),
            ]),
        ]),
    ])


@callback(
    Output('user-session', 'data', allow_duplicate=True),
    Input('profile-signout-btn', 'n_clicks'),
    prevent_initial_call=True
)
def profile_signout(n_clicks):
    if n_clicks:
        return None
    return dash.no_update


@callback(
    Output('profile-avatar-large', 'children'),
    Output('profile-hero-name', 'children'),
    Output('profile-username-display', 'children'),
    Input('user-session', 'data'),
)
def populate_profile(session_data):
    if session_data and session_data.get('username'):
        username = session_data['username']
        return username[0].upper(), username, username
    return '?', 'Unknown User', '—'


@callback(
    Output('profile-msg', 'children'),
    Output('profile-msg', 'className'),
    Output('profile-current-password', 'value'),
    Output('profile-new-password', 'value'),
    Output('profile-confirm-password', 'value'),
    Input('profile-update-btn', 'n_clicks'),
    State('profile-current-password', 'value'),
    State('profile-new-password', 'value'),
    State('profile-confirm-password', 'value'),
    State('user-session', 'data'),
    prevent_initial_call=True,
)
def update_password(n_clicks, current_pw, new_pw, confirm_pw, session_data):
    no_clear = (dash.no_update, dash.no_update, dash.no_update)

    if not current_pw or not new_pw or not confirm_pw:
        return 'Please fill in all fields.', 'profile-msg error', *no_clear

    if new_pw != confirm_pw:
        return 'New passwords do not match.', 'profile-msg error', *no_clear

    if len(new_pw) < 6:
        return 'New password must be at least 6 characters.', 'profile-msg error', *no_clear

    username = (session_data or {}).get('username')
    if not username:
        return 'Session expired. Please log in again.', 'profile-msg error', *no_clear

    supabase = get_supabase()
    if not supabase:
        return 'Connection error. Please try again.', 'profile-msg error', *no_clear

    try:
        resp = supabase.table('users').select('username') \
            .eq('username', username).eq('password', current_pw).execute()
        if not resp.data:
            return 'Current password is incorrect.', 'profile-msg error', *no_clear

        supabase.table('users').update({'password': new_pw}).eq('username', username).execute()
        return 'Password updated successfully.', 'profile-msg success', '', '', ''
    except Exception as e:
        return f'Error: {str(e)}', 'profile-msg error', *no_clear
