import dash
from dash import html, dcc, callback, Input, Output, State, set_props
import dash_bootstrap_components as dbc
from logic.data_fetcher import fetch_fred_data, process_data, save_to_supabase
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots


dash.register_page(__name__, path='/dashboard')


def sidebar(active_tab):
    def link(id_, label, icon, tab_name):
        classes = 'nav-link-custom active' if active_tab == tab_name else 'nav-link-custom'
        return html.Div(id=id_, className=classes, children=[
            html.Span(icon, style={'marginRight': '0.75rem'}),
            html.Span(label)
        ], n_clicks=0)

    return html.Div(className='sidebar', children=[
        html.Div(className='sidebar-logo', children=[
            html.Img(src=dash.get_asset_url('logo_dark.svg'), style={'height': '32px'})
        ]),
        link('nav-data', 'Data', '📊', 'data'),
        link('nav-model', 'Model', '🧠', 'model'),
        html.Div(className='sidebar-footer', children=[
            link('nav-signout', 'Sign out', '🚪', 'signout')
        ])
    ])


def data_tab_content():
    return html.Div(className='dashboard-card', children=[
        html.H3('Data', className='section-title'),
        html.Div(className='api-key-input', children=[
            html.Label('FRED API Key'),
            dcc.Input(id='fred-api-key', type='text', className='form-input', placeholder='Enter your FRED API key')
        ]),
        html.Div(className='api-key-input', children=[
            html.Label('EconData API Key'),
            dcc.Input(id='econdata-api-key', type='text', className='form-input', placeholder='Enter your EconData API key')
        ]),
        html.Button('Fetch Data', id='fetch-data-btn', n_clicks=0, className='login-button'),
        
        # Progress Bar
        html.Div(id='progress-container', hidden=True, style={'marginTop': '1.5rem'}, children=[
            html.Div(className='progress-wrapper', style={'display': 'flex', 'alignItems': 'center', 'gap': '1rem'}, children=[
                dbc.Progress(id='fetch-progress-bar', value=0, max=100, striped=True, animated=True, style={'height': '15px', 'flex': '1'}),
                html.Div(id='progress-percentage', style={'fontSize': '1.1rem', 'fontWeight': 'bold', 'color': 'var(--accent)', 'minWidth': '50px'}, children='0%')
            ]),
            html.Div(id='progress-status', style={'textAlign': 'left', 'marginTop': '0.75rem', 'fontSize': '0.9rem', 'color': 'var(--text-secondary)'})
        ]),
        
        html.Div(id='data-error', className='login-error', style={'marginTop': '1rem'}),
        
        # Visualization Section
        html.Div(id='visualization-container', style={'marginTop': '2rem', 'display': 'none'}, children=[
            html.H3('Visualization', className='section-title'),
            html.Div(className='api-key-input', children=[
                html.Label('Select Predictor to Compare with ZAR/USD:'),
                dcc.Dropdown(
                    id='predictor-dropdown',
                    className='form-input',
                    placeholder='Select a factor...',
                    style={'backgroundColor': 'var(--input-bg)', 'color': '#000'}
                )
            ]),
            dcc.Graph(id='zar-graph', className='dashboard-card')
        ]),
        
        html.Div(id='data-table-container', className='data-table-container', style={'marginTop': '1.5rem'})
    ])


def model_tab_content():
    return html.Div(className='dashboard-card', children=[
        html.H3('Model', className='section-title'),
        html.Div('Model functionality coming soon.')
    ])


def layout():
    # Default active tab is 'data'
    active_tab = 'data'
    return html.Div(id='dashboard-container', children=[
        dcc.Store(id='dashboard-tab', data=active_tab, storage_type='session'),
        dcc.Store(id='fetched-data', storage_type='memory'),
        dcc.Store(id='fetch-trigger', data=0, storage_type='memory'),
        sidebar(active_tab),
        html.Div(className='content-area', children=[
            html.Div(id='content-body', children=[data_tab_content()])
        ])
    ])



# Navigation: set active tab when clicking sidebar links
@callback(
    Output('dashboard-tab', 'data'),
    Input('nav-data', 'n_clicks'),
    Input('nav-model', 'n_clicks'),
    Input('nav-signout', 'n_clicks'),
    State('dashboard-tab', 'data'),
    prevent_initial_call=True
)
def set_active_tab(data_clicks, model_clicks, signout_clicks, current_tab):
    ctx = dash.callback_context
    if not ctx.triggered:
        return current_tab or 'data'
    trigger = ctx.triggered[0]['prop_id'].split('.')[0]
    if trigger == 'nav-data':
        return 'data'
    if trigger == 'nav-model':
        return 'model'
    if trigger == 'nav-signout':
        return 'signout'
    return current_tab or 'data'


