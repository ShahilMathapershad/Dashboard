2# Architecture

## Tech Stack

### Backend (Python)

- **Dash v4** -- Multi-page web framework (built on Flask + Plotly). Manages routing, callbacks, and server-side state.
- **Flask** -- Underlying WSGI server exposed as `app.server` for gunicorn.
- **gunicorn** -- Production WSGI server with gthread worker class (1 worker, 4 threads) to stay within 512MB RAM on Render.
- **Supabase (Python SDK)** -- PostgreSQL database for persistent storage of user accounts and macroeconomic data.
- **scikit-learn** -- HuberRegressor pipeline for ZAR/USD forecasting. Frozen model loaded from `.pkl` artifact.
- **pandas / numpy / scipy / statsmodels** -- Data manipulation, feature engineering, and statistical computations.
- **fredapi** -- Python wrapper for the Federal Reserve Economic Data (FRED) API.
- **google-genai** -- Google Gemini SDK for the AI chat assistant.
- **diskcache** -- File-based cache (`.cache/`) for background callback state and data persistence across processes.
- **joblib** -- Model serialization/deserialization.

### Frontend

- **Plotly.js v6** -- Interactive charts (time series, bar charts, scatter plots, waterfall, heatmaps).
- **Dash Bootstrap Components** -- Layout grid and UI components.
- **Three.js** -- 3D WebGL scenes on the landing page (particle globe, flowing mesh). Written in TypeScript, bundled with esbuild.
- **Custom CSS** -- `assets/style.css` (~3,500 lines) handling dark/light themes, glassmorphism cards, animations, and responsive layout.
- **Custom JS** -- `assets/interactions.js` for Plotly resize handling, scroll animations, and sidebar toggling.

## Folder Structure

```
Dash/
├── app.py                         # Application entry point
├── pages/                         # Dash page modules (auto-registered)
│   ├── login.py                   #   / route -- landing + login
│   ├── registration.py            #   /registration route
│   ├── dashboard.py               #   /dashboard route
│   └── profile.py                 #   /profile route
├── logic/                         # Business logic (no UI code)
│   ├── supabase_client.py         #   Database connection singleton
│   ├── data_fetcher.py            #   Data pipeline (FRED, World Bank, StatsSA)
│   └── model.py                   #   ML inference + scenario analysis
├── models/                        # Serialized ML artifacts
│   ├── zar_usd_forecast_model.pkl #   sklearn Pipeline (ColumnTransformer + HuberRegressor)
│   └── ZAR_USD_Model_Report.pdf   #   Model documentation
├── assets/                        # Static files (auto-served by Dash)
│   ├── style.css                  #   Global styles (dark/light theme)
│   ├── interactions.js            #   Client-side JavaScript
│   ├── three-scenes.js            #   Bundled Three.js (from src/three/)
│   └── logo*.svg                  #   Light/dark logo variants
├── src/three/                     # Three.js TypeScript source
└── docs/                          # Project documentation
```

## Application Flow

### Startup Sequence

1. `app.py` loads environment variables and initializes the Dash app with `use_pages=True`.
2. DiskCache is configured at `.cache/` (128MB limit) for background callback state.
3. Flask server is created and wrapped by Dash.
4. 20 `dcc.Store` components are defined in the root layout for cross-callback state.
5. Clientside callbacks register for theme detection and chart resize events.
6. Page modules (`pages/*.py`) are auto-discovered and registered by Dash.

### Authentication Flow

```
User visits /
  ├── Not logged in → Show landing page (hero) → "Get Started" → Login form
  │     ├── Valid credentials → Set user-session store → Redirect to /dashboard
  │     └── Invalid → Show error message
  └── Already logged in (session exists) → Redirect to /dashboard

User visits /dashboard without session → Redirect to /
User visits /profile without session → Redirect to /
```

The `auth_redirection` callback in `app.py` acts as a global navigation guard, checking `user-session` on every page navigation.

### Data Pipeline Flow

```
Dashboard loads → fetch-trigger fires
  ├── should_update_from_api() checks:
  │     ├── Is today the last day of the month?
  │     └── Does Supabase already have this month's data?
  │
  ├── If stale: Fetch from FRED API + World Bank + StatsSA → process → save to Supabase
  └── If fresh: Read directly from Supabase
  
  → Data stored in fetched-data dcc.Store
  → Triggers model-prediction-trigger (sequential chain)
  → Triggers scenario-trigger (sequential chain)
```

### Sequential Background Callback Chaining

To avoid memory spikes on Render's 512MB limit, three background callbacks execute in strict sequence:

1. **Data Fetch** (`fetch-trigger` → `fetched-data`) -- Fetches macroeconomic data from APIs or Supabase.
2. **Model Prediction** (`model-prediction-trigger` → `model-prediction-data`) -- Runs the HuberRegressor pipeline to generate forecasts.
3. **Scenario Baseline** (`scenario-trigger` → `scenario-baseline-data`) -- Computes slider ranges and base prediction for the scenario tab.

Each step writes to a `dcc.Store`, and the next step's trigger callback fires only when the previous store is populated. This is orchestrated in `app.py` via the `chain_model_prediction` and `chain_scenario_baseline` callbacks.

## Caching Architecture

### Dual-Layer Cache

| Layer | Implementation | TTL | Scope |
|-------|---------------|-----|-------|
| In-memory | Python dict (`_model_cache`, `_supabase_data_cache`, etc.) | 5 min | Per-process |
| DiskCache | `diskcache.Cache("./.cache/data")` (32MB) | 5 min | Cross-process |
| Background callbacks | `diskcache.Cache("./.cache")` (128MB) | Session | Cross-process |

