"""Verify the predictions table exists and is empty/queryable."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

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
