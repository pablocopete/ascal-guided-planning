#!/usr/bin/env bash
# Blind UCS baseline on all benchmark problems in parallel.
# Logs go to <exp_root>/results/results_blind/<domain>/ by default.
#
# Defaults (override with env vars):
#   MAX_EXPANSIONS=0        — no expansion cap
#   MAX_WALL_SEC=3600       — 1 hour wall time per problem (use 0 for no cap)
#
# Usage:
#   bash scripts/run_blind_all.sh
#   bash scripts/run_blind_all.sh 8
#   MAX_JOBS=8 RESULTS_ROOT=/tmp/blind bash scripts/run_blind_all.sh
#
# Optional env: UCS_DOMAINS=blocks  MAX_EXPANSIONS=…  MAX_WALL_SEC=…

set -euo pipefail

EXP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"
PROJECT_ROOT="$(cd "$EXP_ROOT/../.." && pwd)"
MAX_JOBS="${1:-${MAX_JOBS:-4}}"
PYTHON="${PYTHON:-python3}"
SCRIPT="$EXP_ROOT/scripts/run_ucs_baseline.py"
BENCH_ROOT="${BENCH_ROOT:-$PROJECT_ROOT/benchmarks}"
RESULTS_ROOT="${RESULTS_ROOT:-$EXP_ROOT/results/results_blind}"
MAX_EXPANSIONS="${MAX_EXPANSIONS:-0}"
MAX_WALL_SEC="${MAX_WALL_SEC:-3600}"

if [[ -n "${UCS_DOMAINS:-}" ]]; then
  # shellcheck disable=SC2206
  DOMAINS=($UCS_DOMAINS)
else
  DOMAINS=("blocks" "satellite" "miconic" "driverlog")
fi
COMMANDS=()

if [[ ! -f "$SCRIPT" ]]; then
  echo "error: missing $SCRIPT" >&2
  exit 1
fi

if [[ ! -d "$BENCH_ROOT" ]]; then
  echo "error: missing $BENCH_ROOT" >&2
  exit 1
fi

shopt -s nullglob

for DOMAIN in "${DOMAINS[@]}"; do
  PROB_DIR="$BENCH_ROOT/$DOMAIN/problems"

  if [[ ! -d "$PROB_DIR" ]]; then
    echo "error: missing $PROB_DIR" >&2
    exit 1
  fi

  paths=("$PROB_DIR"/*.pddl)
  if [[ ${#paths[@]} -eq 0 ]]; then
    echo "error: no .pddl files found under $PROB_DIR" >&2
    exit 1
  fi

  mapfile -t sorted < <(printf '%s\n' "${paths[@]}" | LC_ALL=C sort -V)

  for f in "${sorted[@]}"; do
    PROB_FILE="problems/$(basename "$f")"
    _extra=" --max-expansions ${MAX_EXPANSIONS} --max-wall-sec ${MAX_WALL_SEC}"
    COMMANDS+=(
      "'$PYTHON' '$SCRIPT' --domain '$DOMAIN' --problem '$PROB_FILE' --benchmarks-root '$BENCH_ROOT' --results-root '$RESULTS_ROOT'${_extra}"
    )
  done
done

echo "[run_blind_all] exp_root=$EXP_ROOT benchmarks=$BENCH_ROOT results=$RESULTS_ROOT max_expansions=${MAX_EXPANSIONS} max_wall_sec=${MAX_WALL_SEC} max_concurrent_jobs=$MAX_JOBS total_tasks=${#COMMANDS[@]}" >&2

printf '%s\n' "${COMMANDS[@]}" | xargs -P "$MAX_JOBS" -I{} bash -c "{}"

echo "[run_blind_all] all tasks finished" >&2
