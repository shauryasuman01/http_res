#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

usage() {
  cat <<'EOF'
Usage:
  ./run-all.sh backend [interface]
  ./run-all.sh test

backend starts InfluxDB, ingestion, the API, and the live probe. The probe
interface must be supplied as the second argument or PROBE_INTERFACE.
EOF
}

run_tests() {
  npm test
  .venv/bin/python -m unittest discover -s tests/python
  env -u INFLUX_URL -u INFLUX_TOKEN npm run smoke
}

run_backend() {
  local interface="${1:-${PROBE_INTERFACE:-}}"
  if [[ -z "$interface" ]]; then
    echo "error: supply a probe interface, for example: ./run-all.sh backend eth0" >&2
    exit 2
  fi
  command -v influxdb3 >/dev/null || { echo "error: influxdb3 is not on PATH" >&2; exit 1; }
  [[ -x .venv/bin/python ]] || { echo "error: .venv/bin/python is missing" >&2; exit 1; }

  mkdir -p data
  local db_pid ingestion_pid api_pid probe_pid
  cleanup() {
    trap - EXIT INT TERM
    [[ -n "${probe_pid:-}" ]] && sudo kill "$probe_pid" 2>/dev/null || true
    [[ -n "${api_pid:-}" ]] && kill "$api_pid" 2>/dev/null || true
    [[ -n "${ingestion_pid:-}" ]] && kill "$ingestion_pid" 2>/dev/null || true
    [[ -n "${db_pid:-}" ]] && kill "$db_pid" 2>/dev/null || true
    wait 2>/dev/null || true
  }
  trap cleanup EXIT INT TERM

  influxdb3 serve \
    --node-id adwiser-probe-dev \
    --object-store file \
    --data-dir "$ROOT_DIR/data/influx" \
    --http-bind 127.0.0.1:18181 &
  db_pid=$!

  for _ in {1..60}; do
    if curl -fsS http://127.0.0.1:18181/health >/dev/null 2>&1; then break; fi
    sleep 1
  done
  kill -0 "$db_pid" 2>/dev/null || { echo "error: InfluxDB stopped during startup" >&2; exit 1; }

  if [[ ! -f data/dev-token.json ]]; then
    node deploy/live.js setup
  fi
  node deploy/live.js ingestion &
  ingestion_pid=$!
  node deploy/live.js api &
  api_pid=$!

  for _ in {1..30}; do
    if curl -fsS http://127.0.0.1:8090/health >/dev/null 2>&1; then break; fi
    sleep 1
  done
  curl -fsS http://127.0.0.1:8090/health >/dev/null || {
    echo "error: API did not become ready" >&2
    exit 1
  }

  echo "backend running; press Ctrl+C to stop all services"
  sudo env \
    PROBE_INTERFACE="$interface" \
    PROBE_ID="${PROBE_ID:-adwiser-probe-dev}" \
    ZMQ_BIND_ENDPOINT="${ZMQ_BIND_ENDPOINT:-tcp://127.0.0.1:5557}" \
    "$ROOT_DIR/.venv/bin/python" "$ROOT_DIR/probe/probe.py" &
  probe_pid=$!
  wait "$probe_pid"
}

case "${1:-}" in
  backend) run_backend "${2:-}" ;;
  test) run_tests ;;
  -h|--help) usage ;;
  *) usage >&2; exit 2 ;;
esac