# Update sidebar active classes and content area based on active tab
@callback(
    Output('nav-data', 'className'),
    Output('nav-model', 'className'),
    Output('nav-signout', 'className'),
    Output('content-body', 'children'),
    Input('dashboard-tab', 'data')
)
def update_view(active_tab):
    data_cls = 'nav-link-custom active' if active_tab == 'data' else 'nav-link-custom'
    model_cls = 'nav-link-custom active' if active_tab == 'model' else 'nav-link-custom'
    signout_cls = 'nav-link-custom active' if active_tab == 'signout' else 'nav-link-custom'

    if active_tab == 'data':
        content = data_tab_content()
    elif active_tab == 'model':
        content = model_tab_content()
    else:
        content = html.Div(className='dashboard-card', children=[
            html.H3('Sign out', className='section-title'),
            html.Div('Click to confirm sign out from the left menu.')
        ])

    return data_cls, model_cls, signout_cls, content


# Handle signout: clear session
@callback(
    Output('user-session', 'data', allow_duplicate=True),
    Output('url', 'pathname', allow_duplicate=True),
    Input('nav-signout', 'n_clicks'),
    prevent_initial_call=True
)
def perform_signout(signout_clicks):
    if signout_clicks:
        return None, "/"
    return dash.no_update, dash.no_update


# Validation callback to prevent background fetch if keys are missing
@callback(
    Output('fetch-trigger', 'data'),
    Output('data-error', 'children', allow_duplicate=True),
    Input('fetch-data-btn', 'n_clicks'),
    State('fred-api-key', 'value'),
    State('econdata-api-key', 'value'),
    State('fetch-trigger', 'data'),
    prevent_initial_call=True
)
def validate_keys(n_clicks, fred_key, econdata_key, current_trigger):
    if not n_clicks:
        return dash.no_update, dash.no_update
    
    if not fred_key or not econdata_key:
        return dash.no_update, 'Please enter both FRED and EconData API keys.'
    
    return (current_trigger or 0) + 1, ""


