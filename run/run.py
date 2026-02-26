import os
import sys
import webbrowser
import subprocess
import threading
import time

# Get the absolute path of the project root (parent of the 'run' folder)
# This allows us to find the root folder correctly from any starting directory.
RUN_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(RUN_DIR)

# Change the current working directory to the project root
# This ensures Dash finds 'assets', 'pages', and 'data' correctly
os.chdir(PROJECT_ROOT)

# Add the project root to sys.path so we can import 'app' from 'app.py'
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

try:
    from app import app
    from logic.git_sync import sync_push
except ImportError as e:
    print(f"Error: Could not import 'app' from 'app.py'. Ensure you are running this from the project structure.")
    print(f"Details: {e}")
    sys.exit(1)

def open_browser():
    """Opens the web browser after a short delay to allow the server to start."""
    # A short delay ensures the Dash server is up and listening
    time.sleep(1.5)
    url = "http://127.0.0.1:8050"
    print(f"Automatically opening {url} in your browser...")
    webbrowser.open(url)

if __name__ == "__main__":
    # Start the initial autopush/sync to ensure remote is up to date
    sync_push("Initial sync from local run")
    
    # Start the browser-opening thread in the background
    threading.Thread(target=open_browser, daemon=True).start()
    
    # Run the Dash application
    # We use debug=False here to prevent the Dash reloader from starting the browser thread twice
    print("Starting the Dash application...")
    app.run(host='127.0.0.1', port=8050, debug=False)
