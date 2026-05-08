# Architecture

## Tech Stack

### Backend (Python)

- **Dash v4** -- Multi-page web framework (built on Flask + Plotly). Manages routing, callbacks, and server-side state.
- **Flask** -- Underlying WSGI server exposed as `app.server` for gunicorn. `flask-compress` adds gzip on all responses.
- **gunicorn** -- Production WSGI server with gthread worker class (1 worker, 4 threads) to stay within 512MB RAM on Render.
- **Supabase (Python SDK)** -- PostgreSQL database for users, macro data, and the predictions cache.
- **scikit-learn** -- HuberRegressor pipeline for ZAR/USD forecasting. Frozen model loaded from `.pkl` artifact.
- **pandas / numpy / scipy / statsmodels** -- Data manipulation, feature engineering, and statistical computations.
- **fredapi** -- Python wrapper for the Federal Reserve Economic Data (FRED) API.
- **google-genai** -- Google Gemini SDK for the AI chat assistant + Agent Mode.
- **diskcache** -- File-based cache (`.cache/`) for background callback state and cross-process result caching.
- **joblib** -- Model serialization/deserialization.

### Frontend

- **Plotly.js v6** -- Interactive charts (time series, bar charts, scatter plots, waterfall, heatmaps).
- **Dash Bootstrap Components** -- Layout grid and UI components.
- **Three.js** -- 3D WebGL scenes on the landing page (particle globe, flowing mesh). Written in TypeScript, bundled with esbuild. Loaded conditionally on desktop only.
- **Custom CSS** -- `assets/style.css` (~3,500 lines) for dark/light themes, glassmorphism cards, animations, responsive layout. `assets/critical.css` is inlined into `<head>` for fast first paint.
- **Custom JS** -- `assets/interactions.js` for Plotly resize, scroll animations, sidebar toggle, and conditional Three.js loading.

## Folder Structure

```
Dash/
├── app.py                            # Application entry point
├── core/
│   └── cache_callbacks.py            # Unified hydrate + prewarm + opportunistic refresh
├── pages/                            # Dash page modules (auto-registered)
│   ├── login.py                      #   / route -- landing + login
│   ├── registration.py               #   /registration route
│   ├── dashboard.py                  #   /dashboard route
│   └── profile.py                    #   /profile route
├── logic/                            # Business logic (no UI code)
│   ├── supabase_client.py            #   Database connection singleton
│   ├── session.py                    #   HMAC session token make/verify
│   ├── cache_contract.py             #   TypedDict contract for the predictions cache
│   ├── explainable_registry.py       #   Static + dynamic registry of citable values
│   ├── data_fetcher.py               #   Backwards-compat shim → logic/data
│   ├── data/                         #   Data pipeline split into submodules
│   │   ├── fred_source.py            #     FRED API
│   │   ├── worldbank_source.py       #     World Bank gold scraper
│   │   ├── static_inputs.py          #     Hardcoded SA inflation
│   │   ├── processing.py             #     Resample, merge, clip
│   │   ├── storage.py                #     Supabase R/W with hard timeouts
│   │   └── freshness.py              #     should_update_from_api()
│   ├── model/                        #   ML inference + scenario analysis
│   │   ├── loading.py                #     load_model + shared diskcache
│   │   ├── features.py               #     11 feature engineering
│   │   ├── inference.py              #     predict_next_month, test-set predictions
│   │   ├── forecasting.py            #     multi_horizon_forecast
│   │   ├── scenario.py               #     Scenario baseline + slider prediction
│   │   ├── explain.py                #     compute_feature_contributions
│   │   └── payload.py                #     compute_full_predictions_payload + MODEL_VERSION
│   └── predictions_cache/            #   Persistent prediction cache
│       ├── read.py
│       ├── write.py
│       ├── refresh.py                #     Single-flight refresh w/ hard timeouts
│       ├── freshness.py              #     24-hour staleness check
│       └── bootstrap.py              #     One-shot eager populate
├── models/                           # Serialized ML artifacts
│   ├── zar_usd_forecast_model.pkl                # Production model (through 2026-04-30)
│   ├── zar_usd_forecast_model_train_only.pkl     # Train-only model (cutoff 2023-04-30)
│   ├── model.py                                  # Training script
│   ├── train_legacy_snapshots.py                 # Point-in-time snapshot training
│   ├── legacy/                                   # 2025_0{1,2,3} + 2026_0{1,2,3} pkls + inference_comparison.json
│   └── ZAR_USD_Model_Report.pdf
├── assets/                           # Static files (auto-served by Dash)
│   ├── style.css                     # Global styles (dark/light theme)
│   ├── critical.css                  # Inlined critical CSS for first paint
│   ├── interactions.js               # Client-side JavaScript
│   ├── three-scenes.js               # Bundled Three.js (from src/three/)
│   └── logo*.svg                     # Light/dark logo variants
├── src/three/                        # Three.js TypeScript source
└── docs/                             # Project documentation
```

