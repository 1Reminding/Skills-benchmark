#!/usr/bin/env python3
"""Build capability-aware retrieval candidate skill pools for selected tasks.

This script is a retrieval MVP aligned with the current project plan:
1) build a task capability schema
2) load a structured skill registry
3) retrieve multi-source candidates with rule-based scoring
4) write raw retrieval results and a provisional balanced task-level pool

It intentionally does NOT call any generation API.
Generation / rewrite / leakage filtering should happen in later scripts.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATASET_INDEX = PROJECT_ROOT / "dataset" / "dataset_index.json"
DEFAULT_DATASET_ROOT = PROJECT_ROOT / "dataset"
DEFAULT_SKILL_REGISTRY = PROJECT_ROOT / "data" / "skill_registry.json"
DEFAULT_GENERIC_SKILLS = PROJECT_ROOT / "data" / "generic_skills.json"
DEFAULT_EXTERNAL_SKILLS = PROJECT_ROOT / "data" / "external_skills.json"
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "skill_pool"

TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9\-_/+]*")
ARTIFACT_EXTENSIONS = {
    ".pdf": "pdf",
    ".xlsx": "xlsx",
    ".xlsm": "xlsx",
    ".xls": "xlsx",
    ".csv": "csv",
    ".tsv": "csv",
    ".json": "json",
    ".md": "markdown",
    ".txt": "text",
    ".py": "python",
    ".ipynb": "notebook",
    ".html": "html",
    ".tex": "latex",
}

TAG_TO_FAMILY = {
    "excel": "spreadsheet_analytics",
    "pivot-tables": "spreadsheet_analytics",
    "spreadsheet": "spreadsheet_analytics",
    "latex": "document_extraction",
    "pdf": "document_extraction",
    "extraction": "document_extraction",
    "debugging": "debugging_ci_repair",
    "ci": "debugging_ci_repair",
    "build": "debugging_ci_repair",
    "gis": "geospatial_analysis",
    "spatial-analysis": "geospatial_analysis",
    "geophysics": "geospatial_analysis",
    "statistics": "data_analytics",
    "data-cleaning": "data_analytics",
}

TAG_TO_OPERATIONS = {
    "excel": {"extract", "aggregate"},
    "pivot-tables": {"aggregate", "calculate"},
    "statistics": {"aggregate", "calculate", "validate"},
    "debugging": {"debug", "patch", "validate"},
    "ci": {"debug", "validate"},
    "build": {"debug", "patch"},
    "latex": {"extract", "transform"},
    "pdf": {"extract", "transform"},
    "extraction": {"extract"},
    "gis": {"analyze", "calculate"},
    "spatial-analysis": {"analyze", "calculate"},
    "geophysics": {"analyze", "calculate"},
}

FAMILY_DEFAULT_TOOLS = {
    "spreadsheet_analytics": {"spreadsheet", "python"},
    "document_extraction": {"pdf", "python"},
    "debugging_ci_repair": {"shell", "python", "testing", "ci"},
    "geospatial_analysis": {"python", "geospatial"},
    "data_analytics": {"python"},
    "general_problem_solving": {"shell"},
}

GENERIC_SKILL_HINTS = {
    "result_verification": {
        "summary": "Verify outputs against task constraints before finalizing results.",
        "family": ["general_problem_solving"],
        "artifacts": [],
        "operations": ["verify", "validate"],
        "tools": ["shell", "python"],
        "granularity": "generic",
        "domain_specificity": "low",
    },
    "step_decomposition": {
        "summary": "Break a task into smaller executable steps and track intermediate state.",
        "family": ["general_problem_solving"],
        "artifacts": [],
        "operations": ["plan", "verify"],
        "tools": ["shell"],
        "granularity": "generic",
        "domain_specificity": "low",
    },
    "spreadsheet_sanity_check": {
        "summary": "Check spreadsheet schema, column types, missing values, and formula consistency.",
        "family": ["spreadsheet_analytics"],
        "artifacts": ["xlsx", "csv"],
        "operations": ["validate", "clean", "verify"],
        "tools": ["spreadsheet", "python"],
        "granularity": "atomic",
        "domain_specificity": "low",
    },
    "error_diagnosis": {
        "summary": "Locate the failing stage, isolate the error source, and validate the fix minimally.",
        "family": ["debugging_ci_repair", "general_problem_solving"],
        "artifacts": ["text", "python"],
        "operations": ["debug", "validate", "verify"],
        "tools": ["shell", "python", "testing"],
        "granularity": "generic",
        "domain_specificity": "low",
    },
}


def _normalize_token(token: str) -> str:
    token = token.lower().strip()
    if token.endswith("s") and len(token) > 4:
        token = token[:-1]
    return token



def _tokenize(text: str) -> set[str]:
    return {_normalize_token(t) for t in TOKEN_RE.findall((text or "").lower()) if len(t) >= 2}



def _read_json(path: Path) -> Any:
    with open(path) as f:
        return json.load(f)



def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))



def _safe_list_str(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return sorted({str(v).strip() for v in value if str(v).strip()})
    return [str(value).strip()] if str(value).strip() else []



def _detect_artifacts(task_dir: Path) -> list[str]:
    found: set[str] = set()
    env_dir = task_dir / "environment"
    if not env_dir.is_dir():
        return []
    for p in env_dir.rglob("*"):
        if not p.is_file():
            continue
        if "skills" in p.parts:
            continue
        artifact = ARTIFACT_EXTENSIONS.get(p.suffix.lower())
        if artifact:
            found.add(artifact)
    return sorted(found)



def _infer_family(domain: str, tags: list[str], artifacts: list[str]) -> str:
    tags_s = {_normalize_token(t) for t in tags}
    for t in tags_s:
        if t in TAG_TO_FAMILY:
            return TAG_TO_FAMILY[t]
    if "xlsx" in artifacts or "csv" in artifacts:
        return "spreadsheet_analytics"
    if "pdf" in artifacts or "latex" in artifacts:
        return "document_extraction"
    d = domain.lower()
    if "software" in d or "engineering" in d:
        return "debugging_ci_repair"
    if "science" in d and ("json" in artifacts or "csv" in artifacts):
        return "data_analytics"
    return "general_problem_solving"



def _detect_operations(tags: list[str], artifacts: list[str], domain: str) -> list[str]:
    ops = {"verify"}
    for tag in tags:
        ops |= TAG_TO_OPERATIONS.get(_normalize_token(tag), set())
    if "xlsx" in artifacts or "csv" in artifacts:
        ops |= {"extract", "aggregate", "validate"}
    if "pdf" in artifacts:
        ops |= {"extract", "transform"}
    if domain.lower().startswith("software"):
        ops |= {"debug", "patch", "validate"}
    return sorted(ops)



def _detect_tools(artifacts: list[str], family: str) -> list[str]:
    tools = set(FAMILY_DEFAULT_TOOLS.get(family, {"shell"}))
    if "xlsx" in artifacts or "csv" in artifacts:
        tools |= {"spreadsheet", "python"}
    if "pdf" in artifacts:
        tools |= {"pdf", "python"}
    if "python" in artifacts:
        tools.add("python")
    return sorted(tools)



@dataclass
class TaskSchema:
    task_id: str
    family: str
    domain: str
    artifacts: list[str]
    operations: list[str]
    tools: list[str]
    output_type: str
    constraints: list[str]
    tags: list[str] = field(default_factory=list)
    original_curated_skills: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "family": self.family,
            "domain": self.domain,
            "artifacts": self.artifacts,
            "operations": self.operations,
            "tools": self.tools,
            "output_type": self.output_type,
            "constraints": self.constraints,
            "tags": self.tags,
            "original_curated_skills": self.original_curated_skills,
        }



@dataclass
class SkillSchema:
    skill_id: str
    source_type: str
    family: list[str]
    artifacts: list[str]
    operations: list[str]
    tools: list[str]
    granularity: str
    domain_specificity: str
    summary: str
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "source_type": self.source_type,
            "family": self.family,
            "artifacts": self.artifacts,
            "operations": self.operations,
            "tools": self.tools,
            "granularity": self.granularity,
            "domain_specificity": self.domain_specificity,
            "summary": self.summary,
            "tags": self.tags,
            "metadata": self.metadata,
        }



def _build_task_schema(task_meta: dict[str, Any], dataset_root: Path) -> TaskSchema:
    task_id = task_meta["task_id"]
    domain = str(task_meta.get("domain", "unknown"))
    tags = _safe_list_str(task_meta.get("tags", []))
    original_curated = _safe_list_str(task_meta.get("required_skills", []))
    artifacts = _detect_artifacts(dataset_root / task_id)
    family = _infer_family(domain, tags, artifacts)
    operations = _detect_operations(tags, artifacts, domain)
    tools = _detect_tools(artifacts, family)
    constraints = ["deterministic_verifier"]
    output_type = "structured_output_or_file_update"
    return TaskSchema(
        task_id=task_id,
        family=family,
        domain=domain,
        artifacts=artifacts,
        operations=operations,
        tools=tools,
        output_type=output_type,
        constraints=constraints,
        tags=tags,
        original_curated_skills=original_curated,
    )



def _normalize_skill_record(raw: dict[str, Any], default_source: str) -> SkillSchema:
    skill_id = str(raw.get("skill_id") or raw.get("name") or "").strip()
    if not skill_id:
        raise ValueError(f"Skill record missing skill_id/name: {raw}")
    source_type = str(raw.get("source_type") or raw.get("source") or default_source)
    family = _safe_list_str(raw.get("family"))
    artifacts = _safe_list_str(raw.get("artifacts"))
    operations = _safe_list_str(raw.get("operations"))
    tools = _safe_list_str(raw.get("tools"))
    granularity = str(raw.get("granularity") or "atomic")
    domain_specificity = str(raw.get("domain_specificity") or "unknown")
    summary = str(raw.get("summary") or raw.get("description") or "").strip()
    tags = _safe_list_str(raw.get("tags"))
    metadata = dict(raw.get("metadata") or {})
    return SkillSchema(
        skill_id=skill_id,
        source_type=source_type,
        family=family,
        artifacts=artifacts,
        operations=operations,
        tools=tools,
        granularity=granularity,
        domain_specificity=domain_specificity,
        summary=summary,
        tags=tags,
        metadata=metadata,
    )



def _load_skill_file(path: Path, default_source: str) -> list[SkillSchema]:
    if not path.exists():
        return []
    data = _read_json(path)
    if isinstance(data, dict) and isinstance(data.get("skills"), list):
        items = data["skills"]
    elif isinstance(data, list):
        items = data
    else:
        raise SystemExit(f"Unsupported skill file format: {path}")
    skills: list[SkillSchema] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        skills.append(_normalize_skill_record(item, default_source=default_source))
    return skills



def _load_default_generic_skills() -> list[SkillSchema]:
    return [
        _normalize_skill_record({"skill_id": skill_id, **payload}, default_source="generic_builtin")
        for skill_id, payload in GENERIC_SKILL_HINTS.items()
    ]



def _build_skill_registry(
    skill_registry_path: Path,
    generic_skills_path: Path | None,
    external_skills_path: Path | None,
) -> list[SkillSchema]:
    registry: dict[str, SkillSchema] = {}
    for skill in _load_skill_file(skill_registry_path, default_source="registry"):
        registry[skill.skill_id] = skill
    if generic_skills_path:
        for skill in _load_skill_file(generic_skills_path, default_source="generic"):
            registry[skill.skill_id] = skill
    else:
        for skill in _load_default_generic_skills():
            if skill.skill_id not in registry:
                registry[skill.skill_id] = skill
    if external_skills_path:
        for skill in _load_skill_file(external_skills_path, default_source="external"):
            registry[skill.skill_id] = skill
    return list(registry.values())



def _fallback_skill_tokens(skill: SkillSchema) -> set[str]:
    return _tokenize(
        " ".join(
            [
                skill.skill_id,
                skill.summary,
                " ".join(skill.family),
                " ".join(skill.artifacts),
                " ".join(skill.operations),
                " ".join(skill.tools),
                " ".join(skill.tags),
            ]
        )
    )



def _score_task_skill(task: TaskSchema, skill: SkillSchema) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []

    task_family = task.family
    skill_families = set(skill.family)
    if task_family in skill_families:
        score += 4.0
        reasons.append("family_match")
    elif task_family != "general_problem_solving" and "general_problem_solving" in skill_families:
        score += 1.5
        reasons.append("generic_family_match")

    artifact_overlap = set(task.artifacts) & set(skill.artifacts)
    if artifact_overlap:
        score += 2.0 * len(artifact_overlap)
        reasons.append("artifact_overlap")

    op_overlap = set(task.operations) & set(skill.operations)
    if op_overlap:
        score += 2.0 * len(op_overlap)
        reasons.append("operation_overlap")

    tool_overlap = set(task.tools) & set(skill.tools)
    if tool_overlap:
        score += 1.0 * len(tool_overlap)
        reasons.append("tool_overlap")

    task_tokens = _tokenize(
        " ".join([task.task_id, task.domain, task.family, " ".join(task.tags), " ".join(task.artifacts)])
    )
    token_overlap = len(task_tokens & _fallback_skill_tokens(skill))
    if token_overlap:
        score += min(2.0, 0.25 * token_overlap)
        reasons.append("semantic_overlap")

    if skill.skill_id in set(task.original_curated_skills):
        score += 6.0
        reasons.append("original_curated_match")

    if skill.domain_specificity == "low":
        score += 0.5
        reasons.append("transfer_bonus")

    if skill.granularity == "generic":
        score += 0.2
        reasons.append("generic_skill_bonus")

    return round(score, 3), reasons



def _source_bucket(skill: SkillSchema, task: TaskSchema) -> str:
    if skill.skill_id in set(task.original_curated_skills):
        return "orig"
    if skill.source_type.startswith("generic"):
        return "generic"
    if skill.source_type == "external":
        return "external"
    return "cross"



def _dedupe_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for candidate in sorted(candidates, key=lambda x: x["score"], reverse=True):
        skill_id = candidate["skill_id"]
        if skill_id not in deduped:
            deduped[skill_id] = candidate
    return list(deduped.values())



def _select_balanced_pool(
    task: TaskSchema,
    candidates: list[dict[str, Any]],
    max_pool_size: int,
    max_per_bucket: dict[str, int],
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    counts = {k: 0 for k in max_per_bucket}

    # Always keep original curated candidates when present.
    for candidate in candidates:
        if candidate["bucket"] == "orig":
            selected.append(candidate)
            counts["orig"] += 1

    for candidate in candidates:
        if len(selected) >= max_pool_size:
            break
        if candidate in selected:
            continue
        bucket = candidate["bucket"]
        if bucket in max_per_bucket and counts[bucket] >= max_per_bucket[bucket]:
            continue
        selected.append(candidate)
        if bucket in counts:
            counts[bucket] += 1

    return selected[:max_pool_size]



def _build_retrieval_for_task(
    task_meta: dict[str, Any],
    dataset_root: Path,
    skill_registry: list[SkillSchema],
    max_pool_size: int,
) -> dict[str, Any]:
    task = _build_task_schema(task_meta, dataset_root)
    raw_candidates: list[dict[str, Any]] = []

    for skill in skill_registry:
        score, reasons = _score_task_skill(task, skill)
        if score <= 0:
            continue
        raw_candidates.append(
            {
                "skill_id": skill.skill_id,
                "bucket": _source_bucket(skill, task),
                "source_type": skill.source_type,
                "score": score,
                "retrieval_path": reasons,
                "family": skill.family,
                "artifacts": skill.artifacts,
                "operations": skill.operations,
                "tools": skill.tools,
                "granularity": skill.granularity,
                "domain_specificity": skill.domain_specificity,
                "summary": skill.summary,
            }
        )

    raw_candidates = _dedupe_candidates(raw_candidates)
    raw_candidates.sort(key=lambda x: x["score"], reverse=True)

    balanced_pool = _select_balanced_pool(
        task,
        raw_candidates,
        max_pool_size=max_pool_size,
        max_per_bucket={"orig": 99, "cross": 6, "generic": 3, "external": 4},
    )

    grouped: dict[str, list[dict[str, Any]]] = {"orig": [], "cross": [], "generic": [], "external": []}
    for candidate in raw_candidates:
        grouped.setdefault(candidate["bucket"], []).append(candidate)

    return {
        "task_id": task.task_id,
        "generated_at": datetime.now().isoformat(),
        "schema": task.to_json(),
        "raw_retrieval": grouped,
        "balanced_task_pool": balanced_pool,
        "summary": {
            "n_raw_total": len(raw_candidates),
            "n_orig": len(grouped.get("orig", [])),
            "n_cross": len(grouped.get("cross", [])),
            "n_generic": len(grouped.get("generic", [])),
            "n_external": len(grouped.get("external", [])),
            "n_balanced_pool": len(balanced_pool),
        },
    }



def _select_tasks(all_tasks: list[dict[str, Any]], task_ids: list[str] | None) -> list[dict[str, Any]]:
    if not task_ids:
        return all_tasks
    lookup = {t["task_id"]: t for t in all_tasks}
    return [lookup[tid] for tid in task_ids if tid in lookup]



def main() -> None:
    parser = argparse.ArgumentParser(description="Build capability-aware retrieval candidate skill pools")
    parser.add_argument("--dataset-index", type=Path, default=DEFAULT_DATASET_INDEX)
    parser.add_argument("--dataset-root", type=Path, default=DEFAULT_DATASET_ROOT)
    parser.add_argument("--skill-registry", type=Path, default=DEFAULT_SKILL_REGISTRY)
    parser.add_argument("--generic-skills", type=Path, default=None)
    parser.add_argument("--external-skills", type=Path, default=None)
    parser.add_argument("--task-ids", type=str, default=None, help="Comma-separated task ids")
    parser.add_argument("--max-pool-size", type=int, default=12)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args()

    index_data = _read_json(args.dataset_index)
    all_tasks = list(index_data.get("tasks", []))
    if not all_tasks:
        raise SystemExit("No tasks found in dataset index.")

    selected_ids = [s.strip() for s in args.task_ids.split(",") if s.strip()] if args.task_ids else None
    selected_tasks = _select_tasks(all_tasks, selected_ids)
    if not selected_tasks:
        raise SystemExit("No valid tasks selected.")

    skill_registry = _build_skill_registry(
        skill_registry_path=args.skill_registry,
        generic_skills_path=args.generic_skills,
        external_skills_path=args.external_skills,
    )
    if not skill_registry:
        raise SystemExit(
            "Skill registry is empty. Fill data/skill_registry.json first, or pass --generic-skills/--external-skills."
        )

    raw_dir = args.output_root / "raw_retrieved"
    task_pool_dir = args.output_root / "task_pools"
    raw_dir.mkdir(parents=True, exist_ok=True)
    task_pool_dir.mkdir(parents=True, exist_ok=True)

    manifest: dict[str, Any] = {
        "generated_at": datetime.now().isoformat(),
        "dataset_index": str(args.dataset_index),
        "dataset_root": str(args.dataset_root),
        "skill_registry": str(args.skill_registry),
        "generic_skills": str(args.generic_skills) if args.generic_skills else None,
        "external_skills": str(args.external_skills) if args.external_skills else None,
        "max_pool_size": args.max_pool_size,
        "selected_task_ids": [t["task_id"] for t in selected_tasks],
        "results": [],
    }

    for task_meta in selected_tasks:
        result = _build_retrieval_for_task(
            task_meta=task_meta,
            dataset_root=args.dataset_root,
            skill_registry=skill_registry,
            max_pool_size=args.max_pool_size,
        )
        task_id = task_meta["task_id"]
        raw_path = raw_dir / f"{task_id}.json"
        pool_path = task_pool_dir / f"{task_id}.json"

        _write_json(raw_path, {"task_id": task_id, "schema": result["schema"], "raw_retrieval": result["raw_retrieval"], "summary": result["summary"]})
        _write_json(pool_path, result)

        manifest["results"].append(
            {
                "task_id": task_id,
                "raw_retrieval": str(raw_path),
                "task_pool": str(pool_path),
                "summary": result["summary"],
            }
        )
        print(
            f"[OK] {task_id}: raw={result['summary']['n_raw_total']} "
            f"orig={result['summary']['n_orig']} cross={result['summary']['n_cross']} "
            f"generic={result['summary']['n_generic']} external={result['summary']['n_external']} "
            f"final={result['summary']['n_balanced_pool']}"
        )

    manifest_path = args.output_root / "metadata.json"
    _write_json(manifest_path, manifest)
    print(f"\nDone. Manifest: {manifest_path}")
    print(f"Raw retrieval dir: {raw_dir}")
    print(f"Task pool dir: {task_pool_dir}")


if __name__ == "__main__":
    main()
