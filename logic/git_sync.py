import os
import git
import threading
import time
from dotenv import load_dotenv

load_dotenv()

def get_repo():
    """Initializes and returns the Git repository instance."""
    try:
        repo = git.Repo(os.getcwd())
        return repo
    except Exception as e:
        print(f"--- GitSync Error: Could not initialize repo: {e} ---")
        return None

def configure_git_remote(repo):
    """Updates the remote URL with GITHUB_TOKEN if available (for Render)."""
    token = os.environ.get('GITHUB_TOKEN')
    if not token:
        return # Use default remote if no token

    try:
        # Get the current remote URL (origin)
        origin = repo.remote(name='origin')
        url = origin.url
        
        # Only update if it's a GitHub URL and doesn't already have a token
        if "github.com" in url and "https://" in url and "@" not in url:
            new_url = url.replace("https://", f"https://{token}@")
            origin.set_url(new_url)
            print(f"--- GitSync: Remote URL updated with GITHUB_TOKEN ---")
    except Exception as e:
        print(f"--- GitSync Error: Remote configuration failed: {e} ---")

def configure_git_user(repo):
    """Sets git user configuration if not already set."""
    try:
        with repo.config_writer() as cw:
            if not cw.get_value('user', 'email', None):
                cw.set_value('user', 'email', 'render-bot@example.com')
            if not cw.get_value('user', 'name', None):
                cw.set_value('user', 'name', 'Render Bot')
    except Exception as e:
        print(f"--- GitSync Error: User configuration failed: {e} ---")

def sync_push(message):
    """Performs a pull-rebase and then a push."""
    def _run_push():
        repo = get_repo()
        if not repo: return
        
        configure_git_remote(repo)
        configure_git_user(repo)
        
        try:
            # 1. Add changes
            repo.git.add('.')
            
            # 2. Check if there are changes to commit
            if repo.is_dirty(untracked_files=True):
                repo.index.commit(message)
                print(f"--- GitSync: Committed: {message} ---")
            else:
                print("--- GitSync: No changes to commit ---")
                return

            # 3. Pull latest (rebase)
            print("--- GitSync: Pulling latest changes ---")
            repo.git.pull('origin', 'main', rebase=True)

            # 4. Push
            print("--- GitSync: Pushing to GitHub ---")
            repo.git.push('origin', 'main')
            print("--- GitSync: Push successful! ---")
        except Exception as e:
            print(f"--- GitSync Error during push: {e} ---")

    # Run in background to not block the app
    threading.Thread(target=_run_push, daemon=True).start()

def sync_pull_periodic(interval=60):
    """Periodically pulls changes in a background thread."""
    def _run_pull():
        print(f"--- GitSync: Background pull started (interval: {interval}s) ---")
        while True:
            repo = get_repo()
            if repo:
                try:
                    # Only pull if not on Render OR if explicitly requested
                    # Render auto-deploys on push, so pull is mainly for local environment
                    # to get changes made on Render.
                    repo.git.pull('origin', 'main', rebase=True)
                    # print("--- GitSync: Periodic pull successful ---")
                except Exception as e:
                    # Don't print every time to avoid log spam if it fails (e.g. no internet)
                    pass
            time.sleep(interval)

    # Only start pull thread if not on Render (unless RUN_AUTOPULL is set)
    if os.environ.get('RUN_AUTOPULL') == 'true' or not os.environ.get('RENDER'):
        threading.Thread(target=_run_pull, daemon=True).start()
