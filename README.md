# ZAR/USD Exchange Rate Forecasting Dashboard

A data-driven forecasting tool built for South African agribusiness to navigate ZAR/USD exchange rate volatility with clarity. The dashboard combines macroeconomic data from multiple sources with a robust HuberRegressor machine learning model to provide transparent, explainable exchange rate forecasts.

## Features

- **Macroeconomic Data Exploration** -- Interactive time series charts of 10+ macroeconomic variables (VIX, gold price, bond rates, policy uncertainty, inflation, and more) normalized for visual comparison. Supports time series, 2D/3D comparison, and correlation heatmap plot modes.
- **ML-Powered Forecasting** -- HuberRegressor error-correction model predicting ZAR/USD levels at 1-month, 3-month, and 6-month horizons. Includes fair value estimation, feature contribution analysis, and historical fit visualization.
- **Scenario Analysis** -- Slider-driven what-if analysis allowing users to adjust VIX, US/SA policy uncertainty, gold price, and bond rates to see how the ZAR/USD would respond. Waterfall charts show per-feature impact.
- **AI Chat Assistant** -- Embedded chatbot (powered by Gemini 2.5 Flash) with full context of dashboard state for answering economics and forecast questions.
- **Dark/Light Theme** -- Automatic system theme detection with manual override.
- **3D Visualizations** -- Three.js-powered particle globe and flowing mesh on the landing page.
- **User Authentication** -- Supabase-backed login/registration with session management and password change.

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
# Development mode (with hot reload)
python app.py

# Or use the convenience runner (auto-opens browser)
python run/run.py
```

The app will be available at `http://localhost:10000` (app.py) or `http://localhost:8050` (run.py).

### Production

```bash
gunicorn app:server -b 0.0.0.0:10000 --workers 1 --threads 4 --worker-class gthread --timeout 120 --preload
```

See [`DEPLOYMENT.md`](DEPLOYMENT.md) for full deployment instructions.

## Project Structure

```
Dash/
├── app.py                    # Entry point -- Dash app init, auth, chat, callbacks
├── Procfile                  # Render/Heroku process definition
├── requirements.txt          # Python dependencies
├── package.json              # Node.js deps (Three.js build)
├── tsconfig.json             # TypeScript configuration
├── .env.example              # Environment variable template
│
├── pages/                    # Dash multi-page modules
│   ├── login.py              # Landing page + login form
│   ├── registration.py       # User registration
│   ├── dashboard.py          # Main dashboard (Data/Model/Scenario tabs)
│   └── profile.py            # User profile + password change
│
├── logic/                    # Backend logic
│   ├── supabase_client.py    # Lazy-initialized Supabase singleton
│   ├── data_fetcher.py       # FRED/World Bank/StatsSA data pipeline
│   └── model.py              # ML inference, feature engineering, scenarios
│
├── frozen models/            # Serialized ML artifacts
│   ├── zar_usd_forecast_model.pkl
│   └── ZAR_USD_Model_Report.pdf
│
├── assets/                   # Static assets (auto-served by Dash)
│   ├── style.css             # Global stylesheet (~3,500 lines)
│   ├── interactions.js       # Client-side JS (resize, animations)
│   ├── three-scenes.js       # Bundled Three.js scenes
│   ├── logo.svg / logo_light.svg / logo_dark.svg
│   └── background.png / data.png / model.png
│
├── src/three/                # Three.js TypeScript source
│   ├── index.ts
│   ├── LandingScene.ts       # Particle globe + flowing mesh
│   ├── CardDepth.ts          # Card parallax effects
│   ├── ChartTilt.ts          # Chart tilt interactions
│   └── noise.ts              # Noise generation utilities
│
├── run/
│   └── run.py                # Development runner (auto-opens browser)
│
├── data/
│   └── zar_usd_hist.csv      # Historical data placeholder
│
└── .cache/                   # DiskCache directory (runtime)
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

**Performance (out-of-sample test set):**
- Test R² = 0.6157
- Theil's U = 0.9969
- Directional Accuracy = 67.65%

See [`ARCHITECTURE.md`](ARCHITECTURE.md) for detailed model documentation.

## Documentation

- [`ARCHITECTURE.md`](ARCHITECTURE.md) -- Tech stack, folder structure, and design patterns
- [`DATABASE.md`](DATABASE.md) -- Database schema and table documentation
- [`API.md`](API.md) -- External API integrations and data flow
- [`DEPLOYMENT.md`](DEPLOYMENT.md) -- Deployment instructions for Render
- [`CONTRIBUTING.md`](CONTRIBUTING.md) -- Code style guide and contribution conventions

## License

Private. Authorized access for economicsweekly.co.za stakeholders.
