"""
Online loop (sound → complete → version_space) with **restart-on-negative-demo** behaviour.

After each outer iteration that has a **plan**:

- If the plan executes **without any negative demo** (every action is applicable),
  the **next** iteration plans from the **carried** UP state (the terminal state of
  the successful rollout).
- If the plan produces a **negative demo** (an action is inapplicable mid-plan),
  carry is **cleared** and the next iteration plans from the **original PDDL initial
  state** again.
- If there is **no plan at all**, carry is cleared (same as above).

This is the **restart** counterpart to ``loop_ascal_no_restart.py``, which always
carries the last valid state regardless of whether the simulation failed.

Post-loop sound check always uses the **original** PDDL initial (``gt_problem``) for
comparability across variants.

**Smoke test:**

    python scripts/loop_ascal_restart.py --domain blocks --problem problem-00 --max-outer 1

Default benchmark root is ``<repo>/benchmarks`` (override with ``--benchmarks-root``).

**Planner isolation:** each run uses its own temporary working directory so parallel jobs (or
other FD users in the same folder) do not corrupt shared plan files — see project notes on
``sas_plan`` races.

**Server log file:** by default writes to ``<exp_root>/results/results_ascal_restart/<domain>/<problem-stem>.log``
(inside the repo so it is easy to find). Lines go to the file only; use ``--console`` to also
echo to stdout. Override path with ``--log-file``, or ``--no-log-file`` for stdout-only.

**Log metrics (after the online loop, before post-loop FD check):**
``[demos_processed]`` — JSON with ``positive_total``, ``negative_total``, and
``per_action.{action: {positive, negative}}`` counting ``learner.update`` calls.
``[sound_complete_convergence]`` — JSON: per PDDL action, whether the version
space has fully converged (``learner.version_space_size`` criterion: ``L == U``
for both preconditions and effects). No sound/complete UP
models are built.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path
from typing import Any

import unified_planning as up
from unified_planning.io import PDDLReader
from unified_planning.shortcuts import OneshotPlanner, SequentialSimulator
from unified_planning.engines import PlanGenerationResultStatus

experiment_root = Path(__file__).resolve().parent.parent
project_root = experiment_root.parent.parent

from ascal import Learner
from ascal.models import Action as VAction, Demonstration
from ascal.transitions import (
    build_literal_descriptors,
    lift_demonstrations,
    signature_to_state,
    state_to_signature,
)

up.shortcuts.get_environment().credits_stream = None


def resolve_benchmark_problem(bench_dir: Path, problem_arg: str) -> Path:
    """Resolve ``--problem`` against ``<benchmarks-root>/<domain>/``.

    Accepts e.g. ``problems/problem-00.pddl`` or shorthand ``problem-00`` /
    ``problem-00.pddl`` (looks under ``problems/`` and adds ``.pddl`` when needed).
    """

    raw = problem_arg.strip()
    p = Path(raw)
    candidates: list[Path] = [bench_dir / p]
    if p.suffix.lower() != ".pddl":
        candidates.append(bench_dir / f"{raw}.pddl")
        candidates.append(bench_dir / "problems" / f"{p.stem}.pddl")
        candidates.append(bench_dir / "problems" / raw)
    else:
        candidates.append(bench_dir / "problems" / p.name)

    seen: set[Path] = set()
    for c in candidates:
        rp = c.resolve()
        if rp in seen:
            continue
        seen.add(rp)
        if c.is_file():
            return c

    print("error: problem file not found. Tried:", file=sys.stderr)
    for c in candidates:
        print(f"  {c}", file=sys.stderr)
    print(
        "hint: use e.g. --problem problems/problem-00.pddl or --problem problem-00",
        file=sys.stderr,
    )
    raise SystemExit(2)


def inject_actions(base_problem, learned_problem):
    p = base_problem.clone()
    p.clear_actions()
    p.add_actions(learned_problem.actions)
    return p


def sound_complete_convergence_report(learner: Learner, gt_problem) -> dict[str, Any]:
    """Per PDDL action convergence using ``learner.version_space_size``.

    An action is **converged** when its version-space has collapsed to a single
    hypothesis for both preconditions and effects (``L == U`` for pre and eff).
    """
    actions = list(gt_problem.actions)
    rep = learner.version_space_size  # dict[action_name -> {n_pre, n_eff, converged, total}]
    per_action: dict[str, dict[str, Any]] = {}
    n_conv = 0
    for a in actions:
        r = rep.get(a.name, {})
        conv = bool(r.get("converged", False))
        if conv:
            n_conv += 1
        per_action[a.name] = {
            "converged": conv,
            "n_pre_interval": r.get("n_pre"),
            "n_eff_proxy": r.get("n_eff"),
            "total": r.get("total"),
        }
    return {
        "domain_action_count": len(actions),
        "converged_action_count": n_conv,
        "per_action": per_action,
        "criterion": "version_space_size",
    }


def learner_up_problem(learner, kind: str):
    kind = kind.lower()
    if kind == "sound":
        return learner.sound_model()
    if kind == "complete":
        return learner.complete_model()
    if kind == "version_space":
        return learner.version_space()
    raise ValueError('kind must be one of: "sound", "complete", "version_space"')


def simulate_prefix_on_ground_truth(
    problem, plan, literal_descriptors, *, verbose=False
):
    """Returns (positives, neg_demo, final_up_state_or_none, carry_up_state).

    ``carry_up_state`` is always the **last valid** UP state after the walk: the
    simulator state before a failed action, or the terminal state if the full
    prefix was executed (including empty plan → initial).
    """

    def upstate_to_ascal_state(up_state):
        sig = state_to_signature(up_state, literal_descriptors)
        return signature_to_state(sig)

    positives = []
    neg_demo = None
    final_up_state = None
    with SequentialSimulator(problem=problem) as sim:
        state = sim.get_initial_state()
        for i, ai in enumerate(plan.actions):
            base_name = ai.action.name.split("_version")[0]
            base_action = problem.action(base_name)
            params = tuple(ai.actual_parameters)
            applicable = sim.is_applicable(state, base_action, params)
            if verbose:
                print(f"Step {i} {ai.action.name} applicable={applicable}")
            pre_v = upstate_to_ascal_state(state)
            if not applicable:
                neg_demo = Demonstration(
                    pre_state=pre_v,
                    action=VAction(base_name, tuple(str(p) for p in params)),
                    post_state=None,
                )
                if verbose:
                    print("Failed at step", i)
                break
            post = sim.apply(state, base_action, params)
            post_v = upstate_to_ascal_state(post)
            positives.append(
                Demonstration(
                    pre_state=pre_v,
                    action=VAction(base_name, tuple(str(p) for p in params)),
                    post_state=post_v,
                )
            )
            state = post
        else:
            final_up_state = state
    carry_up_state = state
    return positives, neg_demo, final_up_state, carry_up_state


def clone_gt_with_up_initial(gt_problem, up_state):
    """Clone ``gt_problem`` so its PDDL initial values match ``up_state`` (for planning)."""
    p = gt_problem.clone()
    for fl, _ in list(p.initial_values.items()):
        p.set_initial_value(fl, up_state.get_value(fl))
    return p


def simulate_prefix_from_state(
    problem, start_state, plan, literal_descriptors, *, verbose=False
):
    """Same returns as ``simulate_prefix_on_ground_truth``; walk starts at ``start_state``."""

    def upstate_to_ascal_state(up_state):
        sig = state_to_signature(up_state, literal_descriptors)
        return signature_to_state(sig)

    positives = []
    neg_demo = None
    final_up_state = None
    with SequentialSimulator(problem=problem) as sim:
        state = start_state
        for i, ai in enumerate(plan.actions):
            base_name = ai.action.name.split("_version")[0]
            base_action = problem.action(base_name)
            params = tuple(ai.actual_parameters)
            applicable = sim.is_applicable(state, base_action, params)
            if verbose:
                print(f"Step {i} {ai.action.name} applicable={applicable}")
            pre_v = upstate_to_ascal_state(state)
            if not applicable:
                neg_demo = Demonstration(
                    pre_state=pre_v,
                    action=VAction(base_name, tuple(str(p) for p in params)),
                    post_state=None,
                )
                if verbose:
                    print("Failed at step", i)
                break
            post = sim.apply(state, base_action, params)
            post_v = upstate_to_ascal_state(post)
            positives.append(
                Demonstration(
                    pre_state=pre_v,
                    action=VAction(base_name, tuple(str(p) for p in params)),
                    post_state=post_v,
                )
            )
            state = post
        else:
            final_up_state = state
    carry_up_state = state
    return positives, neg_demo, final_up_state, carry_up_state


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--domain",
        default="blocks",
        help=(
            "Benchmark folder under the benchmarks root (e.g. blocks, satellite). "
            "Domain file: domain_original.pddl if present, else domain.pddl."
        ),
    )
    ap.add_argument(
        "--problem",
        default="problems/problem-00.pddl",
        help=(
            "Path under <benchmarks-root>/<domain>/, or shorthand like problem-00 "
            "(resolves to problems/problem-00.pddl)."
        ),
    )
    ap.add_argument("--max-outer", type=int, default=500)
    ap.add_argument("--quiet", action="store_true", default=True)
    ap.add_argument(
        "--log-file",
        type=Path,
        default=None,
        metavar="PATH",
        help=(
            "Log path (default: <exp_root>/results/results_ascal_restart/<domain>/<problem-stem>.log)."
        ),
    )
    ap.add_argument(
        "--no-log-file",
        action="store_true",
        help="Do not write a log file (print all progress to stdout).",
    )
    ap.add_argument(
        "--console",
        action="store_true",
        help="When writing a log file, also echo each line to stdout (default: file only).",
    )
    ap.add_argument(
        "--benchmarks-root",
        type=Path,
        default=None,
        metavar="DIR",
        help=(
            "Directory that contains <domain>/domain_*.pddl and problems/ "
            "(default: <repo>/benchmarks)."
        ),
    )
    ap.add_argument(
        "--results-root",
        type=Path,
        default=None,
        metavar="DIR",
        help=(
            "Directory for default log layout <domain>/<problem-stem>.log "
            "(default: <exp_root>/results/results_ascal_restart)."
        ),
    )
    args = ap.parse_args()

    bench_root = (
        args.benchmarks_root.expanduser().resolve()
        if args.benchmarks_root is not None
        else project_root / "benchmarks"
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
            f"error: no domain file in {bench_dir} "
            f"(expected domain_original.pddl or domain.pddl)",
            file=sys.stderr,
        )
        raise SystemExit(2)
    problem_file = resolve_benchmark_problem(bench_dir, args.problem)
    MAX_OUTER_ITERATIONS = args.max_outer
    QUIET_ONLINE_LOOP = args.quiet

    prob_rel = Path(args.problem)
    results_root = (
        args.results_root.expanduser().resolve()
        if args.results_root is not None
        else experiment_root / "results" / "results_ascal_restart"
    )
    default_log_file = (
        results_root / args.domain / f"{prob_rel.stem}.log"
    ).resolve()
    if args.no_log_file:
        log_file_path = None
    elif args.log_file is not None:
        log_file_path = args.log_file.expanduser().resolve()
    else:
        log_file_path = default_log_file

    # With a log file, default is file-only (no stdout spam). Stdout-only when no log file.
    console_out = log_file_path is None or args.console

    # Fast Downward (via UP) writes plan/translator artifacts in cwd; parallel runs must
    # not share the same directory or plan parse errors (e.g. mystery action names) appear.
    _fd_workdir = tempfile.mkdtemp(prefix="ascal_")
    _orig_cwd = os.getcwd()
    os.chdir(_fd_workdir)

    log_fp = None

    def emit(msg: str = "") -> None:
        if log_fp is not None:
            log_fp.write(msg + "\n")
            log_fp.flush()
        if console_out:
            print(msg)

    try:
        if log_file_path is not None:
            log_file_path.parent.mkdir(parents=True, exist_ok=True)
            log_fp = open(log_file_path, "w", encoding="utf-8", buffering=1)
            print(f"[loop_ascal_restart] log file: {log_file_path}", file=sys.stderr)
            emit(f"# argv: {sys.argv}")
            emit(f"# log_file: {log_file_path}")
            emit(f"# start_utc: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}")

        reader = PDDLReader()
        gt_problem = reader.parse_problem(str(domain_file), str(problem_file))

        all_actions = list(gt_problem.actions)
        all_fluents = list(gt_problem.fluents)
        static_fluents = gt_problem.get_static_fluents()
        learner = Learner(all_fluents, all_actions, static_fluents)

        emit(f"Loaded: {domain_file.name} + {problem_file.name}")

        all_ground_literals = list(gt_problem.initial_values.keys())
        literal_descriptors = build_literal_descriptors(all_ground_literals)

        _t_model0 = time.perf_counter()
        plan_learned = learner_up_problem(learner, "sound")
        _t_model1 = time.perf_counter()
        plan_problem = inject_actions(gt_problem, plan_learned)
        _t_inject1 = time.perf_counter()
        _pa = len(list(plan_learned.actions))
        _n_init = _pa

        emit(
            f"[timing] initial UP export (sound): "
            f"{_t_model1 - _t_model0:.4f}s  |  inject: {_t_inject1 - _t_model1:.4f}s"
        )
        emit(f"Planning actions (sound): {_pa}")

        stats = {
            "plan_found": 0,
            "plan_found_sound": 0,
            "plan_found_complete": 0,
            "plan_found_version_space": 0,
            "plan_verified": 0,
            "plan_spurious": 0,
            "no_plan": 0,
        }

        demo_step = 0
        demo_pos_total = 0
        demo_neg_total = 0
        demo_pos_by_action: Counter[str] = Counter()
        demo_neg_by_action: Counter[str] = Counter()
        _t_loop_start = time.perf_counter()
        goal_reached = False
        stop_reason = None
        i = -1
        _sum_export_build = 0.0
        _sum_solve = 0.0
        carry_up_state = None  # last valid UP state after last simulated plan (or None)

        with OneshotPlanner(name="fast-downward", problem_kind=plan_problem.kind) as planner:
            while (i + 1) < MAX_OUTER_ITERATIONS:
                i += 1
                goal_reached = False
                plan = None
                plan_source: str | None = None
                t_plan = 0.0

                plan_base = (
                    clone_gt_with_up_initial(gt_problem, carry_up_state)
                    if carry_up_state is not None
                    else gt_problem
                )
                if carry_up_state is not None:
                    emit("[carry] planning from previous iteration last valid state")

                t_e0 = time.perf_counter()
                plan_learned_sound = learner_up_problem(learner, "sound")
                t_e1 = time.perf_counter()
                _sum_export_build += t_e1 - t_e0
                plan_problem_sound = inject_actions(plan_base, plan_learned_sound)
                t0 = time.perf_counter()
                result_s = planner.solve(plan_problem_sound)
                dt_s = time.perf_counter() - t0
                _sum_solve += dt_s
                t_plan += dt_s
                ok_s = result_s.status == PlanGenerationResultStatus.SOLVED_SATISFICING
                if ok_s:
                    plan = result_s.plan
                    plan_source = "sound"
                else:
                    t_e0 = time.perf_counter()
                    plan_learned_complete = learner_up_problem(learner, "complete")
                    t_e1 = time.perf_counter()
                    _sum_export_build += t_e1 - t_e0
                    plan_problem_complete = inject_actions(plan_base, plan_learned_complete)
                    t0 = time.perf_counter()
                    result_c = planner.solve(plan_problem_complete)
                    dt_c = time.perf_counter() - t0
                    _sum_solve += dt_c
                    t_plan += dt_c
                    ok_c = result_c.status == PlanGenerationResultStatus.SOLVED_SATISFICING
                    if ok_c:
                        plan = result_c.plan
                        plan_source = "complete"
                    else:
                        t_e2 = time.perf_counter()
                        plan_learned_vs = learner_up_problem(learner, "version_space")
                        t_e3 = time.perf_counter()
                        _sum_export_build += t_e3 - t_e2
                        plan_problem_vs = inject_actions(plan_base, plan_learned_vs)
                        t1 = time.perf_counter()
                        result_vs = planner.solve(plan_problem_vs)
                        dt_vs = time.perf_counter() - t1
                        _sum_solve += dt_vs
                        t_plan += dt_vs
                        ok_vs = (
                            result_vs.status
                            == PlanGenerationResultStatus.SOLVED_SATISFICING
                        )
                        if ok_vs:
                            plan = result_vs.plan
                            plan_source = "version_space"

                pos_demos, neg_demo, final_up_state = [], None, None
                verified = False
                sim_carry_state = None
                if plan is not None:
                    stats["plan_found"] += 1
                    if plan_source == "sound":
                        stats["plan_found_sound"] += 1
                    elif plan_source == "complete":
                        stats["plan_found_complete"] += 1
                    elif plan_source == "version_space":
                        stats["plan_found_version_space"] += 1
                    if carry_up_state is not None:
                        pos_demos, neg_demo, final_up_state, sim_carry_state = (
                            simulate_prefix_from_state(
                                gt_problem,
                                carry_up_state,
                                plan,
                                literal_descriptors,
                                verbose=False,
                            )
                        )
                    else:
                        pos_demos, neg_demo, final_up_state, sim_carry_state = (
                            simulate_prefix_on_ground_truth(
                                gt_problem, plan, literal_descriptors, verbose=False
                            )
                        )
                    verified = neg_demo is None and len(pos_demos) == len(plan.actions)
                    if verified:
                        stats["plan_verified"] += 1
                    else:
                        stats["plan_spurious"] += 1
                    if final_up_state is not None:
                        with SequentialSimulator(problem=gt_problem) as sim_goal:
                            goal_reached = sim_goal.is_goal(final_up_state)
                else:
                    stats["no_plan"] += 1
                    if not QUIET_ONLINE_LOOP:
                        emit(
                            f"[no plan] sound / complete / version_space all failed "
                            f"(outer i={i})."
                        )

                # Restart policy: carry forward only after a clean plan (no negative demo).
                # A negative demo resets to the PDDL initial state next iteration.
                if plan is not None and neg_demo is None:
                    carry_up_state = sim_carry_state
                else:
                    carry_up_state = None

                batch = pos_demos + ([neg_demo] if neg_demo is not None else [])
                lifted_batch = lift_demonstrations(batch, list(gt_problem.actions))

                if not QUIET_ONLINE_LOOP:
                    emit(
                        f">>> outer i={i} plan_source={plan_source!s} plan_time={t_plan:.3f}s "
                        f"batch={len(lifted_batch)} goal_reached={goal_reached} stats={stats}"
                    )

                for demo in lifted_batch:
                    an = demo.action.name
                    if demo.is_positive:
                        demo_pos_total += 1
                        demo_pos_by_action[an] += 1
                    else:
                        demo_neg_total += 1
                        demo_neg_by_action[an] += 1
                    learner.update(demo)
                    demo_step += 1

                if plan is None:
                    stop_reason = "no_plan_complete"
                    break
                if goal_reached:
                    stop_reason = "goal"
                    break

        if stop_reason is None:
            stop_reason = "max_iterations"

        demo_action_names = sorted(
            set(demo_pos_by_action) | set(demo_neg_by_action)
        )
        emit(
            "[demos_processed] "
            + json.dumps(
                {
                    "positive_total": demo_pos_total,
                    "negative_total": demo_neg_total,
                    "per_action": {
                        a: {
                            "positive": int(demo_pos_by_action[a]),
                            "negative": int(demo_neg_by_action[a]),
                        }
                        for a in demo_action_names
                    },
                },
                sort_keys=True,
            )
        )
        emit(
            "[sound_complete_convergence] "
            + json.dumps(sound_complete_convergence_report(learner, gt_problem))
        )

        # Post-loop check: final sound model — planner SAT vs GT goal after full prefix.
        plan_learned_final_sound = learner_up_problem(learner, "sound")
        plan_problem_final_sound = inject_actions(gt_problem, plan_learned_final_sound)
        sound_post_loop_plan_found = False
        sound_post_loop_goal_gt = False
        with OneshotPlanner(
            name="fast-downward", problem_kind=plan_problem_final_sound.kind
        ) as planner_final:
            result_final = planner_final.solve(plan_problem_final_sound)
            if (
                result_final.status
                == PlanGenerationResultStatus.SOLVED_SATISFICING
            ):
                sound_post_loop_plan_found = True
                sound_plan = result_final.plan
                _pos_f, neg_f, final_up_f, _carry_f = simulate_prefix_on_ground_truth(
                    gt_problem,
                    sound_plan,
                    literal_descriptors,
                    verbose=False,
                )
                if neg_f is None and final_up_f is not None:
                    with SequentialSimulator(problem=gt_problem) as sim_goal:
                        sound_post_loop_goal_gt = sim_goal.is_goal(final_up_f)

        emit(
            "[sound model post-loop] "
            f"plan_found={sound_post_loop_plan_found} "
            f"goal_on_gt={sound_post_loop_goal_gt}"
        )

        n_outer = max(0, i + 1)
        emit(
            f"[online loop] wall {time.perf_counter() - _t_loop_start:.3f}s  "
            f"(outer iterations={n_outer}, stop_reason={stop_reason!r}, "
            f"goal_reached={goal_reached})"
        )
        _stop_msgs = {
            "goal": "GT state after full simulated plan satisfies PDDL goals",
            "no_plan_complete": (
                "planner returned no plan for sound, complete, and version_space"
            ),
            "max_iterations": (
                f"reached MAX_OUTER_ITERATIONS ({MAX_OUTER_ITERATIONS}) without goal"
            ),
        }
        emit(f"[stop] {stop_reason}: {_stop_msgs[stop_reason]}")
        if n_outer > 0:
            emit(
                f"[timing summary] total plan_model_export={_sum_export_build:.3f}s  "
                f"total plan_solve={_sum_solve:.3f}s  "
                f"avg plan_model_export/iter={_sum_export_build / n_outer:.3f}s  "
                f"avg plan_solve/iter={_sum_solve / n_outer:.3f}s"
            )

        emit(
            "[summary] "
            f"{stats} learn_steps {demo_step} exported_UP_actions_end "
            f"{len(list(learner_up_problem(learner, 'sound').actions))} "
            f"(started {_n_init})"
        )
    finally:
        end_line = f"# end_utc: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}"
        if log_fp is not None:
            log_fp.write(end_line + "\n")
            log_fp.close()
        if console_out:
            print(end_line)
        try:
            os.chdir(_orig_cwd)
        except OSError:
            pass
        shutil.rmtree(_fd_workdir, ignore_errors=True)


if __name__ == "__main__":
    main()
