import dash
from dash import html, dcc, callback, Input, Output, State
import dash_bootstrap_components as dbc
from logic.data_fetcher import fetch_fred_data, fetch_world_bank_gold_data, fetch_sa_inflation_hardcoded, process_data, save_to_supabase, replace_gold_price_column_in_supabase, FRED_API_KEY, SERIES_CONFIG
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
            html.Img(src=dash.get_asset_url('logo_light.svg'), className='logo-light', style={'height': '32px'}),
            html.Img(src=dash.get_asset_url('logo_dark.svg'), className='logo-dark', style={'height': '32px'})
        ]),
        link('nav-data', 'Data', '📊', 'data'),
        link('nav-model', 'Model', '🧠', 'model'),
        html.Div(className='sidebar-footer', children=[
            link('nav-signout', 'Sign out', '🚪', 'signout')
        ])
    ])


def data_tab_content():
    return html.Div(className='dashboard-card fade-in', children=[
        html.H3('Data', className='section-title', style={'marginBottom': '0.5rem'}),
        html.P("Fetch and analyse economic indicators to understand their impact on the ZAR/USD exchange rate. "
               "Visualise trends, compare predictors, and manage historical data from multiple sources.",
               style={'color': 'var(--text-secondary)', 'marginBottom': '2rem', 'fontSize': '0.95rem'}),
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
        
        # Visualisation Section
        html.Div(id='visualization-container', style={'marginTop': '2rem', 'display': 'none'}, children=[
            html.H3('Visualisation', className='section-title'),
            html.Div(className='api-key-input', children=[
                html.Label('Select Predictor to Compare with ZAR/USD:'),
                html.Div(id='custom-dropdown-root', className='custom-dropdown-root', children=[
                    html.Button(
                        id='custom-dropdown-control',
                        className='custom-dropdown-control',
                        n_clicks=0,
                        type='button',
                        children=[
                            html.Span(id='custom-dropdown-selected-label', className='custom-dropdown-selected-label', children='Select a factor...'),
                            html.Span(id='custom-dropdown-arrow', className='custom-dropdown-arrow', children='▼')
                        ]
                    ),
                    html.Div(
                        id='custom-dropdown-menu',
                        className='custom-dropdown-menu',
                        style={'display': 'none'},
                        children=[html.Div(id='custom-dropdown-options-list')]
                    )
                ]),
                html.Div(id='custom-dropdown-backdrop', className='custom-dropdown-backdrop', n_clicks=0, style={'display': 'none'}),
                dcc.Store(id='predictor-dropdown-value'),
                dcc.Store(id='predictor-dropdown-options-store'),
                dcc.Store(id='custom-dropdown-state', data=False)
            ]),
            dcc.Graph(id='zar-graph', className='dashboard-card')
        ]),
        
        html.Div(id='data-table-container', className='data-table-container', style={'marginTop': '1.5rem'})
    ])


def model_tab_content():
    return html.Div(className='dashboard-card fade-in', children=[
        html.H3('Model', className='section-title', style={'marginBottom': '0.5rem'}),
        html.P("Predict ZAR/USD trends using machine learning and statistical models. "
               "Leverage historical data to generate insights into future exchange rate movements.",
               style={'color': 'var(--text-secondary)', 'marginBottom': '2rem', 'fontSize': '0.95rem'}),
        html.Div('Model functionality coming soon.')
    ])


