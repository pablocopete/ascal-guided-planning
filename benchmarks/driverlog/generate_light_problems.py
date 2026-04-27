#!/usr/bin/env python3
"""Generate benchmarks/driverlog/problems/problem-00..19 (light suite).

Tuned on the full IPC driverlog benchmark (>>2h, ~132 actions).
Caps: <=4 store locations, no pedestrian mesh, max 2 drivers / 2 trucks / 3 packages
(no 3-driver fleets). Domain: dlog_3_3_3_problem_problem-domain.
"""
from __future__ import annotations

import os

OUT = os.path.join(os.path.dirname(__file__), "problems")
DOMAIN = "dlog_3_3_3_problem_problem-domain"


def line_locs(n: int) -> list[str]:
    return [f"s{i}" for i in range(n)]


def line_edges(n: int) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    links: list[tuple[str, str]] = []
    paths: list[tuple[str, str]] = []
    for i in range(n - 1):
        a, b = f"s{i}", f"s{i + 1}"
        links.extend([(a, b), (b, a)])
        paths.extend([(a, b), (b, a)])
    return links, paths


def add_edge(
    links: list[tuple[str, str]],
    paths: list[tuple[str, str]],
    a: str,
    b: str,
) -> None:
    links.extend([(a, b), (b, a)])
    paths.extend([(a, b), (b, a)])


def fmt_objects(locs: list[str], nd: int, nt: int, np: int) -> str:
    drivers = " ".join(f"driver{i}" for i in range(1, nd + 1))
    trucks = " ".join(f"truck{i}" for i in range(1, nt + 1))
    pkgs = " ".join(f"package{i}" for i in range(1, np + 1))
    loc_line = " ".join(locs)
    return f"""   {loc_line} - location
   {drivers} - driver
   {trucks} - truck
   {pkgs} - obj"""


def fmt_init(
    driver_at: list[tuple[int, int]],
    truck_at: list[tuple[int, int]],
    pkg_at: list[tuple[int, int]],
    links: list[tuple[str, str]],
    paths: list[tuple[str, str]],
) -> str:
    def L(i: int) -> str:
        return f"s{i}"

    parts: list[str] = []
    for di, li in driver_at:
        parts.append(f"(at_ driver{di} {L(li)})")
    for ti, li in truck_at:
        parts.append(f"(at_ truck{ti} {L(li)})")
        parts.append(f"(empty truck{ti})")
    for pi, li in pkg_at:
        parts.append(f"(at_ package{pi} {L(li)})")
    for a, b in links:
        parts.append(f"(link {a} {b})")
    for a, b in paths:
        parts.append(f"(path {a} {b})")
    return " ".join(parts)


def fmt_goal(conjuncts: list[str]) -> str:
    return "(and " + " ".join(conjuncts) + ")"


