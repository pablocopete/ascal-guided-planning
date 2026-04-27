"""
Uniform cost search + GT plan replay (no fixed paths). Used by run_ucs_baseline.py.
"""
from __future__ import annotations

import heapq
import sys
import time
from pathlib import Path
from typing import Any

import unified_planning as up
from unified_planning.engines import (
    evaluate_quality_metric,
    evaluate_quality_metric_in_initial_state,
)
from unified_planning.shortcuts import SequentialSimulator

up.shortcuts.get_environment().credits_stream = None


def _ap_key(item: tuple) -> tuple:
    action, params = item
    return (action.name, tuple(str(p) for p in params))


def sorted_applicable(sim: SequentialSimulator, state) -> list[tuple]:
    acts = tuple(sim.get_applicable_actions(state))
    return sorted(acts, key=_ap_key)


def _pick_metric(problem):
    for m in problem.quality_metrics:
        if m.is_minimize_action_costs() or m.is_minimize_sequential_plan_length():
            return m
    return None


def _metric_name(metric) -> str:
    if metric is None:
        return "none_implicit_unit_cost"
    return type(metric).__name__


def _initial_g(sim, metric) -> float:
    if metric is None:
        return 0.0
    return float(evaluate_quality_metric_in_initial_state(sim, metric))


def _g_after_transition(sim, metric, g: float, state, action, params, next_state) -> float:
    if metric is None:
        return g + 1.0
    return float(
        evaluate_quality_metric(sim, metric, g, state, action, params, next_state)
    )


def _action_base_name(action: up.model.Action) -> str:
    return action.name.split("_version")[0]


def serialize_plan_step(action: up.model.Action, params: tuple) -> dict[str, Any]:
    return {
        "action": _action_base_name(action),
        "params": [str(p) for p in params],
    }


def _reconstruct_plan(initial, goal, came_from: dict) -> list[dict[str, Any]]:
    if goal == initial:
        return []
    rev: list[dict[str, Any]] = []
    cur = goal
    while cur != initial:
        if cur not in came_from:
            raise RuntimeError("UCS came_from chain broken (missing predecessor)")
        prev, action, params = came_from[cur]
        rev.append(serialize_plan_step(action, params))
        cur = prev
    rev.reverse()
    return rev


def _object_by_name(problem: up.model.Problem, name: str):
    for o in problem.all_objects:
        if o.name == name:
            return o
    raise KeyError(f"object {name!r} not in problem")


def params_from_names(problem: up.model.Problem, param_names: list[str]) -> tuple:
    em = problem.environment.expression_manager
    return tuple(em.ObjectExp(_object_by_name(problem, n)) for n in param_names)


