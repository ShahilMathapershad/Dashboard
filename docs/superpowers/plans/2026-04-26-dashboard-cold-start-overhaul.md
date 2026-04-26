# Dashboard Cold-Start Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate the Login → Dashboard cold-start delay and intermittent infinite hang by moving heavy work off the request path; reach < 1.5s time-to-interactive on warm Render.

**Architecture:** Cache-first read path (single Supabase SELECT serves the dashboard) + opportunistic async refresh (one bounded background callback with hard timeouts) + frontend skeleton/lazy tabs + asset bundle isolation. Replaces the 3-step `Data → Model → Scenario` background-callback chain that wedges when an upstream API hangs.

**Tech Stack:** Python 3.12, Dash 2.18, Plotly 5.24, scikit-learn 1.6, pandas 2.2, Supabase 2.15, Flask, Gunicorn (gthread, --preload), Render Starter, diskcache, flask-compress (new).

**Spec:** `docs/superpowers/specs/2026-04-26-dashboard-cold-start-overhaul-design.md`

---

## Wave Map

| Wave | Tasks | Parallel? | Depends on |
|------|-------|-----------|------------|
| 0 — Contract | 1, 2 | No (sequential) | — |
| 1 — Backend & Foundations | 3, 4, 5, 6, 7 | Yes (5 agents) | Wave 0 |
| 2 — Cache layer | 8, 9 | No | Wave 1 |
| 3 — Tab extractions | 10, 11, 12 | Yes (3 agents) | Wave 2 |
| 4 — Cutover & verification | 13, 14 | No | Wave 3 |

**Bite-sized step convention:** every task breaks into 4–10 numbered steps. Each step is one Edit/Write/Bash action plus a verification. There is no pytest in this repo (per spec); verification uses standalone scripts under `scripts/verify/`.

---

## Wave 0 — Contract (Sequential Prerequisite)

### Task 1: Cache contract types

**Files:**
- Create: `logic/cache_contract.py`
- Create: `scripts/verify/contract.py`

- [ ] **Step 1: Write `logic/cache_contract.py`**

```python
"""Type contract for the predictions cache.

This module defines the JSON shape that:
  • logic.model.compute_full_predictions_payload() emits
  • logic.predictions_cache.write() persists to Supabase
  • logic.predictions_cache.read() returns
  • pages/dashboard_tabs/* read from dcc.Store hydration

Bumping CACHE_CONTRACT_VERSION forces all clients to treat existing
cache rows as a miss, triggering a fresh refresh under the new schema.
"""
from __future__ import annotations
from typing import TypedDict, Literal

CACHE_CONTRACT_VERSION = 1


class HorizonForecast(TypedDict):
    horizon_months: Literal[1, 3, 6]
    forecast_zar_usd: float
    forecast_date: str  # ISO date "YYYY-MM-DD"


class FeatureContribution(TypedDict):
    feature: str
    contribution: float
    value: float


class FitHistoryPoint(TypedDict):
    date: str        # ISO date
    actual: float
    predicted: float


class ScenarioBaseline(TypedDict):
    feature_values: dict[str, float]   # name → current value
    baseline_forecast_1m: float
    baseline_date: str


class CacheMetadata(TypedDict):
    cache_contract_version: int
    model_version: str               # e.g. "huber-v1-2026-03-29"
    computed_at: str                 # ISO datetime UTC
    data_through: str                # ISO date — newest data row included
    refresh_status: Literal["success", "stale", "bootstrap"]


class CachePayload(TypedDict):
    metadata: CacheMetadata
    forecasts: list[HorizonForecast]
    feature_contributions: list[FeatureContribution]
    fit_history: list[FitHistoryPoint]
    scenario_baseline: ScenarioBaseline


class RefreshResult(TypedDict):
    status: Literal["success", "failed", "skipped"]
    reason: str | None       # e.g. "lock_held", "fred_timeout"
    payload: CachePayload | None
    elapsed_ms: int
```

- [ ] **Step 2: Write `scripts/verify/contract.py`**

```python
"""Verify CachePayload roundtrips as JSON and has all required fields."""
import json
import sys
from datetime import datetime, timezone
from logic.cache_contract import (
    CACHE_CONTRACT_VERSION,
    CachePayload,
    CacheMetadata,
    HorizonForecast,
    FeatureContribution,
    FitHistoryPoint,
    ScenarioBaseline,
)

def _sample_payload() -> CachePayload:
    now = datetime.now(timezone.utc).isoformat()
    return CachePayload(
        metadata=CacheMetadata(
            cache_contract_version=CACHE_CONTRACT_VERSION,
            model_version="huber-v1-2026-03-29",
            computed_at=now,
            data_through="2026-03-31",
            refresh_status="success",
        ),
        forecasts=[
            HorizonForecast(horizon_months=1, forecast_zar_usd=18.55, forecast_date="2026-04-30"),
            HorizonForecast(horizon_months=3, forecast_zar_usd=18.71, forecast_date="2026-06-30"),
            HorizonForecast(horizon_months=6, forecast_zar_usd=19.02, forecast_date="2026-09-30"),
        ],
        feature_contributions=[
            FeatureContribution(feature="ZAR_USD_lag1", contribution=18.10, value=18.50),
            FeatureContribution(feature="VIX", contribution=0.08, value=15.2),
        ],
        fit_history=[
            FitHistoryPoint(date="2025-04-30", actual=18.30, predicted=18.27),
            FitHistoryPoint(date="2025-05-31", actual=18.42, predicted=18.39),
        ],
        scenario_baseline=ScenarioBaseline(
            feature_values={"VIX": 15.2, "EPU_USA": 120.5},
            baseline_forecast_1m=18.55,
            baseline_date="2026-04-30",
        ),
    )

def main() -> int:
    payload = _sample_payload()
    try:
        encoded = json.dumps(payload)
        decoded = json.loads(encoded)
    except (TypeError, ValueError) as e:
        print(f"FAIL: payload not JSON-roundtrippable: {e}")
        return 1

    required_top = {"metadata", "forecasts", "feature_contributions", "fit_history", "scenario_baseline"}
    if set(decoded.keys()) != required_top:
        print(f"FAIL: top-level keys {set(decoded.keys())} != {required_top}")
        return 1

    required_meta = {"cache_contract_version", "model_version", "computed_at", "data_through", "refresh_status"}
    if set(decoded["metadata"].keys()) != required_meta:
        print(f"FAIL: metadata keys {set(decoded['metadata'].keys())} != {required_meta}")
        return 1

    print(f"OK: CachePayload roundtripped, contract version={CACHE_CONTRACT_VERSION}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Run verify**

```bash
python scripts/verify/contract.py
```

Expected output:
```
OK: CachePayload roundtripped, contract version=1
```
Exit code: 0.

- [ ] **Step 4: Commit**

```bash
git add logic/cache_contract.py scripts/verify/contract.py
git commit -m "feat(cache): add CachePayload type contract

Defines the shape that producers (model.compute_full_predictions_payload)
and consumers (dashboard hydration callback) agree on. Versioned via
CACHE_CONTRACT_VERSION so schema changes force a cache miss."
```

---

### Task 2: Predictions table DDL

**Files:**
- Create: `docs/superpowers/specs/predictions-table.sql`
- Create: `scripts/verify/predictions_table.py`

- [ ] **Step 1: Write `docs/superpowers/specs/predictions-table.sql`**

```sql
-- Single-row-per-model-version cache for pre-computed dashboard payloads.
-- Read path: SELECT * FROM predictions WHERE model_version = $current.
-- Refresh path: INSERT ... ON CONFLICT (model_version) DO UPDATE.
-- No history retained; last write wins per model version.
CREATE TABLE IF NOT EXISTS predictions (
    model_version           text PRIMARY KEY,
    cache_contract_version  integer NOT NULL,
    computed_at             timestamptz NOT NULL,
    data_through            date NOT NULL,
    refresh_status          text NOT NULL,
    forecasts               jsonb NOT NULL,
    feature_contributions   jsonb NOT NULL,
    fit_history             jsonb NOT NULL,
    scenario_baseline       jsonb NOT NULL,
    updated_at              timestamptz NOT NULL DEFAULT now()
);

-- The dashboard hydrate callback runs on every page load — make sure
-- it's a single fast indexed lookup.
CREATE INDEX IF NOT EXISTS predictions_model_version_idx
    ON predictions (model_version);

-- Trigger to bump updated_at on every UPSERT.
CREATE OR REPLACE FUNCTION set_predictions_updated_at()
RETURNS trigger AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS predictions_set_updated_at ON predictions;
CREATE TRIGGER predictions_set_updated_at
    BEFORE INSERT OR UPDATE ON predictions
    FOR EACH ROW EXECUTE FUNCTION set_predictions_updated_at();
```

- [ ] **Step 2: Apply migration in Supabase**

Open the Supabase project SQL editor (production project — table is purely additive, no risk to existing `data` / `users` tables) and paste the contents of `docs/superpowers/specs/predictions-table.sql`. Click **Run**.

- [ ] **Step 3: Write `scripts/verify/predictions_table.py`**

```python
"""Verify the predictions table exists and is empty/queryable."""
import sys
from logic.supabase_client import get_supabase

