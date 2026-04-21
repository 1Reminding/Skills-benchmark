#!/usr/bin/env python3
from __future__ import annotations
import argparse, base64, json, os, re, urllib.error, urllib.parse, urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = PROJECT_ROOT / "docs" / "skills-research" / "official_skills.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "external_skill_corpus.json"
DEFAULT_OUTPUT_RAW_HITS = PROJECT_ROOT / "data" / "external_hits.raw.json"
DEFAULT_PER_TASK_OUTPUT_DIR = PROJECT_ROOT / "data" / "external_candidates"
DEFAULT_INTERNAL_REGISTRY = PROJECT_ROOT / "data" / "skill_registry.json"
DEFAULT_QUERY_MANIFEST = PROJECT_ROOT / "data" / "external_queries.json"
DEFAULT_QUERY_DIR = PROJECT_ROOT / "data" / "external_queries"
DEFAULT_FETCH_REPOS = (
    "anthropics/skills:skills,"
    "openai/skills:skills/.curated,"
    "openai/skills:skills/.experimental,"
    "openai/skills:skills/.system"
)

FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
FM_LINE_RE = re.compile(r"^\s*([A-Za-z0-9_-]+)\s*:\s*(.*?)\s*$")
TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9\-_/+]*")
WEAK_ARTIFACTS = {"json", "text", "markdown", "python"}

KEYWORDS_TO_ARTIFACTS = {
    "pdf": {"pdf"}, "spreadsheet": {"xlsx"}, "excel": {"xlsx"}, "xlsx": {"xlsx"},
    "csv": {"csv"}, "json": {"json"}, "latex": {"latex"}, "notebook": {"notebook"}, "html": {"html"},
}
KEYWORDS_TO_OPERATIONS = {
    "extract": {"extract"}, "parse": {"extract"}, "transform": {"transform"},
    "convert": {"transform"}, "aggregate": {"aggregate"}, "calculate": {"calculate"},
    "compute": {"calculate"}, "verify": {"verify", "validate"}, "validate": {"validate"},
    "check": {"validate"}, "debug": {"debug"}, "fix": {"debug", "patch"},
    "patch": {"patch"}, "search": {"search"}, "plan": {"plan"}, "analyze": {"analyze"},
    "analysis": {"analyze"}, "test": {"verify"}, "testing": {"verify"},
}
KEYWORDS_TO_TOOLS = {
    "python": {"python"}, "pandas": {"python"}, "pytest": {"testing"}, "test": {"testing"},
    "testing": {"testing"}, "ci": {"ci"}, "shell": {"shell"}, "bash": {"shell"},
    "terminal": {"shell"}, "spreadsheet": {"spreadsheet"}, "excel": {"spreadsheet"},
    "pdf": {"pdf"}, "browser": {"browser"}, "playwright": {"browser"},
    "geospatial": {"geospatial"}, "gis": {"geospatial"},
}
TRUSTED_REPO_BONUS = {"anthropics/skills": 0.5, "openai/skills": 0.5}

def _read_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

def _normalize_token(token: str) -> str:
    token = token.lower().strip()
    if token.endswith("s") and len(token) > 4:
        token = token[:-1]
    return token

def _tokenize(text: str) -> set[str]:
    return {_normalize_token(t) for t in TOKEN_RE.findall((text or "").lower()) if len(t) >= 2}

def _parse_frontmatter(content: str) -> dict[str, str]:
    match = FRONTMATTER_RE.match(content or "")
    if not match:
        return {}
    parsed = {}
    for line in match.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = FM_LINE_RE.match(line)
        if not m:
            continue
        parsed[m.group(1).strip().lower()] = m.group(2).strip().strip('"').strip("'")
    return parsed

def _collect_source_items(raw: Any) -> list[dict[str, Any]]:
    collected = []
    if isinstance(raw, dict):
        if "live" in raw and isinstance(raw["live"], list):
            return [x for x in raw["live"] if isinstance(x, dict)]
        for _, entries in raw.items():
            if isinstance(entries, list):
                for item in entries:
                    if isinstance(item, dict):
                        collected.append(item)
    elif isinstance(raw, list):
        collected = [x for x in raw if isinstance(x, dict)]
    return collected

