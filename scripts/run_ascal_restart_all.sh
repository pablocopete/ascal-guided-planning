#!/usr/bin/env bash
# Run loop_ascal_restart.py (ASCAL online loop, restart on negative demo) on all
# benchmark problems in parallel.
# Logs go to <repo>/results_ascal_restart/<domain>/ by default.
#
# Usage:
#   bash scripts/run_ascal_restart_all.sh
#   bash scripts/run_ascal_restart_all.sh 8
#   MAX_JOBS=8 bash scripts/run_ascal_restart_all.sh
#
# Optional: RESULTS_ROOT=/path/to/logs bash scripts/run_ascal_restart_all.sh

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"
MAX_JOBS="${1:-${MAX_JOBS:-5}}"
PYTHON="${PYTHON:-python3}"
SCRIPT="$ROOT/scripts/loop_ascal_restart.py"
BENCH_ROOT="$ROOT/benchmarks"
RESULTS_ROOT="${RESULTS_ROOT:-$ROOT/results_ascal_restart}"

DOMAINS=("blocks" "satellite" "miconic" "driverlog")
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
    COMMANDS+=(
      "'$PYTHON' '$SCRIPT' --domain '$DOMAIN' --problem '$PROB_FILE' --benchmarks-root '$BENCH_ROOT' --results-root '$RESULTS_ROOT'"
    )
  done
done

echo "[run_ascal_restart_all] repo=$ROOT benchmarks=$BENCH_ROOT results=$RESULTS_ROOT max_concurrent_jobs=$MAX_JOBS total_tasks=${#COMMANDS[@]}" >&2

printf '%s\n' "${COMMANDS[@]}" | xargs -P "$MAX_JOBS" -I{} bash -c "{}"

echo "[run_ascal_restart_all] all tasks finished" >&2