## Application Flow

### Startup Sequence

1. `app.py` loads environment variables and initializes the Dash app with `use_pages=True`.
2. DiskCache is configured at `.cache/` (128MB limit) for background callback state.
3. `flask-compress` is applied for gzip on all responses.
4. `assets/critical.css` is inlined into `app.index_string`; `three-scenes.js` and `critical.css` are excluded from auto-discovery via `assets_ignore`.
5. Cache-Control middleware adds `public, max-age=3600` to `/assets/*` responses.
6. ~28 `dcc.Store` components are defined in the root layout for cross-callback state.
7. `core.cache_callbacks.register(app)` wires the unified hydrate, prewarm, and opportunistic-refresh callbacks.
8. Page modules (`pages/*.py`) are auto-discovered and registered by Dash.

### Authentication Flow

```
User visits /
  ├── Not logged in → Show landing page (hero) → "Get Started"
  │     ├── Click triggers prewarm_on_get_started (background) — warms diskcaches
  │     │   for fetch_data_from_supabase, predict_next_month, get_scenario_baseline
  │     ├── Login form
  │     │   ├── Valid credentials → store {username, token} in user-session (HMAC) → /dashboard
  │     │   └── Invalid → Show error message
  └── Already logged in (verify_session passes) → Redirect to /dashboard

User visits /dashboard or /profile without verified session → Redirect to /
```

The `auth_redirection` callback in `app.py` is the global navigation guard. It calls `logic.session.verify_session` — the user-session store must contain `{username, token}` where `token` is HMAC-SHA256 of the username signed by `SESSION_SECRET`. Tokens cannot be forged client-side.

### Dashboard Hydrate Flow (Cache-First)

The legacy three-step trigger chain (`fetch-trigger → model-prediction-trigger → scenario-trigger`) has been replaced by a single `hydrate_dashboard` callback in `core/cache_callbacks.py`.

```
User navigates to /dashboard
  ├── hydrate_dashboard fires (one shot)
  │     ├── Read predictions cache from Supabase (logic.predictions_cache.read_cached)
  │     │     - Empty / contract mismatch / Supabase down → cache_status='miss'
  │     │     - Hit → cache_status='hit', payload[metadata, forecasts, ...]
  │     ├── fetch_data_from_supabase() (in-memory + diskcache, both 5-min TTL)
  │     ├── predict_next_month() (uses the cached pipeline)
  │     ├── get_scenario_baseline()
  │     └── Writes 8 stores in one pass:
  │           fetched-data, fetched-data-status, predictor-dropdown-options-store,
  │           selected-predictors, model-prediction-data, scenario-baseline-data,
  │           cache-metadata-store, cache-status-store
  │
  └── If cache_status ∈ {'miss', 'stale (>24h)'}, opportunistic_refresh fires
        ├── refresh_async() (single-flight via threading.Lock)
        │     ├── Parallel fetch_fred_data + fetch_world_bank_gold_data with hard
        │     │   timeouts (FRED 20s, WB 25s)
        │     ├── process_to_monthly + save_to_supabase
        │     ├── compute_full_predictions_payload → write_payload
        │     └── Returns RefreshResult{status, reason, payload, elapsed_ms}
        └── On success, writes new cache_metadata + flips cache_status='hit'
```

### Get-Started Prewarm

Clicking "Get Started" on the landing hero fires a background callback that calls `fetch_data_from_supabase()`, `predict_next_month()`, and `get_scenario_baseline()` in succession. Each is individually diskcached, so by the time the user finishes filling the login form (~3-5s), every dependency the post-login hydrate needs is hot. Failure is silently swallowed — hydrate retries from cold if needed.

## Caching Architecture

### Triple-Layer Cache

| Layer | Implementation | TTL | Scope | Used For |
|-------|---------------|-----|-------|----------|
| In-memory | Python dicts (`_model_cache`, `_supabase_data_cache`, `_should_update_cache`) | 5 min | Per-process | Hot path — first-line lookup |
| DiskCache | `diskcache.Cache("./.cache/data")` (32MB) | 5 min | Cross-process (workers) | Cross-worker / cross-process result sharing |
| Background callbacks | `diskcache.Cache("./.cache")` (128MB) | Session | Cross-process | Dash background callback state |
| Supabase `predictions` table | UPSERT keyed by `model_version` | 24h staleness | Cross-deploy | Persistent precomputed payload |

