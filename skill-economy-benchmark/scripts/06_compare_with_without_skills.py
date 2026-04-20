#!/usr/bin/env python3
"""Run with-skills vs no-skills experiments and summarize metric deltas.

This script intentionally excludes any skill-generation condition.
It focuses on two conditions aligned with the core research question:
  1) withskills  (original curated skills)
  2) noskills    (no skill folders)
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REAL_RUN_SCRIPT = PROJECT_ROOT / "scripts" / "05_run_real_evaluation.py"
DEFAULT_SKILLSBENCH_ROOT = Path("/local-data/xingqinghua/skillsbench")


def _run_condition(
    condition: str,
    task_root: Path,
    skillsbench_root: Path,
    agent: str,
    model: str | None,
    task_ids: str | None,
    attempts: int,
    force_build: bool,
    harbor_cmd: str | None,
) -> tuple[str, Path]:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    job_name = f"{condition}-{agent}-{timestamp}"
    report_path = PROJECT_ROOT / "results" / f"real_evaluation_report_{job_name}.json"

    cmd = [
        sys.executable,
        str(REAL_RUN_SCRIPT),
        "--skillsbench-root",
        str(skillsbench_root),
        "--tasks-root",
        str(task_root),
        "--job-name",
        job_name,
        "--agent",
        agent,
        "--attempts",
        str(max(1, attempts)),
    ]
    if model:
        cmd += ["--model", model]
    if task_ids:
        cmd += ["--task-ids", task_ids]
    if force_build:
        cmd += ["--force-build"]
    if harbor_cmd:
        cmd += ["--harbor-cmd", harbor_cmd]

    print(f"\n=== Running condition: {condition} ===")
    print(f"Tasks root: {task_root}")
    print(f"Command: {' '.join(cmd)}")
    try:
        subprocess.run(cmd, cwd=PROJECT_ROOT, check=True)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"Condition '{condition}' failed. Usually this means Harbor prerequisites are missing "
            f"(e.g. Docker not installed/running) or the job had infra-level failures."
        ) from exc

    return job_name, report_path


def _load_json(path: Path) -> dict[str, Any]:
    with open(path) as f:
        return json.load(f)


def _safe_get_metric(report: dict[str, Any], key: str) -> float:
    value = report.get("aggregated_metrics", {}).get(f"mean_{key}", 0.0)
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _build_summary(
    with_report: dict[str, Any],
    no_report: dict[str, Any],
    with_job_name: str,
    no_job_name: str,
) -> dict[str, Any]:
    metric_keys = [
        "token_efficiency",
        "step_redundancy",
        "skill_utilization_cost",
        "skill_combination_synergy",
        "cross_task_transferability",
        "failure_mode_specificity",
    ]

    deltas: dict[str, Any] = {}
    for key in metric_keys:
        with_v = _safe_get_metric(with_report, key)
        no_v = _safe_get_metric(no_report, key)
        deltas[key] = {
            "withskills": with_v,
            "noskills": no_v,
            "delta_with_minus_no": with_v - no_v,
        }

    with_summary = with_report.get("summary", {})
    no_summary = no_report.get("summary", {})

    return {
        "meta": {
            "generated_at": datetime.now().isoformat(),
            "withskills_job": with_job_name,
            "noskills_job": no_job_name,
            "protocol": "withskills_vs_noskills_only",
        },
        "success": {
            "withskills_success_rate": with_summary.get("success_rate", 0.0),
            "noskills_success_rate": no_summary.get("success_rate", 0.0),
            "delta_with_minus_no": float(with_summary.get("success_rate", 0.0)) - float(no_summary.get("success_rate", 0.0)),
            "withskills_total_tasks": with_summary.get("total_tasks", 0),
            "noskills_total_tasks": no_summary.get("total_tasks", 0),
        },
        "metrics": deltas,
        "failure_modes": {
            "withskills": with_summary.get("failure_mode_distribution", {}),
            "noskills": no_summary.get("failure_mode_distribution", {}),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare with-skills vs no-skills using our metrics")
    parser.add_argument("--skillsbench-root", type=Path, default=DEFAULT_SKILLSBENCH_ROOT,
                        help="Path to original SkillsBench repository")
    parser.add_argument("--withskills-tasks-root", type=Path, default=None,
                        help="Path to with-skills task dir (default: <skillsbench-root>/tasks)")
    parser.add_argument("--noskills-tasks-root", type=Path, default=None,
                        help="Path to no-skills task dir (default: <skillsbench-root>/tasks-no-skills)")
    parser.add_argument("--agent", type=str, default="oracle",
                        help="Harbor agent name (oracle/codex/claude-code...)")
    parser.add_argument("--model", type=str, default=None,
                        help="Model name for non-oracle agents")
    parser.add_argument("--task-ids", type=str, default=None,
                        help="Comma-separated task ids")
    parser.add_argument("--attempts", type=int, default=1,
                        help="Attempts per task")
    parser.add_argument("--force-build", action="store_true",
                        help="Force docker environment rebuild in Harbor")
    parser.add_argument("--harbor-cmd", type=str, default=None,
                        help="Custom Harbor launcher command, e.g. 'uvx harbor'")
    args = parser.parse_args()

    skillsbench_root = args.skillsbench_root.resolve()
    with_root = (args.withskills_tasks_root or (skillsbench_root / "tasks")).resolve()
    no_root = (args.noskills_tasks_root or (skillsbench_root / "tasks-no-skills")).resolve()

    with_job_name, with_report_path = _run_condition(
        condition="withskills",
        task_root=with_root,
        skillsbench_root=skillsbench_root,
        agent=args.agent,
        model=args.model,
        task_ids=args.task_ids,
        attempts=args.attempts,
        force_build=args.force_build,
        harbor_cmd=args.harbor_cmd,
    )

    no_job_name, no_report_path = _run_condition(
        condition="noskills",
        task_root=no_root,
        skillsbench_root=skillsbench_root,
        agent=args.agent,
        model=args.model,
        task_ids=args.task_ids,
        attempts=args.attempts,
        force_build=args.force_build,
        harbor_cmd=args.harbor_cmd,
    )

    with_report = _load_json(with_report_path)
    no_report = _load_json(no_report_path)
    summary = _build_summary(with_report, no_report, with_job_name, no_job_name)

    out_path = PROJECT_ROOT / "results" / f"compare_withskills_vs_noskills_{args.agent}_{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    out_path.write_text(json.dumps(summary, indent=2))

    print("\n=== Comparison Complete ===")
    print(f"With-skills report: {with_report_path}")
    print(f"No-skills report:   {no_report_path}")
    print(f"Comparison summary: {out_path}")
    print(f"Success delta (with - no): {summary['success']['delta_with_minus_no']:.4f}")
    print(
        "Synergy delta (with - no): "
        f"{summary['metrics']['skill_combination_synergy']['delta_with_minus_no']:.6f}"
    )
    print(
        "Transfer delta (with - no): "
        f"{summary['metrics']['cross_task_transferability']['delta_with_minus_no']:.6f}"
    )


if __name__ == "__main__":
    main()
