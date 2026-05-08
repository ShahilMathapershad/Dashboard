# ZAR/USD Exchange Rate Forecasting Dashboard

A data-driven forecasting tool built for South African agribusiness to navigate ZAR/USD exchange rate volatility with clarity. The dashboard combines macroeconomic data from multiple sources with a robust HuberRegressor machine learning model to provide transparent, explainable exchange rate forecasts.

## Features

- **Macroeconomic Data Exploration** -- Interactive time series charts of 10+ macroeconomic variables (VIX, gold price, bond rates, policy uncertainty, inflation, and more) normalized for visual comparison. Supports time series, 2D/3D comparison, and correlation heatmap plot modes.
- **ML-Powered Forecasting** -- HuberRegressor error-correction model predicting ZAR/USD levels at 1-month, 3-month, and 6-month horizons. Includes fair value estimation, feature contribution analysis, and historical fit visualization.
- **Scenario Analysis** -- Slider-driven what-if analysis allowing users to adjust VIX, US/SA policy uncertainty, gold price, and bond rates to see how the ZAR/USD would respond. Waterfall charts show per-feature impact.
- **AI Chat Assistant + Agent Mode** -- Embedded chatbot (powered by Gemini 2.5 Flash) with full context of dashboard state. Toggle into Agent Mode and the assistant can navigate tabs, drive scenario sliders, and highlight model metrics on your behalf. Inline citation chips on numbers (`[[id|value]]`) jump straight to the source on the page.
- **Explainable Values (✦)** -- Hover any forecast, metric, or feature contribution to ask the assistant about it with one click.
- **Dark/Light Theme** -- Automatic system theme detection with manual override.
- **3D Visualizations** -- Three.js-powered particle globe and flowing mesh on the landing page.
- **User Authentication** -- Supabase-backed login/registration with HMAC-signed session tokens and password change.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Framework | [Dash](https://dash.plotly.com/) v4 (Plotly) |
| UI Components | Dash Bootstrap Components, custom CSS |
| Charts | Plotly.js v6 |
| 3D Rendering | Three.js (TypeScript, bundled with esbuild) |
| ML Model | scikit-learn HuberRegressor (frozen pipeline) |
| Database | [Supabase](https://supabase.com/) (PostgreSQL) |
| Data Sources | FRED API, World Bank, Statistics South Africa |
| AI Chatbot | Google Gemini 2.5 Flash |
| Deployment | Render (gunicorn, 512MB RAM) |
| Language | Python 3.12+ / TypeScript |

## Quick Start

### Prerequisites

- Python 3.12 or later
- Node.js 18+ (only needed to rebuild Three.js assets)
- A `.env` file with required API keys (see [`.env.example`](.env.example))

### Installation

```bash
# Clone the repository
git clone <repository-url>
cd Dash

# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate  # macOS/Linux
# .venv\Scripts\activate   # Windows

# Install Python dependencies
pip install -r requirements.txt
```

### Running Locally

```bash
python app.py
```

The app will be available at `http://localhost:10000`.

### Production

```bash
gunicorn app:server -b 0.0.0.0:10000 --workers 1 --threads 4 --worker-class gthread --timeout 120
```

See [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) for full deployment instructions.

## Project Structure

```
Dash/
├── app.py                    # Entry point -- Dash app init, auth, chat/agent, global callbacks
├── Procfile                  # Render process definition
├── requirements.txt          # Python dependencies
├── package.json              # Node.js deps (Three.js build)
├── tsconfig.json             # TypeScript configuration
├── .env.example              # Environment variable template
│
├── core/
│   └── cache_callbacks.py    # Unified hydrate + Get-Started prewarm + opportunistic refresh
│
├── pages/                    # Dash multi-page modules
│   ├── login.py              # Landing page + login form
│   ├── registration.py       # User registration
│   ├── dashboard.py          # Main dashboard (Data/Model/Scenario tabs)
│   └── profile.py            # User profile + password change
│
├── logic/                    # Backend logic
│   ├── supabase_client.py    # Lazy-initialized Supabase singleton
│   ├── session.py            # HMAC session token make/verify
│   ├── cache_contract.py     # TypedDict contract for the predictions cache payload
│   ├── explainable_registry.py # ✦ + chat-citation registry (single source of truth)
│   ├── data_fetcher.py       # Backwards-compat shim → logic/data
│   ├── data/                 # Split data pipeline
│   │   ├── fred_source.py    #   FRED API
│   │   ├── worldbank_source.py #   World Bank gold price scraper
│   │   ├── static_inputs.py  #   Hardcoded SA inflation
│   │   ├── processing.py     #   Monthly resample, merge, clip
│   │   ├── storage.py        #   Supabase R/W with hard timeouts
│   │   └── freshness.py      #   should_update_from_api()
│   ├── model/                # Split ML logic
│   │   ├── loading.py        #   Model loader + shared diskcache
│   │   ├── features.py       #   11 feature engineering
│   │   ├── inference.py      #   predict_next_month, test-set predictions
│   │   ├── forecasting.py    #   multi_horizon_forecast (1M/3M/6M)
│   │   ├── scenario.py       #   Scenario baseline + slider-driven prediction
│   │   ├── explain.py        #   Feature contributions
│   │   └── payload.py        #   compute_full_predictions_payload + MODEL_VERSION
│   └── predictions_cache/    # Persistent prediction cache (Supabase 'predictions' table)
│       ├── read.py
│       ├── write.py
│       ├── refresh.py        #   Single-flight async refresh with hard timeouts
│       ├── freshness.py      #   24-hour staleness check
│       └── bootstrap.py      #   `python -m logic.predictions_cache.bootstrap`
│
├── models/                   # Serialized ML artifacts
│   ├── zar_usd_forecast_model.pkl          # Production model (through 2026-04-30)
│   ├── zar_usd_forecast_model_train_only.pkl # Train-only model (cutoff 2023-04-30)
│   ├── model.py                            # Training script
│   ├── train_legacy_snapshots.py           # Legacy snapshot trainer
│   ├── legacy/                             # Point-in-time snapshot pkls (2025_0{1,2,3} + 2026_0{1,2,3}) + inference_comparison.json
│   └── ZAR_USD_Model_Report.pdf
│
├── assets/                   # Static assets (auto-served by Dash)
│   ├── style.css             # Global stylesheet
│   ├── critical.css          # Inlined into <head> for fast first paint
│   ├── interactions.js       # Client-side JS (resize, animations, conditional Three.js loader)
│   ├── three-scenes.js       # Bundled Three.js scenes (built from src/, desktop-only)
│   └── logo*.svg             # Light/dark logo variants
│
├── src/three/                # Three.js TypeScript source
│   ├── index.ts
│   ├── LandingScene.ts       # Particle globe + flowing mesh
│   ├── CardDepth.ts          # Card parallax effects
│   ├── ChartTilt.ts          # Chart tilt interactions
│   └── noise.ts              # Noise generation utilities
│
└── docs/                     # Project documentation
    ├── ARCHITECTURE.md       # Tech stack, design patterns
    ├── API.md                # External API integrations + callback inventory
    ├── DATABASE.md           # Database schema
    ├── DEPLOYMENT.md         # Render deployment guide
    └── CONTRIBUTING.md       # Code style and conventions
```

## Data Sources

| Source | Variables | Frequency |
|--------|----------|-----------|
| [FRED API](https://fred.stlouisfed.org/) | ZAR/USD, VIX, EPU(USA), WUIZAF(SA), 10Y Bond Rates (US/SA), US CPI, Brent Oil | Monthly |
| [World Bank](https://www.worldbank.org/en/research/commodity-markets) | Gold Price (CMO Historical Data) | Monthly |
| Statistics South Africa | SA Headline CPI Index (hardcoded through Feb 2026) | Monthly |

Data is refreshed from APIs only on the last day of each month when Supabase data is stale. Otherwise, all reads come directly from the Supabase cache.

## Model Overview

The frozen HuberRegressor pipeline uses an error-correction framework:

**Equation:** `S_hat(t+1) = B0 + B1 * S(t-1) + sum(Bj * x_j(t))`

With `B1 ~ 0.96`, the model behaves as a random-walk anchor with small corrections from 10 macro signals. Multi-horizon forecasts (1M, 3M, 6M) iterate predictions forward assuming macro drivers persist.

**Performance (out-of-sample test set, May 2023 → Apr 2026):**
- Test R² = 0.6238, Adjusted R² = 0.4357
- Theil's U = 1.051, Directional Accuracy = 64.71%
- MAE = 0.39, RMSE = 0.53, MAPE = 2.18%

A train-only model (cutoff 2023-04-30) is kept alongside the production model so that all reported OOS metrics and diagnostic plots are genuinely out-of-sample. Legacy snapshot models trained at Jan/Feb/Mar 2026 cutoffs provide additional point-in-time forecast validation.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for detailed model documentation.

## Documentation

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) -- Tech stack, folder structure, and design patterns
- [`docs/DATABASE.md`](docs/DATABASE.md) -- Database schema and table documentation
- [`docs/API.md`](docs/API.md) -- External API integrations and data flow
- [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) -- Deployment instructions for Render
- [`docs/CONTRIBUTING.md`](docs/CONTRIBUTING.md) -- Code style guide and contribution conventions

## License

Private. Authorized access for economicsweekly.co.za stakeholders.
