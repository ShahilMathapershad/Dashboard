"""Verify the refresh lock prevents concurrent refreshes."""
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from logic.predictions_cache.refresh import refresh_async


def main() -> int:
    results = []

    def worker():
        results.append(refresh_async())

    t1 = threading.Thread(target=worker)
    t2 = threading.Thread(target=worker)
    t1.start()
    time.sleep(0.05)
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

    t1.join(timeout=180)

    print("OK: concurrent refresh skipped within bound")
    return 0


if __name__ == "__main__":
    sys.exit(main())
