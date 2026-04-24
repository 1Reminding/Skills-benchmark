#!/usr/bin/env python3
"""Build richer task schemas for SkillsBench-style tasks.

Rules-first, optional API-on-ambiguity refinement.
Produces backward-compatible fields plus richer semantic fields.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import tomllib
except Exception:  # pragma: no cover
    import tomli as tomllib  # type: ignore

try:
    import openai
except Exception:  # pragma: no cover
    openai = None  # type: ignore

PROJECT_ROOT = Path(__file__).resolve().parent.parent

TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_\-/.+]*")
WS_RE = re.compile(r"\s+")
JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", re.DOTALL)

CONTROLLED_FAMILIES = [
    "spreadsheet_analytics",
    "document_extraction",
    "debugging_ci_repair",
    "geospatial_analysis",
    "data_analytics",
    "scientific_analysis",
    "general_problem_solving",
]
CONTROLLED_ARTIFACTS = ["xlsx", "csv", "pdf", "html", "json", "notebook", "latex", "xml", "yaml", "txt"]
CONTROLLED_TOOLS = ["python", "spreadsheet", "pdf", "ci", "testing", "shell", "geospatial", "browser"]
CONTROLLED_OPERATIONS = [
    "extract", "transform", "aggregate", "calculate", "analyze",
    "validate", "verify", "debug", "patch", "search", "plan"
]
GRANULARITIES = ["atomic", "compositional", "generic"]

ARTIFACT_ALIASES = {
    "xlsx": {"xlsx", "xls", "excel", "spreadsheet", "workbook", "openpyxl", "xlsxwriter"},
    "csv": {"csv", "tsv", "tabular", "dataframe"},
    "pdf": {"pdf", "ocr", "document", "table-extract"},
    "html": {"html", "webpage", "dom"},
    "json": {"json"},
    "notebook": {"ipynb", "notebook", "jupyter"},
    "latex": {"latex", "tex"},
    "xml": {"xml"},
    "yaml": {"yaml", "yml"},
    "txt": {"txt", "text", "plain-text"},
}
TOOL_ALIASES = {
    "python": {"python", "pandas", "numpy", "openpyxl", "script", "jupyter"},
    "spreadsheet": {"excel", "spreadsheet", "workbook", "openpyxl", "pivot"},
    "pdf": {"pdf", "ocr", "pdfplumber", "pymupdf", "camelot", "tabula"},
    "ci": {"ci", "github_actions", "workflow", "runner", "pipeline"},
    "testing": {"pytest", "test", "testing", "unittest"},
    "shell": {"bash", "shell", "cli", "terminal", "uv", "make"},
    "geospatial": {"geopandas", "shapely", "pyproj", "gis", "crs", "geometry"},
    "browser": {"browser", "dom", "html", "selenium", "playwright"},
}
OP_ALIASES = {
    "extract": {"extract", "extraction", "parse", "parsing", "read", "ingest"},
    "transform": {"transform", "conversion", "convert", "normalize", "clean", "coerce", "update", "modify"},
    "aggregate": {"aggregate", "aggregation", "groupby", "pivot", "summarize", "merge", "join"},
    "calculate": {"calculate", "calculation", "compute", "formula", "weighted", "metric"},
    "analyze": {"analyze", "analysis", "inspect", "eda"},
    "validate": {"validate", "validation", "schema-check", "sanity-check"},
    "verify": {"verify", "verification", "assert", "check", "deterministic_verifier"},
    "debug": {"debug", "troubleshoot", "error", "failure", "fix-build"},
    "patch": {"patch", "repair", "fix", "edit", "update-dependency"},
    "search": {"search", "retrieve", "lookup"},
    "plan": {"plan", "workflow", "steps", "procedure"},
}
FAMILY_CUES = {
    "spreadsheet_analytics": {"excel", "spreadsheet", "xlsx", "openpyxl", "pivot", "workbook", "sheet", "formula"},
    "document_extraction": {"pdf", "ocr", "document", "table", "extract", "extraction", "img2table", "pdfplumber", "pymupdf"},
    "debugging_ci_repair": {"ci", "pytest", "test", "testing", "debug", "build", "workflow", "runner", "dependency", "uv"},
    "geospatial_analysis": {"geospatial", "geopandas", "shapely", "pyproj", "gis", "geometry", "crs", "earthquake"},
    "data_analytics": {"dataframe", "analysis", "csv", "statistics", "pandas", "aggregation"},
    "scientific_analysis": {"scientific", "simulation", "physics", "bioinformatics", "chemistry", "matplotlib", "numpy", "scipy"},
    "general_problem_solving": {"workflow", "guide", "automation"},
}
NEGATIVE_QUERY_TERMS = {"archive", "changelog", "release", "news", "requirements", "lockfile", "brand", "marketing", "landing-page", "theme", "internal-comms"}

def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))

def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

def _now_iso() -> str:
    return datetime.now().isoformat()

def _normalize_token(token: str) -> str:
    token = token.lower().strip().replace("/", "_")
    if token.endswith("s") and len(token) > 4:
        token = token[:-1]
    return token

def _tokenize(text: str) -> set[str]:
    return {_normalize_token(t) for t in TOKEN_RE.findall(text or "") if len(t) >= 2}

def _compact(text: str) -> str:
    return WS_RE.sub(" ", (text or "")).strip()

def _safe_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    return [str(value).strip()] if str(value).strip() else []

def _extract_json(text: str) -> Any:
    text = text.strip()
    m = JSON_BLOCK_RE.search(text)
    if m:
        frag = m.group(1).strip()
        try:
            return json.loads(frag)
        except Exception:
            pass
    try:
        return json.loads(text)
    except Exception:
        pass
    for oc, cc in [("{", "}"), ("[", "]")]:
        s = text.find(oc)
        e = text.rfind(cc)
        if s != -1 and e != -1 and e > s:
            frag = text[s:e+1]
            try:
                return json.loads(frag)
            except Exception:
                pass
    raise ValueError("Could not parse JSON from model output.")

def _slugify(text: str) -> str:
    out = re.sub(r"[^A-Za-z0-9]+", "-", text.lower()).strip("-")
    return out or "unknown"

def _read_text_if_exists(path: Path, max_chars: int = 8000) -> str:
    if not path.exists() or not path.is_file():
        return ""
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = path.read_text(encoding="latin-1", errors="replace")
    return text[:max_chars]

def _load_task_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _list_relative_files(root: Path, max_files: int = 200) -> list[str]:
    if not root.exists():
        return []
    out = []
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out.append(str(p.relative_to(root)).replace("\\", "/"))
        if len(out) >= max_files:
            break
    return out

def build_ontology(dataset_tasks: list[dict[str, Any]], dataset_root: Path) -> dict[str, Any]:
    domains, tags, required_skills, suffixes, family_obs = Counter(), Counter(), Counter(), Counter(), Counter()
    for task in dataset_tasks:
        task_id = str(task.get("task_id", "")).strip()
        if not task_id:
            continue
        domains.update(_safe_list(task.get("domain")))
        tags.update(_safe_list(task.get("tags")))
        required_skills.update(_safe_list(task.get("required_skills")))
        env_root = dataset_root / task_id / "environment"
        for rel in _list_relative_files(env_root, max_files=80):
            suf = Path(rel).suffix.lower()
            if suf:
                suffixes[suf] += 1
        toks = set()
        toks |= _tokenize(" ".join(_safe_list(task.get("tags"))))
        toks |= _tokenize(" ".join(_safe_list(task.get("required_skills"))))
        toks |= _tokenize(str(task.get("domain", "")))
        fam_scores = {fam: len(cues & toks) for fam, cues in FAMILY_CUES.items()}
        fam = max(fam_scores, key=fam_scores.get)
        if fam_scores[fam] == 0:
            fam = "general_problem_solving"
        family_obs[fam] += 1
    return {
        "generated_at": _now_iso(),
        "controlled_families": CONTROLLED_FAMILIES,
        "controlled_artifacts": CONTROLLED_ARTIFACTS,
        "controlled_tools": CONTROLLED_TOOLS,
        "controlled_operations": CONTROLLED_OPERATIONS,
        "granularities": GRANULARITIES,
        "aliases": {
            "artifacts": {k: sorted(v) for k, v in ARTIFACT_ALIASES.items()},
            "tools": {k: sorted(v) for k, v in TOOL_ALIASES.items()},
            "operations": {k: sorted(v) for k, v in OP_ALIASES.items()},
            "family_cues": {k: sorted(v) for k, v in FAMILY_CUES.items()},
        },
        "observed_distribution": {
            "domains": domains.most_common(),
            "tags": tags.most_common(),
            "required_skills": required_skills.most_common(),
            "file_suffixes": suffixes.most_common(),
            "family_observations": family_obs.most_common(),
        },
        "family_to_tool_priors": {
            "spreadsheet_analytics": ["python", "spreadsheet"],
            "document_extraction": ["pdf", "python"],
            "debugging_ci_repair": ["python", "testing", "ci", "shell"],
            "geospatial_analysis": ["python", "geospatial"],
            "data_analytics": ["python"],
            "scientific_analysis": ["python"],
            "general_problem_solving": ["python"],
        },
        "family_to_operation_priors": {
            "spreadsheet_analytics": ["extract", "transform", "aggregate", "validate", "verify", "calculate"],
            "document_extraction": ["extract", "transform", "validate"],
            "debugging_ci_repair": ["debug", "patch", "validate", "verify"],
            "geospatial_analysis": ["extract", "transform", "analyze", "calculate"],
            "data_analytics": ["extract", "transform", "aggregate", "analyze"],
            "scientific_analysis": ["extract", "transform", "calculate", "analyze"],
            "general_problem_solving": ["plan", "search", "validate"],
        },
    }

def _infer_artifacts(task: dict[str, Any], task_root: Path) -> tuple[list[str], dict[str, list[str]]]:
    reasons = defaultdict(list)
    scores = Counter()
    toks = set()
    toks |= _tokenize(" ".join(_safe_list(task.get("tags"))))
    toks |= _tokenize(" ".join(_safe_list(task.get("required_skills"))))
    toks |= _tokenize(str(task.get("instruction_file", "")))
    for rel in _list_relative_files(task_root / "environment", max_files=120):
        toks |= _tokenize(rel)
        suf = Path(rel).suffix.lower()
        if suf in {".xlsx", ".xls"}:
            scores["xlsx"] += 4; reasons["xlsx"].append(f"env_file:{rel}")
        elif suf == ".csv":
            scores["csv"] += 4; reasons["csv"].append(f"env_file:{rel}")
        elif suf == ".pdf":
            scores["pdf"] += 4; reasons["pdf"].append(f"env_file:{rel}")
        elif suf in {".html", ".htm"}:
            scores["html"] += 3; reasons["html"].append(f"env_file:{rel}")
        elif suf == ".json":
            scores["json"] += 1; reasons["json"].append(f"env_file:{rel}")
        elif suf == ".ipynb":
            scores["notebook"] += 3; reasons["notebook"].append(f"env_file:{rel}")
        elif suf in {".tex", ".latex"}:
            scores["latex"] += 3; reasons["latex"].append(f"env_file:{rel}")
    for art, aliases in ARTIFACT_ALIASES.items():
        overlap = toks & aliases
        if overlap:
            scores[art] += len(overlap)
            reasons[art].append("token_overlap:" + ",".join(sorted(overlap)))
    ordered = [k for k, v in scores.most_common() if v > 0 and k in CONTROLLED_ARTIFACTS]
    return ordered, dict(reasons)

def _infer_tools(task: dict[str, Any], task_root: Path, artifacts: list[str]) -> tuple[list[str], dict[str, list[str]]]:
    reasons = defaultdict(list)
    scores = Counter()
    toks = set()
    toks |= _tokenize(" ".join(_safe_list(task.get("tags"))))
    toks |= _tokenize(" ".join(_safe_list(task.get("required_skills"))))
    toks |= _tokenize(str(task.get("domain", "")))
    for rel in _list_relative_files(task_root / "environment", max_files=120):
        toks |= _tokenize(rel)
    for rel in _list_relative_files(task_root / "tests", max_files=80):
        toks |= _tokenize(rel)
    toks |= _tokenize(_read_text_if_exists(task_root / "instruction.md", max_chars=6000))
    for tool, aliases in TOOL_ALIASES.items():
        overlap = toks & aliases
        if overlap:
            scores[tool] += len(overlap)
            reasons[tool].append("token_overlap:" + ",".join(sorted(overlap)))
    if "xlsx" in artifacts or "csv" in artifacts:
        scores["spreadsheet"] += 2; reasons["spreadsheet"].append("artifact_prior")
    if "pdf" in artifacts:
        scores["pdf"] += 2; reasons["pdf"].append("artifact_prior")
    if any((task_root / p).exists() for p in ["solution", "tests"]):
        scores["python"] += 1; reasons["python"].append("repo_structure_prior")
    if any(tok in toks for tok in {"pytest", "test", "testing"}):
        scores["testing"] += 2; reasons["testing"].append("pytest_or_test_token")
    if any(tok in toks for tok in {"ci", "workflow", "github_actions", "runner"}):
        scores["ci"] += 2; reasons["ci"].append("ci_token")
    if any(tok in toks for tok in {"bash", "shell", "uv", "make", "terminal", "cli"}):
        scores["shell"] += 2; reasons["shell"].append("shell_token")
    ordered = [k for k, v in scores.most_common() if v > 0 and k in CONTROLLED_TOOLS]
    return ordered, dict(reasons)

def _infer_operations(task: dict[str, Any], task_root: Path) -> tuple[list[str], dict[str, list[str]]]:
    reasons = defaultdict(list)
    scores = Counter()
    toks = set()
    toks |= _tokenize(" ".join(_safe_list(task.get("tags"))))
    toks |= _tokenize(" ".join(_safe_list(task.get("required_skills"))))
    toks |= _tokenize(str(task.get("domain", "")))
    toks |= _tokenize(_read_text_if_exists(task_root / "instruction.md", max_chars=8000))
    toks |= _tokenize(_read_text_if_exists(task_root / "solution" / "README.md", max_chars=4000))
    for rel in _list_relative_files(task_root / "tests", max_files=100):
        toks |= _tokenize(rel)
    for op, aliases in OP_ALIASES.items():
        overlap = toks & aliases
        if overlap:
            scores[op] += len(overlap)
            reasons[op].append("token_overlap:" + ",".join(sorted(overlap)))
    if "deterministic_verifier" in _safe_list(task.get("tags")):
        scores["verify"] += 2; reasons["verify"].append("deterministic_verifier_tag")
    ordered = [k for k, v in scores.most_common() if v > 0 and k in CONTROLLED_OPERATIONS]
    return ordered, dict(reasons)

def _infer_family(task: dict[str, Any], task_root: Path, artifacts: list[str], tools: list[str], operations: list[str]) -> tuple[str, list[str], dict[str, list[str]]]:
    reasons = defaultdict(list)
    scores = Counter()
    toks = set()
    toks |= _tokenize(" ".join(_safe_list(task.get("tags"))))
    toks |= _tokenize(" ".join(_safe_list(task.get("required_skills"))))
    toks |= _tokenize(str(task.get("domain", "")))
    toks |= _tokenize(_read_text_if_exists(task_root / "instruction.md", max_chars=7000))
    for fam, cues in FAMILY_CUES.items():
        overlap = toks & cues
        if overlap:
            scores[fam] += len(overlap)
            reasons[fam].append("token_overlap:" + ",".join(sorted(overlap)))
    if "xlsx" in artifacts or "spreadsheet" in tools:
        scores["spreadsheet_analytics"] += 2; reasons["spreadsheet_analytics"].append("artifact_tool_prior")
    if "pdf" in artifacts:
        scores["document_extraction"] += 2; reasons["document_extraction"].append("artifact_prior")
    if "ci" in tools or "testing" in tools or "debug" in operations or "patch" in operations:
        scores["debugging_ci_repair"] += 2; reasons["debugging_ci_repair"].append("tool_op_prior")
    if "geospatial" in tools:
        scores["geospatial_analysis"] += 2; reasons["geospatial_analysis"].append("tool_prior")
    if "calculate" in operations and "aggregate" in operations and "xlsx" in artifacts:
        scores["spreadsheet_analytics"] += 1; reasons["spreadsheet_analytics"].append("calc_agg_xlsx_prior")
    if "analyze" in operations and "csv" in artifacts:
        scores["data_analytics"] += 1; reasons["data_analytics"].append("analysis_csv_prior")
    ordered = [k for k, v in scores.most_common() if v > 0]
    family = ordered[0] if ordered else "general_problem_solving"
    return family, (ordered[:3] if ordered else ["general_problem_solving"]), dict(reasons)

def _infer_output_type(task_root: Path, instruction_text: str, artifacts: list[str]) -> str:
    toks = _tokenize(instruction_text)
    test_files = " ".join(_list_relative_files(task_root / "tests", max_files=60))
    test_toks = _tokenize(test_files)
    if {"update", "modify", "write", "save"} & toks:
        return "structured_output_or_file_update"
    if {"report", "summary"} & toks:
        return "report_or_summary"
    if "assert" in test_toks or "verify" in toks:
        return "structured_output_or_file_update"
    if artifacts:
        return "structured_output_or_file_update"
    return "general_output"

def _infer_constraints(task: dict[str, Any], task_root: Path, instruction_text: str) -> list[str]:
    out = set(_safe_list(task.get("constraints")))
    toks = _tokenize(instruction_text)
    test_text = _read_text_if_exists(task_root / "tests" / "README.md", max_chars=3000)
    if "deterministic_verifier" in toks or "deterministic" in toks or "assert" in _tokenize(test_text):
        out.add("deterministic_verifier")
    if "offline" in toks or "no_network" in toks:
        out.add("offline_or_local_only")
    return sorted(out)

def _infer_goal_and_outputs(instruction_text: str, task: dict[str, Any], artifacts: list[str], operations: list[str]) -> tuple[str, str, str]:
    domain = str(task.get("domain", "")).strip()
    task_id = str(task.get("task_id", "")).strip()
    tags = ", ".join(_safe_list(task.get("tags")))
    goal = f"Complete task '{task_id}' in domain '{domain}' by performing {', '.join(operations[:4]) or 'task-relevant operations'} over artifacts {', '.join(artifacts) or 'task inputs'}."
    if tags:
        goal += f" Context tags: {tags}."
    input_state = f"Task provides environment files and instructions under dataset/{task_id}. Primary artifacts appear to be: {', '.join(artifacts) or 'unspecified'}."
    expected_output = "Produce a deterministic, verifier-compatible file update or structured result." if artifacts else "Produce a verifier-compatible result."
    return goal, input_state, expected_output

def _infer_verifier_targets(task_root: Path, artifacts: list[str], operations: list[str]) -> list[str]:
    targets = []
    test_files = _list_relative_files(task_root / "tests", max_files=100)
    joined = " ".join(test_files) + " " + _read_text_if_exists(task_root / "tests" / "README.md", max_chars=3000)
    toks = _tokenize(joined)
    if "xlsx" in artifacts:
        targets.append("workbook_structure_or_cell_values")
    if "pdf" in artifacts:
        targets.append("document_or_table_extraction_output")
    if {"validate", "verify"} & set(operations):
        targets.append("deterministic_validation_checks")
    if {"aggregate", "calculate"} & set(operations):
        targets.append("computed_metric_correctness")
    if {"debug", "patch"} & set(operations):
        targets.append("tests_or_build_pass")
    if not targets:
        targets.append("assertion_based_output_check" if "assert" in toks else "verifier_defined_output")
    return targets

def _infer_critical_substeps(artifacts: list[str], tools: list[str], operations: list[str]) -> list[str]:
    steps = []
    if "pdf" in artifacts and "extract" in operations:
        steps.append("extract_tabular_or_structured_content_from_pdf")
    if "xlsx" in artifacts:
        steps.append("load_and_inspect_workbook_structure")
    if "transform" in operations:
        steps.append("clean_or_normalize_intermediate_data")
    if "aggregate" in operations:
        steps.append("aggregate_values_over_target_dimensions")
    if "calculate" in operations:
        steps.append("compute_required_metrics_or_weighted_values")
    if "validate" in operations or "verify" in operations:
        steps.append("validate_outputs_against_expected_constraints")
    if "debug" in operations or "patch" in operations:
        steps.append("identify_failure_cause_and_apply_targeted_fix")
    out = []
    for s in steps:
        if s not in out:
            out.append(s)
    return out

def _infer_failure_modes(artifacts: list[str], operations: list[str], tools: list[str]) -> list[str]:
    failures = []
    if "xlsx" in artifacts:
        failures += ["wrong_cell_range_or_sheet_selection", "type_or_formula_mismatch"]
    if "pdf" in artifacts:
        failures += ["table_detection_failure", "ocr_or_format_loss"]
    if "aggregate" in operations or "calculate" in operations:
        failures += ["incorrect_grouping_or_weighting", "numeric_aggregation_error"]
    if "validate" in operations or "verify" in operations:
        failures += ["output_format_mismatch", "verifier_assertion_failure"]
    if "debug" in operations or "patch" in operations:
        failures += ["incomplete_fix", "dependency_or_test_breakage"]
    out = []
    for s in failures:
        if s not in out:
            out.append(s)
    return out[:6]

def _infer_granularity(original_curated_skills: list[str], operations: list[str]) -> str:
    if len(original_curated_skills) <= 1 and len(operations) <= 3:
        return "atomic"
    if len(original_curated_skills) >= 2 or len(operations) >= 4:
        return "compositional"
    return "compositional"

def _infer_comparable_shape(task_id: str, original_curated_skills: list[str], granularity: str, critical_substeps: list[str]) -> str:
    curated = ", ".join(original_curated_skills) if original_curated_skills else "curated task skills"
    steps = ", ".join(critical_substeps[:3]) if critical_substeps else "task-critical substeps"
    return f"Comparable skills for '{task_id}' should be {granularity}, method-like units aligned with the original curated skills ({curated}) and focused on {steps}, rather than broad project workflows."

def _infer_query_terms(task: dict[str, Any], family: str, artifacts: list[str], tools: list[str], operations: list[str], original_curated_skills: list[str]) -> tuple[list[str], list[str]]:
    focus = set()
    focus |= set(_safe_list(task.get("tags")))
    focus |= set(original_curated_skills)
    focus |= set(artifacts)
    focus |= set(tools)
    focus |= set(operations)
    focus |= set(FAMILY_CUES.get(family, set()))
    focus_terms = sorted({_slugify(x).replace("-", " ") for x in focus if len(str(x)) >= 3})[:18]
    return focus_terms, sorted(NEGATIVE_QUERY_TERMS)

def _collect_evidence_pack(task: dict[str, Any], task_root: Path) -> dict[str, Any]:
    return {
        "instruction_text": _read_text_if_exists(task_root / "instruction.md", max_chars=8000),
        "task_toml": _load_task_toml(task_root / "task.toml"),
        "env_files": _list_relative_files(task_root / "environment", max_files=120),
        "test_files": _list_relative_files(task_root / "tests", max_files=120),
        "solution_files": _list_relative_files(task_root / "solution", max_files=60),
    }

def _heuristic_schema(task: dict[str, Any], task_root: Path) -> dict[str, Any]:
    ev = _collect_evidence_pack(task, task_root)
    instruction_text = ev["instruction_text"]
    artifacts, artifact_reasons = _infer_artifacts(task, task_root)
    tools, tool_reasons = _infer_tools(task, task_root, artifacts)
    operations, op_reasons = _infer_operations(task, task_root)
    family, family_candidates, family_reasons = _infer_family(task, task_root, artifacts, tools, operations)
    output_type = _infer_output_type(task_root, instruction_text, artifacts)
    constraints = _infer_constraints(task, task_root, instruction_text)
    task_goal, input_state, expected_output = _infer_goal_and_outputs(instruction_text, task, artifacts, operations)
    verifier_targets = _infer_verifier_targets(task_root, artifacts, operations)
    critical_substeps = _infer_critical_substeps(artifacts, tools, operations)
    failure_modes = _infer_failure_modes(artifacts, operations, tools)
    original_curated_skills = _safe_list(task.get("required_skills"))
    preferred_granularity = _infer_granularity(original_curated_skills, operations)
    comparable_skill_shape = _infer_comparable_shape(str(task.get("task_id", "")), original_curated_skills, preferred_granularity, critical_substeps)
    query_focus_terms, negative_terms = _infer_query_terms(task, family, artifacts, tools, operations, original_curated_skills)
    return {
        "task_id": str(task.get("task_id", "")).strip(),
        "family": family,
        "domain": str(task.get("domain", "")).strip(),
        "artifacts": artifacts,
        "operations": operations,
        "tools": tools,
        "output_type": output_type,
        "constraints": constraints,
        "tags": _safe_list(task.get("tags")),
        "family_candidates": family_candidates,
        "original_curated_skills": original_curated_skills,
        "task_goal": task_goal,
        "input_state": input_state,
        "expected_output": expected_output,
        "verifier_targets": verifier_targets,
        "critical_substeps": critical_substeps,
        "hard_constraints": constraints,
        "failure_modes": failure_modes,
        "comparable_skill_shape": comparable_skill_shape,
        "preferred_granularity": preferred_granularity,
        "query_focus_terms": query_focus_terms,
        "negative_terms": negative_terms,
        "must_not_be": ["broad_project_workflow", "generic_platform_skill", "task_answer_or_solution_dump"],
        "extraction_debug": {
            "artifact_reasons": artifact_reasons,
            "tool_reasons": tool_reasons,
            "operation_reasons": op_reasons,
            "family_reasons": family_reasons,
            "evidence_preview": {
                "env_files": ev["env_files"][:20],
                "test_files": ev["test_files"][:20],
                "solution_files": ev["solution_files"][:20],
            },
        },
    }

def _ambiguity_score(schema: dict[str, Any]) -> float:
    score = 0.0
    if len(schema.get("family_candidates", [])) > 1:
        score += 0.4
    if len(schema.get("artifacts", [])) == 0:
        score += 0.2
    if len(schema.get("operations", [])) <= 1:
        score += 0.15
    if len(schema.get("tools", [])) <= 1:
        score += 0.15
    if schema.get("family") == "general_problem_solving":
        score += 0.2
    if len(schema.get("critical_substeps", [])) <= 1:
        score += 0.1
    return round(min(1.0, score), 3)

def _chat_completion(client: Any, model: str, system_prompt: str, user_prompt: str, temperature: float, max_tokens: int) -> str:
    kwargs = {
        "model": model,
        "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    try:
        resp = client.chat.completions.create(**kwargs, response_format={"type": "json_object"})
        return resp.choices[0].message.content
    except Exception:
        resp = client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content

def _api_refine_schema(client: Any, model: str, task: dict[str, Any], heuristic: dict[str, Any], evidence_pack: dict[str, Any], temperature: float = 0.0, max_tokens: int = 1800) -> dict[str, Any]:
    system = """You are refining a benchmark task schema.

