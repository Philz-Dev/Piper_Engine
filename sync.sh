#!/bin/bash

# 1. Capture the commit message from the first argument
MESSAGE=$1

# 2. Safety Check: Ensure a message was provided
if [ -z "$MESSAGE" ]; then
  echo "❌ Error: You must provide a commit message."
  echo "Usage: ./sync.sh 'fixed database connection bug'"
  exit 1
fi

# 3. Execution Phase
echo "Step 1: ➕ Adding changes..."
git add .

echo "Step 2: 📝 Committing with message: '$MESSAGE'..."
git commit -m "$MESSAGE"

echo "Step 3: 🚀 Pushing to GitHub (main branch)..."
git push origin main

echo "✅ Sync Complete! Code is live on GitHub."