from typing import Any

from src.core.execution_trace import ExecutionTrace
from src.core.task import Task
from src.core.skill import SkillRegistry
from src.metrics.base_metric import BaseMetric


class SkillCost(BaseMetric):
    name = "skill_utilization_cost"
    description = "SUC = sum(cost_per_call for each skill invocation)"
    higher_is_better = False

    def compute(self, trace: ExecutionTrace, task: Task, **kwargs: Any) -> float:
        registry: SkillRegistry | None = kwargs.get("skill_registry")
        if registry is None:
            return 0.0
        total = 0.0
        for call in trace.skill_calls:
            total += registry.cost_of(call.skill_name)
        return total
