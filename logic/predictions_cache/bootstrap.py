"""One-time eager refresh for empty cache. Run via:
    python -m logic.predictions_cache.bootstrap
"""
from __future__ import annotations
import logging
import sys

from dotenv import load_dotenv
load_dotenv()

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
