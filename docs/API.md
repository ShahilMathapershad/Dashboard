# API Documentation

This application does not expose a REST API. It is a server-rendered Dash application where all data flows through Dash callbacks (server-side Python functions triggered by UI events). This document covers the **external APIs consumed** by the application and the **internal callback endpoints** that power the dashboard.

## External APIs

### 1. FRED API (Federal Reserve Economic Data)

**Library:** `fredapi` (Python)
**Base URL:** `https://api.stlouisfed.org/`
**Authentication:** API key via `FRED_API_KEY` environment variable
**Rate Limit:** 120 requests per minute (the app adds 0.5s delay between calls)

**Series fetched:**

| App Name | FRED Series ID | Description |
|----------|---------------|-------------|
| `ZAR_USD` | `DEXSFUS` | South African Rand / US Dollar exchange rate |
| `VIX` | `VIXCLS` | CBOE Volatility Index |
| `EPU(USA)` | `USEPUINDXM` | Economic Policy Uncertainty Index for USA |
| `WUIZAF(SA)` | `WUIZAF` | World Uncertainty Index for South Africa |
| `10_YEAR_BOND_RATES(USA)` | `GS10` | 10-Year Treasury Constant Maturity Rate |
| `10_YEAR_BOND_RATES(SA)` | `IRLTLT01ZAM156N` | 10-Year Bond Rate (South Africa) |
| `USA_CPI` | `CPALTT01USM659N` | CPI for All Items (USA, FRED variant) |
| `SA_CPI_FRED` | `CPALTT01ZAM659N` | CPI for All Items (SA, FRED variant) |
| `US_CPI` | `CPIAUCSL` | Consumer Price Index for All Urban Consumers |
| `BRENT_OIL_PRICE` | `POILBREUSDM` | Global Price of Brent Crude |

**Usage in code:**
```python
# logic/data/fred_source.py  (re-exported from logic/data_fetcher for back-compat)
from fredapi import Fred
fred = Fred(api_key=FRED_API_KEY)
series = fred.get_series(series_id, observation_start='2009-12-31')
```

**Response format:** pandas Series indexed by date, values as floats.

**Example call flow:**
```
fetch_fred_data()
  → For each series in SERIES_CONFIG where source == 'FRED':
      fred.get_series(series_id, observation_start='2009-12-31')
      sleep(0.5)  # rate limit
  → Concatenate all series into a DataFrame
  → Return combined DataFrame
```

---

### 2. World Bank Commodity Markets

**Method:** HTTP GET + Excel file parsing
**Page URL:** `https://www.worldbank.org/en/research/commodity-markets`
**Data URL:** Dynamically scraped from the page (links to `CMO-Historical-Data-Monthly.xlsx`)

**Data extracted:** Gold price from the "Monthly Prices" sheet.

**Usage in code:**
```python
# logic/data/worldbank_source.py
def _get_world_bank_gold_excel_url():
    """Scrape the commodity markets page for the latest workbook URL."""
    response = requests.get("https://www.worldbank.org/en/research/commodity-markets")
    # Regex search for CMO-Historical-Data-Monthly.xlsx link
    match = re.search(r'href=["\']([^"\']*CMO-Historical-Data-Monthly\.xlsx...)', html_content)
    return match.group(1)

def fetch_world_bank_gold_data(start_date='2009-12-31'):
    url = _get_world_bank_gold_excel_url()
    df = pd.read_excel(url, sheet_name="Monthly Prices", header=4)
    # Extract 'Gold' column, parse dates (YYYY-M format), convert to monthly
    return monthly_gold_series
```

**Response format:** Excel workbook. The "Monthly Prices" sheet has dates in `YYYYM##` format and commodity prices in labeled columns.

---

### 3. Statistics South Africa (Hardcoded)

**Method:** No API call -- data is hardcoded in `logic/data/static_inputs.py`.

The SA Headline CPI Index (Base: Dec 2024 = 100) is maintained as a Python list of monthly values from December 2009 through February 2026. Values for 2025-2026 are derived from official StatsSA year-over-year percentage changes applied to the 2024 base index.

```python
# logic/data/static_inputs.py
def fetch_sa_inflation_hardcoded():
    cpi_values = [48.0, 48.1, ...]  # ~195 monthly values
    dates = pd.date_range(start="2009-12-31", end="2026-02-28", freq="ME")
    return pd.DataFrame({'SA_INFLATION': cpi_values}, index=dates)
```

**Update procedure:** Manually update the `cpi_values` list and extend the date range when new StatsSA data is published.

---

### 4. Google Gemini API

**Library:** `google-genai` (Python SDK)
**Model:** `gemini-2.5-flash`
**Authentication:** API key via `GOOGLE_API_KEY` environment variable

**Usage:** Powers the global AI chat assistant + Agent Mode embedded in the dashboard. Each chat message sends the full conversation history plus a system prompt containing the current dashboard state (data, predictions, scenario values) and the citation-markup catalog generated from `logic.explainable_registry.build_system_prompt_snippet`.

