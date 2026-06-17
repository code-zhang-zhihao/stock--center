#!/usr/bin/env bash

set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
API_DIR="$ROOT_DIR/python-back"
WEB_DIR="$ROOT_DIR/web-admin"
LOG_DIR="$ROOT_DIR/logs"
BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_HOST="${FRONTEND_HOST:-127.0.0.1}"
FRONTEND_PORT="${FRONTEND_PORT:-8080}"
INSTALL_DEPS="false"
WITH_FRONTEND="true"

BACKEND_PID=""
FRONTEND_PID=""

usage() {
  cat <<EOF
stock-center local launcher

Usage:
  ./start.sh                  Start Python backend and Web Admin
  ./start.sh --install        Install/update backend and frontend dependencies, then start
  ./start.sh --backend-only   Start Python backend only
  ./start.sh --with-frontend  Compatibility flag; frontend is enabled by default
  ./start.sh --help           Show this help

Backend:
  API     : http://${BACKEND_HOST}:${BACKEND_PORT}
  Swagger : http://${BACKEND_HOST}:${BACKEND_PORT}/docs
  Health  : http://${BACKEND_HOST}:${BACKEND_PORT}/api/v1/health

Frontend:
  Web Admin: http://${FRONTEND_HOST}:${FRONTEND_PORT}

Notes:
  - This script does not initialize database tables.
  - Run docs/sql/01-schema.sql and docs/sql/02-stock-analysis-migration-mapping.sql manually.
  - Backend .env must point DATABASE_URL to the existing stock-analysis database.
EOF
}

log() {
  printf '[start] %s\n' "$*"
}

die() {
  printf '[start] ERROR: %s\n' "$*" >&2
  exit 1
}

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

port_in_use() {
  local port="$1"
  if command_exists lsof; then
    lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1
  else
    return 1
  fi
}

cleanup() {
  local exit_code=$?
  trap - INT TERM EXIT

  if [ -n "${FRONTEND_PID:-}" ] && kill -0 "$FRONTEND_PID" >/dev/null 2>&1; then
    log "Stopping Web Admin (pid $FRONTEND_PID)"
    kill "$FRONTEND_PID" >/dev/null 2>&1 || true
  fi

  if [ -n "${BACKEND_PID:-}" ] && kill -0 "$BACKEND_PID" >/dev/null 2>&1; then
    log "Stopping Python backend (pid $BACKEND_PID)"
    kill "$BACKEND_PID" >/dev/null 2>&1 || true
  fi

  wait "$FRONTEND_PID" >/dev/null 2>&1 || true
  wait "$BACKEND_PID" >/dev/null 2>&1 || true
  exit "$exit_code"
}

parse_args() {
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --install)
        INSTALL_DEPS="true"
        ;;
      --with-frontend)
        WITH_FRONTEND="true"
        ;;
      --backend-only|--no-frontend)
        WITH_FRONTEND="false"
        ;;
      --help|-h)
        usage
        exit 0
        ;;
      *)
        die "Unknown argument: $1"
        ;;
    esac
    shift
  done
}

install_dependencies() {
  command_exists python3 || die "python3 not found. Please install Python 3.11+ first."

  if [ ! -d "$API_DIR/.venv" ]; then
    log "Creating Python virtual environment: python-back/.venv"
    python3 -m venv "$API_DIR/.venv"
  fi

  # shellcheck disable=SC1091
  source "$API_DIR/.venv/bin/activate"
  log "Installing Python dependencies into python-back/.venv"
  python -m pip install -U pip setuptools wheel
  python -m pip install -e "$API_DIR"
  deactivate || true

  if [ ! -f "$API_DIR/.env" ] && [ -f "$API_DIR/.env.example" ]; then
    log "Creating python-back/.env from .env.example"
    cp "$API_DIR/.env.example" "$API_DIR/.env"
  fi

  if [ "$WITH_FRONTEND" = "true" ] && [ -d "$WEB_DIR" ]; then
    command_exists npm || die "npm not found. Please install Node.js/npm first."
    if [ ! -f "$WEB_DIR/.env" ] && [ -f "$WEB_DIR/.env.example" ]; then
      log "Creating web-admin/.env from .env.example"
      cp "$WEB_DIR/.env.example" "$WEB_DIR/.env"
    fi
    log "Installing Web Admin dependencies"
    (cd "$WEB_DIR" && npm install)
  fi
}

