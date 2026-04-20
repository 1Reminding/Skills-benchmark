#!/usr/bin/env python3
"""Build a structured skill registry by scanning SkillsBench-style task folders.

This script is designed to reduce manual work before retrieval.
It scans dataset/<task>/environment/skills/, reads each SKILL.md, extracts
heuristic metadata, deduplicates repeated skills across tasks, and writes:

1) data/skill_registry.raw.json    # one record per scanned skill occurrence
2) data/skill_registry.json        # deduplicated registry for retrieval
3) data/skill_registry.review.json # low-confidence / needs-review hints

Expected dataset structure:
project_root/
├── dataset/
│   ├── dataset_index.json
│   └── <task_id>/
│       └── environment/
│           └── skills/
│               └── <skill_name>/
│                   ├── SKILL.md
│                   ├── scripts/
│                   └── references/
└── scripts/
    └── 06_build_skill_registry_from_dataset.py

No external dependencies are required.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATASET_INDEX = PROJECT_ROOT / "dataset" / "dataset_index.json"
DEFAULT_DATASET_ROOT = PROJECT_ROOT / "dataset"
DEFAULT_OUTPUT_RAW = PROJECT_ROOT / "data" / "skill_registry.raw.json"
DEFAULT_OUTPUT_REGISTRY = PROJECT_ROOT / "data" / "skill_registry.json"
DEFAULT_OUTPUT_REVIEW = PROJECT_ROOT / "data" / "skill_registry.review.json"

# -----------------------------
# Heuristics / vocab
# -----------------------------

TOKEN_RE = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_\-/.+]*")
FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
HEADING_RE = re.compile(r"^#{1,6}\s+(.+)$", re.MULTILINE)
CODE_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
WS_RE = re.compile(r"\s+")

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
    ".sql": "sql",
    ".xml": "xml",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".sh": "shell",
}

KEYWORDS_TO_ARTIFACTS = {
    "pdf": {"pdf"},
    "spreadsheet": {"xlsx"},
    "excel": {"xlsx"},
    "workbook": {"xlsx"},
    "csv": {"csv"},
    "json": {"json"},
    "latex": {"latex"},
    "notebook": {"notebook"},
    "html": {"html"},
    "xml": {"xml"},
    "sql": {"sql"},
}

KEYWORDS_TO_TOOLS = {
    "python": {"python"},
    "pandas": {"python"},
    "pytest": {"testing"},
    "test": {"testing"},
    "testing": {"testing"},
    "ci": {"ci"},
    "shell": {"shell"},
    "bash": {"shell"},
    "terminal": {"shell"},
    "spreadsheet": {"spreadsheet"},
    "excel": {"spreadsheet"},
    "pdf": {"pdf"},
    "browser": {"browser"},
    "selenium": {"browser"},
    "playwright": {"browser"},
    "geospatial": {"geospatial"},
    "gis": {"geospatial"},
    "sql": {"database"},
    "database": {"database"},
    "latex": {"latex"},
}

KEYWORDS_TO_OPERATIONS = {
    "extract": {"extract"},
    "parse": {"extract"},
    "read": {"extract"},
    "transform": {"transform"},
    "convert": {"transform"},
    "normalize": {"transform", "clean"},
    "clean": {"clean"},
    "aggregate": {"aggregate"},
    "summarize": {"summarize"},
    "calculate": {"calculate"},
    "compute": {"calculate"},
    "verify": {"verify", "validate"},
    "validate": {"validate"},
    "check": {"validate"},
    "debug": {"debug"},
    "fix": {"debug", "patch"},
    "patch": {"patch"},
    "search": {"search"},
    "plan": {"plan"},
    "reason": {"summarize"},
    "analyze": {"analyze"},
    "analysis": {"analyze"},
    "compare": {"compare"},
    "diff": {"compare"},
    "optimize": {"optimize"},
}

KEYWORDS_TO_FAMILY = {
    "spreadsheet": "spreadsheet_analytics",
    "excel": "spreadsheet_analytics",
    "xlsx": "spreadsheet_analytics",
    "pdf": "document_extraction",
    "latex": "document_extraction",
    "document": "document_extraction",
    "debug": "debugging_ci_repair",
    "ci": "debugging_ci_repair",
    "build": "debugging_ci_repair",
    "dependency": "debugging_ci_repair",
    "geospatial": "geospatial_analysis",
    "gis": "geospatial_analysis",
    "spatial": "geospatial_analysis",
    "science": "scientific_analysis",
    "statistics": "data_analytics",
    "data": "data_analytics",
    "analysis": "data_analytics",
}

LOW_DOMAIN_SPECIFICITY_HINTS = {
    "generic", "general", "verification", "validate", "check", "debug",
    "spreadsheet", "pdf", "python", "workflow", "decomposition", "result",
}
HIGH_DOMAIN_SPECIFICITY_HINTS = {
    "powerlifting", "geospatial", "plate", "earthquake", "biology", "medical",
    "finance", "manufacturing", "cybersecurity", "protein", "wyckoff",
}

# -----------------------------
# Utilities
# -----------------------------


def _read_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _normalize_token(token: str) -> str:
    token = token.lower().strip()
    token = token.replace("/", "_")
    if token.endswith("s") and len(token) > 4:
        token = token[:-1]
    return token


def _tokenize(text: str) -> set[str]:
    return {_normalize_token(t) for t in TOKEN_RE.findall(text or "") if len(t) >= 2}


def _clean_text(text: str) -> str:
    text = FRONTMATTER_RE.sub("", text)
    text = HTML_COMMENT_RE.sub("", text)
    text = CODE_FENCE_RE.sub(" ", text)
    text = text.replace("\r\n", "\n")
    return text


def _slugify(text: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    return text or "unknown-skill"


def _first_nonempty_paragraph(text: str) -> str:
    cleaned = _clean_text(text)
    parts = [p.strip() for p in cleaned.split("\n\n")]
    for p in parts:
        if not p:
            continue
        if p.startswith("#"):
            continue
        if len(p) < 20:
            continue
        return WS_RE.sub(" ", p).strip()
    return ""


def _heading_titles(text: str) -> list[str]:
    return [m.group(1).strip() for m in HEADING_RE.finditer(text)]


def _sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _safe_list(x: Any) -> list[str]:
    if x is None:
        return []
    if isinstance(x, list):
        vals = [str(v).strip() for v in x if str(v).strip()]
    else:
        vals = [str(x).strip()] if str(x).strip() else []
    return sorted(set(vals))


def _task_map_from_index(index_data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    tasks = index_data.get("tasks", [])
    return {str(t["task_id"]): t for t in tasks if isinstance(t, dict) and "task_id" in t}


def _discover_task_ids(dataset_root: Path) -> list[str]:
    task_ids = []
    for p in sorted(dataset_root.iterdir()):
        if not p.is_dir():
            continue
        if p.name.startswith("."):
            continue
        if (p / "environment").exists():
            task_ids.append(p.name)
    return task_ids


# -----------------------------
# Data models
# -----------------------------

@dataclass
class RawSkillRecord:
    skill_occurrence_id: str
    skill_id: str
    source_task: str
    source_path: str
    skill_md_path: str
    title: str
    summary: str
    text_sha1: str
    full_text: str
    family: list[str]
    artifacts: list[str]
    operations: list[str]
    tools: list[str]
    granularity: str
    domain_specificity: str
    confidence: float
    scripts_present: bool
    references_present: bool
    headings: list[str] = field(default_factory=list)


@dataclass
class RegistrySkill:
    skill_id: str
    source_type: str
    source_tasks: list[str]
    source_paths: list[str]
    aliases: list[str]
    family: list[str]
    artifacts: list[str]
    operations: list[str]
    tools: list[str]
    granularity: str
    domain_specificity: str
    summary: str
    confidence: float
    text_sha1s: list[str]
    occurrences: int
    notes: list[str] = field(default_factory=list)


# -----------------------------
# Parsing and inference
# -----------------------------


def _extract_frontmatter_title(text: str) -> str | None:
    m = FRONTMATTER_RE.match(text)
    if not m:
        return None
    block = m.group(1)
    for line in block.splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        if k.strip().lower() in {"title", "name"}:
            title = v.strip().strip('"').strip("'")
            return title or None
    return None


def _extract_title(skill_dir: Path, text: str) -> str:
    title = _extract_frontmatter_title(text)
    if title:
        return title
    headings = _heading_titles(text)
    if headings:
        return headings[0]
    return skill_dir.name.replace("-", " ").replace("_", " ").strip().title()

def _scan_dir_artifacts(skill_dir: Path) -> set[str]:
    found = set()
    allowed = {"pdf", "xlsx", "csv", "json", "html", "latex", "sql", "xml", "yaml"}
    for p in skill_dir.rglob("*"):
        if not p.is_file():
            continue
        artifact = ARTIFACT_EXTENSIONS.get(p.suffix.lower())
        if artifact and artifact in allowed:
            found.add(artifact)
    return found

def _infer_artifacts_from_text(text: str) -> set[str]:
    toks = _tokenize(text)
    found: set[str] = set()
    for k, vals in KEYWORDS_TO_ARTIFACTS.items():
        if _normalize_token(k) in toks:
            found |= vals
    return found


def _infer_tools_from_text(text: str) -> set[str]:
    toks = _tokenize(text)
    found: set[str] = set()
    for k, vals in KEYWORDS_TO_TOOLS.items():
        if _normalize_token(k) in toks:
            found |= vals
    return found

def _infer_operations_from_text(text: str, title: str = "", headings: list[str] | None = None, summary: str = "") -> set[str]:
    headings = headings or []
    focus_text = "\n".join([title, summary] + headings[:12])
    toks = _tokenize(focus_text)

    found: set[str] = set()
    for k, vals in KEYWORDS_TO_OPERATIONS.items():
        if _normalize_token(k) in toks:
            found |= vals

    lowered = focus_text.lower()
    if "step" in lowered or "steps" in lowered:
        found.add("plan")

    if not found:
        found.add("verify")

    return found

def _infer_family(task_meta: dict[str, Any], text: str, artifacts: set[str], operations: set[str]) -> list[str]:
    votes: Counter[str] = Counter()

    domain = str(task_meta.get("domain", "") or "").lower()
    tags = [_normalize_token(t) for t in task_meta.get("tags", []) or []]
    tokens = _tokenize(text)

    for t in tags:
        fam = KEYWORDS_TO_FAMILY.get(t)
        if fam:
            votes[fam] += 3

    for token in tokens:
        fam = KEYWORDS_TO_FAMILY.get(token)
        if fam:
            votes[fam] += 1

    if "software" in domain or "engineering" in domain:
        votes["debugging_ci_repair"] += 2
    if "finance" in domain:
        votes["data_analytics"] += 1
    if "science" in domain:
        votes["scientific_analysis"] += 1
    if "office" in domain and ("xlsx" in artifacts or "csv" in artifacts):
        votes["spreadsheet_analytics"] += 2

    if "xlsx" in artifacts or "csv" in artifacts:
        votes["spreadsheet_analytics"] += 2
    if "pdf" in artifacts or "latex" in artifacts:
        votes["document_extraction"] += 2
    if {"debug", "patch"} & operations:
        votes["debugging_ci_repair"] += 2
    if {"analyze", "calculate"} & operations and "geospatial" in tokens:
        votes["geospatial_analysis"] += 2

    if not votes:
        return ["general_problem_solving"]
    best = [fam for fam, score in votes.items() if score == max(votes.values())]
    return sorted(best)


def _infer_granularity(text: str, operations: set[str], headings: list[str], title: str) -> str:
    lowered = text.lower()
    title_toks = _tokenize(title)
    op_count = len(operations)
    step_count = lowered.count("step ") + lowered.count("steps")
    workflow_hints = {"workflow", "pipeline", "end-to-end", "checklist"}

    if workflow_hints & title_toks:
        return "compositional"
    if any(k in lowered for k in ["first", "then", "finally"]) and op_count >= 3:
        return "compositional"
    if step_count >= 2 and op_count >= 3:
        return "compositional"
    if any(h.lower() in {"when to use", "common pitfalls", "validation"} for h in headings):
        return "generic"
    if op_count <= 2:
        return "atomic"
    return "generic"


def _infer_domain_specificity(text: str, task_meta: dict[str, Any], family: list[str]) -> str:
    tokens = _tokenize(text)
    domain = str(task_meta.get("domain", "") or "").lower()
    tags = {_normalize_token(t) for t in task_meta.get("tags", []) or []}

    score = 0
    for tok in tokens:
        if tok in HIGH_DOMAIN_SPECIFICITY_HINTS:
            score += 2
        if tok in LOW_DOMAIN_SPECIFICITY_HINTS:
            score -= 1
        if tok in tags:
            score += 1
    if any(f in {"geospatial_analysis", "scientific_analysis"} for f in family):
        score += 1
    if any(w in domain for w in ["medical", "manufacturing", "cyber", "geophysics"]):
        score += 1

    if score >= 3:
        return "high"
    if score >= 1:
        return "medium"
    return "low"


def _estimate_confidence(summary: str, family: list[str], artifacts: set[str], operations: set[str], tools: set[str]) -> float:
    confidence = 0.25
    if summary and len(summary) >= 40:
        confidence += 0.20
    if family:
        confidence += 0.15
    if artifacts:
        confidence += 0.10
    if operations:
        confidence += 0.15
    if tools:
        confidence += 0.10
    if len(summary) > 120:
        confidence += 0.05
    return round(min(confidence, 0.95), 3)


def _canonical_skill_id(skill_dir_name: str, title: str) -> str:
    base = skill_dir_name.strip().lower()
    if base and base not in {"skill", "skills"}:
        return _slugify(base)
    return _slugify(title)


def _scan_one_skill(task_id: str, task_meta: dict[str, Any], skill_dir: Path) -> RawSkillRecord | None:
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        return None

    text = skill_md.read_text(encoding="utf-8", errors="replace")
    cleaned = _clean_text(text)
    title = _extract_title(skill_dir, text)
    headings = _heading_titles(text)
    summary = _first_nonempty_paragraph(text)
    if not summary:
        summary = f"Procedural skill for {skill_dir.name.replace('-', ' ')}."

    dir_artifacts = _scan_dir_artifacts(skill_dir)
    text_artifacts = _infer_artifacts_from_text(cleaned)
    artifacts = dir_artifacts | text_artifacts

    tools = _infer_tools_from_text(cleaned)
    if "scripts" in [p.name for p in skill_dir.iterdir() if p.exists()]:
        tools.add("shell")

    operations = _infer_operations_from_text(
        cleaned,
        title=title,
        headings=headings,
        summary=summary,
    )
    family = _infer_family(task_meta, cleaned, artifacts, operations)
    granularity = _infer_granularity(cleaned, operations, headings, title)
    domain_specificity = _infer_domain_specificity(cleaned, task_meta, family)
    confidence = _estimate_confidence(summary, family, artifacts, operations, tools)

    skill_id = _canonical_skill_id(skill_dir.name, title)
    rel_skill_dir = str(skill_dir)
    occurrence_id = f"{task_id}::{skill_id}"

    print(f"[OK] found skill: {task_id} / {skill_id}")

    return RawSkillRecord(
        skill_occurrence_id=occurrence_id,
        skill_id=skill_id,
        source_task=task_id,
        source_path=rel_skill_dir,
        skill_md_path=str(skill_md),
        title=title,
        summary=summary,
        text_sha1=_sha1(cleaned),
        full_text=cleaned,
        family=sorted(family),
        artifacts=sorted(artifacts),
        operations=sorted(operations),
        tools=sorted(tools),
        granularity=granularity,
        domain_specificity=domain_specificity,
        confidence=confidence,
        scripts_present=(skill_dir / "scripts").exists(),
        references_present=(skill_dir / "references").exists(),
        headings=headings,
    )


# -----------------------------
# Registry aggregation
# -----------------------------


def _merge_mode(values: list[str], default: str = "unknown") -> str:
    vals = [v for v in values if v]
    if not vals:
        return default
    return Counter(vals).most_common(1)[0][0]


def _merge_lists(records: list[RawSkillRecord], field_name: str) -> list[str]:
    acc: set[str] = set()
    for r in records:
        for v in getattr(r, field_name):
            if v:
                acc.add(v)
    return sorted(acc)


def _merge_summary(records: list[RawSkillRecord]) -> str:
    # Prefer the longest reasonably concise summary with highest confidence.
    ranked = sorted(records, key=lambda r: (r.confidence, len(r.summary)), reverse=True)
    return ranked[0].summary if ranked else ""


def _should_merge_records(a: RawSkillRecord, b: RawSkillRecord) -> bool:
    # Strong merge signals:
    # 1) same canonical skill_id
    # 2) same text hash
    # 3) same title slug and high family overlap
    if a.skill_id == b.skill_id:
        return True
    if a.text_sha1 == b.text_sha1:
        return True
    if _slugify(a.title) == _slugify(b.title):
        if set(a.family) & set(b.family):
            return True
    return False


def _group_records(records: list[RawSkillRecord]) -> list[list[RawSkillRecord]]:
    groups: list[list[RawSkillRecord]] = []
    for rec in records:
        placed = False
        for group in groups:
            if any(_should_merge_records(rec, g) for g in group):
                group.append(rec)
                placed = True
                break
        if not placed:
            groups.append([rec])
    return groups


def _aggregate_group(group: list[RawSkillRecord]) -> RegistrySkill:
    skill_ids = Counter([r.skill_id for r in group])
    titles = Counter([r.title for r in group])
    notes: list[str] = []

    canonical_skill_id = skill_ids.most_common(1)[0][0]
    if len(skill_ids) > 1:
        notes.append("multiple_skill_ids_merged")

    confidence = round(sum(r.confidence for r in group) / max(1, len(group)), 3)
    granularity = _merge_mode([r.granularity for r in group], default="generic")
    domain_specificity = _merge_mode([r.domain_specificity for r in group], default="medium")

    return RegistrySkill(
        skill_id=canonical_skill_id,
        source_type="scanned_from_dataset",
        source_tasks=sorted({r.source_task for r in group}),
        source_paths=sorted({r.source_path for r in group}),
        aliases=sorted({r.skill_id for r in group} | {t for t, _ in titles.items()}),
        family=_merge_lists(group, "family"),
        artifacts=_merge_lists(group, "artifacts"),
        operations=_merge_lists(group, "operations"),
        tools=_merge_lists(group, "tools"),
        granularity=granularity,
        domain_specificity=domain_specificity,
        summary=_merge_summary(group),
        confidence=confidence,
        text_sha1s=sorted({r.text_sha1 for r in group}),
        occurrences=len(group),
        notes=notes,
    )


# -----------------------------
# Review hints
# -----------------------------

def _make_review_hints(raw_records: list[RawSkillRecord], registry: list[RegistrySkill]) -> dict[str, Any]:
    low_conf = [asdict(r) for r in raw_records if r.confidence < 0.80]

    weak_summary = [
        asdict(r) for r in raw_records
        if len(r.summary.strip()) < 80
    ]

    sparse_metadata = [
        asdict(r) for r in raw_records
        if (not r.family)
        or (not r.operations)
        or (not r.tools)
        or (not r.artifacts)
        or len(r.operations) <= 1
    ]

    suspicious_artifacts = [
        asdict(r) for r in raw_records
        if any(a in {"json", "markdown", "text"} for a in r.artifacts)
    ]

    registry_notes = []
    for r in registry:
        notes = list(r.notes)

        if len(r.text_sha1s) > 1:
            notes.append("multiple_text_versions_merged")

        if any(a in {"json", "markdown", "text"} for a in r.artifacts):
            notes.append("suspicious_artifacts")

        if not r.artifacts:
            notes.append("no_artifacts")

        if len(r.operations) <= 1:
            notes.append("too_few_operations")

        if notes:
            item = asdict(r)
            item["review_notes"] = sorted(set(notes))
            registry_notes.append(item)

    return {
        "generated_at": datetime.now().isoformat(),
        "needs_review": {
            "low_confidence_records": low_conf,
            "short_summary_records": weak_summary,
            "sparse_metadata_records": sparse_metadata,
            "suspicious_artifact_records": suspicious_artifacts,
            "registry_entries_with_notes": registry_notes,
        },
        "summary": {
            "n_low_confidence_records": len(low_conf),
            "n_short_summary_records": len(weak_summary),
            "n_sparse_metadata_records": len(sparse_metadata),
            "n_suspicious_artifact_records": len(suspicious_artifacts),
            "n_registry_entries_with_notes": len(registry_notes),
        },
    }

# -----------------------------
# Main pipeline
# -----------------------------
def _select_task_ids(task_map: dict[str, dict[str, Any]], dataset_root: Path, task_ids_arg: str | None) -> list[str]:
    valid_ids = sorted(task_map.keys())

    if task_ids_arg:
        requested = [x.strip() for x in task_ids_arg.split(",") if x.strip()]
        selected = [x for x in requested if x in task_map]
        missing = [x for x in requested if x not in task_map]

        print(f"[INFO] requested task ids: {requested}")
        print(f"[INFO] matched {len(selected)} / {len(requested)} tasks")

        if missing:
            print("[WARN] task ids not found:")
            for x in missing:
                print("   -", x)

            print("[INFO] valid task ids:")
            for x in valid_ids:
                print("   -", x)

        if not selected:
            raise ValueError("No valid tasks selected. Check --task-ids.")

        return selected

    if valid_ids:
        print(f"[INFO] No --task-ids provided. Using all {len(valid_ids)} tasks from dataset_index.json")
        return valid_ids

    discovered = _discover_task_ids(dataset_root)
    if discovered:
        print(f"[INFO] dataset_index has no tasks; discovered {len(discovered)} task dirs from dataset/")
        return discovered

    raise ValueError("No tasks found in dataset_index.json or dataset root.")

def build_registry(
    dataset_index: Path,
    dataset_root: Path,
    output_raw: Path,
    output_registry: Path,
    output_review: Path,
    task_ids_arg: str | None,
    drop_missing_skill_md: bool,
) -> dict[str, Any]:
    index_data = _read_json(dataset_index) if dataset_index.exists() else {"tasks": []}
    task_map = _task_map_from_index(index_data)
    selected_task_ids = _select_task_ids(task_map, dataset_root, task_ids_arg)

    raw_records: list[RawSkillRecord] = []
    missing_skill_md: list[dict[str, str]] = []

    
    for task_id in selected_task_ids:
        task_meta = task_map.get(task_id, {"task_id": task_id, "domain": "unknown", "tags": []})
        skills_dir = dataset_root / task_id / "environment" / "skills"

        print(f"[INFO] scanning task: {task_id}")
        print(f"[INFO] skills_dir: {skills_dir}")

        if not skills_dir.is_dir():
            print(f"[WARN] skills dir not found: {skills_dir}")
            continue

        for skill_dir in sorted(skills_dir.iterdir()):
            if not skill_dir.is_dir():
                continue

            skill_md = skill_dir / "SKILL.md"
            if not skill_md.exists():
                missing_skill_md.append({"task_id": task_id, "skill_dir": str(skill_dir)})
                print(f"[WARN] missing SKILL.md: {skill_md}")
                if drop_missing_skill_md:
                    continue

            rec = _scan_one_skill(task_id, task_meta, skill_dir)
            if rec is not None:
                raw_records.append(rec)

    raw_json = {
        "generated_at": datetime.now().isoformat(),
        "dataset_index": str(dataset_index),
        "dataset_root": str(dataset_root),
        "selected_task_ids": selected_task_ids,
        "summary": {
            "n_tasks_selected": len(selected_task_ids),
            "n_raw_skill_occurrences": len(raw_records),
            "n_missing_skill_md": len(missing_skill_md),
        },
        "records": [asdict(r) for r in raw_records],
        "missing_skill_md": missing_skill_md,
    }
    _write_json(output_raw, raw_json)

    grouped = _group_records(raw_records)
    registry_entries = sorted([_aggregate_group(g) for g in grouped], key=lambda x: x.skill_id)
    registry_json = {
        "generated_at": datetime.now().isoformat(),
        "source_type": "scanned_from_dataset",
        "summary": {
            "n_registry_entries": len(registry_entries),
            "n_raw_skill_occurrences": len(raw_records),
            "n_tasks_covered": len({r.source_task for r in raw_records}),
        },
        "skills": [asdict(r) for r in registry_entries],
    }
    _write_json(output_registry, registry_json)

    review_json = _make_review_hints(raw_records, registry_entries)
    if missing_skill_md:
        review_json["missing_skill_md"] = missing_skill_md
    _write_json(output_review, review_json)

    return {
        "raw_path": str(output_raw),
        "registry_path": str(output_registry),
        "review_path": str(output_review),
        "n_tasks_selected": len(selected_task_ids),
        "n_raw_skill_occurrences": len(raw_records),
        "n_registry_entries": len(registry_entries),
        "n_missing_skill_md": len(missing_skill_md),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a structured skill registry from dataset task folders.")
    parser.add_argument("--dataset-index", type=Path, default=DEFAULT_DATASET_INDEX)
    parser.add_argument("--dataset-root", type=Path, default=DEFAULT_DATASET_ROOT)
    parser.add_argument("--output-raw", type=Path, default=DEFAULT_OUTPUT_RAW)
    parser.add_argument("--output-registry", type=Path, default=DEFAULT_OUTPUT_REGISTRY)
    parser.add_argument("--output-review", type=Path, default=DEFAULT_OUTPUT_REVIEW)
    parser.add_argument(
        "--task-ids",
        type=str,
        default=None,
        help="Comma-separated task ids. If omitted, use dataset_index tasks or discover from dataset root.",
    )
    parser.add_argument(
        "--keep-missing-skill-md",
        action="store_true",
        help="If set, keep directories without SKILL.md in the missing report instead of silently dropping them.",
    )
    args = parser.parse_args()

    result = build_registry(
        dataset_index=args.dataset_index,
        dataset_root=args.dataset_root,
        output_raw=args.output_raw,
        output_registry=args.output_registry,
        output_review=args.output_review,
        task_ids_arg=args.task_ids,
        drop_missing_skill_md=not args.keep_missing_skill_md,
    )

    print("[OK] Skill registry build finished")
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