The header toggle picks one of two system prompts:
- `CHAT_SYSTEM_PROMPT` — plain Q&A; replies may include `[[id|value]]` citation chips that get post-processed into clickable React elements by `_build_citation_children`.
- `AGENT_SYSTEM_PROMPT` — the model returns a JSON action plan (`navigate_tab`, `set_scenario_sliders`, `set_compare_variables`, `highlight_model`, `select_predictors`, `set_plot_mode`, `reset_scenario`) plus a natural-language reply. Actions are dispatched via `agent-action-store` and executed by `execute_agent_actions`.

```python
# app.py
from google import genai
from google.genai import types

client = genai.Client(api_key=GOOGLE_API_KEY)
response = client.models.generate_content(
    model='gemini-2.5-flash',
    contents=contents,  # Conversation history
    config=types.GenerateContentConfig(
        system_instruction=system_instruction,  # Dashboard context
        max_output_tokens=2048,
        temperature=0.7,
    )
)
```

**Context injected:** The `_build_chat_context()` function assembles a text summary including:
- Active tab and plot mode
- All variable summary statistics (latest, min, max, mean, MoM%, YoY%)
- Correlations with ZAR/USD
- Model predictions (point estimate, fair value, multi-horizon forecasts)
- Feature contributions
- Model performance metrics
- Scenario baseline values

---

### 5. Supabase

**Library:** `supabase` (Python SDK)
**Authentication:** Service key via `SUPABASE_URL` and `SUPABASE_KEY` environment variables

See [DATABASE.md](./DATABASE.md) for full table documentation and query patterns.

## Internal Callback Architecture

Dash callbacks are the internal "endpoints" of the application. They are Python functions triggered by UI component changes (button clicks, dropdown selections, store updates).

### Key Server-Side Callbacks

| Callback | Triggers | Outputs | Location |
|----------|----------|---------|----------|
| `hydrate_dashboard` | Page navigation to `/dashboard`, session change | 8 stores: `fetched-data`, `fetched-data-status`, `predictor-dropdown-options-store`, `selected-predictors`, `model-prediction-data`, `scenario-baseline-data`, `cache-metadata-store`, `cache-status-store` | `core/cache_callbacks.py` |
| `prewarm_on_get_started` | "Get Started" button click on landing | `prewarm-status-store` (background; warms diskcaches) | `core/cache_callbacks.py` |
| `opportunistic_refresh` | `cache-status-store` change | Background refresh of `predictions` table; flips status `'stale' → 'hit'` | `core/cache_callbacks.py` |
| `auth_redirection` | Page navigation, session change | Pathname redirect (verifies HMAC token) | `app.py` |
| `clear_data_on_logout` | `user-session` cleared | Wipes chat history + saved scenarios | `app.py` |
| `populate_explainable_registry` | `fetched-data` change | `explainable-registry-store` (static + heatmap-cell entries) | `app.py` |
| `execute_agent_actions` | `agent-action-store` change | Tab, slider values, predictors, plot mode, compare vars, pathname, highlight | `app.py` |
| `handle_chat_send` | Chat send button, input submit | `chat-messages`, `chat-history`, optional `agent-action-store` | `app.py` |
| `login_auth` | Login button click | `user-session` (`{username, token}` HMAC), error message | `pages/login.py` |
| `register_user` | Register button click | Success/error message | `pages/registration.py` |
| `update_password` | Update password button | Success/error message | `pages/profile.py` |
| `run_scenario_prediction` | Scenario slider changes | Scenario results | `pages/dashboard.py` |

> **Removed:** `global_prerender_trigger`, `chain_model_prediction`, `chain_scenario_baseline`, `fetch_data_background`, `run_model_prediction`, `compute_scenario_baseline` — the old three-step trigger chain was retired in favour of the unified cache-first hydrate. The `fetch-trigger` / `model-prediction-trigger` / `scenario-trigger` stores are still in the layout as no-op stubs for back-compat with browsers cached on the previous build.

### Background Callbacks

Two callbacks now use Dash's `background=True` with DiskCache to run in separate processes:

1. **`prewarm_on_get_started`** -- Fired when the landing-page "Get Started" button is clicked. Calls `fetch_data_from_supabase()`, `predict_next_month()`, and `get_scenario_baseline()` to populate diskcaches in advance of post-login hydrate.
2. **`opportunistic_refresh`** -- Fired by changes to `cache-status-store`. If the cache is missing or stale (>24h), triggers `refresh_async()` (single-flight via threading.Lock) which re-fetches FRED + World Bank with hard timeouts, recomputes the payload, and UPSERTs the `predictions` row.

### Clientside Callbacks (No Server Roundtrip)

| Purpose | Input | Output | Location |
|---------|-------|--------|----------|
| Theme detection | `theme-store` | DOM class | `app.py` |
| Chart resize (model) | `model-results-container` style | Plotly resize event | `app.py` |
| Chart resize (data) | `visualization-container` style | Plotly resize event | `app.py` |
| Figure change resize | `model-history-chart` figure | Plotly resize event | `app.py` |
| Chat toggle | Chat toggle/close buttons | Panel visibility | `app.py` |
| Chat auto-scroll | `chat-messages` children | Scroll position, typewriter | `app.py` |
| Chat loading state | Send button, input submit | Optimistic UI elements | `app.py` |
