import os
import dash
from dash import html, dcc, callback, Input, Output, State
import dash_bootstrap_components as dbc
from logic.data_fetcher import (
    fetch_fred_data, fetch_world_bank_gold_data, fetch_sa_inflation_hardcoded,
    process_data, save_to_supabase, replace_gold_price_column_in_supabase,
    FRED_API_KEY, SERIES_CONFIG, should_update_from_api, fetch_and_save_data
)
from logic.model import predict_next_month, fetch_data_from_supabase, get_scenario_baseline, scenario_predict
import pandas as pd
import plotly.graph_objects as go
import traceback
import datetime

dash.register_page(__name__, path='/dashboard')


# ═══════════════════════════════════════════
#   Helper: Scenario Slider UI Component
# ═══════════════════════════════════════════
def create_scenario_slider(slider_id, label, unit, min_val, max_val, current_val, active_val, step):
    """
    Generates an independent, cleanly laid out slider component.
    """
    # 1. Calculate evenly spaced marks for the numberline
    num_intervals = 4
    step_val = (max_val - min_val) / num_intervals if num_intervals > 0 else 1

    # Format decimals based on the step size
    decimals = 2 if step < 0.1 else (1 if step < 1 else 0)

    marks = {}
    for i in range(num_intervals + 1):
        mark_val = float(min_val + (i * step_val))
        marks[mark_val] = {
            'label': f'{mark_val:.{decimals}f}',
            'style': {'color': '#94a3b8', 'fontSize': '0.75rem', 'marginTop': '8px'}  # Muted gray for numberline
        }

    # 2. Inject the baseline "dot" marker
    marks[float(current_val)] = {
        'label': '●',
        'style': {'color': '#3b82f6', 'fontSize': '1.1rem', 'marginTop': '-16px', 'fontWeight': 'bold'}
    }

    # 3. Build the isolated layout
    return html.Div(className='scenario-slider-group', style={'marginBottom': '2.5rem'}, children=[

        # --- TOP ROW: Label and Active Value Display ---
        html.Div(style={'display': 'flex', 'justifyContent': 'space-between', 'alignItems': 'center',
                        'marginBottom': '12px'}, children=[
            html.Span(label, style={'fontWeight': '600', 'color': '#f8fafc', 'fontSize': '0.9rem'}),
            html.Span(
                f"{active_val:.{decimals}f} {unit}".strip(),
                id={'type': 'scenario-value-display', 'index': slider_id},
                style={'color': '#93c5fd', 'fontWeight': '600', 'fontSize': '0.9rem'}
            )
        ]),

        # --- BOTTOM ROW: The Slider Track ---
        html.Div(style={'position': 'relative', 'padding': '0 10px'}, children=[
            dcc.Slider(
                id={'type': 'scenario-slider', 'index': slider_id},
                min=float(min_val),
                max=float(max_val),
                step=float(step),
                value=float(active_val),
                marks=marks,
                tooltip=None,  # Ensure default tooltips stay off
                updatemode='drag',
                className='custom-dash-slider'
            )
        ])
    ])


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
            link('nav-scenario', 'Scenario', 'scenario'),
        ]),
        html.Div(className='sidebar-footer', children=[
            html.A(href='/profile', className='nav-link-profile', children=[
                html.Span('◉', className='nav-icon'),
                html.Span('Profile', className='nav-label'),
            ]),
            html.Div(id='nav-signout', className='nav-link-custom', children=[
                html.Span('→', className='nav-icon'),
                html.Span('Sign out', className='nav-label')
            ], n_clicks=0)
        ])
    ])


def topbar():
    now = datetime.datetime.now()
    date_str = f"{now.strftime('%a, %b')} {now.day}, {now.year}"
    return html.Div(className='topbar', children=[
        html.Div(className='topbar-breadcrumb', children=[
            html.Span('ZAR/USD Dashboard', className='topbar-root'),
            html.Span(' / ', className='topbar-sep'),
            html.Span('Data Explorer', id='topbar-page-name', className='topbar-page'),
        ]),
        html.Div(className='topbar-right', children=[
            html.Span(date_str, className='topbar-date'),
            html.A(href='/profile', className='topbar-user', children=[
                html.Div('?', id='topbar-avatar', className='topbar-avatar'),
                html.Span('User', id='topbar-username', className='topbar-username'),
            ]),
        ]),
    ])


def _render_loading_state(id_prefix, title, subtitle, visible=True):
    style = {'display': 'flex'} if visible else {'display': 'none'}
    return html.Div(id=f'{id_prefix}-loading', className='scenario-loading-state', style=style, children=[
        html.Div(className='empty-state', children=[
            html.Div(className='futuristic-loader', children=[
                html.Div(className='ring'),
                html.Div(className='ring'),
                html.Div(className='ring'),
                html.Div(className='core'),
            ]),
            html.H4(title),
            html.P(subtitle),
        ])
    ])


