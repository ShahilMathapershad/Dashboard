import logging
import os
import threading
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Use a lazy getter to avoid overhead on every import and ensure process-safety
_client = None
_client_lock = threading.Lock()


def get_supabase():
    """
    Returns a Supabase client, initializing it lazily on first call.
    Lock-guarded so concurrent threads (gunicorn gthread workers) don't
    each create and leak a duplicate client.
    """
    global _client
    if _client is not None:
        return _client

    with _client_lock:
        if _client is not None:
            return _client

        load_dotenv()

        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_KEY")

        if not url or not key:
            logger.warning("SUPABASE_URL or SUPABASE_KEY not configured")
            return None

        from supabase import create_client

        logger.info("Supabase client initializing for url=%s", url)
        _client = create_client(url, key)
        return _client