The in-memory cache is checked first. On miss, the disk cache is checked. On miss, the actual data source (Supabase, model file) is read and both caches are populated.

### Conditional API Fetch

`should_update_from_api()` in `data_fetcher.py` returns `True` only when:
1. Today is the last day of the month, AND
2. Supabase doesn't already have data for the current month.

This prevents unnecessary API calls (FRED has rate limits) and keeps the data refresh predictable.

## Global State (dcc.Store Components)

The app uses 20 `dcc.Store` components defined in `app.py` for cross-callback state:

| Store ID | Storage Type | Purpose |
|----------|-------------|---------|
| `user-session` | session | Authenticated user info (`{username: ...}`) |
| `theme-store` | local | Current theme (dark/light) |
| `dashboard-tab` | session | Active dashboard tab (data/model/scenario) |
| `sidebar-state` | local | Sidebar collapsed/expanded |
| `fetched-data` | session | Processed macroeconomic DataFrame (JSON) |
| `model-prediction-data` | session | Model prediction results |
| `fetch-trigger` | session | Triggers data fetch background callback |
| `model-prediction-trigger` | session | Triggers model prediction callback |
| `scenario-trigger` | session | Triggers scenario baseline callback |
| `predictor-dropdown-options-store` | session | Dropdown options for predictor selection |
| `selected-predictors` | session | Currently selected predictors on chart |
| `fetched-data-status` | session | Data fetch status message |
| `scenario-baseline-data` | session | Scenario baseline (slider config + base prediction) |
| `scenario-current-values` | session | Current scenario slider values |
| `saved-scenarios` | session | User-saved scenario snapshots |
| `chat-history` | session | AI chat conversation history |
| `plot-mode` | session | Current plot mode (timeseries/compare/correlation) |
| `selected-compare-vars` | session | Variables selected in compare mode |
| `force-refresh-trigger` | memory | Force data re-fetch |
| `table-view-mode` | session | Data table view mode (raw/normalized) |

## Model Architecture (HuberRegressor)

### Error-Correction Framework

The model predicts the ZAR/USD level directly (not log-returns):

```
S_hat(t+1) = B0 + B1 * S(t-1) + sum(Bj * x_tilde_j(t))
```

Where `B1 ~ 0.96` (the lag coefficient) makes the model a random-walk anchor with small error-correction adjustments from 10 macro signals.

### 11 Features

| # | Feature | Source | Transform | Category |
|---|---------|--------|-----------|----------|
| 1 | `ZAR_USD_lag1` | ZAR/USD | S(t-1) passthrough | Anchor |
| 2 | `ZAR_USD_logret1` | ZAR/USD | ln(S_t / S_{t-1}) | Momentum |
| 3 | `ZAR_USD_change3` | ZAR/USD | S_t - S_{t-3} | 3M trend |
| 4 | `ZAR_USD_zscore12` | ZAR/USD | z-score of S_{t-1} over 12mo | Mean-reversion |
| 5 | `VIX` | FRED | Level | Risk level |
| 6 | `VIX_change1` | FRED | VIX_t - VIX_{t-1} | Risk direction |
| 7 | `VIX_zscore12` | FRED | z-score of VIX_{t-1} over 12mo | Stress regime |
| 8 | `EPU_USA` | FRED | Level | Policy uncertainty |
| 9 | `WUIZAF_SA` | FRED | Level | SA uncertainty |
| 10 | `bond_spread_change1` | FRED | delta(SA_10Y - US_10Y) | Carry trade |
| 11 | `GOLD_PRICE_logret1` | World Bank | ln(G_t / G_{t-1}) | Commodity signal |

### Pipeline Structure

```
ColumnTransformer:
  ├── passthrough: ZAR_USD_lag1 (unscaled)
  └── StandardScaler: remaining 10 features
→ HuberRegressor(alpha=7.906, epsilon=1.1)
```

### Deliberately Excluded Variables

SA Inflation, US CPI, and Brent Oil are excluded because they are trending non-stationary series that cause train-test distribution shift.

### Performance Metrics (Out-of-Sample)

| Metric | Value |
|--------|-------|
| MAE | Stored in model artifact |
| RMSE | Stored in model artifact |
| R² | 0.6157 |
| Theil's U | 0.9969 |
| Directional Accuracy | 67.65% |
| Training Observations | 134 |
| Test Observations | 34 |

## Dashboard Tabs

### Data Tab

- Normalized (0-100) time series chart of selected predictors vs ZAR/USD
- Three plot modes: Time Series, Compare (2D/3D), Correlation Heatmap
- Background data fetch with progress bar
- Toggleable raw/normalized data table

### Model Tab

- Multi-horizon forecast table (1M, 3M, 6M) with point estimates and fair values
- Feature contribution bar chart (sorted by absolute impact)
- Historical fit chart (60-month window, actual vs predicted)
- Model specification card (HuberRegressor parameters)
- Performance metrics (MAE, RMSE, R², Theil's U, directional accuracy, MAPE)
- Diagnostic plots (actual vs predicted scatter, partial residual plots)

### Scenario Tab

- Slider-driven sensitivity analysis for 6 adjustable predictors
- Base vs scenario comparison cards
- Impact waterfall chart showing per-feature ZAR contribution deltas
- Scenario summary table
- Save/compare multiple scenario snapshots

## Clientside Callbacks

Several callbacks run entirely in the browser (no server roundtrip):

- **Theme sync** -- Detects system color scheme, applies `light-theme` class to DOM.
- **Chart resize** -- Dispatches `plotlyResize` events when tab visibility changes.
- **Chat panel** -- Toggle open/close, auto-scroll on new messages, typewriter animation.
- **Loading state** -- Instant optimistic UI for chat (shows user message + typing dots before server responds).