Important:
- Do NOT freely invent open-ended labels.
- You must choose family/artifacts/tools/operations from the provided controlled vocabularies.
- Improve task fit and granularity, not broad workflows.
- Output strict JSON only.
"""
    payload = {
        "task_metadata": task,
        "heuristic_schema": heuristic,
        "controlled_vocabularies": {
            "families": CONTROLLED_FAMILIES,
            "artifacts": CONTROLLED_ARTIFACTS,
            "tools": CONTROLLED_TOOLS,
            "operations": CONTROLLED_OPERATIONS,
            "granularities": GRANULARITIES,
        },
        "instruction_excerpt": evidence_pack.get("instruction_text", "")[:5000],
        "env_files": evidence_pack.get("env_files", [])[:60],
        "test_files": evidence_pack.get("test_files", [])[:60],
        "solution_files": evidence_pack.get("solution_files", [])[:30],
        "task_toml": evidence_pack.get("task_toml", {}),
        "required_output_schema": {
            "family": "one controlled family label",
            "artifacts": ["controlled artifact labels"],
            "tools": ["controlled tool labels"],
            "operations": ["controlled operation labels"],
            "task_goal": "short string",
            "expected_output": "short string",
            "verifier_targets": ["short strings"],
            "critical_substeps": ["short strings"],
            "failure_modes": ["short strings"],
            "preferred_granularity": "one controlled value",
            "comparable_skill_shape": "short string",
            "query_focus_terms": ["strings"],
            "negative_terms": ["strings"],
            "must_not_be": ["strings"],
            "confidence": "0-1 float",
            "notes": "short explanation",
        },
    }
    text = _chat_completion(client, model, system, json.dumps(payload, ensure_ascii=False, indent=2), temperature, max_tokens)
    return _extract_json(text)

def _merge_refined_schema(heuristic: dict[str, Any], refined: dict[str, Any]) -> dict[str, Any]:
    out = dict(heuristic)
    family = str(refined.get("family", "")).strip()
    if family in CONTROLLED_FAMILIES:
        out["family"] = family
        out["family_candidates"] = list(dict.fromkeys([family] + _safe_list(heuristic.get("family_candidates"))))[:3]
    for key, controlled in [("artifacts", CONTROLLED_ARTIFACTS), ("tools", CONTROLLED_TOOLS), ("operations", CONTROLLED_OPERATIONS)]:
        vals = [x for x in _safe_list(refined.get(key)) if x in controlled]
        if vals:
            out[key] = vals
    gran = str(refined.get("preferred_granularity", "")).strip()
    if gran in GRANULARITIES:
        out["preferred_granularity"] = gran
    for key in ["task_goal", "expected_output", "comparable_skill_shape"]:
        val = _compact(str(refined.get(key, "")))
        if val:
            out[key] = val
    for key in ["verifier_targets", "critical_substeps", "failure_modes", "query_focus_terms", "negative_terms", "must_not_be"]:
        vals = _safe_list(refined.get(key))
        if vals:
            out[key] = vals
    out.setdefault("extraction_debug", {})
    out["extraction_debug"]["api_refinement"] = {
        "used": True,
        "confidence": refined.get("confidence"),
        "notes": refined.get("notes", ""),
    }
    return out

def build_task_schemas(dataset_index: Path, dataset_root: Path, output_dir: Path, manifest_out: Path, ontology_out: Path, task_ids: list[str] | None = None, use_api_on_ambiguity: bool = False, ambiguity_threshold: float = 0.45, api_base: str | None = None, api_key: str | None = None, api_model: str | None = None) -> dict[str, Any]:
    data = _read_json(dataset_index)
    tasks = [t for t in data.get("tasks", []) if isinstance(t, dict)]
    if task_ids:
        wanted = set(task_ids)
        tasks = [t for t in tasks if str(t.get("task_id", "")).strip() in wanted]
    ontology = build_ontology(tasks, dataset_root)
    _write_json(ontology_out, ontology)

    client = None
    if use_api_on_ambiguity:
        if openai is None:
            raise SystemExit("openai package is required for --use-api-on-ambiguity")
        if not api_key:
            raise SystemExit("Missing API key for --use-api-on-ambiguity")
        client = openai.OpenAI(api_key=api_key, base_url=api_base)

    manifest = {
        "generated_at": _now_iso(),
        "dataset_index": str(dataset_index),
        "dataset_root": str(dataset_root),
        "ontology_file": str(ontology_out),
        "summary": {"n_tasks": 0, "n_api_refined": 0},
        "tasks": [],
    }

    api_refined_count = 0
    for task in tasks:
        task_id = str(task.get("task_id", "")).strip()
        if not task_id:
            continue
        task_root = dataset_root / task_id
        schema = _heuristic_schema(task, task_root)
        ambiguity = _ambiguity_score(schema)
        schema["ambiguity_score"] = ambiguity
        if use_api_on_ambiguity and client is not None and ambiguity >= ambiguity_threshold:
            try:
                refined = _api_refine_schema(client, api_model or "gpt-4.1-mini", task, schema, _collect_evidence_pack(task, task_root))
                if isinstance(refined, dict):
                    schema = _merge_refined_schema(schema, refined)
                    api_refined_count += 1
            except Exception as e:
                schema.setdefault("extraction_debug", {})
                schema["extraction_debug"]["api_refinement_error"] = str(e)
        schema["generated_at"] = _now_iso()
        out_path = output_dir / f"{task_id}.json"
        _write_json(out_path, schema)
        manifest["tasks"].append({
            "task_id": task_id,
            "output_file": str(out_path),
            "family": schema.get("family"),
            "ambiguity_score": schema.get("ambiguity_score"),
            "api_refined": bool(((schema.get("extraction_debug") or {}).get("api_refinement") or {}).get("used", False)),
        })
        print(f"[OK] {task_id}: family={schema.get('family')} ambiguity={schema.get('ambiguity_score')}")
    manifest["summary"]["n_tasks"] = len(manifest["tasks"])
    manifest["summary"]["n_api_refined"] = api_refined_count
    _write_json(manifest_out, manifest)
    return manifest

def main() -> None:
    parser = argparse.ArgumentParser(description="Build richer task schemas.")
    parser.add_argument("--dataset-index", type=Path, required=True)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "data" / "task_schema_v2")
    parser.add_argument("--manifest-out", type=Path, default=PROJECT_ROOT / "data" / "task_schema_manifest.json")
    parser.add_argument("--ontology-out", type=Path, default=PROJECT_ROOT / "data" / "schema_ontology_v2.json")
    parser.add_argument("--task-ids", type=str, default=None)
    parser.add_argument("--use-api-on-ambiguity", action="store_true")
    parser.add_argument("--ambiguity-threshold", type=float, default=0.45)
    parser.add_argument("--api-base", type=str, default=os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1"))
    parser.add_argument("--api-key", type=str, default=os.getenv("OPENAI_API_KEY"))
    parser.add_argument("--api-model", type=str, default=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"))
    args = parser.parse_args()

    task_ids = [x.strip() for x in args.task_ids.split(",") if x.strip()] if args.task_ids else None
    result = build_task_schemas(
        dataset_index=args.dataset_index,
        dataset_root=args.dataset_root,
        output_dir=args.output_dir,
        manifest_out=args.manifest_out,
        ontology_out=args.ontology_out,
        task_ids=task_ids,
        use_api_on_ambiguity=args.use_api_on_ambiguity,
        ambiguity_threshold=args.ambiguity_threshold,
        api_base=args.api_base,
        api_key=args.api_key,
        api_model=args.api_model,
    )
    print(json.dumps(result["summary"], indent=2, ensure_ascii=False))
    print(f"Manifest: {args.manifest_out}")
    print(f"Schemas dir: {args.output_dir}")
    print(f"Ontology: {args.ontology_out}")

if __name__ == "__main__":
    main()
