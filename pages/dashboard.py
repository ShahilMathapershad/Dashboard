import dash
from dash import html, dcc, callback, Input, Output, State
import dash_bootstrap_components as dbc
from logic.data_fetcher import (
    fetch_fred_data, fetch_world_bank_gold_data, fetch_sa_inflation_hardcoded, 
    process_data, save_to_supabase, replace_gold_price_column_in_supabase, 
    FRED_API_KEY, SERIES_CONFIG, should_update_from_api, fetch_and_save_data
)
from logic.model import predict_next_month, fetch_data_from_supabase
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import traceback
import datetime


dash.register_page(__name__, path='/dashboard')


def sidebar(active_tab):
    def link(id_, label, tab_name):
        classes = 'nav-link-custom active' if active_tab == tab_name else 'nav-link-custom'
        return html.Div(id=id_, className=classes, children=[
            html.Span(label, className='nav-label')
        ], n_clicks=0)

    return html.Div(className='sidebar', id='sidebar', children=[
        html.Button(id='sidebar-toggle', className='sidebar-toggle', children='❮', n_clicks=0),
        html.Div(className='sidebar-logo', children=[
            html.Img(src=dash.get_asset_url('logo_light.svg'), className='logo-light'),
            html.Img(src=dash.get_asset_url('logo_dark.svg'), className='logo-dark')
        ]),
        html.Div(className='sidebar-nav', children=[
            link('nav-data', 'Data', 'data'),
            link('nav-model', 'Model', 'model'),
        ]),
        html.Div(className='sidebar-footer', children=[
            html.Div(id='nav-signout', className='nav-link-custom', children=[
                html.Span('→', className='nav-icon'),
                html.Span('Sign out', className='nav-label')
            ], n_clicks=0)
        ])
    ])


def data_tab_content(existing_data=None):
    viz_style = {'display': 'block', 'marginTop': '2rem'} if existing_data else {'display': 'none'}
    return html.Div(className='tab-content fade-in', children=[
        # Page Header
        html.Div(className='page-header', children=[
            html.Div(children=[
                html.H2('Data Explorer', className='page-title'),
                html.P("Automated data analysis and visualisation against ZAR/USD.",
                       className='page-subtitle'),
            ]),
            html.Div(className='page-actions', children=[
                html.Div(id='fetch-status-display', className='status-badge'),
            ])
        ]),

        # Progress Bar
        html.Div(id='progress-container', hidden=True, className='progress-card', children=[
            html.Div(className='progress-wrapper', children=[
                dbc.Progress(id='fetch-progress-bar', value=0, max=100, striped=True, animated=True,
                             className='progress-bar-custom'),
                html.Div(id='progress-percentage', className='progress-pct', children='0%')
            ]),
            html.Div(id='progress-status', className='progress-status')
        ]),

        html.Div(id='data-error', className='error-message'),

        # Visualisation Section
        html.Div(id='visualization-container', className='viz-container', style=viz_style, children=[
            # Predictor Selector Bar
            html.Div(className='predictor-bar', children=[
                html.Div(className='predictor-bar-header', children=[
                    html.Span('Predictors', className='predictor-bar-title'),
                    html.Button(
                        id='toggle-table-btn',
                        className='btn-ghost',
                        children='Show Table',
                        n_clicks=0
                    )
                ]),
                html.Div(id='predictor-checkboxes-container', className='predictor-chips'),
            ]),

            # Hero Chart
            dcc.Graph(
                id='zar-graph',
                className='hero-chart',
                style={'height': '68vh', 'minHeight': '560px', 'maxHeight': '760px', 'width': '100%'},
                config={
                    'displayModeBar': 'hover',
                    'displaylogo': False,
                    'responsive': True,
                    'modeBarButtonsToAdd': ['drawline', 'drawopenpath', 'eraseshape'],
                    'modeBarButtonsToRemove': ['lasso2d', 'select2d'],
                    'toImageButtonOptions': {
                        'format': 'png',
                        'filename': 'zar_analysis',
                        'height': 1080,
                        'width': 1920,
                        'scale': 2
                    },
                    'scrollZoom': True
                },
            ),

            # Data Table (hidden by default)
            html.Div(id='data-table-container', className='table-card', style={'display': 'none'})
        ]),
    ])