def replay_plan_on_gt(
    gt_problem: up.model.Problem,
    plan: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    if plan is None:
        return {
            "executable": False,
            "goal_reached": False,
            "steps_executed": 0,
            "reason": "no_plan",
        }
    if not plan:
        with SequentialSimulator(problem=gt_problem) as sim:
            state = sim.get_initial_state()
            return {
                "executable": True,
                "goal_reached": bool(sim.is_goal(state)),
                "steps_executed": 0,
                "reason": None,
            }

    with SequentialSimulator(problem=gt_problem) as sim:
        state = sim.get_initial_state()
        for i, step in enumerate(plan):
            name = step["action"]
            param_names = step["params"]
            try:
                base_action = gt_problem.action(name)
            except Exception as e:
                return {
                    "executable": False,
                    "goal_reached": False,
                    "steps_executed": i,
                    "reason": f"unknown_action:{name}:{e}",
                }
            try:
                params = params_from_names(gt_problem, param_names)
            except KeyError as e:
                return {
                    "executable": False,
                    "goal_reached": False,
                    "steps_executed": i,
                    "reason": f"bad_param:{e}",
                }
            if not sim.is_applicable(state, base_action, params):
                return {
                    "executable": False,
                    "goal_reached": False,
                    "steps_executed": i,
                    "reason": f"not_applicable_at_step_{i}",
                }
            nxt = sim.apply(state, base_action, params)
            if nxt is None:
                return {
                    "executable": False,
                    "goal_reached": False,
                    "steps_executed": i,
                    "reason": f"apply_failed_at_step_{i}",
                }
            state = nxt
        return {
            "executable": True,
            "goal_reached": bool(sim.is_goal(state)),
            "steps_executed": len(plan),
            "reason": None,
        }


def run_ucs(
    problem: up.model.Problem,
    *,
    max_expansions: int = 50_000,
    max_wall_sec: float | None = None,
    return_plan: bool = True,
) -> dict[str, Any]:
    # max_expansions <= 0 means no expansion cap (only wall timeout / empty frontier stop).
    wall0 = time.perf_counter()
    metric = _pick_metric(problem)
    metric_name = _metric_name(metric)

    def wall_exceeded() -> bool:
        return (
            max_wall_sec is not None
            and max_wall_sec > 0
            and (time.perf_counter() - wall0) >= max_wall_sec
        )

    def finish(outcome: str, **kw: Any) -> dict[str, Any]:
        base = {
            "outcome": outcome,
            "wall_time_sec": time.perf_counter() - wall0,
            "max_expansions": max_expansions,
            "max_wall_sec": max_wall_sec,
            "metric": metric_name,
        }
        base.update(kw)
        if not return_plan and "plan" in base:
            del base["plan"]
        return base

    with SequentialSimulator(problem=problem) as sim:
        initial = sim.get_initial_state()
        g0 = _initial_g(sim, metric)

        if sim.is_goal(initial):
            return finish(
                "SOLVED",
                optimal_cost=g0,
                expansions=0,
                iterations=0,
                nodes_generated=0,
                plan=[] if return_plan else None,
            )

        best_g: dict = {initial: g0}
        came_from: dict = {}
        tie = 0
        heap: list[tuple[float, int, object]] = [(g0, tie, initial)]
        tie += 1
        expansions = 0
        iterations = 0
        nodes_generated = 1  # initial on heap; +1 per improving successor push

        while heap:
            if wall_exceeded():
                return finish(
                    "ABORT_WALL_TIMEOUT",
                    optimal_cost=None,
                    expansions=expansions,
                    iterations=iterations,
                    nodes_generated=nodes_generated,
                    plan=None,
                )
            g, _, s = heapq.heappop(heap)
            iterations += 1
            bg = best_g.get(s)
            if bg is None or g > bg:
                continue
            if sim.is_goal(s):
                plan = _reconstruct_plan(initial, s, came_from) if return_plan else None
                return finish(
                    "SOLVED",
                    optimal_cost=g,
                    expansions=expansions,
                    iterations=iterations,
                    nodes_generated=nodes_generated,
                    plan=plan,
                )
            if max_expansions > 0 and expansions >= max_expansions:
                return finish(
                    "ABORT_MAX_EXPANSIONS",
                    optimal_cost=None,
                    expansions=expansions,
                    iterations=iterations,
                    nodes_generated=nodes_generated,
                    plan=None,
                )
            if wall_exceeded():
                return finish(
                    "ABORT_WALL_TIMEOUT",
                    optimal_cost=None,
                    expansions=expansions,
                    iterations=iterations,
                    nodes_generated=nodes_generated,
                    plan=None,
                )
            expansions += 1
            for action, params in sorted_applicable(sim, s):
                if wall_exceeded():
                    return finish(
                        "ABORT_WALL_TIMEOUT",
                        optimal_cost=None,
                        expansions=expansions,
                        iterations=iterations,
                        nodes_generated=nodes_generated,
                        plan=None,
                    )
                ns = sim.apply(s, action, params)
                g2 = _g_after_transition(sim, metric, g, s, action, params, ns)
                if g2 < best_g.get(ns, float("inf")):
                    best_g[ns] = g2
                    came_from[ns] = (s, action, params)
                    heapq.heappush(heap, (g2, tie, ns))
                    nodes_generated += 1
                    tie += 1

        return finish(
            "UNSOLVED_EMPTY_FRONTIER",
            optimal_cost=None,
            expansions=expansions,
            iterations=iterations,
            nodes_generated=nodes_generated,
            plan=None,
        )


def resolve_benchmark_problem(bench_dir: Path, problem_arg: str) -> Path:
    """Resolve ``--problem`` against ``<benchmarks-root>/<domain>/``.

    Accepts ``problems/problem-00.pddl`` or shorthand ``problem-00`` /
    ``problem-00.pddl`` (looks under ``problems/`` and adds ``.pddl`` as needed).
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
    raise SystemExit(2)
