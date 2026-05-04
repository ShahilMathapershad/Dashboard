import os
import dash
from dash import html, dcc, callback, Input, Output, State
import dash_bootstrap_components as dbc
from logic.data_fetcher import (
    fetch_fred_data, fetch_world_bank_gold_data, fetch_sa_inflation_hardcoded,
    process_data, save_to_supabase, replace_gold_price_column_in_supabase,
    FRED_API_KEY, SERIES_CONFIG,
)
from logic.model import (predict_next_month, fetch_data_from_supabase, get_scenario_baseline,
                         scenario_predict, get_friendly_feature_name as model_get_friendly_name,
                         get_coefficient_unit as model_get_coef_unit, get_feature_category,
                         get_test_set_predictions)
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
            html.Span(label, className='scenario-slider-label', style={'fontWeight': '600', 'fontSize': '0.9rem'}),
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
    icons = {'data': '⊞', 'model': '◆', 'scenario': '◇'}
    def link(id_, label, tab_name):
        classes = 'nav-link-custom active' if active_tab == tab_name else 'nav-link-custom'
        return html.Div(id=id_, className=classes, children=[
            html.Span(icons.get(tab_name, ''), className='nav-icon'),
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
        html.Div(className='topbar-left', children=[
            html.Div('☰', id='mobile-menu-btn', className='mobile-menu-btn', role='button', tabIndex=0),
            html.Div(className='topbar-breadcrumb', children=[
                html.Span('ZAR/USD Dashboard', className='topbar-root'),
                html.Span(' / ', className='topbar-sep'),
                html.Span('Data Explorer', id='topbar-page-name', className='topbar-page'),
            ]),
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
                html.Button(
                    '↻ Refresh Data',
                    id='refresh-data-btn',
                    className='btn-ghost',
                    n_clicks=0,
                    title='Force re-fetch from FRED, World Bank & Stats SA APIs (SA CPI is hardcoded)',
                ),
            ])
        ]),

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

            dcc.Graph(
                id='zar-graph',
                className='hero-chart',
                style={'height': 'clamp(300px, 55vh, 760px)', 'width': '100%'},
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
            html.Div(id='data-table-container', className='table-card', style={'display': 'none'}, children=[
                html.Div(className='table-controls', children=[
                    html.Div(className='plot-mode-toggle', children=[
                        html.Button('Raw', id='table-mode-raw', className='plot-mode-btn plot-mode-active', n_clicks=0),
                        html.Button('% Change', id='table-mode-pct', className='plot-mode-btn', n_clicks=0),
                    ]),
                    html.Button('↓ Download CSV', id='download-csv-btn', className='btn-ghost', n_clicks=0),
                ]),
                html.Div(id='data-table-body'),
                dcc.Download(id='download-csv'),
            ]),
        ]),

    ])


def model_tab_content(existing_model_data=None):
    model_style = {'display': 'block'} if existing_model_data else {'display': 'none'}
    return html.Div(id='model-tab', className='tab-content', style={'display': 'none'}, children=[
        html.Div(className='page-header', children=[
            html.Div(children=[
                html.H2('Model', className='page-title'),
                html.P("HuberRegressor error-correction model for ZAR/USD.",
                       className='page-subtitle'),
            ]),
            html.Div(className='page-actions', children=[
                # Sub-tab toggle
                html.Div(className='model-sub-tab-toggle', children=[
                    html.Button('Predictions', id='model-sub-predictions', className='model-sub-tab-btn model-sub-tab-active', n_clicks=0),
                    html.Button('Specifications', id='model-sub-specifications', className='model-sub-tab-btn', n_clicks=0),
                ]),
                html.Div(id='model-status-display', className='status-badge', style={'marginLeft': '12px'}),
            ])
        ]),

        # Loading state
        _render_loading_state('model', 'Running model prediction...',
                             'Analyzing latest macroeconomic drivers and generating forecast.',
                             visible=not existing_model_data),

        html.Div(id='model-results-container', style=model_style, children=[

            # ── SUB-TAB: Predictions ──
            html.Div(id='model-predictions-panel', children=[
                # Multi-horizon Forecast Cards
                html.Div(className='model-card', children=[
                    html.H4('ZAR/USD Forecast', className='card-title'),
                    html.P('Point estimates and fair values across multiple horizons.',
                           className='card-subtitle'),
                    html.Div(id='forecast-table-container', className='forecast-table-wrapper')
                ]),

                # Feature Contributions
                html.Div(className='model-card', children=[
                    html.H4('What\'s Driving the Forecast', className='card-title'),
                    html.P('Anchored on last month\'s rate, then adjusted by 10 macro correction signals.',
                           className='card-subtitle'),
                    html.Div(id='feature-contributions'),
                ]),

                # Dynamic model description / analysis
                html.Div(className='model-card', children=[
                    html.H4('Forecast Summary', className='card-title'),
                    html.Div(id='model-description-content', className='model-analysis-text', style={
                        'lineHeight': '1.7',
                        'color': 'var(--text-2)',
                        'fontSize': '0.9375rem',
                    }),
                ]),
            ]),

            # ── SUB-TAB: Specifications ──
            html.Div(id='model-specifications-panel', style={'display': 'none'}, children=[
                # Model Info
                html.Div(className='model-card model-info-card', children=[
                    html.H4('Model Specification & Performance', className='card-title'),
                    html.P('Architecture, hyperparameters, and out-of-sample test metrics.',
                           className='card-subtitle'),
                    html.Div(id='model-info-content'),
                ]),

                # Out-of-Sample Test Set Chart
                html.Div(className='model-card', children=[
                    html.H4('Out-of-Sample Test Performance', className='card-title'),
                    html.P('Actual vs predicted ZAR/USD on the held-out test set (post-training period).',
                           className='card-subtitle'),
                    html.Div(id='test-set-chart-container'),
                ]),

                # Diagnostic Plots Section
                html.Div(className='model-card', children=[
                    html.H4('Diagnostic Plots', className='card-title'),
                    html.P('Visual checks of model fit quality and per-feature relationships.',
                           className='card-subtitle'),
                    html.Div(id='diagnostics-container'),
                ]),

                # Legacy Inference Comparison
                html.Div(className='model-card', children=[
                    html.H4('Live Forecast Inference — Jan/Feb/Mar 2026', className='card-title'),
                    html.P(
                        'Production models retrained at each month-end snapshot (Jan 2026, Feb 2026, '
                        'Mar 2026) then evaluated against the realised ZAR/USD one month later. '
                        'Measures real-world point-in-time forecast accuracy.',
                        className='card-subtitle',
                    ),
                    html.Div(
                        className='info-box',
                        style={'marginBottom': '12px', 'padding': '10px 14px',
                               'borderRadius': '8px', 'fontSize': '0.82rem', 'lineHeight': '1.55'},
                        children=[
                            html.Strong('Spot at Cutoff vs Predicted: '),
                            'Spot at cutoff is the actual ZAR/USD rate on the last day the model had data '
                            '(e.g. Jan 31, 2026). Predicted is the model\'s forecast for the following '
                            'month-end (e.g. Feb 28, 2026). The key subtlety: the passthrough feature '
                            'ZAR_USD_lag1 is Sₜ₋₁ (the prior month\'s rate), not the current '
                            'spot. So even though β₁ ≈ 0.96, the predicted value is anchored '
                            'to the previous month\'s rate — meaning spot and predicted can diverge '
                            'meaningfully when the last two months moved sharply.',
                        ],
                    ),
                    html.Div(id='legacy-inference-container'),
                ]),
            ]),
        ]),
    ])


