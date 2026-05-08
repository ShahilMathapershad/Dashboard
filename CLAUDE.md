# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commonly Used Commands

-   **Install Dependencies**: `pip install -r requirements.txt`
-   **Run (Development)**: `python app.py` — starts Dash in debug mode on `http://localhost:10000`
-   **Run (Production)**: `gunicorn app:server -b 0.0.0.0:10000 --workers 1 --threads 4 --worker-class gthread --timeout 120` (see `Procfile`)
-   **Build Three.js**: `npm run build` — rebuilds `assets/three-scenes.js` from `src/three/*.ts`
-   **Bootstrap predictions cache** (one-off, after deploy or contract bump): `python -m logic.predictions_cache.bootstrap`

There are no test files, test framework, or linting configuration in this repository.

## High-Level Architecture

Dash (v4) multi-page web application for ZAR/USD exchange rate forecasting, deployed on Render (512MB RAM constraint).

### Project Structure

```
app.py                          — Entry point (Dash init, auth, AI chat/agent, global callbacks)
core/
  cache_callbacks.py            — Unified hydrate-from-cache + opportunistic refresh + Get-Started prewarm
pages/                          — Dash page modules (login, registration, dashboard, profile)
logic/
  supabase_client.py            — Lazy Supabase singleton
  session.py                    — HMAC session token make/verify (uses SESSION_SECRET)
  cache_contract.py             — TypedDict contract for the predictions-cache JSON shape
  explainable_registry.py       — Single source of truth for ✦-citable IDs (chat citations + hover-explain)
  data_fetcher.py               — Backwards-compat shim re-exporting from logic/data/
  data/                         — Split data pipeline: fred_source, worldbank_source, static_inputs,
                                  processing, storage (with hard timeouts), freshness
  model/                        — Split ML logic: loading, features, inference, forecasting,
                                  scenario, explain, payload (defines MODEL_VERSION)
  predictions_cache/            — Persistent prediction cache in Supabase: read, write,
                                  freshness, refresh, bootstrap
models/                         — Serialized ML artifacts (.pkl + report PDF)
models/legacy/                  — Point-in-time snapshot pkls + inference_comparison.json
models/model.py                 — Training script (produces production + train-only pkls)
models/train_legacy_snapshots.py — Trains legacy cutoff models for validation
assets/                         — Static files auto-served by Dash (CSS, JS, SVG logos, critical.css)
src/three/                      — Three.js TypeScript source (builds to assets/three-scenes.js)
docs/                           — Project documentation (ARCHITECTURE, API, DATABASE, DEPLOYMENT, CONTRIBUTING)
```

### Application Flow

1. **`app.py`** — Entry point. Initializes Dash with `use_pages=True`, manages authentication redirects via HMAC-verified `user-session` dcc.Store, theme toggling (dark/light), AI chat + agent mode (Gemini 2.5 Flash), and the global layout. Registers `core.cache_callbacks` which owns dashboard hydration.
2. **Pages (`pages/`):**
   - `login.py` — Two-stage landing (hero → login form). Authenticates against Supabase `users` table; on success stores `{username, token}` (HMAC).
   - `registration.py` — User registration to Supabase `users` table.
   - `dashboard.py` — Main authenticated area with three tabs: **Data**, **Model**, and **Scenario**.
   - `profile.py` — User profile and password change.
