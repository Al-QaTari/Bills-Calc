#!/bin/bash
# =============================================================================
# Treasury Bills Calculator - Docker Entrypoint
# حاسبة أذون الخزانة - نقطة دخول Docker
# =============================================================================

# Ensure script stops if any command fails
set -e

# This part of the script runs as root
echo "🔧 Fixing permissions for app and cache directories..."
# Create cache directory if it doesn't exist to ensure it exists before changing ownership
mkdir -p "$PLAYWRIGHT_BROWSERS_PATH"
chown -R appuser:appuser /home/appuser/app "$PLAYWRIGHT_BROWSERS_PATH"

echo "✅ Permissions fixed. Switching to user 'appuser' to run the command..."
echo "------------------------------------------------------------"

# Use gosu to switch to appuser
# Then use bash -c to execute a series of commands
# "$@" at the end passes the original command from 'docker run' to the script
exec gosu appuser bash -c '
  set -e
  echo "--> Now running as user: $(whoami)"
  
  echo "--> Installing Playwright browser at runtime (dependencies are in packages.txt)..."
  python -m playwright install chromium
  echo "--> Playwright browser installation complete."
  echo "------------------------------------------------------------"
  
  echo "🚀 Executing main command: $@"
  exec "$@"
' -- "$@"
