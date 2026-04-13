from typing import Dict, List, Any

from src.core.execution_trace import ExecutionTrace
from src.core.task import Task
from src.core.skill import SkillRegistry
from src.metrics.economy.token_efficiency import TokenEfficiency
from src.metrics.economy.step_redundancy import StepRedundancy
from src.metrics.economy.skill_cost import SkillCost
from src.metrics.effectiveness.skill_synergy import SkillSynergy
from src.metrics.effectiveness.transferability import CrossTaskTransferability
from src.metrics.effectiveness.failure_analysis import FailureModeSpecificity


class TraceEvaluator:
    def __init__(self, skill_registry: SkillRegistry):
        self.skill_registry = skill_registry
        self.te = TokenEfficiency()
        self.srr = StepRedundancy()
        self.suc = SkillCost()
        self.scs = SkillSynergy()
        self.ctt = CrossTaskTransferability()
        self.fms = FailureModeSpecificity()

    def evaluate_single(
        self,
        trace: ExecutionTrace,
        task: Task,
        all_traces: List[ExecutionTrace],
    ) -> Dict[str, Any]:
        failure_label, _ = self.fms.classify(trace, task)
        return {
            "task_id": trace.task_id,
            "agent_name": trace.agent_name,
            "task_success": trace.task_success,
            "failure_reason": trace.failure_reason,
            "failure_mode": failure_label,
            "metrics": {
                "token_efficiency": self.te.compute(trace, task),
                "step_redundancy": self.srr.compute(trace, task),
                "skill_utilization_cost": self.suc.compute(
                    trace, task, skill_registry=self.skill_registry
                ),
                "skill_combination_synergy": self.scs.compute(
                    trace, task, all_traces=all_traces
                ),
                "cross_task_transferability": self.ctt.compute(
                    trace, task, all_traces=all_traces
                ),
                "failure_mode_specificity": self.fms.compute(trace, task),
            },
        }

    def evaluate_all(
        self,
        traces: List[ExecutionTrace],
        tasks: List[Task],
    ) -> List[Dict[str, Any]]:
        task_map = {t.task_id: t for t in tasks}
        results = []
        for trace in traces:
            task = task_map.get(trace.task_id)
            if task is None:
                continue
            results.append(self.evaluate_single(trace, task, traces))
        return results
