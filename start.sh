#!/usr/bin/env bash

# Pipe Fail 
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Move into project directory 
cd "$SCRIPT_DIR"

PORT="${PORT:-8080}"

# Image Name
#CONTAINER_NAME="prod-ai-agent"

#IMAGE_NAME="prod-ai-agent"

# Set variables in .env file.
if [ -f .env ]; then
  set -a
  source .env
  set +a
fi

# Check for duplicate docker process.
#if docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "$CONTAINER_NAME"; then
#  echo "Container $CONTAINER_NAME already running."
#  echo "Dashboard: http://127.0.0.1:${PORT}/dashboard"
#  exit 0
#fi

# Kill uvicorn process.
if pgrep -f "uvicorn app:app" >/dev/null 2>&1; then
  echo "Local uvicorn already running. Use stop.sh first if you want Docker."
  exit 0
fi

# Prefer Docker if available
#if command -v docker >/dev/null 2>&1; then
#  if ! docker image inspect "$IMAGE_NAME" >/dev/null 2>&1; then
#    echo "Building image $IMAGE_NAME ..."
#    docker build -t "$IMAGE_NAME" .
#  fi
  # Remove exited containers.
#  docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true

#  docker run -d \
#    --name "$CONTAINER_NAME" \
#    -p "${PORT}:8080" \
#    -e ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-}" \
#    -e ANTHROPIC_MODEL="${ANTHROPIC_MODEL:-claude-sonnet-5}" \
#    "$IMAGE_NAME"

#  echo "Started $CONTAINER_NAME"
#  echo "Dashboard: http://127.0.0.1:${PORT}/dashboard"
#  echo "Health:    http://127.0.0.1:${PORT}/health"
#  exit 0
#fi    

if [ -f "venv/bin/activate" ]; then
  source venv/bin/activate
fi

# Start uvicorn process.
command -v uvicorn >/dev/null || { echo "uvicorn not found; install deps or use Docker."; exit 1; }
uvicorn app:app --host 127.0.0.1 --port "$PORT" --workers 1 &
echo "Local API started at http://127.0.0.1:${PORT} (PID $!)"

