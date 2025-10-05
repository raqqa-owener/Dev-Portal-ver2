#!/usr/bin/env bash
set -euo pipefail

# ===== 設定 =====
NS=${NS:-portal-dev}
PF_ADDR=${PF_ADDR:-127.0.0.1}

# ★ ご要望どおりの既定ポート
PG_LOCAL_PORT=${PG_LOCAL_PORT:-15432}  # -> svc/postgres:5432
API_LOCAL_PORT=${API_LOCAL_PORT:-8080} # -> svc/portal-api:80

RUNDIR="${RUNDIR:-.run/pfwd}"
LOGDIR="${LOGDIR:-logs}"
mkdir -p "$RUNDIR" "$LOGDIR"

# name ns kind/name local remote
FORWARDS=(
  "pg  $NS svc/postgres   $PG_LOCAL_PORT  5432"
  "api $NS svc/portal-api $API_LOCAL_PORT 80"
)

log(){ printf "\033[1;36m==>\033[0m %s\n" "$*"; }
err(){ printf "\033[1;31m!!\033[0m %s\n" "$*" >&2; }
pidfile(){ echo "$RUNDIR/$1.pid"; }
logfile(){ echo "$LOGDIR/$1.log"; }

is_alive(){
  local pid="${1:-}"
  [[ -n "$pid" ]] || return 1
  [[ -d "/proc/$pid" ]] && return 0
  ps -p "$pid" >/dev/null 2>&1
}

have_eps(){
  # Service の Endpoints が付いているか（Pod Ready までの待機に使う）
  local ns="$1" res="$2"
  local kind="${res%%/*}" name="${res##*/}"
  [[ "$kind" != "svc" ]] && return 0
  kubectl -n "$ns" get endpoints "$name" -o jsonpath='{.subsets[*].addresses[*].ip}' 2>/dev/null \
    | grep -q '[0-9]'
}

wait_eps(){
  local ns="$1" res="$2" tries="${3:-20}"
  local kind="${res%%/*}"
  [[ "$kind" != "svc" ]] && return 0
  for ((i=1;i<=tries;i++)); do
    have_eps "$ns" "$res" && return 0
    sleep 0.7
  done
  return 1
}

start_one(){
  local name="$1" ns="$2" res="$3" lport="$4" rport="$5"
  local pf; pf="$(pidfile "$name")"
  local lf; lf="$(logfile "$name")"

  # 既存が生きてたらスキップ
  if [[ -f "$pf" ]]; then
    local pid; pid="$(cat "$pf" || true)"
    if is_alive "$pid"; then
      log "[$name] already running (pid=$pid) → http://$PF_ADDR:${lport}"
      return 0
    fi
    rm -f "$pf"
  fi

  # リソース存在チェック
  if ! kubectl -n "$ns" get "$res" >/dev/null 2>&1; then
    err "[$name] SKIP: $ns/$res がありません"
    return 0
  fi

  # Service の場合は Endpoints を少し待つ
  if ! wait_eps "$ns" "$res" 25; then
    err "[$name] WARN: $ns/$res の Endpoints が未検出（起動直後かも）"
  fi

  log "[$name] kubectl -n $ns port-forward $res $lport:$rport --address $PF_ADDR"
  nohup kubectl -n "$ns" port-forward "$res" "$lport:$rport" --address "$PF_ADDR" \
    >"$lf" 2>&1 < /dev/null &
  echo $! > "$pf"
  sleep 0.5
  if is_alive "$(cat "$pf")"; then
    log "[$name] started (pid=$(cat "$pf")) → http://$PF_ADDR:${lport}"
  else
    err "[$name] failed. see $lf"; rm -f "$pf"; return 1
  fi
}

stop_one(){
  local name="$1" pf; pf="$(pidfile "$name")"
  [[ -f "$pf" ]] || { log "[$name] not running"; return 0; }
  local pid; pid="$(cat "$pf" || true)"
  if is_alive "$pid"; then
    log "[$name] kill pid=$pid"
    kill "$pid" 2>/dev/null || true
    sleep 0.3
    is_alive "$pid" && kill -9 "$pid" 2>/dev/null || true
  fi
  rm -f "$pf"
}

status_one(){
  local name="$1" port="$2" pf; pf="$(pidfile "$name")"
  if [[ -f "$pf" ]] && is_alive "$(cat "$pf")"; then
    echo "  - $name: RUNNING (http://$PF_ADDR:$port)"
  else
    echo "  - $name: STOPPED (http://$PF_ADDR:$port)"
  fi
}

start(){
  for spec in "${FORWARDS[@]}"; do
    # shellcheck disable=SC2086
    start_one $spec
  done
  echo
  echo "✅ started. Logs: $LOGDIR/{pg,api}.log"
  echo "   PG  DSN: postgresql://<user>:<pass>@$PF_ADDR:$PG_LOCAL_PORT/<db>"
  echo "   API UI:  http://$PF_ADDR:$API_LOCAL_PORT/docs"
}

stop(){
  for spec in "${FORWARDS[@]}"; do
    set -- $spec
    stop_one "$1"
  done
  echo "🛑 stopped."
}

status(){
  echo "Port-forwards status:"
  for spec in "${FORWARDS[@]}"; do
    set -- $spec
    status_one "$1" "$4"
  done
}

case "${1:-}" in
  start|"") start ;;
  stop)      stop ;;
  status)    status ;;
  restart)   stop; start ;;
  *) echo "Usage: $0 [start|stop|status|restart]"; exit 2 ;;
esac