3. **Logic (`logic/`):**
   - `supabase_client.py` — Lazy-initialized Supabase client singleton. Uses env vars `SUPABASE_URL` and `SUPABASE_KEY`.
   - `session.py` — `make_session_token()` / `verify_session()` — HMAC-SHA256 session tokens to prevent forgery; reads `SESSION_SECRET` (required in production).
   - `data/` — Macroeconomic data pipeline split across modules. `storage.py` wraps every Supabase call in `_with_supabase_timeout` (10s hard timeout). `freshness.should_update_from_api` returns True only on the last day of the month when Supabase is stale (cached 5 min in-process).
   - `model/features.py` — Feature engineering: builds all 11 features. Owns FEATURE_LIST, BASE_FEATURE_NAMES, FEATURE_CATEGORIES, SCENARIO_RAW_PREDICTORS, and `engineer_features()`.
   - `model/inference.py` — Core ML inference using the frozen HuberRegressor pipeline. Loads both production and train-only pkls; MAPE is read from stored OOS metrics.
   - `model/forecasting.py` — `multi_horizon_forecast` (1M/3M/6M iterative).
   - `model/scenario.py` — `predict_scenario`, `compute_scenario_baseline`, `find_scenario_for_target`.
   - `model/explain.py` — `compute_feature_contributions`.
   - `model/loading.py` — `load_model` + the cross-process `_persistent_cache` (32MB DiskCache) used by every other model submodule.
   - `model/payload.py` — `compute_full_predictions_payload` builds the structured `CachePayload` written to the `predictions` table. Defines `MODEL_VERSION = "huber-v1-2026-03-29"`.
   - `predictions_cache/` — Reads/writes the `predictions` Supabase table keyed by `MODEL_VERSION`. `refresh.refresh_async()` is single-flight (threading.Lock) and uses hard timeouts on FRED (20s) and World Bank (25s).
   - `cache_contract.py` — TypedDict shape for the cache. Bumping `CACHE_CONTRACT_VERSION` invalidates all existing cache rows.
   - `explainable_registry.py` — Static + dynamic registry of values the AI can cite (`[[id|value]]` markup) and the user can ✦-explain via hover. Heatmap correlation cells are generated dynamically per-session from the columns in `fetched-data`.
4. **Core (`core/`):**
   - `cache_callbacks.py` — Three callbacks: `hydrate_dashboard` (single-shot read of the predictions cache + Supabase data on `/dashboard` nav, populates 8 stores), `prewarm_on_get_started` (background warm of diskcaches when user clicks landing CTA), `opportunistic_refresh` (background refresh if cache stale > 24h).

### Key Architectural Patterns

- **Cache-First Hydrate (replaces the old sequential trigger chain)**: On dashboard load, a single `hydrate_dashboard` callback reads the `predictions` Supabase table and Supabase `data` table once, then populates all dashboard stores in one pass. If the cache is stale (>24h) or missing, `opportunistic_refresh` rebuilds it in the background without blocking the UI. The legacy `chain_model_prediction` / `chain_scenario_baseline` callbacks have been removed.
- **Get-Started Prewarm**: Clicking "Get Started" on the landing hero fires a background callback that pre-populates the diskcaches behind `fetch_data_from_supabase`, `predict_next_month`, and `get_scenario_baseline`, so the post-login `/dashboard` hydrate is essentially instant.
- **~28 Global dcc.Store Components**: Defined in `app.py` for cross-callback state (session, theme, fetched data, predictions, scenario config, agent mode, explainable registry, cache metadata, prewarm status).
- **Triple-Layer Caching**:
  - In-memory (process-level, 5-min TTL) for Supabase + model results.
  - DiskCache (`.cache/`, 128MB for callback state, 32MB for data) — shared across workers.
  - Supabase `predictions` table — persisted, shared across deploys; keyed by `model_version`, invalidated by `CACHE_CONTRACT_VERSION` bump.