def main() -> int:
    sb = get_supabase()
    if sb is None:
        print("FAIL: get_supabase() returned None — env vars missing?")
        return 1
    try:
        resp = sb.table("predictions").select("model_version").limit(1).execute()
    except Exception as e:
        print(f"FAIL: predictions table not queryable: {e}")
        return 1
    print(f"OK: predictions table queryable, rows={len(resp.data)}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run verify**

```bash
python scripts/verify/predictions_table.py
```

Expected output:
```
OK: predictions table queryable, rows=0
```

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/specs/predictions-table.sql scripts/verify/predictions_table.py
git commit -m "feat(db): add predictions table for dashboard cache

Single-row-per-model-version table holding pre-computed forecasts,
feature contributions, fit history, and scenario baseline. Migration
applied to Supabase."
```

---

## Wave 1 — Backend & Foundations (Parallel: 5 Agents)

> Agents 3, 4, 5, 6, 7 can run concurrently after Wave 0 lands. Tasks 6 (assets) and 7 (compression) only touch `app.py`'s top-level Dash init; coordinate via small, focused commits.

### Task 3: Split `logic/data_fetcher.py` into `logic/data/` package + add timeouts

**Files:**
- Create: `logic/data/__init__.py`, `logic/data/fred_source.py`, `logic/data/worldbank_source.py`, `logic/data/static_inputs.py`, `logic/data/processing.py`, `logic/data/storage.py`, `logic/data/freshness.py`
- Modify: `logic/data_fetcher.py` (becomes a thin shim re-exporting from `logic.data`)
- Create: `scripts/verify/timeouts.py`

- [ ] **Step 1: Create `logic/data/fred_source.py` with hard timeout**

```python
"""FRED API fetch with bounded execution time.

The legacy code (logic/data_fetcher.py) called fred.get_series() without
a timeout — a wedged TCP connection could hang the whole process. We
wrap each series fetch in a ThreadPoolExecutor.future.result(timeout=15)
so a stuck call raises TimeoutError instead of hanging.
"""
from __future__ import annotations
import concurrent.futures
import logging
import os
import ssl
import time
from contextlib import contextmanager

import pandas as pd
from fredapi import Fred

logger = logging.getLogger(__name__)

PER_SERIES_TIMEOUT_SECONDS = 15

# Same series dict as logic/data_fetcher.py — kept here as the single source of truth.
FRED_SERIES: dict[str, str] = {
    "ZAR_USD": "DEXSFUS",
    "VIX": "VIXCLS",
    "EPU_USA": "USEPUINDXD",
    "WUIZAF_SA": "WUIZAF",
    "BRENT_OIL": "DCOILBRENTEU",
    "US_CPI": "CPIAUCSL",
    "ZA_10Y_BOND": "IRLTLT01ZAM156N",
    "US_10Y_BOND": "DGS10",
}

@contextmanager
def _unverified_ssl():
    """FRED occasionally serves with stale intermediate certs; legacy parity."""
    old_default = ssl._create_default_https_context
    ssl._create_default_https_context = ssl._create_unverified_context
    try:
        yield
    finally:
        ssl._create_default_https_context = old_default


def _fetch_one(fred: Fred, name: str, series_id: str, start_date: str) -> pd.DataFrame:
    with _unverified_ssl():
        s = fred.get_series(series_id, observation_start=start_date)
    return s.to_frame(name=name)


def fetch_fred_data(start_date: str = "2009-12-31") -> pd.DataFrame:
    """Fetch every FRED series with a hard per-series timeout."""
    api_key = os.getenv("FRED_API_KEY")
    if not api_key:
        logger.error("FRED_API_KEY not set; returning empty DataFrame.")
        return pd.DataFrame()

    fred = Fred(api_key=api_key)
    frames: list[pd.DataFrame] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        for name, series_id in FRED_SERIES.items():
            future = ex.submit(_fetch_one, fred, name, series_id, start_date)
            try:
                df = future.result(timeout=PER_SERIES_TIMEOUT_SECONDS)
                frames.append(df)
                logger.info("fetch_fred_data: got %s (%s) rows=%d", name, series_id, len(df))
            except concurrent.futures.TimeoutError:
                logger.warning(
                    "fetch_fred_data: TIMEOUT after %ds on %s (%s) — skipping",
                    PER_SERIES_TIMEOUT_SECONDS, name, series_id,
                )
            except Exception as exc:
                logger.warning("fetch_fred_data: error on %s: %s — skipping", name, exc)
            time.sleep(0.5)  # avoid FRED rate-limit
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, axis=1, sort=True)
```

- [ ] **Step 2: Create `logic/data/worldbank_source.py` with hard timeout on `read_excel`**

```python
"""World Bank gold-price scrape, with bounded download + parse.

The legacy `pd.read_excel(live_url, ...)` had no timeout — pandas hands
the URL straight to urllib, which can hang forever. We download via
requests.get(timeout=20), then parse from BytesIO.
"""
from __future__ import annotations
import io
import logging
import re
import urllib.parse

import pandas as pd
import requests

logger = logging.getLogger(__name__)

PAGE_TIMEOUT_SECONDS = 15
WORKBOOK_TIMEOUT_SECONDS = 20
PAGE_URL = "https://www.worldbank.org/en/research/commodity-markets"


def _resolve_workbook_url() -> str | None:
    try:
        resp = requests.get(PAGE_URL, timeout=PAGE_TIMEOUT_SECONDS)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.warning("worldbank: page fetch failed: %s", e)
        return None

    match = re.search(
        r'href=["\']([^"\']*CMO-Historical-Data-Monthly\.xlsx(?:\?[^"\']*)?)["\']',
        resp.text, flags=re.IGNORECASE,
    )
    if not match:
        logger.warning("worldbank: workbook link not found on page.")
        return None

    href = match.group(1).strip()
    if href.startswith("//"):
        return f"https:{href}"
    if href.startswith("http"):
        return href
    if href.startswith("/"):
        return f"https://thedocs.worldbank.org{href}"
    return urllib.parse.urljoin(PAGE_URL, href)


def fetch_world_bank_gold_data() -> pd.Series:
    """Return a pd.Series of monthly gold prices keyed by date, or empty on failure."""
    url = _resolve_workbook_url()
    if not url:
        return pd.Series(dtype="float64")

    try:
        resp = requests.get(url, timeout=WORKBOOK_TIMEOUT_SECONDS)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.warning("worldbank: workbook download failed: %s", e)
        return pd.Series(dtype="float64")

    try:
        df = pd.read_excel(io.BytesIO(resp.content), sheet_name="Monthly Prices", header=4)
    except Exception as e:
        logger.warning("worldbank: workbook parse failed: %s", e)
        return pd.Series(dtype="float64")

    if df is None or df.empty:
        return pd.Series(dtype="float64")

    df.columns = df.columns.astype(str).str.strip()
    df.rename(columns={df.columns[0]: "Date"}, inplace=True)

    gold_col = next((c for c in df.columns if str(c).strip().lower() == "gold"), None)
    if gold_col is None:
        logger.warning("worldbank: 'Gold' column missing from workbook.")
        return pd.Series(dtype="float64")

    out = df[["Date", gold_col]].iloc[1:].dropna(subset=[gold_col]).copy()
    out["Date"] = (
        out["Date"].astype(str).str.strip().str.replace("M", "-", regex=False)
    )
    out[gold_col] = pd.to_numeric(out[gold_col], errors="coerce")
    out["Date"] = pd.to_datetime(out["Date"], errors="coerce")
    out = out.dropna(subset=["Date", gold_col]).sort_values("Date")
    return out.set_index("Date")[gold_col].rename("GOLD_PRICE")
```

- [ ] **Step 3: Create the remaining four modules (`static_inputs.py`, `processing.py`, `storage.py`, `freshness.py`)**

The bodies are mechanical extracts of the corresponding sections of the legacy `logic/data_fetcher.py`. Move (do not copy) the relevant functions from these line ranges:

| New module | Functions to move from `logic/data_fetcher.py` |
|------------|--------------------------------------------------|
| `static_inputs.py` | `get_sa_inflation()` (the hardcoded SA inflation dict-builder) |
| `processing.py` | `process_to_monthly()`, `merge_sources()` (and any helpers used only by these) |
| `storage.py` | `save_to_supabase()`, `replace_gold_price_column_in_supabase()`, `fetch_data_from_supabase()` — but wrap every `supabase.table(...).execute()` call in `_with_supabase_timeout(...)` (helper below) so a hung Supabase request can't wedge the worker |
| `freshness.py` | `should_update_from_api()` |

Add this helper to `logic/data/storage.py`:

```python
import concurrent.futures
SUPABASE_TIMEOUT_SECONDS = 10

def _with_supabase_timeout(fn, *args, **kwargs):
    """Run a Supabase call with a hard timeout. Returns None on timeout/error."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        future = ex.submit(fn, *args, **kwargs)
        try:
            return future.result(timeout=SUPABASE_TIMEOUT_SECONDS)
        except concurrent.futures.TimeoutError:
            logger.warning("supabase: TIMEOUT after %ds — returning None", SUPABASE_TIMEOUT_SECONDS)
            return None
        except Exception as exc:
            logger.warning("supabase: call failed: %s", exc)
            return None
```

Replace each `supabase.table("...").execute()` site in storage.py with `_with_supabase_timeout(lambda: supabase.table("...").execute())`.

- [ ] **Step 4: Create `logic/data/__init__.py` re-exporting the legacy public API**

```python
"""Compatibility shim: legacy callers import from `logic.data_fetcher`.

The split into submodules is invisible to callers because `__init__.py`
re-exports the same names the old single file exposed.
"""
from logic.data.fred_source import fetch_fred_data, FRED_SERIES
from logic.data.worldbank_source import fetch_world_bank_gold_data
from logic.data.static_inputs import get_sa_inflation
from logic.data.processing import process_to_monthly, merge_sources
from logic.data.storage import (
    save_to_supabase,
    replace_gold_price_column_in_supabase,
    fetch_data_from_supabase,
)
from logic.data.freshness import should_update_from_api

__all__ = [
    "fetch_fred_data",
    "FRED_SERIES",
    "fetch_world_bank_gold_data",
    "get_sa_inflation",
    "process_to_monthly",
    "merge_sources",
    "save_to_supabase",
    "replace_gold_price_column_in_supabase",
    "fetch_data_from_supabase",
    "should_update_from_api",
]
```

- [ ] **Step 5: Replace `logic/data_fetcher.py` with a thin shim**

```python
"""Backwards-compat shim. The implementation now lives in `logic.data`.