def _http_get_json(url: str, token: str | None) -> Any:
    req = urllib.request.Request(url, method="GET")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "skill-economy-benchmark/09_collect_external_skills")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))

def _github_contents(owner: str, repo: str, path: str, token: str | None) -> list[dict[str, Any]]:
    encoded = urllib.parse.quote(path.strip("/"))
    for ref in ("main", "master"):
        url = f"https://api.github.com/repos/{owner}/{repo}/contents/{encoded}?ref={ref}"
        try:
            data = _http_get_json(url, token)
            if isinstance(data, list):
                return [x for x in data if isinstance(x, dict)]
            return [data] if isinstance(data, dict) else []
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
    return []

def _decode_base64_text(raw: str) -> str:
    return base64.b64decode(raw.strip().replace("\n", "")).decode("utf-8", errors="replace")

def _fetch_live_source_items(fetch_repos: str, token: str | None, max_fetch_skills: int) -> list[dict[str, Any]]:
    items = []
    specs = [s.strip() for s in fetch_repos.split(",") if s.strip()]
    for spec in specs:
        if ":" not in spec or "/" not in spec.split(":", 1)[0]:
            continue
        repo_part, root_path = spec.split(":", 1)
        owner, repo = repo_part.split("/", 1)
        try:
            entries = _github_contents(owner, repo, root_path, token)
        except Exception as e:
            print(f"[WARN] Failed to list {owner}/{repo}:{root_path} -> {e}")
            continue
        for ent in entries:
            if ent.get("type") != "dir":
                continue
            skill_name = str(ent.get("name", "")).strip()
            if not skill_name:
                continue
            skill_rel = f"{root_path.strip('/')}/{skill_name}"
            try:
                md_entries = _github_contents(owner, repo, f"{skill_rel}/SKILL.md", token)
            except Exception:
                continue
            if not md_entries:
                continue
            md = md_entries[0]
            content_b64 = str(md.get("content", "")).strip()
            if not content_b64:
                continue
            items.append({
                "name": skill_name,
                "source": f"{owner}/{repo}",
                "type": "official_live",
                "url": f"https://github.com/{owner}/{repo}/tree/main/{skill_rel}",
                "content": _decode_base64_text(content_b64),
            })
            if len(items) >= max_fetch_skills:
                return items
    return items

def _internal_skill_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    data = _read_json(path)
    return {str(s["skill_id"]).strip() for s in data.get("skills", []) if isinstance(s, dict) and s.get("skill_id")}

def _infer_family(tokens: set[str], source_name: str) -> str:
    if "pdf" in tokens: return "document_extraction"
    if "xlsx" in tokens or "spreadsheet" in tokens or "excel" in tokens: return "spreadsheet_analytics"
    if "ci" in tokens or "debug" in tokens or source_name.startswith("gh-"): return "debugging_ci_repair"
    if "gis" in tokens or "geospatial" in tokens: return "geospatial_analysis"
    if "statistics" in tokens or "analysis" in tokens or "data" in tokens: return "data_analytics"
    return "general_problem_solving"

def _infer_artifacts(tokens: set[str]) -> list[str]:
    out = set()
    for k, vals in KEYWORDS_TO_ARTIFACTS.items():
        if _normalize_token(k) in tokens:
            out |= vals
    return sorted(out)

def _infer_operations(tokens: set[str]) -> list[str]:
    ops = {"verify"}
    for k, vals in KEYWORDS_TO_OPERATIONS.items():
        if _normalize_token(k) in tokens:
            ops |= vals
    return sorted(ops)

def _infer_tools(tokens: set[str], artifacts: list[str], family: str) -> list[str]:
    out = set()
    for k, vals in KEYWORDS_TO_TOOLS.items():
        if _normalize_token(k) in tokens:
            out |= vals
    if "xlsx" in artifacts:
        out |= {"spreadsheet", "python"}
    if "pdf" in artifacts:
        out |= {"pdf", "python"}
    if family == "debugging_ci_repair":
        out |= {"shell"}
    return sorted(out or {"shell"})

def _infer_granularity(text: str) -> str:
    low = text.lower()
    if any(x in low for x in ("workflow", "quick start", "process", "step")): return "compositional"
    if any(x in low for x in ("guide", "toolkit", "comprehensive")): return "generic"
    return "atomic"

