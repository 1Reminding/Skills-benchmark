"""Dummy agent that generates simulated ExecutionTraces for dry-run evaluation.

Supports both the simple sample_tasks.json format and the real SkillsBench dataset
tasks loaded via dataset_index.json.
"""

import random
from datetime import datetime, timedelta
from typing import List

from src.core.task import Task
from src.core.execution_trace import ExecutionTrace, SkillCall

HARDCODED_TRACES = {
    "task_001": dict(success=True, steps=2, total_tokens=150, calls=[
        ("code_write", 100, True), ("code_write", 50, True),
    ]),
    "task_002": dict(success=True, steps=5, total_tokens=400, calls=[
        ("code_read", 60, True), ("code_read", 60, True),
        ("debug", 120, True), ("code_write", 80, True), ("debug", 80, True),
    ]),
    "task_003": dict(success=False, steps=6, total_tokens=500, calls=[
        ("plan", 150, True), ("code_write", 100, True),
        ("plan", 100, False), ("code_write", 150, False),
    ], failure_reason="Bad Combination of plan and code_write"),
}

DATASET_SCENARIOS = {
    "weighted-gdp-calc": dict(success=True, steps=4, total_tokens=320, calls=[
        ("xlsx", 80, True), ("code_write", 100, True),
        ("xlsx", 80, True), ("code_read", 60, True),
    ]),
    "powerlifting-coef-calc": dict(success=True, steps=3, total_tokens=250, calls=[
        ("xlsx", 80, True), ("powerlifting", 30, True),
        ("senior-data-scientist", 140, True),
    ]),
    "fix-build-agentops": dict(success=True, steps=6, total_tokens=480, calls=[
        ("analyze-ci", 100, True), ("code_read", 40, True),
        ("testing-python", 90, True), ("debug", 100, True),
        ("uv-package-manager", 50, True), ("code_write", 100, True),
    ]),
    "sales-pivot-analysis": dict(success=True, steps=5, total_tokens=380, calls=[
        ("pdf", 60, True), ("xlsx", 80, True),
        ("code_write", 100, True), ("xlsx", 80, True), ("code_read", 60, True),
    ]),
    "earthquake-plate-calculation": dict(success=False, steps=7, total_tokens=550, calls=[
        ("geospatial-analysis", 120, True), ("code_write", 100, True),
        ("geospatial-analysis", 120, True), ("code_write", 100, False),
        ("debug", 110, False),
    ], failure_reason="Missing skill: needed advanced projection handling"),
    "latex-formula-extraction": dict(success=True, steps=4, total_tokens=300, calls=[
        ("pdf", 60, True), ("marker", 70, True),
        ("code_write", 100, True), ("code_read", 70, True),
    ]),
}


def _build_trace(task: Task, scenario: dict) -> ExecutionTrace:
    start = datetime(2026, 4, 12, 10, 0, 0)
    skill_calls = [
        SkillCall(
            skill_name=name,
            input_params={"action": f"invoke {name}"},
            output=f"{name} completed" if ok else f"{name} failed",
            token_used=tokens,
            time_cost_ms=float(tokens * 3),
            success=ok,
        )
        for name, tokens, ok in scenario["calls"]
    ]
    return ExecutionTrace(
        task_id=task.task_id,
        agent_name="DummyAgent",
        start_time=start,
        end_time=start + timedelta(seconds=scenario["steps"] * 2),
        total_tokens=scenario["total_tokens"],
        steps_taken=scenario["steps"],
        skill_calls=skill_calls,
        task_success=scenario["success"],
        failure_reason=scenario.get("failure_reason"),
    )


def _generate_fallback_trace(task: Task) -> ExecutionTrace:
    """Generate a plausible trace for any unknown task based on its metadata."""
    random.seed(hash(task.task_id))
    n_skills = len(task.required_skills)
    success = random.random() > 0.3
    steps = task.optimal_steps + random.randint(0, 3)
    base_tokens = 80 * n_skills + random.randint(50, 200)

    calls = []
    for s in task.required_skills:
        calls.append((s, random.randint(40, 120), success or random.random() > 0.5))
    if not success and n_skills > 0:
        calls.append((task.required_skills[0], random.randint(40, 80), False))

    return _build_trace(task, dict(
        success=success,
        steps=steps,
        total_tokens=base_tokens,
        calls=calls,
        failure_reason=None if success else "Simulated failure for unknown task",
    ))


def run_dummy_agent(tasks: List[Task]) -> List[ExecutionTrace]:
    traces: List[ExecutionTrace] = []
    for task in tasks:
        if task.task_id in HARDCODED_TRACES:
            traces.append(_build_trace(task, HARDCODED_TRACES[task.task_id]))
        elif task.task_id in DATASET_SCENARIOS:
            traces.append(_build_trace(task, DATASET_SCENARIOS[task.task_id]))
        else:
            traces.append(_generate_fallback_trace(task))
    return traces