# Fetch data using provided API keys
@callback(
    Output('fetched-data', 'data'),
    Output('data-error', 'children', allow_duplicate=True),
    Output('data-table-container', 'children'),
    Output('predictor-dropdown', 'options'),
    Output('predictor-dropdown', 'value'),
    Output('visualization-container', 'style'),
    Input('fetch-trigger', 'data'),
    State('fred-api-key', 'value'),
    State('econdata-api-key', 'value'),
    background=True,
    running=[
        (Output('fetch-data-btn', 'disabled'), True, False),
        (Output('progress-container', 'hidden'), False, True),
        (Output('data-error', 'children'), "", dash.no_update)
    ],
    progress=[
        Output('fetch-progress-bar', 'value'),
        Output('progress-percentage', 'children'),
        Output('progress-status', 'children')
    ],
    prevent_initial_call=True
)
def fetch_data(set_progress, trigger_value, fred_key, econdata_key):
    if trigger_value:
        print(f"DEBUG: fetch_data background callback started. trigger_value={trigger_value}")
        set_progress((0, '0%', 'Starting data fetch...'))
        
        try:
            series = {
                'EPU(USA)': 'USEPUINDXM',
                'WUIZAF(SA)': 'WUIZAF',
                '10_YEAR_BOND_RATES(USA)': 'GS10',
                '10_YEAR_BOND_RATES(SA)': 'IRLTLT01ZAM156N',
                'SA_INFLATION': 'CPALTT01ZAM659N',
                'USA_INFLATION': 'CPALTT01USM659N',
                'VIX': 'VIXCLS',
                'GOLD_PRICE': 'PCU2122212122210',
                'BRENT_OIL_PRICE': 'POILBREUSDM',
                'ZAR_USD': 'DEXSFUS'
            }
            
            def update_progress(percent, status_msg):
                print(f"DEBUG: Progress update: {percent}% - {status_msg}")
                # Bar value goes from 0 to 100, and we explicitly show percentage
                set_progress((percent, f'{percent}%', f'Processing: {percent}% - {status_msg}'))
            
            print("DEBUG: Calling fetch_fred_data...")
            raw = fetch_fred_data(series, api_key=str(fred_key), progress_callback=update_progress)
            
            if raw.empty:
                print("DEBUG: raw_df is empty")
                return dash.no_update, 'Failed to fetch data. Please check your API keys and try again.', dash.no_update, dash.no_update, dash.no_update, dash.no_update
            
            print(f"DEBUG: Successfully fetched raw data with {len(raw)} rows. Processing...")
            set_progress((95, '95%', 'Processing and saving data...'))
            processed = process_data(raw, start_date='2000-01-01', end_date='2026-12-31')
            
            if processed.empty:
                print("DEBUG: processed_df is empty")
                return dash.no_update, 'No data available in the requested date range.', dash.no_update, dash.no_update, dash.no_update, dash.no_update

            # Save to Supabase (All data since 2000)
            supabase_msg = ""
            try:
                print("DEBUG: Attempting to save to Supabase...")
                save_to_supabase(processed)
                print("DEBUG: Save to Supabase successful")
            except Exception as e:
                # Non-fatal: show message but still display data
                print(f"DEBUG Warning: Could not save to Supabase: {e}")
                supabase_msg = f" (Warning: Could not save to Supabase: {e})"

            # Prepare for display
            print("DEBUG: Preparing data for display...")
            df_all = processed.reset_index()
            df_all['Date'] = pd.to_datetime(df_all['Date']).dt.strftime('%Y-%m-%d')
            # Sort descending by date for display (2026 -> 2000)
            df_all = df_all.sort_values('Date', ascending=False)
            
            # Limit to 10 most recent observations for the table
            df_table = df_all.head(10)

            columns = ['Date'] + [c for c in df_table.columns if c != 'Date']

            header = html.Thead(html.Tr([html.Th(col) for col in columns]))
            body_rows = []
            for _, row in df_table.iterrows():
                tds = [html.Td(row[col] if pd.notna(row[col]) else '-') for col in columns]
                body_rows.append(html.Tr(tds))
            table = html.Table(className='custom-table', children=[header, html.Tbody(body_rows)])

            # Get predictors (all columns except Date and ZAR_USD)
            predictors = [c for c in df_all.columns if c not in ['Date', 'ZAR_USD']]
            dropdown_options = [{'label': p, 'value': p} for p in predictors]
            default_predictor = predictors[0] if predictors else None

            msg = f"Data successfully loaded!{supabase_msg} showing 10 most recent observations."
            
            print("DEBUG: Background fetch_data complete. Returning results.")
            set_progress((100, '100%', 'Complete!'))
            return df_all.to_dict('records'), msg, table, dropdown_options, default_predictor, {'marginTop': '2rem', 'display': 'block'}
        except Exception as e:
            print(f"DEBUG Error in fetch_data: {str(e)}")
            import traceback
            traceback.print_exc()
            return dash.no_update, f'Error: {str(e)}', dash.no_update, dash.no_update, dash.no_update, dash.no_update
    return dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update


@callback(
    Output('zar-graph', 'figure'),
    Input('predictor-dropdown', 'value'),
    Input('fetched-data', 'data'),
    State('theme-store', 'data')
)
def update_graph(predictor, data, theme):
    if not data or not predictor:
        return go.Figure()
    
    df = pd.DataFrame(data)
    df['Date'] = pd.to_datetime(df['Date'])
    df = df.sort_values('Date')
    
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    
    # Primary axis: ZAR/USD
    fig.add_trace(
        go.Scatter(x=df['Date'], y=df['ZAR_USD'], name='ZAR/USD', line=dict(color='#38bdf8', width=2)),
        secondary_y=False
    )
    
    # Secondary axis: Selected Predictor
    fig.add_trace(
        go.Scatter(x=df['Date'], y=df[predictor], name=predictor, line=dict(color='#8b5cf6', width=2)),
        secondary_y=True
    )
    
    template = 'plotly_dark' if theme == 'dark' else 'plotly_white'
    
    fig.update_layout(
        template=template,
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        margin=dict(l=40, r=40, t=40, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="x unified",
        transition_duration=500
    )
    
    fig.update_yaxes(title_text="ZAR/USD", secondary_y=False)
    fig.update_yaxes(title_text=predictor, secondary_y=True)
    
    return fig
