#!/usr/bin/env python3
"""Build retrieval-only candidate skill pools for selected tasks.

This script intentionally does NOT call any generation API.
It creates task schemas and multi-source retrieval candidates:
1) original curated skills from each task
2) cross-task skills from local dataset index
3) external skills from a pre-collected corpus json
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATASET_INDEX = PROJECT_ROOT / "dataset" / "dataset_index.json"
DEFAULT_DATASET_ROOT = PROJECT_ROOT / "dataset"
DEFAULT_EXTERNAL_SKILLS = PROJECT_ROOT / "docs" / "skills-research" / "curated_skills.json"
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
        ext = p.suffix.lower()
        artifact = ARTIFACT_EXTENSIONS.get(ext)
        if artifact:
            found.add(artifact)
    return sorted(found)


def _detect_tools(required_skills: list[str], artifacts: list[str], domain: str) -> list[str]:
    tools = {"shell"}
    if "xlsx" in required_skills or "xlsx" in artifacts:
        tools.add("spreadsheet")
    if "pdf" in required_skills or "pdf" in artifacts:
        tools.add("pdf")
    if any(s in required_skills for s in ("analyze-ci", "testing-python", "uv-package-manager")):
        tools.update({"python", "testing", "ci"})
    if "geospatial-analysis" in required_skills:
        tools.update({"python", "geospatial"})
    if "software-engineering" in domain:
        tools.update({"python", "codebase"})
    return sorted(tools)


def _detect_operations(tags: list[str], required_skills: list[str], domain: str) -> list[str]:
    ops = {"verify"}
    tags_s = set(tags)
    if {"excel", "pivot-tables", "statistics"} & tags_s:
        ops.update({"extract", "aggregate", "calculate"})
    if {"build", "ci", "debugging"} & tags_s:
        ops.update({"debug", "patch", "validate"})
    if {"latex", "pdf", "extraction"} & tags_s:
        ops.update({"extract", "transform"})
    if {"spatial-analysis", "gis", "geophysics"} & tags_s:
        ops.update({"analyze", "calculate"})
    if "software-engineering" in domain:
        ops.update({"debug", "patch"})
    if "senior-data-scientist" in required_skills:
        ops.add("summarize")
    return sorted(ops)


def _infer_family(domain: str, tags: list[str], required_skills: list[str]) -> str:
    tags_s = set(tags)
    if "xlsx" in required_skills:
        return "spreadsheet_analytics"
    if "pdf" in required_skills and "latex" in tags_s:
        return "document_extraction"
    if "software-engineering" in domain or {"build", "ci", "debugging"} & tags_s:
        return "debugging_ci_repair"
    if "geospatial-analysis" in required_skills:
        return "geospatial_analysis"
    if "data-analysis" in domain:
        return "data_analytics"
    return "general_problem_solving"


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
    required_skills: list[str]
    tags: list[str]

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
            "required_skills": self.required_skills,
            "tags": self.tags,
        }


def _build_task_schema(task_meta: dict[str, Any], dataset_root: Path) -> TaskSchema:
    task_id = task_meta["task_id"]
    domain = task_meta.get("domain", "unknown")
    tags = list(task_meta.get("tags", []))
    required_skills = list(task_meta.get("required_skills", []))
    task_dir = dataset_root / task_id
    artifacts = _detect_artifacts(task_dir)
    family = _infer_family(domain, tags, required_skills)
    operations = _detect_operations(tags, required_skills, domain)
    tools = _detect_tools(required_skills, artifacts, domain)
    constraints = ["deterministic_verifier", "filesystem_mutation_possible"]
    output_type = "file_update_or_exact_answer"
    return TaskSchema(
        task_id=task_id,
        family=family,
        domain=domain,
        artifacts=artifacts,
        operations=operations,
        tools=tools,
        output_type=output_type,
        constraints=constraints,
        required_skills=required_skills,
        tags=tags,
    )


def _score_cross_task_candidate(
    source_task: dict[str, Any],
    source_skill: str,
    target_schema: TaskSchema,
    target_tags: set[str],
) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    if source_task.get("domain") == target_schema.domain:
        score += 3
        reasons.append("domain_match")
    source_tags = set(source_task.get("tags", []))
    overlap_tags = source_tags & target_tags
    if overlap_tags:
        score += min(3, len(overlap_tags))
        reasons.append("tag_overlap")
    if source_skill in target_schema.required_skills:
        score += 5
        reasons.append("required_skill_match")
    if source_skill in {"xlsx", "pdf", "code_read", "debug", "search"}:
        score += 1
        reasons.append("generic_skill_bonus")
    if source_skill == "geospatial-analysis" and target_schema.family == "geospatial_analysis":
        score += 3
        reasons.append("family_match")
    return score, reasons


def _profile_text(schema: TaskSchema) -> str:
    return " ".join(
        [
            schema.task_id,
            schema.family,
            schema.domain,
            " ".join(schema.artifacts),
            " ".join(schema.operations),
            " ".join(schema.tools),
            " ".join(schema.required_skills),
            " ".join(schema.tags),
        ]
    )


def _score_external_candidate(
    candidate: dict[str, Any],
    profile_tokens: set[str],
    required_skill_set: set[str],
    family: str,
) -> tuple[float, list[str]]:
    name = str(candidate.get("name", ""))
    description = str(candidate.get("description", ""))
    text_tokens = _tokenize(name + " " + description)
    overlap = len(profile_tokens & text_tokens)
    score = float(overlap)
    reasons: list[str] = []
    if overlap > 0:
        reasons.append("token_overlap")
    if name in required_skill_set:
        score += 8.0
        reasons.append("required_skill_match")
    if family.startswith("spreadsheet") and ("xlsx" in text_tokens or "spreadsheet" in text_tokens):
        score += 2.0
        reasons.append("family_bias")
    if family == "document_extraction" and ("pdf" in text_tokens or "extract" in text_tokens):
        score += 2.0
        reasons.append("family_bias")
    if family == "debugging_ci_repair" and (
        "debug" in text_tokens or "ci" in text_tokens or "testing" in text_tokens
    ):
        score += 2.0
        reasons.append("family_bias")
    if family == "geospatial_analysis" and ("geo" in text_tokens or "spatial" in text_tokens):
        score += 2.0
        reasons.append("family_bias")
    return score, reasons


def _load_external_candidates(path: Path) -> list[dict[str, Any]]:
    data = _read_json(path)
    if isinstance(data, list):
        return [d for d in data if isinstance(d, dict)]
    if isinstance(data, dict):
        if isinstance(data.get("names"), list):
            names = [str(n) for n in data.get("names", [])]
            descs = data.get("descriptions", {})
            result = []
            for n in names:
                result.append(
                    {
                        "name": n,
                        "description": str(descs.get(n, "")),
                        "source": "skills_research_index",
                    }
                )
            return result
        flat: list[dict[str, Any]] = []
        for v in data.values():
            if isinstance(v, list):
                for item in v:
                    if isinstance(item, dict) and "name" in item:
                        flat.append(item)
        if flat:
            return flat
    return []


def _build_retrieval_for_task(
    target_task: dict[str, Any],
    all_tasks: list[dict[str, Any]],
    external_candidates: list[dict[str, Any]],
    dataset_root: Path,
    top_k_cross: int,
    top_k_external: int,
) -> dict[str, Any]:
    schema = _build_task_schema(target_task, dataset_root)
    target_task_id = target_task["task_id"]
    target_tags = set(target_task.get("tags", []))

    original = []
    for s in target_task.get("required_skills", []):
        original.append(
            {
                "skill_id": s,
                "source": "orig",
                "retrieval_path": ["orig_curated"],
                "score": 100.0,
                "estimated_granularity": "atomic",
                "estimated_domain_specificity": "medium",
            }
        )

    cross_candidates: list[dict[str, Any]] = []
    seen_cross: set[str] = set()
    for source_task in all_tasks:
        sid = source_task["task_id"]
        if sid == target_task_id:
            continue
        for s in source_task.get("required_skills", []):
            score, reasons = _score_cross_task_candidate(source_task, s, schema, target_tags)
            if score <= 0 or s in seen_cross:
                continue
            seen_cross.add(s)
            cross_candidates.append(
                {
                    "skill_id": s,
                    "source": "cross",
                    "from_task_id": sid,
                    "retrieval_path": reasons or ["cross_task"],
                    "score": float(score),
                    "estimated_granularity": "atomic",
                    "estimated_domain_specificity": "medium",
                }
            )
    cross_candidates.sort(key=lambda x: x["score"], reverse=True)
    cross_candidates = cross_candidates[:top_k_cross]

    profile_tokens = _tokenize(_profile_text(schema))
    required_skill_set = set(schema.required_skills)
    external_ranked: list[dict[str, Any]] = []
    seen_external: set[str] = set()
    for c in external_candidates:
        name = str(c.get("name", "")).strip()
        if not name or name in seen_external:
            continue
        score, reasons = _score_external_candidate(c, profile_tokens, required_skill_set, schema.family)
        if score <= 0:
            continue
        seen_external.add(name)
        external_ranked.append(
            {
                "skill_id": name,
                "source": str(c.get("source", "external")),
                "retrieval_path": reasons or ["semantic_overlap"],
                "score": round(score, 3),
                "description": str(c.get("description", "")),
                "url": c.get("url"),
                "estimated_granularity": "unknown",
                "estimated_domain_specificity": "unknown",
            }
        )
    external_ranked.sort(key=lambda x: x["score"], reverse=True)
    external_ranked = external_ranked[:top_k_external]

    return {
        "task_id": target_task_id,
        "generated_at": datetime.now().isoformat(),
        "schema": schema.to_json(),
        "retrieval": {
            "orig": original,
            "cross": cross_candidates,
            "external": external_ranked,
        },
        "summary": {
            "n_orig": len(original),
            "n_cross": len(cross_candidates),
            "n_external": len(external_ranked),
            "n_total": len(original) + len(cross_candidates) + len(external_ranked),
        },
    }


def _select_tasks(all_tasks: list[dict[str, Any]], task_ids: list[str] | None) -> list[dict[str, Any]]:
    if not task_ids:
        return all_tasks
    task_map = {t["task_id"]: t for t in all_tasks}
    selected = []
    for tid in task_ids:
        if tid in task_map:
            selected.append(task_map[tid])
    return selected


def main() -> None:
    parser = argparse.ArgumentParser(description="Build retrieval-only skill pools (no generation API)")
    parser.add_argument("--dataset-index", type=Path, default=DEFAULT_DATASET_INDEX)
    parser.add_argument("--dataset-root", type=Path, default=DEFAULT_DATASET_ROOT)
    parser.add_argument("--external-skills-json", type=Path, default=DEFAULT_EXTERNAL_SKILLS)
    parser.add_argument(
        "--task-ids",
        type=str,
        default=None,
        help="Comma-separated task ids. If omitted, all tasks in dataset_index are used.",
    )
    parser.add_argument("--top-k-cross", type=int, default=8)
    parser.add_argument("--top-k-external", type=int, default=20)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args()

    index_data = _read_json(args.dataset_index)
    all_tasks = list(index_data.get("tasks", []))
    if not all_tasks:
        raise SystemExit("No tasks found in dataset index.")

    selected_ids = None
    if args.task_ids:
        selected_ids = [s.strip() for s in args.task_ids.split(",") if s.strip()]
    selected_tasks = _select_tasks(all_tasks, selected_ids)
    if not selected_tasks:
        raise SystemExit("No valid tasks selected.")

    external_candidates = _load_external_candidates(args.external_skills_json)

    raw_dir = args.output_root / "raw_retrieved"
    task_pool_dir = args.output_root / "task_pools"
    raw_dir.mkdir(parents=True, exist_ok=True)
    task_pool_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "generated_at": datetime.now().isoformat(),
        "dataset_index": str(args.dataset_index),
        "dataset_root": str(args.dataset_root),
        "external_skills_json": str(args.external_skills_json),
        "selected_task_ids": [t["task_id"] for t in selected_tasks],
        "top_k_cross": max(0, args.top_k_cross),
        "top_k_external": max(0, args.top_k_external),
        "results": [],
    }

    for task in selected_tasks:
        retrieval = _build_retrieval_for_task(
            target_task=task,
            all_tasks=all_tasks,
            external_candidates=external_candidates,
            dataset_root=args.dataset_root,
            top_k_cross=max(0, args.top_k_cross),
            top_k_external=max(0, args.top_k_external),
        )
        task_id = task["task_id"]
        out_path = raw_dir / f"{task_id}.json"
        out_path.write_text(json.dumps(retrieval, indent=2))

        merged_pool = []
        merged_pool.extend(retrieval["retrieval"]["orig"])
        merged_pool.extend(retrieval["retrieval"]["cross"])
        merged_pool.extend(retrieval["retrieval"]["external"])
        merged_pool_path = task_pool_dir / f"{task_id}.json"
        merged_pool_path.write_text(
            json.dumps(
                {
                    "task_id": task_id,
                    "generated_at": retrieval["generated_at"],
                    "schema": retrieval["schema"],
                    "candidate_pool": merged_pool,
                    "summary": retrieval["summary"],
                },
                indent=2,
            )
        )

        manifest["results"].append(
            {
                "task_id": task_id,
                "raw_retrieval": str(out_path),
                "task_pool": str(merged_pool_path),
                "summary": retrieval["summary"],
            }
        )
        print(
            f"[OK] {task_id}: "
            f"orig={retrieval['summary']['n_orig']} "
            f"cross={retrieval['summary']['n_cross']} "
            f"external={retrieval['summary']['n_external']}"
        )

    manifest_path = args.output_root / "metadata.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    print(f"\nDone. Manifest: {manifest_path}")
    print(f"Raw retrieval dir: {raw_dir}")
    print(f"Task pool dir: {task_pool_dir}")


if __name__ == "__main__":
    main()
