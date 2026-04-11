import os
import sys
import webbrowser
import threading
import time
import urllib.request
import urllib.error

# Get the absolute path of the project root (parent of the 'run' folder)
# This allows us to find the root folder correctly from any starting directory.
RUN_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(RUN_DIR)
#hello
# Change the current working directory to the project root
# This ensures Dash finds 'assets', 'pages', and 'data' correctly
os.chdir(PROJECT_ROOT)

# Add the project root to sys.path so we can import 'app' from 'app.py'
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

try:
    from app import app
except ImportError as e:
    print(f"Error: Could not import 'app' from 'app.py'. Ensure you are running this from the project structure.")
    print(f"Details: {e}")
    sys.exit(1)

def open_browser():
    """Opens the web browser after a short delay to allow the server to start."""
    url = "http://127.0.0.1:8050"
    deadline = time.time() + 15

    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1):
                print(f"Automatically opening {url} in your browser...")
                webbrowser.open_new(url)
                returnremo
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            time.sleep(0.5)

    print(f"Server did not become reachable in time. Open {url} manually if needed.")

if __name__ == "__main__":
    # Start the browser-opening thread in the background
    threading.Thread(target=open_browser, daemon=True).start()
    
    # Run the Dash application
    # We use debug=False here to prevent the Dash reloader from starting the browser thread twice
    print("Starting the Dash application...")
    app.run(host='127.0.0.1', port=8050, debug=False)
