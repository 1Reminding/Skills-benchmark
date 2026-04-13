#!/usr/bin/env python3
"""Generate sample task data and run the dummy agent to produce execution traces."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils.data_loader import load_tasks, load_skill_registry
from src.agents.dummy_agent import run_dummy_agent

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TASKS_PATH = PROJECT_ROOT / "data" / "raw" / "sample_tasks.json"
SKILLS_PATH = PROJECT_ROOT / "data" / "skill_taxonomy" / "base_skills.json"
TRACES_OUTPUT = PROJECT_ROOT / "data" / "processed" / "dummy_traces.json"


def main() -> None:
    print(f"Loading tasks from {TASKS_PATH} ...")
    tasks = load_tasks(TASKS_PATH)
    print(f"  Loaded {len(tasks)} tasks")

    print(f"Loading skill registry from {SKILLS_PATH} ...")
    registry = load_skill_registry(SKILLS_PATH)
    print(f"  Loaded {len(registry.skills)} skills")

    print("Running DummyAgent ...")
    traces = run_dummy_agent(tasks)
    print(f"  Generated {len(traces)} execution traces")

    TRACES_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    traces_data = [t.model_dump(mode="json") for t in traces]
    with open(TRACES_OUTPUT, "w") as f:
        json.dump({"traces": traces_data}, f, indent=2, default=str)
    print(f"  Traces saved to {TRACES_OUTPUT}")

    for trace in traces:
        status = "PASS" if trace.task_success else "FAIL"
        print(f"  [{status}] {trace.task_id}: {trace.steps_taken} steps, "
              f"{trace.total_tokens} tokens")


if __name__ == "__main__":
    main()
