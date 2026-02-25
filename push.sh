#!/bin/bash

# Default commit message if none is provided
MESSAGE=${1:-"Update site: $(date +'%Y-%m-%d %H:%M:%S')"}

echo "--- Starting Auto-Push ---"

# 1. Add all changes
git add .

# 2. Commit with message
git commit -m "$MESSAGE"

# 3. Push to GitHub
echo "Pushing to GitHub (Render will auto-deploy once this finishes)..."
git push origin main

if [ $? -eq 0 ]; then
    echo "--- Success! Changes are live on GitHub. ---"
    echo "Check your Render dashboard to see the deployment progress."
else
    echo "--- Error: Push failed. ---"
    exit 1
fi
