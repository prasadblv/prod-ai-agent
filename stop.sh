#!/usr/bin/env bash

# Pipe Fail 
set -euo pipefail

# Image Name
CONTAINER_NAME="prod-ai-agent"

# Kill all uvicorn process. Send standard error to /dev/null(black hole)
pkill -f "uvicorn app:app" 2>/dev/null || true

# Stop container.
docker stop "$CONTAINER_NAME" >/dev/null 2>&1 || true

# Remove container.
docker rm "$CONTAINER_NAME" >/dev/null 2>&1 || true

echo "local uvicorn and Docker container ($CONTAINER_NAME) stopped."

#echo "local uvicorn stopped."