def data_tab_content(existing_data=None):
    viz_style = {'display': 'block', 'marginTop': '2rem'} if existing_data else {'display': 'none'}
    return html.Div(id='data-tab', className='tab-content', children=[
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

        html.Div(id='data-error', className='error-message'),

        # Loading state
        _render_loading_state('data', 'Analyzing historical data...',
                             'Connecting to database and processing macroeconomic series.',
                             visible=not existing_data),

        # Visualisation Section
        html.Div(id='visualization-container', className='viz-container', style=viz_style, children=[
            # Variable Selector Bar
            html.Div(className='predictor-bar', children=[
                html.Div(className='predictor-bar-header', children=[
                    html.Span('Variables', className='predictor-bar-title'),
                    # Plot mode segmented control
                    html.Div(className='plot-mode-toggle', children=[
                        html.Button('Time Series', id='mode-timeseries', className='plot-mode-btn plot-mode-active', n_clicks=0),
                        html.Button('Compare', id='mode-compare', className='plot-mode-btn', n_clicks=0),
                        html.Button('Correlation', id='mode-correlation', className='plot-mode-btn', n_clicks=0),
                    ]),
                    html.Button(
                        id='toggle-table-btn',
                        className='btn-ghost',
                        children='Show Table',
                        n_clicks=0
                    )
                ]),
                # Variable checkboxes (Time Series mode)
                html.Div(id='predictor-checkboxes-container', className='predictor-chips'),
                # Compare mode checkboxes (max 3 variables)
                html.Div(id='compare-checkboxes-container', className='predictor-chips', style={'display': 'none'}),
                html.Div(id='compare-hint', className='compare-hint', style={'display': 'none'}, children=[
                    html.Span('Select 2 variables for a line plot (X vs Y), or 3 for a 3D surface.', className='compare-hint-text'),
                ]),
            ]),

            # Hero Chart — 3D tilt-enabled
            dcc.Graph(
                id='zar-graph',
                className='hero-chart chart-3d',
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

        # ── AI Chat Panel ──
        html.Div(id='chat-panel', className='chat-panel', children=[
            html.Div(className='chat-header', children=[
                html.Div(className='chat-header-left', children=[
                    html.Span('✦', className='chat-header-icon'),
                    html.Span('AI Assistant', className='chat-header-title'),
                ]),
                html.Button('✕', id='chat-close-btn', className='chat-close-btn', n_clicks=0),
            ]),
            html.Div(id='chat-messages', className='chat-messages', children=[
                html.Div(className='chat-message chat-message-ai', children=[
                    html.Div("Ask me about the data on the chart — trends, variables, ZAR/USD dynamics, or economics.",
                             className='chat-bubble chat-bubble-ai')
                ])
            ]),
            html.Div(className='chat-input-area', children=[
                dcc.Input(
                    id='chat-input',
                    type='text',
                    placeholder='Ask about the chart or economics...',
                    className='chat-input',
                    debounce=False,
                    n_submit=0,
                ),
                html.Button('→', id='chat-send-btn', className='chat-send-btn', n_clicks=0),
            ]),
        ]),

        # Chat toggle FAB
        html.Button(
            html.Span('✦', className='chat-fab-icon'),
            id='chat-toggle-btn',
            className='chat-fab',
            n_clicks=0,
        ),
        # Hidden dummy for clientside loading callback
        html.Div(id='chat-loading-trigger', style={'display': 'none'}),
    ])


def model_tab_content(existing_model_data=None):
    model_style = {'display': 'block'} if existing_model_data else {'display': 'none'}
    return html.Div(id='model-tab', className='tab-content', style={'display': 'none'}, children=[
        html.Div(className='page-header', children=[
            html.Div(children=[
                html.H2('Model Forecasts', className='page-title'),
                html.P("ZAR/USD estimates via frozen ElasticNet (Lasso) model.",
                       className='page-subtitle'),
            ]),
            html.Div(className='page-actions', children=[
                html.Div(id='model-status-display', className='status-badge'),
            ])
        ]),

        html.Div(id='model-error', className='error-message'),

        # Loading state
        _render_loading_state('model', 'Running model prediction...',
                             'Analyzing latest macroeconomic drivers and generating forecast.',
                             visible=not existing_model_data),

        html.Div(id='model-results-container', style=model_style, children=[
            # Multi-horizon Forecast Table (Replaces Prediction Card)
            html.Div(className='model-card', children=[
                html.H4('Multi-Horizon ZAR/USD Estimates', className='card-title'),
                html.P('Fair Value vs Spot-based Actual estimates for various horizons.', className='card-subtitle'),
                html.Div(id='forecast-table-container', className='forecast-table-wrapper')
            ]),

            # Feature Contributions
            html.Div(className='model-card', children=[
                html.H4('Key Macro Drivers', className='card-title'),
                html.P('Non-zero model coefficients and their current contribution to the fair value.',
                       className='card-subtitle'),
                html.Div(id='feature-contributions'),
            ]),

            # Historical Fit Chart — 3D tilt
            html.Div(id='model-visualization-container', className='model-card chart-3d', children=[
                html.H4('Historical Fit', className='card-title'),
                html.P('Model predictions vs actual ZAR/USD (level space)',
                       className='card-subtitle'),
                dcc.Graph(
                    id='model-history-chart',
                    className='model-chart',
                    style={'height': '420px'},
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
                html.H4('Model Specification & Forecast Equilibrium', className='card-title'),
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

            # Diagnostic Plots Section
            html.Div(className='model-card', children=[
                html.H4('Diagnostic Plots', className='card-title'),
                html.Div(id='diagnostics-container'),
            ]),
        ]),
    ])


def scenario_tab_content():
    return html.Div(id='scenario-tab', className='tab-content', style={'display': 'none'}, children=[
        html.Div(className='page-header', children=[
            html.Div(children=[
                html.H2('Scenario Analysis', className='page-title'),
                html.P("Adjust macroeconomic predictors to model hypothetical ZAR/USD outcomes.",
                       className='page-subtitle'),
            ]),
            html.Div(className='page-actions', children=[
                html.Button('💾 Save Scenario', id='scenario-save-btn', className='btn-primary', n_clicks=0,
                            style={'marginRight': '8px'}),
                html.Button('Reset All', id='scenario-reset-btn', className='btn-ghost', n_clicks=0),
                html.Div(id='scenario-status-display', className='status-badge', style={'marginLeft': '12px'}),
            ])
        ]),

        html.Div(id='scenario-error', className='error-message'),

        # Loading state while baseline is fetched
        _render_loading_state('scenario', 'Loading scenario engine...',
                             'Fetching current predictor values and model configuration.',
                             visible=True),

        html.Div(id='scenario-content', style={'display': 'none'}, children=[
            # Top row: Scenario vs Base comparison cards
            html.Div(className='scenario-comparison-row', children=[
                # Base prediction card
                html.Div(className='model-card scenario-card scenario-card-base', children=[
                    html.Div(className='scenario-card-header', children=[
                        html.Span('Base Forecast', className='scenario-card-label'),
                        html.Span('Current Values', className='scenario-card-tag tag-neutral'),
                    ]),
                    html.Div(id='scenario-base-value', className='scenario-card-value'),
                    html.Div(id='scenario-base-change', className='scenario-card-change'),
                ]),

                # Arrow
                html.Div(className='scenario-arrow', children='→'),

                # Scenario prediction card
                html.Div(className='model-card scenario-card scenario-card-scenario', children=[
                    html.Div(className='scenario-card-header', children=[
                        html.Span('Scenario Forecast', className='scenario-card-label'),
                        html.Span('Modified Values', className='scenario-card-tag tag-accent'),
                    ]),
                    html.Div(id='scenario-result-value', className='scenario-card-value'),
                    html.Div(id='scenario-result-change', className='scenario-card-change'),
                ]),

                # Delta card
                html.Div(className='model-card scenario-card scenario-card-delta', children=[
                    html.Div(className='scenario-card-header', children=[
                        html.Span('Net Impact', className='scenario-card-label'),
                        html.Span(id='scenario-delta-tag', className='scenario-card-tag'),
                    ]),
                    html.Div(id='scenario-delta-value', className='scenario-card-value'),
                    html.Div(id='scenario-delta-pct', className='scenario-card-change'),
                ]),
            ]),

            # Main content: sliders on left, waterfall on right
            html.Div(className='scenario-main-row', children=[
                # Predictor sliders panel
                html.Div(className='model-card scenario-sliders-panel', children=[
                    html.Div(className='scenario-panel-header', children=[
                        html.H4('Predictor Adjustments', className='card-title'),
                        html.P('Drag sliders to model hypothetical changes. The dot marks the current value.',
                               className='card-subtitle'),
                    ]),
                    html.Div(id='scenario-sliders-container'),
                ]),

                # Waterfall chart — 3D tilt
                html.Div(className='model-card scenario-waterfall-panel chart-3d', children=[
                    html.H4('Impact Waterfall', className='card-title'),
                    html.P('Contribution change per feature from base to scenario (scaled space)',
                           className='card-subtitle'),
                    dcc.Graph(
                        id='scenario-waterfall-chart',
                        className='scenario-chart',
                        config={
                            'displayModeBar': 'hover',
                            'displaylogo': False,
                            'responsive': True,
                        },
                    ),
                ]),
            ]),

            # Sensitivity table
            html.Div(className='model-card', style={'marginTop': '1.5vh'}, children=[
                html.H4('Scenario Summary', className='card-title'),
                html.P('Side-by-side comparison of current vs scenario predictor values',
                       className='card-subtitle'),
                html.Div(id='scenario-summary-table'),
            ]),

            # Saved Scenarios Comparison (Premium Feature)
            html.Div(id='scenario-comparison-section', style={'marginTop': '1.5vh', 'display': 'none'}, children=[
                html.Div(className='model-card', children=[
                    html.Div(className='scenario-comparison-header', children=[
                        html.Div(children=[
                            html.H4('📊 Scenario Comparison', className='card-title'),
                            html.P('Compare saved scenarios to identify best and worst case outcomes',
                                   className='card-subtitle'),
                        ]),
                        html.Button('Clear All', id='scenario-clear-all-btn', className='btn-ghost btn-sm', n_clicks=0),
                    ]),
                    html.Div(id='saved-scenarios-list', className='saved-scenarios-grid'),
                    dcc.Graph(
                        id='scenario-comparison-chart',
                        className='scenario-comparison-chart',
                        config={'displayModeBar': 'hover', 'displaylogo': False, 'responsive': True},
                    ),
                ]),
            ]),
        ]),
    ])


def layout():
    return html.Div(id='dashboard-container', className='page-transition sidebar-collapsed', n_clicks=0, children=[
        sidebar('data'),
        html.Div(className='content-area', id='content-area', children=[
            topbar(),
            html.Div(id='content-body', className='content-body', children=[
                data_tab_content(),
                model_tab_content(),
                scenario_tab_content(),
            ])
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
    Input('nav-scenario', 'n_clicks'),
    Input('nav-signout', 'n_clicks'),
    State('dashboard-tab', 'data'),
    prevent_initial_call=True
)
def set_active_tab(data_clicks, model_clicks, scenario_clicks, signout_clicks, current_tab):
    ctx = dash.callback_context
    if not ctx.triggered:
        return current_tab or 'data'
    trigger = ctx.triggered[0]['prop_id'].split('.')[0]
    if trigger == 'nav-data':
        return 'data'
    if trigger == 'nav-model':
        return 'model'
    if trigger == 'nav-scenario':
        return 'scenario'
    if trigger == 'nav-signout':
        return 'signout'
    return current_tab or 'data'


# Update sidebar active classes and tab visibility via clientside callback (instant, no server roundtrip)
dash.clientside_callback(
    """
    function(activeTab) {
        var tabIds = ['data-tab', 'model-tab', 'scenario-tab'];
        var tabKeys = ['data', 'model', 'scenario'];
        var tabNames = {
            'data': 'Data Explorer',
            'model': 'Model Forecasts',
            'scenario': 'Scenario Analysis'
        };

        // Hide all tabs first
        tabIds.forEach(function(id) {
            var el = document.getElementById(id);
            if (el) el.style.display = 'none';
        });

        // Show active tab with smooth fade-in animation
        for (var i = 0; i < tabKeys.length; i++) {
            if (tabKeys[i] === activeTab) {
                var activeEl = document.getElementById(tabIds[i]);
                if (activeEl) {
                    activeEl.style.display = 'block';
                    activeEl.style.animation = 'none';
                    void activeEl.offsetWidth; // force reflow
                    activeEl.style.animation = 'tabFadeIn 0.32s cubic-bezier(0,0,0.2,1)';
                }
                break;
            }
        }

        // Update topbar breadcrumb page name
        var breadcrumb = document.getElementById('topbar-page-name');
        if (breadcrumb && tabNames[activeTab]) {
            breadcrumb.innerText = tabNames[activeTab];
        }

        // Update nav link classes
        var dataCls = (activeTab === 'data') ? 'nav-link-custom active' : 'nav-link-custom';
        var modelCls = (activeTab === 'model') ? 'nav-link-custom active' : 'nav-link-custom';
        var scenarioCls = (activeTab === 'scenario') ? 'nav-link-custom active' : 'nav-link-custom';
        var signoutCls = (activeTab === 'signout') ? 'nav-link-custom active' : 'nav-link-custom';

        return [dataCls, modelCls, scenarioCls, signoutCls];
    }
    """,
    [Output('nav-data', 'className'),
     Output('nav-model', 'className'),
     Output('nav-scenario', 'className'),
     Output('nav-signout', 'className')],
    Input('dashboard-tab', 'data')
)


@callback(
    Output('topbar-avatar', 'children'),
    Output('topbar-username', 'children'),
    Input('user-session', 'data'),
)
def update_topbar_user(session_data):
    if session_data and session_data.get('username'):
        username = session_data['username']
        return username[0].upper(), username
    return '?', 'User'


# Handle signout: clear session
@callback(
    Output('user-session', 'data', allow_duplicate=True),
    Input('nav-signout', 'n_clicks'),
    prevent_initial_call=True
)
def perform_signout(signout_clicks):
    if signout_clicks:
        return None
    return dash.no_update


# Trigger data fetch and model prediction automatically (fallback/sync)
@callback(
    Output('fetch-trigger', 'data', allow_duplicate=True),
    Output('model-prediction-trigger', 'data', allow_duplicate=True),
    Output('scenario-trigger', 'data', allow_duplicate=True),
    Input('dashboard-tab', 'data'),
    State('fetch-trigger', 'data'),
    State('model-prediction-trigger', 'data'),
    State('scenario-trigger', 'data'),
    State('fetched-data', 'data'),
    State('model-prediction-data', 'data'),
    State('scenario-baseline-data', 'data'),
    prevent_initial_call=True
)
def auto_trigger_callbacks(active_tab, current_fetch_trigger, current_model_trigger, current_scenario_trigger,
                           existing_data, existing_model_data, existing_scenario_data):
    fetch_trigger = dash.no_update
    model_trigger = dash.no_update
    scenario_trigger = dash.no_update

    # Fallback: if data is missing, ensure trigger is at least 1
    if active_tab == 'data' and not existing_data:
        fetch_trigger = (current_fetch_trigger or 0) + 1

    if active_tab == 'model' and not existing_model_data:
        model_trigger = (current_model_trigger or 0) + 1

    if active_tab == 'scenario' and not existing_scenario_data:
        scenario_trigger = (current_scenario_trigger or 0) + 1

    return fetch_trigger, model_trigger, scenario_trigger


def _generate_data_table(df_all):
    if df_all is None or (isinstance(df_all, pd.DataFrame) and df_all.empty) or (
            isinstance(df_all, list) and not df_all):
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
                prev_val = df_sorted.iloc[i - 1][col]
                curr_val = df_sorted.iloc[i][col]
                if pd.notna(prev_val) and pd.notna(curr_val) and prev_val != 0:
                    pct_change = ((curr_val - prev_val) / prev_val) * 100
                    row_data[col] = pct_change
                else:
                    row_data[col] = None
        pct_change_data.append(row_data)

    df_pct = pd.DataFrame(pct_change_data)
    df_pct = df_pct.sort_values('Date', ascending=False).head(10)

    # Build table — all variables treated equally, ZAR/USD first
    all_vars = [c for c in df_pct.columns if c != 'Date']
    if 'ZAR_USD' in all_vars:
        all_vars.remove('ZAR_USD')
        all_vars.insert(0, 'ZAR_USD')

    user_friendly_columns = ['Date']
    for v in all_vars:
        friendly_name = 'ZAR/USD' if v == 'ZAR_USD' else SERIES_CONFIG.get(v, {}).get('label', v)
        if len(friendly_name) > 25:
            friendly_name = friendly_name.replace('(', '\n(').replace(' for ', '\n')
            friendly_name = '\n'.join([line.strip() for line in friendly_name.split('\n') if line.strip()])
        user_friendly_columns.append(friendly_name)

    header = html.Thead(html.Tr(
        [html.Th(col, style={'textAlign': 'center', 'whiteSpace': 'pre-line', 'fontSize': '0.75rem'}) for col in
         user_friendly_columns]))
    body_rows = []
    for _, row in df_pct.iterrows():
        tds = [html.Td(row['Date'], style={'fontWeight': '500'})]
        for col in all_vars:
            val = row.get(col)
            if pd.isna(val):
                tds.append(html.Td('-', style={'textAlign': 'center'}))
            else:
                if col == 'ZAR_USD':
                    color = '#EF4444' if val > 0 else '#10B981' if val < 0 else '#6b6b6b'
                    tds.append(html.Td(f"{val:+.2f}%", style={'color': color, 'fontWeight': '700', 'textAlign': 'center',
                                                              'fontSize': '1.05em'}))
                else:
                    color = '#10B981' if val > 0 else '#EF4444' if val < 0 else '#6b6b6b'
                    tds.append(html.Td(f"{val:+.2f}%", style={'color': color, 'fontWeight': '600', 'textAlign': 'center'}))
        body_rows.append(html.Tr(tds))

    return html.Table(className='custom-table', children=[header, html.Tbody(body_rows)])


@callback(
    Output('fetch-status-display', 'children'),
    Output('visualization-container', 'style', allow_duplicate=True),
    Output('data-table-container', 'children'),
    Output('data-loading', 'style'),
    Input('dashboard-tab', 'data'),
    Input('fetched-data', 'data'),
    Input('fetched-data-status', 'data'),
    prevent_initial_call='initial_duplicate'
)
def sync_data_tab_ui(active_tab, data, status_info):
    if active_tab != 'data':
        return dash.no_update, dash.no_update, dash.no_update, dash.no_update

    status_msg = ""
    if status_info:
        # Reconstruct the status badge
        status_msg = html.Span(status_info.get('text', ''), style={'color': status_info.get('color', '#6b6b6b')})

    viz_style = {'display': 'block', 'marginTop': '2rem'} if data else {'display': 'none'}
    loading_style = {'display': 'none'} if data else {'display': 'flex'}

    # Use the helper to rebuild the table from persisted data
    table = _generate_data_table(data) if data else ""

    return status_msg, viz_style, table, loading_style


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
    prevent_initial_call='initial_duplicate',
    running=[
        (Output('data-error', 'children'), "", ""),
        (Output('data-loading', 'style'), {'display': 'flex'}, {'display': 'none'}),
    ],
)
def fetch_data(trigger_value, existing_data, existing_options, existing_selected, existing_status):
    import pandas as pd
    import time

    if trigger_value:
        # If we already have data in session, just return it to re-populate UI
        if existing_data:
            return existing_data, "", existing_options, existing_selected, existing_status

        try:
            # Check if we should update from API or Supabase
            use_api = should_update_from_api()

            if not use_api:
                processed = fetch_data_from_supabase()
                status_data = {'text': '● Live (Supabase)', 'color': '#10B981'}
                wb_gold = pd.Series()
            else:
                # Use unified configuration from data_fetcher
                fred_series = {name: cfg['id'] for name, cfg in SERIES_CONFIG.items() if cfg['source'] == 'FRED'}

                raw = fetch_fred_data(fred_series, api_key=FRED_API_KEY, progress_callback=None)

                # Fetch GOLD_PRICE from World Bank monthly commodity data.
                wb_gold = fetch_world_bank_gold_data(start_date='2009-12-31')
                if not wb_gold.empty:
                    # Use concat instead of assignment to allow the index to expand to the latest available data.
                    raw = pd.concat([raw, wb_gold.to_frame(name='GOLD_PRICE')], axis=1)

                # Fetch SA_INFLATION (Hardcoded)
                sa_inflation = (fetch_sa_inflation_hardcoded
                                ())
                raw = pd.concat([raw, sa_inflation], axis=1)

                if raw.empty:
                    return dash.no_update, 'Failed to fetch data from APIs.', dash.no_update, dash.no_update, dash.no_update

                processed = process_data(raw, start_date='2009-12-31')
                status_data = {'text': '● Updated from API', 'color': '#3B82F6'}

            if processed.empty:
                return dash.no_update, 'No data available.', dash.no_update, dash.no_update, dash.no_update

            # Save to Supabase only if we fetched from API
            if use_api:
                try:
                    save_to_supabase(processed)
                    if not wb_gold.empty:
                        replace_gold_price_column_in_supabase(wb_gold)
                except Exception as e:
                    print(f"Warning: Could not save to Supabase: {e}")
                    status_data = {'text': '● Updated (Supabase error)', 'color': '#F59E0B'}

            # Prepare for display
            df_all = processed.reset_index()
            df_all['Date'] = pd.to_datetime(df_all['Date']).dt.strftime('%Y-%m-%d')

            # Round numeric columns to reduce JSON payload size in dcc.Store
            numeric_cols = df_all.select_dtypes(include='number').columns
            df_all[numeric_cols] = df_all[numeric_cols].round(6)

            # Get all variables (all columns except Date), ZAR/USD first
            all_vars = [c for c in df_all.columns if c != 'Date']
            # Put ZAR_USD first if present
            if 'ZAR_USD' in all_vars:
                all_vars.remove('ZAR_USD')
                all_vars.insert(0, 'ZAR_USD')

            # Use labels from SERIES_CONFIG for the options
            dropdown_options = [
                {'label': SERIES_CONFIG.get(p, {}).get('label', p) if p != 'ZAR_USD' else 'ZAR/USD Exchange Rate', 'value': p}
                for p in all_vars
            ]
            # Default: ZAR_USD + first predictor selected
            default_predictors = ['ZAR_USD'] + all_vars[1:2] if len(all_vars) >= 2 else all_vars[:1]

            return df_all.to_dict('records'), "", dropdown_options, default_predictors, status_data
        except Exception as e:
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
        return html.Div('No variables available', style={'color': 'var(--text-secondary)'})

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


# ── Plot mode switching ──
@callback(
    Output('plot-mode', 'data'),
    Output('mode-timeseries', 'className'),
    Output('mode-compare', 'className'),
    Output('mode-correlation', 'className'),
    Output('predictor-checkboxes-container', 'style'),
    Output('compare-checkboxes-container', 'style'),
    Output('compare-hint', 'style'),
    Input('mode-timeseries', 'n_clicks'),
    Input('mode-compare', 'n_clicks'),
    Input('mode-correlation', 'n_clicks'),
    prevent_initial_call=True
)
def switch_plot_mode(ts_clicks, cmp_clicks, co_clicks):
    ctx = dash.callback_context
    if not ctx.triggered:
        return (dash.no_update,) * 7
    trigger = ctx.triggered[0]['prop_id'].split('.')[0]

    base = 'plot-mode-btn'
    active = 'plot-mode-btn plot-mode-active'
    hide = {'display': 'none'}

    if trigger == 'mode-compare':
        return 'compare', base, active, base, hide, {}, {}
    elif trigger == 'mode-correlation':
        return 'correlation', base, base, active, hide, hide, hide
    else:
        return 'timeseries', active, base, base, {}, hide, hide


# Render compare checkboxes (same chip style, max 3, grey out when full)
@callback(
    Output('compare-checkboxes-container', 'children'),
    Input('predictor-dropdown-options-store', 'data'),
    Input('selected-compare-vars', 'data'),
    Input('dashboard-tab', 'data'),
)
def render_compare_checkboxes(options, selected_compare, active_tab):
    if active_tab != 'data' or not options:
        return dash.no_update

    selected_compare = selected_compare or []
    selected_set = set(selected_compare)
    at_max = len(selected_set) >= 3
    checkboxes = []

    for option in options:
        is_checked = option['value'] in selected_set
        disabled = at_max and not is_checked
        item_class = 'predictor-checkbox-item'
        if disabled:
            item_class += ' chip-disabled'

        checkboxes.append(
            html.Div(
                className=item_class,
                children=[
                    dcc.Checklist(
                        id={'type': 'compare-checkbox', 'index': option['value']},
                        options=[{'label': option['label'], 'value': option['value'],
                                  'disabled': disabled}],
                        value=[option['value']] if is_checked else [],
                        className='custom-checklist',
                        labelStyle={'display': 'flex', 'alignItems': 'center', 'cursor': 'pointer' if not disabled else 'not-allowed'}
                    )
                ]
            )
        )

    return checkboxes


# Update selected-compare-vars from compare checkboxes
@callback(
    Output('selected-compare-vars', 'data'),
    Input({'type': 'compare-checkbox', 'index': dash.ALL}, 'value'),
    prevent_initial_call=True
)
def update_selected_compare(checkbox_values):
    if not checkbox_values:
        return dash.no_update

    selected = []
    ctx = dash.callback_context
    for i, values in enumerate(checkbox_values):
        if values:
            trigger_id = ctx.inputs_list[0][i]['id']
            selected.append(trigger_id['index'])

    return selected[:3]


# Set default compare selection when data first loads
@callback(
    Output('selected-compare-vars', 'data', allow_duplicate=True),
    Input('predictor-dropdown-options-store', 'data'),
    State('selected-compare-vars', 'data'),
    prevent_initial_call='initial_duplicate'
)
def init_compare_defaults(options, existing):
    if existing:
        return dash.no_update
    if not options:
        return []
    # Default: ZAR_USD + first other variable
    defaults = ['ZAR_USD']
    for o in options:
        if o['value'] != 'ZAR_USD':
            defaults.append(o['value'])
            break
    return defaults


@callback(
    Output('zar-graph', 'figure'),
    Input('selected-predictors', 'data'),
    Input('fetched-data', 'data'),
    Input('dashboard-tab', 'data'),
    Input('plot-mode', 'data'),
    Input('selected-compare-vars', 'data'),
    State('theme-store', 'data'),
    State('predictor-dropdown-options-store', 'data')
)
def update_graph(selected_predictors, data, active_tab, plot_mode, compare_vars, theme, options):
    if active_tab != 'data' or not data:
        return go.Figure()

    plot_mode = plot_mode or 'timeseries'

    df = pd.DataFrame(data)
    df['Date'] = pd.to_datetime(df['Date'])
    df = df.sort_values('Date')

    # Shared theme colors — Apple-inspired palette
    is_dark = theme == 'dark'
    grid_color = 'rgba(255,255,255,0.03)' if is_dark else 'rgba(0,0,0,0.03)'
    line_color = 'rgba(255,255,255,0.06)' if is_dark else 'rgba(0,0,0,0.06)'
    text_color = '#f5f5f7' if is_dark else '#1d1d1f'
    text_muted = '#86868b' if is_dark else '#6e6e73'
    spike_color = 'rgba(255,255,255,0.15)' if is_dark else 'rgba(0,0,0,0.1)'
    label_map = {opt['value']: opt['label'] for opt in (options or [])}

    # Premium color palette — refined for depth
    color_palette = [
        '#F59E0B', '#EC4899', '#10B981', '#8B5CF6', '#F97316',
        '#EF4444', '#22C55E', '#D946EF', '#EAB308', '#14B8A6',
        '#A855F7', '#84CC16', '#F43F5E', '#FB923C', '#4ADE80',
        '#C084FC', '#06B6D4', '#0EA5E9', '#FACC15', '#FB7185',
    ]

    font_family = "-apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Inter', 'Segoe UI', sans-serif"
    base_layout = dict(
        template=None,
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        autosize=True,
        font=dict(family=font_family, size=12, color=text_color),
        modebar=dict(bgcolor='rgba(0,0,0,0)', color=text_muted,
                     activecolor='#5b8def' if is_dark else '#4f7df3', orientation='v'),
    )

    # ═══ CORRELATION MATRIX ═══
    if plot_mode == 'correlation':
        import numpy as np
        numeric_cols = [c for c in df.columns if c != 'Date' and df[c].dtype in ['float64', 'int64', 'float32']]
        if 'ZAR_USD' in numeric_cols:
            numeric_cols.remove('ZAR_USD')
            numeric_cols.insert(0, 'ZAR_USD')

        friendly_names = [label_map.get(c, c) for c in numeric_cols]
        # Truncate long labels
        friendly_names = [n[:20] + '…' if len(n) > 20 else n for n in friendly_names]

        corr = df[numeric_cols].corr()
        z = corr.values

        fig = go.Figure(data=go.Heatmap(
            z=z,
            x=friendly_names,
            y=friendly_names,
            colorscale=[[0, '#EF4444'], [0.5, '#1a1a2e' if is_dark else '#f8f8fc'], [1, '#10B981']],
            zmin=-1, zmax=1,
            text=np.round(z, 2),
            texttemplate='%{text}',
            textfont=dict(size=10, color=text_color),
            hovertemplate='%{x} vs %{y}<br>r = %{z:.3f}<extra></extra>',
            colorbar=dict(
                title=dict(text='r', font=dict(color=text_muted, size=11)),
                tickfont=dict(color=text_muted, size=10),
                outlinewidth=0,
            ),
        ))

        fig.update_layout(
            **base_layout,
            margin=dict(l=120, r=40, t=30, b=120),
            xaxis=dict(tickfont=dict(size=9, color=text_muted), tickangle=-45, showgrid=False),
            yaxis=dict(tickfont=dict(size=9, color=text_muted), showgrid=False, autorange='reversed'),
        )
        return fig

    # ═══ COMPARE MODE — 2D lines or 3D surface ═══
    if plot_mode == 'compare':
        import numpy as np

        compare_vars = compare_vars or []
        # Filter to valid columns
        cmp = [v for v in compare_vars if v in df.columns]
        if len(cmp) < 2:
            return go.Figure()

        compare_x = cmp[0]
        compare_y = cmp[1]
        compare_z = cmp[2] if len(cmp) >= 3 else None

        x_label = label_map.get(compare_x, compare_x)
        y_label = label_map.get(compare_y, compare_y)
        use_3d = compare_z is not None

        if use_3d:
            # ── 3D Surface: Z as a function of X and Y ──
            z_label = label_map.get(compare_z, compare_z)
            sub = df[[compare_x, compare_y, compare_z]].dropna()

            if len(sub) < 4:
                return go.Figure()

            from scipy.interpolate import griddata
            xi = np.linspace(sub[compare_x].min(), sub[compare_x].max(), 40)
            yi = np.linspace(sub[compare_y].min(), sub[compare_y].max(), 40)
            xi_grid, yi_grid = np.meshgrid(xi, yi)
            zi_grid = griddata(
                (sub[compare_x].values, sub[compare_y].values),
                sub[compare_z].values,
                (xi_grid, yi_grid),
                method='cubic',
            )
            # Fill NaN edges with nearest-neighbor
            zi_nearest = griddata(
                (sub[compare_x].values, sub[compare_y].values),
                sub[compare_z].values,
                (xi_grid, yi_grid),
                method='nearest',
            )
            mask = np.isnan(zi_grid)
            zi_grid[mask] = zi_nearest[mask]

            fig = go.Figure(data=go.Surface(
                x=xi_grid, y=yi_grid, z=zi_grid,
                colorscale='Viridis' if is_dark else 'RdYlBu_r',
                colorbar=dict(
                    title=dict(text=z_label, font=dict(size=10, color=text_muted)),
                    tickfont=dict(size=9, color=text_muted), outlinewidth=0,
                ),
                hovertemplate=(f'<b>{x_label}</b>: %{{x:.4f}}<br>'
                               f'<b>{y_label}</b>: %{{y:.4f}}<br>'
                               f'<b>{z_label}</b>: %{{z:.4f}}<extra></extra>'),
                opacity=0.92,
                contours=dict(
                    z=dict(show=True, usecolormap=True, highlightcolor='white', project_z=True),
                ),
            ))

            scene_axis = lambda title: dict(
                title=dict(text=title, font=dict(size=10, color=text_muted)),
                backgroundcolor='rgba(0,0,0,0.02)' if is_dark else 'rgba(0,0,0,0.01)',
                gridcolor=grid_color, showbackground=True,
                tickfont=dict(size=9, color=text_muted),
            )
            fig.update_layout(
                **base_layout,
                margin=dict(l=0, r=0, t=30, b=0),
                scene=dict(
                    xaxis=scene_axis(x_label),
                    yaxis=scene_axis(y_label),
                    zaxis=scene_axis(z_label),
                    bgcolor='rgba(0,0,0,0)',
                ),
            )
            return fig

        # ── 2D: line plot — X = predictor 1, Y = predictor 2 ──
        pair = df[[compare_x, compare_y]].dropna().sort_values(compare_x)
        corr_val = pair[compare_x].corr(pair[compare_y]) if len(pair) >= 2 else None

        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=pair[compare_x], y=pair[compare_y],
                mode='lines',
                line=dict(color=color_palette[0], width=2.5, shape='spline'),
                hovertemplate=(f'<b>{x_label}</b>: %{{x:.4f}}<br>'
                               f'<b>{y_label}</b>: %{{y:.4f}}<extra></extra>'),
            )
        )

        if corr_val is not None:
            fig.add_annotation(
                text=f"r = {corr_val:.3f}",
                xref="paper", yref="paper", x=0.02, y=0.98,
                showarrow=False, font=dict(size=11, color=text_muted),
                bgcolor='rgba(0,0,0,0.3)' if is_dark else 'rgba(255,255,255,0.8)',
                borderpad=6, bordercolor=line_color, borderwidth=1,
            )

        fig.update_layout(
            **base_layout,
            margin=dict(l=60, r=30, t=30, b=60),
            showlegend=False,
            hovermode="closest",
            hoverlabel=dict(
                bgcolor='rgba(18,18,20,0.75)' if is_dark else 'rgba(248,248,252,0.75)',
                font_size=12, font_family="Inter", font_color=text_color,
                bordercolor=line_color, namelength=-1,
            ),
            xaxis=dict(
                title=dict(text=x_label, font=dict(size=11, color=text_muted)),
                showgrid=True, gridwidth=1, gridcolor=grid_color, griddash='dot',
                zeroline=False, showline=True, linewidth=1, linecolor=line_color,
                tickfont=dict(size=10, color=text_muted),
            ),
            yaxis=dict(
                title=dict(text=y_label, font=dict(size=11, color=text_muted)),
                showgrid=True, gridwidth=1, gridcolor=grid_color, griddash='dot',
                zeroline=False, showline=True, linewidth=1, linecolor=line_color,
                tickfont=dict(size=10, color=text_muted),
            ),
            dragmode='zoom',
        )
        return fig

    # ═══ TIME SERIES MODE (default) — always normalized 0–100 ═══
    if not selected_predictors:
        return go.Figure()

    fig = go.Figure()

    zar_color = '#E8E8E8' if is_dark else '#1A1A1A'
    color_idx = 0

    def normalize(series):
        min_val = series.min()
        max_val = series.max()
        if max_val == min_val:
            return series * 0 + 50
        return ((series - min_val) / (max_val - min_val)) * 100

    for var in selected_predictors:
        if var not in df.columns:
            continue

        is_zar = var == 'ZAR_USD'
        if is_zar:
            color = zar_color
            width = 3
            var_label = label_map.get(var, 'ZAR/USD')
        else:
            color = color_palette[color_idx % len(color_palette)]
            width = 2
            var_label = label_map.get(var, var)
            color_idx += 1

        var_normalized = normalize(df[var])
        fig.add_trace(
            go.Scatter(
                x=df['Date'], y=var_normalized,
                name=var_label,
                line=dict(color=color, width=width, shape='spline'),
                mode='lines',
                customdata=df[var],
                hovertemplate=f'<b>{var_label}</b>: %{{customdata:.4f}}<br><span style="color:#86868b">Normalized: %{{y:.1f}}</span><extra></extra>',
            )
        )

    fig.update_layout(
        **base_layout,
        margin=dict(l=50, r=20, t=30, b=80),
        legend=dict(
            orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
            font=dict(size=11, weight=500, color=text_muted),
            bgcolor='rgba(0,0,0,0)', borderwidth=0,
            itemsizing='constant', itemwidth=30, tracegroupgap=8,
        ),
        hovermode="x unified",
        hoverlabel=dict(
            bgcolor='rgba(18,18,20,0.75)' if is_dark else 'rgba(248,248,252,0.75)',
            font_size=12, font_family="Inter", font_color=text_color,
            bordercolor=line_color, namelength=-1,
        ),
        xaxis=dict(
            showgrid=False, zeroline=False, showline=True, linewidth=1, linecolor=line_color,
            tickfont=dict(size=10, color=text_muted), title=None,
            showspikes=True, spikemode='across', spikesnap='cursor',
            spikedash='dot', spikethickness=1, spikecolor=spike_color,
        ),
        dragmode='zoom',
    )

    y_title = "Normalized (0–100)"
    fig.update_yaxes(
        showgrid=True, gridwidth=1, gridcolor=grid_color, griddash='dot',
        zeroline=False, showline=False,
        tickfont=dict(size=10, color=text_muted),
        title=dict(text=y_title, font=dict(size=11, color=text_muted, weight=500)),
        tickformat=".0f",
        showspikes=False,
    )

    # Range selector buttons
    fig.update_xaxes(
        rangeselector=dict(
            buttons=[
                dict(count=3, label="3M", step="month", stepmode="backward"),
                dict(count=6, label="6M", step="month", stepmode="backward"),
                dict(count=1, label="1Y", step="year", stepmode="backward"),
                dict(count=2, label="2Y", step="year", stepmode="backward"),
                dict(step="all", label="All"),
            ],
            bgcolor='rgba(255,255,255,0.04)' if is_dark else 'rgba(0,0,0,0.03)',
            activecolor='#5b8def' if is_dark else '#4f7df3',
            font=dict(color=text_muted, size=10),
            x=1, y=1.12, xanchor='right', yanchor='top',
        ),
        rangeslider=dict(visible=False),
    )

    return fig


# ═══════════════════════════════════════════
#   Model Page Callbacks
# ═══════════════════════════════════════════

BASE_FEATURE_NAMES = {
    '10_YEAR_BOND_RATES(SA)': 'SA 10-Year Bond Rate',
    '10_YEAR_BOND_RATES(USA)': 'US 10-Year Bond Rate',
    'VIX': 'VIX',
    'BRENT_OIL_PRICE': 'Brent Crude Oil Price',
    'GOLD_PRICE': 'Gold Price',
    'EPU(USA)': 'US Economic Policy Uncertainty',
    'INFLATION_DIFF': 'SA-US Inflation Differential',
    'WUIZAF(SA)': 'SA World Uncertainty Index',
    'ZAR_USD': 'ZAR per USD',
    'SA_INFLATION_YOY': 'SA Inflation (YoY)',
    'US_CPI_YOY': 'US CPI (YoY)',
}


def get_friendly_feature_name(feature_name, transform_type):
    """Dynamically build a friendly name reflecting the actual transform applied."""
    is_lag = feature_name.endswith('_Lag1')
    is_trend = feature_name.endswith('_3M_Trend')
    base = feature_name.replace('_Lag1', '').replace('_3M_Trend', '')

    display_name = BASE_FEATURE_NAMES.get(base, base)

    # Simplified names - now interpretable per unit change in original rate
    if is_lag:
        return f"{display_name} (Prev. Month)"
    elif is_trend:
        return f"{display_name} (3M Trend)"
    return display_name


def get_coefficient_unit(transform_type):
    """Return appropriate unit label for interpretable coefficients (MSc research standard)."""
    if transform_type == 'log_diff':
        return 'ZAR per USD per 1-unit change in level'
    elif transform_type == 'first_diff':
        return 'ZAR per USD per 1-unit change'
    return 'ZAR per USD per unit'


# Background callbacks for Model and Scenario calculation (prerendering support)
@callback(
    Output('model-prediction-data', 'data'),
    Output('model-error', 'children', allow_duplicate=True),
    Input('model-prediction-trigger', 'data'),
    State('model-prediction-data', 'data'),
    background=True,
    prevent_initial_call='initial_duplicate',
    running=[
        (Output('model-loading', 'style'), {'display': 'flex'}, {'display': 'none'}),
        (Output('model-error', 'children'), "", ""),
    ],
)
def fetch_model_prediction(trigger, existing_data):
    if trigger and not existing_data:
        try:
            result = predict_next_month()
            return {'raw_result': result}, ""
        except Exception as e:
            traceback.print_exc()
            return dash.no_update, f"Model Prediction Failed: {str(e)}"
    return dash.no_update, dash.no_update


@callback(
    Output('scenario-baseline-data', 'data'),
    Output('scenario-error', 'children', allow_duplicate=True),
    Input('scenario-trigger', 'data'),
    State('scenario-baseline-data', 'data'),
    background=True,
    prevent_initial_call='initial_duplicate',
    running=[
        (Output('scenario-loading', 'style'), {'display': 'flex'}, {'display': 'none'}),
        (Output('scenario-error', 'children'), "", ""),
    ],
)
def fetch_scenario_baseline(trigger, existing_data):
    if trigger and not existing_data:
        try:
            result = get_scenario_baseline()
            return result, ""
        except Exception as e:
            traceback.print_exc()
            return dash.no_update, f"Scenario engine load failed: {str(e)}"
    return dash.no_update, dash.no_update


@callback(
    Output('model-results-container', 'style'),
    Output('model-error', 'children', allow_duplicate=True),
    Output('forecast-table-container', 'children'),
    Output('feature-contributions', 'children'),
    Output('model-history-chart', 'figure'),
    Output('model-info-content', 'children'),
    Output('model-description-content', 'children'),
    Output('model-loading', 'style'),
    Input('dashboard-tab', 'data'),
    Input('model-prediction-data', 'data'),
    State('theme-store', 'data'),
    prevent_initial_call='initial_duplicate'
)
def render_model_ui(active_tab, prediction_data, theme):
    if active_tab != 'model':
        return [dash.no_update] * 8

    if not prediction_data:
        empty_fig = go.Figure().to_dict()
        return ({'display': 'none'}, '', '', '', empty_fig, '', '', {'display': 'flex'})

    result = prediction_data.get('raw_result')
    if not result:
        empty_fig = go.Figure().to_dict()
        return ({'display': 'none'}, 'Prediction results unavailable.', '', '', empty_fig, '', '', {'display': 'none'})

    pred_level = result['predicted_level']
    direction = result['direction']
    change_pct = result['predicted_change_pct']
    date_text = result['next_month_date']
    pred_value = f"R {pred_level:.4f}"
    baseline_text = f"Current: R {result['last_zar_usd']:.4f} ({result['last_date']})"

    # ── Multi-Horizon Forecast Table ──
    forecasts = result.get('forecasts', {})
    table_header = html.Thead(html.Tr([
        html.Th('Horizon'),
        html.Th('Actual Estimate (Spot)'),
        html.Th('Fair Value Estimate'),
        html.Th('Reasoning'),
    ]))
    
    table_rows = []
    horizon_labels = {'1m': '1 Month', '3m': '3 Months', '6m': '6 Months'}
    
    for key, label in horizon_labels.items():
        if key in forecasts:
            f = forecasts[key]
            table_rows.append(html.Tr([
                html.Td(label, style={'fontWeight': '600'}),
                html.Td(f"R {f['actual_estimate']:.4f}"),
                html.Td(f"R {f['fair_value']:.4f}", style={'color': 'var(--accent)', 'fontWeight': '600'}),
                html.Td(f['reason'], style={'fontSize': '0.8125rem', 'color': 'var(--text-2)'}),
            ]))
            
    forecast_table = html.Table(className='forecast-table', children=[
        table_header,
        html.Tbody(table_rows)
    ])

    # ── Feature contributions ──
    contrib_rows = []
    for c in result['contributions']:
        feat_name = get_friendly_feature_name(c['feature'], c['transform_type'])
        coef = c['zar_level_coefficient']  # Use ZAR/USD level coefficient for user interpretation
        contrib = c['contribution']

        # Direction label based on coefficient sign (MSc research standard)
        # Positive coef → ZAR per USD increases → ZAR depreciates (weakens)
        # Negative coef → ZAR per USD decreases → ZAR appreciates (strengthens)
        if abs(coef) < 0.0001:
            direction_label = 'Neutral'
        elif coef > 0:
            direction_label = 'ZAR Depreciates'
        else:
            direction_label = 'ZAR Appreciates'

        bar_color = '#EF4444' if contrib > 0 else '#10B981'
        bar_width = min(abs(contrib) / max(abs(x['contribution']) for x in result['contributions']) * 100, 100)

        # Add unit suffix based on transform type
        unit_suffix = get_coefficient_unit(c['transform_type'])

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
                html.Span(f'{coef:+.4f} {unit_suffix}', className='contrib-value',
                          style={'color': bar_color}),
            ])
        )

    # ── Historical fit chart ──
    history = result.get('history', {})
    # Fallback to dark theme if theme is None — Apple palette
    is_dark = (theme == 'dark') if theme else True
    text_color = '#f5f5f7' if is_dark else '#1d1d1f'
    text_muted = '#86868b' if is_dark else '#6e6e73'
    grid_color = 'rgba(255,255,255,0.03)' if is_dark else 'rgba(0,0,0,0.03)'
    line_color = 'rgba(255,255,255,0.06)' if is_dark else 'rgba(0,0,0,0.06)'

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

    font_family = "-apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Inter', sans-serif"
    layout = {
        'template': None,
        'paper_bgcolor': 'rgba(0,0,0,0)',
        'plot_bgcolor': 'rgba(0,0,0,0)',
        'margin': dict(l=48, r=24, t=24, b=48),
        'autosize': True,
        'font': dict(family=font_family, size=12, color=text_color),
        'legend': dict(
            orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
            font=dict(size=11, color=text_muted), bgcolor='rgba(0,0,0,0)',
            borderwidth=0,
        ),
        'hovermode': "x unified",
        'hoverlabel': dict(
            bgcolor='rgba(18,18,20,0.75)' if is_dark else 'rgba(248,248,252,0.75)',
            font_size=12, font_family=font_family, font_color=text_color,
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
        html.H5('Model Specification',
                style={'fontSize': '0.8125rem', 'fontWeight': '600', 'color': 'var(--text-2)', 'marginBottom': '12px'}),
        html.Div(className='model-info-grid', children=[
            _info_pill('Type', 'ElasticNet (L1 = Lasso)',
                       'Statistical model using both L1 and L2 regularization to find the best predictors.'),
            _info_pill('Alpha', f"{info['alpha']:.4f}" if info.get('alpha') is not None else "N/A",
                       'Regularization strength: higher values mean more indicators are excluded to prevent overfitting.'),
            _info_pill('L1 Ratio', f"{info['l1_ratio']:.2f}" if info.get('l1_ratio') is not None else "N/A",
                       'Balance between Lasso (1.0) and Ridge (0.0) regularization.'),
            _info_pill('Intercept', f"{info['intercept']:+.4f}" if info.get('intercept') is not None else "N/A",
                       'The base log-return forecast before considering macroeconomic indicator impacts.'),
            _info_pill('Training Obs', str(info.get('training_observations', 'N/A')),
                       'Number of historical monthly data points used to calibrate the model.'),
            _info_pill('Features', f"{info.get('n_selected', 0)} / {info.get('n_features', 0)} selected",
                       'The number of macroeconomic indicators the model found statistically significant.'),
            _info_pill('Date Range', info.get('training_date_range', 'N/A'),
                       'The historical window of data used for training the current model version.'),
            _info_pill('Target', 'Log-return ZAR/USD (% MoM)',
                       'The model predicts the percentage change in the exchange rate from one month to the next.'),
        ]),
        html.H5('In-Sample Performance Metrics',
                style={'fontSize': '0.8125rem', 'fontWeight': '600', 'color': 'var(--text-2)', 'marginTop': '24px',
                       'marginBottom': '12px'}),
        html.Div(className='model-info-grid', children=[
            _info_pill('MAE', f"ZAR {metrics.get('mae', 0):.4f}",
                       'Mean Absolute Error: Average forecast error in ZAR. Lower values indicate better precision.'),
            _info_pill('RMSE', f"ZAR {metrics.get('rmse', 0):.4f}",
                       'Root Mean Squared Error: Similar to MAE but penalizes larger misses more heavily.'),
            _info_pill('R²', f"{metrics.get('r2', 0):.4f}",
                       'Explains how much of the ZAR/USD volatility is captured by the model (0 to 1 scale).'),
            _info_pill('MAPE', f"{metrics.get('mape', 0):.2f}%",
                       'Mean Absolute Percentage Error: Average error relative to the exchange rate level.'),
            _info_pill('MedAE', f"ZAR {metrics.get('medae', 0):.4f}",
                       'Median Absolute Error: The median value of all absolute errors. Robust to outliers.'),
            _info_pill('Max Error', f"ZAR {metrics.get('max_error', 0):.4f}",
                       'Maximum Error: The largest absolute difference between actual and predicted ZAR/USD.'),
            _info_pill('Explained Variance', f"{metrics.get('evs', 0):.4f}",
                       'Measures how much of the variation in ZAR/USD is captured by the model.'),
            _info_pill('Directional Accuracy', f"{metrics.get('directional_accuracy', 0):.1f}%",
                       'Percentage of months where the model correctly predicted if the ZAR would strengthen or weaken.'),
        ]),
        html.H5('Forward Model Estimates',
                style={'fontSize': '0.8125rem', 'fontWeight': '600', 'color': 'var(--text-2)', 'marginTop': '24px',
                       'marginBottom': '12px'}),
        html.Div(className='model-info-grid', children=[
            _info_pill('1 Month Forward', f"R {result.get('forecasts', {}).get('1m', {}).get('fair_value', 0):.4f}",
                       f"Estimate for {result.get('forecasts', {}).get('1m', {}).get('date', 'next month')}. Using latest macro drivers."),
            _info_pill('3 Month Forward', f"R {result.get('forecasts', {}).get('3m', {}).get('fair_value', 0):.4f}",
                       f"Estimate for {result.get('forecasts', {}).get('3m', {}).get('date', 'in 3 months')}. Iterative multi-horizon forecast."),
            _info_pill('6 Month Forward', f"R {result.get('forecasts', {}).get('6m', {}).get('fair_value', 0):.4f}",
                       f"Estimate for {result.get('forecasts', {}).get('6m', {}).get('date', 'in 6 months')}. Assuming macro conditions persist."),
        ]),
    ])

    # Dynamic Description Generation (MSc research standard)
    top_feature = result['contributions'][0] if result['contributions'] else None
    feature_impact_text = ""
    if top_feature:
        feat_name = get_friendly_feature_name(top_feature['feature'], top_feature['transform_type'])
        impact_dir = "depreciation" if top_feature['zar_level_coefficient'] > 0 else "appreciation"
        feature_impact_text = f"The most significant driver for this period is {feat_name}, which is associated with expected ZAR {impact_dir} pressure."

    direction_text = ""
    if direction == 'weaken':
        direction_text = f"The model forecasts a ZAR depreciation of {abs(change_pct):.2f}% against the USD."
    elif direction == 'strengthen':
        direction_text = f"The model forecasts a ZAR appreciation of {abs(change_pct):.2f}% against the USD."
    else:
        direction_text = "The model expects the ZAR/USD exchange rate to remain relatively stable."

    perf_text = f"Historically, this model has achieved a directional accuracy of {metrics.get('directional_accuracy', 0):.1f}% during its training period, with a mean absolute error (MAE) of approximately {metrics.get('mae', 0):.2f} cents per Dollar."

    analysis_content = html.Div([
        html.P(f"Based on the latest data for {result['last_date']}, {direction_text} {feature_impact_text}"),
        html.P(perf_text),
        html.P(
            "This forecast is based on an ElasticNet (Lasso) regression model that automatically selects the most relevant macroeconomic indicators. "
            "Coefficients represent expected changes in ZAR per USD holding all else constant. "
            "The model uses log-returns to ensure statistical stability and then converts the results back to level exchange rates for interpretability.")
    ])

    return ({'display': 'block'}, '', forecast_table, contrib_rows, fig_dict, info_items, analysis_content,
            {'display': 'none'})


def _build_diagnostic_plots(diagnostics_data, theme):
    """Pre-render diagnostic plots so the toggle only needs to show/hide them."""
    if not diagnostics_data:
        return html.P('No diagnostic data available. Run a prediction first.',
                      style={'color': 'var(--text-muted)', 'textAlign': 'center', 'padding': '20px'})

    is_dark = (theme == 'dark') if theme else True
    text_color = '#f5f5f7' if is_dark else '#1d1d1f'
    text_muted = '#86868b' if is_dark else '#6e6e73'
    grid_color = 'rgba(255,255,255,0.03)' if is_dark else 'rgba(0,0,0,0.03)'
    line_color = 'rgba(255,255,255,0.06)' if is_dark else 'rgba(0,0,0,0.06)'

    # Actual vs Predicted Plot (Replaces QQ Plot)
    avp_data = diagnostics_data.get('actual_vs_predicted', {})
    avp_plot = html.Div('No comparison data available', style={'color': text_muted})
    
    if avp_data and avp_data.get('actual') and avp_data.get('predicted'):
        avp_fig = go.Figure()

        actual = avp_data['actual']
        predicted = avp_data['predicted']
        
        avp_fig.add_trace(go.Scatter(
            x=actual,
            y=predicted,
            mode='markers',
            marker=dict(color='#5b8def', size=8, opacity=0.7, 
                        line=dict(width=1, color='rgba(255,255,255,0.1)' if is_dark else 'rgba(0,0,0,0.1)')),
            name='Observations',
            hovertemplate='Actual: R %{x:.4f}<br>Predicted: R %{y:.4f}<extra></extra>'
        ))

        min_val = min(min(actual), min(predicted)) * 0.98
        max_val = max(max(actual), max(predicted)) * 1.02
        
        avp_fig.add_trace(go.Scatter(
            x=[min_val, max_val],
            y=[min_val, max_val],
            mode='lines',
            line=dict(color='#EF4444', width=2, dash='dash'),
            name='Ideal (y=x)',
            hoverinfo='skip'
        ))

        avp_fig.update_layout(
            template=None,
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            margin=dict(l=56, r=24, t=32, b=48),
            height=400,
            font=dict(family="Inter, sans-serif", size=12, color=text_color),
            legend=dict(
                orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
                font=dict(size=11, color=text_muted), bgcolor='rgba(0,0,0,0)',
            ),
            hovermode="closest",
            xaxis=dict(
                title='Actual ZAR / USD',
                showgrid=True, gridwidth=1, gridcolor=grid_color,
                tickfont=dict(size=10, color=text_muted),
                tickformat=".2f",
            ),
            yaxis=dict(
                title='Predicted ZAR / USD',
                showgrid=True, gridwidth=1, gridcolor=grid_color,
                tickfont=dict(size=10, color=text_muted),
                tickformat=".2f",
            ),
        )

        avp_plot = html.Div(className='diagnostic-plot-container', children=[
            html.H5('Actual vs Predicted ZAR/USD (Validation Set)',
                    style={'fontSize': '0.9375rem', 'fontWeight': '600', 'marginBottom': '8px'}),
            html.P('Points should cluster around the diagonal line for accurate level predictions',
                   style={'fontSize': '0.8125rem', 'color': text_muted, 'marginBottom': '12px'}),
            dcc.Graph(id='diag-avp-plot', figure=avp_fig.to_dict(), style={'height': '400px'},
                      config={'displayModeBar': 'hover', 'displaylogo': False, 'responsive': True})
        ])

    # Partial Plots
    partial_plot_children = []
    partial_plots_data = diagnostics_data.get('partial_plots', {})
    if partial_plots_data:
        for feat_name, plot_data in partial_plots_data.items():
            if plot_data.get('x') and plot_data.get('y'):
                partial_fig = go.Figure()

                partial_fig.add_trace(go.Scatter(
                    x=plot_data['x'],
                    y=plot_data['y'],
                    mode='markers',
                    marker=dict(color='#5b8def', size=6, opacity=0.6),
                    name=feat_name,
                    hovertemplate='%{x:.4f}<br>Partial Residual: %{y:.4f}<extra></extra>'
                ))

                try:
                    import numpy as np
                    x_arr = np.array(plot_data['x'])
                    y_arr = np.array(plot_data['y'])

                    if len(x_arr) > 2:
                        coeffs = np.polyfit(x_arr, y_arr, 1)
                        x_line = np.array([x_arr.min(), x_arr.max()])
                        y_line = np.polyval(coeffs, x_line)

                        partial_fig.add_trace(go.Scatter(
                            x=x_line,
                            y=y_line,
                            mode='lines',
                            line=dict(color='#F59E0B', width=2),
                            name='Trend',
                            hoverinfo='skip'
                        ))
                except:
                    pass

                partial_fig.update_layout(
                    template=None,
                    paper_bgcolor='rgba(0,0,0,0)',
                    plot_bgcolor='rgba(0,0,0,0)',
                    margin=dict(l=56, r=24, t=32, b=48),
                    height=350,
                    font=dict(family="Inter, sans-serif", size=12, color=text_color),
                    showlegend=False,
                    hovermode="closest",
                    xaxis=dict(
                        title=f'{feat_name} (Transformed)',
                        showgrid=True, gridwidth=1, gridcolor=grid_color,
                        tickfont=dict(size=10, color=text_muted),
                    ),
                    yaxis=dict(
                        title='Partial Residual',
                        showgrid=True, gridwidth=1, gridcolor=grid_color,
                        tickfont=dict(size=10, color=text_muted),
                    ),
                )

                safe_id = feat_name.replace('(', '').replace(')', '').replace(' ', '-').lower()
                partial_plot_children.append(
                    html.Div(className='diagnostic-plot-container', children=[
                        html.H6(feat_name, style={'fontSize': '0.875rem', 'fontWeight': '600', 'marginBottom': '4px'}),
                        dcc.Graph(id=f'diag-partial-{safe_id}', figure=partial_fig.to_dict(), style={'height': '350px'},
                                  config={'displayModeBar': 'hover', 'displaylogo': False, 'responsive': True})
                    ]))

    # Combine into a grid layout to prevent horizontal stretching
    return html.Div(className='diagnostics-grid', children=[
        html.Div(avp_plot, className='diagnostics-full-width'),
        html.Div(className='partial-plots-section', children=[
            html.H5('Partial Residual Plots',
                    style={'fontSize': '0.9375rem', 'fontWeight': '600', 'marginBottom': '8px', 'marginTop': '32px'}),
            html.P('Shows relationship between each predictor and target, holding other predictors constant',
                   style={'fontSize': '0.8125rem', 'color': text_muted, 'marginBottom': '20px'}),
            html.Div(className='partial-plots-grid', children=partial_plot_children)
        ])
    ])


@callback(
    Output('diagnostics-container', 'children'),
    Input('model-prediction-data', 'data'),
    Input('dashboard-tab', 'data'),
    State('theme-store', 'data'),
    prevent_initial_call='initial_duplicate'
)
def render_diagnostics(prediction_data, active_tab, theme):
    if active_tab != 'model' or not prediction_data:
        return dash.no_update
    result = prediction_data.get('raw_result')
    if not result:
        return dash.no_update
    diagnostics_data = result.get('diagnostics', {})
    return _build_diagnostic_plots(diagnostics_data, theme)


def _info_pill(label, value, description=None):
    return html.Div(className='info-pill', children=[
        html.Div(className='info-pill-header', children=[
            html.Span(label, className='info-pill-label'),
            html.Span(str(value), className='info-pill-value'),
        ]),
        html.P(description, className='info-pill-description') if description else None
    ])


# ═══════════════════════════════════════════
#   Scenario Analysis Callbacks
# ═══════════════════════════════════════════

SCENARIO_FRIENDLY_NAMES = {
    'VIX': 'VIX (Volatility Index)',
    'GOLD_PRICE': 'Gold Price (USD/oz)',
    'BRENT_OIL_PRICE': 'Brent Crude Oil (USD/bbl)',
    'EPU(USA)': 'US Economic Policy Uncertainty',
    'WUIZAF(SA)': 'SA World Uncertainty Index',
    '10_YEAR_BOND_RATES(USA)': 'US 10-Year Bond Rate (%)',
    '10_YEAR_BOND_RATES(SA)': 'SA 10-Year Bond Rate (%)',
    'INFLATION_DIFF': 'SA-US Inflation Differential (pp)',
    'SA_INFLATION_YOY': 'SA Inflation YoY (%)',
    'US_CPI_YOY': 'US CPI YoY (%)',
}

SCENARIO_UNITS = {
    'VIX': '',
    'GOLD_PRICE': 'USD',
    'BRENT_OIL_PRICE': 'USD',
    'EPU(USA)': '',
    'WUIZAF(SA)': '',
    '10_YEAR_BOND_RATES(USA)': '%',
    '10_YEAR_BOND_RATES(SA)': '%',
    'INFLATION_DIFF': 'pp',
    'SA_INFLATION_YOY': '%',
    'US_CPI_YOY': '%',
}


@callback(
    Output('scenario-error', 'children', allow_duplicate=True),
    Output('scenario-loading', 'style'),
    Output('scenario-content', 'style'),
    Output('scenario-current-values', 'data'),
    Input('dashboard-tab', 'data'),
    Input('scenario-baseline-data', 'data'),
    prevent_initial_call='initial_duplicate'
)
def sync_scenario_ui(active_tab, existing_baseline):
    if active_tab != 'scenario':
        return [dash.no_update] * 4

    if not existing_baseline:
        return '', {'display': 'flex'}, {'display': 'none'}, dash.no_update

    # Already have baseline, just return current state
    current_vals = {p['raw_col']: p['current_value'] for p in existing_baseline.get('predictors', [])}
    return '', {'display': 'none'}, {'display': 'block'}, current_vals


@callback(
    Output('scenario-sliders-container', 'children'),
    Output('scenario-base-value', 'children'),
    Output('scenario-base-change', 'children'),
    Input('scenario-baseline-data', 'data'),
    State('scenario-current-values', 'data'),
)
def render_scenario_sliders(baseline, current_values):
    if not baseline:
        return dash.no_update, dash.no_update, dash.no_update

    predictors = baseline.get('predictors', [])
    base_pred = baseline.get('base_prediction', 0)
    last_zar = baseline.get('last_zar_usd', 0)
    base_change = ((base_pred - last_zar) / last_zar * 100) if last_zar else 0

    sliders = []
    for pred in predictors:
        raw_col = pred['raw_col']
        friendly = SCENARIO_FRIENDLY_NAMES.get(raw_col, raw_col)
        unit = SCENARIO_UNITS.get(raw_col, '')
        current = pred['current_value']
        rng_low = pred['range_low']
        rng_high = pred['range_high']

        # Use session value if available, otherwise current
        slider_val = current_values.get(raw_col, current) if current_values else current

        # Determine step size based on range magnitude
        rng_span = rng_high - rng_low
        if rng_span > 1000:
            step = 1.0
        elif rng_span > 100:
            step = 0.5
        elif rng_span > 10:
            step = 0.1
        else:
            step = 0.01

        sliders.append(
            create_scenario_slider(
                slider_id=raw_col,
                label=friendly,
                unit=unit,
                min_val=rng_low,
                max_val=rng_high,
                current_val=current,
                active_val=slider_val,
                step=step
            )
        )

    base_value_text = f"R {base_pred:.4f}"
    base_change_text = f"{base_change:+.2f}% vs current" if abs(base_change) > 0.005 else "~ stable"

    return sliders, base_value_text, base_change_text


@callback(
    Output('scenario-current-values', 'data', allow_duplicate=True),
    Input({'type': 'scenario-slider', 'index': dash.ALL}, 'value'),
    State('scenario-baseline-data', 'data'),
    prevent_initial_call=True
)
def update_scenario_values(slider_values, baseline):
    if not baseline or not slider_values:
        return dash.no_update

    predictors = baseline.get('predictors', [])
    updated = {}

    for i, pred in enumerate(predictors):
        raw_col = pred['raw_col']

        if i < len(slider_values) and slider_values[i] is not None:
            val = slider_values[i]
            updated[raw_col] = val
        else:
            updated[raw_col] = pred['current_value']

    return updated


@callback(
    Output({'type': 'scenario-value-display', 'index': dash.ALL}, 'children'),
    Input('scenario-current-values', 'data'),
    State('scenario-baseline-data', 'data'),
    prevent_initial_call=True
)
def update_value_displays(current_values, baseline):
    if not baseline or not current_values:
        return dash.no_update

    predictors = baseline.get('predictors', [])
    display_values = []

    for pred in predictors:
        raw_col = pred['raw_col']
        unit = SCENARIO_UNITS.get(raw_col, '')
        val = current_values.get(raw_col, pred['current_value'])

        # Determine decimals based on value magnitude
        rng_span = pred['range_high'] - pred['range_low']
        if rng_span > 1000:
            decimals = 0
        elif rng_span > 100:
            decimals = 1
        else:
            decimals = 2

        display_values.append(f"{val:.{decimals}f} {unit}".strip())

    return display_values


@callback(
    Output('scenario-result-value', 'children'),
    Output('scenario-result-change', 'children'),
    Output('scenario-delta-value', 'children'),
    Output('scenario-delta-pct', 'children'),
    Output('scenario-delta-tag', 'children'),
    Output('scenario-delta-tag', 'className'),
    Output('scenario-waterfall-chart', 'figure'),
    Output('scenario-summary-table', 'children'),
    Output('scenario-status-display', 'children'),
    Input('scenario-current-values', 'data'),
    State('scenario-baseline-data', 'data'),
    State('theme-store', 'data'),
    prevent_initial_call=True
)
def run_scenario_prediction(current_values, baseline, theme):
    if not current_values or not baseline:
        empty_fig = go.Figure()
        return ('', '', '', '', '', 'scenario-card-tag', empty_fig.to_dict(), '', '')

    predictors = baseline.get('predictors', [])
    base_pred = baseline.get('base_prediction', 0)
    last_zar = baseline.get('last_zar_usd', 0)

    # Check if any value has changed from current
    has_changes = False
    scenario_vals = {}
    for pred in predictors:
        raw_col = pred['raw_col']
        current = pred['current_value']
        scenario_val = current_values.get(raw_col, current)
        scenario_vals[raw_col] = scenario_val
        if abs(scenario_val - current) > 0.0001:
            has_changes = True

    if not has_changes:
        # No changes — show base values for all
        base_change = ((base_pred - last_zar) / last_zar * 100) if last_zar else 0
        empty_fig = go.Figure()
        empty_fig.add_annotation(
            text="Adjust a predictor to see impact",
            xref="paper", yref="paper", x=0.5, y=0.5,
            showarrow=False, font=dict(color='#6b6b6b', size=14)
        )
        _apply_scenario_chart_layout(empty_fig, theme)

        return (
            f"R {base_pred:.4f}",
            f"{base_change:+.2f}% vs current",
            "R 0.0000",
            "No change",
            'Unchanged',
            'scenario-card-tag tag-neutral',
            empty_fig.to_dict(),
            _build_scenario_summary_table(predictors, current_values, baseline),
            html.Span('● No changes', style={'color': 'var(--text-3)'}),
        )

    try:
        result = scenario_predict(scenario_vals)
    except Exception as e:
        traceback.print_exc()
        empty_fig = go.Figure()
        return ('Error', str(e), '', '', 'Error', 'scenario-card-tag tag-neutral',
                empty_fig.to_dict(), '', html.Span(f'● Error: {e}', style={'color': '#EF4444'}))

    scen_level = result['scenario_level']
    scen_change = result['scenario_change_pct']
    delta_level = result['delta_level']
    delta_pct = scen_change - result['base_change_pct']

    # Scenario result
    scen_value_text = f"R {scen_level:.4f}"
    scen_change_text = f"{scen_change:+.2f}% vs current"

    # Delta
    delta_value_text = f"R {delta_level:+.4f}"
    delta_pct_text = f"{delta_pct:+.2f}pp shift"

    if delta_level > 0.001:
        delta_tag_text = 'ZAR Weakens'
        delta_tag_class = 'scenario-card-tag tag-negative'
    elif delta_level < -0.001:
        delta_tag_text = 'ZAR Strengthens'
        delta_tag_class = 'scenario-card-tag tag-positive'
    else:
        delta_tag_text = 'Neutral'
        delta_tag_class = 'scenario-card-tag tag-neutral'

    # Waterfall chart
    waterfall = result.get('waterfall', [])
    # Filter to only features that actually changed
    active_waterfall = [w for w in waterfall if abs(w['delta']) > 0.0001]

    fig = go.Figure()
    if active_waterfall:
        labels = [get_friendly_feature_name(w['feature'], w['transform_type']) for w in active_waterfall]
        deltas = [w['delta'] for w in active_waterfall]
        colors = ['#EF4444' if d > 0 else '#10B981' for d in deltas]

        fig.add_trace(go.Bar(
            x=deltas,
            y=labels,
            orientation='h',
            marker=dict(color=colors, cornerradius=4),
            hovertemplate='%{y}<br>Δ Contribution: %{x:+.4f}<extra></extra>',
        ))
    else:
        fig.add_annotation(
            text="No significant contribution changes",
            xref="paper", yref="paper", x=0.5, y=0.5,
            showarrow=False, font=dict(color='#6b6b6b', size=14)
        )

    _apply_scenario_chart_layout(fig, theme)
    fig.update_layout(
        height=min(600, max(250, len(active_waterfall) * 48 + 80)),
        autosize=False,
        yaxis=dict(autorange='reversed'),
        xaxis=dict(
            title=dict(text='Contribution Change (scaled)', font=dict(size=11)),
            zeroline=True,
            zerolinewidth=2,
        ),
    )

    # Status
    n_changed = sum(1 for pred in predictors if
                    abs(current_values.get(pred['raw_col'], pred['current_value']) - pred['current_value']) > 0.0001)
    status = html.Span(f'● {n_changed} predictor{"s" if n_changed != 1 else ""} modified', style={'color': '#3B82F6'})

    summary_table = _build_scenario_summary_table(predictors, current_values, baseline)

    return (scen_value_text, scen_change_text, delta_value_text, delta_pct_text,
            delta_tag_text, delta_tag_class, fig.to_dict(), summary_table, status)


def _apply_scenario_chart_layout(fig, theme):
    is_dark = (theme == 'dark') if theme else True
    text_color = '#f5f5f7' if is_dark else '#1d1d1f'
    text_muted = '#86868b' if is_dark else '#6e6e73'
    grid_color = 'rgba(255,255,255,0.03)' if is_dark else 'rgba(0,0,0,0.03)'
    line_color = 'rgba(255,255,255,0.06)' if is_dark else 'rgba(0,0,0,0.06)'
    font_family = "-apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Inter', sans-serif"

    fig.update_layout(
        template=None,
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        margin=dict(l=180, r=24, t=16, b=48),
        autosize=True,
        font=dict(family=font_family, size=12, color=text_color),
        showlegend=False,
        hovermode="closest",
        xaxis=dict(
            showgrid=True, gridwidth=1, gridcolor=grid_color, griddash='dot',
            zeroline=True, zerolinewidth=1, zerolinecolor=line_color,
            tickfont=dict(size=10, color=text_muted),
        ),
        yaxis=dict(
            showgrid=False,
            tickfont=dict(size=11, color=text_color),
        ),
    )


def _build_scenario_summary_table(predictors, current_values, baseline):
    if not predictors:
        return html.Div("No predictors available.")

    header = html.Thead(html.Tr([
        html.Th('Predictor', style={'textAlign': 'left'}),
        html.Th('Current Value', style={'textAlign': 'center'}),
        html.Th('Scenario Value', style={'textAlign': 'center'}),
        html.Th('Change', style={'textAlign': 'center'}),
        html.Th('Change %', style={'textAlign': 'center'}),
    ]))

    rows = []
    for pred in predictors:
        raw_col = pred['raw_col']
        friendly = SCENARIO_FRIENDLY_NAMES.get(raw_col, raw_col)
        unit = SCENARIO_UNITS.get(raw_col, '')
        current = pred['current_value']
        scenario = current_values.get(raw_col, current) if current_values else current
        change = scenario - current
        change_pct = (change / current * 100) if current != 0 else 0
        is_changed = abs(change) > 0.0001

        change_color = '#EF4444' if change > 0.0001 else '#10B981' if change < -0.0001 else 'var(--text-3)'
        row_style = {'backgroundColor': 'rgba(91, 141, 239, 0.04)'} if is_changed else {}

        decimals = 2 if abs(current) < 20 else (1 if abs(current) < 200 else 0)

        rows.append(html.Tr(style=row_style, children=[
            html.Td(friendly, style={'fontWeight': '500'}),
            html.Td(f"{current:.{decimals}f} {unit}".strip(), style={'textAlign': 'center'}),
            html.Td(
                f"{scenario:.{decimals}f} {unit}".strip(),
                style={'textAlign': 'center', 'fontWeight': '600' if is_changed else '400',
                       'color': change_color if is_changed else 'var(--text-1)'}
            ),
            html.Td(
                f"{change:+.{decimals}f}" if is_changed else '—',
                style={'textAlign': 'center', 'color': change_color, 'fontWeight': '600'}
            ),
            html.Td(
                f"{change_pct:+.1f}%" if is_changed else '—',
                style={'textAlign': 'center', 'color': change_color, 'fontWeight': '600'}
            ),
        ]))

    return html.Table(className='custom-table', children=[header, html.Tbody(rows)])


@callback(
    Output('scenario-current-values', 'data', allow_duplicate=True),
    Output('scenario-trigger', 'data', allow_duplicate=True),
    Input('scenario-reset-btn', 'n_clicks'),
    State('scenario-baseline-data', 'data'),
    State('scenario-trigger', 'data'),
    prevent_initial_call=True
)
def reset_scenario(n_clicks, baseline, current_trigger):
    if not n_clicks or not baseline:
        return dash.no_update, dash.no_update
    # Reset current values to baseline current values and bump trigger to re-render sliders
    current_vals = {p['raw_col']: p['current_value'] for p in baseline.get('predictors', [])}
    return current_vals, (current_trigger or 0) + 1


@callback(
    Output('saved-scenarios', 'data'),
    Output('scenario-comparison-section', 'style'),
    Input('scenario-save-btn', 'n_clicks'),
    Input('scenario-clear-all-btn', 'n_clicks'),
    State('scenario-current-values', 'data'),
    State('scenario-baseline-data', 'data'),
    State('saved-scenarios', 'data'),
    prevent_initial_call=True
)
def manage_saved_scenarios(save_clicks, clear_clicks, current_values, baseline, saved_scenarios):
    ctx = dash.callback_context
    if not ctx.triggered:
        return dash.no_update, dash.no_update

    trigger = ctx.triggered[0]['prop_id'].split('.')[0]

    if trigger == 'scenario-clear-all-btn':
        return [], {'marginTop': '1.5vh', 'display': 'none'}

    if trigger == 'scenario-save-btn':
        if not current_values or not baseline:
            return dash.no_update, dash.no_update

        # Check if any values changed
        predictors = baseline.get('predictors', [])
        has_changes = any(
            abs(current_values.get(p['raw_col'], p['current_value']) - p['current_value']) > 0.0001
            for p in predictors
        )

        if not has_changes:
            return dash.no_update, dash.no_update

        # Run prediction for this scenario
        try:
            scenario_vals = {p['raw_col']: current_values.get(p['raw_col'], p['current_value']) for p in predictors}
            result = scenario_predict(scenario_vals)

            # Create scenario snapshot
            import datetime
            scenario_name = f"Scenario {len(saved_scenarios) + 1}"
            timestamp = datetime.datetime.now().strftime('%H:%M:%S')

            scenario_snapshot = {
                'name': scenario_name,
                'timestamp': timestamp,
                'values': scenario_vals,
                'prediction': result['scenario_level'],
                'change_pct': result['scenario_change_pct'],
                'delta_from_base': result['delta_level'],
            }

            # Add to saved scenarios (max 5)
            updated_scenarios = (saved_scenarios or []).copy()
            updated_scenarios.append(scenario_snapshot)
            if len(updated_scenarios) > 5:
                updated_scenarios = updated_scenarios[-5:]

            return updated_scenarios, {'marginTop': '1.5vh', 'display': 'block'}
        except Exception as e:
            print(f"Error saving scenario: {e}")
            traceback.print_exc()
            return dash.no_update, dash.no_update

    return dash.no_update, dash.no_update


@callback(
    Output('saved-scenarios-list', 'children'),
    Output('scenario-comparison-chart', 'figure'),
    Input('saved-scenarios', 'data'),
    State('scenario-baseline-data', 'data'),
    State('theme-store', 'data'),
    prevent_initial_call=True
)
def render_scenario_comparison(saved_scenarios, baseline, theme):
    if not saved_scenarios or not baseline:
        empty_fig = go.Figure()
        empty_fig.add_annotation(
            text="Save scenarios to compare them here",
            xref="paper", yref="paper", x=0.5, y=0.5,
            showarrow=False, font=dict(color='#6b6b6b', size=14)
        )
        _apply_scenario_chart_layout(empty_fig, theme)
        empty_fig.update_layout(height=300)
        return html.Div("No saved scenarios yet.",
                        style={'color': 'var(--text-3)', 'padding': '20px', 'textAlign': 'center'}), empty_fig.to_dict()

    base_pred = baseline.get('base_prediction', 0)

    # Render scenario cards
    scenario_cards = []
    for i, scenario in enumerate(saved_scenarios):
        pred = scenario['prediction']
        change = scenario['change_pct']
        delta = scenario['delta_from_base']

        if delta > 0.001:
            card_class = 'saved-scenario-card scenario-negative'
            icon = '📉'
        elif delta < -0.001:
            card_class = 'saved-scenario-card scenario-positive'
            icon = '📈'
        else:
            card_class = 'saved-scenario-card scenario-neutral'
            icon = '➡️'

        scenario_cards.append(
            html.Div(className=card_class, children=[
                html.Div(className='saved-scenario-header', children=[
                    html.Span(f"{icon} {scenario['name']}", className='saved-scenario-name'),
                    html.Span(scenario['timestamp'], className='saved-scenario-time'),
                ]),
                html.Div(f"R {pred:.4f}", className='saved-scenario-value'),
                html.Div(f"{change:+.2f}% vs current", className='saved-scenario-change'),
                html.Div(f"Δ {delta:+.4f} from base", className='saved-scenario-delta'),
            ])
        )

    # Comparison chart — Apple palette
    is_dark = (theme == 'dark') if theme else True
    text_color = '#f5f5f7' if is_dark else '#1d1d1f'
    text_muted = '#86868b' if is_dark else '#6e6e73'

    fig = go.Figure()

    # Add base prediction as reference line
    fig.add_hline(
        y=base_pred,
        line=dict(color='#6b6b6b', width=2, dash='dash'),
        annotation=dict(text='Base', font=dict(size=10, color=text_muted), xanchor='left')
    )

    # Add saved scenarios
    scenario_names = [s['name'] for s in saved_scenarios]
    scenario_preds = [s['prediction'] for s in saved_scenarios]
    scenario_colors = [
        '#EF4444' if s['delta_from_base'] > 0.001 else '#10B981' if s['delta_from_base'] < -0.001 else '#6b6b6b'
        for s in saved_scenarios
    ]

    fig.add_trace(go.Bar(
        x=scenario_names,
        y=scenario_preds,
        marker=dict(color=scenario_colors, cornerradius=6),
        text=[f"R {p:.4f}" for p in scenario_preds],
        textposition='outside',
        textfont=dict(size=11, color=text_color),
        hovertemplate='%{x}<br>Forecast: R %{y:.4f}<extra></extra>',
    ))

    _apply_scenario_chart_layout(fig, theme)
    fig.update_layout(
        height=350,
        autosize=False,
        showlegend=False,
        yaxis=dict(
            title=dict(text='ZAR/USD Forecast', font=dict(size=11, color=text_muted)),
            tickformat='.4f',
        ),
        xaxis=dict(
            title='',
            tickfont=dict(size=11, color=text_color),
        ),
        margin=dict(l=56, r=24, t=40, b=48),
    )

    return scenario_cards, fig.to_dict()


# ═══════════════════════════════════════════
#   AI Chatbot (Data Explorer)
# ═══════════════════════════════════════════

GOOGLE_API_KEY = os.environ.get('GOOGLE_API_KEY')

# Toggle chat panel open/closed
dash.clientside_callback(
    """
    function(toggleClicks, closeClicks) {
        const panel = document.getElementById('chat-panel');
        const fab = document.getElementById('chat-toggle-btn');
        if (!panel) return window.dash_clientside.no_update;

        const isOpen = panel.classList.contains('chat-panel-open');
        if (isOpen) {
            panel.classList.remove('chat-panel-open');
            if (fab) fab.classList.remove('chat-fab-hidden');
        } else {
            panel.classList.add('chat-panel-open');
            if (fab) fab.classList.add('chat-fab-hidden');
            // Focus input
            setTimeout(() => {
                const input = document.getElementById('chat-input');
                if (input) input.focus();
            }, 300);
        }
        return window.dash_clientside.no_update;
    }
    """,
    Output('chat-panel', 'id'),
    Input('chat-toggle-btn', 'n_clicks'),
    Input('chat-close-btn', 'n_clicks'),
    prevent_initial_call=True
)

# Auto-scroll + typewriter animation on new messages
dash.clientside_callback(
    """
    function(children) {
        setTimeout(() => {
            const el = document.getElementById('chat-messages');
            if (!el) return;
            el.scrollTop = el.scrollHeight;

            // Find any new typewriter bubbles that haven't been animated yet
            const bubbles = el.querySelectorAll('.chat-typewriter:not(.chat-tw-started)');
            bubbles.forEach(bubble => {
                bubble.classList.add('chat-tw-started');
                const fullText = bubble.getAttribute('data-fulltext');
                if (!fullText) return;

                const words = fullText.split(/( +)/);  // preserve spaces
                let idx = 0;
                bubble.textContent = '';

                const interval = setInterval(() => {
                    if (idx < words.length) {
                        bubble.textContent += words[idx];
                        idx++;
                        el.scrollTop = el.scrollHeight;
                    } else {
                        clearInterval(interval);
                        bubble.classList.add('chat-tw-done');
                    }
                }, 30);
            });
        }, 60);
        return window.dash_clientside.no_update;
    }
    """,
    Output('chat-send-btn', 'id'),
    Input('chat-messages', 'children'),
    prevent_initial_call=True
)

# Instant loading state — shows user bubble + typing dots before server responds
dash.clientside_callback(
    """
    function(sendClicks, nSubmit, inputValue) {
        if (!inputValue || !inputValue.trim()) return window.dash_clientside.no_update;

        const messages = document.getElementById('chat-messages');
        if (!messages) return window.dash_clientside.no_update;

        // Append user bubble
        const userDiv = document.createElement('div');
        userDiv.className = 'chat-message chat-message-user';
        const bubble = document.createElement('div');
        bubble.className = 'chat-bubble chat-bubble-user';
        bubble.textContent = inputValue.trim();
        userDiv.appendChild(bubble);
        messages.appendChild(userDiv);

        // Append loading dots
        const loadDiv = document.createElement('div');
        loadDiv.className = 'chat-message chat-message-ai';
        loadDiv.id = 'chat-loading-indicator';
        loadDiv.innerHTML = '<div class="chat-bubble chat-bubble-ai"><div class="chat-loading-dots"><span></span><span></span><span></span></div></div>';
        messages.appendChild(loadDiv);

        // Scroll to bottom
        messages.scrollTop = messages.scrollHeight;

        // Clear input immediately for snappy feel
        const input = document.getElementById('chat-input');
        if (input) input.value = '';

        return window.dash_clientside.no_update;
    }
    """,
    Output('chat-loading-trigger', 'children'),
    Input('chat-send-btn', 'n_clicks'),
    Input('chat-input', 'n_submit'),
    State('chat-input', 'value'),
    prevent_initial_call=True
)


def _build_plot_context(data, selected_predictors, options, plot_mode=None, compare_vars=None):
    """Build a comprehensive text summary of all data available in the Data section."""
    if not data:
        return "No data has been loaded yet."

    import numpy as np

    df = pd.DataFrame(data)
    df['Date'] = pd.to_datetime(df['Date'])
    df = df.sort_values('Date')

    label_map = {opt['value']: opt['label'] for opt in (options or [])}
    numeric_cols = [c for c in df.columns if c != 'Date' and df[c].dtype in ['float64', 'int64', 'float32']]

    lines = []

    # Dataset overview
    lines.append(f"=== DATASET OVERVIEW ===")
    lines.append(f"Date range: {df['Date'].min().strftime('%Y-%m')} to {df['Date'].max().strftime('%Y-%m')}")
    lines.append(f"Data points: {len(df)} monthly observations")
    lines.append(f"Active plot mode: {plot_mode or 'timeseries'}")
    if plot_mode == 'compare' and compare_vars:
        cmp_names = [label_map.get(v, v) for v in compare_vars]
        if len(compare_vars) == 2:
            lines.append(f"Compare mode: 2D line plot — X={cmp_names[0]}, Y={cmp_names[1]}")
        elif len(compare_vars) >= 3:
            lines.append(f"Compare mode: 3D surface — X={cmp_names[0]}, Y={cmp_names[1]}, Z(surface)={cmp_names[2]}")
    if selected_predictors:
        sel_names = [label_map.get(v, v) for v in selected_predictors]
        lines.append(f"Variables on time series chart: {', '.join(sel_names)}")

    # All variable summaries
    lines.append(f"\n=== ALL VARIABLES (summary stats) ===")
    for col in numeric_cols:
        s = df[col].dropna()
        if s.empty:
            continue
        friendly = label_map.get(col, col)
        latest = s.iloc[-1]
        lines.append(f"• {friendly}: latest={latest:.4f}, min={s.min():.4f}, max={s.max():.4f}, mean={s.mean():.4f}")
        if len(s) >= 2:
            pct_m = ((s.iloc[-1] - s.iloc[-2]) / abs(s.iloc[-2])) * 100 if s.iloc[-2] != 0 else 0
            lines.append(f"    MoM: {pct_m:+.2f}%")
        if len(s) >= 12:
            yoy = ((s.iloc[-1] - s.iloc[-12]) / abs(s.iloc[-12])) * 100 if s.iloc[-12] != 0 else 0
            lines.append(f"    YoY: {yoy:+.2f}%")

    # Correlation matrix — top correlations with ZAR/USD and between variables
    lines.append(f"\n=== KEY CORRELATIONS ===")
    if 'ZAR_USD' in numeric_cols and len(numeric_cols) > 1:
        corr = df[numeric_cols].corr()

        # ZAR/USD correlations ranked
        zar_corr = corr['ZAR_USD'].drop('ZAR_USD').sort_values(key=abs, ascending=False)
        lines.append("Correlations with ZAR/USD (ranked by strength):")
        for var, r in zar_corr.items():
            friendly = label_map.get(var, var)
            direction = "positive" if r > 0 else "negative"
            strength = "strong" if abs(r) > 0.7 else "moderate" if abs(r) > 0.4 else "weak"
            lines.append(f"  • {friendly}: r={r:.3f} ({strength} {direction})")

        # Strongest inter-variable correlations (top 5 pairs, excluding self)
        lines.append("\nStrongest inter-variable correlations:")
        pair_list = []
        for i, c1 in enumerate(numeric_cols):
            for c2 in numeric_cols[i+1:]:
                r = corr.loc[c1, c2]
                pair_list.append((c1, c2, r))
        pair_list.sort(key=lambda x: abs(x[2]), reverse=True)
        for c1, c2, r in pair_list[:5]:
            f1 = label_map.get(c1, c1)
            f2 = label_map.get(c2, c2)
            lines.append(f"  • {f1} vs {f2}: r={r:.3f}")

    # Compare mode — 3D surface analysis
    compare_vars = compare_vars or []
    cmp = [v for v in compare_vars if v in df.columns]
    if plot_mode == 'compare' and len(cmp) >= 3:
        cx, cy, cz = cmp[0], cmp[1], cmp[2]
        cx_l = label_map.get(cx, cx)
        cy_l = label_map.get(cy, cy)
        cz_l = label_map.get(cz, cz)
        lines.append(f"\n=== 3D SURFACE ANALYSIS ({cx_l} × {cy_l} → {cz_l}) ===")
        sub = df[[cx, cy, cz]].dropna()
        if len(sub) >= 4:
            # Pairwise correlations among the 3 vars
            lines.append(f"Pairwise correlations:")
            lines.append(f"  {cx_l} vs {cy_l}: r={sub[cx].corr(sub[cy]):.3f}")
            lines.append(f"  {cx_l} vs {cz_l}: r={sub[cx].corr(sub[cz]):.3f}")
            lines.append(f"  {cy_l} vs {cz_l}: r={sub[cy].corr(sub[cz]):.3f}")

            # Surface shape — check where Z is highest/lowest
            z_vals = sub[cz]
            max_row = sub.loc[z_vals.idxmax()]
            min_row = sub.loc[z_vals.idxmin()]
            lines.append(f"Surface peak ({cz_l} max={max_row[cz]:.4f}): "
                         f"at {cx_l}={max_row[cx]:.4f}, {cy_l}={max_row[cy]:.4f}")
            lines.append(f"Surface trough ({cz_l} min={min_row[cz]:.4f}): "
                         f"at {cx_l}={min_row[cx]:.4f}, {cy_l}={min_row[cy]:.4f}")

            # Partial correlation direction — how does Z change with X holding Y roughly constant?
            from numpy.polynomial import polynomial as P
            try:
                coeffs = np.polyfit(sub[[cx, cy]].values.T[0], sub[cz].values, 1)
                slope_x = coeffs[0]
                lines.append(f"Marginal slope: {cz_l} changes ~{slope_x:.4f} per unit of {cx_l}")
            except Exception:
                pass

    elif plot_mode == 'compare' and len(cmp) == 2:
        cx, cy = cmp[0], cmp[1]
        cx_l = label_map.get(cx, cx)
        cy_l = label_map.get(cy, cy)
        lines.append(f"\n=== 2D COMPARE ({cx_l} vs {cy_l}) ===")
        pair = df[[cx, cy]].dropna()
        if len(pair) >= 2:
            r = pair[cx].corr(pair[cy])
            lines.append(f"Correlation: r={r:.3f}, R²={r**2:.3f}")
            lines.append(f"These are plotted as a line plot with {cx_l} on X-axis and {cy_l} on Y-axis.")

    return "\n".join(lines)


@callback(
    Output('chat-messages', 'children'),
    Output('chat-input', 'value'),
    Output('chat-history', 'data'),
    Input('chat-send-btn', 'n_clicks'),
    Input('chat-input', 'n_submit'),
    State('chat-input', 'value'),
    State('chat-messages', 'children'),
    State('chat-history', 'data'),
    State('fetched-data', 'data'),
    State('selected-predictors', 'data'),
    State('predictor-dropdown-options-store', 'data'),
    State('plot-mode', 'data'),
    State('selected-compare-vars', 'data'),
    prevent_initial_call=True
)
def handle_chat_send(send_clicks, n_submit, user_msg, current_messages, chat_history,
                     fetched_data, selected_predictors, predictor_options, plot_mode, compare_vars):
    if not user_msg or not user_msg.strip():
        return dash.no_update, dash.no_update, dash.no_update

    user_msg = user_msg.strip()
    current_messages = current_messages or []
    chat_history = chat_history or []

    # Add user message bubble
    current_messages.append(
        html.Div(className='chat-message chat-message-user', children=[
            html.Div(user_msg, className='chat-bubble chat-bubble-user')
        ])
    )

    # Build comprehensive context from all data
    plot_context = _build_plot_context(fetched_data, selected_predictors, predictor_options, plot_mode, compare_vars)

    # Add to conversation history for Gemini
    chat_history.append({'role': 'user', 'parts': [user_msg]})

    # Call Gemini
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=GOOGLE_API_KEY)

        system_instruction = (
            "You are an economics assistant embedded in a ZAR/USD exchange rate dashboard. "
            "You have full access to the dataset context below, including all variables, their latest values, "
            "month-over-month and year-over-year changes, and the full correlation matrix between all variables. "
            "You ONLY answer questions about: the data in the dashboard, ZAR/USD exchange rate dynamics, "
            "macroeconomic indicators (interest rates, inflation, oil prices, gold, VIX, economic policy uncertainty), "
            "South African and US economics, correlations between variables, and how these factors relate to the Rand. "
            "If the user asks about anything unrelated, politely decline and redirect them to data or economics questions. "
            "When discussing correlations, cite the actual r values from the data. "
            "Keep answers concise (2-4 sentences) unless the user asks for detail. "
            "The dashboard has three plot modes: Time Series (dual Y-axis), Compare (2D scatter or 3D), "
            "and Correlation (heatmap). Reference these when relevant.\n\n"
            f"DASHBOARD DATA CONTEXT:\n{plot_context}"
        )

        # Build contents list for the API
        contents = []
        for msg in chat_history:
            contents.append(types.Content(
                role=msg['role'],
                parts=[types.Part.from_text(text=msg['parts'][0])]
            ))

        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                max_output_tokens=2048,
                temperature=0.7,
            )
        )

        ai_text = (response.text or "I couldn't generate a response. Please try again.").strip()
    except Exception as e:
        print(f"[Chatbot Error] {type(e).__name__}: {e}")
        traceback.print_exc()
        ai_text = f"Sorry, I couldn't process that request. ({type(e).__name__}: {e})"

    # Save AI response to history
    chat_history.append({'role': 'model', 'parts': [ai_text]})

    # Add AI message bubble with typewriter data attribute
    # The clientside callback will animate word-by-word reveal
    current_messages.append(
        html.Div(className='chat-message chat-message-ai', children=[
            html.Div('', className='chat-bubble chat-bubble-ai chat-typewriter',
                     **{'data-fulltext': ai_text})
        ])
    )

    return current_messages, '', chat_history