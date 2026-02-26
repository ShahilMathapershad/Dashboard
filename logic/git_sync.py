import os
import git
import threading
import time
from dotenv import load_dotenv

load_dotenv()

def get_repo():
    """Initializes and returns the Git repository instance, searching upwards if necessary."""
    try:
        # Start searching from the current directory or the directory of this file
        search_path = os.getcwd()
        repo = git.Repo(search_path, search_parent_directories=True)
        return repo
    except Exception as e:
        print(f"--- GitSync Error: Could not initialize repo: {e} ---")
        return None

def configure_git_remote(repo):
    """Updates the remote URL with GITHUB_TOKEN if available (for Render)."""
    token = os.environ.get('GITHUB_TOKEN')
    if not token:
        print("--- GitSync: No GITHUB_TOKEN found in environment ---")
        return

    try:
        # Get the current remote URL (origin)
        origin = repo.remote(name='origin')
        url = origin.url
        
        # Only update if it's a GitHub URL and doesn't already have a token
        if "github.com" in url and "https://" in url and "@" not in url:
            new_url = url.replace("https://", f"https://{token}@")
            origin.set_url(new_url)
            print(f"--- GitSync: Remote URL updated with GITHUB_TOKEN ---")
        elif "@github.com" in url:
            print("--- GitSync: Remote URL already contains a token or is SSH ---")
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

def get_branch(repo):
    """Detects the current branch name."""
    # 1. Try environment variable (Render sets this)
    branch = os.environ.get('RENDER_GIT_BRANCH')
    if branch:
        return branch
    
    # 2. Try to get from repo
    try:
        return repo.active_branch.name
    except:
        # Detached HEAD
        pass
    
    # 3. Fallback to common names
    for b in ['main', 'master']:
        try:
            repo.git.rev_parse('--verify', b)
            return b
        except:
            continue
            
    return 'main'

def handle_shallow_repo(repo):
    """Checks if the repo is shallow and tries to unshallow it if on Render."""
    try:
        if os.path.exists(os.path.join(repo.git_dir, 'shallow')):
            print("--- GitSync: Shallow repository detected. Attempting to fetch unshallow... ---")
            repo.git.fetch('--unshallow')
    except Exception as e:
        print(f"--- GitSync Warning: Could not unshallow repo: {e} ---")

def sync_push(message):
    """Performs a pull-rebase and then a push."""
    def _run_push():
        repo = get_repo()
        if not repo: return
        
        configure_git_remote(repo)
        configure_git_user(repo)
        handle_shallow_repo(repo)
        
        branch = get_branch(repo)
        print(f"--- GitSync: Using branch '{branch}' ---")
        
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
            print(f"--- GitSync: Pulling latest changes from {branch} ---")
            repo.git.pull('origin', branch, rebase=True)

            # 4. Push
            print(f"--- GitSync: Pushing to GitHub ---")
            repo.git.push('origin', branch)
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
                    handle_shallow_repo(repo)
                    branch = get_branch(repo)
                    repo.git.pull('origin', branch, rebase=True)
                except Exception as e:
                    pass
            time.sleep(interval)

    # Only start pull thread if not on Render (unless RUN_AUTOPULL is set)
    if os.environ.get('RUN_AUTOPULL') == 'true' or not os.environ.get('RENDER'):
        threading.Thread(target=_run_pull, daemon=True).start()
