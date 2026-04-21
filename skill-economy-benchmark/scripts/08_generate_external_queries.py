
#!/usr/bin/env python3
"""Generate external retrieval queries from task schemas.

Purpose
-------
This script is the first step of the automatic external skill expansion pipeline.

It reuses the internal baseline pipeline you already built:
    dataset/ + internal skill pools -> task schema -> external query generation

It does NOT fetch webpages.
It only generates a structured query plan that later scripts can use to:
1) search official docs / trusted repos automatically
2) collect external sources
3) normalize them into external_skill_corpus.json
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_DATASET_INDEX = PROJECT_ROOT / "dataset" / "dataset_index.json"
DEFAULT_DATASET_ROOT = PROJECT_ROOT / "dataset"
DEFAULT_TASK_POOL_ROOT = PROJECT_ROOT / "skill_pool" / "task_pools"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "external_queries.json"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "external_queries"
DEFAULT_SOURCE_POLICY = PROJECT_ROOT / "data" / "source_policy.json"

TOKEN_RE = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_\-/.+]*")
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
    ".htm": "html",
    ".tex": "latex",
    ".sql": "sql",
    ".xml": "xml",
    ".yaml": "yaml",
    ".yml": "yaml",
}
WEAK_ARTIFACTS = {"json", "text", "markdown", "python"}

TAG_TO_FAMILY = {
    "excel": "spreadsheet_analytics",
    "pivot-tables": "spreadsheet_analytics",
    "spreadsheet": "spreadsheet_analytics",
    "financial-modeling": "spreadsheet_analytics",
    "latex": "document_extraction",
    "pdf": "document_extraction",
    "extraction": "document_extraction",
    "ocr": "document_extraction",
    "debugging": "debugging_ci_repair",
    "ci": "debugging_ci_repair",
    "build": "debugging_ci_repair",
    "github-actions": "debugging_ci_repair",
    "gis": "geospatial_analysis",
    "spatial-analysis": "geospatial_analysis",
    "geophysics": "geospatial_analysis",
    "statistics": "data_analytics",
    "data-cleaning": "data_analytics",
    "analysis": "data_analytics",
    "science": "scientific_analysis",
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
    "science": {"analyze", "calculate", "validate"},
}

FAMILY_DEFAULT_TOOLS = {
    "spreadsheet_analytics": {"spreadsheet", "python"},
    "document_extraction": {"pdf", "python"},
    "debugging_ci_repair": {"shell", "python", "testing", "ci"},
    "geospatial_analysis": {"python", "geospatial"},
    "data_analytics": {"python"},
    "scientific_analysis": {"python"},
    "general_problem_solving": {"shell"},
}

FAMILY_QUERY_SEEDS = {
    "spreadsheet_analytics": [
        ("family_core", "spreadsheet validation workflow python"),
        ("family_core", "openpyxl workbook editing best practices"),
        ("family_core", "pandas excel analysis workflow"),
        ("family_specific", "pivot table workflow openpyxl"),
        ("family_specific", "financial spreadsheet sanity check"),
    ],
    "document_extraction": [
        ("family_core", "pdf table extraction python workflow"),
        ("family_core", "document to structured data extraction"),
        ("family_specific", "pdf parsing best practices python"),
        ("family_specific", "layout aware document extraction python"),
    ],
    "debugging_ci_repair": [
        ("family_core", "github actions log triage workflow"),
        ("family_core", "pytest debugging workflow"),
        ("family_core", "dependency conflict troubleshooting python"),
        ("family_specific", "uv package manager troubleshooting"),
        ("family_specific", "minimal validation after fix python"),
    ],
    "geospatial_analysis": [
        ("family_core", "geopandas projection best practices"),
        ("family_core", "point to line distance geopandas"),
        ("family_core", "spatial filtering geopandas workflow"),
        ("family_specific", "unary_union distance workflow geopandas"),
        ("family_specific", "crs transformation distance calculation geopandas"),
    ],
    "data_analytics": [
        ("family_core", "data analysis validation workflow python"),
        ("family_core", "aggregation and verification patterns pandas"),
        ("family_specific", "structured data transformation checklist"),
    ],
    "scientific_analysis": [
        ("family_core", "scientific python data analysis workflow"),
        ("family_core", "numerical result verification workflow"),
        ("family_specific", "unit conversion and validation scientific python"),
    ],
    "general_problem_solving": [
        ("family_core", "result verification checklist"),
        ("family_core", "step decomposition workflow"),
        ("family_specific", "intermediate state validation workflow"),
    ],
}

SKILL_ALIAS_HINTS = {
    "xlsx": [
        "openpyxl excel workflow",
        "pandas excel validation",
        "spreadsheet formula verification",
    ],
    "pdf": [
        "pdf table extraction python",
        "document extraction structured output",
    ],
    "geospatial-analysis": [
        "geopandas spatial analysis workflow",
        "projection distance calculation geopandas",
        "spatial filtering unary_union geopandas",
    ],
    "analyze-ci": [
        "github actions failure analysis workflow",
        "ci log root cause analysis",
    ],
    "testing-python": [
        "pytest test design best practices",
        "python testing debugging workflow",
    ],
    "temporal-python-testing": [
        "temporal python testing workflow",
        "workflow replay testing python",
    ],
    "uv-package-manager": [
        "uv dependency resolution troubleshooting",
        "uv package manager workflow python",
    ],
}

TOOL_QUERY_SEEDS = {
    "python": [
        ("tool_workflow", "python best practices workflow"),
    ],
    "spreadsheet": [
        ("tool_workflow", "openpyxl workbook workflow"),
        ("tool_workflow", "spreadsheet validation python"),
    ],
    "pdf": [
        ("tool_workflow", "pdf extraction python best practices"),
    ],
    "testing": [
        ("tool_workflow", "pytest debugging and validation workflow"),
    ],
    "ci": [
        ("tool_workflow", "github actions troubleshooting workflow"),
    ],
    "geospatial": [
        ("tool_workflow", "geopandas spatial analysis best practices"),
    ],
    "shell": [
        ("tool_workflow", "cli workflow validation best practices"),
    ],
}

DEFAULT_SOURCE_POLICY_DATA = {
    "global_allowed_domains": [
        "github.com",
        "readthedocs.io",
    ],
    "domains_by_family": {
        "spreadsheet_analytics": [
            "openpyxl.readthedocs.io",
            "pandas.pydata.org",
            "xlsxwriter.readthedocs.io",
            "github.com",
        ],
        "document_extraction": [
            "pdfplumber.readthedocs.io",
            "pymupdf.readthedocs.io",
            "github.com",
            "readthedocs.io",
        ],
        "debugging_ci_repair": [
            "docs.pytest.org",
            "docs.astral.sh",
            "docs.github.com",
            "github.com",
        ],
        "geospatial_analysis": [
            "geopandas.org",
            "shapely.readthedocs.io",
            "pyproj4.github.io",
            "github.com",
        ],
        "data_analytics": [
            "pandas.pydata.org",
            "numpy.org",
            "github.com",
        ],
        "scientific_analysis": [
            "numpy.org",
            "scipy.org",
            "matplotlib.org",
            "github.com",
        ],
        "general_problem_solving": [
            "github.com",
            "readthedocs.io",
        ],
    },
}

QUERY_TYPE_PRIOR = {
    "family_core": 1.00,
    "family_specific": 0.95,
    "artifact_operation": 0.93,
    "tool_workflow": 0.88,
    "skill_neighbor": 0.97,
    "tag_specialization": 0.86,
    "generic_validation": 0.82,
    "domain_specialization": 0.84,
}

GENERIC_OPERATION_TERMS = {
    "extract": ["extraction workflow", "structured extraction"],
    "transform": ["transformation workflow", "normalization workflow"],
    "aggregate": ["aggregation workflow"],
    "calculate": ["calculation workflow", "numeric validation"],
    "validate": ["validation checklist", "sanity check"],
    "verify": ["result verification", "output checking"],
    "debug": ["debugging workflow", "error diagnosis"],
    "patch": ["repair workflow", "minimal fix validation"],
    "analyze": ["analysis workflow"],
    "compare": ["diff and compare workflow"],
    "plan": ["step decomposition workflow"],
    "search": ["retrieval workflow"],
    "clean": ["data cleaning workflow"],
    "summarize": ["summarization workflow"],
    "optimize": ["optimization workflow"],
}

ARTIFACT_CANONICAL_TERMS = {
    "xlsx": ["excel", "spreadsheet", "workbook"],
    "csv": ["csv", "tabular data"],
    "pdf": ["pdf", "document"],
    "html": ["html", "webpage"],
    "latex": ["latex", "formula document"],
    "sql": ["sql", "database"],
    "xml": ["xml", "structured document"],
    "yaml": ["yaml", "configuration"],
    "notebook": ["notebook", "jupyter"],
}

TOOL_CANONICAL_TERMS = {
    "spreadsheet": ["openpyxl", "pandas excel"],
    "pdf": ["pdfplumber", "pymupdf"],
    "geospatial": ["geopandas", "shapely", "pyproj"],
    "testing": ["pytest"],
    "ci": ["github actions"],
    "python": ["python"],
    "database": ["sqlalchemy", "database"],
    "browser": ["playwright", "selenium"],
    "shell": ["bash", "cli"],
    "latex": ["latex"],
}


def _read_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _normalize_token(token: str) -> str:
    token = token.lower().strip().replace("/", "_")
    if token.endswith("s") and len(token) > 4:
        token = token[:-1]
    return token


def _tokenize(text: str) -> set[str]:
    return {_normalize_token(t) for t in TOKEN_RE.findall(text or "") if len(t) >= 2}


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


def _infer_family_candidates(domain: str, tags: list[str], artifacts: list[str]) -> list[str]:
    votes: dict[str, int] = {}
    for tag in tags:
        fam = TAG_TO_FAMILY.get(_normalize_token(tag))
        if fam:
            votes[fam] = votes.get(fam, 0) + 2
    if "xlsx" in artifacts or "csv" in artifacts:
        votes["spreadsheet_analytics"] = votes.get("spreadsheet_analytics", 0) + 2
    if "pdf" in artifacts or "latex" in artifacts:
        votes["document_extraction"] = votes.get("document_extraction", 0) + 2
    low_domain = domain.lower()
    if "software" in low_domain or "engineering" in low_domain:
        votes["debugging_ci_repair"] = votes.get("debugging_ci_repair", 0) + 2
    if "science" in low_domain:
        votes["scientific_analysis"] = votes.get("scientific_analysis", 0) + 1
    if not votes:
        return ["general_problem_solving"]
    ranked = sorted(votes.items(), key=lambda x: (-x[1], x[0]))
    best = ranked[0][1]
    top = [fam for fam, score in ranked if score == best]
    return sorted(top)


def _detect_operations(tags: list[str], artifacts: list[str], domain: str) -> list[str]:
    ops = {"verify"}
    for tag in tags:
        ops |= TAG_TO_OPERATIONS.get(_normalize_token(tag), set())
    if "xlsx" in artifacts or "csv" in artifacts:
        ops |= {"extract", "aggregate", "validate"}
    if "pdf" in artifacts:
        ops |= {"extract", "transform"}
    low_domain = domain.lower()
    if low_domain.startswith("software"):
        ops |= {"debug", "patch", "validate"}
    if "science" in low_domain:
        ops |= {"analyze", "calculate", "validate"}
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
    family_candidates: list[str] = field(default_factory=list)
    original_curated_skills: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class QueryCandidate:
    query_id: str
    text: str
    query_type: str
    priority: float
    rationale: str
    family: str
    suggested_domains: list[str] = field(default_factory=list)
    source_hints: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


def _build_task_schema_from_meta(task_meta: dict[str, Any], dataset_root: Path) -> TaskSchema:
    task_id = task_meta["task_id"]
    domain = str(task_meta.get("domain", "unknown"))
    tags = _safe_list_str(task_meta.get("tags", []))
    original_curated = _safe_list_str(task_meta.get("required_skills", []))
    artifacts = _detect_artifacts(dataset_root / task_id)
    family_candidates = _infer_family_candidates(domain, tags, artifacts)
    family = family_candidates[0] if family_candidates else "general_problem_solving"
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
        family_candidates=family_candidates,
        original_curated_skills=original_curated,
    )


def _load_task_schema_from_pool(task_pool_file: Path) -> TaskSchema | None:
    if not task_pool_file.exists():
        return None
    data = _read_json(task_pool_file)
    schema = data.get("schema")
    if not isinstance(schema, dict):
        return None
    return TaskSchema(
        task_id=str(schema.get("task_id")),
        family=str(schema.get("family") or "general_problem_solving"),
        domain=str(schema.get("domain") or "unknown"),
        artifacts=_safe_list_str(schema.get("artifacts")),
        operations=_safe_list_str(schema.get("operations")),
        tools=_safe_list_str(schema.get("tools")),
        output_type=str(schema.get("output_type") or "structured_output_or_file_update"),
        constraints=_safe_list_str(schema.get("constraints")),
        tags=_safe_list_str(schema.get("tags")),
        family_candidates=_safe_list_str(schema.get("family_candidates") or [schema.get("family")]),
        original_curated_skills=_safe_list_str(schema.get("original_curated_skills")),
    )


def _load_internal_pool_skill_ids(task_pool_file: Path) -> list[str]:
    if not task_pool_file.exists():
        return []
    data = _read_json(task_pool_file)
    pool = data.get("balanced_task_pool", [])
    if not isinstance(pool, list):
        return []
    out = []
    for item in pool:
        if isinstance(item, dict) and item.get("skill_id"):
            out.append(str(item["skill_id"]))
    return sorted(dict.fromkeys(out))


def _load_source_policy(path: Path | None) -> dict[str, Any]:
    if path and path.exists():
        return _read_json(path)
    return DEFAULT_SOURCE_POLICY_DATA


def _dedupe_keep_best(candidates: list[QueryCandidate]) -> list[QueryCandidate]:
    best: dict[str, QueryCandidate] = {}
    for cand in sorted(candidates, key=lambda x: (-x.priority, x.text)):
        key = " ".join(sorted(_tokenize(cand.text)))
        if not key:
            key = cand.text.lower().strip()
        if key not in best:
            best[key] = cand
    return sorted(best.values(), key=lambda x: (-x.priority, x.text))


def _artifact_terms(artifacts: list[str]) -> list[str]:
    out: list[str] = []
    for art in artifacts:
        if art in WEAK_ARTIFACTS:
            continue
        out.extend(ARTIFACT_CANONICAL_TERMS.get(art, [art]))
    return sorted(dict.fromkeys(out))


def _tool_terms(tools: list[str]) -> list[str]:
    out: list[str] = []
    for tool in tools:
        out.extend(TOOL_CANONICAL_TERMS.get(tool, [tool]))
    return sorted(dict.fromkeys(out))


def _allowed_domains_for_family(family: str, source_policy: dict[str, Any]) -> list[str]:
    domains_by_family = source_policy.get("domains_by_family", {})
    global_domains = source_policy.get("global_allowed_domains", [])
    return sorted(set(global_domains) | set(domains_by_family.get(family, [])))


def _make_query_id(task_id: str, query_type: str, idx: int) -> str:
    return f"{task_id}::{query_type}::{idx:02d}"


def _make_candidate(
    task: TaskSchema,
    query_type: str,
    text: str,
    rationale: str,
    source_policy: dict[str, Any],
    evidence: dict[str, Any],
) -> QueryCandidate:
    priority = QUERY_TYPE_PRIOR.get(query_type, 0.75)
    if task.family in text:
        priority += 0.05
    if any(skill in text for skill in task.original_curated_skills):
        priority += 0.03
    return QueryCandidate(
        query_id="",
        text=text,
        query_type=query_type,
        priority=round(priority, 3),
        rationale=rationale,
        family=task.family,
        suggested_domains=_allowed_domains_for_family(task.family, source_policy),
        source_hints=["official_docs", "trusted_repo_docs", "examples", "how_to_guides"],
        evidence=evidence,
    )


def _generate_family_queries(task: TaskSchema, source_policy: dict[str, Any]) -> list[QueryCandidate]:
    seeds = FAMILY_QUERY_SEEDS.get(task.family, FAMILY_QUERY_SEEDS["general_problem_solving"])
    out: list[QueryCandidate] = []
    for query_type, text in seeds:
        out.append(
            _make_candidate(
                task,
                query_type=query_type,
                text=text,
                rationale="family-level reusable workflow query",
                source_policy=source_policy,
                evidence={"family": task.family},
            )
        )
    return out


def _generate_artifact_operation_queries(task: TaskSchema, source_policy: dict[str, Any]) -> list[QueryCandidate]:
    out: list[QueryCandidate] = []
    artifacts = _artifact_terms(task.artifacts)
    ops = [op for op in task.operations if op in GENERIC_OPERATION_TERMS]
    tools = _tool_terms(task.tools)

    for art in artifacts[:3]:
        for op in ops[:4]:
            for op_term in GENERIC_OPERATION_TERMS.get(op, []):
                text = f"{art} {op_term} python"
                out.append(
                    _make_candidate(
                        task,
                        query_type="artifact_operation",
                        text=text,
                        rationale="artifact + operation query derived from task schema",
                        source_policy=source_policy,
                        evidence={"artifact": art, "operation": op},
                    )
                )

    for art in artifacts[:2]:
        for tool in tools[:2]:
            text = f"{art} {tool} workflow"
            out.append(
                _make_candidate(
                    task,
                    query_type="artifact_operation",
                    text=text,
                    rationale="artifact + tool query derived from task schema",
                    source_policy=source_policy,
                    evidence={"artifact": art, "tool": tool},
                )
            )
    return out


def _generate_tool_queries(task: TaskSchema, source_policy: dict[str, Any]) -> list[QueryCandidate]:
    out: list[QueryCandidate] = []
    for tool in task.tools:
        for query_type, seed in TOOL_QUERY_SEEDS.get(tool, []):
            out.append(
                _make_candidate(
                    task,
                    query_type=query_type,
                    text=seed,
                    rationale="tool-driven reusable search query",
                    source_policy=source_policy,
                    evidence={"tool": tool},
                )
            )
    return out


def _generate_tag_queries(task: TaskSchema, source_policy: dict[str, Any]) -> list[QueryCandidate]:
    out: list[QueryCandidate] = []
    for tag in task.tags[:6]:
        norm = _normalize_token(tag)
        if norm in {"excel", "pdf", "ci", "debugging", "statistics", "analysis"}:
            continue
        text = f"{norm.replace('_', ' ')} workflow best practices"
        out.append(
            _make_candidate(
                task,
                query_type="tag_specialization",
                text=text,
                rationale="tag/domain specialization query",
                source_policy=source_policy,
                evidence={"tag": tag},
            )
        )
    if task.domain and task.domain != "unknown":
        text = f"{task.domain.replace('-', ' ')} python workflow"
        out.append(
            _make_candidate(
                task,
                query_type="domain_specialization",
                text=text,
                rationale="domain specialization query",
                source_policy=source_policy,
                evidence={"domain": task.domain},
            )
        )
    return out


def _generate_skill_neighbor_queries(task: TaskSchema, internal_pool_skills: list[str], source_policy: dict[str, Any]) -> list[QueryCandidate]:
    out: list[QueryCandidate] = []
    seen = task.original_curated_skills + internal_pool_skills
    for skill_id in seen:
        aliases = SKILL_ALIAS_HINTS.get(skill_id, [])
        for alias in aliases:
            out.append(
                _make_candidate(
                    task,
                    query_type="skill_neighbor",
                    text=alias,
                    rationale="neighbor query derived from internal baseline skills",
                    source_policy=source_policy,
                    evidence={"skill_id": skill_id},
                )
            )
    return out


def _generate_generic_validation_queries(task: TaskSchema, source_policy: dict[str, Any]) -> list[QueryCandidate]:
    out: list[QueryCandidate] = []
    candidates = [
        "result verification checklist",
        "intermediate state validation workflow",
        "step decomposition workflow",
    ]
    for text in candidates:
        out.append(
            _make_candidate(
                task,
                query_type="generic_validation",
                text=text,
                rationale="generic procedural query for reusable control skills",
                source_policy=source_policy,
                evidence={"family": "general_problem_solving"},
            )
        )
    return out


def _generate_queries_for_task(
    task: TaskSchema,
    internal_pool_skills: list[str],
    source_policy: dict[str, Any],
    max_queries_per_task: int,
) -> list[QueryCandidate]:
    all_candidates: list[QueryCandidate] = []
    all_candidates.extend(_generate_family_queries(task, source_policy))
    all_candidates.extend(_generate_artifact_operation_queries(task, source_policy))
    all_candidates.extend(_generate_tool_queries(task, source_policy))
    all_candidates.extend(_generate_tag_queries(task, source_policy))
    all_candidates.extend(_generate_skill_neighbor_queries(task, internal_pool_skills, source_policy))
    all_candidates.extend(_generate_generic_validation_queries(task, source_policy))

    deduped = _dedupe_keep_best(all_candidates)
    trimmed = deduped[:max_queries_per_task]
    for idx, cand in enumerate(trimmed, start=1):
        cand.query_id = _make_query_id(task.task_id, cand.query_type, idx)
    return trimmed


def _select_tasks(all_tasks: list[dict[str, Any]], task_ids: list[str] | None) -> list[dict[str, Any]]:
    if not task_ids:
        return all_tasks
    lookup = {str(t["task_id"]): t for t in all_tasks if "task_id" in t}
    return [lookup[tid] for tid in task_ids if tid in lookup]


def build_external_queries(
    dataset_index: Path,
    dataset_root: Path,
    task_pool_root: Path,
    output: Path,
    output_dir: Path,
    source_policy_path: Path | None,
    task_ids: list[str] | None,
    max_queries_per_task: int,
) -> dict[str, Any]:
    index_data = _read_json(dataset_index)
    all_tasks = list(index_data.get("tasks", []))
    if not all_tasks:
        raise SystemExit("No tasks found in dataset index.")

    selected_tasks = _select_tasks(all_tasks, task_ids)
    if not selected_tasks:
        raise SystemExit("No valid tasks selected.")

    source_policy = _load_source_policy(source_policy_path)
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest: dict[str, Any] = {
        "generated_at": datetime.now().isoformat(),
        "dataset_index": str(dataset_index),
        "dataset_root": str(dataset_root),
        "task_pool_root": str(task_pool_root),
        "max_queries_per_task": max_queries_per_task,
        "source_policy_path": str(source_policy_path) if source_policy_path and source_policy_path.exists() else None,
        "selected_task_ids": [t["task_id"] for t in selected_tasks],
        "tasks": [],
    }

    for task_meta in selected_tasks:
        task_id = str(task_meta["task_id"])
        pool_file = task_pool_root / f"{task_id}.json"

        task_schema = _load_task_schema_from_pool(pool_file)
        if task_schema is None:
            task_schema = _build_task_schema_from_meta(task_meta, dataset_root)

        internal_pool_skills = _load_internal_pool_skill_ids(pool_file)
        queries = _generate_queries_for_task(
            task=task_schema,
            internal_pool_skills=internal_pool_skills,
            source_policy=source_policy,
            max_queries_per_task=max_queries_per_task,
        )

        task_payload = {
            "task_id": task_id,
            "generated_at": datetime.now().isoformat(),
            "schema": task_schema.to_json(),
            "internal_pool_skills": internal_pool_skills,
            "source_policy": {
                "allowed_domains": _allowed_domains_for_family(task_schema.family, source_policy),
            },
            "queries": [q.to_json() for q in queries],
            "summary": {
                "n_queries": len(queries),
                "family": task_schema.family,
                "artifacts": task_schema.artifacts,
                "tools": task_schema.tools,
            },
        }

        task_file = output_dir / f"{task_id}.json"
        _write_json(task_file, task_payload)

        manifest["tasks"].append(
            {
                "task_id": task_id,
                "family": task_schema.family,
                "query_file": str(task_file),
                "n_queries": len(queries),
            }
        )
        print(f"[OK] {task_id}: queries={len(queries)} family={task_schema.family}")

    _write_json(output, manifest)
    return {
        "manifest_path": str(output),
        "per_task_dir": str(output_dir),
        "n_tasks": len(manifest["tasks"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate external retrieval queries from task schemas.")
    parser.add_argument("--dataset-index", type=Path, default=DEFAULT_DATASET_INDEX)
    parser.add_argument("--dataset-root", type=Path, default=DEFAULT_DATASET_ROOT)
    parser.add_argument("--task-pool-root", type=Path, default=DEFAULT_TASK_POOL_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--source-policy", type=Path, default=DEFAULT_SOURCE_POLICY)
    parser.add_argument("--task-ids", type=str, default=None, help="Comma-separated task ids")
    parser.add_argument("--max-queries-per-task", type=int, default=10)
    args = parser.parse_args()

    selected_ids = [x.strip() for x in args.task_ids.split(",") if x.strip()] if args.task_ids else None

    result = build_external_queries(
        dataset_index=args.dataset_index,
        dataset_root=args.dataset_root,
        task_pool_root=args.task_pool_root,
        output=args.output,
        output_dir=args.output_dir,
        source_policy_path=args.source_policy,
        task_ids=selected_ids,
        max_queries_per_task=args.max_queries_per_task,
    )
    print("[OK] external query generation finished")
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
