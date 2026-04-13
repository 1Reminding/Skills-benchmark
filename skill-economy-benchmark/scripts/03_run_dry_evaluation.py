#!/usr/bin/env python3
"""Run the full dry-run evaluation pipeline: load data, compute metrics, generate report.

Supports two modes:
  --dataset   Use the real SkillsBench dataset from dataset/dataset_index.json
  --sample    Use the simple sample data from data/raw/sample_tasks.json (default)
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils.data_loader import load_tasks, load_skill_registry, load_dataset_index
from src.agents.dummy_agent import run_dummy_agent
from src.evaluators.trace_evaluator import TraceEvaluator
from src.evaluators.report_generator import generate_report

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    parser = argparse.ArgumentParser(description="Skill Economy Benchmark - Dry Run Evaluation")
    parser.add_argument("--dataset", action="store_true",
                        help="Use real SkillsBench dataset (dataset/dataset_index.json)")
    parser.add_argument("--sample", action="store_true", default=True,
                        help="Use simple sample data (default)")
    args = parser.parse_args()

    use_dataset = args.dataset

    print("=" * 60)
    print("  Skill Economy Benchmark - Dry Run Evaluation")
    print("=" * 60)

    if use_dataset:
        index_path = PROJECT_ROOT / "dataset" / "dataset_index.json"
        report_output = PROJECT_ROOT / "results" / "dataset_evaluation_report.json"
        print(f"\n[1/4] Loading dataset from {index_path} ...")
        tasks, registry = load_dataset_index(index_path)
    else:
        tasks_path = PROJECT_ROOT / "data" / "raw" / "sample_tasks.json"
        skills_path = PROJECT_ROOT / "data" / "skill_taxonomy" / "base_skills.json"
        report_output = PROJECT_ROOT / "results" / "evaluation_report.json"
        print(f"\n[1/4] Loading sample data ...")
        tasks = load_tasks(tasks_path)
        registry = load_skill_registry(skills_path)

    print(f"  {len(tasks)} tasks, {len(registry.skills)} skills loaded")

    print("\n[2/4] Running DummyAgent ...")
    traces = run_dummy_agent(tasks)
    print(f"  {len(traces)} traces generated")

    print("\n[3/4] Computing metrics ...")
    evaluator = TraceEvaluator(skill_registry=registry)
    results = evaluator.evaluate_all(traces, tasks)

    for r in results:
        status = "PASS" if r["task_success"] else "FAIL"
        print(f"\n  [{status}] {r['task_id']} (mode: {r['failure_mode']})")
        for k, v in r["metrics"].items():
            print(f"    {k}: {v:.6f}")

    print("\n[4/4] Generating report ...")
    report = generate_report(results, report_output)

    print(f"\n  Report saved to {report_output}")
    print(f"\n  Summary:")
    summary = report["summary"]
    print(f"    Total tasks:      {summary['total_tasks']}")
    print(f"    Successful:       {summary['successful_tasks']}")
    print(f"    Success rate:     {summary['success_rate']:.2%}")
    print(f"    Failure modes:    {summary['failure_mode_distribution']}")

    print(f"\n  Aggregated Metrics:")
    for k, v in report["aggregated_metrics"].items():
        print(f"    {k}: {v:.6f}")

    print("\n" + "=" * 60)
    print("  Evaluation complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
