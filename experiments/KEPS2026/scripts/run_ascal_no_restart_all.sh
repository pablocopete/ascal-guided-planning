#!/usr/bin/env bash
# Run loop_ascal_no_restart.py (ASCAL online loop, carry-state) on all benchmark problems in parallel.
# Logs go to <exp_root>/results/results_ascal_no_restart/<domain>/ by default.
#
# Usage:
#   bash experiments/KEPS2026/scripts/run_ascal_no_restart_all.sh
#   bash experiments/KEPS2026/scripts/run_ascal_no_restart_all.sh 8
#   MAX_JOBS=8 bash experiments/KEPS2026/scripts/run_ascal_no_restart_all.sh
#
# Optional: RESULTS_ROOT=/path/to/logs bash experiments/KEPS2026/scripts/run_ascal_no_restart_all.sh

set -euo pipefail

EXP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"
PROJECT_ROOT="$(cd "$EXP_ROOT/../.." && pwd)"
MAX_JOBS="${1:-${MAX_JOBS:-5}}"
PYTHON="${PYTHON:-python3}"
SCRIPT="$EXP_ROOT/scripts/loop_ascal_no_restart.py"
BENCH_ROOT="${BENCH_ROOT:-$PROJECT_ROOT/benchmarks}"
RESULTS_ROOT="${RESULTS_ROOT:-$EXP_ROOT/results/results_ascal_no_restart}"

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

echo "[run_ascal_no_restart_all] exp_root=$EXP_ROOT benchmarks=$BENCH_ROOT results=$RESULTS_ROOT max_concurrent_jobs=$MAX_JOBS total_tasks=${#COMMANDS[@]}" >&2

printf '%s\n' "${COMMANDS[@]}" | xargs -P "$MAX_JOBS" -I{} bash -c "{}"

echo "[run_ascal_no_restart_all] all tasks finished" >&2
