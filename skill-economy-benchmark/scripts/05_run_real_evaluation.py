#!/usr/bin/env python3
"""Run real SkillsBench tasks with Harbor and evaluate traces with our metrics.

This script bridges:
1) Harbor real execution (`skillsbench` repository)
2) SkillsBench job outputs (`jobs/<job>/<trial>/result.json`)
3) Our metric evaluator/report generator in this repository.
"""

import argparse
import json
import shlex
import shutil
import subprocess
import sys
import tomllib
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.task import Task
from src.evaluators.report_generator import generate_report
from src.evaluators.trace_evaluator import TraceEvaluator
from src.utils.data_loader import load_dataset_index
from src.utils.harbor_results_parser import parse_harbor_job_to_traces

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SKILLSBENCH_ROOT = Path("/local-data/xingqinghua/skillsbench")
DEFAULT_JOBS_DIR = PROJECT_ROOT / "results" / "harbor_jobs"
INFRA_ERROR_KEYWORDS = (
    "no such file or directory: 'docker'",
    "docker is not installed",
    "cannot connect to the docker daemon",
    "docker daemon",
)


def _default_job_name(agent_name: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"realrun-{agent_name}-{timestamp}"


def _build_harbor_config(
    job_name: str,
    jobs_dir: Path,
    tasks_root: Path,
    task_names: list[str],
    agent_name: str,
    model_name: str | None,
    n_attempts: int,
    force_build: bool,
) -> str:
    task_lines = "\n".join([f"  - {t}" for t in task_names]) if task_names else "  - null"
    model_yaml = "null" if not model_name else model_name

    return f"""job_name: {job_name}
jobs_dir: {jobs_dir}
n_attempts: {n_attempts}
timeout_multiplier: 1.0
debug: false
orchestrator:
  type: local
  n_concurrent_trials: 1
  quiet: false
  retry:
    max_retries: 1
    include_exceptions: null
    exclude_exceptions: []
    wait_multiplier: 1.0
    min_wait_sec: 1.0
    max_wait_sec: 30.0
  kwargs: {{}}
environment:
  type: docker
  import_path: null
  force_build: {"true" if force_build else "false"}
  delete: true
  override_cpus: null
  override_memory_mb: null
  override_storage_mb: null
  override_gpus: null
  kwargs: {{}}
verifier:
  override_timeout_sec: null
  max_timeout_sec: null
  disable: false
metrics: []
agents:
- name: {agent_name}
  import_path: null
  model_name: {model_yaml}
  override_timeout_sec: null
  override_setup_timeout_sec: null
  max_timeout_sec: null
  kwargs: {{}}
datasets:
- task_names:
{task_lines}
  exclude_task_names: []
  path: {tasks_root}
"""


def _resolve_harbor_commands(harbor_cmd: str | None) -> list[list[str]]:
    if harbor_cmd:
        return [shlex.split(harbor_cmd) + ["run"]]

    candidates: list[list[str]] = []
    if shutil.which("harbor"):
        candidates.append(["harbor", "run"])
    if shutil.which("uvx"):
        candidates.append(["uvx", "harbor", "run"])
    if shutil.which("uv"):
        candidates.append(["uv", "run", "harbor", "run"])
    return candidates


def _select_tasks(all_tasks: list[str], selected: list[str] | None) -> list[str]:
    if not selected:
        return all_tasks
    deduped: list[str] = []
    seen: set[str] = set()
    for task_id in selected:
        if task_id not in seen:
            deduped.append(task_id)
            seen.add(task_id)
    return deduped


def _build_external_task(tasks_root: Path, task_id: str) -> Task | None:
    task_dir = tasks_root / task_id
    task_toml_path = task_dir / "task.toml"
    instruction_path = task_dir / "instruction.md"
    if not task_toml_path.exists() or not instruction_path.exists():
        return None

    metadata: dict = {}
    try:
        with open(task_toml_path, "rb") as f:
            toml_data = tomllib.load(f)
        metadata = toml_data.get("metadata", {}) if isinstance(toml_data, dict) else {}
    except Exception:
        metadata = {}

    skill_names: list[str] = []
    skills_dir = task_dir / "environment" / "skills"
    if skills_dir.is_dir():
        skill_names = sorted([p.name for p in skills_dir.iterdir() if p.is_dir()])

    return Task(
        task_id=task_id,
        domain=str(metadata.get("category", "unknown")),
        instruction=instruction_path.read_text(),
        required_skills=skill_names,
        optimal_steps=1,
        verification_code=f"# external task from {task_id}",
        metadata={
            "difficulty": metadata.get("difficulty", "unknown"),
            "tags": metadata.get("tags", []),
            "source": "skillsbench_external",
        },
    )


def _is_infrastructure_failure(reason: str | None) -> bool:
    if not reason:
        return False
    normalized = reason.strip().lower()
    return any(keyword in normalized for keyword in INFRA_ERROR_KEYWORDS)


def _validate_runtime_prerequisites(skip_run: bool) -> None:
    if skip_run:
        return
    if shutil.which("docker") is not None:
        return
    print("[ERROR] Docker is required for SkillsBench Harbor runs but was not found in PATH.")
    print("        Install/start Docker first, then rerun this script.")
    print("        Tip: use '--skip-run' only when parsing an already-completed valid Harbor job.")
    sys.exit(2)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run real SkillsBench tasks and evaluate with Skill Economy metrics")
    parser.add_argument("--skillsbench-root", type=Path, default=DEFAULT_SKILLSBENCH_ROOT,
                        help="Path to original SkillsBench repository")
    parser.add_argument("--tasks-root", type=Path, default=None,
                        help="Path to task directory inside SkillsBench (default: <skillsbench-root>/tasks)")
    parser.add_argument("--jobs-dir", type=Path, default=DEFAULT_JOBS_DIR,
                        help="Directory where Harbor writes jobs")
    parser.add_argument("--job-name", type=str, default=None,
                        help="Harbor job name (default: auto timestamp)")
    parser.add_argument("--agent", type=str, default="oracle",
                        help="Harbor agent name (e.g. oracle, codex, claude-code)")
    parser.add_argument("--model", type=str, default=None,
                        help="Model name for non-oracle agents (e.g. openai/gpt-5.2-codex)")
    parser.add_argument("--attempts", type=int, default=1,
                        help="Number of attempts per task")
    parser.add_argument("--task-ids", type=str, default=None,
                        help="Comma-separated task ids; default is all tasks in dataset/dataset_index.json")
    parser.add_argument("--skip-run", action="store_true",
                        help="Skip Harbor execution and only parse existing job outputs")
    parser.add_argument("--force-build", action="store_true",
                        help="Force docker environment rebuild in Harbor")
    parser.add_argument("--harbor-cmd", type=str, default=None,
                        help="Custom Harbor launcher command, e.g. 'uvx harbor' or '/path/to/harbor'")
    args = parser.parse_args()
    _validate_runtime_prerequisites(args.skip_run)

    index_path = PROJECT_ROOT / "dataset" / "dataset_index.json"
    tasks, registry = load_dataset_index(index_path)
    all_task_ids = [t.task_id for t in tasks]
    all_task_id_set = set(all_task_ids)

    selected_input = None
    if args.task_ids:
        selected_input = [s.strip() for s in args.task_ids.split(",") if s.strip()]
    selected_task_ids = _select_tasks(all_task_ids, selected_input)
    if not selected_task_ids:
        print("[ERROR] No valid tasks selected.")
        sys.exit(1)

    skillsbench_root = args.skillsbench_root.resolve()
    tasks_root = (args.tasks_root or (skillsbench_root / "tasks")).resolve()
    jobs_dir = args.jobs_dir.resolve()
    jobs_dir.mkdir(parents=True, exist_ok=True)

    job_name = args.job_name or _default_job_name(args.agent)
    job_dir = jobs_dir / job_name

    print("=" * 72)
    print("  Skill Economy Benchmark - Real Run Evaluation")
    print("=" * 72)
    print(f"SkillsBench repo: {skillsbench_root}")
    print(f"Tasks root:       {tasks_root}")
    in_index = [t for t in selected_task_ids if t in all_task_id_set]
    external = [t for t in selected_task_ids if t not in all_task_id_set]
    print(f"Selected tasks:   {len(selected_task_ids)} (index={len(in_index)}, external={len(external)})")
    print(f"Agent:            {args.agent}")
    print(f"Job name:         {job_name}")
    print(f"Jobs dir:         {jobs_dir}")
    print(f"Skip Harbor run:  {args.skip_run}")

    if not args.skip_run:
        config_dir = PROJECT_ROOT / "results" / "harbor_configs"
        config_dir.mkdir(parents=True, exist_ok=True)
        config_path = config_dir / f"{job_name}.yaml"
        config_text = _build_harbor_config(
            job_name=job_name,
            jobs_dir=jobs_dir,
            tasks_root=tasks_root,
            task_names=selected_task_ids,
            agent_name=args.agent,
            model_name=args.model,
            n_attempts=max(1, args.attempts),
            force_build=args.force_build,
        )
        config_path.write_text(config_text)
        print(f"\n[1/3] Harbor config written: {config_path}")

        harbor_bases = _resolve_harbor_commands(args.harbor_cmd)
        if not harbor_bases:
            print("[ERROR] No Harbor launcher found.")
            print("  Try one of:")
            print("  1) uv tool install harbor")
            print("  2) uvx harbor run -c <config.yaml>")
            print("  3) python script with --harbor-cmd 'uvx harbor'")
            sys.exit(1)

        print("[2/3] Running Harbor ...")
        last_error: Exception | None = None
        for base in harbor_bases:
            cmd = base + ["-c", str(config_path)]
            print(f"  Trying: {' '.join(cmd)}")
            try:
                subprocess.run(cmd, cwd=skillsbench_root, check=True)
                last_error = None
                break
            except FileNotFoundError as exc:
                last_error = exc
                continue
            except subprocess.CalledProcessError as exc:
                last_error = exc
                continue

        if last_error is not None:
            print("[ERROR] Harbor run failed with all launcher candidates.")
            print("  Tried:")
            for base in harbor_bases:
                print(f"    - {' '.join(base)} -c <config>")
            print(f"  Last error: {last_error}")
            sys.exit(1)

    print(f"\n[3/3] Parsing Harbor results from: {job_dir}")
    traces = parse_harbor_job_to_traces(job_dir)
    if not traces:
        print("[ERROR] No trial traces parsed from Harbor job output.")
        print("        Confirm Harbor completed and trial folders contain result.json.")
        sys.exit(1)
    print(f"  Parsed {len(traces)} traces")

    selected_task_id_set = set(selected_task_ids)
    selected_task_map = {t.task_id: t for t in tasks if t.task_id in selected_task_id_set}
    for task_id in external:
        ext_task = _build_external_task(tasks_root, task_id)
        if ext_task is None:
            print(f"[WARN] external task metadata not found, skipping: {task_id}")
            continue
        selected_task_map[task_id] = ext_task

    filtered_tasks = list(selected_task_map.values())
    filtered_traces = [tr for tr in traces if tr.task_id in selected_task_map]
    if not filtered_traces:
        print("[ERROR] No parsed traces match selected task ids.")
        sys.exit(1)

    infra_failures = [tr for tr in filtered_traces if (not tr.task_success and _is_infrastructure_failure(tr.failure_reason))]
    if infra_failures:
        print("[WARN] Detected infrastructure-level failures in parsed traces:")
        for tr in infra_failures[:5]:
            print(f"  - {tr.task_id}: {tr.failure_reason}")
        if len(infra_failures) == len(filtered_traces):
            print("[ERROR] All selected traces failed before real task execution.")
            print("        This run is invalid for skill evaluation; refusing to generate a misleading 0-score report.")
            sys.exit(2)
        print("       Continuing with mixed results, but metrics may be biased.")

    evaluator = TraceEvaluator(skill_registry=registry)
    task_results = evaluator.evaluate_all(filtered_traces, filtered_tasks)

    report_path = PROJECT_ROOT / "results" / f"real_evaluation_report_{job_name}.json"
    report = generate_report(task_results, report_path)

    traces_path = PROJECT_ROOT / "results" / f"real_traces_{job_name}.json"
    traces_path.write_text(
        json.dumps({"traces": [t.model_dump(mode="json") for t in filtered_traces]}, indent=2, default=str)
    )

    summary = report["summary"]
    print("\nDone.")
    print(f"  Report: {report_path}")
    print(f"  Traces: {traces_path}")
    print(f"  Success rate: {summary['success_rate']:.2%} ({summary['successful_tasks']}/{summary['total_tasks']})")
    print(f"  Failure modes: {summary['failure_mode_distribution']}")


if __name__ == "__main__":
    main()
