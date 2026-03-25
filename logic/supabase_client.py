import os
from dotenv import load_dotenv

# Use a lazy getter to avoid overhead on every import and ensure process-safety
_client = None

def get_supabase():
    """
    Returns a Supabase client, initializing it lazily on first call.
    This avoids initial overhead during module imports and ensures
    that the client is created in the correct process (important for background workers).
    """
    global _client
    if _client is not None:
        return _client

    load_dotenv()
    
    url: str = os.environ.get("SUPABASE_URL")
    key: str = os.environ.get("SUPABASE_KEY")

    if not url or not key:
        print("--- Warning: SUPABASE_URL or SUPABASE_KEY not found ---")
        return None
    
    from supabase import create_client
    
    # Print partially for debugging on Render
    masked_key = key[:10] + "..." + key[-5:] if key else "None"
    print(f"--- Supabase Client: Initializing with URL {url} and Key {masked_key} ---")
    
    _client = create_client(url, key)
    return _client