def model_tab_content(existing_model_data=None):
    model_style = {'display': 'block'} if existing_model_data else {'display': 'none'}
    return html.Div(className='tab-content fade-in', children=[
        html.Div(className='page-header', children=[
            html.Div(children=[
                html.H2('Model', className='page-title'),
                html.P("Next-month ZAR/USD forecast via frozen ElasticNet (Lasso) model.",
                       className='page-subtitle'),
            ]),
            html.Div(className='page-actions', children=[
                html.Div(id='model-status-display', className='status-badge'),
            ])
        ]),

        html.Div(id='model-error', className='error-message'),

        html.Div(id='model-results-container', style=model_style, children=[

            # Top row: prediction card + feature contributions
            html.Div(className='model-top-row', children=[

                # Prediction Card
                html.Div(className='model-card prediction-hero', children=[
                    html.Div(className='prediction-header', children=[
                        html.Span('Next Month Forecast', className='prediction-label'),
                        html.Span(id='prediction-date', className='prediction-date'),
                    ]),
                    html.Div(id='prediction-value', className='prediction-value'),
                    html.Div(id='prediction-change', className='prediction-change'),
                    html.Div(className='prediction-baseline', children=[
                        html.Span('Current: ', className='baseline-label'),
                        html.Span(id='prediction-baseline-value', className='baseline-value'),
                    ]),
                ]),

                # Feature Contributions
                html.Div(className='model-card', children=[
                    html.H4('Key Drivers', className='card-title'),
                    html.P('Non-zero model coefficients and their current contribution',
                           className='card-subtitle'),
                    html.Div(id='feature-contributions'),
                ]),
            ]),

            # Historical Fit Chart
            html.Div(id='visualization-container', className='model-card', children=[
                html.H4('Historical Fit', className='card-title'),
                html.P('Model predictions vs actual ZAR/USD (level space)',
                       className='card-subtitle'),
                dcc.Graph(
                    id='model-history-chart',
                    className='model-chart',
                    config={
                        'displayModeBar': 'hover',
                        'displaylogo': False,
                        'responsive': True,
                        'scrollZoom': True,
                    },
                ),
            ]),

            # Model Info
            html.Div(className='model-card model-info-card', children=[
                html.H4('Model Specification', className='card-title'),
                html.Div(id='model-info-content'),
                # Dynamic model description
                html.Hr(style={'margin': '24px 0', 'borderTop': '1px solid var(--border)'}),
                html.H4('Model Analysis & Forecast Summary', className='card-title'),
                html.Div(id='model-description-content', className='model-analysis-text', style={
                    'lineHeight': '1.6',
                    'color': 'var(--text-2)',
                    'fontSize': '0.9375rem',
                    'marginTop': '12px'
                }),
            ]),
        ]),
    ])


def layout():
    active_tab = 'data'
    return html.Div(id='dashboard-container', className='page-transition sidebar-collapsed', n_clicks=0, children=[
        dcc.Store(id='dashboard-tab', data=active_tab, storage_type='session'),
        dcc.Store(id='sidebar-state', data='collapsed', storage_type='local'),
        dcc.Store(id='fetched-data', storage_type='session'), # Changed to session for persistence
        dcc.Store(id='model-prediction-data', storage_type='session'), # Added for persistence
        dcc.Store(id='fetch-trigger', data=0, storage_type='session'),
        dcc.Store(id='model-prediction-trigger', data=0, storage_type='session'),
        dcc.Store(id='predictor-dropdown-options-store', storage_type='session'),
        dcc.Store(id='selected-predictors', data=[], storage_type='session'),
        dcc.Store(id='fetched-data-status', storage_type='session'),
        sidebar(active_tab),
        html.Div(className='content-area', id='content-area', children=[
            html.Div(id='content-body', children=[data_tab_content()])
        ])
    ])



@callback(
    Output('sidebar-state', 'data'),
    Input('sidebar-toggle', 'n_clicks'),
    State('sidebar-state', 'data'),
    prevent_initial_call=True
)
def toggle_sidebar(n_clicks, current_state):
    if n_clicks > 0:
        return 'collapsed' if current_state == 'expanded' else 'expanded'
    return current_state


