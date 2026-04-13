from typing import Any

from src.core.execution_trace import ExecutionTrace
from src.core.task import Task
from src.metrics.base_metric import BaseMetric


class TokenEfficiency(BaseMetric):
    name = "token_efficiency"
    description = "TE = I(success) / total_tokens"
    higher_is_better = True

    def compute(self, trace: ExecutionTrace, task: Task, **kwargs: Any) -> float:
        if trace.total_tokens == 0:
            return 0.0
        success = 1.0 if trace.task_success else 0.0
        return success / trace.total_tokens
