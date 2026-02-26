import os
import git
import threading
import time
from dotenv import load_dotenv

load_dotenv()

# Global lock to prevent concurrent Git operations in background threads
git_lock = threading.Lock()

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
        return

    try:
        # Look for 'origin', or fall back to the first available remote
        remote = None
        try:
            remote = repo.remote(name='origin')
        except:
            if repo.remotes:
                remote = repo.remotes[0]
        
        if not remote:
            print("--- GitSync Error: No remotes found to configure ---")
            return

        url = remote.url
        
        # Only update if it's a GitHub URL and doesn't already have a token
        if "github.com" in url and "https://" in url and "@" not in url:
            new_url = url.replace("https://", f"https://{token}@")
            remote.set_url(new_url)
            print(f"--- GitSync: Remote URL updated with GITHUB_TOKEN ---")
        elif "@github.com" in url:
            # print("--- GitSync: Remote URL already contains a token or is SSH ---")
            pass
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
            repo.git.fetch('--unshallow', '--update-head-ok')
    except Exception as e:
        print(f"--- GitSync Warning: Could not unshallow repo: {e} ---")

def sync_push(message):
    """Performs a pull-rebase and then a push."""
    def _run_push():
        with git_lock:
            repo = get_repo()
            if not repo: return
            
            configure_git_remote(repo)
            configure_git_user(repo)
            handle_shallow_repo(repo)
            
            branch = get_branch(repo)
            print(f"--- GitSync: [PUSH] Using branch '{branch}' ---")
            
            try:
                # 1. Add changes
                repo.git.add(A=True)
                
                # 2. Check if there are changes to commit
                if repo.is_dirty(index=True, working_tree=True, untracked_files=True):
                    repo.index.commit(message)
                    print(f"--- GitSync: [PUSH] Committed: {message} ---")
                else:
                    print("--- GitSync: [PUSH] No changes to commit ---")

                # Get remote name
                remote_name = 'origin'
                try:
                    repo.remote(name='origin')
                except:
                    if repo.remotes:
                        remote_name = repo.remotes[0].name

                # 3. Pull latest (rebase)
                print(f"--- GitSync: [PUSH] Pulling latest changes from {branch} before push ---")
                repo.git.pull(remote_name, branch, rebase=True)

                # 4. Push
                print(f"--- GitSync: [PUSH] Pushing to GitHub ---")
                repo.git.push(remote_name, branch)
                print("--- GitSync: [PUSH] Push successful! ---")
            except Exception as e:
                print(f"--- GitSync Error during push: {e} ---")

    # Run in background to not block the app
    threading.Thread(target=_run_push, daemon=True).start()

def sync_pull_periodic(interval=60):
    """Periodically pulls changes in a background thread."""
    def _run_pull():
        # Short initial delay to allow app to start
        time.sleep(5)
        print(f"--- GitSync: Background pull started (interval: {interval}s) ---")
        while True:
            with git_lock:
                repo = get_repo()
                if repo:
                    try:
                        configure_git_remote(repo)
                        configure_git_user(repo)
                        handle_shallow_repo(repo)
                        
                        # NEW: Automatically commit changes so pull doesn't fail
                        if repo.is_dirty(untracked_files=True):
                            repo.git.add(A=True)
                            repo.index.commit("Render: Syncing local changes before pull")
                            print("--- GitSync: [PULL] Committed local changes before pulling ---")

                        branch = get_branch(repo)
                        
                        # Get remote name
                        remote_name = 'origin'
                        try:
                            repo.remote(name='origin')
                        except:
                            if repo.remotes:
                                remote_name = repo.remotes[0].name
                        
                        repo.git.pull(remote_name, branch, rebase=True)
                    except Exception as e:
                        # Log errors that are not just "already up to date"
                        err_msg = str(e).lower()
                        if "already up to date" not in err_msg:
                            print(f"--- GitSync [PULL] Error: {e} ---")
            time.sleep(interval)

    # Enable periodic pull on all environments (Render and Local)
    # This ensures a two-way sync is always active.
    threading.Thread(target=_run_pull, daemon=True).start()
