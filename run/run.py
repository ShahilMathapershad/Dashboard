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
except ImportError as e:
    print(f"Error: Could not import 'app' from 'app.py'. Ensure you are running this from the project structure.")
    print(f"Details: {e}")
    sys.exit(1)

def run_autopull():
    """Periodically pulls changes from GitHub to stay updated with remote registrations."""
    print("--- Autopull from GitHub started in background ---")
    while True:
        try:
            if os.path.exists("./push.sh"):
                # We can use git pull directly or a minimal script
                # push.sh does a pull --rebase before pushing, but we just want to pull here
                subprocess.run(["git", "pull", "origin", "main", "--rebase"], check=False)
            time.sleep(60)  # Pull every minute
        except Exception as e:
            print(f"--- Autopull failed: {e} ---")
            time.sleep(60)

def run_autopush():
    """Runs the push.sh script to update the site on GitHub/Render."""
    print("--- Autopush to GitHub/Render started in background ---")
    try:
        # Check if the push script exists before running
        if os.path.exists("./push.sh"):
            # We explicitly use /bin/bash to run the script
            subprocess.run(["/bin/bash", "./push.sh", "Initial sync from local run"], check=False)
        else:
            print("--- Autopush skipped: push.sh not found ---")
    except Exception as e:
        print(f"--- Autopush failed: {e} ---")

def open_browser():
    """Opens the web browser after a short delay to allow the server to start."""
    # A short delay ensures the Dash server is up and listening
    time.sleep(1.5)
    url = "http://127.0.0.1:8050"
    print(f"Automatically opening {url} in your browser...")
    webbrowser.open(url)

if __name__ == "__main__":
    # Start the autopush in a background thread so the app starts immediately
    threading.Thread(target=run_autopush, daemon=True).start()
    
    # We don't need to start run_autopull() here because it's now started in app.py 
    # when the server starts, but we keep it here just in case run.py is run directly.
    # However, to avoid double threads, we can check if it's already running or let it be.
    # If app.py is imported, it starts the thread. run.py imports app.
    
    # Start the browser-opening thread in the background
    threading.Thread(target=open_browser, daemon=True).start()
    
    # Run the Dash application
    # We use debug=False here to prevent the Dash reloader from starting the browser thread twice
    print("Starting the Dash application...")
    app.run(host='127.0.0.1', port=8050, debug=False)
