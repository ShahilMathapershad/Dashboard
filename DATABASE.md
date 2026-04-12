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
- `logic/model.py` -- Reads data for feature engineering and model inference. Cached in-memory (5-min TTL) and on disk (DiskCache, 5-min TTL).
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

## Data Access Patterns

### Read Path (Model / Dashboard)

```python
# logic/model.py
supabase.table('data').select('*').order('Date', desc=True).limit(250).execute()
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
users                          data
┌──────────────────┐          ┌──────────────────────┐
│ username (PK)    │          │ Date (PK)            │
│ password         │          │ EPU(USA)             │
└──────────────────┘          │ WUIZAF(SA)           │
                              │ 10_YEAR_BOND_RATES.. │
   (no foreign key            │ VIX                  │
    relationship)             │ GOLD_PRICE           │
                              │ BRENT_OIL_PRICE      │
                              │ US_CPI               │
                              │ SA_INFLATION         │
                              │ ZAR_USD              │
                              └──────────────────────┘
```

The two tables are independent -- there is no foreign key relationship between `users` and `data`. All authenticated users see the same dataset.
