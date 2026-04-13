import json
from pathlib import Path
from typing import List

from src.core.task import Task
from src.core.skill import Skill, SkillRegistry


def load_tasks(path: str | Path) -> List[Task]:
    path = Path(path)
    with open(path) as f:
        data = json.load(f)
    return [Task(**t) for t in data["tasks"]]


def load_skill_registry(path: str | Path) -> SkillRegistry:
    path = Path(path)
    with open(path) as f:
        data = json.load(f)
    skills = [Skill(**s) for s in data["skills"]]
    return SkillRegistry(skills=skills)


def load_dataset_index(index_path: str | Path) -> tuple[List[Task], SkillRegistry]:
    """Load tasks and skill registry from the unified dataset_index.json."""
    index_path = Path(index_path)
    with open(index_path) as f:
        data = json.load(f)

    dataset_dir = index_path.parent

    tasks = []
    for t in data["tasks"]:
        instruction = ""
        instr_path = dataset_dir / t["instruction_file"]
        if instr_path.exists():
            instruction = instr_path.read_text()

        tasks.append(Task(
            task_id=t["task_id"],
            domain=t["domain"],
            instruction=instruction,
            required_skills=t["required_skills"],
            optimal_steps=t["optimal_steps"],
            verification_code=f"# see tests/ in {t['task_id']}",
            metadata={
                "difficulty": t.get("difficulty", "unknown"),
                "tags": t.get("tags", []),
            },
        ))

    taxonomy = data.get("skill_taxonomy", {})
    skills = [
        Skill(
            id=sid,
            name=sdata["name"],
            cost_per_call=sdata["cost_per_call"],
            category=sdata.get("category"),
        )
        for sid, sdata in taxonomy.items()
    ]
    registry = SkillRegistry(skills=skills)

    return tasks, registry