def _infer_domain_specificity(tokens: set[str]) -> str:
    domain_keywords = {"ci", "github", "spreadsheet", "excel", "pdf", "playwright", "gis", "geospatial"}
    score = len(tokens & domain_keywords)
    if score >= 3: return "high"
    if score >= 1: return "medium"
    return "low"

def _load_query_plans(query_manifest: Path, query_dir: Path, selected_task_ids: list[str] | None) -> dict[str, dict[str, Any]]:
    plans = {}
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
            if not query_file.exists():
                continue
            plans[task_id] = _read_json(query_file)
    else:
        for p in sorted(query_dir.glob("*.json")):
            task_data = _read_json(p)
            task_id = str(task_data.get("task_id", "")).strip()
            if not task_id:
                continue
            if selected_task_ids and task_id not in selected_task_ids:
                continue
            plans[task_id] = task_data
    return plans

def _soft_duplicate_flag(external_item: dict[str, Any], internal_registry_path: Path) -> bool:
    if not internal_registry_path.exists():
        return False
    data = _read_json(internal_registry_path)
    ext_tokens = _tokenize(" ".join([
        external_item.get("skill_id", ""), external_item.get("summary", ""),
        " ".join(external_item.get("family", [])), " ".join(external_item.get("operations", [])),
        " ".join(external_item.get("tools", [])),
    ]))
    if not ext_tokens:
        return False
    for s in data.get("skills", []):
        if not isinstance(s, dict):
            continue
        int_tokens = _tokenize(" ".join([
            str(s.get("skill_id", "")), str(s.get("summary", "")),
            " ".join(s.get("family", []) or []), " ".join(s.get("operations", []) or []),
            " ".join(s.get("tools", []) or []),
        ]))
        if len(ext_tokens & int_tokens) >= 8:
            return True
    return False

def _normalize_external_item(src: dict[str, Any], source_mode: str) -> dict[str, Any] | None:
    name = str(src.get("name", "")).strip()
    if not name:
        return None
    fm = _parse_frontmatter(str(src.get("content", "")))
    summary = str(fm.get("description") or "").strip()
    license_note = str(fm.get("license") or "unknown").strip()
    source_url = str(src.get("url", "")).strip()
    source_repo = str(src.get("source", "external")).strip()
    corpus_text = " ".join([name, summary, source_url, str(src.get("content", ""))[:4000]])
    tokens = _tokenize(corpus_text)
    family = _infer_family(tokens, source_name=name)
    artifacts = _infer_artifacts(tokens)
    operations = _infer_operations(tokens)
    tools = _infer_tools(tokens, artifacts, family)
    granularity = _infer_granularity(corpus_text)
    domain_specificity = _infer_domain_specificity(tokens)
    if not summary:
        summary = f"External skill candidate from {source_repo}: {name}"
    return {
        "skill_id": name,
        "source_type": "external",
        "family": [family],
        "artifacts": artifacts,
        "operations": operations,
        "tools": tools,
        "granularity": granularity,
        "domain_specificity": domain_specificity,
        "summary": summary,
        "metadata": {
            "source_name": name,
            "source_url": source_url,
            "source_repo": source_repo,
            "license_note": license_note,
            "provenance": source_mode,
            "collected_at": datetime.now().isoformat(),
        },
    }

