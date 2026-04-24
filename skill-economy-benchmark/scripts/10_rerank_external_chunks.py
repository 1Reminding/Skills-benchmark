#!/usr/bin/env python3
"""Rerank external corpus chunks for each task."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_CHUNKS = PROJECT_ROOT / "data" / "external_corpus_chunks.jsonl"
DEFAULT_QUERY_MANIFEST = PROJECT_ROOT / "data" / "external_queries.json"
DEFAULT_QUERY_DIR = PROJECT_ROOT / "data" / "external_queries"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "external_ranked_chunks"
DEFAULT_MANIFEST = PROJECT_ROOT / "data" / "external_ranked_chunks_manifest.json"

TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_\-/.+]*")
WS_RE = re.compile(r"\s+")
PATH_BAD_HINTS = {
    "archive", "changelog", "release", "releases", "news", "feedback", "roadmap",
    "license", "contributing", "authors", "requirements", "poetry.lock",
    "package-lock", "pnpm-lock", "yarn.lock", "cargo.lock", "composer.lock",
    "gemfile.lock", "setup.cfg", "pyproject.toml", "package.json",
}
PATH_GOOD_HINTS = {
    "readme", "guide", "tutorial", "cookbook", "example", "examples",
    "howto", "how-to", "usage", "docs", "workflow",
}
PROCEDURAL_CUES = {
    "step", "steps", "workflow", "guide", "tutorial", "howto", "how-to",
    "validate", "validation", "verify", "verification",
    "extract", "extraction", "parse", "parsing",
    "transform", "conversion", "convert",
    "aggregate", "aggregation", "groupby", "pivot",
    "calculate", "calculation", "compute",
    "load", "save", "write", "read", "open", "export", "import",
    "debug", "fix", "patch", "repair", "test", "testing",
}
STRONG_OPERATIONS = {
    "extract", "transform", "aggregate", "calculate",
    "analyze", "debug", "patch", "search", "plan",
}
WEAK_OPERATIONS = {"verify", "validate"}
WEAK_ARTIFACTS = {"json", "text", "markdown", "python"}
GENERIC_FAMILY = "general_problem_solving"

def _read_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows

def _now_iso() -> str:
    return datetime.now().isoformat()

def _normalize_token(token: str) -> str:
    token = token.lower().strip().replace("/", "_")
    if token.endswith("s") and len(token) > 4:
        token = token[:-1]
    return token

def _tokenize(text: str) -> set[str]:
    return {_normalize_token(t) for t in TOKEN_RE.findall(text or "") if len(t) >= 2}

def _text_compact(text: str) -> str:
    return WS_RE.sub(" ", (text or "")).strip()

def _load_query_plans(query_manifest: Path, query_dir: Path, selected_task_ids: list[str] | None) -> dict[str, dict[str, Any]]:
    plans: dict[str, dict[str, Any]] = {}
    if query_manifest.exists():
        manifest = _read_json(query_manifest)
        for task_item in manifest.get("tasks", []):
            if not isinstance(task_item, dict):
                continue
            task_id = str(task_item.get("task_id", "")).strip()
            if not task_id:
                continue
            if selected_task_ids and task_id not in selected_task_ids:
                continue
            query_file = query_dir / f"{task_id}.json"
            if not query_file.exists() and task_item.get("query_file"):
                query_file = Path(str(task_item["query_file"]))
            if query_file.exists():
                plans[task_id] = _read_json(query_file)
    else:
        for p in sorted(query_dir.glob("*.json")):
            d = _read_json(p)
            task_id = str(d.get("task_id", "")).strip()
            if not task_id:
                continue
            if selected_task_ids and task_id not in selected_task_ids:
                continue
            plans[task_id] = d
    return plans

def _looks_like_dependency_list(text: str) -> bool:
    lines = [x.strip() for x in (text or "").splitlines() if x.strip()]
    if not lines:
        return False
    if len(lines) > 60:
        lines = lines[:60]
    dep_like = 0
    for line in lines:
        if len(line) > 120:
            continue
        if "==" in line or ">=" in line or "<=" in line:
            dep_like += 1
        elif re.fullmatch(r"[A-Za-z0-9_.\-]+", line):
            dep_like += 1
        elif re.fullmatch(r"[A-Za-z0-9_.\-]+\[[A-Za-z0-9_,\-]+\]", line):
            dep_like += 1
    return dep_like >= max(8, int(0.55 * max(1, len(lines))))

def _looks_like_include_placeholder(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return True
    if "{% include" in t.lower():
        return True
    if len(t) < 80 and ("include" in t.lower() or "generated" in t.lower()):
        return True
    return False

def _english_ratio(text: str) -> float:
    if not text:
        return 0.0
    ascii_letters = sum(1 for c in text if ("a" <= c.lower() <= "z"))
    visible = sum(1 for c in text if not c.isspace())
    if visible == 0:
        return 0.0
    return ascii_letters / visible

def _procedural_score(text: str) -> tuple[float, list[str]]:
    low = (text or "").lower()
    toks = _tokenize(low)
    cue_overlap = PROCEDURAL_CUES & toks
    score = 0.0
    reasons = []
    if cue_overlap:
        score += min(4.0, 0.5 * len(cue_overlap))
        reasons.append(f"procedural_cues:{len(cue_overlap)}")
    if re.search(r"\b(step|steps)\b", low):
        score += 0.8
        reasons.append("step_pattern")
    if re.search(r"\b(example|examples)\b", low):
        score += 0.5
        reasons.append("example_pattern")
    if re.search(r"\b(read|load|parse|extract|transform|aggregate|calculate|save|write)\b", low):
        score += 0.8
        reasons.append("workflow_verbs")
    return score, reasons

def _path_prior(path: str, title: str) -> tuple[float, list[str]]:
    low = f"{path} {title}".lower()
    score = 0.0
    reasons = []
    good = sum(1 for h in PATH_GOOD_HINTS if h in low)
    bad = sum(1 for h in PATH_BAD_HINTS if h in low)
    if good:
        score += min(2.0, 0.6 * good)
        reasons.append(f"path_good:{good}")
    if bad:
        score -= min(3.0, 0.9 * bad)
        reasons.append(f"path_bad:{bad}")
    return score, reasons

def _hard_filter_chunk(chunk: dict[str, Any]) -> tuple[bool, list[str]]:
    path = str(chunk.get("path", "")).lower()
    title = str(chunk.get("title", "")).lower()
    text = _text_compact(str(chunk.get("text", "")))

    if len(text) < 120:
        return False, ["too_short"]
    if _looks_like_include_placeholder(text):
        return False, ["include_placeholder"]
    if _looks_like_dependency_list(text):
        return False, ["dependency_list"]
    if _english_ratio(text) < 0.20:
        return False, ["likely_non_english"]

    bad_path_hits = [h for h in PATH_BAD_HINTS if h in path or h in title]
    if bad_path_hits:
        if "readme" not in path and "readme" not in title:
            return False, [f"bad_path:{','.join(sorted(set(bad_path_hits)))}"]

    if len(_tokenize(text)) < 20:
        return False, ["too_few_tokens"]

    proc_score, _ = _procedural_score(text)
    if proc_score <= 0 and len(text) < 500:
        return False, ["no_procedural_signal"]

    return True, []

def _score_chunk_for_task(chunk: dict[str, Any], task_plan: dict[str, Any]) -> tuple[float, list[str]]:
    score = 0.0
    reasons = []

    schema = task_plan.get("schema", {}) or {}
    task_family = str(schema.get("family") or GENERIC_FAMILY)
    task_artifacts = {a for a in (schema.get("artifacts") or []) if a not in WEAK_ARTIFACTS}
    task_ops = set(schema.get("operations") or [])
    task_tools = set(schema.get("tools") or [])

    strong_task_ops = task_ops & STRONG_OPERATIONS
    weak_task_ops = task_ops & WEAK_OPERATIONS

    title = str(chunk.get("title", ""))
    section = str(chunk.get("section_title", ""))
    path = str(chunk.get("path", ""))
    text = _text_compact(str(chunk.get("text", "")))

    chunk_tokens = _tokenize(" ".join([title, section, path, text]))

    family_cues = {
        "spreadsheet_analytics": {"xlsx", "excel", "spreadsheet", "workbook", "openpyxl", "pandas"},
        "document_extraction": {"pdf", "document", "table", "extraction", "ocr", "pymupdf", "pdfplumber"},
        "debugging_ci_repair": {"debug", "ci", "pytest", "workflow", "error", "fix", "patch", "github_actions"},
        "geospatial_analysis": {"geopandas", "shapely", "pyproj", "gis", "geospatial", "crs", "geometry"},
        "data_analytics": {"pandas", "dataframe", "analysis", "aggregate", "groupby", "csv"},
        "general_problem_solving": {"workflow", "guide", "tutorial"},
    }
    fam_overlap = family_cues.get(task_family, set()) & chunk_tokens
    if fam_overlap:
        score += min(4.0, 0.7 * len(fam_overlap))
        reasons.append(f"family_cues:{len(fam_overlap)}")

    artifact_term_map = {
        "xlsx": {"xlsx", "excel", "spreadsheet", "workbook"},
        "csv": {"csv", "tabular", "dataframe"},
        "pdf": {"pdf", "document", "table", "ocr"},
        "html": {"html", "webpage"},
        "latex": {"latex"},
    }
    artifact_overlap_count = 0
    for art in task_artifacts:
        if artifact_term_map.get(art, {art}) & chunk_tokens:
            artifact_overlap_count += 1
    if artifact_overlap_count:
        score += 2.2 * artifact_overlap_count
        reasons.append(f"artifact_overlap:{artifact_overlap_count}")

    tool_term_map = {
        "python": {"python", "pandas", "script"},
        "spreadsheet": {"excel", "spreadsheet", "openpyxl", "xlsxwriter", "workbook"},
        "pdf": {"pdf", "pdfplumber", "pymupdf", "ocr"},
        "testing": {"pytest", "test", "testing"},
        "ci": {"ci", "github_actions", "workflow", "runner"},
        "geospatial": {"geopandas", "shapely", "pyproj", "gis"},
        "shell": {"bash", "shell", "cli", "terminal"},
    }
    tool_overlap_count = 0
    for tool in task_tools:
        if tool_term_map.get(tool, {tool}) & chunk_tokens:
            tool_overlap_count += 1
    if tool_overlap_count:
        score += 1.5 * tool_overlap_count
        reasons.append(f"tool_overlap:{tool_overlap_count}")

    op_term_map = {
        "extract": {"extract", "extraction", "parse", "parsing", "read"},
        "transform": {"transform", "conversion", "convert", "normalize", "clean"},
        "aggregate": {"aggregate", "aggregation", "groupby", "pivot", "summarize"},
        "calculate": {"calculate", "calculation", "compute", "formula", "metric"},
        "analyze": {"analyze", "analysis", "inspect"},
        "debug": {"debug", "troubleshoot", "error", "failure", "fix"},
        "patch": {"patch", "repair", "fix"},
        "search": {"search", "retrieve"},
        "plan": {"plan", "workflow", "steps"},
        "verify": {"verify", "validation", "validate", "check"},
        "validate": {"validate", "validation", "check"},
    }

    strong_overlap_count = 0
    for op in strong_task_ops:
        if op_term_map.get(op, {op}) & chunk_tokens:
            strong_overlap_count += 1
    if strong_overlap_count:
        score += 1.8 * strong_overlap_count
        reasons.append(f"strong_ops:{strong_overlap_count}")

    weak_overlap_count = 0
    for op in weak_task_ops:
        if op_term_map.get(op, {op}) & chunk_tokens:
            weak_overlap_count += 1
    if weak_overlap_count:
        score += 0.3 * weak_overlap_count
        reasons.append(f"weak_ops:{weak_overlap_count}")

    best_query_overlap = 0
    best_query_id = None
    for q in task_plan.get("queries", []) or []:
        if not isinstance(q, dict):
            continue
        q_tokens = _tokenize(str(q.get("text", "")))
        overlap = len(q_tokens & chunk_tokens)
        if overlap > best_query_overlap:
            best_query_overlap = overlap
            best_query_id = q.get("query_id")
    if best_query_overlap:
        score += min(5.0, 0.9 * best_query_overlap)
        reasons.append(f"query_overlap:{best_query_overlap}")
        if best_query_id:
            reasons.append(f"best_query:{best_query_id}")

    proc_score, proc_reasons = _procedural_score(text)
    score += proc_score
    reasons.extend(proc_reasons)

    path_score, path_reasons = _path_prior(path, title)
    score += path_score
    reasons.extend(path_reasons)

    tok_count = len(chunk_tokens)
    if tok_count >= 80:
        score += 0.8
        reasons.append("substantive_chunk")
    elif tok_count < 30:
        score -= 1.0
        reasons.append("thin_chunk")

    meaningful = (
        best_query_overlap >= 2
        or artifact_overlap_count > 0
        or tool_overlap_count > 0
        or strong_overlap_count > 0
        or len(fam_overlap) > 0
    )
    if not meaningful:
        return 0.0, ["insufficient_task_signal"]
    if score < 4.0:
        return 0.0, ["below_threshold"]
    return round(score, 3), reasons

def rank_chunks(
    chunks_path: Path,
    query_manifest: Path,
    query_dir: Path,
    output_dir: Path,
    manifest_path: Path,
    task_ids: list[str] | None,
    top_k: int,
    top_docs_per_task: int,
) -> dict[str, Any]:
    all_chunks = _read_jsonl(chunks_path)
    query_plans = _load_query_plans(query_manifest, query_dir, task_ids)
    if not query_plans:
        raise SystemExit("No query plans found. Run 08_generate_external_queries.py first.")

    kept_chunks = []
    filter_counter = Counter()
    for ch in all_chunks:
        ok, reasons = _hard_filter_chunk(ch)
        if ok:
            kept_chunks.append(ch)
        else:
            filter_counter.update(reasons)

    print(f"[INFO] input_chunks={len(all_chunks)} kept_after_hard_filter={len(kept_chunks)}")
    if filter_counter:
        print(f"[INFO] hard_filter_top_reasons={dict(filter_counter.most_common(10))}")

    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "generated_at": _now_iso(),
        "chunks_path": str(chunks_path),
        "query_manifest": str(query_manifest),
        "query_dir": str(query_dir),
        "summary": {
            "n_input_chunks": len(all_chunks),
            "n_kept_after_hard_filter": len(kept_chunks),
            "n_tasks": len(query_plans),
        },
        "tasks": [],
    }

    for task_id, plan in query_plans.items():
        scored = []
        for ch in kept_chunks:
            score, reasons = _score_chunk_for_task(ch, plan)
            if score <= 0:
                continue
            item = dict(ch)
            item["retrieval_score"] = score
            item["retrieval_path"] = reasons
            scored.append(item)

        deduped = {}
        for x in sorted(scored, key=lambda r: r["retrieval_score"], reverse=True):
            key = (
                str(x.get("doc_id", "")),
                str(x.get("section_title", "")),
                _text_compact(str(x.get("text", "")))[:180],
            )
            if key not in deduped:
                deduped[key] = x

        ranked = list(deduped.values())
        ranked.sort(key=lambda r: r["retrieval_score"], reverse=True)

        selected = []
        doc_counter = Counter()
        for x in ranked:
            doc_key = str(x.get("doc_id", ""))
            if doc_counter[doc_key] >= top_docs_per_task:
                continue
            selected.append(x)
            doc_counter[doc_key] += 1
            if len(selected) >= top_k:
                break

        payload = {
            "task_id": task_id,
            "generated_at": _now_iso(),
            "schema": plan.get("schema", {}),
            "summary": {
                "n_ranked_candidates": len(selected),
                "n_scored_before_dedup": len(scored),
                "n_after_dedup": len(ranked),
            },
            "ranked_chunks": selected,
        }
        _write_json(output_dir / f"{task_id}.json", payload)
        manifest["tasks"].append({
            "task_id": task_id,
            "output_file": str(output_dir / f"{task_id}.json"),
            "n_ranked_candidates": len(selected),
        })
        print(f"[OK] {task_id}: selected={len(selected)} scored={len(scored)} dedup={len(ranked)}")

    _write_json(manifest_path, manifest)
    return manifest

def main() -> None:
    parser = argparse.ArgumentParser(description="Rerank external corpus chunks for each task.")
    parser.add_argument("--chunks-path", type=Path, default=DEFAULT_CHUNKS)
    parser.add_argument("--query-manifest", type=Path, default=DEFAULT_QUERY_MANIFEST)
    parser.add_argument("--query-dir", type=Path, default=DEFAULT_QUERY_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--manifest-path", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--task-ids", type=str, default=None)
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--top-docs-per-task", type=int, default=3)
    args = parser.parse_args()

    selected_task_ids = [x.strip() for x in args.task_ids.split(",") if x.strip()] if args.task_ids else None

    result = rank_chunks(
        chunks_path=args.chunks_path,
        query_manifest=args.query_manifest,
        query_dir=args.query_dir,
        output_dir=args.output_dir,
        manifest_path=args.manifest_path,
        task_ids=selected_task_ids,
        top_k=max(1, args.top_k),
        top_docs_per_task=max(1, args.top_docs_per_task),
    )
    print(json.dumps(result["summary"], indent=2, ensure_ascii=False))
    print(f"Manifest: {args.manifest_path}")
    print(f"Ranked chunks dir: {args.output_dir}")

if __name__ == "__main__":
    main()
