from typing import Any, List

from src.core.execution_trace import ExecutionTrace
from src.core.task import Task
from src.metrics.base_metric import BaseMetric


class CrossTaskTransferability(BaseMetric):
    name = "cross_task_transferability"
    description = "CTT = tasks_succeeded / tasks_attempted per skill"
    higher_is_better = True

    def compute(self, trace: ExecutionTrace, task: Task, **kwargs: Any) -> float:
        """Compute CTT for each skill used in this trace, return average."""
        all_traces: List[ExecutionTrace] = kwargs.get("all_traces", [])
        if not all_traces:
            return 0.0

        used_skills = {c.skill_name for c in trace.skill_calls}
        if not used_skills:
            return 0.0

        skill_ctts: list[float] = []
        for skill_name in used_skills:
            tasks_attempted: set[str] = set()
            tasks_succeeded: set[str] = set()
            for t in all_traces:
                if any(c.skill_name == skill_name for c in t.skill_calls):
                    tasks_attempted.add(t.task_id)
                    if t.task_success:
                        tasks_succeeded.add(t.task_id)
            if tasks_attempted:
                skill_ctts.append(len(tasks_succeeded) / len(tasks_attempted))

        if not skill_ctts:
            return 0.0
        return sum(skill_ctts) / len(skill_ctts)
