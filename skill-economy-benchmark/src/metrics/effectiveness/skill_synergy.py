from typing import Any, List

from src.core.execution_trace import ExecutionTrace
from src.core.task import Task
from src.metrics.base_metric import BaseMetric


class SkillSynergy(BaseMetric):
    name = "skill_combination_synergy"
    description = "SCS = combo_success_rate - mean(individual_success_rates)"
    higher_is_better = True

    def compute(self, trace: ExecutionTrace, task: Task, **kwargs: Any) -> float:
        all_traces: List[ExecutionTrace] = kwargs.get("all_traces", [])
        if not all_traces:
            return 0.0

        used_skills = {c.skill_name for c in trace.skill_calls}
        if len(used_skills) < 2:
            return 0.0

        combo_traces = [
            t for t in all_traces
            if used_skills.issubset({c.skill_name for c in t.skill_calls})
        ]
        if not combo_traces:
            return 0.0
        combo_success = sum(1.0 for t in combo_traces if t.task_success) / len(combo_traces)

        individual_rates: list[float] = []
        for skill in used_skills:
            single_traces = [
                t for t in all_traces
                if any(c.skill_name == skill for c in t.skill_calls)
            ]
            if single_traces:
                rate = sum(1.0 for t in single_traces if t.task_success) / len(single_traces)
                individual_rates.append(rate)

        if not individual_rates:
            return 0.0

        avg_individual = sum(individual_rates) / len(individual_rates)
        return combo_success - avg_individual
