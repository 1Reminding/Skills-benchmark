from typing import Any, Tuple

from src.core.execution_trace import ExecutionTrace
from src.core.task import Task
from src.metrics.base_metric import BaseMetric

FAILURE_SCORES = {
    "success": 1.0,
    "missing_skill": 0.0,
    "bad_combination": 0.5,
    "other": 0.25,
}


class FailureModeSpecificity(BaseMetric):
    name = "failure_mode_specificity"
    description = "FMS: classifies failure as missing_skill or bad_combination"
    higher_is_better = True

    def classify(self, trace: ExecutionTrace, task: Task) -> Tuple[str, float]:
        if trace.task_success:
            return "success", FAILURE_SCORES["success"]

        used = {c.skill_name for c in trace.skill_calls}
        required = set(task.required_skills)

        if not required.issubset(used):
            return "missing_skill", FAILURE_SCORES["missing_skill"]
        return "bad_combination", FAILURE_SCORES["bad_combination"]

    def compute(self, trace: ExecutionTrace, task: Task, **kwargs: Any) -> float:
        _, score = self.classify(trace, task)
        return score
