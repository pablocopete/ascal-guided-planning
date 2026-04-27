#!/usr/bin/env python3
"""
Scan results log directories (results_ascal_no_restart, results_ascal_restart, or results_blind) for coverage (post-loop sound) and runtime.

One CSV row per log; optional --domain filter; stdout per-domain summary.
"""
from __future__ import annotations

import argparse
import csv
import re
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_RESULTS_ROOT = Path(__file__).resolve().parent.parent / "results" / "results_ascal_no_restart"

RE_START_UTC = re.compile(r"^# start_utc:\s*(\S+)", re.MULTILINE)
RE_END_UTC = re.compile(r"^# end_utc:\s*(\S+)", re.MULTILINE)
RE_ARGV = re.compile(r"^# argv:\s*(.+)$", re.MULTILINE)
RE_POST_LOOP = re.compile(
    r"^\[sound model post-loop\]\s*plan_found=(True|False)\s+goal_on_gt=(True|False)\s*$",
    re.MULTILINE,
)
RE_ONLINE_LOOP = re.compile(
    r"^\[online loop\]\s+wall\s+([\d.]+)s\s+"
    r"\(outer iterations=(\d+),\s*stop_reason='([^']+)',\s*goal_reached=(True|False)\)\s*$",
    re.MULTILINE,
)
RE_TIMING_SUMMARY = re.compile(
    r"^\[timing summary\]\s+total plan_model_export=([\d.]+)s\s+"
    r"total plan_solve=([\d.]+)s",
    re.MULTILINE,
)
RE_PLANNING_ACTIONS = re.compile(
    r"^Planning actions \([^)]+\):\s*(\d+)\s*$", re.MULTILINE
)
RE_SUMMARY_INTS = {
    "plan_found": re.compile(r"'plan_found':\s*(\d+)"),
    "plan_found_sound": re.compile(r"'plan_found_sound':\s*(\d+)"),
    "plan_found_complete": re.compile(r"'plan_found_complete':\s*(\d+)"),
    "plan_found_version_space": re.compile(r"'plan_found_version_space':\s*(\d+)"),
    "plan_verified": re.compile(r"'plan_verified':\s*(\d+)"),
    "plan_spurious": re.compile(r"'plan_spurious':\s*(\d+)"),
    "no_plan": re.compile(r"'no_plan':\s*(\d+)"),
}
RE_LEARN_STEPS = re.compile(r"learn_steps\s+(\d+)")
RE_EXPORTED_END = re.compile(r"exported_UP_actions_end\s+(\d+)")
RE_STARTED = re.compile(r"\(started\s+(\d+)\)")


def _parse_bool(s: str) -> bool:
    return s == "True"


def _parse_iso_utc(s: str) -> datetime | None:
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _first_int(pattern: re.Pattern[str], text: str) -> str:
    m = pattern.search(text)
    return m.group(1) if m else ""


def parse_log(text: str) -> dict[str, str]:
    """Extract fields; use empty string for missing / not applicable."""
    row: dict[str, str] = {}

    m = RE_START_UTC.search(text)
    row["start_utc"] = m.group(1).strip() if m else ""

    m = RE_END_UTC.search(text)
    row["end_utc"] = m.group(1).strip() if m else ""

    row["complete"] = "1" if row["end_utc"] else "0"

    t0 = _parse_iso_utc(row["start_utc"]) if row["start_utc"] else None
    t1 = _parse_iso_utc(row["end_utc"]) if row["end_utc"] else None
    if t0 and t1:
        row["wall_total_s"] = f"{(t1 - t0).total_seconds():.3f}"
    else:
        row["wall_total_s"] = ""

    m = RE_ARGV.search(text)
    row["argv"] = m.group(1).strip() if m else ""

    m = RE_POST_LOOP.search(text)
    if m:
        pf, g = m.group(1), m.group(2)
        row["post_plan_found"] = pf
        row["post_goal_on_gt"] = g
        row["sound_success_gt"] = (
            "1" if (_parse_bool(pf) and _parse_bool(g)) else "0"
        )
    else:
        row["post_plan_found"] = ""
        row["post_goal_on_gt"] = ""
        row["sound_success_gt"] = ""

    m = RE_ONLINE_LOOP.search(text)
    if m:
        row["wall_loop_s"] = m.group(1)
        row["n_outer"] = m.group(2)
        row["stop_reason"] = m.group(3)
        row["goal_reached"] = m.group(4)
    else:
        row["wall_loop_s"] = ""
        row["n_outer"] = ""
        row["stop_reason"] = ""
        row["goal_reached"] = ""

    m = RE_TIMING_SUMMARY.search(text)
    if m:
        row["total_plan_export_s"] = m.group(1)
        row["total_plan_solve_s"] = m.group(2)
    else:
        row["total_plan_export_s"] = ""
        row["total_plan_solve_s"] = ""

    row["initial_planning_actions"] = _first_int(RE_PLANNING_ACTIONS, text)

    summary_block = text
    for key, pat in RE_SUMMARY_INTS.items():
        row[key] = _first_int(pat, summary_block)

    row["learn_steps"] = _first_int(RE_LEARN_STEPS, text)
    row["exported_up_actions_end"] = _first_int(RE_EXPORTED_END, text)
    row["initial_snapshot_started"] = _first_int(RE_STARTED, text)

    return row


