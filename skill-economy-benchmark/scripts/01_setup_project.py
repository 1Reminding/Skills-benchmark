#!/usr/bin/env python3
"""Validate that the project directory structure is complete."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

REQUIRED_DIRS = [
    "src/core",
    "src/metrics/economy",
    "src/metrics/effectiveness",
    "src/evaluators",
    "src/agents",
    "src/utils",
    "docs",
    "data/raw",
    "data/processed",
    "data/skill_taxonomy",
    "scripts",
    "tests",
    "results",
]

REQUIRED_FILES = [
    "pyproject.toml",
    "requirements.txt",
    "README.md",
    "src/core/task.py",
    "src/core/skill.py",
    "src/core/execution_trace.py",
    "src/metrics/base_metric.py",
    "src/metrics/economy/token_efficiency.py",
    "src/metrics/economy/step_redundancy.py",
    "src/metrics/economy/skill_cost.py",
    "src/metrics/effectiveness/skill_synergy.py",
    "src/metrics/effectiveness/transferability.py",
    "src/metrics/effectiveness/failure_analysis.py",
    "src/evaluators/trace_evaluator.py",
    "src/evaluators/report_generator.py",
    "src/agents/dummy_agent.py",
    "src/utils/data_loader.py",
    "src/utils/visualization.py",
    "data/skill_taxonomy/base_skills.json",
    "data/raw/sample_tasks.json",
    "docs/research_proposal.md",
    "docs/metrics_definition.md",
]


def main() -> None:
    ok = True
    for d in REQUIRED_DIRS:
        p = PROJECT_ROOT / d
        if not p.is_dir():
            print(f"MISSING DIR:  {d}")
            ok = False

    for f in REQUIRED_FILES:
        p = PROJECT_ROOT / f
        if not p.is_file():
            print(f"MISSING FILE: {f}")
            ok = False

    if ok:
        print("All directories and files present. Project structure is valid.")
    else:
        print("\nSome items are missing. Please fix before continuing.")
        sys.exit(1)


if __name__ == "__main__":
    main()
