# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commonly Used Commands

-   **Install Dependencies**: `pip install -r requirements.txt`
-   **Run (Development)**: `python app.py` — starts Dash in debug mode on localhost
-   **Run (Production)**: `gunicorn app:server --workers 1 --threads 4 --worker-class gthread --timeout 120` (see `Procfile`)

There are no test files, test framework, or linting configuration in this repository.

## High-Level Architecture

Dash (v4) multi-page web application for ZAR/USD exchange rate forecasting, deployed on Render (512MB RAM constraint).

### Application Flow

1. **`app.py`** — Entry point. Initializes Dash with `use_pages=True`, manages authentication redirects via `user-session` dcc.Store, theme toggling (dark/light), and sequential background callback chaining.
2. **Pages (`pages/`):**
   - `login.py` — Two-stage landing (hero → login form). Authenticates against Supabase `users` table.
   - `registration.py` — User registration to Supabase `users` table.
   - `dashboard.py` (~2,163 lines) — Main authenticated area with three tabs: **Data**, **Model**, and **Scenario**.
3. **Logic (`logic/`):**
   - `supabase_client.py` — Lazy-initialized Supabase client singleton. Uses env vars `SUPABASE_URL` and `SUPABASE_KEY` (with hardcoded fallbacks).
   - `data_fetcher.py` — Fetches macroeconomic data from FRED API, World Bank (gold price Excel scrape), and hardcoded SA inflation. Processes to monthly frequency, saves to Supabase `data` table.
   - `model.py` — ML inference using a frozen HuberRegressor pipeline in `frozen models/zar_usd_forecast_model.pkl`. Feature engineering pipeline (11 features: lag, momentum, mean-reversion, risk/volatility, uncertainty, interest rates, commodities). Scenario analysis with slider-driven what-if predictions.

### Key Architectural Patterns

- **Sequential Background Callback Chaining**: On dashboard load, three background callbacks execute in sequence (Data fetch → Model prediction → Scenario baseline) to avoid memory spikes on Render's 512MB limit. Orchestrated via trigger stores (`fetch-trigger`, `model-prediction-trigger`, `scenario-trigger`).
- **13 Global dcc.Store Components**: Defined in `app.py` for cross-callback state (session, theme, fetched data, predictions, scenario config, UI state).
- **Dual Caching**: In-memory (process-level, 5-min TTL) + DiskCache (`.cache/`, 64–256MB, shared across workers) for Supabase data and model objects.
- **Conditional API Fetch**: `should_update_from_api()` in `data_fetcher.py` returns True only on the last day of the month when Supabase data is stale. Otherwise, data is read directly from Supabase.
- **Clientside Callbacks**: Used for theme sync to DOM, chart resize on tab switch, and tab visibility — no server roundtrip.

### Model Details (HuberRegressor — Error-Correction Framework)

- Frozen model: `frozen models/zar_usd_forecast_model.pkl` (sklearn Pipeline: ColumnTransformer + HuberRegressor)
- Target: ZAR/USD level directly (not log-return). Equation: Ŝ_{t+1} = β₀ + β₁·S_{t-1} + Σ β_j·x̃_j(t)
- Since β₁ ≈ 0.96, the model behaves as a random-walk anchor with small error-correction adjustments
- 11 features: ZAR_USD_lag1 (passthrough/unscaled), ZAR_USD_logret1, ZAR_USD_change3, ZAR_USD_zscore12, VIX, VIX_change1, VIX_zscore12, EPU_USA, WUIZAF_SA, bond_spread_change1, GOLD_PRICE_logret1
- Pipeline: ColumnTransformer (passthrough for lag1 + StandardScaler for remaining 10) → HuberRegressor (α=7.906, ε=1.1)
- SA Inflation, US CPI, Brent Oil deliberately excluded (trending non-stationary series that cause train-test distribution shift)
- Test R²=0.6157, Theil's U=0.9969, Directional Accuracy=67.65%
- Multi-horizon forecasts (1M, 3M, 6M) iterate predictions assuming macro drivers persist

### Dashboard Tab Structure

- **Data Tab**: Normalized (0–100) time series chart of selected predictors vs ZAR/USD. Background fetch with progress bar. Toggleable data table.
- **Model Tab**: Multi-horizon forecast table, feature contribution bar chart, historical fit chart (60-month window), model specification card (HuberRegressor details), performance metrics (MAE, RMSE, R², Theil's U, directional accuracy), diagnostic plots.
- **Scenario Tab**: Slider-driven sensitivity analysis. Comparison cards (base vs scenario), impact waterfall chart, scenario summary table.

### Environment Variables

Required in `.env`:
- `SUPABASE_URL` / `SUPABASE_KEY` — Database connection
- `FRED_API_KEY` — Federal Reserve Economic Data API access