"""End-to-end dry run test: load -> agent -> evaluate -> report."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils.data_loader import load_tasks, load_skill_registry
from src.agents.dummy_agent import run_dummy_agent
from src.evaluators.trace_evaluator import TraceEvaluator
from src.evaluators.report_generator import generate_report

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TASKS_PATH = PROJECT_ROOT / "data" / "raw" / "sample_tasks.json"
SKILLS_PATH = PROJECT_ROOT / "data" / "skill_taxonomy" / "base_skills.json"
REPORT_OUTPUT = PROJECT_ROOT / "results" / "test_evaluation_report.json"


class TestEndToEnd:
    def test_full_pipeline(self):
        tasks = load_tasks(TASKS_PATH)
        assert len(tasks) == 3

        registry = load_skill_registry(SKILLS_PATH)
        assert len(registry.skills) == 5

        traces = run_dummy_agent(tasks)
        assert len(traces) == 3

        evaluator = TraceEvaluator(skill_registry=registry)
        results = evaluator.evaluate_all(traces, tasks)
        assert len(results) == 3

        report = generate_report(results, REPORT_OUTPUT)

        assert report["summary"]["total_tasks"] == 3
        assert report["summary"]["successful_tasks"] == 2
        assert report["summary"]["success_rate"] > 0

        for r in results:
            m = r["metrics"]
            assert m["token_efficiency"] >= 0
            assert m["step_redundancy"] >= 0
            assert m["skill_utilization_cost"] >= 0
            assert m["failure_mode_specificity"] >= 0

    def test_task1_metrics(self):
        """Task 1: success, 2 steps (optimal=2), 150 tokens."""
        tasks = load_tasks(TASKS_PATH)
        registry = load_skill_registry(SKILLS_PATH)
        traces = run_dummy_agent(tasks)
        evaluator = TraceEvaluator(skill_registry=registry)
        results = evaluator.evaluate_all(traces, tasks)

        r1 = next(r for r in results if r["task_id"] == "task_001")
        assert r1["task_success"] is True
        assert r1["metrics"]["token_efficiency"] == 1.0 / 150
        assert r1["metrics"]["step_redundancy"] == 0.0
        assert r1["metrics"]["skill_utilization_cost"] == 200  # 2 x code_write(100)

    def test_task2_redundancy(self):
        """Task 2: success but redundant steps (5 vs optimal 3)."""
        tasks = load_tasks(TASKS_PATH)
        registry = load_skill_registry(SKILLS_PATH)
        traces = run_dummy_agent(tasks)
        evaluator = TraceEvaluator(skill_registry=registry)
        results = evaluator.evaluate_all(traces, tasks)

        r2 = next(r for r in results if r["task_id"] == "task_002")
        assert r2["task_success"] is True
        expected_srr = (5 - 3) / 3
        assert abs(r2["metrics"]["step_redundancy"] - expected_srr) < 1e-9

    def test_task3_failure_mode(self):
        """Task 3: failure with bad_combination mode."""
        tasks = load_tasks(TASKS_PATH)
        registry = load_skill_registry(SKILLS_PATH)
        traces = run_dummy_agent(tasks)
        evaluator = TraceEvaluator(skill_registry=registry)
        results = evaluator.evaluate_all(traces, tasks)

        r3 = next(r for r in results if r["task_id"] == "task_003")
        assert r3["task_success"] is False
        assert r3["failure_mode"] == "bad_combination"
        assert r3["metrics"]["token_efficiency"] == 0.0

    def test_report_file_exists(self):
        """Verify report file is generated."""
        tasks = load_tasks(TASKS_PATH)
        registry = load_skill_registry(SKILLS_PATH)
        traces = run_dummy_agent(tasks)
        evaluator = TraceEvaluator(skill_registry=registry)
        results = evaluator.evaluate_all(traces, tasks)
        generate_report(results, REPORT_OUTPUT)

        assert REPORT_OUTPUT.exists()
        with open(REPORT_OUTPUT) as f:
            report = json.load(f)
        assert "summary" in report
        assert "task_results" in report
        assert "aggregated_metrics" in report
