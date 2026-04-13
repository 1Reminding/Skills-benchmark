from typing import Any

from src.core.execution_trace import ExecutionTrace
from src.core.task import Task
from src.metrics.base_metric import BaseMetric


class StepRedundancy(BaseMetric):
    name = "step_redundancy"
    description = "SRR = max(0, (steps_taken - optimal_steps) / optimal_steps)"
    higher_is_better = False

    def compute(self, trace: ExecutionTrace, task: Task, **kwargs: Any) -> float:
        if task.optimal_steps == 0:
            return 0.0
        redundancy = (trace.steps_taken - task.optimal_steps) / task.optimal_steps
        return max(0.0, redundancy)
