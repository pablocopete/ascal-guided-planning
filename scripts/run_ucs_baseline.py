#!/usr/bin/env python3
"""
Blind UCS on ground-truth PDDL (SequentialSimulator), one problem per run.

Log format matches aggregate_results_server.parse_log so
notebooks/results_ascal_vs_blind.ipynb can plot ECDF when pointed at
the results root (e.g. results_blind). The [ucs] JSON includes expansions,
iterations, and nodes_generated (heap enqueues: start state plus each improving
successor push).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

from unified_planning.io import PDDLReader

repo = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ucs_baseline_core import replay_plan_on_gt, resolve_benchmark_problem  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description="UCS baseline on one PDDL problem (GT simulator).")
    ap.add_argument("--domain", required=True, help="Benchmark folder name under benchmarks root")
    ap.add_argument(
        "--problem",
        required=True,
        help="Problem path under domain, e.g. problems/problem-00.pddl",
    )
    ap.add_argument(
        "--benchmarks-root",
        type=Path,
        default=None,
        help="Root with <domain>/domain_*.pddl (default: <repo>/benchmarks)",
    )
    ap.add_argument(
        "--results-root",
        type=Path,
        default=None,
        help="Logs go to <results-root>/<domain>/<problem-stem>.log (default: <repo>/results_blind)",
    )
    ap.add_argument(
        "--max-expansions",
        type=int,
        default=500_000,
        help="UCS expansion cap (default 500000). Use 0 for no cap (wall time still applies unless --max-wall-sec 0).",
    )
    ap.add_argument(
        "--max-wall-sec",
        type=float,
        default=3600.0,
        help="Wall-clock limit in seconds (default 3600 = 1h). Use 0 to disable.",
    )
    ap.add_argument("--console", action="store_true", help="Echo log lines to stdout as well")
    args = ap.parse_args()

    from ucs_baseline_core import run_ucs  # noqa: E402

    bench_root = (
        args.benchmarks_root.expanduser().resolve()
        if args.benchmarks_root is not None
        else repo / "benchmarks"
    )
    bench_dir = bench_root / args.domain
    domain_original = bench_dir / "domain_original.pddl"
    domain_plain = bench_dir / "domain.pddl"
    if domain_original.is_file():
        domain_file = domain_original
    elif domain_plain.is_file():
        domain_file = domain_plain
    else:
        print(
            f"error: no domain file in {bench_dir}",
            file=sys.stderr,
        )
        raise SystemExit(2)
    problem_file = resolve_benchmark_problem(bench_dir, args.problem)

    results_root = (
        args.results_root.expanduser().resolve()
        if args.results_root is not None
        else repo / "results_blind"
    )
    prob_rel = Path(args.problem)
    log_path = (results_root / args.domain / f"{prob_rel.stem}.log").resolve()
    log_path.parent.mkdir(parents=True, exist_ok=True)

    def emit(msg: str = "") -> None:
        log_fp.write(msg + "\n")
        log_fp.flush()
        if args.console:
            print(msg)

    log_fp = open(log_path, "w", encoding="utf-8", buffering=1)
    print(f"[run_ucs_baseline] log: {log_path}", file=sys.stderr)
    try:
        emit(f"# argv: {sys.argv}")
        emit(f"# log_file: {log_path}")
        emit(f"# start_utc: {(datetime.now(timezone.utc)).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'}")
        max_wall = None if args.max_wall_sec <= 0 else float(args.max_wall_sec)
        wall_note = "unlimited" if max_wall is None else str(max_wall)
        exp_note = "unlimited" if args.max_expansions <= 0 else str(args.max_expansions)
        method_tag = "blind_ucs_gt_applicable"
        emit(
            f"method: {method_tag} max_expansions={exp_note} "
            f"max_wall_sec={wall_note}"
        )
        emit(f"domain_file: {domain_file}")
        emit(f"problem_file: {problem_file}")

        reader = PDDLReader()
        gt = reader.parse_problem(str(domain_file), str(problem_file))
        emit(f"Loaded: {domain_file.name} + {problem_file.name}")

        ucs = run_ucs(
            gt,
            max_expansions=args.max_expansions,
            max_wall_sec=max_wall,
            return_plan=True,
        )
        replay = replay_plan_on_gt(gt, ucs.get("plan"))

        emit("")
        emit("[ucs]")
        emit(json.dumps({k: v for k, v in ucs.items() if k != "plan"}, indent=2))
        emit("")
        emit("[gt_replay]")
        emit(json.dumps(replay, indent=2))

        outcome = ucs.get("outcome")
        plan_found = outcome == "SOLVED"
        goal_gt = bool(replay.get("goal_reached"))
        wall = float(ucs.get("wall_time_sec", 0.0))

        emit("")
        emit(
            "[sound model post-loop] "
            f"plan_found={plan_found} "
            f"goal_on_gt={goal_gt}"
        )
        emit(
            f"[online loop] wall {wall:.3f}s  "
            f"(outer iterations=0, stop_reason={repr('ucs')}, "
            f"goal_reached={goal_gt})"
        )
        emit(
            f"[stop] ucs: outcome={outcome!r} executable={replay.get('executable')} "
            f"reason={replay.get('reason')!r}"
        )
    except Exception as e:
        emit("")
        emit(f"[error] {type(e).__name__}: {e}")
        emit(traceback.format_exc())
        plan_found = False
        goal_gt = False
        wall = 0.0
        emit(
            "[sound model post-loop] "
            f"plan_found={plan_found} "
            f"goal_on_gt={goal_gt}"
        )
        emit(
            f"[online loop] wall {wall:.3f}s  "
            f"(outer iterations=0, stop_reason={repr('ucs_error')}, "
            f"goal_reached={goal_gt})"
        )
        raise
    finally:
        end = f"# end_utc: {(datetime.now(timezone.utc)).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'}"
        log_fp.write(end + "\n")
        log_fp.flush()
        if args.console:
            print(end)
        log_fp.close()


if __name__ == "__main__":
    main()
