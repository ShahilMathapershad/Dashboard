import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

# SUPABASE_URL and SUPABASE_KEY are expected in environment variables
# Fallbacks for local development if needed, though they should be in .env or system env
url: str = os.environ.get("SUPABASE_URL", "https://nugwzktxrbpaynkwussb.supabase.co")
key: str = os.environ.get("SUPABASE_KEY", os.environ.get("KEY", "sb_secret_8swIxMG-TASuT3XT4i3zGA_kIpOuiHk"))

if not url or not key:
    print("--- Warning: SUPABASE_URL or SUPABASE_KEY not found in environment variables ---")
else:
    # Print partially for debugging on Render
    masked_key = key[:10] + "..." + key[-5:] if key else "None"
    print(f"--- Supabase Client: Initializing with URL {url} and Key {masked_key} ---")

supabase: Client = create_client(url, key) if url and key else None
