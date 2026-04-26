"""Prove FRED + World Bank fetches respect their hard timeouts.

This is the single most important verification: it monkeypatches the
HTTP layer and asserts our wrappers either pass a `timeout=` to
requests.get OR enforce a bounded elapsed time via ThreadPoolExecutor.
If this passes, hangs on the request path are gone.

World Bank
----------
We can't test the real `requests.get(timeout=20)` by mocking
requests.get itself (the mock replaces the timeout enforcement). So we
verify two things instead:
  1. The wrapper actually passes a numeric `timeout` kwarg to
     requests.get (static guarantee that pandas/urllib won't be handed
     a URL with no timeout — the original hang vector).
  2. When requests.get raises requests.Timeout, the wrapper swallows it
     and returns an empty Series instead of propagating.

FRED
----
The legacy fred.get_series() call is wrapped in a ThreadPoolExecutor
with a 15s timeout. We monkeypatch get_series to sleep 60s and verify
the call returns within ~17s with an empty DataFrame.
"""
from __future__ import annotations
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import requests

# Make `logic.*` importable when running from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

EXPECTED_FRED_BOUND_PER_SERIES = 17  # 15s timeout + ~2s thread overhead
EXPECTED_WB_BOUND = 22               # belt-and-braces if anything goes wrong


def _check_worldbank_passes_timeout_kwarg() -> int:
    """Confirm requests.get is invoked with a numeric timeout kwarg."""
    from logic.data import worldbank_source

    captured_kwargs: list[dict] = []

    def _stub_get(*args, **kwargs):
        captured_kwargs.append(kwargs)
        # Return a response-like object so the page-fetch path errors out
        # gracefully via raise_for_status, terminating the call.
        m = MagicMock()
        m.raise_for_status.side_effect = requests.RequestException("stubbed")
        return m

    with patch("logic.data.worldbank_source.requests.get", side_effect=_stub_get):
        result = worldbank_source.fetch_world_bank_gold_data()

    if not captured_kwargs:
        print("FAIL: requests.get was never called by worldbank fetch")
        return 1

    for i, kw in enumerate(captured_kwargs):
        timeout = kw.get("timeout")
        if not isinstance(timeout, (int, float)) or timeout <= 0 or timeout > 30:
            print(f"FAIL: worldbank requests.get call #{i} had timeout={timeout!r} (expected 1..30)")
            return 1

    if not result.empty:
        print("FAIL: worldbank fetch returned data despite stub failure")
        return 1

    print(f"OK: worldbank requests.get always passes timeout kwarg "
          f"(saw {len(captured_kwargs)} call(s), all bounded), and errors return empty Series")
    return 0


def _check_worldbank_swallows_timeout() -> int:
    """When requests.get raises Timeout, the fetch should return empty quickly."""
    from logic.data import worldbank_source

    started = time.monotonic()
    with patch("logic.data.worldbank_source.requests.get",
               side_effect=requests.Timeout("simulated network hang")):
        result = worldbank_source.fetch_world_bank_gold_data()
    elapsed = time.monotonic() - started

    if elapsed > EXPECTED_WB_BOUND:
        print(f"FAIL: worldbank fetch took {elapsed:.1f}s > {EXPECTED_WB_BOUND}s bound")
        return 1
    if not result.empty:
        print("FAIL: worldbank fetch returned data despite Timeout stub")
        return 1
    print(f"OK: worldbank fetch swallows requests.Timeout in {elapsed:.2f}s and returns empty Series")
    return 0


def _slow_fred_series(*_a, **_kw):
    time.sleep(60)


def _check_fred() -> int:
    from logic.data import fred_source

    if not os.getenv("FRED_API_KEY"):
        os.environ["FRED_API_KEY"] = "verify-stub-key"

    # Single-series dict so the bound is ~17s rather than 8 * 17s.
    one_series = {"VIX": "VIXCLS"}

    started = time.monotonic()
    with patch.object(fred_source.Fred, "get_series", side_effect=_slow_fred_series):
        df = fred_source.fetch_fred_data(series_dict=one_series, api_key="verify-stub-key")
    elapsed = time.monotonic() - started

    upper = EXPECTED_FRED_BOUND_PER_SERIES + 5  # +5s for thread teardown + 0.5s rate-limit sleep
    if elapsed > upper:
        print(f"FAIL: fred fetch took {elapsed:.1f}s > {upper}s bound for 1 series")
        return 1
    if not df.empty:
        print("FAIL: fred fetch returned data despite stub")
        return 1
    print(f"OK: fred ThreadPoolExecutor timeout fired in {elapsed:.1f}s (1-series stub, empty DataFrame)")
    return 0


def main() -> int:
    rc = _check_worldbank_passes_timeout_kwarg()
    if rc != 0:
        return rc
    rc = _check_worldbank_swallows_timeout()
    if rc != 0:
        return rc
    rc = _check_fred()
    if rc != 0:
        return rc
    return 0


if __name__ == "__main__":
    sys.exit(main())