def layout():
    # Default active tab is 'data'
    active_tab = 'data'
    return html.Div(id='dashboard-container', className='page-transition', n_clicks=0, children=[
        html.Div(id='fetch-loading-bar', className='fetch-loading-bar', hidden=True),
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
        content = html.Div(className='dashboard-card fade-in', children=[
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


# Validation callback to prevent background fetch if clicks is 0
@callback(
    Output('fetch-trigger', 'data'),
    Output('data-error', 'children', allow_duplicate=True),
    Input('fetch-data-btn', 'n_clicks'),
    State('fetch-trigger', 'data'),
    prevent_initial_call=True
)
def validate_keys(n_clicks, current_trigger):
    if not n_clicks:
        return dash.no_update, dash.no_update
    
    return (current_trigger or 0) + 1, ""


# Fetch data using hardcoded API keys
@callback(
    Output('fetched-data', 'data'),
    Output('data-error', 'children', allow_duplicate=True),
    Output('data-table-container', 'children'),
    Output('predictor-dropdown-options-store', 'data'),
    Output('predictor-dropdown-value', 'data'),
    Output('visualization-container', 'style'),
    Input('fetch-trigger', 'data'),
    background=True,
    running=[
        (Output('fetch-data-btn', 'disabled'), True, False),
        (Output('progress-container', 'hidden'), False, True),
        (Output('fetch-loading-bar', 'hidden'), False, True),
        (Output('data-error', 'children'), "", dash.no_update)
    ],
    progress=[
        Output('fetch-progress-bar', 'value'),
        Output('progress-percentage', 'children'),
        Output('progress-status', 'children')
    ],
    prevent_initial_call=True
)
def fetch_data(set_progress, trigger_value):
    if trigger_value:
        print(f"DEBUG: fetch_data background callback started. trigger_value={trigger_value}")
        set_progress((0, '0%', 'Starting data fetch...'))
        
        try:
            # Use unified configuration from data_fetcher
            fred_series = {name: cfg['id'] for name, cfg in SERIES_CONFIG.items() if cfg['source'] == 'FRED'}
            
            def update_progress(percent, status_msg):
                print(f"DEBUG: Progress update: {percent}% - {status_msg}")
                set_progress((percent, f'{percent}%', f'Processing: {percent}% - {status_msg}'))
            
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
                return dash.no_update, 'Failed to fetch data. Please check your API keys and try again.', dash.no_update, dash.no_update, dash.no_update, dash.no_update
            
            print(f"DEBUG: Successfully fetched raw data with {len(raw)} rows. Processing...")
            set_progress((95, '95%', 'Processing and saving data...'))
            processed = process_data(raw, start_date='2018-01-31')
            
            if processed.empty:
                print("DEBUG: processed_df is empty")
                return dash.no_update, 'No data available in the requested date range.', dash.no_update, dash.no_update, dash.no_update, dash.no_update

            # Save to Supabase (All data since 2018-01-31)
            supabase_msg = ""
            try:
                print("DEBUG: Attempting to save to Supabase...")
                save_to_supabase(processed)
                replace_gold_price_column_in_supabase(wb_gold)
                print("DEBUG: Save to Supabase successful")
            except Exception as e:
                # Non-fatal: show message but still display data
                print(f"DEBUG Warning: Could not save to Supabase: {e}")
                supabase_msg = f" (Warning: Could not save to Supabase: {e})"

            # Prepare for display
            print("DEBUG: Preparing data for display...")
            df_all = processed.reset_index()
            df_all['Date'] = pd.to_datetime(df_all['Date']).dt.strftime('%Y-%m-%d')
            # Sort descending by date for display
            df_all = df_all.sort_values('Date', ascending=False)
            
            # Limit to 10 most recent observations for the table
            df_table = df_all.head(10)

            columns = ['Date'] + [c for c in df_table.columns if c != 'Date']

            header = html.Thead(html.Tr([html.Th(col) for col in columns]))
            body_rows = []
            for _, row in df_table.iterrows():
                tds = []
                for col in columns:
                    val = row[col]
                    if col == 'Date':
                        tds.append(html.Td(val))
                    elif pd.isna(val):
                        tds.append(html.Td('-'))
                    else:
                        try:
                            # Round to 4 decimals for display
                            formatted_val = f"{float(val):.4f}"
                            tds.append(html.Td(formatted_val))
                        except (ValueError, TypeError):
                            tds.append(html.Td(val))
                body_rows.append(html.Tr(tds))
            table = html.Table(className='custom-table', children=[header, html.Tbody(body_rows)])

            # Get predictors (all columns except Date and ZAR_USD)
            predictors = [c for c in df_all.columns if c not in ['Date', 'ZAR_USD']]
            
            # Use labels from SERIES_CONFIG for the options
            dropdown_options = [
                {'label': SERIES_CONFIG.get(p, {}).get('label', p), 'value': p} 
                for p in predictors
            ]
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
    Output('custom-dropdown-options-list', 'children'),
    Output('custom-dropdown-selected-label', 'children'),
    Input('predictor-dropdown-options-store', 'data'),
    Input('predictor-dropdown-value', 'data')
)
def render_custom_dropdown(options, selected_value):
    if not options:
        return [html.Div('No predictors available', className='custom-dropdown-empty')], 'Select a factor...'

    selected_label = 'Select a factor...'
    option_elements = []
    for option in options:
        is_selected = option['value'] == selected_value
        if is_selected:
            selected_label = option['label']

        option_elements.append(
            html.Div(
                [
                    html.Span(option['label']),
                    html.Span('✓', className='custom-dropdown-check')
                ],
                id={'type': 'predictor-option', 'index': option['value']},
                className='custom-dropdown-option active' if is_selected else 'custom-dropdown-option',
                n_clicks=0
            )
        )

    return option_elements, selected_label


@callback(
    Output('predictor-dropdown-value', 'data', allow_duplicate=True),
    Input({'type': 'predictor-option', 'index': dash.ALL}, 'n_clicks'),
    prevent_initial_call=True
)
def select_custom_dropdown_option(_):
    trigger_id = dash.callback_context.triggered_id
    if isinstance(trigger_id, dict) and trigger_id.get('type') == 'predictor-option':
        return trigger_id.get('index')
    return dash.no_update


@callback(
    Output('custom-dropdown-state', 'data'),
    Output('custom-dropdown-menu', 'style'),
    Output('custom-dropdown-arrow', 'style'),
    Output('custom-dropdown-backdrop', 'style'),
    Input('custom-dropdown-control', 'n_clicks'),
    Input('custom-dropdown-backdrop', 'n_clicks'),
    Input({'type': 'predictor-option', 'index': dash.ALL}, 'n_clicks'),
    Input('predictor-dropdown-value', 'data'),
    State('custom-dropdown-state', 'data'),
    prevent_initial_call=True
)
def toggle_custom_dropdown(control_clicks, backdrop_clicks, option_clicks, selected_value, is_open):
    trigger_id = dash.callback_context.triggered_id
    if trigger_id == 'custom-dropdown-control':
        next_state = not bool(is_open)
    elif trigger_id in ('custom-dropdown-backdrop', 'predictor-dropdown-value'):
        next_state = False
    elif isinstance(trigger_id, dict) and trigger_id.get('type') == 'predictor-option':
        next_state = False
    else:
        next_state = bool(is_open)

    menu_style = {'display': 'block' if next_state else 'none'}
    arrow_style = {'transform': 'rotate(180deg)' if next_state else 'rotate(0deg)'}
    backdrop_style = {'display': 'block' if next_state else 'none'}
    return next_state, menu_style, arrow_style, backdrop_style


@callback(
    Output('zar-graph', 'figure'),
    Input('predictor-dropdown-value', 'data'),
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
    hover_bgcolor = "rgba(15, 23, 42, 0.9)" if theme == 'dark' else "rgba(255, 255, 255, 0.9)"
    hover_font_color = "#f8fafc" if theme == 'dark' else "#0f172a"
    
    fig.update_layout(
        template=template,
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        margin=dict(l=40, r=40, t=40, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="x unified",
        hoverlabel=dict(
            bgcolor=hover_bgcolor,
            font_size=13,
            font_family="Inter",
            font_color=hover_font_color,
            bordercolor="rgba(51, 65, 85, 0.6)" if theme == 'dark' else "rgba(203, 213, 225, 0.8)"
        ),
        transition_duration=500
    )
    
    fig.update_yaxes(title_text="ZAR/USD", secondary_y=False)
    fig.update_yaxes(title_text=predictor, secondary_y=True)
    
    return fig