def scenario_tab_content():
    return html.Div(id='scenario-tab', className='tab-content', style={'display': 'none'}, children=[
        html.Div(className='page-header', children=[
            html.Div(children=[
                html.H2('Scenario Analysis', className='page-title'),
                html.P("Adjust VIX, policy uncertainty, bond rates, and gold price to see how the HuberRegressor error-correction model responds.",
                       className='page-subtitle'),
            ]),
            html.Div(className='page-actions', children=[
                html.Button('💾 Save Scenario', id='scenario-save-btn', className='btn-primary', n_clicks=0,
                            style={'marginRight': '8px'}),
                html.Button('Reset All', id='scenario-reset-btn', className='btn-ghost', n_clicks=0),
                html.Div(id='scenario-status-display', className='status-badge', style={'marginLeft': '12px'}),
            ])
        ]),

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
                html.Div(className='model-card scenario-waterfall-panel', children=[
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
        html.Div(id='sidebar-overlay', className='sidebar-overlay', n_clicks=0),
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
        var container = document.getElementById('dashboard-container');
        var toggleBtn = document.getElementById('sidebar-toggle');
        // Force collapsed on mobile regardless of localStorage
        var isMobile = window.innerWidth <= 1024;
        var effectiveState = isMobile ? 'collapsed' : state;
        if (effectiveState === 'collapsed') {
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
        return dash.no_update
    return current_tab or 'data'


# Update sidebar active classes and tab visibility via clientside callback (instant, no server roundtrip)
dash.clientside_callback(
    """
    function(activeTab) {
        var tabIds = ['data-tab', 'model-tab', 'scenario-tab'];
        var tabKeys = ['data', 'model', 'scenario'];
        var tabNames = {
            'data': 'Data Explorer',
            'model': 'Model',
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
    State('_pages_location', 'pathname'),
)
def update_topbar_user(session_data, pathname):
    # Topbar elements only exist on /dashboard.
    if pathname != '/dashboard':
        return dash.no_update, dash.no_update
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


def _prepare_table_df(df_all):
    """Convert raw data list/df to a sorted DataFrame with proper Date column."""
    if df_all is None or (isinstance(df_all, pd.DataFrame) and df_all.empty) or (
            isinstance(df_all, list) and not df_all):
        return None
    if isinstance(df_all, list):
        df_all = pd.DataFrame(df_all)
    df_all['Date'] = pd.to_datetime(df_all['Date']).dt.strftime('%Y-%m-%d')
    return df_all.sort_values('Date', ascending=True)


def _generate_data_table(df_all, mode='raw'):
    """Build an HTML table in either 'raw' or 'pct' (MoM % change) mode."""
    df_sorted = _prepare_table_df(df_all)
    if df_sorted is None:
        return html.Div("No data available for table.")

    all_vars = [c for c in df_sorted.columns if c != 'Date']
    if 'ZAR_USD' in all_vars:
        all_vars.remove('ZAR_USD')
        all_vars.insert(0, 'ZAR_USD')

    # Build the display DataFrame
    if mode == 'pct':
        # Vectorized MoM % change replaces the old O(n²) per-cell iloc scan.
        # pct_change emits inf when prev==0; coerce to NaN to match the original
        # `prev != 0` guard.
        import numpy as np
        pct_vals = df_sorted[all_vars].pct_change() * 100
        pct_vals = pct_vals.replace([np.inf, -np.inf], np.nan)
        df_display = pct_vals.assign(Date=df_sorted['Date']).iloc[1:]
        df_display = df_display.sort_values('Date', ascending=False)
    else:
        df_display = df_sorted.sort_values('Date', ascending=False)

    # Friendly column names
    friendly = {}
    for v in all_vars:
        name = 'ZAR/USD' if v == 'ZAR_USD' else SERIES_CONFIG.get(v, {}).get('label', v)
        if len(name) > 25:
            name = name.replace('(', '\n(').replace(' for ', '\n')
            name = '\n'.join([l.strip() for l in name.split('\n') if l.strip()])
        friendly[v] = name

    col_headers = ['Date'] + [friendly[v] for v in all_vars]
    header = html.Thead(html.Tr(
        [html.Th(c, style={'textAlign': 'center', 'whiteSpace': 'pre-line', 'fontSize': '0.75rem'})
         for c in col_headers]))

    body_rows = []
    # to_dict('records') is several times faster than iterrows() because it
    # avoids constructing a fresh Series per row.
    for row in df_display.to_dict('records'):
        tds = [html.Td(row['Date'], style={'fontWeight': '500'})]
        for col in all_vars:
            val = row.get(col)
            if pd.isna(val):
                tds.append(html.Td('-', style={'textAlign': 'center'}))
            elif mode == 'pct':
                if col == 'ZAR_USD':
                    color = '#EF4444' if val > 0 else '#10B981' if val < 0 else '#6b6b6b'
                    tds.append(html.Td(f"{val:+.2f}%", style={
                        'color': color, 'fontWeight': '700', 'textAlign': 'center', 'fontSize': '1.05em'}))
                else:
                    color = '#10B981' if val > 0 else '#EF4444' if val < 0 else '#6b6b6b'
                    tds.append(html.Td(f"{val:+.2f}%", style={
                        'color': color, 'fontWeight': '600', 'textAlign': 'center'}))
            else:
                fmt = f"{val:.4f}" if abs(val) < 1000 else f"{val:.2f}"
                tds.append(html.Td(fmt, style={'textAlign': 'center', 'fontVariantNumeric': 'tabular-nums'}))
        body_rows.append(html.Tr(tds))

    return html.Table(className='custom-table', children=[header, html.Tbody(body_rows)])


@callback(
    Output('fetch-status-display', 'children'),
    Output('visualization-container', 'style', allow_duplicate=True),
    Output('data-table-body', 'children'),
    Output('data-loading', 'style'),
    Input('dashboard-tab', 'data'),
    Input('fetched-data', 'data'),
    Input('fetched-data-status', 'data'),
    Input('table-view-mode', 'data'),
    State('_pages_location', 'pathname'),
    prevent_initial_call='initial_duplicate'
)
def sync_data_tab_ui(active_tab, data, status_info, table_mode, pathname):
    # Outputs only exist on /dashboard. If a Store change fires this callback
    # while we're elsewhere (e.g. on /login), no-op to avoid "nonexistent object"
    # warnings.
    if pathname != '/dashboard' or active_tab != 'data':
        return dash.no_update, dash.no_update, dash.no_update, dash.no_update

    status_msg = ""
    if status_info:
        status_msg = html.Span(status_info.get('text', ''), style={'color': status_info.get('color', '#6b6b6b')})

    viz_style = {'display': 'block', 'marginTop': '2rem'} if data else {'display': 'none'}
    loading_style = {'display': 'none'} if data else {'display': 'flex'}

    table = _generate_data_table(data, mode=table_mode or 'raw') if data else ""

    return status_msg, viz_style, table, loading_style


# Refresh button → force a full API re-fetch
@callback(
    Output('fetched-data', 'data', allow_duplicate=True),
    Output('fetched-data-status', 'data', allow_duplicate=True),
    Output('force-refresh-trigger', 'data'),
    Input('refresh-data-btn', 'n_clicks'),
    prevent_initial_call=True,
)
def handle_refresh_click(n_clicks):
    if not n_clicks:
        return dash.no_update, dash.no_update, dash.no_update
    # Clear existing data so the fetch callback runs the full API path
    return None, None, n_clicks


# Disable the refresh button while a fetch is in flight. Replaces the
# `running=` parameter that used to live on `fetch_data`.
dash.clientside_callback(
    """
    function(triggerVal, fetchedData) {
        const ctx = window.dash_clientside.callback_context;
        if (!ctx.triggered.length) return window.dash_clientside.no_update;
        const trig = ctx.triggered[0].prop_id;
        if (trig === 'force-refresh-trigger.data') return true;          // fetch starting
        if (trig === 'fetched-data.data') return !fetchedData ? true : false;
        return window.dash_clientside.no_update;
    }
    """,
    Output('refresh-data-btn', 'disabled'),
    Input('force-refresh-trigger', 'data'),
    Input('fetched-data', 'data'),
    prevent_initial_call=True,
)


# Refresh button → re-fetch from APIs and overwrite Supabase. Initial /dashboard
# hydration is handled by core.cache_callbacks.hydrate_dashboard; this callback
# only fires when the user explicitly clicks Refresh.
@callback(
    Output('fetched-data', 'data', allow_duplicate=True),
    Output('data-error', 'children', allow_duplicate=True),
    Output('predictor-dropdown-options-store', 'data', allow_duplicate=True),
    Output('selected-predictors', 'data', allow_duplicate=True),
    Output('fetched-data-status', 'data', allow_duplicate=True),
    Output('model-prediction-data', 'data', allow_duplicate=True),
    Output('scenario-baseline-data', 'data', allow_duplicate=True),
    Input('force-refresh-trigger', 'data'),
    background=True,
    prevent_initial_call=True,
)
def fetch_data(force_refresh):
    import pandas as pd

    _no_update_7 = (dash.no_update,) * 7

    if not force_refresh:
        return dash.no_update, '', dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update

    try:
        fred_series = {name: cfg['id'] for name, cfg in SERIES_CONFIG.items() if cfg['source'] == 'FRED'}
        raw = fetch_fred_data(fred_series, api_key=FRED_API_KEY, progress_callback=None)

        wb_gold = fetch_world_bank_gold_data(start_date='2009-12-31')
        if not wb_gold.empty:
            raw = pd.concat([raw, wb_gold.to_frame(name='GOLD_PRICE')], axis=1)

        sa_inflation = fetch_sa_inflation_hardcoded()
        raw = pd.concat([raw, sa_inflation], axis=1)

        if raw.empty:
            return dash.no_update, 'Failed to fetch data from APIs.', dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update

        processed = process_data(raw, start_date='2009-12-31')
        status_data = {'text': '● Updated from API', 'color': '#3B82F6'}

        if processed.empty:
            return dash.no_update, 'No data available.', dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update

        supabase_ok = True
        try:
            save_to_supabase(processed)
            if not wb_gold.empty:
                replace_gold_price_column_in_supabase(wb_gold)
        except Exception as e:
            print(f"Warning: Could not save to Supabase: {e}")
            status_data = {'text': '● Updated (Supabase error)', 'color': '#F59E0B'}
            supabase_ok = False

        df_all = processed.reset_index()
        df_all['Date'] = pd.to_datetime(df_all['Date']).dt.strftime('%Y-%m-%d')

        numeric_cols = df_all.select_dtypes(include='number').columns
        df_all[numeric_cols] = df_all[numeric_cols].round(6)

        all_vars = [c for c in df_all.columns if c != 'Date']
        if 'ZAR_USD' in all_vars:
            all_vars.remove('ZAR_USD')
            all_vars.insert(0, 'ZAR_USD')

        dropdown_options = [
            {'label': SERIES_CONFIG.get(p, {}).get('label', p) if p != 'ZAR_USD' else 'ZAR/USD Exchange Rate', 'value': p}
            for p in all_vars
        ]
        default_predictors = ['ZAR_USD'] + all_vars[1:2] if len(all_vars) >= 2 else all_vars[:1]

        # Invalidate model diskcache so predictions reflect the newly saved data.
        model_pred = dash.no_update
        scenario_base = dash.no_update
        if supabase_ok:
            try:
                from logic.model.loading import _persistent_cache
                for key in ('supabase_data_df', 'predict_next_month_result',
                            'test_set_predictions', 'scenario_baseline_result'):
                    try:
                        del _persistent_cache[key]
                    except KeyError:
                        pass
                # Also invalidate the data-storage in-memory cache for this process.
                from logic.data.storage import _fetched_cache
                _fetched_cache['df'] = None
                _fetched_cache['time'] = 0
            except Exception as cache_err:
                print(f"Warning: Could not clear model caches: {cache_err}")

            # Re-run predictions against the freshly saved data so the Model and
            # Scenario tabs reflect the latest numbers without requiring a full
            # page reload.
            try:
                model_pred = {'raw_result': predict_next_month()}
            except Exception as pred_err:
                print(f"Warning: Model re-prediction after refresh failed: {pred_err}")

            try:
                scenario_base = get_scenario_baseline()
            except Exception as scen_err:
                print(f"Warning: Scenario re-baseline after refresh failed: {scen_err}")

        return df_all.to_dict('records'), "", dropdown_options, default_predictors, status_data, model_pred, scenario_base
    except Exception as e:
        traceback.print_exc()
        return dash.no_update, f'Error: {str(e)}', dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update


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


# Table view mode toggle (Raw / % Change)
@callback(
    Output('table-view-mode', 'data'),
    Output('table-mode-raw', 'className'),
    Output('table-mode-pct', 'className'),
    Input('table-mode-raw', 'n_clicks'),
    Input('table-mode-pct', 'n_clicks'),
    State('table-view-mode', 'data'),
    prevent_initial_call=True,
)
def toggle_table_mode(raw_clicks, pct_clicks, current_mode):
    ctx = dash.callback_context
    if not ctx.triggered:
        return current_mode, dash.no_update, dash.no_update
    trigger = ctx.triggered[0]['prop_id'].split('.')[0]
    if trigger == 'table-mode-raw':
        return 'raw', 'plot-mode-btn plot-mode-active', 'plot-mode-btn'
    return 'pct', 'plot-mode-btn', 'plot-mode-btn plot-mode-active'


# Download CSV — pulls fresh from Supabase
@callback(
    Output('download-csv', 'data'),
    Input('download-csv-btn', 'n_clicks'),
    State('table-view-mode', 'data'),
    prevent_initial_call=True,
)
def download_csv(n_clicks, table_mode):
    if not n_clicks:
        return dash.no_update

    # Always pull latest from Supabase for the download
    try:
        df = fetch_data_from_supabase()
        if df is None or df.empty:
            return dash.no_update
    except Exception:
        return dash.no_update

    df = df.reset_index()
    df['Date'] = pd.to_datetime(df['Date']).dt.strftime('%Y-%m-%d')
    df = df.sort_values('Date')

    if table_mode == 'pct':
        # Vectorized pct_change across all numeric columns at once instead of
        # one column at a time.
        numeric_cols = [c for c in df.columns if c != 'Date']
        pct_df = (df[numeric_cols].pct_change() * 100).iloc[1:].round(4)
        pct_df.insert(0, 'Date', df['Date'].iloc[1:].values)
        return dcc.send_data_frame(pct_df.to_csv, 'zar_usd_pct_changes.csv', index=False)
    else:
        return dcc.send_data_frame(df.to_csv, 'zar_usd_raw_data.csv', index=False)


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
    defaults = ['ZAR_USD']
    for o in options:
        if o['value'] != 'ZAR_USD':
            defaults.append(o['value'])
            break
    return defaults


# Ensure defaults are checked when user switches to compare mode
@callback(
    Output('selected-compare-vars', 'data', allow_duplicate=True),
    Input('plot-mode', 'data'),
    State('predictor-dropdown-options-store', 'data'),
    State('selected-compare-vars', 'data'),
    prevent_initial_call=True
)
def ensure_compare_defaults_on_switch(plot_mode, options, existing):
    if plot_mode != 'compare':
        return dash.no_update
    # Only backfill when the selection is genuinely empty. If the user has at
    # least one variable picked we leave them alone — the graph callback will
    # auto-default the missing axis when rendering.
    if existing:
        return dash.no_update
    if not options:
        return dash.no_update
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
    is_dark = theme != 'light'
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

        corr = df[numeric_cols].corr(min_periods=12)
        z = corr.values
        # Render NaN cells as '—' (insufficient overlap) instead of disguising
        # them as a genuine zero correlation. Plotly will leave the z-cell
        # blank when the value is NaN.
        text_grid = np.where(np.isnan(z), '—', np.round(z, 2).astype(str))

        fig = go.Figure(data=go.Heatmap(
            z=z,
            x=friendly_names,
            y=friendly_names,
            colorscale=[[0, '#EF4444'], [0.5, '#1a1a2e' if is_dark else '#f8f8fc'], [1, '#10B981']],
            zmin=-1, zmax=1,
            text=text_grid,
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
            # Auto-default: ZAR_USD vs first available other column
            available = [c for c in df.columns if c != 'Date' and df[c].notna().sum() > 0]
            if 'ZAR_USD' in available:
                available = ['ZAR_USD'] + [c for c in available if c != 'ZAR_USD']
            cmp = available[:2]
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
                method='linear',
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
        # Sorted by X to ensure a "one-to-one function" appearance, matching the
        # expectation for a non-temporal line plot.
        pair = df[['Date', compare_x, compare_y]].dropna().sort_values(compare_x)
        corr_val = pair[compare_x].corr(pair[compare_y]) if len(pair) >= 2 else None

        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=pair[compare_x], y=pair[compare_y],
                mode='lines',
                line=dict(color=color_palette[0], width=3, shape='spline'),
                customdata=pair['Date'].dt.strftime('%Y-%m'),
                hovertemplate=(f'<b>%{{customdata}}</b><br>'
                               f'{x_label}: %{{x:.4f}}<br>'
                               f'{y_label}: %{{y:.4f}}<extra></extra>'),
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
        # min/max already skip NaN in pandas, so an explicit dropna() copy is redundant.
        min_val = series.min()
        max_val = series.max()
        if pd.isna(min_val) or pd.isna(max_val):
            return series * 0
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
        custom = list(zip(df[var].tolist(), df['Date'].dt.strftime('%Y-%m').tolist()))
        fig.add_trace(
            go.Scatter(
                x=df['Date'], y=var_normalized,
                name=var_label,
                line=dict(color=color, width=width, shape='spline'),
                mode='lines',
                customdata=custom,
                hovertemplate=(f'<b>%{{customdata[1]}}</b><br>'
                               f'{var_label}: %{{customdata[0]:.4f}}<br>'
                               f'<span style="color:#86868b">Normalized: %{{y:.1f}}</span><extra></extra>'),
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
        hovermode="closest",
        hoverlabel=dict(
            bgcolor='rgba(18,18,20,0.75)' if is_dark else 'rgba(248,248,252,0.75)',
            font_size=12, font_family="Inter", font_color=text_color,
            bordercolor=line_color, namelength=-1,
        ),
        xaxis=dict(
            showgrid=False, zeroline=False, showline=True, linewidth=1, linecolor=line_color,
            tickfont=dict(size=10, color=text_muted), title=None,
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

def get_friendly_feature_name(feature_name, _transform_type=None):
    """Return a human-readable name for a feature (delegates to model.py)."""
    return model_get_friendly_name(feature_name)


def get_coefficient_unit(feature_name):
    """Return appropriate unit label for interpretable coefficients."""
    return model_get_coef_unit(feature_name)


@callback(
    Output('model-results-container', 'style'),
    Output('model-error', 'children', allow_duplicate=True),
    Output('forecast-table-container', 'children'),
    Output('feature-contributions', 'children'),
    Output('model-info-content', 'children'),
    Output('model-description-content', 'children'),
    Output('model-loading', 'style'),
    Input('dashboard-tab', 'data'),
    Input('model-prediction-data', 'data'),
    State('theme-store', 'data'),
    State('_pages_location', 'pathname'),
    prevent_initial_call='initial_duplicate'
)
def render_model_ui(active_tab, prediction_data, theme, pathname):
    # Outputs only exist on /dashboard. Guard against firing on other pages.
    if pathname != '/dashboard' or active_tab != 'model':
        return [dash.no_update] * 7

    if not prediction_data:
        return ({'display': 'none'}, '', '', '', '', '', {'display': 'flex'})

    result = prediction_data.get('raw_result')
    if not result:
        return ({'display': 'none'}, 'Prediction results unavailable.', '', '', '', '', {'display': 'none'})

    pred_level = result['predicted_level']
    direction = result['direction']
    change_pct = result['predicted_change_pct']
    date_text = result['next_month_date']
    last_zar = result['last_zar_usd']
    pred_change = result.get('predicted_change', pred_level - last_zar)

    # Direction styling
    if direction == 'strengthen':
        dir_color = '#10B981'
        dir_arrow = '▼'
        dir_label = 'ZAR Strengthens'
    elif direction == 'weaken':
        dir_color = '#EF4444'
        dir_arrow = '▲'
        dir_label = 'ZAR Weakens'
    else:
        dir_color = '#6b6b6b'
        dir_arrow = '—'
        dir_label = 'Stable'

    # ── Fair Value & Point Estimates ──
    fair_value = result.get('fair_value', pred_level)
    fv_misalign = result.get('fair_value_misalignment', 0)
    fv_misalign_pct = result.get('fair_value_misalignment_pct', 0)
    fv_signal = result.get('fair_value_signal', 'fairly_valued')

    # fv_signal == 'undervalued' means the rate (R per USD) is below fair value,
    # i.e. ZAR is currently too strong → ZAR Overvalued. The opposite for 'overvalued'.
    if fv_signal == 'undervalued':
        signal_color = '#EF4444'
        signal_label = 'ZAR Overvalued'
    elif fv_signal == 'overvalued':
        signal_color = '#10B981'
        signal_label = 'ZAR Undervalued'
    else:
        signal_color = '#6b6b6b'
        signal_label = 'Fairly Valued'

    forecasts = result.get('forecasts', {})

    # Build rows: Horizon | Point Estimate | Fair Value | Gap
    # Current row: spot vs today's fair value
    # Horizon rows: that horizon's point estimate vs that horizon's own fair value
    horizon_rows_data = [
        ('Current', result['last_date'], last_zar, fair_value),
    ]
    for key, label in [('1m', '1 Month'), ('3m', '3 Months'), ('6m', '6 Months')]:
        if key in forecasts:
            f = forecasts[key]
            horizon_rows_data.append((label, f['date'], f['point_estimate'], f['fair_value']))

    table_rows = []
    for label, date_str, spot_val, fv_val in horizon_rows_data:
        gap = spot_val - fv_val
        gap_pct = (gap / fv_val) * 100 if fv_val else 0
        gap_color = '#EF4444' if gap > 0.01 else '#10B981' if gap < -0.01 else '#6b6b6b'

        is_current = (label == 'Current')

        table_rows.append(
            html.Tr(className='ev-row ev-row-current' if is_current else 'ev-row', children=[
                html.Td(children=[
                    html.Div(label, className='ev-horizon-label'),
                    html.Div(date_str, className='ev-horizon-date'),
                ], className='ev-cell-horizon'),
                html.Td(f'R {spot_val:.2f}', className='ev-cell-spot'),
                html.Td(f'R {fv_val:.2f}', className='ev-cell-fv'),
                html.Td(children=[
                    html.Span(f'{gap:+.2f}', style={'color': gap_color}),
                    html.Span(f' ({gap_pct:+.1f}%)', className='ev-gap-pct', style={'color': gap_color}),
                ], className='ev-cell-gap'),
            ])
        )

    # Interpretation — reference horizon-specific fair values
    fv_1m = forecasts.get('1m', {}).get('fair_value', fair_value)
    fv_6m = forecasts.get('6m', {}).get('fair_value', fair_value)
    pt_1m = forecasts.get('1m', {}).get('point_estimate', pred_level)

    if fv_signal == 'undervalued':
        interp_text = (
            f'The ZAR is currently stronger than fundamentals suggest — spot (R {last_zar:.2f}) sits below '
            f'fair value (R {fair_value:.2f}), a {abs(fv_misalign_pct):.1f}% undervaluation. '
            f'Fair value itself shifts across horizons as ZAR-derived momentum and mean-reversion signals evolve: '
            f'from R {fair_value:.2f} today to R {fv_6m:.2f} at 6 months.'
        )
    elif fv_signal == 'overvalued':
        interp_text = (
            f'The ZAR is weaker than fundamentals suggest — spot (R {last_zar:.2f}) sits above '
            f'fair value (R {fair_value:.2f}), a {abs(fv_misalign_pct):.1f}% overvaluation. '
            f'As the model iterates forward, fair value adjusts from R {fair_value:.2f} today to R {fv_6m:.2f} at 6 months, '
            f'reflecting evolving ZAR momentum and mean-reversion dynamics.'
        )
    else:
        interp_text = (
            f'Spot (R {last_zar:.2f}) is closely aligned with today\'s fair value (R {fair_value:.2f}) — '
            f'only a {abs(fv_misalign_pct):.1f}% gap. Fair value shifts across horizons as ZAR-derived features evolve: '
            f'R {fv_1m:.2f} at 1 month, R {fv_6m:.2f} at 6 months. The gap column shows whether each point estimate '
            f'overshoots or undershoots its horizon\'s own equilibrium.'
        )

    # Signal badge
    signal_badge = html.Div(className='valuation-signal-row', children=[
        html.Div(className='valuation-signal-badge', style={'borderColor': signal_color}, children=[
            html.Span('●', style={'color': signal_color, 'marginRight': '6px', 'fontSize': '0.75rem'}),
            html.Span(signal_label, style={'fontWeight': '600', 'color': signal_color}),
            html.Span(
                f'  Gap: {abs(fv_misalign_pct):.1f}%' if fv_signal != 'fairly_valued' else '  Spot ≈ Fair Value',
                style={'color': 'var(--text-3)', 'marginLeft': '8px', 'fontSize': '0.8125rem'}
            ),
        ]),
    ])

    forecast_table = html.Div(className='estimates-panel', children=[
        signal_badge,
        html.Table(className='ev-table', children=[
            html.Thead(html.Tr([
                html.Th('Horizon', className='ev-th ev-th-horizon'),
                html.Th('Point Estimate', className='ev-th ev-th-spot'),
                html.Th('Fair Value', className='ev-th ev-th-fv'),
                html.Th('Gap', className='ev-th ev-th-gap'),
            ])),
            html.Tbody(table_rows),
        ]),
        html.Div(interp_text, className='ev-interpretation'),
    ])

    # ── Feature contributions ──
    # Separate the lag anchor from correction features
    lag_contrib = None
    correction_contribs = []
    for c in result['contributions']:
        if c['feature'] == 'ZAR_USD_lag1':
            lag_contrib = c
        else:
            correction_contribs.append(c)

    # Sort correction features by absolute contribution
    correction_contribs.sort(key=lambda x: abs(x['contribution']), reverse=True)
    max_correction = max((abs(x['contribution']) for x in correction_contribs), default=1)

    # Anchor summary
    anchor_value = lag_contrib['contribution'] if lag_contrib else 0
    intercept = result['model_info'].get('intercept', 0)
    total_correction = sum(c['contribution'] for c in correction_contribs) + (intercept or 0)

    contrib_rows = []

    # Anchor info card
    contrib_rows.append(
        html.Div(className='contrib-anchor-card', children=[
            html.Div(className='contrib-anchor-row', children=[
                html.Div(children=[
                    html.Span('Random Walk Anchor', style={'fontWeight': '600', 'fontSize': '0.875rem'}),
                    html.Span(
                        f'  Previous month (R {last_zar:.2f}) x 0.96 + intercept',
                        style={'color': 'var(--text-3)', 'fontSize': '0.8125rem', 'marginLeft': '8px'}
                    ),
                ]),
                html.Span(f'R {anchor_value + (intercept or 0):.2f}',
                          style={'fontWeight': '700', 'fontSize': '0.9375rem', 'color': 'var(--text-1)'}),
            ]),
            html.Div(className='contrib-anchor-row', style={'marginTop': '6px'}, children=[
                html.Div(children=[
                    html.Span('Correction Term', style={'fontWeight': '600', 'fontSize': '0.875rem'}),
                    html.Span(
                        '  Net adjustment from 10 macro signals',
                        style={'color': 'var(--text-3)', 'fontSize': '0.8125rem', 'marginLeft': '8px'}
                    ),
                ]),
                html.Span(f'{total_correction:+.2f} ZAR',
                          style={'fontWeight': '700', 'fontSize': '0.9375rem',
                                 'color': '#EF4444' if total_correction > 0 else '#10B981'}),
            ]),
        ])
    )

    # Correction feature bars
    for c in correction_contribs:
        feat_name = get_friendly_feature_name(c['feature'])
        contrib = c['contribution']

        if abs(contrib) < 0.0001:
            direction_label = 'Neutral'
        elif contrib > 0:
            direction_label = 'Weakens ZAR'
        else:
            direction_label = 'Strengthens ZAR'

        bar_color = '#EF4444' if contrib > 0 else '#10B981'
        bar_width = min(abs(contrib) / max_correction * 100, 100)

        contrib_rows.append(
            html.Div(className='contrib-row', children=[
                html.Div(className='contrib-info', children=[
                    html.Span(feat_name, className='contrib-name'),
                    html.Span(direction_label, className='contrib-direction'),
                ]),
                html.Div(className='contrib-bar-container', children=[
                    html.Div(className='contrib-bar', style={
                        'width': f'{max(bar_width, 2)}%',
                        'backgroundColor': bar_color,
                    }),
                ]),
                html.Span(f'{contrib:+.4f} ZAR', className='contrib-value',
                          style={'color': bar_color}),
            ])
        )

    # ── Model info ──
    info = result['model_info']
    metrics = result.get('metrics', {})

    # Build model info layout
    info_items = html.Div(children=[
        html.H5('Model Specification',
                style={'fontSize': '0.8125rem', 'fontWeight': '600', 'color': 'var(--text-2)', 'marginBottom': '12px'}),
        html.Div(className='model-info-grid', children=[
            _info_pill('Type', 'HuberRegressor (ℓ₂ penalty)',
                       'Robust regression that downweights outlier residuals via the Huber loss function, with Ridge (ℓ₂) regularization.'),
            _info_pill('Alpha (α)', f"{info['alpha']:.4f}" if info.get('alpha') is not None else "N/A",
                       'ℓ₂ regularisation strength. Higher α shrinks coefficients toward zero, trading bias for variance reduction.'),
            _info_pill('Epsilon (ε)', f"{info.get('epsilon', 1.1):.1f}",
                       'Huber loss transition point. Residuals exceeding ε·σ̂ are treated as outliers with linear (not quadratic) loss.'),
            _info_pill('Intercept (β₀)', f"{info['intercept']:+.4f}" if info.get('intercept') is not None else "N/A",
                       'Base level correction applied before lag and feature adjustments.'),
            _info_pill('Scale (σ̂)', f"{info.get('scale', 0):.4f}" if info.get('scale') else "N/A",
                       'Fitted robust standard deviation of residuals. Used with ε to classify outliers.'),
            _info_pill('Features', f"{info.get('n_selected', 0)} predictors (all non-zero)",
                       'All 11 economically motivated features contribute; none were shrunk to zero by ℓ₂ regularization.'),
            _info_pill('Training / Test', f"{info.get('training_observations', 'N/A')} / {info.get('test_observations', 'N/A')} obs",
                       'Chronological 80/20 split with no shuffling. 13 observations lost to rolling window + lag.'),
            _info_pill('Target', 'ZAR/USD Level (error-correction)',
                       'Predicts next month\'s exchange rate directly. Starts from S_{t-1} as random-walk anchor, then applies corrections.'),
        ]),
        html.H5('Out-of-Sample Performance Metrics (Test Set)',
                style={'fontSize': '0.8125rem', 'fontWeight': '600', 'color': 'var(--text-2)', 'marginTop': '24px',
                       'marginBottom': '12px'}),
        html.Div(className='model-info-grid', children=[
            _info_pill('MAE', f"ZAR {metrics.get('mae', 0):.4f}",
                       'Mean Absolute Error: Average forecast error in ZAR. Lower values indicate better precision.'),
            _info_pill('RMSE', f"ZAR {metrics.get('rmse', 0):.4f}",
                       'Root Mean Squared Error: Similar to MAE but penalizes larger misses more heavily.'),
            _info_pill('R²', f"{metrics.get('r2', 0):.4f}",
                       'Out-of-sample R². Proportion of test-set variance explained — noteworthy for FX (Meese-Rogoff puzzle).'),
            _info_pill('Adjusted R²', f"{metrics.get('adjusted_r2', 0):.4f}",
                       'R² penalized for number of predictors. Guards against overfitting by accounting for model complexity.'),
            _info_pill('MAPE', f"{metrics.get('mape', 0):.2f}%",
                       'Mean Absolute Percentage Error: Average error relative to the exchange rate level.'),
            _info_pill("Theil's U", f"{metrics.get('theils_u', 0):.4f}",
                       'Model RMSE / random-walk RMSE. U < 1 means the model beats the naïve forecast (U = 0.9969).'),
            _info_pill('Directional Accuracy', f"{metrics.get('directional_accuracy', 0):.1f}%",
                       'Correctly predicted direction in 67.65% of test months (vs 50% random guessing).'),
        ]),
        html.H5('Valuation & Forward Estimates',
                style={'fontSize': '0.8125rem', 'fontWeight': '600', 'color': 'var(--text-2)', 'marginTop': '24px',
                       'marginBottom': '12px'}),
        html.Div(className='model-info-grid', children=[
            _info_pill('Spot', f"R {result.get('last_zar_usd', 0):.4f}",
                       f"Latest ZAR/USD as of {result.get('last_date', 'N/A')}."),
            _info_pill('Fair Value (Now)', f"R {result.get('fair_value', 0):.4f}",
                       f"Equilibrium from current macro state. Gap vs spot: {result.get('fair_value_misalignment_pct', 0):+.1f}%."),
            _info_pill('1M Pt / FV', f"R {result.get('predicted_level', 0):.4f} / {result.get('forecasts', {}).get('1m', {}).get('fair_value', 0):.4f}",
                       f"Point estimate vs fair value at 1-month horizon."),
            _info_pill('3M Pt / FV', f"R {result.get('forecasts', {}).get('3m', {}).get('point_estimate', 0):.4f} / {result.get('forecasts', {}).get('3m', {}).get('fair_value', 0):.4f}",
                       f"Point estimate vs fair value at 3-month horizon."),
            _info_pill('6M Pt / FV', f"R {result.get('forecasts', {}).get('6m', {}).get('point_estimate', 0):.4f} / {result.get('forecasts', {}).get('6m', {}).get('fair_value', 0):.4f}",
                       f"Point estimate vs fair value at 6-month horizon."),
        ]),
    ])

    # Dynamic Description Generation — show the top *correction* driver, not the
    # lag1 random-walk anchor (which always dominates the raw contributions list).
    top_feature = correction_contribs[0] if correction_contribs else None
    feature_impact_text = ""
    if top_feature:
        feat_name = get_friendly_feature_name(top_feature['feature'])
        impact_dir = "depreciation" if top_feature['contribution'] > 0 else "appreciation"
        feature_impact_text = f"The most significant driver for this period is {feat_name}, which is associated with expected ZAR {impact_dir} pressure."

    direction_text = ""
    if direction == 'weaken':
        direction_text = f"The model forecasts a ZAR depreciation of {abs(change_pct):.2f}% against the USD."
    elif direction == 'strengthen':
        direction_text = f"The model forecasts a ZAR appreciation of {abs(change_pct):.2f}% against the USD."
    else:
        direction_text = "The model expects the ZAR/USD exchange rate to remain relatively stable."

    perf_text = (
        f"On the out-of-sample test set, this model achieved a directional accuracy of {metrics.get('directional_accuracy', 0):.1f}%, "
        f"Theil's U of {metrics.get('theils_u', 0):.4f} (marginally beating the random walk), "
        f"and a mean absolute error (MAE) of ZAR {metrics.get('mae', 0):.4f}."
    )

    analysis_content = html.Div([
        html.P(f"Based on the latest data for {result['last_date']}, {direction_text} {feature_impact_text}"),
        html.P(perf_text),
        html.P(
            "This forecast uses a HuberRegressor with ℓ₂ regularization — an error-correction model that starts from the previous month's "
            "exchange rate as a random-walk anchor, then applies small corrections based on momentum, mean-reversion, global risk sentiment, "
            "interest rate changes, and commodity prices. The Huber loss function ensures that extreme market shocks do not distort the relationships.")
    ])

    return ({'display': 'block'}, '', forecast_table, contrib_rows, info_items, analysis_content,
            {'display': 'none'})


# ── Model sub-tab toggle ──
@callback(
    Output('model-sub-tab', 'data'),
    Output('model-sub-predictions', 'className'),
    Output('model-sub-specifications', 'className'),
    Input('model-sub-predictions', 'n_clicks'),
    Input('model-sub-specifications', 'n_clicks'),
    State('model-sub-tab', 'data'),
    prevent_initial_call=True
)
def toggle_model_sub_tab(pred_clicks, spec_clicks, current):
    ctx = dash.callback_context
    if not ctx.triggered:
        return current, dash.no_update, dash.no_update
    trigger = ctx.triggered[0]['prop_id'].split('.')[0]
    active = 'model-sub-tab-btn model-sub-tab-active'
    inactive = 'model-sub-tab-btn'
    if trigger == 'model-sub-specifications':
        return 'specifications', inactive, active
    return 'predictions', active, inactive


dash.clientside_callback(
    """
    function(subTab) {
        var pred = document.getElementById('model-predictions-panel');
        var spec = document.getElementById('model-specifications-panel');
        if (pred && spec) {
            if (subTab === 'specifications') {
                pred.style.display = 'none';
                spec.style.display = 'block';
                spec.style.animation = 'none';
                void spec.offsetWidth;
                spec.style.animation = 'tabFadeIn 0.25s cubic-bezier(0,0,0.2,1)';
            } else {
                spec.style.display = 'none';
                pred.style.display = 'block';
                pred.style.animation = 'none';
                void pred.offsetWidth;
                pred.style.animation = 'tabFadeIn 0.25s cubic-bezier(0,0,0.2,1)';
            }
        }
        return window.dash_clientside.no_update;
    }
    """,
    Output('model-predictions-panel', 'id'),
    Input('model-sub-tab', 'data')
)


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
                except Exception:
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


@callback(
    Output('test-set-chart-container', 'children'),
    Input('dashboard-tab', 'data'),
    Input('model-sub-tab', 'data'),
    State('theme-store', 'data'),
    prevent_initial_call='initial_duplicate'
)
def render_test_set_chart(active_tab, sub_tab, theme):
    if active_tab != 'model' or sub_tab != 'specifications':
        return dash.no_update

    try:
        test_data = get_test_set_predictions()
    except Exception as e:
        return html.P(f'Unable to load test set data: {e}',
                      style={'color': 'var(--text-muted)', 'textAlign': 'center', 'padding': '20px'})

    dates = test_data['dates']
    actual = test_data['actual']
    predicted = test_data['predicted']

    is_dark = (theme == 'dark') if theme else True
    text_color = '#f5f5f7' if is_dark else '#1d1d1f'
    text_muted = '#86868b' if is_dark else '#6e6e73'
    grid_color = 'rgba(255,255,255,0.03)' if is_dark else 'rgba(0,0,0,0.03)'
    line_color = 'rgba(255,255,255,0.06)' if is_dark else 'rgba(0,0,0,0.06)'
    font_family = "-apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Inter', 'Segoe UI', sans-serif"

    fig = go.Figure()

    # Actual line
    fig.add_trace(go.Scatter(
        x=dates, y=actual,
        name='Actual',
        mode='lines+markers',
        line=dict(color='#E8E8E8' if is_dark else '#1A1A1A', width=2.5, shape='spline'),
        marker=dict(size=5, color='#E8E8E8' if is_dark else '#1A1A1A'),
        hovertemplate='<b>Actual</b>: R %{y:.4f}<br>%{x}<extra></extra>',
    ))

    # Predicted line
    fig.add_trace(go.Scatter(
        x=dates, y=predicted,
        name='Predicted',
        mode='lines+markers',
        line=dict(color='#5b8def', width=2.5, shape='spline', dash='dot'),
        marker=dict(size=5, color='#5b8def', symbol='diamond'),
        hovertemplate='<b>Predicted</b>: R %{y:.4f}<br>%{x}<extra></extra>',
    ))

    # Error shading between actual and predicted
    fig.add_trace(go.Scatter(
        x=dates + dates[::-1],
        y=actual + predicted[::-1],
        fill='toself',
        fillcolor='rgba(91,141,239,0.08)' if is_dark else 'rgba(91,141,239,0.12)',
        line=dict(width=0),
        hoverinfo='skip',
        showlegend=False,
    ))

    fig.update_layout(
        template=None,
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        autosize=True,
        font=dict(family=font_family, size=12, color=text_color),
        modebar=dict(bgcolor='rgba(0,0,0,0)', color=text_muted,
                     activecolor='#5b8def' if is_dark else '#4f7df3', orientation='v'),
        margin=dict(l=60, r=30, t=30, b=60),
        height=420,
        legend=dict(
            orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
            font=dict(size=11, color=text_muted), bgcolor='rgba(0,0,0,0)',
        ),
        hovermode="x unified",
        hoverlabel=dict(
            bgcolor='rgba(18,18,20,0.75)' if is_dark else 'rgba(248,248,252,0.75)',
            font_size=12, font_family="Inter", font_color=text_color,
            bordercolor=line_color, namelength=-1,
        ),
        xaxis=dict(
            title=dict(text='Date', font=dict(size=11, color=text_muted)),
            showgrid=True, gridwidth=1, gridcolor=grid_color, griddash='dot',
            zeroline=False, showline=True, linewidth=1, linecolor=line_color,
            tickfont=dict(size=10, color=text_muted),
        ),
        yaxis=dict(
            title=dict(text='ZAR / USD', font=dict(size=11, color=text_muted)),
            showgrid=True, gridwidth=1, gridcolor=grid_color, griddash='dot',
            zeroline=False, showline=True, linewidth=1, linecolor=line_color,
            tickfont=dict(size=10, color=text_muted),
            tickformat=".2f",
        ),
    )

    # Metrics summary pills
    metrics_row = html.Div(className='model-info-grid', style={'marginTop': '16px'}, children=[
        _info_pill('Test Observations', str(test_data['n_obs']),
                   f"Held-out data from {test_data['train_end']} onwards."),
        _info_pill('MAE', f"ZAR {test_data['mae']:.4f}",
                   'Mean Absolute Error on the out-of-sample test set.'),
        _info_pill('RMSE', f"ZAR {test_data['rmse']:.4f}",
                   'Root Mean Squared Error on the out-of-sample test set.'),
        _info_pill('R²', f"{test_data['r2']:.4f}",
                   'Proportion of test-set variance explained by the train-only model.'),
    ])

    return html.Div(children=[
        dcc.Graph(
            id='test-set-avp-chart',
            figure=fig.to_dict(),
            style={'height': '420px'},
            config={'displayModeBar': 'hover', 'displaylogo': False, 'responsive': True},
        ),
        metrics_row,
    ])


@callback(
    Output('legacy-inference-container', 'children'),
    Input('dashboard-tab', 'data'),
    Input('model-sub-tab', 'data'),
    State('theme-store', 'data'),
    prevent_initial_call='initial_duplicate',
)
def render_legacy_inference(active_tab, sub_tab, theme):
    if active_tab != 'model' or sub_tab != 'specifications':
        return dash.no_update

    import json as _json
    _JSON_PATH = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'models', 'legacy', 'inference_comparison.json',
    )
    try:
        with open(_JSON_PATH) as f:
            data = _json.load(f)
    except FileNotFoundError:
        return html.P('Legacy inference data not found.',
                      style={'color': 'var(--text-muted)', 'padding': '20px'})
    except Exception as exc:
        return html.P(f'Error loading legacy data: {exc}',
                      style={'color': 'var(--text-muted)', 'padding': '20px'})

    rows = data.get('rows', [])
    summary = data.get('summary', {})

    def _fmt_month(iso):
        try:
            import datetime
            d = datetime.date.fromisoformat(iso)
            return d.strftime('%b %Y')
        except Exception:
            return iso

    def _dir_badge(correct):
        if correct is None:
            return html.Span('—', style={'color': 'var(--text-3)'})
        if correct:
            return html.Span('HIT', style={
                'background': 'rgba(16,185,129,0.15)', 'color': '#10B981',
                'padding': '2px 9px', 'borderRadius': '4px',
                'fontSize': '0.6875rem', 'fontWeight': '700', 'letterSpacing': '0.03em',
            })
        return html.Span('MISS', style={
            'background': 'rgba(239,68,68,0.12)', 'color': '#ef4444',
            'padding': '2px 9px', 'borderRadius': '4px',
            'fontSize': '0.6875rem', 'fontWeight': '700', 'letterSpacing': '0.03em',
        })

    def _err_color(error):
        if error is None:
            return 'var(--text-1)'
        return '#ef4444' if abs(error) > 0.5 else '#10B981' if abs(error) < 0.2 else '#f59e0b'

    # Shared cell base — applied via style on each td
    _td = {'verticalAlign': 'middle'}
    _num = {**_td, 'textAlign': 'right', 'fontVariantNumeric': 'tabular-nums'}

    table_rows = []
    for r in rows:
        err = r.get('error')
        pct = r.get('pct_error')
        err_col = _err_color(err)
        table_rows.append(html.Tr(className='ev-row', children=[
            # Forecast month
            html.Td(style=_td, children=[
                html.Span(_fmt_month(r['predict_month']),
                          style={'fontSize': '0.8125rem', 'fontWeight': '600', 'color': 'var(--text-1)'}),
            ]),
            # Trained to
            html.Td(style=_td, children=[
                html.Span(_fmt_month(r['cutoff']),
                          style={'fontSize': '0.8rem', 'color': 'var(--text-2)'}),
            ]),
            # Spot (S_t-1 anchor)
            html.Td(style=_num, children=[
                html.Span(f"R {r['spot_at_cutoff']:.4f}",
                          style={'fontSize': '0.8125rem', 'color': 'var(--text-2)'}),
            ]),
            # Predicted
            html.Td(style=_num, children=[
                html.Span(f"R {r['predicted']:.4f}",
                          style={'fontSize': '0.8125rem', 'fontWeight': '600',
                                 'color': 'var(--accent)'}),
            ]),
            # Actual
            html.Td(style=_num, children=[
                html.Span(
                    f"R {r['actual']:.4f}" if r['actual'] else '—',
                    style={'fontSize': '0.8125rem', 'fontWeight': '600', 'color': 'var(--text-1)'},
                ),
            ]),
            # Error — ZAR + % stacked
            html.Td(style=_num, children=[
                html.Div([
                    html.Span(
                        f"{err:+.4f}" if err is not None else '—',
                        style={'fontSize': '0.8125rem', 'fontWeight': '600', 'color': err_col},
                    ),
                    html.Span(
                        f"  {pct:+.2f}%" if pct is not None else '',
                        style={'fontSize': '0.7rem', 'color': err_col, 'opacity': '0.75',
                               'marginLeft': '5px'},
                    ),
                ], style={'display': 'flex', 'alignItems': 'baseline', 'justifyContent': 'flex-end'}),
            ]),
            # Direction
            html.Td(style={**_td, 'textAlign': 'center'},
                    children=[_dir_badge(r.get('direction_correct'))]),
            # Model name
            html.Td(style=_td, children=[
                html.Span(r.get('model_name', '').replace('_', ' '),
                          style={'fontSize': '0.7rem', 'color': 'var(--text-3)'}),
            ]),
        ]))

    table = html.Div(style={'overflowX': 'auto'}, children=[
        html.Table(className='ev-table', children=[
            html.Thead(html.Tr([
                html.Th('Forecast', className='ev-th'),
                html.Th('Trained To', className='ev-th'),
                html.Th('Spot', className='ev-th', style={'textAlign': 'right'}),
                html.Th('Predicted', className='ev-th', style={'textAlign': 'right'}),
                html.Th('Actual', className='ev-th', style={'textAlign': 'right'}),
                html.Th('Error', className='ev-th', style={'textAlign': 'right'}),
                html.Th('Dir.', className='ev-th', style={'textAlign': 'center'}),
                html.Th('Model', className='ev-th'),
            ])),
            html.Tbody(table_rows),
        ]),
    ])

    metrics_pills = html.Div(className='model-info-grid', style={'marginTop': '20px'}, children=[
        _info_pill('Forecasts', str(summary.get('n', 0)),
                   'Number of point-in-time monthly forecasts evaluated against actuals.'),
        _info_pill('MAE', f"R {summary.get('mae', 0):.4f}",
                   'Mean Absolute Error across all forecasts.'),
        _info_pill('RMSE', f"R {summary.get('rmse', 0):.4f}",
                   'Root Mean Squared Error — penalises larger misses more heavily.'),
        _info_pill('MAD', f"R {summary.get('mad', 0):.4f}",
                   'Median Absolute Deviation — robust measure; median of |errors|.'),
        _info_pill('MAPE', f"{summary.get('mape', 0):.2f}%",
                   'Mean Absolute Percentage Error relative to realised ZAR/USD.'),
        _info_pill('Direction Hit Rate', f"{summary.get('hit_rate', 0)*100:.1f}%",
                   'Proportion of forecasts that correctly called ZAR direction.'),
    ])

    note = html.P(
        f"Generated {data.get('generated_at', '')[:10]}. "
        "Each model was independently trained via GridSearchCV on data available at that month-end, "
        "then used for a single one-step-ahead forecast.",
        style={'fontSize': '0.75rem', 'color': 'var(--text-3)', 'marginTop': '16px',
               'lineHeight': '1.5'},
    )

    return html.Div([table, metrics_pills, note])


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
    'EPU(USA)': 'US Economic Policy Uncertainty',
    'WUIZAF(SA)': 'SA World Uncertainty Index',
    '10_YEAR_BOND_RATES(USA)': 'US 10-Year Bond Rate (%)',
    '10_YEAR_BOND_RATES(SA)': 'SA 10-Year Bond Rate (%)',
}

SCENARIO_UNITS = {
    'VIX': '',
    'GOLD_PRICE': 'USD',
    'EPU(USA)': '',
    'WUIZAF(SA)': '',
    '10_YEAR_BOND_RATES(USA)': '%',
    '10_YEAR_BOND_RATES(SA)': '%',
}


@callback(
    Output('scenario-error', 'children', allow_duplicate=True),
    Output('scenario-loading', 'style'),
    Output('scenario-content', 'style'),
    Output('scenario-current-values', 'data'),
    Input('dashboard-tab', 'data'),
    Input('scenario-baseline-data', 'data'),
    State('scenario-current-values', 'data'),
    State('_pages_location', 'pathname'),
    prevent_initial_call='initial_duplicate'
)
def sync_scenario_ui(active_tab, existing_baseline, existing_values, pathname):
    # Outputs only exist on /dashboard. Guard against firing on other pages.
    if pathname != '/dashboard' or active_tab != 'scenario':
        return [dash.no_update] * 4

    if not existing_baseline:
        return '', {'display': 'flex'}, {'display': 'none'}, dash.no_update

    # Only set initial values if none exist yet — don't clobber agent or user slider changes
    if existing_values:
        return '', {'display': 'none'}, {'display': 'block'}, dash.no_update

    current_vals = {p['raw_col']: p['current_value'] for p in existing_baseline.get('predictors', [])}
    return '', {'display': 'none'}, {'display': 'block'}, current_vals


@callback(
    Output('scenario-sliders-container', 'children'),
    Output('scenario-base-value', 'children'),
    Output('scenario-base-change', 'children'),
    Input('scenario-baseline-data', 'data'),
    Input('agent-slider-sync', 'data'),
    State('scenario-current-values', 'data'),
)
def render_scenario_sliders(baseline, _agent_sync, current_values):
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
    State({'type': 'scenario-slider', 'index': dash.ALL}, 'id'),
    State('scenario-baseline-data', 'data'),
    prevent_initial_call=True
)
def update_scenario_values(slider_values, slider_ids, baseline):
    if not baseline or not slider_ids:
        return dash.no_update

    # Start with baseline values
    updated = {p['raw_col']: p['current_value'] for p in baseline.get('predictors', [])}

    # Overwrite with current slider positions, matched by index
    for val, id_dict in zip(slider_values, slider_ids):
        if val is not None:
            updated[id_dict['index']] = val

    return updated


@callback(
    Output({'type': 'scenario-value-display', 'index': dash.ALL}, 'children'),
    Input('scenario-current-values', 'data'),
    State({'type': 'scenario-value-display', 'index': dash.ALL}, 'id'),
    State('scenario-baseline-data', 'data'),
    prevent_initial_call=True
)
def update_value_displays(current_values, display_ids, baseline):
    if not display_ids:
        return []

    if not baseline or not current_values:
        return [dash.no_update] * len(display_ids)

    # Map raw_col to predictor config for easy lookup
    predictors = {p['raw_col']: p for p in baseline.get('predictors', [])}
    display_values = []

    for id_dict in display_ids:
        raw_col = id_dict['index']
        pred = predictors.get(raw_col)

        if not pred:
            display_values.append(dash.no_update)
            continue

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

        try:
            display_values.append(f"{float(val):.{decimals}f} {unit}".strip())
        except (ValueError, TypeError):
            display_values.append(str(val))

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
        labels = [get_friendly_feature_name(w['feature']) for w in active_waterfall]
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
    Input('scenario-reset-btn', 'n_clicks'),
    State('scenario-baseline-data', 'data'),
    prevent_initial_call=True
)
def reset_scenario(n_clicks, baseline):
    if not n_clicks or not baseline:
        return dash.no_update
    return {p['raw_col']: p['current_value'] for p in baseline.get('predictors', [])}


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
            timestamp = datetime.datetime.now().strftime('%H:%M:%S')

            # Monotonically increasing counter survives the max-5 trim. Pulled
            # from the highest 'Scenario N' suffix already in the list.
            existing_nums = []
            for s in (saved_scenarios or []):
                nm = s.get('name', '')
                if nm.startswith('Scenario '):
                    try:
                        existing_nums.append(int(nm.split(' ', 1)[1]))
                    except (ValueError, IndexError):
                        pass
            next_num = (max(existing_nums) + 1) if existing_nums else 1
            scenario_name = f"Scenario {next_num}"

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


