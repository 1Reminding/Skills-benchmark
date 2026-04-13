from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from datetime import datetime


class SkillCall(BaseModel):
    skill_name: str
    input_params: Dict[str, Any] = Field(default_factory=dict)
    output: Any = None
    token_used: int = 0
    time_cost_ms: float = 0.0
    success: bool = True


class ExecutionTrace(BaseModel):
    task_id: str
    agent_name: str
    start_time: datetime
    end_time: datetime
    total_tokens: int
    steps_taken: int
    skill_calls: List[SkillCall] = Field(default_factory=list)
    task_success: bool = False
    failure_reason: Optional[str] = None
