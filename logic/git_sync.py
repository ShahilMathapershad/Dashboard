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
    repo_url = os.environ.get('GITHUB_REPO_URL')
    
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
            if repo_url:
                print(f"--- GitSync: Creating 'origin' remote using GITHUB_REPO_URL ---")
                repo.create_remote('origin', repo_url)
                remote = repo.remote(name='origin')
            else:
                print("--- GitSync Error: No remotes found to configure. Set GITHUB_REPO_URL if this persists. ---")
                return

        url = remote.url
        
        # Only update if it's a GitHub URL and doesn't already have a token
        if "github.com" in url and "https://" in url and "@" not in url:
            new_url = url.replace("https://", f"https://{token}@")
            remote.set_url(new_url)
            print(f"--- GitSync: Remote URL updated with GITHUB_TOKEN (using {remote.name}) ---")
        elif "@github.com" in url:
            # Refresh token if it's different
            parts = url.split('@')
            current_token = parts[0].replace("https://", "")
            if current_token != token:
                new_url = f"https://{token}@{parts[1]}"
                remote.set_url(new_url)
                print(f"--- GitSync: Remote URL refreshed with new GITHUB_TOKEN ---")
        else:
            pass
    except Exception as e:
        print(f"--- GitSync Error: Remote configuration failed: {e} ---")

def configure_git_user(repo):
    """Sets git user configuration if not already set."""
    try:
        # Check if user.email and user.name are set globally or locally
        try:
            email = repo.git.config('--get', 'user.email')
            name = repo.git.config('--get', 'user.name')
        except:
            email = None
            name = None

        if not email or not name:
            with repo.config_writer() as cw:
                cw.set_value('user', 'email', 'render-bot@example.com')
                cw.set_value('user', 'name', 'Render Bot')
            print("--- GitSync: User configuration updated ---")
    except Exception as e:
        # Fallback if config_writer fails (e.g. read-only filesystem or missing config)
        try:
            repo.git.config('user.email', 'render-bot@example.com')
            repo.git.config('user.name', 'Render Bot')
            print("--- GitSync: User configuration updated via CLI fallback ---")
        except Exception as e2:
            print(f"--- GitSync Error: User configuration failed completely: {e2} ---")

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

                # Re-configure remote right before push to ensure token is fresh and remote is correct
                configure_git_remote(repo)

                # Get remote name and URL
                remote_name = 'origin'
                remote_url = os.environ.get('GITHUB_REPO_URL')
                remote_obj = None
                
                try:
                    remote_obj = repo.remote(name='origin')
                    remote_name = 'origin'
                    remote_url = remote_obj.url
                except:
                    if repo.remotes:
                        remote_obj = repo.remotes[0]
                        remote_name = remote_obj.name
                        remote_url = remote_obj.url
                
                # Explicitly use the tokenized URL if we have a token
                token = os.environ.get('GITHUB_TOKEN')
                push_target = remote_name
                
                if token and remote_url and "github.com" in remote_url:
                    # Construct explicit URL to bypass any remote config issues
                    base_url = remote_url.split('@')[-1] if '@' in remote_url else remote_url.replace("https://", "")
                    push_target = f"https://{token}@{base_url}"
                    print(f"--- GitSync: [PUSH] Using explicit tokenized URL for push ---")
                elif not remote_obj and not remote_url:
                    print("--- GitSync Error: [PUSH] No remote found and GITHUB_REPO_URL not set ---")
                    return

                # 3. Pull latest (rebase)
                print(f"--- GitSync: [PUSH] Pulling latest changes from {branch} before push ---")
                try:
                    repo.git.pull(push_target if push_target.startswith('http') else remote_name, branch, rebase=True)
                except Exception as pull_e:
                    print(f"--- GitSync [PUSH] Pull warning: {pull_e} ---")

                # 4. Push
                print(f"--- GitSync: [PUSH] Pushing to {remote_name} {branch} ---")
                repo.git.push(push_target, branch)
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
                        
                        # Get remote name and URL
                        remote_name = 'origin'
                        remote_url = os.environ.get('GITHUB_REPO_URL')
                        remote_obj = None
                        
                        try:
                            remote_obj = repo.remote(name='origin')
                            remote_name = 'origin'
                            remote_url = remote_obj.url
                        except:
                            if repo.remotes:
                                remote_obj = repo.remotes[0]
                                remote_name = remote_obj.name
                                remote_url = remote_obj.url
                        
                        # Use explicit URL for pull as well
                        token = os.environ.get('GITHUB_TOKEN')
                        pull_target = remote_name
                        
                        if token and remote_url and "github.com" in remote_url:
                            base_url = remote_url.split('@')[-1] if '@' in remote_url else remote_url.replace("https://", "")
                            pull_target = f"https://{token}@{base_url}"
                        elif not remote_obj and not remote_url:
                            # If no remote and no GITHUB_REPO_URL, we can't pull
                            # But maybe we don't need to pull if we just started
                            time.sleep(interval)
                            continue

                        repo.git.pull(pull_target, branch, rebase=True)
                    except Exception as e:
                        # Log errors that are not just "already up to date"
                        err_msg = str(e).lower()
                        if "already up to date" not in err_msg:
                            print(f"--- GitSync [PULL] Error: {e} ---")
            time.sleep(interval)

    # Enable periodic pull on all environments (Render and Local)
    # This ensures a two-way sync is always active.
    threading.Thread(target=_run_pull, daemon=True).start()