def write(idx: int, locs: list[str], body_init: str, goal_parts: list[str]) -> None:
    num = f"{idx:02d}"
    path = os.path.join(OUT, f"problem-{num}.pddl")
    text = f"""(define (problem dlog_light_{num})
 (:domain {DOMAIN})
 (:objects
{fmt_objects(locs, *fleet_sizes[idx])}
 )
 (:init {body_init})
 (:goal {fmt_goal(goal_parts)})
)
"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


# (ndrivers, ntrucks, npackages) — never 3 drivers (IPC-style blow-up)
fleet_sizes: list[tuple[int, int, int]] = [
    (1, 1, 1),
    (1, 1, 2),
    (1, 1, 1),
    (1, 1, 2),
    (2, 2, 2),
    (1, 1, 1),
    (1, 1, 2),
    (2, 2, 2),
    (2, 2, 3),
    (2, 2, 2),
    (2, 2, 2),
    (2, 2, 3),
    (2, 2, 3),
    (2, 2, 3),
    (2, 2, 3),
    (2, 2, 3),
    (2, 2, 2),
    (2, 2, 3),
    (2, 2, 3),
    (2, 2, 3),
]


def main() -> None:
    os.makedirs(OUT, exist_ok=True)

    # 00–01: 2 locs
    n = 2
    locs = line_locs(n)
    lk, pt = line_edges(n)
    init = fmt_init([(1, 0)], [(1, 0)], [(1, 0)], lk, pt)
    write(0, locs, init, ["(at_ package1 s1)"])
    init = fmt_init([(1, 0)], [(1, 0)], [(1, 0), (2, 1)], lk, pt)
    write(1, locs, init, ["(at_ package1 s1)", "(at_ package2 s0)"])

    # 02–04: 3 locs
    n = 3
    locs = line_locs(n)
    lk, pt = line_edges(n)
    init = fmt_init([(1, 0)], [(1, 0)], [(1, 0)], lk, pt)
    write(2, locs, init, ["(at_ package1 s2)"])
    init = fmt_init([(1, 0)], [(1, 0)], [(1, 0), (2, 1)], lk, pt)
    write(3, locs, init, ["(at_ package1 s2)", "(at_ package2 s2)"])
    init = fmt_init([(1, 0), (2, 2)], [(1, 0), (2, 2)], [(1, 0), (2, 2)], lk, pt)
    write(4, locs, init, ["(at_ package1 s2)", "(at_ package2 s0)"])

    # 05–19: 4 locs (line); optional shortcut s0–s2 on hardest three
    n = 4
    locs = line_locs(n)
    lk, pt = line_edges(n)
    init = fmt_init([(1, 0)], [(1, 0)], [(1, 0)], lk, pt)
    write(5, locs, init, ["(at_ package1 s3)"])
    init = fmt_init([(1, 0)], [(1, 0)], [(1, 0), (2, 3)], lk, pt)
    write(6, locs, init, ["(at_ package1 s3)", "(at_ package2 s0)"])
    init = fmt_init([(1, 0), (2, 3)], [(1, 0), (2, 3)], [(1, 1), (2, 2)], lk, pt)
    write(7, locs, init, ["(at_ package1 s3)", "(at_ package2 s0)"])
    init = fmt_init([(1, 0), (2, 2)], [(1, 0), (2, 2)], [(1, 0), (2, 1), (3, 3)], lk, pt)
    write(
        8,
        locs,
        init,
        ["(at_ package1 s2)", "(at_ package2 s3)", "(at_ package3 s1)"],
    )
    init = fmt_init([(1, 0)], [(1, 0)], [(1, 1), (2, 2)], lk, pt)
    write(9, locs, init, ["(at_ package1 s3)", "(at_ package2 s3)"])
    init = fmt_init([(1, 0), (2, 3)], [(1, 0), (2, 3)], [(1, 2), (2, 1)], lk, pt)
    write(10, locs, init, ["(at_ package1 s0)", "(at_ package2 s3)"])
    init = fmt_init([(1, 0), (2, 3)], [(1, 0), (2, 3)], [(1, 1), (2, 2), (3, 0)], lk, pt)
    write(
        11,
        locs,
        init,
        ["(at_ package1 s3)", "(at_ package2 s0)", "(at_ package3 s2)"],
    )
    init = fmt_init([(1, 0), (2, 2)], [(1, 0), (2, 2)], [(1, 1), (2, 3), (3, 0)], lk, pt)
    write(
        12,
        locs,
        init,
        [
            "(at_ driver1 s2)",
            "(at_ truck2 s1)",
            "(at_ package1 s3)",
            "(at_ package2 s0)",
            "(at_ package3 s1)",
        ],
    )
    init = fmt_init([(1, 0), (2, 3)], [(1, 0), (2, 3)], [(1, 1), (2, 2), (3, 0)], lk, pt)
    write(
        13,
        locs,
        init,
        ["(at_ package1 s3)", "(at_ package2 s0)", "(at_ package3 s2)"],
    )
    init = fmt_init([(1, 1), (2, 2)], [(1, 1), (2, 2)], [(1, 0), (2, 3), (3, 1)], lk, pt)
    write(
        14,
        locs,
        init,
        [
            "(at_ package1 s3)",
            "(at_ package2 s0)",
            "(at_ package3 s2)",
            "(at_ truck1 s0)",
        ],
    )
    init = fmt_init([(1, 0), (2, 3)], [(1, 0), (2, 2)], [(1, 1), (2, 0), (3, 2)], lk, pt)
    write(
        15,
        locs,
        init,
        [
            "(at_ driver1 s3)",
            "(at_ package1 s2)",
            "(at_ package2 s3)",
            "(at_ package3 s0)",
        ],
    )
    init = fmt_init([(1, 0), (2, 3)], [(1, 0), (2, 3)], [(1, 1), (2, 0)], lk, pt)
    write(16, locs, init, ["(at_ package1 s3)", "(at_ package2 s0)"])

    # 17–19: same 4 locs + chord s0–s2 (shorter drives, still small graph)
    lk, pt = line_edges(n)
    add_edge(lk, pt, "s0", "s2")
    init = fmt_init([(1, 0), (2, 3)], [(1, 0), (2, 3)], [(1, 1), (2, 2), (3, 0)], lk, pt)
    write(
        17,
        locs,
        init,
        [
            "(at_ package1 s3)",
            "(at_ package2 s0)",
            "(at_ package3 s2)",
            "(at_ truck1 s1)",
        ],
    )
    init = fmt_init([(1, 0), (2, 2)], [(1, 0), (2, 2)], [(1, 3), (2, 0), (3, 1)], lk, pt)
    write(
        18,
        locs,
        init,
        [
            "(at_ driver2 s3)",
            "(at_ package1 s0)",
            "(at_ package2 s2)",
            "(at_ package3 s3)",
        ],
    )
    init = fmt_init([(1, 1), (2, 3)], [(1, 1), (2, 3)], [(1, 0), (2, 2), (3, 1)], lk, pt)
    write(
        19,
        locs,
        init,
        [
            "(at_ truck2 s0)",
            "(at_ package1 s3)",
            "(at_ package2 s1)",
            "(at_ package3 s0)",
        ],
    )

    print(f"Wrote problem-00..19 into {OUT}")


if __name__ == "__main__":
    main()