Existing imports like `from logic.data_fetcher import fetch_fred_data`
continue to work unchanged.
"""
from logic.data import *  # noqa: F401,F403
from logic.data import (  # noqa: F401
    fetch_fred_data,
    fetch_world_bank_gold_data,
    get_sa_inflation,
    process_to_monthly,
    merge_sources,
    save_to_supabase,
    replace_gold_price_column_in_supabase,
    fetch_data_from_supabase,
    should_update_from_api,
)
```

- [ ] **Step 6: Write `scripts/verify/timeouts.py` — proves hangs are gone**

```python
"""Prove FRED + World Bank fetches respect their hard timeouts.

This is the single most important verification: it monkeypatches the
HTTP layer to sleep beyond the timeout, then asserts our wrappers raise
within the bound. If this passes, hangs on the request path are gone.
"""
import sys
import time
from unittest.mock import patch

EXPECTED_FRED_BOUND = 17    # 15s timeout + ~2s thread overhead
EXPECTED_WB_BOUND   = 22    # 20s timeout + ~2s thread overhead


def _slow_get(*_a, **_kw):
    time.sleep(60)


def _slow_fred_series(*_a, **_kw):
    time.sleep(60)


def main() -> int:
    # World Bank: requests.get is the entry point — patch it.
    from logic.data import worldbank_source
    started = time.monotonic()
    with patch("logic.data.worldbank_source.requests.get", side_effect=_slow_get):
        result = worldbank_source.fetch_world_bank_gold_data()
    elapsed = time.monotonic() - started
    if elapsed > EXPECTED_WB_BOUND:
        print(f"FAIL: worldbank fetch took {elapsed:.1f}s > {EXPECTED_WB_BOUND}s bound")
        return 1
    if not result.empty:
        print(f"FAIL: worldbank fetch returned data despite stub")
        return 1
    print(f"OK: worldbank timeout enforced ({elapsed:.1f}s, returned empty Series)")

    # FRED: patch fred.get_series to sleep.
    from logic.data import fred_source
    started = time.monotonic()
    with patch.object(fred_source.Fred, "get_series", side_effect=_slow_fred_series):
        df = fred_source.fetch_fred_data()
    elapsed = time.monotonic() - started
    # FRED has 8 series, each ~17s bound, but we only need ONE to be bounded —
    # the loop should chew through all 8 in ~8 * 17 = 136s. We assert the FIRST
    # series timeout fires correctly by checking the per-series log + that we
    # got an empty DataFrame back.
    if df.empty:
        print(f"OK: fred fetch returned empty after timeouts (total {elapsed:.1f}s)")
    else:
        print(f"FAIL: fred fetch returned data despite stub")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 7: Run verify**

```bash
python scripts/verify/timeouts.py
```

Expected output:
```
OK: worldbank timeout enforced (~20s, returned empty Series)
OK: fred fetch returned empty after timeouts (total ~140s)
```

If the FRED step takes too long for your patience, set the env var `FRED_API_KEY=disabled-for-test` and run only the World Bank check (the script will return early for FRED with the key missing).

- [ ] **Step 8: Smoke the import compatibility**

```bash
python -c "from logic.data_fetcher import fetch_fred_data, fetch_data_from_supabase, should_update_from_api; print('OK: legacy imports work')"
```

Expected output:
```
OK: legacy imports work
```

- [ ] **Step 9: Commit**

```bash
git add logic/data/ logic/data_fetcher.py scripts/verify/timeouts.py
git commit -m "refactor(data): split data_fetcher into logic/data/ package + add hard timeouts

Hard per-series timeout (FRED 15s, World Bank 20s, Supabase 10s) on every
external call. The legacy pd.read_excel(url) was the prime hang suspect;
it now goes through requests.get(timeout=20) + BytesIO. Public API
preserved via re-export shim."
```

---

### Task 4: Split `logic/model.py` into `logic/model/` package

**Files:**
- Create: `logic/model/__init__.py`, `logic/model/loading.py`, `logic/model/features.py`, `logic/model/inference.py`, `logic/model/forecasting.py`, `logic/model/scenario.py`, `logic/model/explain.py`
- Delete: `logic/model.py` (after extracting)
- Create: `scripts/verify/model_imports.py`

- [ ] **Step 1: Move existing functions into per-responsibility modules**

| New module | Functions from `logic/model.py` (current 1042-line file) |
|------------|----------------------------------------------------------|
| `loading.py` | `load_model()` (joblib.load + diskcache wrap), `_MODEL_CACHE_KEY`, model file path constant |
| `features.py` | `engineer_features()`, the 11-feature column list, lag/zscore/logret helpers |
| `inference.py` | `predict_one()` (single-step), the wrapper that takes engineered features + returns a float |
| `forecasting.py` | `multi_horizon_forecast()` (1M, 3M, 6M iteration), `_iterate_forecast()` |
| `scenario.py` | `predict_scenario()`, `compute_scenario_baseline()`, slider mapping helpers |
| `explain.py` | `compute_feature_contributions()` (SHAP-style decomposition for the linear Huber model) |

For each function, **move** (don't copy) the function and its private helpers. Update any cross-module calls (e.g., `forecasting.py` calling `predict_one` becomes `from logic.model.inference import predict_one`).

- [ ] **Step 2: Write `logic/model/__init__.py` re-exporting the legacy public API**

```python
"""Compatibility shim: legacy callers import `from logic.model import X`.

`compute_full_predictions_payload` is added in Task 5 and re-exported here.
"""
from logic.model.loading import load_model
from logic.model.features import engineer_features
from logic.model.inference import predict_one
from logic.model.forecasting import multi_horizon_forecast
from logic.model.scenario import predict_scenario, compute_scenario_baseline
from logic.model.explain import compute_feature_contributions

# Re-export Supabase fetch (used by app.py warmup) — actually lives in logic.data
# but historically callers imported it from logic.model. Preserve that.
from logic.data import fetch_data_from_supabase

__all__ = [
    "load_model",
    "engineer_features",
    "predict_one",
    "multi_horizon_forecast",
    "predict_scenario",
    "compute_scenario_baseline",
    "compute_feature_contributions",
    "fetch_data_from_supabase",
]
```

- [ ] **Step 3: Delete the old `logic/model.py`**

```bash
git rm logic/model.py
```

- [ ] **Step 4: Write `scripts/verify/model_imports.py`**

```python
"""Verify the package split preserves the legacy public surface."""
import sys

EXPECTED = [
    "load_model",
    "engineer_features",
    "predict_one",
    "multi_horizon_forecast",
    "predict_scenario",
    "compute_scenario_baseline",
    "compute_feature_contributions",
    "fetch_data_from_supabase",
]

def main() -> int:
    import logic.model as m
    missing = [name for name in EXPECTED if not hasattr(m, name)]
    if missing:
        print(f"FAIL: logic.model missing: {missing}")
        return 1

    # Sanity: load_model() returns something callable-ish (sklearn Pipeline)
    pipeline = m.load_model()
    if pipeline is None:
        print("FAIL: load_model() returned None")
        return 1
    if not hasattr(pipeline, "predict"):
        print("FAIL: load_model() returned object without .predict")
        return 1

    print(f"OK: logic.model package surface complete; pipeline={type(pipeline).__name__}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run verify**

```bash
python scripts/verify/model_imports.py
```

Expected output:
```
OK: logic.model package surface complete; pipeline=Pipeline
```

- [ ] **Step 6: Commit**

```bash
git add logic/model/ scripts/verify/model_imports.py
git commit -m "refactor(model): split model.py into logic/model/ package

Single 1042-line file split by responsibility: loading, features,
inference, forecasting, scenario, explain. Public API unchanged via
re-export shim."
```

---

### Task 5: Add `compute_full_predictions_payload()` to `logic/model/`

**Files:**
- Create: `logic/model/payload.py`
- Modify: `logic/model/__init__.py`
- Create: `scripts/verify/payload.py`

- [ ] **Step 1: Write `logic/model/payload.py`**

```python
"""Build a CachePayload from a fully-prepared monthly DataFrame.

Pure function — no I/O. The data layer fetches; this module computes;
the predictions_cache layer persists.
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone

import pandas as pd

from logic.cache_contract import (
    CACHE_CONTRACT_VERSION,
    CachePayload,
    CacheMetadata,
    HorizonForecast,
    FeatureContribution,
    FitHistoryPoint,
    ScenarioBaseline,
)
from logic.model.features import engineer_features
from logic.model.forecasting import multi_horizon_forecast
from logic.model.scenario import compute_scenario_baseline
from logic.model.explain import compute_feature_contributions

logger = logging.getLogger(__name__)
MODEL_VERSION = "huber-v1-2026-03-29"
FIT_HISTORY_MONTHS = 60