dash.clientside_callback(
    """
    function(state) {
        const container = document.getElementById('dashboard-container');
        const toggleBtn = document.getElementById('sidebar-toggle');
        if (state === 'collapsed') {
            container.classList.add('sidebar-collapsed');
            if (toggleBtn) toggleBtn.innerText = '❯';
        } else {
            container.classList.remove('sidebar-collapsed');
            if (toggleBtn) toggleBtn.innerText = '❮';
        }
        return window.dash_clientside.no_update;
    }
    """,
    Output('sidebar-toggle', 'id'),
    Input('sidebar-state', 'data')
)


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
    Input('dashboard-tab', 'data'),
    State('fetched-data', 'data'),
    State('model-prediction-data', 'data'),
    prevent_initial_call=False
)
def update_view(active_tab, existing_data, existing_model_data):
    data_cls = 'nav-link-custom active' if active_tab == 'data' else 'nav-link-custom'
    model_cls = 'nav-link-custom active' if active_tab == 'model' else 'nav-link-custom'
    signout_cls = 'nav-link-custom active' if active_tab == 'signout' else 'nav-link-custom'
    
    if active_tab == 'data':
        print("DEBUG: Rendering Data Tab")
        content = data_tab_content(existing_data)
    elif active_tab == 'model':
        print("DEBUG: Rendering Model Tab")
        content = model_tab_content(existing_model_data)
    else:
        print(f"DEBUG: Rendering Sign Out or Other Tab: {active_tab}")
        content = html.Div(className='tab-content fade-in', children=[
            html.Div(className='page-header', children=[
                html.Div(children=[
                    html.H2('Sign Out', className='page-title'),
                    html.P('You will be redirected to the login page.', className='page-subtitle'),
                ]),
            ]),
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


# Trigger data fetch and model prediction automatically
@callback(
    Output('fetch-trigger', 'data'),
    Output('model-prediction-trigger', 'data'),
    Input('dashboard-tab', 'data'),
    State('fetch-trigger', 'data'),
    State('model-prediction-trigger', 'data'),
    State('fetched-data', 'data'),
    State('model-prediction-data', 'data'),
    prevent_initial_call='initial_duplicate'
)
def auto_trigger_callbacks(active_tab, current_fetch_trigger, current_model_trigger, existing_data, existing_model_data):
    fetch_trigger = dash.no_update
    model_trigger = dash.no_update
    
    # Always try to fetch data if on data tab
    # We increment the trigger even if existing_data is present, because
    # switching tabs creates new elements that need to be populated by the callback.
    if active_tab == 'data':
        print(f"DEBUG: Triggering data fetch (active_tab={active_tab})")
        fetch_trigger = (current_fetch_trigger or 0) + 1
        
    # Always try to run model when on model tab
    # We increment the trigger even if existing_model_data is present, because
    # switching tabs creates new elements that need to be populated by the callback.
    if active_tab == 'model':
        print(f"DEBUG: Triggering model prediction (active_tab={active_tab})")
        model_trigger = (current_model_trigger or 0) + 1
        
    return fetch_trigger, model_trigger


def _generate_data_table(df_all):
    if df_all is None or (isinstance(df_all, pd.DataFrame) and df_all.empty) or (isinstance(df_all, list) and not df_all):
        return html.Div("No data available for table.")
    
    if isinstance(df_all, list):
        df_all = pd.DataFrame(df_all)
        
    df_all['Date'] = pd.to_datetime(df_all['Date']).dt.strftime('%Y-%m-%d')
    df_sorted = df_all.sort_values('Date', ascending=True)
    
    # Calculate percentage changes for all columns except Date
    pct_change_data = []
    for i in range(1, len(df_sorted)):
        row_data = {'Date': df_sorted.iloc[i]['Date']}
        for col in df_sorted.columns:
            if col != 'Date':
                prev_val = df_sorted.iloc[i-1][col]
                curr_val = df_sorted.iloc[i][col]
                if pd.notna(prev_val) and pd.notna(curr_val) and prev_val != 0:
                    pct_change = ((curr_val - prev_val) / prev_val) * 100
                    row_data[col] = pct_change
                else:
                    row_data[col] = None
        pct_change_data.append(row_data)
    
    df_pct = pd.DataFrame(pct_change_data)
    df_pct = df_pct.sort_values('Date', ascending=False).head(10)
    
    # Build table
    predictors = [c for c in df_pct.columns if c not in ['Date', 'ZAR_USD']]
    user_friendly_columns = ['Date']
    for pred in predictors:
        friendly_name = SERIES_CONFIG.get(pred, {}).get('label', pred)
        if len(friendly_name) > 25:
            friendly_name = friendly_name.replace('(', '\n(').replace(' for ', '\n')
            friendly_name = '\n'.join([line.strip() for line in friendly_name.split('\n') if line.strip()])
        user_friendly_columns.append(friendly_name)
    user_friendly_columns.append('ZAR/USD Effect')
    
    header = html.Thead(html.Tr([html.Th(col, style={'textAlign': 'center', 'whiteSpace': 'pre-line', 'fontSize': '0.75rem'}) for col in user_friendly_columns]))
    body_rows = []
    for _, row in df_pct.iterrows():
        tds = [html.Td(row['Date'], style={'fontWeight': '500'})]
        for col in predictors:
            val = row[col]
            if pd.isna(val):
                tds.append(html.Td('-', style={'textAlign': 'center'}))
            else:
                color = '#10B981' if val > 0 else '#EF4444' if val < 0 else '#6b6b6b'
                tds.append(html.Td(f"{val:+.2f}%", style={'color': color, 'fontWeight': '600', 'textAlign': 'center'}))
        
        zar_val = row.get('ZAR_USD')
        if pd.isna(zar_val):
            tds.append(html.Td('-', style={'textAlign': 'center'}))
        else:
            color = '#EF4444' if zar_val > 0 else '#10B981' if zar_val < 0 else '#6b6b6b'
            tds.append(html.Td(f"{zar_val:+.2f}%", style={'color': color, 'fontWeight': '700', 'textAlign': 'center', 'fontSize': '1.05em'}))
        body_rows.append(html.Tr(tds))
    
    return html.Table(className='custom-table', children=[header, html.Tbody(body_rows)])


@callback(
    Output('fetch-status-display', 'children'),
    Output('visualization-container', 'style', allow_duplicate=True),
    Output('data-table-container', 'children'),
    Input('dashboard-tab', 'data'),
    Input('fetched-data', 'data'),
    Input('fetched-data-status', 'data'),
    prevent_initial_call='initial_duplicate'
)
def sync_data_tab_ui(active_tab, data, status_info):
    if active_tab != 'data':
        return dash.no_update, dash.no_update, dash.no_update
    
    print(f"DEBUG: sync_data_tab_ui triggered. active_tab={active_tab}")
    
    status_msg = ""
    if status_info:
        # Reconstruct the status badge
        status_msg = html.Span(status_info.get('text', ''), style={'color': status_info.get('color', '#6b6b6b')})
    
    viz_style = {'display': 'block', 'marginTop': '2rem'} if data else {'display': 'none'}
    
    # Use the helper to rebuild the table from persisted data
    table = _generate_data_table(data) if data else ""
    
    return status_msg, viz_style, table


# Fetch data using hardcoded API keys
@callback(
    Output('fetched-data', 'data'),
    Output('data-error', 'children', allow_duplicate=True),
    Output('predictor-dropdown-options-store', 'data'),
    Output('selected-predictors', 'data'),
    Output('fetched-data-status', 'data'),
    Input('fetch-trigger', 'data'),
    State('fetched-data', 'data'),
    State('predictor-dropdown-options-store', 'data'),
    State('selected-predictors', 'data'),
    State('fetched-data-status', 'data'),
    background=True,
    running=[
        (Output('progress-container', 'hidden'), False, True),
        (Output('data-error', 'children'), "", "")
    ],
    progress=[
        Output('fetch-progress-bar', 'value'),
        Output('progress-percentage', 'children'),
        Output('progress-status', 'children')
    ],
    prevent_initial_call=True
)
def fetch_data(set_progress, trigger_value, existing_data, existing_options, existing_selected, existing_status):
    # Defensive check: set_progress can be None in some edge cases during callback initialization
    if set_progress is None:
        print("DEBUG WARNING: set_progress is None, progress updates will be skipped")
        set_progress = lambda x: None  # No-op function
    
    if trigger_value:
        print(f"DEBUG: fetch_data background callback started. trigger_value={trigger_value}")
        
        # If we already have data in session, just return it to re-populate UI
        if existing_data:
            print("DEBUG: Using existing data from session to re-populate UI")
            return existing_data, "", existing_options, existing_selected, existing_status
        
        try:
            # Check if we should update from API or Supabase
            use_api = should_update_from_api()
            
            if not use_api:
                set_progress((20, '20%', 'Fetching data from Supabase...'))
                print("DEBUG: Pulling data from Supabase (not last day or already updated)")
                processed = fetch_data_from_supabase()
                status_data = {'text': '● Live (Supabase)', 'color': '#10B981'}
                # Need wb_gold for replace_gold_price_column_in_supabase if we follow same structure
                # But if we pull from Supabase, we don't need to replace gold.
                wb_gold = pd.Series() 
            else:
                set_progress((0, '0%', 'Connecting to API sources...'))
                print("DEBUG: Fetching data from APIs (last day of month)")
                # Use unified configuration from data_fetcher
                fred_series = {name: cfg['id'] for name, cfg in SERIES_CONFIG.items() if cfg['source'] == 'FRED'}
                
                def update_progress(percent, status_msg):
                    print(f"DEBUG: Progress update: {percent}% - {status_msg}")
                    if set_progress:
                        try:
                            set_progress((percent, f'{percent}%', status_msg))
                        except Exception as e:
                            print(f"DEBUG WARNING: set_progress failed: {e}")
                
                print("DEBUG: Calling fetch_fred_data...")
                raw = fetch_fred_data(fred_series, api_key=FRED_API_KEY, progress_callback=update_progress)

                # Fetch GOLD_PRICE from World Bank monthly commodity data.
                wb_gold = fetch_world_bank_gold_data(start_date='2018-01-31')
                if not wb_gold.empty:
                    # Use concat instead of assignment to allow the index to expand to the latest available data.
                    raw = pd.concat([raw, wb_gold.to_frame(name='GOLD_PRICE')], axis=1)
                
                # Fetch SA_INFLATION (Hardcoded)
                sa_inflation = fetch_sa_inflation_hardcoded()
                raw = pd.concat([raw, sa_inflation], axis=1)
                
                if raw.empty:
                    print("DEBUG: raw_df is empty")
                    return dash.no_update, 'Failed to fetch data from APIs.', dash.no_update, dash.no_update, dash.no_update
                
                print(f"DEBUG: Successfully fetched raw data with {len(raw)} rows. Processing...")
                if set_progress:
                    set_progress((95, '95%', 'Finalising...'))
                processed = process_data(raw, start_date='2018-01-31')
                status_data = {'text': '● Updated from API', 'color': '#3B82F6'}

            if processed.empty:
                print("DEBUG: processed_df is empty")
                return dash.no_update, 'No data available.', dash.no_update, dash.no_update, dash.no_update

            # Save to Supabase only if we fetched from API
            if use_api:
                try:
                    print("DEBUG: Attempting to save to Supabase...")
                    save_to_supabase(processed)
                    if not wb_gold.empty:
                        replace_gold_price_column_in_supabase(wb_gold)
                    print("DEBUG: Save to Supabase successful")
                except Exception as e:
                    print(f"DEBUG Warning: Could not save to Supabase: {e}")
                    status_data = {'text': '● Updated (Supabase error)', 'color': '#F59E0B'}

            # Prepare for display
            print("DEBUG: Preparing data for display...")
            df_all = processed.reset_index()
            df_all['Date'] = pd.to_datetime(df_all['Date']).dt.strftime('%Y-%m-%d')
            
            # Get predictors (all columns except Date and ZAR_USD)
            predictors = [c for c in df_all.columns if c not in ['Date', 'ZAR_USD']]
            
            # Use labels from SERIES_CONFIG for the options
            dropdown_options = [
                {'label': SERIES_CONFIG.get(p, {}).get('label', p), 'value': p} 
                for p in predictors
            ]
            # Default to first 1 predictor selected
            default_predictors = predictors[:1] if len(predictors) >= 1 else predictors

            print("DEBUG: Background fetch_data complete. Returning results.")
            if set_progress:
                set_progress((100, '100%', 'Complete'))
            return df_all.to_dict('records'), "", dropdown_options, default_predictors, status_data
        except Exception as e:
            print(f"DEBUG Error in fetch_data: {str(e)}")
            traceback.print_exc()
            return dash.no_update, f'Error: {str(e)}', dash.no_update, dash.no_update, dash.no_update
    return dash.no_update, '', dash.no_update, dash.no_update, dash.no_update


@callback(
    Output('predictor-checkboxes-container', 'children'),
    Input('predictor-dropdown-options-store', 'data'),
    Input('selected-predictors', 'data'),
    Input('dashboard-tab', 'data')
)
def render_predictor_checkboxes(options, selected_predictors, active_tab):
    if active_tab != 'data':
        return dash.no_update
    
    if not options:
        return html.Div('No predictors available', style={'color': 'var(--text-secondary)'})
    
    selected_set = set(selected_predictors or [])
    checkboxes = []
    
    for option in options:
        is_checked = option['value'] in selected_set
        checkboxes.append(
            html.Div(
                className='predictor-checkbox-item',
                children=[
                    dcc.Checklist(
                        id={'type': 'predictor-checkbox', 'index': option['value']},
                        options=[{'label': option['label'], 'value': option['value']}],
                        value=[option['value']] if is_checked else [],
                        className='custom-checklist',
                        labelStyle={'display': 'flex', 'alignItems': 'center', 'cursor': 'pointer'}
                    )
                ]
            )
        )
    
    return checkboxes


@callback(
    Output('selected-predictors', 'data', allow_duplicate=True),
    Input({'type': 'predictor-checkbox', 'index': dash.ALL}, 'value'),
    prevent_initial_call='initial_duplicate'
)
def update_selected_predictors(checkbox_values):
    # Prevent resetting when components are unmounted (tab switch)
    if not checkbox_values:
        return dash.no_update
    
    selected = []
    ctx = dash.callback_context
    
    # Rebuild selected list from current checkbox states
    for i, values in enumerate(checkbox_values):
        if values:
            # Each 'values' is a list (from dcc.Checklist)
            # We want the index from the component ID
            trigger_id = ctx.inputs_list[0][i]['id']
            selected.append(trigger_id['index'])
    
    return selected


@callback(
    Output('data-table-container', 'style', allow_duplicate=True),
    Output('toggle-table-btn', 'children'),
    Input('toggle-table-btn', 'n_clicks'),
    State('data-table-container', 'style'),
    prevent_initial_call=True
)
def toggle_data_table(n_clicks, current_style):
    if current_style.get('display') == 'none':
        return {'display': 'block'}, 'Hide Table'
    else:
        return {'display': 'none'}, 'Show Table'


@callback(
    Output('zar-graph', 'figure'),
    Input('selected-predictors', 'data'),
    Input('fetched-data', 'data'),
    Input('dashboard-tab', 'data'),
    State('theme-store', 'data'),
    State('predictor-dropdown-options-store', 'data')
)
def update_graph(selected_predictors, data, active_tab, theme, options):
    if active_tab != 'data' or not data or not selected_predictors:
        return go.Figure()
    
    df = pd.DataFrame(data)
    df['Date'] = pd.to_datetime(df['Date'])
    df = df.sort_values('Date')
    
    # Create a single-axis figure (no secondary y-axis)
    fig = go.Figure()
    
    # Premium color palette for predictors - all distinct from ZAR/USD neutral
    # Carefully selected warm and saturated tones, no blues/grays that clash with ZAR/USD
    color_palette = [
        '#F59E0B',  # Amber
        '#EC4899',  # Pink
        '#10B981',  # Emerald
        '#8B5CF6',  # Violet
        '#F97316',  # Orange
        '#EF4444',  # Red
        '#22C55E',  # Green
        '#D946EF',  # Fuchsia
        '#EAB308',  # Yellow
        '#14B8A6',  # Teal
        '#A855F7',  # Purple
        '#84CC16',  # Lime
        '#F43F5E',  # Rose
        '#FB923C',  # Light Orange
        '#4ADE80',  # Light Green
        '#C084FC',  # Light Purple
        '#06B6D4',  # Cyan
        '#0EA5E9',  # Sky Blue
        '#FACC15',  # Golden Yellow
        '#FB7185',  # Coral
    ]
    
    # Create a mapping from predictor value to label
    label_map = {opt['value']: opt['label'] for opt in (options or [])}
    
    # Normalize function: scale to 0-100 range
    def normalize(series):
        min_val = series.min()
        max_val = series.max()
        if max_val == min_val:
            return series * 0 + 50  # If constant, return middle value
        return ((series - min_val) / (max_val - min_val)) * 100
    
    # ZAR/USD gets a distinctive neutral color - clearly different from all predictors
    zar_color = '#E8E8E8' if theme == 'dark' else '#1A1A1A'
    zar_normalized = normalize(df['ZAR_USD'])
    fig.add_trace(
        go.Scatter(
            x=df['Date'], 
            y=zar_normalized,
            name='ZAR/USD',
            line=dict(color=zar_color, width=3, shape='spline'),
            mode='lines',
            customdata=df['ZAR_USD'],
            hovertemplate='<b>ZAR/USD</b>: %{customdata:.4f}<br>Normalized: %{y:.1f}<extra></extra>'
        )
    )
    
    # Plot each selected predictor (normalized)
    for i, predictor in enumerate(selected_predictors):
        if predictor in df.columns:
            color = color_palette[i % len(color_palette)]
            predictor_label = label_map.get(predictor, predictor)
            
            # Normalize the predictor data
            predictor_normalized = normalize(df[predictor])
            
            fig.add_trace(
                go.Scatter(
                    x=df['Date'], 
                    y=predictor_normalized,
                    name=predictor_label,
                    line=dict(color=color, width=2, shape='spline'),
                    mode='lines',
                    customdata=df[predictor],
                    hovertemplate=f'<b>{predictor_label}</b>: %{{customdata:.4f}}<br>Normalized: %{{y:.1f}}<extra></extra>'
                )
            )
    
    is_dark = theme == 'dark'
    
    grid_color = 'rgba(255,255,255,0.04)' if is_dark else 'rgba(0,0,0,0.04)'
    line_color = 'rgba(255,255,255,0.08)' if is_dark else 'rgba(0,0,0,0.08)'
    text_color = '#ffffff' if is_dark else '#0a0a0a'
    text_muted = '#6b6b6b' if is_dark else '#737373'
    spike_color = 'rgba(255,255,255,0.2)' if is_dark else 'rgba(0,0,0,0.15)'
    
    fig.update_layout(
        template=None,
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        margin=dict(l=40, r=20, t=30, b=80),
        autosize=True,
        font=dict(
            family="Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
            size=12,
            color=text_color
        ),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="left",
            x=0,
            font=dict(size=11, weight=500, color=text_muted),
            bgcolor='rgba(0,0,0,0)',
            borderwidth=0,
            itemsizing='constant',
            itemwidth=30,
            tracegroupgap=8
        ),
        hovermode="x unified",
        hoverlabel=dict(
            bgcolor='rgba(16,16,16,0.96)' if is_dark else 'rgba(255,255,255,0.96)',
            font_size=12,
            font_family="Inter",
            font_color=text_color,
            bordercolor=line_color,
            namelength=-1
        ),
        xaxis=dict(
            showgrid=False,
            zeroline=False,
            showline=True,
            linewidth=1,
            linecolor=line_color,
            tickfont=dict(size=10, color=text_muted),
            title=None,
            showspikes=True,
            spikemode='across',
            spikesnap='cursor',
            spikedash='dot',
            spikethickness=1,
            spikecolor=spike_color
        ),
        yaxis=dict(
            showgrid=True,
            gridwidth=1,
            gridcolor=grid_color,
            griddash='dot',
            zeroline=False,
            showline=False,
            tickfont=dict(size=10, color=text_muted),
            title=dict(text="Normalized (0–100)", font=dict(size=11, color=text_muted, weight=500)),
            tickformat=".0f",
            showspikes=False
        ),
        dragmode='zoom',
        modebar=dict(
            bgcolor='rgba(0,0,0,0)',
            color=text_muted,
            activecolor='#5b8def' if is_dark else '#4f7df3',
            orientation='v'
        )
    )
    
    # Range selector buttons
    fig.update_xaxes(
        rangeselector=dict(
            buttons=[
                dict(count=3, label="3M", step="month", stepmode="backward"),
                dict(count=6, label="6M", step="month", stepmode="backward"),
                dict(count=1, label="1Y", step="year", stepmode="backward"),
                dict(count=2, label="2Y", step="year", stepmode="backward"),
                dict(step="all", label="All")
            ],
            bgcolor='rgba(255,255,255,0.04)' if is_dark else 'rgba(0,0,0,0.03)',
            activecolor='#5b8def' if is_dark else '#4f7df3',
            font=dict(color=text_muted, size=10),
            x=1, y=1.12,
            xanchor='right', yanchor='top'
        ),
        rangeslider=dict(
            visible=True,
            thickness=0.06,
            bgcolor='rgba(255,255,255,0.02)' if is_dark else 'rgba(0,0,0,0.01)',
            borderwidth=0,
            range=[df['Date'].min(), df['Date'].max()]
        )
    )
    
    return fig


# ═══════════════════════════════════════════
#   Model Page Callbacks
# ═══════════════════════════════════════════

FRIENDLY_FEATURE_NAMES = {
    '10_YEAR_BOND_RATES(SA)': 'SA 10-Year Bond Rate',
    'VIX': 'VIX (Volatility Index)',
    'BRENT_OIL_PRICE': 'Brent Crude Oil Price',
}


@callback(
    Output('model-results-container', 'style'),
    Output('model-error', 'children'),
    Output('prediction-date', 'children'),
    Output('prediction-value', 'children'),
    Output('prediction-change', 'children'),
    Output('prediction-change', 'className'),
    Output('prediction-baseline-value', 'children'),
    Output('feature-contributions', 'children'),
    Output('model-history-chart', 'figure'),
    Output('model-info-content', 'children'),
    Output('model-description-content', 'children'),
    Output('model-prediction-data', 'data'),
    Input('model-prediction-trigger', 'data'),
    State('model-prediction-data', 'data'),
    State('theme-store', 'data'),
    prevent_initial_call=True
)
def run_model_prediction(trigger, existing_model_data, theme):
    result = None
    error_msg = ""
    
    # Check if we can use cached raw result
    if existing_model_data and isinstance(existing_model_data, dict) and 'raw_result' in existing_model_data:
        print("DEBUG: Using existing model raw result from session")
        result = existing_model_data['raw_result']
    
    # If no cached result and we have a trigger, run new prediction
    if not result and trigger:
        print(f"DEBUG: Running new model prediction. trigger={trigger}")
        try:
            result = predict_next_month()
        except Exception as e:
            traceback.print_exc()
            error_msg = str(e)
            if 'Model dependencies are unavailable' in error_msg:
                error_msg = 'Model dependencies missing. Install joblib and scikit-learn in your Python environment.'
            empty_fig = go.Figure().to_dict()
            return ({'display': 'none'}, f'Prediction failed: {error_msg}',
                    '', '', '', 'prediction-change', '', '', empty_fig, '', '', dash.no_update)

    # If still no result (not triggered and no cache), return empty
    if not result:
        empty_fig = go.Figure().to_dict()
        return ({'display': 'none'}, '', '', '', '', 'prediction-change',
                '', '', empty_fig, '', '', dash.no_update)

    # ── Prediction card ──
    pred_level = result['predicted_level']
    change_pct = result['predicted_change_pct']
    direction = result['direction']

    pred_value = f"R {pred_level:.4f}"
    if direction == 'weaken':
        change_text = f"▲ {abs(change_pct):.2f}% (ZAR weakens)"
        change_class = 'prediction-change change-negative'
    elif direction == 'strengthen':
        change_text = f"▼ {abs(change_pct):.2f}% (ZAR strengthens)"
        change_class = 'prediction-change change-positive'
    else:
        change_text = f"~ {abs(change_pct):.2f}% (stable)"
        change_class = 'prediction-change change-neutral'

    baseline_text = f"R {result['last_zar_usd']:.4f}  ({result['last_date']})"
    date_text = f"for {result['next_month_date']}"

    # ── Feature contributions ──
    contrib_rows = []
    for c in result['contributions']:
        feat_name = FRIENDLY_FEATURE_NAMES.get(c['feature'], c['feature'])
        coef = c['coefficient']
        contrib = c['contribution']
        direction_label = 'Weakens ZAR' if coef > 0 else 'Strengthens ZAR'
        bar_color = '#EF4444' if contrib > 0 else '#10B981'
        bar_width = min(abs(contrib) / max(abs(x['contribution']) for x in result['contributions']) * 100, 100)

        contrib_rows.append(
            html.Div(className='contrib-row', children=[
                html.Div(className='contrib-info', children=[
                    html.Span(feat_name, className='contrib-name'),
                    html.Span(direction_label, className='contrib-direction'),
                ]),
                html.Div(className='contrib-bar-container', children=[
                    html.Div(className='contrib-bar', style={
                        'width': f'{bar_width}%',
                        'backgroundColor': bar_color,
                    }),
                ]),
                html.Span(f'{contrib:+.3f}', className='contrib-value',
                           style={'color': bar_color}),
            ])
        )

    # ── Historical fit chart ──
    history = result.get('history', {})
    # Fallback to dark theme if theme is None
    is_dark = (theme == 'dark') if theme else True
    text_color = '#ffffff' if is_dark else '#0a0a0a'
    text_muted = '#6b6b6b' if is_dark else '#737373'
    grid_color = 'rgba(255,255,255,0.04)' if is_dark else 'rgba(0,0,0,0.04)'
    line_color = 'rgba(255,255,255,0.08)' if is_dark else 'rgba(0,0,0,0.08)'

    fig = go.Figure()
    
    # Ensure data is valid and not empty
    dates = history.get('dates', [])
    actual = history.get('actual', [])
    predicted = history.get('predicted', [])
    
    if dates and actual and predicted and len(dates) > 0:
        # Convert all values to native Python types to avoid serialization issues
        dates_clean = [str(d) for d in dates]
        actual_clean = [float(a) for a in actual]
        predicted_clean = [float(p) for p in predicted]
        
        # Ensure no NaN or infinite values
        valid_data = True
        for i, (d, a, p) in enumerate(zip(dates_clean, actual_clean, predicted_clean)):
            if not (d and a == a and p == p):  # Check for NaN
                valid_data = False
                break
        
        if valid_data:
            fig.add_trace(go.Scatter(
                x=dates_clean, y=actual_clean,
                name='Actual', mode='lines',
                line=dict(color='#E8E8E8' if is_dark else '#1A1A1A', width=2.5),
                hovertemplate='Actual: %{y:.4f}<extra></extra>'
            ))
            fig.add_trace(go.Scatter(
                x=dates_clean, y=predicted_clean,
                name='Predicted', mode='lines',
                line=dict(color='#5b8def', width=2, dash='dot'),
                hovertemplate='Predicted: %{y:.4f}<extra></extra>'
            ))
            # Next-month forecast point
            fig.add_trace(go.Scatter(
                x=[result['next_month_date']], y=[pred_level],
                name='Forecast', mode='markers',
                marker=dict(color='#F59E0B', size=10, symbol='diamond',
                            line=dict(width=2, color='#fff' if is_dark else '#000')),
                hovertemplate=f'<b>Forecast</b>: R {pred_level:.4f}<extra></extra>',
            ))
        else:
            fig.add_annotation(
                text="Invalid data detected",
                xref="paper", yref="paper",
                x=0.5, y=0.5, showarrow=False,
                font=dict(color=text_muted, size=14)
            )
    else:
        # Empty figure with message
        fig.add_annotation(
            text="No data available for chart",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False,
            font=dict(color=text_muted, size=14)
        )

    layout = {
        'template': None,
        'paper_bgcolor': 'rgba(0,0,0,0)',
        'plot_bgcolor': 'rgba(0,0,0,0)',
        'margin': dict(l=56, r=24, t=32, b=48),
        'autosize': True,
        'font': dict(family="Inter, sans-serif", size=12, color=text_color),
        'legend': dict(
            orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
            font=dict(size=11, color=text_muted), bgcolor='rgba(0,0,0,0)',
            borderwidth=0,
        ),
        'hovermode': "x unified",
        'hoverlabel': dict(
            bgcolor='rgba(16,16,16,0.96)' if is_dark else 'rgba(255,255,255,0.96)',
            font_size=12, font_family="Inter", font_color=text_color,
            bordercolor=line_color,
        ),
        'xaxis': dict(
            showgrid=False, zeroline=False, showline=True, linewidth=1,
            linecolor=line_color, tickfont=dict(size=10, color=text_muted),
        ),
        'yaxis': dict(
            showgrid=True, gridwidth=1, gridcolor=grid_color, griddash='dot',
            zeroline=False, showline=False,
            tickfont=dict(size=10, color=text_muted),
            title=dict(text="ZAR / USD", font=dict(size=11, color=text_muted)),
            tickformat=".2f",
        ),
    }
    
    fig.update_layout(layout)
    
    # Convert to dict to ensure proper serialization
    fig_dict = fig.to_dict()

    # ── Model info ──
    info = result['model_info']
    metrics = result.get('metrics', {})
    
    # Build model info layout
    info_items = html.Div(children=[
        html.H5('Model Specification', style={'fontSize': '0.8125rem', 'fontWeight': '600', 'color': 'var(--text-2)', 'marginBottom': '12px'}),
        html.Div(className='model-info-grid', children=[
            _info_pill('Type', 'ElasticNet (L1 = Lasso)', 'Statistical model using both L1 and L2 regularization to find the best predictors.'),
            _info_pill('Alpha', f"{info['alpha']:.4f}", 'Regularization strength: higher values mean more indicators are excluded to prevent overfitting.'),
            _info_pill('L1 Ratio', f"{info['l1_ratio']:.2f}", 'Balance between Lasso (1.0) and Ridge (0.0) regularization. Current is pure Lasso.'),
            _info_pill('Intercept', f"{info['intercept']:+.4f}", 'The base log-return forecast before considering macroeconomic indicator impacts.'),
            _info_pill('Training Obs', str(info['training_observations']), 'Number of historical monthly data points used to calibrate the model.'),
            _info_pill('Features', f"{info['n_selected']} / {info['n_features']} selected", 'The number of macroeconomic indicators the model found statistically significant.'),
            _info_pill('Date Range', info['training_date_range'], 'The historical window of data used for training the current model version.'),
            _info_pill('Target', 'Log-return ZAR/USD (% MoM)', 'The model predicts the percentage change in the exchange rate from one month to the next.'),
        ]),
        html.H5('In-Sample Performance Metrics', style={'fontSize': '0.8125rem', 'fontWeight': '600', 'color': 'var(--text-2)', 'marginTop': '24px', 'marginBottom': '12px'}),
        html.Div(className='model-info-grid', children=[
            _info_pill('MAE', f"R {metrics.get('mae', 0):.4f}", 'Mean Absolute Error: Average forecast error in Rands. Lower values indicate better precision.'),
            _info_pill('RMSE', f"R {metrics.get('rmse', 0):.4f}", 'Root Mean Squared Error: Similar to MAE but penalizes larger misses more heavily.'),
            _info_pill('R²', f"{metrics.get('r2', 0):.4f}", 'Explains how much of the ZAR/USD volatility is captured by the model (0 to 1 scale).'),
            _info_pill('MAPE', f"{metrics.get('mape', 0):.2f}%", 'Mean Absolute Percentage Error: Average error relative to the exchange rate level.'),
            _info_pill('Directional Accuracy', f"{metrics.get('directional_accuracy', 0):.1f}%", 'Percentage of months where the model correctly predicted if the ZAR would strengthen or weaken.'),
        ]),
    ])

    # Dynamic Description Generation
    top_feature = result['contributions'][0] if result['contributions'] else None
    feature_impact_text = ""
    if top_feature:
        feat_name = FRIENDLY_FEATURE_NAMES.get(top_feature['feature'], top_feature['feature'])
        impact_dir = "weakening" if top_feature['coefficient'] > 0 else "strengthening"
        feature_impact_text = f"The most significant driver for this period is {feat_name}, which is currently exerting a {impact_dir} pressure on the ZAR."

    direction_text = ""
    if direction == 'weaken':
        direction_text = f"The model forecasts a ZAR weakening of {abs(change_pct):.2f}% against the USD."
    elif direction == 'strengthen':
        direction_text = f"The model forecasts a ZAR strengthening of {abs(change_pct):.2f}% against the USD."
    else:
        direction_text = "The model expects the ZAR/USD exchange rate to remain relatively stable."

    perf_text = f"Historically, this model has achieved a directional accuracy of {metrics.get('directional_accuracy', 0):.1f}% during its training period, with a mean absolute error (MAE) of approximately {metrics.get('mae', 0):.2f} cents per Dollar."

    analysis_content = html.Div([
        html.P(f"Based on the latest data for {result['last_date']}, {direction_text} {feature_impact_text}"),
        html.P(perf_text),
        html.P("This forecast is based on an ElasticNet (Lasso) regression model that automatically selects the most relevant macroeconomic indicators. "
               "The model uses log-returns to ensure statistical stability and then converts the results back to level exchange rates (Rands per Dollar) for interpretability.")
    ])

    prediction_data = {
        'raw_result': result,
        'last_updated': str(datetime.datetime.now())
    }

    return ({'display': 'block'}, '', date_text, pred_value, change_text,
            change_class, baseline_text, contrib_rows, fig_dict, info_items, analysis_content, prediction_data)


def _info_pill(label, value, description=None):
    return html.Div(className='info-pill', children=[
        html.Div(className='info-pill-header', children=[
            html.Span(label, className='info-pill-label'),
            html.Span(str(value), className='info-pill-value'),
        ]),
        html.P(description, className='info-pill-description') if description else None
    ])
