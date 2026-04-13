"""Unit tests for all 6 metrics."""

import sys
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.task import Task
from src.core.skill import SkillRegistry, Skill
from src.core.execution_trace import ExecutionTrace, SkillCall
from src.metrics.economy.token_efficiency import TokenEfficiency
from src.metrics.economy.step_redundancy import StepRedundancy
from src.metrics.economy.skill_cost import SkillCost
from src.metrics.effectiveness.skill_synergy import SkillSynergy
from src.metrics.effectiveness.transferability import CrossTaskTransferability
from src.metrics.effectiveness.failure_analysis import FailureModeSpecificity


def _make_task(**overrides) -> Task:
    defaults = dict(
        task_id="t1",
        domain="test",
        instruction="test task",
        required_skills=["code_write"],
        optimal_steps=2,
        verification_code="assert True",
    )
    defaults.update(overrides)
    return Task(**defaults)


def _make_trace(**overrides) -> ExecutionTrace:
    now = datetime(2026, 1, 1)
    defaults = dict(
        task_id="t1",
        agent_name="test_agent",
        start_time=now,
        end_time=now + timedelta(seconds=10),
        total_tokens=100,
        steps_taken=2,
        skill_calls=[
            SkillCall(skill_name="code_write", token_used=100, success=True),
        ],
        task_success=True,
    )
    defaults.update(overrides)
    return ExecutionTrace(**defaults)


def _make_registry() -> SkillRegistry:
    return SkillRegistry(skills=[
        Skill(id="code_write", name="Code Writing", cost_per_call=100),
        Skill(id="code_read", name="Code Reading", cost_per_call=20),
        Skill(id="debug", name="Debugging", cost_per_call=150),
        Skill(id="plan", name="Task Planning", cost_per_call=50),
    ])


class TestTokenEfficiency:
    def test_success(self):
        te = TokenEfficiency()
        trace = _make_trace(task_success=True, total_tokens=200)
        task = _make_task()
        assert te.compute(trace, task) == 1.0 / 200

    def test_failure_returns_zero(self):
        te = TokenEfficiency()
        trace = _make_trace(task_success=False, total_tokens=200)
        task = _make_task()
        assert te.compute(trace, task) == 0.0

    def test_zero_tokens(self):
        te = TokenEfficiency()
        trace = _make_trace(total_tokens=0)
        task = _make_task()
        assert te.compute(trace, task) == 0.0


class TestStepRedundancy:
    def test_optimal(self):
        srr = StepRedundancy()
        trace = _make_trace(steps_taken=2)
        task = _make_task(optimal_steps=2)
        assert srr.compute(trace, task) == 0.0

    def test_fewer_than_optimal(self):
        srr = StepRedundancy()
        trace = _make_trace(steps_taken=1)
        task = _make_task(optimal_steps=2)
        assert srr.compute(trace, task) == 0.0

    def test_redundant(self):
        srr = StepRedundancy()
        trace = _make_trace(steps_taken=5)
        task = _make_task(optimal_steps=3)
        result = srr.compute(trace, task)
        assert abs(result - 2.0 / 3.0) < 1e-9

    def test_zero_optimal(self):
        srr = StepRedundancy()
        trace = _make_trace(steps_taken=5)
        task = _make_task(optimal_steps=0)
        assert srr.compute(trace, task) == 0.0


class TestSkillCost:
    def test_basic_cost(self):
        suc = SkillCost()
        trace = _make_trace(skill_calls=[
            SkillCall(skill_name="code_write", token_used=100, success=True),
            SkillCall(skill_name="debug", token_used=150, success=True),
        ])
        task = _make_task()
        registry = _make_registry()
        result = suc.compute(trace, task, skill_registry=registry)
        assert result == 100 + 150  # code_write(100) + debug(150)

    def test_no_registry(self):
        suc = SkillCost()
        trace = _make_trace()
        task = _make_task()
        assert suc.compute(trace, task) == 0.0


class TestSkillSynergy:
    def test_single_skill_returns_zero(self):
        scs = SkillSynergy()
        trace = _make_trace()
        task = _make_task()
        assert scs.compute(trace, task, all_traces=[trace]) == 0.0

    def test_positive_synergy(self):
        scs = SkillSynergy()
        now = datetime(2026, 1, 1)
        combo_trace = _make_trace(
            task_id="t1",
            task_success=True,
            skill_calls=[
                SkillCall(skill_name="code_write", token_used=50, success=True),
                SkillCall(skill_name="debug", token_used=50, success=True),
            ],
        )
        single_a = _make_trace(
            task_id="t2",
            task_success=False,
            skill_calls=[
                SkillCall(skill_name="code_write", token_used=50, success=True),
            ],
        )
        single_b = _make_trace(
            task_id="t3",
            task_success=False,
            skill_calls=[
                SkillCall(skill_name="debug", token_used=50, success=True),
            ],
        )
        all_traces = [combo_trace, single_a, single_b]
        task = _make_task()
        result = scs.compute(combo_trace, task, all_traces=all_traces)
        assert result > 0


class TestTransferability:
    def test_full_transfer(self):
        ctt = CrossTaskTransferability()
        traces = [
            _make_trace(task_id="t1", task_success=True),
            _make_trace(task_id="t2", task_success=True),
        ]
        task = _make_task()
        result = ctt.compute(traces[0], task, all_traces=traces)
        assert result == 1.0

    def test_partial_transfer(self):
        ctt = CrossTaskTransferability()
        traces = [
            _make_trace(task_id="t1", task_success=True),
            _make_trace(task_id="t2", task_success=False),
        ]
        task = _make_task()
        result = ctt.compute(traces[0], task, all_traces=traces)
        assert result == 0.5


class TestFailureModeSpecificity:
    def test_success(self):
        fms = FailureModeSpecificity()
        trace = _make_trace(task_success=True)
        task = _make_task(required_skills=["code_write"])
        label, score = fms.classify(trace, task)
        assert label == "success"
        assert score == 1.0

    def test_missing_skill(self):
        fms = FailureModeSpecificity()
        trace = _make_trace(
            task_success=False,
            skill_calls=[SkillCall(skill_name="code_write", token_used=50, success=True)],
        )
        task = _make_task(required_skills=["code_write", "debug"])
        label, score = fms.classify(trace, task)
        assert label == "missing_skill"
        assert score == 0.0

    def test_bad_combination(self):
        fms = FailureModeSpecificity()
        trace = _make_trace(
            task_success=False,
            skill_calls=[
                SkillCall(skill_name="plan", token_used=50, success=True),
                SkillCall(skill_name="code_write", token_used=50, success=False),
            ],
        )
        task = _make_task(required_skills=["plan", "code_write"])
        label, score = fms.classify(trace, task)
        assert label == "bad_combination"
        assert score == 0.5