- **Hard Timeouts on External I/O**: Every Supabase call goes through `_with_supabase_timeout` (10s). FRED and World Bank fetches in `refresh_async` have explicit ThreadPoolExecutor timeouts (20s/25s). Prevents a hung upstream from wedging the worker.
- **HMAC Session Tokens**: `user-session` stores `{username, token}` where token is HMAC-SHA256(username) signed with `SESSION_SECRET`. `verify_session` is the auth gate in `auth_redirection`. Production requires `SESSION_SECRET`; dev generates an ephemeral random secret.
- **AI Agent Mode**: Toggle in chat header switches Gemini between "Chat" (Q&A) and "Agent" (returns JSON action plans). `execute_agent_actions` interprets actions like `navigate_tab`, `set_scenario_sliders`, `set_compare_variables`, `highlight_model` and writes them into the dashboard stores; clientside callbacks then animate purple highlights on the affected elements.
- **Explainable-Values Registry + Citation Chips**: `[[id|value]]` markup in Gemini responses is post-processed by `_build_citation_children` into clickable chips that fire `agent-action-store` to navigate + highlight the referenced metric. The registry doubles as the source of truth for the system prompt's "CITATION MARKUP" section.
- **Conditional API Fetch**: `should_update_from_api()` in `logic/data/freshness.py` returns True only on the last day of the month when Supabase data is stale.
- **Clientside Callbacks**: Used for theme sync to DOM, chart resize on tab switch, chat panel toggle, agent mode toggle, agent highlight animations, and chat loading state — no server roundtrip.
- **Asset Optimization**: `assets/critical.css` is inlined into `app.index_string` for first-paint; `three-scenes.js` is excluded from auto-discovery and loaded conditionally by `interactions.js` on desktop only; `flask-compress` adds gzip on all responses; `/assets/*` gets `Cache-Control: public, max-age=3600` (Dash's `?m=<mtime>` busts on change).

### Model Details (HuberRegressor — Error-Correction Framework)

- Production model: `models/zar_usd_forecast_model.pkl` (sklearn Pipeline: ColumnTransformer + HuberRegressor, retrained on data through 2026-04-30)
- Train-only model: `models/zar_usd_forecast_model_train_only.pkl` (same architecture, trained on data ≤ 2023-04-30, used for OOS diagnostic plots and reported MAPE)
- `MODEL_VERSION = "huber-v1-2026-03-29"` (defined in `logic/model/payload.py`) — keys the predictions cache. Bump when retraining changes the artifact.
- Target: ZAR/USD level directly (not log-return). Equation: Ŝ_{t+1} = β₀ + β₁·S_{t-1} + Σ β_j·x̃_j(t)
- Since β₁ ≈ 0.96, the model behaves as a random-walk anchor with small error-correction adjustments
- 11 features: ZAR_USD_lag1 (passthrough/unscaled), ZAR_USD_logret1, ZAR_USD_change3, ZAR_USD_zscore12, VIX, VIX_change1, VIX_zscore12, EPU_USA, WUIZAF_SA, bond_spread_change1, GOLD_PRICE_logret1
- Pipeline: ColumnTransformer (passthrough for lag1 + StandardScaler for remaining 10) → HuberRegressor (α=7.906, ε=1.1)
- SA Inflation, US CPI, Brent Oil deliberately excluded (trending non-stationary series that cause train-test distribution shift)
- Test R²=0.6238, Theil's U=1.0510, Directional Accuracy=64.71%, MAPE=2.18% (OOS test set: May 2023 → Apr 2026)
- Multi-horizon forecasts (1M, 3M, 6M) iterate predictions assuming macro drivers persist
- Legacy snapshot models: `models/legacy/prod_2025_0{1,2,3}.pkl` and `prod_2026_0{1,2,3}.pkl` — models trained at Jan/Feb/Mar 2025 and 2026 cutoffs for point-in-time inference validation. Results in `models/legacy/inference_comparison.json`.
- Spot vs Predicted distinction: ZAR_USD_lag1 uses S_{t-1} (prior month), not the current spot S_t. So the predicted value is anchored to the previous month's rate, not the cutoff spot.

### Dashboard Tab Structure

- **Data Tab**: Normalized (0–100) time series chart of selected predictors vs ZAR/USD. Toggleable data table. Multiple plot modes (time series, 2D/3D compare, correlation heatmap). Heatmap cell clicks fire citation actions that switch into compare mode for the chosen pair.
- **Model Tab**: Multi-horizon forecast table, feature contribution bar chart, historical fit chart (60-month window), model specification card, performance metrics, diagnostic plots, and Live Forecast Inference card (Jan/Feb/Mar 2026 snapshots vs actuals). Two sub-tabs: **predictions** and **specifications**.
- **Scenario Tab**: Slider-driven sensitivity analysis. Comparison cards (base vs scenario), impact waterfall chart, scenario summary table. Save/compare multiple snapshots. Agent mode can drive the sliders directly via `set_scenario_sliders` actions.

### Environment Variables

Required in `.env` (see `.env.example`):
- `SUPABASE_URL` / `SUPABASE_KEY` — Database connection
- `FRED_API_KEY` — Federal Reserve Economic Data API access
- `GOOGLE_API_KEY` — Google Gemini API (AI chat assistant)
- `SESSION_SECRET` — HMAC session-token secret. **Required in production** (Render or `FLASK_ENV=production`); dev generates an ephemeral key per process.
