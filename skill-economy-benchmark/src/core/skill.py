from pydantic import BaseModel, Field
from typing import Optional


class Skill(BaseModel):
    id: str
    name: str
    cost_per_call: float
    category: Optional[str] = None
    description: Optional[str] = None


class SkillRegistry(BaseModel):
    skills: list[Skill] = Field(default_factory=list)

    def get(self, skill_id: str) -> Optional[Skill]:
        for s in self.skills:
            if s.id == skill_id:
                return s
        return None

    def cost_of(self, skill_id: str) -> float:
        s = self.get(skill_id)
        return s.cost_per_call if s else 0.0
