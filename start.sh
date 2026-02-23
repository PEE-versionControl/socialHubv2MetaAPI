#!/bin/bash
# Start Social Hub + Meta API Report Server
#
# Usage:
#   ./start.sh          # Dev mode: Vite (5173) + FastAPI (8000) separately
#   ./start.sh --prod   # Production: build React, serve everything on port 8000

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FRONTEND_DIR="$SCRIPT_DIR/socialhubv2Automation"

if [ "$1" = "--prod" ]; then
    echo "=== Production Mode ==="
    echo "Building React frontend..."
    cd "$FRONTEND_DIR" && npm run build
    echo "Copying build to static/..."
    rm -rf "$SCRIPT_DIR/static"
    cp -r "$FRONTEND_DIR/dist" "$SCRIPT_DIR/static"
    echo ""
    echo "Starting server on http://localhost:8000"
    cd "$SCRIPT_DIR" && uvicorn api_server:app --host 0.0.0.0 --port 8000
else
    echo "=== Dev Mode ==="
    echo "Starting Meta API backend on port 8000..."
    cd "$SCRIPT_DIR" && uvicorn api_server:app --reload --port 8000 &
    BACKEND_PID=$!

    echo "Starting Social Hub frontend..."
    cd "$FRONTEND_DIR" && npm run dev &
    FRONTEND_PID=$!

    echo ""
    echo "Backend:  http://localhost:8000  (PID: $BACKEND_PID)"
    echo "Frontend: http://localhost:5173  (PID: $FRONTEND_PID)"
    echo "Press Ctrl+C to stop both."

    trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit" INT TERM
    wait
fi