CSV_FIELDS = [
    "domain",
    "problem",
    "log_path",
    "complete",
    "start_utc",
    "end_utc",
    "wall_total_s",
    "wall_loop_s",
    "n_outer",
    "stop_reason",
    "goal_reached",
    "post_plan_found",
    "post_goal_on_gt",
    "sound_success_gt",
    "total_plan_export_s",
    "total_plan_solve_s",
    "plan_found",
    "plan_found_sound",
    "plan_found_complete",
    "plan_found_version_space",
    "plan_verified",
    "plan_spurious",
    "no_plan",
    "learn_steps",
    "exported_up_actions_end",
    "initial_planning_actions",
    "initial_snapshot_started",
    "argv",
]


def collect_logs(root: Path, domain_filter: str | None) -> list[Path]:
    if domain_filter:
        d = root / domain_filter
        if not d.is_dir():
            print(f"error: not a directory: {d}", file=sys.stderr)
            sys.exit(2)
        return sorted(d.glob("*.log"))
    out: list[Path] = []
    for p in sorted(root.rglob("*.log")):
        if p.is_file():
            out.append(p)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Aggregate ASCAL / UCS results logs.")
    ap.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_RESULTS_ROOT,
        help=f"Results root directory (default: {DEFAULT_RESULTS_ROOT})",
    )
    ap.add_argument(
        "--domain",
        default=None,
        metavar="NAME",
        help="Only include logs under <root>/<NAME>/",
    )
    ap.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Write CSV here (default: stdout CSV-only if set; else table + no CSV)",
    )
    ap.add_argument(
        "--csv-only",
        action="store_true",
        help="Print CSV to stdout (no summary table).",
    )
    args = ap.parse_args()

    root = args.root.expanduser().resolve()
    if not root.is_dir():
        print(f"error: results root not found: {root}", file=sys.stderr)
        sys.exit(2)

    log_paths = collect_logs(root, args.domain)
    if not log_paths:
        print(f"warning: no .log files under {root}", file=sys.stderr)

    rows: list[dict[str, str]] = []
    for lp in log_paths:
        rel = lp.relative_to(root)
        domain = rel.parts[0] if len(rel.parts) > 1 else ""
        problem = lp.stem
        try:
            text = lp.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            print(f"warning: skip {lp}: {e}", file=sys.stderr)
            continue
        data = parse_log(text)
        data["domain"] = domain
        data["problem"] = problem
        data["log_path"] = str(lp.resolve())
        rows.append({k: data.get(k, "") for k in CSV_FIELDS})

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)

    if args.csv_only:
        w = csv.DictWriter(sys.stdout, fieldnames=CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
        return

    # Summary table by domain
    by_domain: dict[str, list[dict[str, str]]] = {}
    for r in rows:
        by_domain.setdefault(r["domain"], []).append(r)

    print("Per-domain summary (sound_success_gt = strict post-loop sound + GT goal)")
    print("-" * 72)
    for dom in sorted(by_domain.keys()):
        rs = by_domain[dom]
        n = len(rs)
        strict = sum(1 for x in rs if x.get("sound_success_gt") == "1")
        with_post = sum(1 for x in rs if x.get("post_plan_found") != "")
        no_post = n - with_post
        loops = [
            float(x["wall_loop_s"])
            for x in rs
            if x.get("wall_loop_s", "").strip()
        ]
        mean_loop = statistics.mean(loops) if loops else float("nan")
        med_loop = statistics.median(loops) if loops else float("nan")
        goals = sum(1 for x in rs if x.get("goal_reached") == "True")
        complete = sum(1 for x in rs if x.get("complete") == "1")
        print(
            f"  {dom:12}  n={n:3}  complete_logs={complete:3}  "
            f"loop_goal={goals:3}  sound_ok_gt={strict:3}/{n}  "
            f"(strict / all logs; missing post-loop line: {no_post})"
        )
        if loops:
            print(
                f"              wall_loop_s  mean={mean_loop:,.1f}s  "
                f"median={med_loop:,.1f}s"
            )
    print("-" * 72)
    if args.output:
        print(f"Wrote {len(rows)} rows to {args.output}")


if __name__ == "__main__":
    main()
