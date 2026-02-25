import dash
from dash import html, dcc, callback, Input, Output, State

dash.register_page(__name__, path='/dashboard')

def layout():
    # We use a wrapper div to check session in callback, 
    # but for simple redirect we can also do it here if we had access to dcc.Location in layout.
    # Dash Pages handles this better with a dynamic layout function.
    return html.Div(id='dashboard-container')

@callback(
    Output('dashboard-container', 'children'),
    Output('url', 'pathname', allow_duplicate=True),
    Input('user-session', 'data'),
    prevent_initial_call='initial_duplicate'
)
def check_auth(session_data):
    if not session_data or not session_data.get('username'):
        return dash.no_update, '/'
    
    # Returning a blank screen as requested
    return html.Div(style={'height': '100vh', 'backgroundColor': 'var(--bg-dark)'}), dash.no_update