def _score_external_item_for_task(item: dict[str, Any], task_plan: dict[str, Any]) -> tuple[float, list[str]]:
    score = 0.0
    reasons = []
    schema = task_plan.get("schema", {}) or {}
    task_family = str(schema.get("family") or "general_problem_solving")
    task_artifacts = {a for a in (schema.get("artifacts") or []) if a not in WEAK_ARTIFACTS}
    task_ops = set(schema.get("operations") or [])
    task_tools = set(schema.get("tools") or [])
    allowed_domains = set((task_plan.get("source_policy") or {}).get("allowed_domains", []))
    item_family = set(item.get("family", []))
    item_artifacts = {a for a in item.get("artifacts", []) if a not in WEAK_ARTIFACTS}
    item_ops = set(item.get("operations", []))
    item_tools = set(item.get("tools", []))

    if task_family in item_family:
        score += 4.0; reasons.append("family_match")
    elif "general_problem_solving" in item_family:
        score += 1.0; reasons.append("generic_family_match")
    artifact_overlap = task_artifacts & item_artifacts
    if artifact_overlap:
        score += 2.0 * len(artifact_overlap); reasons.append("artifact_overlap")
    op_overlap = task_ops & item_ops
    if op_overlap:
        score += 1.5 * len(op_overlap); reasons.append("operation_overlap")
    tool_overlap = task_tools & item_tools
    if tool_overlap:
        score += 1.0 * len(tool_overlap); reasons.append("tool_overlap")

    item_tokens = _tokenize(" ".join([
        item.get("skill_id", ""), item.get("summary", ""),
        " ".join(item.get("family", [])), " ".join(item.get("artifacts", [])),
        " ".join(item.get("operations", [])), " ".join(item.get("tools", [])),
    ]))
    best_query_overlap = 0
    best_query_id = None
    for q in task_plan.get("queries", []) or []:
        if not isinstance(q, dict):
            continue
        q_tokens = _tokenize(str(q.get("text", "")))
        overlap = len(q_tokens & item_tokens)
        if overlap > best_query_overlap:
            best_query_overlap = overlap
            best_query_id = q.get("query_id")
    if best_query_overlap:
        score += min(4.0, 0.6 * best_query_overlap); reasons.append("query_overlap")
        if best_query_id:
            reasons.append(f"best_query:{best_query_id}")

    source_url = str(item.get("metadata", {}).get("source_url", ""))
    source_repo = str(item.get("metadata", {}).get("source_repo", ""))
    if any(dom in source_url for dom in allowed_domains):
        score += 1.0; reasons.append("allowed_domain_match")
    for repo_name, bonus in TRUSTED_REPO_BONUS.items():
        if source_repo == repo_name:
            score += bonus; reasons.append("trusted_repo_bonus"); break

    meaningful = (task_family in item_family) or bool(artifact_overlap) or bool(op_overlap) or bool(tool_overlap) or best_query_overlap >= 2
    if not meaningful:
        return 0.0, ["insufficient_signal"]
    return round(score, 3), reasons

def build_external_catalog(
    source_path: Path, output_path: Path, output_raw_hits: Path, per_task_output_dir: Path,
    query_manifest: Path, query_dir: Path, task_ids: list[str] | None, internal_registry: Path,
    max_skills: int, source_items: list[dict[str, Any]] | None = None, source_mode: str = "file"
) -> dict[str, Any]:
    if source_items is None:
        raw = _read_json(source_path)
        source_items = _collect_source_items(raw)
    query_plans = _load_query_plans(query_manifest, query_dir, task_ids)
    if not query_plans:
        raise SystemExit("No query plans found. Run 08_generate_external_queries.py first.")
    internal_ids = _internal_skill_ids(internal_registry)
    normalized_items = []
    for src in source_items:
        item = _normalize_external_item(src, source_mode=source_mode)
        if item is None:
            continue
        if item["skill_id"] in internal_ids:
            continue
        item["metadata"]["possible_internal_duplicate"] = _soft_duplicate_flag(item, internal_registry)
        normalized_items.append(item)

    raw_hits = []
    per_task = {}
    for task_id, plan in query_plans.items():
        candidates = []
        for item in normalized_items:
            score, reasons = _score_external_item_for_task(item, plan)
            if score <= 0:
                continue
            cand = dict(item)
            cand["retrieval_score"] = score
            cand["retrieval_path"] = reasons
            cand["task_id"] = task_id
            raw_hits.append(cand)
            candidates.append(cand)
        deduped = {}
        for cand in sorted(candidates, key=lambda x: x["retrieval_score"], reverse=True):
            if cand["skill_id"] not in deduped:
                deduped[cand["skill_id"]] = cand
        ranked = list(deduped.values())
        ranked.sort(key=lambda x: x["retrieval_score"], reverse=True)
        per_task[task_id] = ranked[:max(1, max_skills)]

    global_best = {}
    for task_id, items in per_task.items():
        for item in items:
            sid = item["skill_id"]
            if sid not in global_best or item["retrieval_score"] > global_best[sid]["retrieval_score"]:
                global_best[sid] = {k: v for k, v in item.items() if k not in {"task_id", "retrieval_score", "retrieval_path"}}

    corpus_items = sorted(global_best.values(), key=lambda x: x["skill_id"])
    payload = {
        "generated_at": datetime.now().isoformat(),
        "source_file": str(source_path),
        "source_mode": source_mode,
        "query_manifest": str(query_manifest),
        "query_dir": str(query_dir),
        "task_ids": sorted(query_plans.keys()),
        "internal_registry": str(internal_registry),
        "summary": {
            "n_source_items": len(source_items),
            "n_normalized_items": len(normalized_items),
            "n_raw_hits": len(raw_hits),
            "n_written_skills": len(corpus_items),
            "max_skills_per_task": max_skills,
        },
        "skills": corpus_items,
    }
    _write_json(output_path, payload)
    _write_json(output_raw_hits, {"generated_at": datetime.now().isoformat(), "summary": {"n_raw_hits": len(raw_hits)}, "hits": raw_hits})
    per_task_output_dir.mkdir(parents=True, exist_ok=True)
    for task_id, items in per_task.items():
        _write_json(per_task_output_dir / f"{task_id}.json", {
            "task_id": task_id,
            "generated_at": datetime.now().isoformat(),
            "summary": {"n_candidates": len(items)},
            "external_candidates": items,
        })
    return payload

