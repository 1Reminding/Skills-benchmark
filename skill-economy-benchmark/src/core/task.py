from pydantic import BaseModel, Field
from typing import List, Dict, Optional


class Task(BaseModel):
    task_id: str
    domain: str
    instruction: str
    required_skills: List[str]
    optimal_steps: int
    verification_code: str
    metadata: Optional[Dict] = Field(default_factory=dict)