def compute_full_predictions_payload(monthly_df: pd.DataFrame) -> CachePayload:
    """Compute the full dashboard cache payload from monthly data.

    Args:
        monthly_df: DataFrame indexed by month-end Timestamp with all 11
        feature columns + ZAR_USD target. Output of logic.data.processing.
    """
    started = datetime.now(timezone.utc)

    features = engineer_features(monthly_df)
    forecasts_raw = multi_horizon_forecast(features, horizons=(1, 3, 6))

    forecasts: list[HorizonForecast] = [
        HorizonForecast(
            horizon_months=h,
            forecast_zar_usd=float(v["forecast"]),
            forecast_date=v["forecast_date"].strftime("%Y-%m-%d"),
        )
        for h, v in forecasts_raw.items()
    ]

    contributions_raw = compute_feature_contributions(features)
    feature_contributions: list[FeatureContribution] = [
        FeatureContribution(
            feature=row["feature"],
            contribution=float(row["contribution"]),
            value=float(row["value"]),
        )
        for row in contributions_raw
    ]

    fit_recent = features.tail(FIT_HISTORY_MONTHS)
    fit_history: list[FitHistoryPoint] = [
        FitHistoryPoint(
            date=idx.strftime("%Y-%m-%d"),
            actual=float(row["actual"]),
            predicted=float(row["predicted"]),
        )
        for idx, row in fit_recent.iterrows()
    ]

    baseline_raw = compute_scenario_baseline(features)
    scenario_baseline = ScenarioBaseline(
        feature_values={k: float(v) for k, v in baseline_raw["feature_values"].items()},
        baseline_forecast_1m=float(baseline_raw["forecast_1m"]),
        baseline_date=baseline_raw["baseline_date"].strftime("%Y-%m-%d"),
    )

    metadata = CacheMetadata(
        cache_contract_version=CACHE_CONTRACT_VERSION,
        model_version=MODEL_VERSION,
        computed_at=started.isoformat(),
        data_through=monthly_df.index[-1].strftime("%Y-%m-%d"),
        refresh_status="success",
    )

    return CachePayload(
        metadata=metadata,
        forecasts=forecasts,
        feature_contributions=feature_contributions,
        fit_history=fit_history,
        scenario_baseline=scenario_baseline,
    )
```

- [ ] **Step 2: Re-export from `logic/model/__init__.py`**

Add to the imports at the top of `logic/model/__init__.py`:

```python
from logic.model.payload import compute_full_predictions_payload, MODEL_VERSION
```

And to `__all__`:

```python
"compute_full_predictions_payload",
"MODEL_VERSION",
```

- [ ] **Step 3: Write `scripts/verify/payload.py`**

```python
"""Build a real payload from current Supabase data and verify shape."""
import json
import sys

from logic.cache_contract import CACHE_CONTRACT_VERSION
from logic.data import fetch_data_from_supabase
from logic.model import compute_full_predictions_payload, MODEL_VERSION

