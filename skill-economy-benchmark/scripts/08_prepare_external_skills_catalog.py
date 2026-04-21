#!/usr/bin/env python3
"""Prepare external skill catalog with traceable metadata.

This script builds `data/external_skill_corpus.json` automatically from
`docs/skills-research/official_skills.json`:
1) Parse source URL / license / description from raw records.
2) Infer retrieval schema fields (family/artifacts/operations/tools/...).
3) Optionally filter by selected task ids (task-relevant external candidates).
4) Optionally deduplicate against internal registry skill ids.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = PROJECT_ROOT / "docs" / "skills-research" / "official_skills.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "external_skill_corpus.json"
DEFAULT_DATASET_INDEX = PROJECT_ROOT / "dataset" / "dataset_index.json"
DEFAULT_INTERNAL_REGISTRY = PROJECT_ROOT / "data" / "skill_registry.json"
DEFAULT_FETCH_REPOS = (
    "anthropics/skills:skills,"
    "openai/skills:skills/.curated,"
    "openai/skills:skills/.experimental,"
    "openai/skills:skills/.system"
)

FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
FM_LINE_RE = re.compile(r"^\s*([A-Za-z0-9_-]+)\s*:\s*(.*?)\s*$")
TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9\-_/+]*")

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

KEYWORDS_TO_ARTIFACTS = {
    "pdf": {"pdf"},
    "spreadsheet": {"xlsx"},
    "excel": {"xlsx"},
    "xlsx": {"xlsx"},
    "csv": {"csv"},
    "json": {"json"},
    "latex": {"latex"},
    "notebook": {"notebook"},
    "html": {"html"},
}
KEYWORDS_TO_OPERATIONS = {
    "extract": {"extract"},
    "parse": {"extract"},
    "transform": {"transform"},
    "convert": {"transform"},
    "aggregate": {"aggregate"},
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
    "analyze": {"analyze"},
    "analysis": {"analyze"},
    "test": {"verify"},
    "testing": {"verify"},
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
    "playwright": {"browser"},
    "geospatial": {"geospatial"},
    "gis": {"geospatial"},
}


def _read_json(path: Path) -> Any:
    with open(path) as f:
        return json.load(f)


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))


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
    frontmatter = match.group(1)
    parsed: dict[str, str] = {}
    for line in frontmatter.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = FM_LINE_RE.match(line)
        if not m:
            continue
        key = m.group(1).strip().lower()
        value = m.group(2).strip().strip('"').strip("'")
        parsed[key] = value
    return parsed


def _collect_source_items(raw: dict[str, Any]) -> list[dict[str, Any]]:
    collected: list[dict[str, Any]] = []
    for _, entries in raw.items():
        if not isinstance(entries, list):
            continue
        for item in entries:
            if isinstance(item, dict):
                collected.append(item)
    return collected


def _http_get_json(url: str, token: str | None) -> Any:
    req = urllib.request.Request(url, method="GET")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "skill-economy-benchmark/08_prepare_external_skills_catalog")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _github_contents(owner: str, repo: str, path: str, token: str | None) -> list[dict[str, Any]]:
    encoded_path = urllib.parse.quote(path.strip("/"))
    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{encoded_path}?ref=main"
    try:
        data = _http_get_json(url, token)
    except urllib.error.HTTPError as e:
        # fallback to master branch
        if e.code != 404:
            raise
        url = f"https://api.github.com/repos/{owner}/{repo}/contents/{encoded_path}?ref=master"
        data = _http_get_json(url, token)
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    return [data] if isinstance(data, dict) else []


def _decode_base64_text(raw: str) -> str:
    compact = raw.strip().replace("\n", "")
    return base64.b64decode(compact).decode("utf-8", errors="replace")


def _fetch_live_source_items(fetch_repos: str, token: str | None, max_fetch_skills: int) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
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
                # if API returns only metadata, skip
                continue
            content = _decode_base64_text(content_b64)
            items.append(
                {
                    "name": skill_name,
                    "source": f"{owner}/{repo}",
                    "type": "official_live",
                    "url": f"https://github.com/{owner}/{repo}/tree/main/{skill_rel}",
                    "content": content,
                }
            )
            if len(items) >= max_fetch_skills:
                return items
    return items


def _infer_family(tokens: set[str], source_name: str) -> str:
    if "pdf" in tokens:
        return "document_extraction"
    if "xlsx" in tokens or "spreadsheet" in tokens or "excel" in tokens:
        return "spreadsheet_analytics"
    if "ci" in tokens or "debug" in tokens or source_name.startswith("gh-"):
        return "debugging_ci_repair"
    if "gis" in tokens or "geospatial" in tokens:
        return "geospatial_analysis"
    if "statistics" in tokens or "analysis" in tokens or "data" in tokens:
        return "data_analytics"
    return "general_problem_solving"


def _infer_artifacts(tokens: set[str]) -> list[str]:
    artifacts: set[str] = set()
    for k, vals in KEYWORDS_TO_ARTIFACTS.items():
        if _normalize_token(k) in tokens:
            artifacts |= vals
    return sorted(artifacts)


def _infer_operations(tokens: set[str]) -> list[str]:
    ops: set[str] = {"verify"}
    for k, vals in KEYWORDS_TO_OPERATIONS.items():
        if _normalize_token(k) in tokens:
            ops |= vals
    return sorted(ops)


def _infer_tools(tokens: set[str], artifacts: list[str], family: str) -> list[str]:
    tools: set[str] = set()
    for k, vals in KEYWORDS_TO_TOOLS.items():
        if _normalize_token(k) in tokens:
            tools |= vals
    if "xlsx" in artifacts:
        tools |= {"spreadsheet", "python"}
    if "pdf" in artifacts:
        tools |= {"pdf", "python"}
    if family == "debugging_ci_repair":
        tools |= {"shell"}
    if not tools:
        tools = {"shell"}
    return sorted(tools)


def _infer_granularity(text: str) -> str:
    lowered = text.lower()
    if any(x in lowered for x in ("workflow", "quick start", "process", "step")):
        return "compositional"
    if any(x in lowered for x in ("guide", "toolkit", "comprehensive")):
        return "generic"
    return "atomic"


def _infer_domain_specificity(tokens: set[str]) -> str:
    domain_keywords = {"ci", "github", "spreadsheet", "excel", "pdf", "playwright", "gis", "geospatial"}
    score = len(tokens & domain_keywords)
    if score >= 3:
        return "high"
    if score >= 1:
        return "medium"
    return "low"


def _task_family_candidates(dataset_index: Path, task_ids: list[str] | None) -> set[str]:
    if not task_ids:
        return set()
    data = _read_json(dataset_index)
    task_map = {str(t.get("task_id")): t for t in data.get("tasks", []) if isinstance(t, dict)}
    families: set[str] = set()
    for tid in task_ids:
        task = task_map.get(tid)
        if not task:
            continue
        for tag in task.get("tags", []) or []:
            fam = TAG_TO_FAMILY.get(_normalize_token(str(tag)))
            if fam:
                families.add(fam)
        required = {str(x).lower() for x in (task.get("required_skills") or [])}
        if "xlsx" in required:
            families.add("spreadsheet_analytics")
        if "pdf" in required:
            families.add("document_extraction")
    return families


def _internal_skill_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    data = _read_json(path)
    skills = data.get("skills", [])
    result = set()
    for s in skills:
        if isinstance(s, dict) and s.get("skill_id"):
            result.add(str(s["skill_id"]).strip())
    return result


def build_external_catalog(
    source_path: Path,
    output_path: Path,
    dataset_index: Path,
    task_ids: list[str] | None,
    internal_registry: Path,
    max_skills: int,
    source_items: list[dict[str, Any]] | None = None,
    source_mode: str = "file",
) -> dict[str, Any]:
    if source_items is None:
        raw = _read_json(source_path)
        source_items = _collect_source_items(raw)
    target_families = _task_family_candidates(dataset_index, task_ids)
    internal_ids = _internal_skill_ids(internal_registry)

    candidates: list[dict[str, Any]] = []
    for src in source_items:
        name = str(src.get("name", "")).strip()
        if not name:
            continue
        if name in internal_ids:
            continue
        fm = _parse_frontmatter(str(src.get("content", "")))
        summary = str(fm.get("description") or "").strip()
        license_note = str(fm.get("license") or "unknown").strip()
        source_url = str(src.get("url", "")).strip()
        source_repo = str(src.get("source", "external")).strip()
        corpus_text = " ".join(
            [
                name,
                summary,
                source_url,
                str(src.get("content", ""))[:4000],
            ]
        )
        tokens = _tokenize(corpus_text)
        family = _infer_family(tokens, source_name=name)
        if target_families and family not in target_families and family != "general_problem_solving":
            continue
        artifacts = _infer_artifacts(tokens)
        operations = _infer_operations(tokens)
        tools = _infer_tools(tokens, artifacts, family)
        granularity = _infer_granularity(corpus_text)
        domain_specificity = _infer_domain_specificity(tokens)
        if not summary:
            summary = f"External skill candidate from {source_repo}: {name}"

        candidates.append(
            {
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
        )

    # Simple ranking to keep relevant and actionable skills first.
    def _rank(x: dict[str, Any]) -> tuple[float, int]:
        fam = x["family"][0] if x.get("family") else "general_problem_solving"
        fam_bonus = 2.0 if fam in target_families else (1.0 if fam == "general_problem_solving" else 0.5)
        op_bonus = min(2.0, 0.3 * len(x.get("operations", [])))
        tool_bonus = min(1.5, 0.25 * len(x.get("tools", [])))
        license_bonus = 1.0 if x.get("metadata", {}).get("license_note", "").lower() != "unknown" else 0.0
        return (fam_bonus + op_bonus + tool_bonus + license_bonus, len(x.get("summary", "")))

    candidates.sort(key=_rank, reverse=True)
    skills = candidates[: max(1, max_skills)]

    payload = {
        "generated_at": datetime.now().isoformat(),
        "source_file": str(source_path),
        "source_mode": source_mode,
        "dataset_index": str(dataset_index),
        "task_ids": task_ids or [],
        "target_families": sorted(target_families),
        "internal_registry": str(internal_registry),
        "summary": {
            "n_source_items": len(source_items),
            "n_after_filter": len(candidates),
            "n_written_skills": len(skills),
            "max_skills": max_skills,
        },
        "skills": skills,
    }
    _write_json(output_path, payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare external skills catalog with source and license metadata.")
    parser.add_argument("--source-file", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output-file", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--dataset-index", type=Path, default=DEFAULT_DATASET_INDEX)
    parser.add_argument("--task-ids", type=str, default=None, help="Comma-separated task ids for task-relevant filtering.")
    parser.add_argument("--internal-registry", type=Path, default=DEFAULT_INTERNAL_REGISTRY)
    parser.add_argument("--max-skills", type=int, default=30)
    parser.add_argument("--live-fetch", action="store_true", help="Fetch external skills live from GitHub repos instead of using only local source file.")
    parser.add_argument("--github-token", type=str, default=None, help="GitHub token (or use GITHUB_TOKEN env).")
    parser.add_argument("--fetch-repos", type=str, default=DEFAULT_FETCH_REPOS, help="Comma-separated repo specs: owner/repo:path")
    parser.add_argument("--max-fetch-skills", type=int, default=120)
    parser.add_argument("--save-live-snapshot", action="store_true", help="Save fetched raw items to --source-file for reproducibility.")
    parser.add_argument("--query-manifest", type=Path, default=PROJECT_ROOT / "data" / "external_queries.json")
    parser.add_argument("--query-dir", type=Path, default=PROJECT_ROOT / "data" / "external_queries")
    parser.add_argument("--source-policy", type=Path, default=PROJECT_ROOT / "data" / "source_policy.json")
    parser.add_argument("--output-raw-hits", type=Path, default=PROJECT_ROOT / "data" / "external_hits.raw.json")
    parser.add_argument("--per-task-output-dir", type=Path, default=PROJECT_ROOT / "data" / "external_candidates")
    args = parser.parse_args()

    token = args.github_token or os.getenv("GITHUB_TOKEN")
    source_mode = "file"
    live_items: list[dict[str, Any]] | None = None
    if args.live_fetch:
        live_items = _fetch_live_source_items(args.fetch_repos, token, max_fetch_skills=max(1, args.max_fetch_skills))
        if live_items:
            source_mode = "github_live"
            print(f"[INFO] Live fetched skills: {len(live_items)}")
            if args.save_live_snapshot:
                snapshot = {"live": live_items, "fetched_at": datetime.now().isoformat(), "fetch_repos": args.fetch_repos}
                _write_json(args.source_file, snapshot)
                print(f"[INFO] Saved live snapshot to: {args.source_file}")
        else:
            print("[WARN] Live fetch produced 0 items, fallback to local source file.")

    if source_mode == "file" and not args.source_file.exists():
        raise SystemExit(f"Source file not found: {args.source_file}")

    selected_task_ids = [x.strip() for x in args.task_ids.split(",") if x.strip()] if args.task_ids else None
    result = build_external_catalog(
        source_path=args.source_file,
        output_path=args.output_file,
        dataset_index=args.dataset_index,
        task_ids=selected_task_ids,
        internal_registry=args.internal_registry,
        max_skills=max(1, args.max_skills),
        source_items=live_items,
        source_mode=source_mode,
    )
    print(json.dumps(result["summary"], indent=2))
    print(f"Written: {args.output_file}")


if __name__ == "__main__":
    main()