The in-memory cache is checked first. On miss, the disk cache is checked. On miss, the actual data source (Supabase, model file) is read and both caches are populated.

The `predictions` table caches the *output* of the entire pipeline so the dashboard can hydrate without re-running the model on every page load. `CACHE_CONTRACT_VERSION` (in `logic/cache_contract.py`) lets a deploy invalidate the cache atomically — bumping the version means existing rows are treated as misses.

### Hard Timeouts

Every external I/O call has a hard timeout to prevent a hung upstream from wedging the worker:

| Call site | Timeout | Mechanism |
|-----------|---------|-----------|
| Supabase reads/writes | 10s | `_with_supabase_timeout` (ThreadPoolExecutor) in `logic/data/storage.py` |
| FRED fetch in refresh | 20s | `concurrent.futures.TimeoutError` in `logic/predictions_cache/refresh.py` |
| World Bank scrape in refresh | 25s | Same |

### Conditional API Fetch (Monthly Refresh)

`should_update_from_api()` in `logic/data/freshness.py` returns `True` only when:
1. Today is the last day of the month, AND
2. Supabase doesn't already have data for the current month.

The result is cached in-process for 5 minutes — without this, every dashboard fetch_data invocation would pay a ~100–300ms Supabase round-trip just to learn that the answer is "no, use cached data".

## Global State (dcc.Store Components)

The app uses ~28 `dcc.Store` components defined in `app.py` for cross-callback state:

| Store ID | Storage Type | Purpose |
|----------|-------------|---------|
| `user-session` | session | Authenticated user info + HMAC token (`{username, token}`) |
| `theme-store` | local | Current theme (dark/light) |
| `dashboard-tab` | session | Active dashboard tab (data/model/scenario) |
| `model-sub-tab` | session | Active model sub-tab (predictions/specifications) |
| `sidebar-state` | local | Sidebar collapsed/expanded |
| `fetched-data` | session | Processed macroeconomic DataFrame (records) |
| `fetched-data-status` | session | Status pill text + color |
| `model-prediction-data` | session | Model prediction results |
| `scenario-baseline-data` | session | Slider config + base prediction |
| `scenario-current-values` | session | Current scenario slider values |
| `saved-scenarios` | session | User-saved scenario snapshots |
| `predictor-dropdown-options-store` | session | Dropdown options |
| `selected-predictors` | session | Predictors on time-series chart |
| `plot-mode` | session | Current plot mode (timeseries/compare/correlation) |
| `selected-compare-vars` | session | Variables in compare mode |
| `table-view-mode` | session | Data table view (raw/normalized) |
| `chat-history` | session | AI chat conversation history |
| `agent-mode-store` | session | Chat (false) vs Agent (true) toggle |
| `agent-action-store` | memory | Last batch of actions emitted by Gemini |
| `agent-slider-sync` | memory | Counter that triggers slider-UI re-render |
| `agent-highlight-store` | memory | Targets to flash purple after an agent action |
| `explainable-registry-store` | memory | Per-session ✦/citation registry (static + dynamic heatmap entries) |
| `cache-metadata-store` | session | Predictions cache metadata (`computed_at`, `data_through`, …) |
| `cache-status-store` | session | `'hit' \| 'miss' \| 'refreshing' \| 'stale'` |
| `prewarm-status-store` | memory | `'idle'` → `'warm'` after Get-Started prewarm |
| `force-refresh-trigger` | memory | Manual data re-fetch button |
| `fetch-trigger`, `model-prediction-trigger`, `scenario-trigger` | session | Legacy stubs, retained for back-compat — no longer drive the chain |

## AI Chat + Agent Mode

The chat panel is global (available on every page). A toggle in the header switches between two Gemini personas:

| Mode | System prompt | Behavior |
|------|---------------|----------|
| Chat | `CHAT_SYSTEM_PROMPT` | Plain Q&A about the dashboard / economics. May embed `[[id\|value]]` citation chips. |
| Agent | `AGENT_SYSTEM_PROMPT` | Returns JSON action plans (`navigate_tab`, `set_scenario_sliders`, `set_compare_variables`, `highlight_model`, `select_predictors`, `set_plot_mode`, `reset_scenario`). The reply text is rendered to the user; the actions are executed. |

### Citation Chips

Every numerical reference Gemini wraps in `[[id|value]]` is parsed by `_build_citation_children` (in `app.py`) into a clickable chip. Clicking the chip writes to `agent-action-store`, which `execute_agent_actions` uses to navigate to the relevant tab and highlight the source DOM node. The list of citable IDs is generated programmatically by `logic/explainable_registry.build_system_prompt_snippet` and appended to both system prompts so Gemini knows what's available.

