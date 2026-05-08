# Database Documentation

## Overview

The application uses [Supabase](https://supabase.com/) (managed PostgreSQL) as its sole database. The Supabase client is initialized lazily via `logic/supabase_client.py` using the `SUPABASE_URL` and `SUPABASE_KEY` environment variables.

Connection is established on first use (not at import time) to ensure process-safety across gunicorn workers and Dash background callback processes.

## Tables

### `users`

Stores application user accounts for authentication.

| Column | Type | Description |
|--------|------|-------------|
| `username` | text (PK) | Unique username |
| `password` | text | User password (stored as plaintext) |

**Used by:**
- `pages/login.py` -- Authenticates users by matching username + password.
- `pages/registration.py` -- Inserts new users after checking for duplicate usernames.
- `pages/profile.py` -- Validates current password and updates to new password.

**Example row:**
```json
{
  "username": "shahil",
  "password": "mypassword123"
}
```

**Known limitations:**
- Passwords are stored in plaintext (no hashing). This is a security concern for production use -- consider migrating to Supabase Auth or bcrypt hashing.
- No email, role, or created_at columns exist.

---

### `data`

Stores processed monthly macroeconomic time series data. Each row represents one month.

| Column | Type | Description |
|--------|------|-------------|
| `Date` | timestamp | Month-end date (primary key for upserts) |
| `EPU(USA)` | float | Economic Policy Uncertainty Index for USA |
| `WUIZAF(SA)` | float | World Uncertainty Index for South Africa |
| `10_YEAR_BOND_RATES(USA)` | float | 10-Year Treasury Constant Maturity Rate (%) |
| `10_YEAR_BOND_RATES(SA)` | float | 10-Year Bond Rate for South Africa (%) |
| `VIX` | float | CBOE Volatility Index |
| `GOLD_PRICE` | float | World Bank gold price (USD/troy oz) |
| `BRENT_OIL_PRICE` | float | Global Price of Brent Crude (USD/barrel) |
| `US_CPI` | float | Consumer Price Index for All Urban Consumers (USA) |
| `SA_INFLATION` | float | South African Headline CPI Index (Base: Dec 2024=100) |
| `ZAR_USD` | float | ZAR/USD exchange rate |

**Used by:**
- `logic/data_fetcher.py` -- Writes processed data after fetching from APIs. On refresh, the entire table is cleared and rewritten via upsert.
- `logic/model/loading.py` (`fetch_data_from_supabase`) and `logic/data/storage.py` -- Read data for feature engineering and model inference. Cached in-memory (5-min TTL) and on disk via DiskCache (5-min TTL).
- `pages/dashboard.py` -- Reads data for the Data tab charts and tables.

**Data flow:**
```
FRED API + World Bank + StatsSA
  → fetch_fred_data() / fetch_world_bank_gold_data() / fetch_sa_inflation_hardcoded()
  → process_data()  (resample to monthly, forward-fill, clip date range)
  → save_to_supabase()  (delete all → upsert)
  → Supabase 'data' table
```

**Refresh strategy:**
- `should_update_from_api()` returns `True` only on the last day of the month when the latest row in Supabase is from a previous month.
- Gold price can be updated independently via `replace_gold_price_column_in_supabase()` (upserts only the `GOLD_PRICE` column for existing dates).

**Example row:**
```json
{
  "Date": "2025-12-31",
  "EPU(USA)": 156.32,
  "WUIZAF(SA)": 0.124,
  "10_YEAR_BOND_RATES(USA)": 4.25,
  "10_YEAR_BOND_RATES(SA)": 9.87,
  "VIX": 18.45,
  "GOLD_PRICE": 2650.0,
  "BRENT_OIL_PRICE": 72.15,
  "US_CPI": 315.6,
  "SA_INFLATION": 103.8,
  "ZAR_USD": 18.12
}
```

**Date range:** Approximately 15 years of monthly data (limited in `process_data()` for memory efficiency on Render's 512MB constraint).

**Row count:** ~180 rows (15 years x 12 months).

---

### `predictions`

Persistent cache of the dashboard payload (forecasts, contributions, fit history, scenario baseline). Read once per `/dashboard` hydrate so the UI doesn't re-run the model on every page load. Lives across deploys; invalidated atomically by bumping `CACHE_CONTRACT_VERSION` or `MODEL_VERSION`.

| Column | Type | Description |
|--------|------|-------------|
| `model_version` | text (PK) | E.g. `huber-v1-2026-03-29`. Defined in `logic/model/payload.py`. UPSERT key. |
| `cache_contract_version` | int | E.g. `1`. Defined in `logic/cache_contract.py`. Bump to force-invalidate. |
| `computed_at` | timestamptz | When the payload was generated (UTC). Used by `is_stale()` (24h TTL). |
| `data_through` | date | Latest data row included in the payload. |
| `refresh_status` | text | `'success'`, `'stale'`, or `'bootstrap'`. |
| `forecasts` | jsonb | List of `{horizon_months, forecast_zar_usd, forecast_date}` for 1M/3M/6M. |
| `feature_contributions` | jsonb | List of `{feature, contribution, value}` per of 11 features. |
| `fit_history` | jsonb | List of `{date, actual, predicted}` for the trailing 60 months. |
| `scenario_baseline` | jsonb | `{feature_values, baseline_forecast_1m, baseline_date}`. |

**Used by:**
- `logic/predictions_cache/read.py` -- `read_cached()` returns the row matching the active `MODEL_VERSION`. Returns `None` on contract-version mismatch, empty table, or Supabase failure.
- `logic/predictions_cache/write.py` -- `write_payload()` UPSERTs on `model_version` (idempotent across concurrent refreshes).
- `logic/predictions_cache/refresh.py` -- `refresh_async()` orchestrates the FRED + World Bank fetch and writes the new payload. Single-flight via threading.Lock; concurrent calls return `status='skipped'`.
- `logic/predictions_cache/freshness.py` -- `is_stale(metadata)` returns True if older than 24h.
- `core/cache_callbacks.py` -- `hydrate_dashboard` reads on `/dashboard` nav; `opportunistic_refresh` triggers `refresh_async` when stale.

**Bootstrap:** First deploy needs an initial population. Run:
```bash
python -m logic.predictions_cache.bootstrap
```

**Row count:** 1 row per active `model_version` (typically just one).

## Data Access Patterns

### Read Path (Model / Dashboard)

```python
# logic/data/storage.py (and the local rehost in logic/model/loading.py)
supabase.table('data').select('*').order('Date', desc=True).limit(500).execute()
```

Results are cached at two layers:
1. **In-memory dict** (`_supabase_data_cache`) -- 5-minute TTL, per-process.
2. **DiskCache** (`.cache/data/`) -- 5-minute TTL, shared across gunicorn workers and background processes.

### Write Path (Data Fetcher)

```python
# logic/data_fetcher.py
# Step 1: Clear existing data
supabase.table('data').delete().gte('Date', '1900-01-01').execute()

# Step 2: Upsert all rows
supabase.table('data').upsert(filtered_records).execute()
```

The full-table clear + upsert strategy ensures no orphan rows accumulate. This runs at most once per month.

### Auth Path (Login / Registration)

```python
# Login check
supabase.table('users').select("username").eq('username', username).eq('password', password).execute()

# Registration insert
supabase.table('users').insert({"username": username, "password": password}).execute()

# Password update
supabase.table('users').update({'password': new_pw}).eq('username', username).execute()
```

## Entity Relationship

```
users                          data                          predictions
┌──────────────────┐          ┌──────────────────────┐       ┌────────────────────────────┐
│ username (PK)    │          │ Date (PK)            │       │ model_version (PK)         │
│ password         │          │ EPU(USA)             │       │ cache_contract_version     │
└──────────────────┘          │ WUIZAF(SA)           │       │ computed_at                │
                              │ 10_YEAR_BOND_RATES.. │       │ data_through               │
   (no foreign key            │ VIX                  │       │ refresh_status             │
    relationships)            │ GOLD_PRICE           │       │ forecasts (jsonb)          │
                              │ BRENT_OIL_PRICE      │       │ feature_contributions      │
                              │ US_CPI               │       │ fit_history                │
                              │ SA_INFLATION         │       │ scenario_baseline          │
                              │ ZAR_USD              │       └────────────────────────────┘
                              └──────────────────────┘
```

The three tables are independent -- there are no foreign-key relationships. `predictions` is a derived/cached projection of `data` keyed by the active `model_version`; refreshes recompute the payload from `data` and UPSERT.
