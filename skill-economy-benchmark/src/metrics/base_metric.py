from abc import ABC, abstractmethod
from typing import Any

from src.core.execution_trace import ExecutionTrace
from src.core.task import Task


class BaseMetric(ABC):
    name: str = "base"
    description: str = ""
    higher_is_better: bool = True

    @abstractmethod
    def compute(self, trace: ExecutionTrace, task: Task, **kwargs: Any) -> float:
        ...

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name!r})"