### Explainable Values Registry

`logic/explainable_registry.py` is the single source of truth for:
- The static set of forecast/metric IDs (1-month / 3-month / 6-month forecasts, fair value, MAE / RMSE / R² / MAPE / Theil's U / directional accuracy, 11 feature contributions, scenario base/result/delta).
- Dynamic correlation-heatmap cell IDs (`corr_<A>_<B>`) generated per-session from the columns in `fetched-data`.

`populate_explainable_registry` (in `app.py`) writes the merged static + dynamic registry to `explainable-registry-store` whenever fetched data updates, so the browser-side ✦ buttons and chip clicks can resolve any ID without round-tripping the server.

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

### Performance Metrics (Out-of-Sample, test set: May 2023 → Apr 2026)

| Metric | Value |
|--------|-------|
| MAE | 0.3899 |
| RMSE | 0.5283 |
| R² | 0.6238 |
| Adjusted R² | 0.4357 |
| Theil's U | 1.0510 |
| Directional Accuracy | 64.71% |
| MAPE | 2.18% |
| Training Observations | 132 |
| Test Observations | 35 |

### Model Artifacts

| File | Description |
|------|-------------|
| `models/zar_usd_forecast_model.pkl` | Production model — refitted on all data through 2026-04-30 |
| `models/zar_usd_forecast_model_train_only.pkl` | Train-only model — cutoff 2023-04-30, test set held out for OOS diagnostics and MAPE reporting |
| `models/legacy/prod_2025_0{1,2,3}.pkl` | Point-in-time snapshot models trained at Jan/Feb/Mar 2025 cutoffs |
| `models/legacy/prod_2026_0{1,2,3}.pkl` | Point-in-time snapshot models trained at Jan/Feb/Mar 2026 cutoffs |
| `models/legacy/inference_comparison.json` | Predicted vs actual comparison for the legacy snapshots |

The string `MODEL_VERSION = "huber-v1-2026-03-29"` (in `logic/model/payload.py`) keys the predictions cache. Bump it when retraining changes the artifact so existing cache rows are atomically invalidated for that key.

### Spot vs Predicted Distinction

The passthrough feature `ZAR_USD_lag1` is S_{t-1} (the prior month's rate), not the current spot S_t. This means the predicted value is anchored to the *previous* month's rate. Even with β₁ ≈ 0.96, spot and predicted can diverge meaningfully when the last two months moved sharply in opposite directions.

## Dashboard Tabs

### Data Tab

- Normalized (0-100) time series chart of selected predictors vs ZAR/USD
- Three plot modes: Time Series, Compare (2D/3D), Correlation Heatmap
- Heatmap cell clicks emit citation actions (set compare mode + variables for the chosen pair)
- Toggleable raw/normalized data table with CSV download

### Model Tab

Two sub-tabs (`model-sub-tab` store):

**Predictions sub-tab:**
- Multi-horizon forecast table (1M, 3M, 6M) with point estimates and fair values
- Feature contribution bar chart (sorted by absolute impact)
- Historical fit chart (60-month window, actual vs predicted)
- Live Forecast Inference card: point-in-time predicted vs actual table for legacy 2026 snapshots, with error / direction hit-miss / summary metrics

**Specifications sub-tab:**
- Model specification card (HuberRegressor parameters)
- Performance metrics (MAE, RMSE, R², Theil's U, directional accuracy, MAPE — all OOS from train-only model)
- Diagnostic plots (actual vs predicted scatter, partial residual plots — use train-only model on held-out test period to avoid in-sample contamination)

### Scenario Tab

- Slider-driven sensitivity analysis for 6 adjustable predictors
- Base vs scenario comparison cards
- Impact waterfall chart showing per-feature ZAR contribution deltas
- Scenario summary table
- Save/compare multiple scenario snapshots
- Agent Mode can drive sliders directly via `set_scenario_sliders` actions; affected sliders flash purple

## Clientside Callbacks

Several callbacks run entirely in the browser (no server roundtrip):

- **Theme sync** -- Detects system color scheme, applies `light-theme` class to DOM.
- **Chart resize** -- Dispatches `plotlyResize` events when tab visibility changes.
- **Chat panel** -- Toggle open/close, auto-scroll on new messages, typewriter animation.
- **Loading state** -- Instant optimistic UI for chat (shows user message + typing dots before server responds).
- **Agent mode toggle** -- Updates header title, input placeholder, and panel class.
- **Agent highlight animations** -- Adds `agent-highlight` class to targeted DOM nodes for 4s with fade-out.
- **Plot-mode UI sync** -- When agent changes `plot-mode` directly, re-applies button-active classes and visibility of compare/predictor checkboxes.