check_environment() {
  [ -f "$API_DIR/.venv/bin/activate" ] || die "Missing python-back/.venv. Run ./start.sh --install first."
  [ -f "$API_DIR/.env" ] || die "Missing python-back/.env. Copy python-back/.env.example to python-back/.env and configure DATABASE_URL/CONFIG_MASTER_KEY."
  command_exists curl || die "curl not found."

  if port_in_use "$BACKEND_PORT"; then
    die "Port $BACKEND_PORT is already in use. Stop the existing backend first or set BACKEND_PORT."
  fi

  if [ "$WITH_FRONTEND" = "true" ]; then
    [ -d "$WEB_DIR" ] || die "web-admin does not exist yet. Run ./start.sh --backend-only for backend-only startup."
    [ -d "$WEB_DIR/node_modules" ] || die "Missing web-admin/node_modules. Run ./start.sh --install first."
    command_exists npm || die "npm not found. Please install Node.js/npm first."
    if port_in_use "$FRONTEND_PORT"; then
      die "Port $FRONTEND_PORT is already in use. Stop the existing frontend first or set FRONTEND_PORT."
    fi
  fi
}

wait_for_url() {
  local name="$1"
  local url="$2"
  local attempts="${3:-60}"
  local delay_seconds="${4:-1}"
  local i=1

  while [ "$i" -le "$attempts" ]; do
    if curl -fsS "$url" >/dev/null 2>&1; then
      log "$name is ready: $url"
      return 0
    fi
    sleep "$delay_seconds"
    i=$((i + 1))
  done

  return 1
}

start_backend() {
  local log_file="$1"
  log "Starting Python backend, log: $log_file"
  (
    exec > >(tee -a "$log_file") 2>&1
    cd "$API_DIR"
    # shellcheck disable=SC1091
    source .venv/bin/activate
    exec uvicorn app.main:app --reload --host "$BACKEND_HOST" --port "$BACKEND_PORT"
  ) &
  BACKEND_PID=$!
}

start_frontend() {
  local log_file="$1"
  log "Starting Web Admin, log: $log_file"
  (
    exec > >(tee -a "$log_file") 2>&1
    cd "$WEB_DIR"
    exec npm run dev -- --host "$FRONTEND_HOST" --port "$FRONTEND_PORT"
  ) &
  FRONTEND_PID=$!
}

main() {
  parse_args "$@"

  if [ "$INSTALL_DEPS" = "true" ]; then
    install_dependencies
  fi

  check_environment
  mkdir -p "$LOG_DIR"

  local timestamp
  timestamp="$(date '+%Y%m%d-%H%M%S')"
  local backend_log="$LOG_DIR/backend-$timestamp.log"
  local frontend_log="$LOG_DIR/frontend-$timestamp.log"

  trap cleanup INT TERM EXIT

  start_backend "$backend_log"
  if [ "$WITH_FRONTEND" = "true" ]; then
    start_frontend "$frontend_log"
  fi

  log "Waiting for services..."
  if ! wait_for_url "Python backend" "http://$BACKEND_HOST:$BACKEND_PORT/api/v1/health" 60 1; then
    die "Python backend did not become ready. Check $backend_log"
  fi

  if [ "$WITH_FRONTEND" = "true" ]; then
    if ! wait_for_url "Web Admin" "http://$FRONTEND_HOST:$FRONTEND_PORT" 60 1; then
      die "Web Admin did not become ready. Check $frontend_log"
    fi
  fi

  cat <<EOF

stock-center is running.

Python API : http://$BACKEND_HOST:$BACKEND_PORT
Swagger    : http://$BACKEND_HOST:$BACKEND_PORT/docs
Health     : http://$BACKEND_HOST:$BACKEND_PORT/api/v1/health
Backend log: $backend_log

Press Ctrl+C to stop services.
EOF

  if [ "$WITH_FRONTEND" = "true" ]; then
    cat <<EOF
Web Admin  : http://$FRONTEND_HOST:$FRONTEND_PORT
Frontend log: $frontend_log
EOF
    wait "$BACKEND_PID" "$FRONTEND_PID"
  else
    wait "$BACKEND_PID"
  fi
}

main "$@"