def main() -> None:
    parser = argparse.ArgumentParser(description="Collect external skills with query-driven task scoring.")
    parser.add_argument("--source-file", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output-file", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--output-raw-hits", type=Path, default=DEFAULT_OUTPUT_RAW_HITS)
    parser.add_argument("--per-task-output-dir", type=Path, default=DEFAULT_PER_TASK_OUTPUT_DIR)
    parser.add_argument("--query-manifest", type=Path, default=DEFAULT_QUERY_MANIFEST)
    parser.add_argument("--query-dir", type=Path, default=DEFAULT_QUERY_DIR)
    parser.add_argument("--task-ids", type=str, default=None)
    parser.add_argument("--internal-registry", type=Path, default=DEFAULT_INTERNAL_REGISTRY)
    parser.add_argument("--max-skills", type=int, default=20)
    parser.add_argument("--live-fetch", action="store_true")
    parser.add_argument("--github-token", type=str, default=None)
    parser.add_argument("--fetch-repos", type=str, default=DEFAULT_FETCH_REPOS)
    parser.add_argument("--max-fetch-skills", type=int, default=120)
    parser.add_argument("--save-live-snapshot", action="store_true")
    args = parser.parse_args()

    token = args.github_token or os.getenv("GITHUB_TOKEN")
    source_mode = "file"
    live_items = None
    if args.live_fetch:
        live_items = _fetch_live_source_items(args.fetch_repos, token, max_fetch_skills=max(1, args.max_fetch_skills))
        if live_items:
            source_mode = "github_live"
            print(f"[INFO] Live fetched skills: {len(live_items)}")
            if args.save_live_snapshot:
                _write_json(args.source_file, {"live": live_items, "fetched_at": datetime.now().isoformat(), "fetch_repos": args.fetch_repos})
                print(f"[INFO] Saved live snapshot to: {args.source_file}")
        else:
            print("[WARN] Live fetch produced 0 items, fallback to local source file.")
    if source_mode == "file" and not args.source_file.exists():
        raise SystemExit(f"Source file not found: {args.source_file}")
    selected_task_ids = [x.strip() for x in args.task_ids.split(",") if x.strip()] if args.task_ids else None
    result = build_external_catalog(
        source_path=args.source_file, output_path=args.output_file, output_raw_hits=args.output_raw_hits,
        per_task_output_dir=args.per_task_output_dir, query_manifest=args.query_manifest, query_dir=args.query_dir,
        task_ids=selected_task_ids, internal_registry=args.internal_registry, max_skills=max(1, args.max_skills),
        source_items=live_items, source_mode=source_mode,
    )
    print(json.dumps(result["summary"], indent=2))
    print(f"Written corpus: {args.output_file}")
    print(f"Written raw hits: {args.output_raw_hits}")
    print(f"Written per-task dir: {args.per_task_output_dir}")

if __name__ == "__main__":
    main()