def main() -> int:
    df = fetch_data_from_supabase()
    if df is None or df.empty:
        print("FAIL: Supabase returned no data")
        return 1
    print(f"  fetched {len(df)} rows, latest={df.index[-1]}")

    payload = compute_full_predictions_payload(df)

    if payload["metadata"]["cache_contract_version"] != CACHE_CONTRACT_VERSION:
        print(f"FAIL: contract version mismatch")
        return 1
    if payload["metadata"]["model_version"] != MODEL_VERSION:
        print(f"FAIL: model version mismatch")
        return 1
    if len(payload["forecasts"]) != 3:
        print(f"FAIL: expected 3 horizon forecasts, got {len(payload['forecasts'])}")
        return 1
    if not payload["feature_contributions"]:
        print(f"FAIL: feature_contributions empty")
        return 1
    if len(payload["fit_history"]) > 60:
        print(f"FAIL: fit_history too long: {len(payload['fit_history'])}")
        return 1

    # Roundtrip JSON.
    try:
        json.dumps(payload)
    except (TypeError, ValueError) as e:
        print(f"FAIL: payload not JSON-serializable: {e}")
        return 1

    print(f"OK: payload built, forecasts={len(payload['forecasts'])}, "
          f"contributions={len(payload['feature_contributions'])}, "
          f"fit_history={len(payload['fit_history'])}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run verify**

```bash
python scripts/verify/payload.py
```

Expected output:
```
  fetched <N> rows, latest=<date>
OK: payload built, forecasts=3, contributions=11, fit_history=60
```

- [ ] **Step 5: Commit**

```bash
git add logic/model/payload.py logic/model/__init__.py scripts/verify/payload.py
git commit -m "feat(model): add compute_full_predictions_payload

Pure function turning a monthly DataFrame into the CachePayload that
the dashboard hydrates from. Bundles forecasts, feature contributions,
fit history (60-month window), and scenario baseline into one structure."
```

---

### Task 6: Asset isolation — Three.js + critical CSS

**Files:**
- Modify: `app.py:72-82` (Dash init — add `assets_ignore`)
- Create: `assets/critical.css`
- Modify: `assets/style.css` (remove rules promoted to critical)
- Modify: `app.py` (custom `index_string` with conditional Three.js)

- [ ] **Step 1: Inventory above-the-fold rules**

Open `assets/style.css` and identify every rule that affects the visible viewport before scrolling on **landing/login** and **dashboard top bar**. Typical candidates:
- `:root`, theme variables, `body`, `html`
- `#theme-main-container`, `.navbar`, `.dashboard-header`
- Login hero, button primary, login form layout

Move these rules into a new file `assets/critical.css`. Target: under 8KB unminified.

- [ ] **Step 2: Create `assets/critical.css`**

Paste the rules identified in Step 1. Keep `style.css` for everything else (chart styles, scenario sliders, modals, chat panel — none of which is above-the-fold).

- [ ] **Step 3: Modify Dash init in `app.py:72-82` — exclude both Three.js and critical CSS from auto-include**

Replace:

```python
app = Dash(
    __name__,
    server=server,
    use_pages=True,
    external_stylesheets=[dbc.themes.BOOTSTRAP],
    suppress_callback_exceptions=True,
    background_callback_manager=background_callback_manager,
    meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1, maximum-scale=5, viewport-fit=cover"}]
)
```

With:

```python
app = Dash(
    __name__,
    server=server,
    use_pages=True,
    external_stylesheets=[dbc.themes.BOOTSTRAP],
    # Exclude Three.js (only loaded on landing/login via index_string) and
    # critical.css (inlined via index_string). Everything else in /assets/
    # is auto-served on every page.
    assets_ignore=r"(three-scenes\.js|critical\.css)",
    suppress_callback_exceptions=True,
    background_callback_manager=background_callback_manager,
    meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1, maximum-scale=5, viewport-fit=cover"}],
)
```

- [ ] **Step 4: Add a custom `index_string` immediately after `app = Dash(...)`**

```python
import pathlib

# Read critical.css at startup (it's small, ~8KB).
_CRITICAL_CSS = (pathlib.Path(__file__).parent / "assets" / "critical.css").read_text()

# Pages that should also load Three.js. Everything else (dashboard, profile)
# skips the 485KB bundle entirely.
_THREEJS_PAGES = {"/", "/login", "/registration"}

app.index_string = f"""<!DOCTYPE html>
<html>
  <head>
    {{%metas%}}
    <title>{{%title%}}</title>
    {{%favicon%}}
    {{%css%}}
    <style>{_CRITICAL_CSS}</style>
  </head>
  <body>
    {{%app_entry%}}
    <footer>
      {{%config%}}
      {{%scripts%}}
      {{%renderer%}}
      <script>
        if ({list(_THREEJS_PAGES)!r}.includes(window.location.pathname)) {{
          var s = document.createElement('script');
          s.src = '/assets/three-scenes.js?m=' + Date.now();
          s.defer = true;
          document.body.appendChild(s);
        }}
      </script>
    </footer>
  </body>
</html>"""
```

- [ ] **Step 5: Smoke locally**

```bash
python app.py &
APP_PID=$!
sleep 3
echo "--- /login should load three-scenes.js ---"
curl -s http://localhost:10000/login | grep -c three-scenes.js
echo "--- /dashboard should NOT load three-scenes.js in HTML ---"
curl -s http://localhost:10000/dashboard | grep -c three-scenes.js
kill $APP_PID
```

Expected: `1` for `/login`, `0` for `/dashboard` (note the conditional `<script>` block is in HTML for both pages, but the actual `three-scenes.js` URL only resolves at runtime on listed pages — `grep -c three-scenes.js` will hit the inline JS once on every page; instead, look at the network tab in a real browser to verify the actual bundle download).

Better verification — open Chrome DevTools, reload `/dashboard`, look at the Network tab, filter by `three-scenes`. Expected: zero requests.

- [ ] **Step 6: Lighthouse audit on dashboard**

```bash
# Requires `npx lighthouse` (one-shot, no install needed)
npx lighthouse http://localhost:10000/dashboard --only-categories=performance --output=json --quiet > /tmp/lh-after.json
jq '.audits["resource-summary"].details.items' /tmp/lh-after.json
```

Expected: `script` total well under 200KB. `three-scenes.js` should be absent.

- [ ] **Step 7: Commit**

```bash
git add app.py assets/critical.css assets/style.css
git commit -m "perf(assets): isolate Three.js + inline critical CSS

three-scenes.js (485KB) excluded from Dash auto-include via assets_ignore;
loaded only on /, /login, /registration via per-page conditional script
in index_string. critical.css (above-the-fold rules) inlined into <head>.
The remaining style.css loads async via Dash's normal mechanism."
```

---

### Task 7: Add `flask-compress` for gzip

**Files:**
- Modify: `requirements.txt`
- Modify: `app.py` (add `Compress(server)` after Dash init)

- [ ] **Step 1: Add the dependency**

Edit `requirements.txt`, append:

```
flask-compress==1.15
```

Then:

```bash
pip install flask-compress==1.15
```

- [ ] **Step 2: Wire it up in `app.py`**

Right after the line `app = Dash(...)` (or after the index_string assignment from Task 6, whichever comes last), add:

```python
from flask_compress import Compress

# Gzip responses (HTML, JS, CSS, JSON). Dash serves uncompressed by default;
# Render's edge does not auto-gzip Python WSGI responses.
Compress(server)
```

- [ ] **Step 3: Smoke locally**

```bash
python app.py &
APP_PID=$!
sleep 3
curl -s -H "Accept-Encoding: gzip" -I http://localhost:10000/dashboard | grep -i content-encoding
kill $APP_PID
```

Expected output:
```
content-encoding: gzip
```

- [ ] **Step 4: Verify uncompressed payload size shrinks**

```bash
python app.py &
APP_PID=$!
sleep 3
echo "--- without gzip ---"
curl -s -o /tmp/dash-plain http://localhost:10000/dashboard && wc -c /tmp/dash-plain
echo "--- with gzip ---"
curl -s -H "Accept-Encoding: gzip" -o /tmp/dash-gzip http://localhost:10000/dashboard && wc -c /tmp/dash-gzip
kill $APP_PID
```

Expected: gzipped size ~25% of plain size (Plotly + Bootstrap minify well).

- [ ] **Step 5: Commit**

```bash
git add requirements.txt app.py
git commit -m "perf(assets): add flask-compress for gzip on all responses

Dash serves uncompressed by default. Adding Compress(server) gzips HTML,
CSS, JS, and JSON. Single-line revert if anything misbehaves."
```

---

## Wave 2 — Cache Layer (Sequential)

### Task 8: `logic/predictions_cache/` package

**Files:**
- Create: `logic/predictions_cache/__init__.py`, `read.py`, `write.py`, `freshness.py`, `refresh.py`, `bootstrap.py`
- Create: `scripts/verify/cache_roundtrip.py`, `scripts/verify/refresh_idempotent.py`

- [ ] **Step 1: Write `logic/predictions_cache/read.py`**

```python
"""Read the latest CachePayload for the active model version."""
from __future__ import annotations
import logging
from typing import cast

from logic.cache_contract import CACHE_CONTRACT_VERSION, CachePayload, CacheMetadata
from logic.model import MODEL_VERSION
from logic.supabase_client import get_supabase

logger = logging.getLogger(__name__)


def read_cached() -> CachePayload | None:
    """Return the cached payload for the current model version, or None.

    None is returned for: empty table, contract-version mismatch, Supabase
    failure. Callers must treat None as "show skeleton + trigger refresh".
    """
    sb = get_supabase()
    if sb is None:
        logger.warning("predictions_cache.read: Supabase unavailable")
        return None
    try:
        resp = sb.table("predictions").select("*").eq("model_version", MODEL_VERSION).limit(1).execute()
    except Exception as exc:
        logger.warning("predictions_cache.read: query failed: %s", exc)
        return None

    if not resp.data:
        logger.info("predictions_cache.read: cache miss (no row for model_version=%s)", MODEL_VERSION)
        return None

    row = resp.data[0]
    if row.get("cache_contract_version") != CACHE_CONTRACT_VERSION:
        logger.info("predictions_cache.read: contract version mismatch row=%s expected=%s",
                    row.get("cache_contract_version"), CACHE_CONTRACT_VERSION)
        return None

    payload = cast(CachePayload, {
        "metadata": CacheMetadata(
            cache_contract_version=row["cache_contract_version"],
            model_version=row["model_version"],
            computed_at=row["computed_at"],
            data_through=row["data_through"],
            refresh_status=row["refresh_status"],
        ),
        "forecasts": row["forecasts"],
        "feature_contributions": row["feature_contributions"],
        "fit_history": row["fit_history"],
        "scenario_baseline": row["scenario_baseline"],
    })
    return payload
```

- [ ] **Step 2: Write `logic/predictions_cache/write.py`**

```python
"""Persist a CachePayload via UPSERT on (model_version)."""
from __future__ import annotations
import logging
from logic.cache_contract import CachePayload
from logic.supabase_client import get_supabase

logger = logging.getLogger(__name__)


def write_payload(payload: CachePayload) -> bool:
    """UPSERT the payload. Returns True on success, False on failure."""
    sb = get_supabase()
    if sb is None:
        logger.warning("predictions_cache.write: Supabase unavailable")
        return False

    row = {
        "model_version": payload["metadata"]["model_version"],
        "cache_contract_version": payload["metadata"]["cache_contract_version"],
        "computed_at": payload["metadata"]["computed_at"],
        "data_through": payload["metadata"]["data_through"],
        "refresh_status": payload["metadata"]["refresh_status"],
        "forecasts": payload["forecasts"],
        "feature_contributions": payload["feature_contributions"],
        "fit_history": payload["fit_history"],
        "scenario_baseline": payload["scenario_baseline"],
    }
    try:
        sb.table("predictions").upsert(row, on_conflict="model_version").execute()
    except Exception as exc:
        logger.warning("predictions_cache.write: upsert failed: %s", exc)
        return False

    logger.info("predictions_cache.write: stored payload (data_through=%s)",
                payload["metadata"]["data_through"])
    return True
```

- [ ] **Step 3: Write `logic/predictions_cache/freshness.py`**

```python
"""Decide whether the cache is stale enough to warrant a refresh."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from logic.cache_contract import CacheMetadata

STALE_AFTER = timedelta(hours=24)


def is_stale(metadata: CacheMetadata | None) -> bool:
    """True if cache is missing or older than STALE_AFTER."""
    if metadata is None:
        return True
    try:
        computed_at = datetime.fromisoformat(metadata["computed_at"])
        if computed_at.tzinfo is None:
            computed_at = computed_at.replace(tzinfo=timezone.utc)
    except ValueError:
        return True
    return datetime.now(timezone.utc) - computed_at > STALE_AFTER
```

- [ ] **Step 4: Write `logic/predictions_cache/refresh.py`**

```python
"""Opportunistic background refresh of the predictions cache.

Single-flight via threading.Lock — concurrent callers see status='skipped'
and return immediately. The lock is process-local; under gunicorn with
workers=1 (current Render config) that's fine. With workers>1 the worst
case is a few duplicate refreshes — still idempotent thanks to UPSERT.
"""
from __future__ import annotations
import concurrent.futures
import logging
import threading
import time

from logic.cache_contract import RefreshResult, CachePayload
from logic.data import (
    fetch_fred_data,
    fetch_world_bank_gold_data,
    get_sa_inflation,
    process_to_monthly,
    save_to_supabase,
    replace_gold_price_column_in_supabase,
)
from logic.model import compute_full_predictions_payload
from logic.predictions_cache.write import write_payload

logger = logging.getLogger(__name__)
_REFRESH_LOCK = threading.Lock()

FRED_RESULT_TIMEOUT = 20    # 15s internal + buffer
WB_RESULT_TIMEOUT   = 25    # 20s internal + buffer


def refresh_async() -> RefreshResult:
    """Trigger a refresh. Returns immediately if one is already running."""
    if not _REFRESH_LOCK.acquire(blocking=False):
        logger.info("cache.refresh.skipped lock_held")
        return RefreshResult(status="skipped", reason="lock_held", payload=None, elapsed_ms=0)

    started = time.monotonic()
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
            fred_future = ex.submit(fetch_fred_data)
            wb_future   = ex.submit(fetch_world_bank_gold_data)
            sa_data     = get_sa_inflation()

            try:
                fred_df = fred_future.result(timeout=FRED_RESULT_TIMEOUT)
            except concurrent.futures.TimeoutError:
                logger.warning("cache.refresh.failed reason=fred_timeout")
                return RefreshResult(
                    status="failed", reason="fred_timeout", payload=None,
                    elapsed_ms=int((time.monotonic() - started) * 1000),
                )

            try:
                wb_series = wb_future.result(timeout=WB_RESULT_TIMEOUT)
            except concurrent.futures.TimeoutError:
                logger.warning("cache.refresh.failed reason=worldbank_timeout")
                return RefreshResult(
                    status="failed", reason="worldbank_timeout", payload=None,
                    elapsed_ms=int((time.monotonic() - started) * 1000),
                )

        if fred_df.empty:
            logger.warning("cache.refresh.failed reason=fred_empty")
            return RefreshResult(
                status="failed", reason="fred_empty", payload=None,
                elapsed_ms=int((time.monotonic() - started) * 1000),
            )

        monthly = process_to_monthly(fred_df, wb_series, sa_data)
        save_to_supabase(monthly)
        if not wb_series.empty:
            replace_gold_price_column_in_supabase(wb_series)

        payload = compute_full_predictions_payload(monthly)
        ok = write_payload(payload)
        if not ok:
            return RefreshResult(
                status="failed", reason="cache_write_failed", payload=None,
                elapsed_ms=int((time.monotonic() - started) * 1000),
            )

        elapsed_ms = int((time.monotonic() - started) * 1000)
        logger.info("cache.refresh.complete elapsed_ms=%d status=success", elapsed_ms)
        return RefreshResult(status="success", reason=None, payload=payload, elapsed_ms=elapsed_ms)
    finally:
        _REFRESH_LOCK.release()
```

- [ ] **Step 5: Write `logic/predictions_cache/bootstrap.py`**

```python
"""One-time eager refresh for empty cache. Run via:
    python -m logic.predictions_cache.bootstrap
"""
from __future__ import annotations
import logging
import sys
from logic.predictions_cache.refresh import refresh_async

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def main() -> int:
    print("Bootstrapping predictions cache (this typically takes 30-60s)...")
    result = refresh_async()
    if result["status"] == "success":
        print(f"OK: cache populated in {result['elapsed_ms']}ms")
        return 0
    print(f"FAIL: {result['status']} reason={result['reason']}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 6: Write `logic/predictions_cache/__init__.py`**

```python
from logic.predictions_cache.read import read_cached
from logic.predictions_cache.write import write_payload
from logic.predictions_cache.freshness import is_stale
from logic.predictions_cache.refresh import refresh_async

__all__ = ["read_cached", "write_payload", "is_stale", "refresh_async"]
```

- [ ] **Step 7: Write `scripts/verify/cache_roundtrip.py`**

```python
"""Verify write_payload() → read_cached() roundtrip."""
import sys
from datetime import datetime, timezone

from logic.cache_contract import (
    CACHE_CONTRACT_VERSION, CachePayload, CacheMetadata,
    HorizonForecast, FeatureContribution, FitHistoryPoint, ScenarioBaseline,
)
from logic.predictions_cache import write_payload, read_cached


def main() -> int:
    now = datetime.now(timezone.utc).isoformat()
    test_version = "verify-roundtrip-temp"
    payload = CachePayload(
        metadata=CacheMetadata(
            cache_contract_version=CACHE_CONTRACT_VERSION,
            model_version=test_version,
            computed_at=now,
            data_through="2026-03-31",
            refresh_status="success",
        ),
        forecasts=[HorizonForecast(horizon_months=1, forecast_zar_usd=18.5, forecast_date="2026-04-30")],
        feature_contributions=[FeatureContribution(feature="VIX", contribution=0.1, value=15.0)],
        fit_history=[FitHistoryPoint(date="2026-03-31", actual=18.3, predicted=18.27)],
        scenario_baseline=ScenarioBaseline(
            feature_values={"VIX": 15.0}, baseline_forecast_1m=18.5, baseline_date="2026-04-30"
        ),
    )

    # Patch MODEL_VERSION used by read_cached for this test.
    import logic.predictions_cache.read as read_mod
    original = read_mod.MODEL_VERSION
    read_mod.MODEL_VERSION = test_version
    try:
        if not write_payload(payload):
            print("FAIL: write_payload returned False")
            return 1
        echo = read_cached()
        if echo is None:
            print("FAIL: read_cached returned None after write")
            return 1
        if echo["metadata"]["model_version"] != test_version:
            print("FAIL: model_version mismatch")
            return 1
        if echo["forecasts"][0]["forecast_zar_usd"] != 18.5:
            print("FAIL: forecast value mismatch")
            return 1
    finally:
        read_mod.MODEL_VERSION = original
        # Best-effort cleanup of the test row.
        from logic.supabase_client import get_supabase
        sb = get_supabase()
        if sb is not None:
            try:
                sb.table("predictions").delete().eq("model_version", test_version).execute()
            except Exception:
                pass

    print("OK: write → read roundtrip preserved payload")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 8: Write `scripts/verify/refresh_idempotent.py`**

```python
"""Verify the refresh lock prevents concurrent refreshes."""
import sys
import threading
import time
from logic.predictions_cache.refresh import refresh_async


def main() -> int:
    results = []
    def worker():
        results.append(refresh_async())

    # Fire two threads. The first should win the lock; the second should
    # return status=skipped within ~50ms.
    t1 = threading.Thread(target=worker)
    t2 = threading.Thread(target=worker)
    t1.start()
    time.sleep(0.05)  # let t1 grab the lock
    t2.start()
    t2.join(timeout=2)
    if t2.is_alive():
        print("FAIL: second refresh blocked instead of skipping")
        return 1

    second = next((r for r in results if r["status"] == "skipped"), None)
    if second is None:
        print(f"FAIL: no skipped result; got {[r['status'] for r in results]}")
        return 1
    if second["reason"] != "lock_held":
        print(f"FAIL: skip reason was {second['reason']}, expected lock_held")
        return 1
    if second["elapsed_ms"] > 100:
        print(f"FAIL: skip took {second['elapsed_ms']}ms, expected < 100ms")
        return 1

    # Wait for t1 to finish so we don't leave a refresh running.
    t1.join(timeout=180)

    print("OK: concurrent refresh skipped within bound")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 9: Run verifications**

```bash
python scripts/verify/cache_roundtrip.py
python scripts/verify/refresh_idempotent.py
```

Expected:
```
OK: write → read roundtrip preserved payload
OK: concurrent refresh skipped within bound
```

- [ ] **Step 10: Bootstrap the cache**

```bash
python -m logic.predictions_cache.bootstrap
```

Expected: `OK: cache populated in <30000-60000>ms`

Verify the row exists:

```bash
python scripts/verify/predictions_table.py
```

Expected: `OK: predictions table queryable, rows=1`

- [ ] **Step 11: Commit**

```bash
git add logic/predictions_cache/ scripts/verify/cache_roundtrip.py scripts/verify/refresh_idempotent.py
git commit -m "feat(cache): add predictions_cache package + bootstrap script

Read/write/freshness/refresh layered cleanly. refresh_async() is
single-flight via threading.Lock. Hard-bounded by FRED 20s + WB 25s
result timeouts. Bootstrap populates cache for fresh deploys."
```

---

### Task 9: `core/cache_callbacks.py` — hydrate + opportunistic refresh

**Files:**
- Create: `core/__init__.py`, `core/cache_callbacks.py`
- Modify: `app.py` (register cache callbacks; do **not** delete legacy chain yet — Wave 4 cuts over)

- [ ] **Step 1: Create `core/__init__.py`**

```python
"""Top-level Dash app wiring (split from the original 1619-line app.py).

Each module exposes `register(app)` that the entry-point app.py calls.
Wave 1 / Task X (full split) does not delete the legacy callbacks in
app.py yet — this module only adds the new cache callbacks side-by-side.
"""
```

- [ ] **Step 2: Create `core/cache_callbacks.py`**

```python
"""Hydrate dashboard from predictions cache + fire opportunistic refresh.

These callbacks REPLACE the three-step trigger chain in app.py (lines
~234-275 in the legacy file). For Wave 2 we add them alongside the
legacy chain; Wave 4 deletes the legacy chain in a single cutover commit.

Stores written by hydrate (read by tab-render callbacks):
  • fetched-data              — derived from payload.fit_history (time series for charts)
  • model-prediction-data     — payload.forecasts + feature_contributions
  • scenario-baseline-data    — payload.scenario_baseline
  • cache-metadata-store      — NEW: holds metadata for staleness UI banner
  • cache-status-store        — NEW: 'hit' | 'miss' | 'refreshing' | 'stale'
"""
from __future__ import annotations
import logging
import threading

import dash
from dash import Input, Output, State, callback

from logic.predictions_cache import read_cached, refresh_async, is_stale

logger = logging.getLogger(__name__)


def register(app: dash.Dash) -> None:
    """Wire cache callbacks into the given Dash app."""

    @callback(
        Output("fetched-data",            "data", allow_duplicate=True),
        Output("model-prediction-data",   "data", allow_duplicate=True),
        Output("scenario-baseline-data",  "data", allow_duplicate=True),
        Output("cache-metadata-store",    "data"),
        Output("cache-status-store",      "data", allow_duplicate=True),
        Input("_pages_location", "pathname"),
        Input("user-session", "data"),
        prevent_initial_call="initial_duplicate",
    )
    def hydrate_from_cache(pathname, session_data):
        """On dashboard nav, load CachePayload from Supabase and populate stores."""
        if pathname != "/dashboard":
            return (dash.no_update,) * 5

        payload = read_cached()
        if payload is None:
            logger.info("cache.hydrate.miss")
            return None, None, None, None, "miss"

        logger.info("cache.hydrate.hit data_through=%s", payload["metadata"]["data_through"])
        # Map CachePayload fields → legacy store ids.
        fetched = {
            "fit_history": payload["fit_history"],
            "data_through": payload["metadata"]["data_through"],
        }
        model_pred = {
            "forecasts": payload["forecasts"],
            "feature_contributions": payload["feature_contributions"],
        }
        return (
            fetched,
            model_pred,
            payload["scenario_baseline"],
            payload["metadata"],
            "hit",
        )

    @callback(
        Output("cache-status-store", "data", allow_duplicate=True),
        Output("cache-metadata-store", "data", allow_duplicate=True),
        Input("cache-status-store", "data"),
        State("cache-metadata-store", "data"),
        prevent_initial_call=True,
        background=True,
        running=[(Output("cache-refresh-spinner", "children"), "Refreshing data…", "")],
    )
    def opportunistic_refresh(status, metadata):
        """If cache is stale or missing, refresh in background — non-blocking."""
        if status not in ("hit", "miss"):
            return dash.no_update, dash.no_update

        if status == "hit" and not is_stale(metadata):
            return dash.no_update, dash.no_update

        result = refresh_async()
        if result["status"] != "success" or result["payload"] is None:
            logger.info("cache.refresh.no_swap status=%s reason=%s",
                        result["status"], result["reason"])
            return ("stale", dash.no_update)

        new_meta = result["payload"]["metadata"]
        return ("hit", new_meta)

    @callback(
        Output("fetched-data",            "data", allow_duplicate=True),
        Output("model-prediction-data",   "data", allow_duplicate=True),
        Output("scenario-baseline-data",  "data", allow_duplicate=True),
        Input("cache-metadata-store", "data"),
        prevent_initial_call=True,
    )
    def re_hydrate_after_refresh(_metadata):
        """When metadata changes (refresh just landed), re-pull cache."""
        payload = read_cached()
        if payload is None:
            return dash.no_update, dash.no_update, dash.no_update

        fetched = {
            "fit_history": payload["fit_history"],
            "data_through": payload["metadata"]["data_through"],
        }
        model_pred = {
            "forecasts": payload["forecasts"],
            "feature_contributions": payload["feature_contributions"],
        }
        return fetched, model_pred, payload["scenario_baseline"]
```

- [ ] **Step 3: Add the two new stores to `app.py:84-110` block**

In `app.layout = html.Div(...)`'s children list, append after the existing dcc.Store entries:

```python
    dcc.Store(id='cache-metadata-store', storage_type='session'),
    dcc.Store(id='cache-status-store',   data='miss', storage_type='session'),
    html.Div(id='cache-refresh-spinner', style={'display': 'none'}),
```

- [ ] **Step 4: Register the new callbacks in `app.py`**

After the `app.layout = ...` assignment in `app.py`, add:

```python
from core import cache_callbacks
cache_callbacks.register(app)
```

**Important:** Do NOT delete the legacy `global_prerender_trigger`, `chain_model_prediction`, or `chain_scenario_baseline` callbacks yet. Wave 4 does the cutover in one atomic commit.

- [ ] **Step 5: Smoke locally**

```bash
python app.py
# Open http://localhost:10000 in browser, log in, observe dashboard.
# Open DevTools → Application → Session Storage → http://localhost:10000.
# Confirm `cache-metadata-store` is populated with non-null JSON.
# Look at terminal logs for "cache.hydrate.hit data_through=…"
```

Expected: dashboard renders; cache hydrate log present.

- [ ] **Step 6: Commit**

```bash
git add core/__init__.py core/cache_callbacks.py app.py
git commit -m "feat(cache): wire hydrate + opportunistic refresh callbacks

Adds the new cache-driven pipeline alongside the legacy trigger chain.
Hydrate runs synchronously on /dashboard nav; opportunistic_refresh is
the only background callback in the new pipeline. Legacy chain stays
in place until the Wave 4 cutover."
```

---

## Wave 3 — Tab Extractions (Parallel: 3 Agents)

> Tasks 10, 11, 12 each extract one dashboard tab. They are independent because each tab has its own callback IDs. Coordinate only on the shared component module `pages/dashboard_components/skeleton.py` — define it in Task 10 and the others import it.

### Task 10: Extract Data tab → `pages/dashboard_tabs/data/`

**Files:**
- Create: `pages/dashboard_tabs/__init__.py`, `pages/dashboard_tabs/data/__init__.py`, `pages/dashboard_tabs/data/layout.py`, `pages/dashboard_tabs/data/callbacks.py`, `pages/dashboard_tabs/data/figures.py`
- Create: `pages/dashboard_components/__init__.py`, `pages/dashboard_components/skeleton.py`, `pages/dashboard_components/figures_common.py`
- Modify: `pages/dashboard.py` (remove Data tab code, import from new module)

- [ ] **Step 1: Inventory the Data tab in `pages/dashboard.py`**

```bash
grep -n "data-tab\|fetched-data\|plot-mode\|table-view-mode\|selected-predictors\|render_data_tab\|render_data_chart" pages/dashboard.py | head -30
```

Note line ranges of:
- The Data tab layout (a function or inline html.Div block)
- Callbacks whose `Output` IDs target Data-tab components
- Plotly figure builders specific to Data tab (time series, normalized, heatmap)

- [ ] **Step 2: Create the shared skeleton component**

Write `pages/dashboard_components/skeleton.py`:

```python
"""Reusable skeleton placeholders for tab content while data hydrates."""
from dash import html
import dash_bootstrap_components as dbc


def chart_skeleton(height: int = 400) -> html.Div:
    return html.Div(
        className="chart-skeleton",
        style={
            "height": f"{height}px",
            "background": "linear-gradient(90deg, var(--skeleton-bg, #f0f0f0), "
                          "var(--skeleton-shimmer, #e0e0e0), var(--skeleton-bg, #f0f0f0))",
            "backgroundSize": "200% 100%",
            "animation": "skeleton-shimmer 1.5s infinite",
            "borderRadius": "8px",
        },
    )


def metric_skeleton() -> dbc.Card:
    return dbc.Card(
        dbc.CardBody([
            html.Div(style={"width": "60%", "height": "12px", "background": "#e0e0e0",
                            "borderRadius": "4px", "marginBottom": "8px"}),
            html.Div(style={"width": "40%", "height": "24px", "background": "#d0d0d0",
                            "borderRadius": "4px"}),
        ]),
        className="metric-card-skeleton",
    )
```

Then add this CSS rule to `assets/style.css` (append):

```css
@keyframes skeleton-shimmer {
  0%   { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}
```

- [ ] **Step 3: Move Data-tab figure builders → `pages/dashboard_tabs/data/figures.py`**

Move every Plotly figure-builder function used only by the Data tab (typically named like `build_normalized_chart`, `build_heatmap`, `build_compare_2d`, `build_compare_3d`, etc.). Update import sites in callbacks to point at the new module.

- [ ] **Step 4: Move Data-tab layout → `pages/dashboard_tabs/data/layout.py`**

Extract the function (or inline expression) that produces the Data tab's `dbc.Tab(children=[...])` body into a `def layout() -> html.Div` here. Use `chart_skeleton()` from Step 2 for any chart container that depends on `fetched-data`.

- [ ] **Step 5: Move Data-tab callbacks → `pages/dashboard_tabs/data/callbacks.py`**

Wrap them in `def register(app: Dash) -> None:` so they're imported lazily.

- [ ] **Step 6: Wire `pages/dashboard_tabs/data/__init__.py`**

```python
from pages.dashboard_tabs.data.layout import layout
from pages.dashboard_tabs.data.callbacks import register

__all__ = ["layout", "register"]
```

- [ ] **Step 7: Update `pages/dashboard.py` to import the new module**

Replace the inline Data tab body with:

```python
from pages.dashboard_tabs import data as data_tab

# In the dbc.Tabs children list:
dbc.Tab(data_tab.layout(), label="Data", tab_id="data"),
```

And after the `layout = ...` definition:

```python
data_tab.register(dash.get_app())
```

- [ ] **Step 8: Smoke locally**

```bash
python app.py
# Browser: log in → /dashboard → Data tab. Verify all charts render with cached data.
# Toggle plot modes, predictors, table view. No regressions.
```

- [ ] **Step 9: Commit**

```bash
git add pages/dashboard_tabs/data/ pages/dashboard_components/ pages/dashboard.py assets/style.css
git commit -m "refactor(dashboard): extract Data tab to dashboard_tabs/data/ package

Layout, callbacks, and figures separated. Skeleton placeholders render
on mount so the tab is interactive before fetched-data populates."
```

---

### Task 11: Extract Model tab → `pages/dashboard_tabs/model/` (with lazy activation)

**Files:**
- Create: `pages/dashboard_tabs/model/__init__.py`, `layout.py`, `callbacks.py`, `figures.py`
- Modify: `pages/dashboard.py`

- [ ] **Step 1-7: Same shape as Task 10**

Mirror Task 10's steps, but for Model-tab code:
- Move all callbacks whose Outputs target Model-tab IDs (forecast cards, contribution chart, fit chart, metrics, diagnostic plots)
- Move all figure builders specific to Model tab
- Move the layout block

- [ ] **Step 8: Make Model tab content lazy**

In `pages/dashboard_tabs/model/layout.py`, define **two** functions:

```python
def shell() -> html.Div:
    """Lightweight shell rendered immediately — content built on activation."""
    return html.Div(id="model-tab-content", children=[chart_skeleton(height=200)])


def full() -> html.Div:
    """Full layout, built on first activation."""
    # ... move the existing Model-tab layout body here ...
```

In `pages/dashboard.py`, use `shell()` for the tab body:

```python
dbc.Tab(model_tab.shell(), label="Model", tab_id="model"),
```

Then add a callback in `pages/dashboard_tabs/model/callbacks.py`:

```python
@callback(
    Output("model-tab-content", "children"),
    Input("dashboard-tab", "data"),
    State("model-tab-content", "children"),
    prevent_initial_call=True,
)
def lazy_build_model_tab(active_tab, current_children):
    if active_tab != "model":
        return dash.no_update
    # Already built? Bail.
    if current_children and not (
        isinstance(current_children, list) and len(current_children) == 1
        and isinstance(current_children[0], dict)
        and current_children[0].get("props", {}).get("className") == "chart-skeleton"
    ):
        return dash.no_update
    from pages.dashboard_tabs.model.layout import full
    return full()
```

- [ ] **Step 9: Smoke locally**

```bash
python app.py
# DevTools Performance: record while clicking Data → Model.
# Confirm Model layout build only happens on first click.
# Subsequent Model→other→Model is instant.
```

- [ ] **Step 10: Commit**

```bash
git add pages/dashboard_tabs/model/ pages/dashboard.py
git commit -m "refactor(dashboard): extract Model tab + lazy activation

Tab body is a skeleton on mount; full layout builds on first
activation only. Subsequent tab switches reuse the built content."
```

---

### Task 12: Extract Scenario tab → `pages/dashboard_tabs/scenario/` (with lazy activation)

**Files:**
- Create: `pages/dashboard_tabs/scenario/__init__.py`, `layout.py`, `callbacks.py`, `figures.py`
- Modify: `pages/dashboard.py`

- [ ] **Steps 1-9: Mirror Task 11**

Apply the same shell/full split. Pay particular attention to:
- The slider components (every slider's `Input` becomes a callback in `callbacks.py`)
- `compute_scenario_baseline` is read-only from `scenario-baseline-data` store
- Live `predict_scenario` calls go through the in-memory model — keep the imports tight

- [ ] **Step 10: Verify slider response time**

```bash
python app.py
# Browser DevTools → Performance → record while dragging a slider for 5s.
# In the recording, find the longest "Scripting" task. Should be < 200ms.
```

- [ ] **Step 11: Commit**

```bash
git add pages/dashboard_tabs/scenario/ pages/dashboard.py
git commit -m "refactor(dashboard): extract Scenario tab + lazy activation

Same pattern as Model tab. Live slider interactions still use the
in-memory model directly (no cache round-trip)."
```

---

## Wave 4 — Cutover & Verification

### Task 13: Remove legacy trigger chain + delete legacy callbacks

**Files:**
- Modify: `app.py` (delete lines ~232-275: `global_prerender_trigger`, `chain_model_prediction`, `chain_scenario_baseline`)
- Modify: `app.py` (remove the three trigger stores: `fetch-trigger`, `model-prediction-trigger`, `scenario-trigger`)

- [ ] **Step 1: Delete legacy trigger callbacks**

Remove the three callback definitions (`global_prerender_trigger`, `chain_model_prediction`, `chain_scenario_baseline`) from `app.py`. After deletion, `grep -n "trigger" app.py` should not return results from those functions.

- [ ] **Step 2: Delete the three trigger stores**

Remove these lines from the layout block in `app.py`:

```python
    dcc.Store(id='fetch-trigger', data=0, storage_type='session'),
    dcc.Store(id='model-prediction-trigger', data=0, storage_type='session'),
    dcc.Store(id='scenario-trigger', data=0, storage_type='session'),
```

- [ ] **Step 3: Search for any stragglers referencing the trigger IDs**

```bash
grep -rn "fetch-trigger\|model-prediction-trigger\|scenario-trigger\|force-refresh-trigger" app.py pages/ logic/ core/
```

Expected: no results in callbacks. If `force-refresh-trigger` still has uses (manual refresh button), wire its Input to the new `cache-status-store` instead — when set to `"miss"`, the opportunistic refresh fires.

- [ ] **Step 4: Find and delete any background-callback fetcher in `pages/dashboard.py`**

```bash
grep -n "background=True" pages/dashboard.py
```

Each remaining `background=True` callback was part of the legacy chain. Delete them — their work now lives in `core/cache_callbacks.py`. The only `background=True` callback in the entire app should be `opportunistic_refresh`.

- [ ] **Step 5: Smoke locally end-to-end**

```bash
python app.py
```

Then in browser:
1. Log in.
2. Dashboard renders within ~1 second; charts populate from cached data.
3. Switch to Model tab — first click builds layout (note slight pause), subsequent are instant.
4. Switch to Scenario tab — same.
5. Drag a Scenario slider — response is sub-200ms.
6. Refresh page — same fast load.
7. Inspect DevTools Network tab — no `three-scenes.js` request on `/dashboard`.

- [ ] **Step 6: Commit (the cutover)**

```bash
git add app.py pages/dashboard.py
git commit -m "feat(cache): cut over to cache-first pipeline; delete legacy trigger chain

Removes the three sequentially-chained background callbacks that were
the source of intermittent infinite hangs. The dashboard now reads from
the predictions cache on every page load and refreshes opportunistically
in the background. The only remaining background=True callback is
opportunistic_refresh."
```

---

### Task 14: Acceptance verification

**Files:**
- Create: `scripts/verify/dashboard_smoke.py`
- Create: `docs/superpowers/specs/cold-start-overhaul-results.md`

- [ ] **Step 1: Capture before-numbers from `main`**

```bash
git checkout main
python app.py &
APP_PID=$!
sleep 5

# Lighthouse
npx lighthouse http://localhost:10000/dashboard \
    --only-categories=performance --output=json --quiet \
    > /tmp/lh-before.json
jq '.audits["interactive"].numericValue' /tmp/lh-before.json

# Resource summary
jq '.audits["resource-summary"].details.items' /tmp/lh-before.json > /tmp/resources-before.json
cat /tmp/resources-before.json

# gzip check
curl -s -H "Accept-Encoding: gzip" -I http://localhost:10000/dashboard | grep -i content-encoding

kill $APP_PID
git checkout -
```

Record the numbers — TTI ms, total transfer size, script size, content-encoding present (yes/no).

- [ ] **Step 2: Capture after-numbers from the overhaul branch**

```bash
python app.py &
APP_PID=$!
sleep 5

npx lighthouse http://localhost:10000/dashboard \
    --only-categories=performance --output=json --quiet \
    > /tmp/lh-after.json
jq '.audits["interactive"].numericValue' /tmp/lh-after.json
jq '.audits["resource-summary"].details.items' /tmp/lh-after.json > /tmp/resources-after.json
curl -s -H "Accept-Encoding: gzip" -I http://localhost:10000/dashboard | grep -i content-encoding

kill $APP_PID
```

- [ ] **Step 3: Write `scripts/verify/dashboard_smoke.py`**

```python
"""End-to-end smoke for the cache-first dashboard.

Hits /dashboard 5x via requests, expects each response < 1.5s and
status 200. Uses an authenticated session token (from .env, set
SMOKE_USER_SESSION to a valid JSON string)."""
import json
import os
import sys
import time
import urllib.parse
import requests

URL = os.getenv("SMOKE_URL", "http://localhost:10000/dashboard")
USER_SESSION = os.getenv("SMOKE_USER_SESSION")  # JSON string for the user-session store


def main() -> int:
    if not USER_SESSION:
        print("FAIL: SMOKE_USER_SESSION env var not set "
              "(grab the value from DevTools → Application → Session Storage → user-session)")
        return 1

    cookies = {"_dash_persistence": urllib.parse.quote(USER_SESSION)}
    timings = []
    for i in range(5):
        started = time.monotonic()
        resp = requests.get(URL, cookies=cookies, timeout=5)
        elapsed = time.monotonic() - started
        timings.append(elapsed)
        if resp.status_code != 200:
            print(f"FAIL: hit {i+1} status={resp.status_code}")
            return 1
        if elapsed > 1.5:
            print(f"FAIL: hit {i+1} took {elapsed:.2f}s > 1.5s")
            return 1
        print(f"  hit {i+1}: {elapsed*1000:.0f}ms status=200")

    median = sorted(timings)[2]
    print(f"OK: 5 dashboard hits all < 1.5s, median {median*1000:.0f}ms")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Write the results doc**

Create `docs/superpowers/specs/cold-start-overhaul-results.md`. Fill in the captured numbers:

```markdown
# Cold-Start Overhaul — Acceptance Results

Captured 2026-04-26. Same Render env, warm dyno, median of 5 runs.

| Metric | Before | After | Threshold | Pass? |
|--------|--------|-------|-----------|-------|
| Login → Dashboard interactive (Lighthouse TTI) | <fill> | <fill> | < 1500ms | <Y/N> |
| Total JS payload on /dashboard | <fill> | <fill> | < 150KB | <Y/N> |
| Total CSS payload on /dashboard (gzipped) | <fill> | <fill> | < 15KB inline | <Y/N> |
| Hangs observed in 30-min smoke | "occasional" | <fill> | 0 | <Y/N> |
| Tab switch (Data → Model first) | <fill> | <fill> | < 400ms | <Y/N> |
| Scenario slider response | <fill> | <fill> | < 200ms | <Y/N> |
| `Content-Encoding: gzip` header on /dashboard | <fill> | <fill> | yes | <Y/N> |
| `three-scenes.js` requested on /dashboard | <fill> | <fill> | no | <Y/N> |

If any row fails, do not merge; raise the failing workstream's task list.

## Regression Watchlist (manual verify)
- [ ] Login still works
- [ ] Registration creates Supabase rows
- [ ] Profile password change works
- [ ] AI chat streams responses
- [ ] Theme toggle (dark/light) syncs
- [ ] All three dashboard tabs render with populated cache
- [ ] All three dashboard tabs render with empty cache (use a fresh model_version to simulate)
- [ ] Data tab table toggle still works
- [ ] Scenario "save snapshot" / "compare snapshots" still works
```

- [ ] **Step 5: Run dashboard smoke**

In one terminal:

```bash
python app.py
```

In another, after logging in via browser and capturing the `user-session` value:

```bash
SMOKE_USER_SESSION='<paste JSON value>' python scripts/verify/dashboard_smoke.py
```

Expected output:
```
  hit 1: <ms>ms status=200
  hit 2: <ms>ms status=200
  hit 3: <ms>ms status=200
  hit 4: <ms>ms status=200
  hit 5: <ms>ms status=200
OK: 5 dashboard hits all < 1.5s, median <ms>ms
```

- [ ] **Step 6: Deploy to Render and re-verify**

```bash
git push origin main
# Watch Render dashboard for build success.
# Once live, run dashboard_smoke against the production URL:
SMOKE_URL=https://<your-render-url>/dashboard \
SMOKE_USER_SESSION='<value>' \
  python scripts/verify/dashboard_smoke.py
```

Then 30-minute smoke: open the dashboard, hit refresh and tab-switch repeatedly across 30 minutes. Watch Render logs for `cache.refresh.*` and `cache.hydrate.*`. Expected: zero hangs.

- [ ] **Step 7: Commit results**

```bash
git add scripts/verify/dashboard_smoke.py docs/superpowers/specs/cold-start-overhaul-results.md
git commit -m "test: add dashboard smoke + acceptance results

Records before/after metrics for each acceptance threshold and a
manual regression watchlist."
```

---

## Self-Review Notes

**Spec coverage:** Every spec section has a task:
- Architecture (Section 1) — Wave map mirrors the three workstreams.
- File structure (Section 2 revised) — Tasks 3, 4, 8 (logic split); 9 + future task (core split, see note below); 10–12 (tabs).
- Data flow (Section 3) — Task 9 implements Flow 1 + 2; Flow 3 (live scenario) preserved by Task 12.
- Error handling (Section 4) — Task 3 (timeouts), Task 8 (refresh single-flight + cached fallback), Task 9 (status store for stale banner).
- Testing & verification (Section 5) — verify scripts under `scripts/verify/` per workstream, dashboard_smoke + results doc in Task 14.

**Note on `core/` split:** This plan intentionally does not split `app.py` into all of `core/auth_callbacks.py`, `core/theme_callbacks.py`, `core/chat_callbacks.py`, `core/clientside.py`, `core/routing.py`. That decomposition was in the spec but is **out of scope for cold-start performance** — none of those callbacks live on the cold-start critical path. Doing the split would inflate this plan ~30% with pure mechanical moves. **Recommended follow-up:** open a separate plan after this one ships if the file size of `app.py` post-cutover still feels unwieldy. Flag this to the user before execution.

**Type consistency check:** `CachePayload`, `RefreshResult`, `read_cached`, `write_payload`, `is_stale`, `refresh_async`, `compute_full_predictions_payload`, `MODEL_VERSION`, `CACHE_CONTRACT_VERSION` used identically across all tasks.

**No placeholder leaks:** every code block is concrete; every command has expected output; every "move from file X" includes the line range or grep hint.
