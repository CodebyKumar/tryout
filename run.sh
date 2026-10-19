#!/usr/bin/env bash
# One command to run the app.  ./run.sh [start|stop|restart|status|logs|share|dev|test|sim]
set -euo pipefail
cd "$(dirname "$0")"

PORT="${PORT:-8000}"
RUN_DIR=".run"
PID_FILE="$RUN_DIR/server.pid"
LOG_FILE="$RUN_DIR/server.log"
mkdir -p "$RUN_DIR"

running() { [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; }

setup() {
  command -v uv >/dev/null || { echo "uv is required: https://docs.astral.sh/uv/"; exit 1; }
  [[ -f .env ]] || { cp .env.example .env; echo "Created .env - add your GROQ_API_KEY to it."; }
  grep -q '^GROQ_API_KEY=.\+' .env || echo "Warning: GROQ_API_KEY is empty in .env"
  uv sync -q
}

case "${1:-start}" in
  start)
    if running; then echo "Already running on http://localhost:$PORT (pid $(cat "$PID_FILE"))"; exit 0; fi
    setup
    nohup uv run uvicorn backend.app:app --host 0.0.0.0 --port "$PORT" >"$LOG_FILE" 2>&1 &
    echo $! >"$PID_FILE"
    for _ in $(seq 1 20); do
      curl -sf "http://localhost:$PORT/api/health" >/dev/null 2>&1 && { echo "Running: http://localhost:$PORT  (logs: ./run.sh logs, stop: ./run.sh stop)"; exit 0; }
      running || break
      sleep 0.5
    done
    echo "Server failed to start. Last log lines:"; tail -20 "$LOG_FILE"; rm -f "$PID_FILE"; exit 1
    ;;
  stop)
    if running; then
      pid="$(cat "$PID_FILE")"
      pkill -TERM -P "$pid" 2>/dev/null || true   # uvicorn runs as a child of `uv run`
      kill "$pid" 2>/dev/null || true
      for _ in $(seq 1 20); do kill -0 "$pid" 2>/dev/null || break; sleep 0.25; done
      echo "Stopped."
    else echo "Not running."; fi
    rm -f "$PID_FILE"
    ;;
  restart) "$0" stop; "$0" start ;;
  status) running && echo "Running on http://localhost:$PORT (pid $(cat "$PID_FILE"))" || echo "Not running." ;;
  logs) tail -f "$LOG_FILE" ;;
  share)
    # App + public HTTPS link (Cloudflare quick tunnel, no account). Ctrl+C stops both.
    command -v cloudflared >/dev/null || { echo "Install cloudflared first: brew install cloudflared"; exit 1; }
    "$0" start
    TUNNEL_LOG="$RUN_DIR/tunnel.log"
    cloudflared tunnel --no-autoupdate --url "http://localhost:$PORT" >"$TUNNEL_LOG" 2>&1 &
    TUNNEL_PID=$!
    trap 'echo; echo "Stopping..."; kill $TUNNEL_PID 2>/dev/null; "$0" stop; exit 0' INT TERM
    URL=""
    for _ in $(seq 1 60); do
      URL=$(grep -oE "https://[a-z0-9-]+\.trycloudflare\.com" "$TUNNEL_LOG" | head -1 || true)
      [[ -n "$URL" ]] && break
      kill -0 $TUNNEL_PID 2>/dev/null || break
      sleep 0.5
    done
    if [[ -z "$URL" ]]; then echo "Tunnel failed to start:"; tail -20 "$TUNNEL_LOG"; kill $TUNNEL_PID 2>/dev/null; exit 1; fi
    echo
    echo "  Public link:   $URL"
    echo "  Recruiter:     $URL/   (create candidate links from here so they use this address)"
    echo "  Local:         http://localhost:$PORT"
    echo
    echo "  Keep this terminal open. Press Ctrl+C to stop the app and the public link."
    wait $TUNNEL_PID
    ;;
  dev) setup; uv run uvicorn backend.app:app --reload --port "$PORT" ;;
  test) uv run pytest -q ;;
  sim) uv run python scripts/simulate.py "${@:2}" ;;
  *) echo "Usage: ./run.sh [start|stop|restart|status|logs|share|dev|test|sim [persona]]"; exit 1 ;;
esac
