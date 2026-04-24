#!/usr/bin/env python3
"""Finalize grounded skill candidates into final JSON + SKILL.md."""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import openai
import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_GENERATED_DIR = PROJECT_ROOT / "data" / "generated_external_skills"
DEFAULT_RANKED_DIR = PROJECT_ROOT / "data" / "external_ranked_chunks"
DEFAULT_FINAL_JSON_DIR = PROJECT_ROOT / "data" / "finalized_external_skills"
DEFAULT_AUDIT_DIR = PROJECT_ROOT / "data" / "finalized_external_skills_audit"
DEFAULT_SKILL_DIR = PROJECT_ROOT / "skill_pool" / "final_external_skills"
DEFAULT_MANIFEST = PROJECT_ROOT / "data" / "finalized_external_skills_manifest.json"
DEFAULT_INTERNAL_REGISTRY = PROJECT_ROOT / "data" / "skill_registry.json"

DEFAULT_API_BASE = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1")
DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_\-/.+]*")
JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", re.DOTALL)
WS_RE = re.compile(r"\s+")

CONTROLLED_FAMILIES = {
    "spreadsheet_analytics",
    "document_extraction",
    "debugging_ci_repair",
    "geospatial_analysis",
    "data_analytics",
    "scientific_analysis",
    "general_problem_solving",
}
CONTROLLED_ARTIFACTS = {
    "xlsx", "csv", "pdf", "html", "json", "notebook", "latex", "xml", "yaml", "txt"
}
CONTROLLED_TOOLS = {
    "python", "spreadsheet", "pdf", "ci", "testing", "shell", "geospatial", "browser"
}
CONTROLLED_OPERATIONS = {
    "extract", "transform", "aggregate", "calculate", "analyze",
    "validate", "verify", "debug", "patch", "search", "plan"
}
GRANULARITIES = {"atomic", "compositional", "generic"}

GENERIC_NAME_BAD_HINTS = {
    "data-processing",
    "data-analysis",
    "excel-workflow",
    "spreadsheet-workflow",
    "data-workflow",
    "general-analysis",
    "workflow-automation",
}

def _read_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")

def _now_iso() -> str:
    return datetime.now().isoformat()

def _compact(text: str) -> str:
    return WS_RE.sub(" ", (text or "")).strip()

def _normalize_token(token: str) -> str:
    token = token.lower().strip().replace("/", "_")
    if token.endswith("s") and len(token) > 4:
        token = token[:-1]
    return token

def _tokenize(text: str) -> set[str]:
    return {_normalize_token(t) for t in TOKEN_RE.findall(text or "") if len(t) >= 2}

def _slugify(text: str) -> str:
    x = re.sub(r"[^A-Za-z0-9]+", "-", (text or "").lower()).strip("-")
    return x or "unknown"

def _safe_list_str(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return sorted({str(v).strip() for v in value if str(v).strip()})
    if str(value).strip():
        return [str(value).strip()]
    return []

def _extract_json(text: str) -> Any:
    text = text.strip()
    m = JSON_BLOCK_RE.search(text)
    if m:
        frag = m.group(1).strip()
        try:
            return json.loads(frag)
        except json.JSONDecodeError:
            pass
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for open_char, close_char in [("[", "]"), ("{", "}")]:
        start = text.find(open_char)
        end = text.rfind(close_char)
        if start != -1 and end != -1 and end > start:
            frag = text[start:end + 1]
            try:
                return json.loads(frag)
            except json.JSONDecodeError:
                continue
    raise ValueError("Could not parse JSON from model output.")

def _load_internal_skill_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    data = _read_json(path)
    return {
        str(s["skill_id"]).strip()
        for s in data.get("skills", [])
        if isinstance(s, dict) and s.get("skill_id")
    }

def _chat_completion(
    client: openai.OpenAI,
    model: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float,
    max_tokens: int,
    reasoning_effort: str | None = None,
) -> str:
    kwargs = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if reasoning_effort:
        kwargs["reasoning_effort"] = reasoning_effort
    try:
        resp = client.chat.completions.create(**kwargs, response_format={"type": "json_object"})
        return resp.choices[0].message.content
    except Exception:
        pass
    try:
        resp = client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content
    except Exception:
        kwargs.pop("reasoning_effort", None)
        resp = client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content

def _repair_json_with_model(client: openai.OpenAI, model: str, bad_text: str, max_tokens: int = 2200) -> str:
    repair_prompt = (
        "请把下面这段模型输出修复成严格合法的 JSON。"
        "不要添加解释，不要使用 markdown 代码块，不要省略字段。"
        "只输出修复后的 JSON。\n\n原始内容如下：\n"
        f"{bad_text}"
    )
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "你是 JSON 修复器。只输出严格 JSON。"},
                {"role": "user", "content": repair_prompt},
            ],
            temperature=0,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        return resp.choices[0].message.content
    except Exception:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "你是 JSON 修复器。只输出严格 JSON。"},
                {"role": "user", "content": repair_prompt},
            ],
            temperature=0,
            max_tokens=max_tokens,
        )
        return resp.choices[0].message.content

def _prefilter_candidates(task_id: str, schema: dict[str, Any], candidates: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    kept = []
    removed = []
    task_family = str(schema.get("family") or "general_problem_solving")
    schema_ops = set(_safe_list_str(schema.get("operations")))
    schema_artifacts = set(_safe_list_str(schema.get("artifacts")))
    schema_tools = set(_safe_list_str(schema.get("tools")))
    seen_summary_sig = set()

    for cand in candidates:
        skill_id = str(cand.get("skill_id", "")).strip()
        family = set(_safe_list_str(cand.get("family")))
        ops = set(_safe_list_str(cand.get("operations")))
        arts = set(_safe_list_str(cand.get("artifacts")))
        tools = set(_safe_list_str(cand.get("tools")))
        summary = _compact(str(cand.get("summary", "")))
        conf = float((cand.get("metadata", {}) or {}).get("confidence", 0.5))

        reason = None
        if not summary or len(summary) < 30:
            reason = "summary_too_short"
        elif not ((ops & schema_ops) or (arts & schema_artifacts) or (tools & schema_tools) or (task_family in family)):
            reason = "low_schema_alignment"
        elif _slugify(skill_id) in GENERIC_NAME_BAD_HINTS:
            reason = "too_generic_name"
        elif conf < 0.45:
            reason = "low_confidence"

        sig = " ".join(sorted(_tokenize(summary)))
        if not reason and sig in seen_summary_sig:
            reason = "duplicate_summary"
        if not reason and sig:
            seen_summary_sig.add(sig)

        if reason:
            removed.append({"skill_id": skill_id or "unknown", "reason": reason})
        else:
            kept.append(cand)

    if not kept and candidates:
        kept = sorted(candidates, key=lambda x: -float((x.get("metadata", {}) or {}).get("confidence", 0.5)))[: min(3, len(candidates))]
    return kept, removed

def _system_prompt() -> str:
    return """You are the final reviewer for benchmark-compatible skill candidates.

Your job is NOT to invent new skills.
Your job is to review and lightly refine already-generated candidates under strict evidence constraints.

Rules:
1. You may keep, delete, merge-near-duplicates, or lightly rename/rewrite candidates.
2. You must NOT introduce unsupported claims.
3. Every final candidate must keep evidence grounding via source_chunk_ids/source_urls.
4. Prefer reusable procedural skill units, not task answers.
5. Prefer candidates that are distinct from each other.
6. Prefer candidates that align with the task schema.
7. Output strict JSON only.
"""

def _user_prompt(task_id: str, schema: dict[str, Any], candidates: list[dict[str, Any]], evidence_map: list[dict[str, Any]], keep_min: int, keep_max: int) -> str:
    prompt = {
        "task_id": task_id,
        "task_schema": schema,
        "goal": (
            "Review and finalize the candidate pool. "
            "Keep only the strongest grounded candidates, lightly refine names/summaries if useful, "
            "and preserve evidence grounding."
        ),
        "allowed_actions": [
            "keep candidate",
            "delete weak/generic candidate",
            "lightly rename candidate",
            "lightly rewrite summary",
            "merge near-duplicate candidates if and only if evidence overlaps strongly"
        ],
        "hard_constraints": [
            f"Keep between {keep_min} and {keep_max} final candidates if evidence supports it.",
            "Do NOT invent a new skill that is not clearly grounded by the provided candidates/evidence.",
            "Every final candidate must include source_chunk_ids and source_urls drawn from the provided evidence only.",
            "Prefer benchmark-compatible skill units rather than broad project descriptions.",
            "Do not output markdown. Output JSON only."
        ],
        "required_output_schema": {
            "task_id": task_id,
            "final_skill_candidates": [
                {
                    "skill_id": "string, lowercase kebab-case, concise",
                    "display_name": "string",
                    "family": "one controlled family label",
                    "artifacts": ["controlled artifact labels"],
                    "tools": ["controlled tool labels"],
                    "operations": ["controlled operation labels"],
                    "granularity": "atomic|compositional|generic",
                    "summary": "1-3 sentence grounded summary",
                    "why_kept": "brief explanation",
                    "source_chunk_ids": ["evidence chunk ids"],
                    "source_urls": ["evidence urls"],
                    "confidence": "0-1 float"
                }
            ],
            "removed_candidates": [
                {"skill_id": "string", "reason": "brief reason"}
            ]
        },
        "input_candidates": candidates,
        "evidence_reference": evidence_map,
    }
    return json.dumps(prompt, ensure_ascii=False, indent=2)

def _normalize_final_candidate(candidate: dict[str, Any], task_id: str, schema: dict[str, Any], valid_chunk_ids: set[str], valid_urls: set[str], internal_skill_ids: set[str]) -> dict[str, Any] | None:
    skill_id = _slugify(str(candidate.get("skill_id") or candidate.get("display_name") or "").strip())
    if not skill_id:
        return None
    if skill_id in internal_skill_ids:
        skill_id = f"ext-{task_id}-{skill_id}"

    display_name = _compact(str(candidate.get("display_name") or skill_id))
    family = str(candidate.get("family") or schema.get("family") or "general_problem_solving").strip()
    if family not in CONTROLLED_FAMILIES:
        family = str(schema.get("family") or "general_problem_solving")

    artifacts = [x for x in _safe_list_str(candidate.get("artifacts")) if x in CONTROLLED_ARTIFACTS]
    tools = [x for x in _safe_list_str(candidate.get("tools")) if x in CONTROLLED_TOOLS]
    operations = [x for x in _safe_list_str(candidate.get("operations")) if x in CONTROLLED_OPERATIONS]
    granularity = str(candidate.get("granularity") or "compositional").strip()
    if granularity not in GRANULARITIES:
        granularity = "compositional"

    if not artifacts:
        artifacts = [x for x in _safe_list_str(schema.get("artifacts")) if x in CONTROLLED_ARTIFACTS][:2]
    if not tools:
        tools = [x for x in _safe_list_str(schema.get("tools")) if x in CONTROLLED_TOOLS][:3]
    if not operations:
        operations = [x for x in _safe_list_str(schema.get("operations")) if x in CONTROLLED_OPERATIONS][:3]

    summary = _compact(str(candidate.get("summary") or ""))
    if len(summary) < 30:
        return None

    why_kept = _compact(str(candidate.get("why_kept") or ""))
    source_chunk_ids = [x for x in _safe_list_str(candidate.get("source_chunk_ids")) if x in valid_chunk_ids]
    source_urls = [x for x in _safe_list_str(candidate.get("source_urls")) if x in valid_urls]

    if not source_chunk_ids:
        return None

    try:
        confidence = float(candidate.get("confidence", 0.6))
    except Exception:
        confidence = 0.6
    confidence = max(0.0, min(1.0, confidence))

    return {
        "skill_id": skill_id,
        "display_name": display_name,
        "family": [family],
        "artifacts": artifacts,
        "tools": tools,
        "operations": operations,
        "granularity": granularity,
        "summary": summary,
        "why_kept": why_kept,
        "metadata": {
            "task_id": task_id,
            "source_chunk_ids": source_chunk_ids,
            "source_urls": source_urls,
            "confidence": round(confidence, 3),
            "finalized_at": _now_iso(),
            "finalizer": "12_finalize_skill_candidates.py",
        },
    }

def _dedupe_final_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kept = []
    seen = set()
    for cand in sorted(candidates, key=lambda x: (-x["metadata"]["confidence"], x["skill_id"])):
        key = (
            cand["skill_id"],
            tuple(cand.get("family", [])),
            tuple(cand.get("artifacts", [])),
            tuple(cand.get("tools", [])),
            tuple(cand.get("operations", [])),
        )
        if key in seen:
            continue
        seen.add(key)
        sig = " ".join(sorted(_tokenize(cand.get("summary", ""))))
        if sig and sig in seen:
            continue
        seen.add(sig)
        kept.append(cand)
    return kept

def _backfill_urls(candidates: list[dict[str, Any]], evidence_map: dict[str, dict[str, Any]]) -> None:
    for cand in candidates:
        urls = set(cand["metadata"].get("source_urls", []))
        for cid in cand["metadata"].get("source_chunk_ids", []):
            ev = evidence_map.get(cid)
            if ev:
                url = str(ev.get("source_url", "")).strip()
                if url:
                    urls.add(url)
        cand["metadata"]["source_urls"] = sorted(urls)

def _render_skill_md(task_id: str, skill: dict[str, Any], evidence_map: dict[str, dict[str, Any]]) -> str:
    ev_lines = []
    for cid in skill["metadata"].get("source_chunk_ids", []):
        ev = evidence_map.get(cid, {})
        url = str(ev.get("source_url", "")).strip()
        title = str(ev.get("title", "")).strip()
        section = str(ev.get("section_title", "")).strip()
        if url:
            ev_lines.append(f"- {title} :: {section}\n  - {url}")
        else:
            ev_lines.append(f"- {title} :: {section}")

    frontmatter = {
        "skill_id": skill["skill_id"],
        "display_name": skill["display_name"],
        "task_id": task_id,
        "family": skill.get("family", []),
        "artifacts": skill.get("artifacts", []),
        "tools": skill.get("tools", []),
        "operations": skill.get("operations", []),
        "granularity": skill.get("granularity"),
        "confidence": skill["metadata"].get("confidence"),
        "source_urls": skill["metadata"].get("source_urls", []),
    }

    fm_lines = ["---"]
    for k, v in frontmatter.items():
        fm_lines.append(f"{k}: {json.dumps(v, ensure_ascii=False)}")
    fm_lines.append("---")

    body = [
        f"# {skill['display_name']}",
        "",
        "## Summary",
        skill["summary"],
        "",
        "## Why kept",
        skill.get("why_kept", "") or "Grounded candidate retained after final review.",
        "",
        "## When to use",
        f"Use this skill when the task requires artifacts {', '.join(skill.get('artifacts', [])) or 'N/A'}, "
        f"tools {', '.join(skill.get('tools', [])) or 'N/A'}, "
        f"and operations {', '.join(skill.get('operations', [])) or 'N/A'}.",
        "",
        "## Evidence",
        *ev_lines,
        "",
    ]
    return "\n".join(fm_lines + body) + "\n"

def finalize_task(client: openai.OpenAI, task_id: str, generated_payload: dict[str, Any], ranked_payload: dict[str, Any], final_json_dir: Path, audit_dir: Path, skill_dir: Path, internal_skill_ids: set[str], model: str, temperature: float, max_tokens: int, reasoning_effort: str | None, keep_min: int, keep_max: int, retries: int, retry_sleep_sec: float) -> dict[str, Any]:
    schema = generated_payload.get("schema", {}) or {}
    raw_candidates = list(generated_payload.get("skill_candidates") or [])

    ranked_chunks = list(ranked_payload.get("ranked_chunks") or [])
    evidence_reference = []
    evidence_map = {}
    for ch in ranked_chunks[: min(12, len(ranked_chunks))]:
        item = {
            "chunk_id": ch.get("chunk_id"),
            "title": ch.get("title"),
            "section_title": ch.get("section_title"),
            "source_url": ch.get("source_url"),
            "repo": ch.get("repo"),
            "path": ch.get("path"),
            "retrieval_score": ch.get("retrieval_score"),
            "retrieval_path": ch.get("retrieval_path"),
            "text": _compact(str(ch.get("text", "")))[:1200],
        }
        evidence_reference.append(item)
        evidence_map[str(item["chunk_id"])] = item

    pre_kept, pre_removed = _prefilter_candidates(task_id=task_id, schema=schema, candidates=raw_candidates)
    valid_chunk_ids = set(evidence_map.keys())
    valid_urls = {str(x.get("source_url", "")).strip() for x in evidence_reference if str(x.get("source_url", "")).strip()}

    system_prompt = _system_prompt()
    user_prompt = _user_prompt(task_id, schema, pre_kept, evidence_reference, keep_min, keep_max)

    raw_content = None
    parsed = None
    for attempt in range(retries + 1):
        try:
            raw_content = _chat_completion(
                client=client, model=model, system_prompt=system_prompt, user_prompt=user_prompt,
                temperature=temperature, max_tokens=max_tokens, reasoning_effort=reasoning_effort,
            )
            try:
                parsed = _extract_json(raw_content)
            except Exception:
                repaired = _repair_json_with_model(client=client, model=model, bad_text=raw_content, max_tokens=max_tokens)
                parsed = _extract_json(repaired)
            break
        except Exception as e:
            print(f"[WARN] model request failed task={task_id} attempt={attempt+1}/{retries+1} err={type(e).__name__}: {e}")
            if attempt < retries:
                time.sleep(retry_sleep_sec)
            else:
                if raw_content:
                    raw_dir = audit_dir / "_raw_failed_outputs"
                    raw_dir.mkdir(parents=True, exist_ok=True)
                    _write_text(raw_dir / f"{task_id}.txt", raw_content)
                raise

    if isinstance(parsed, dict):
        reviewed_candidates = parsed.get("final_skill_candidates") or []
        model_removed = parsed.get("removed_candidates") or []
    elif isinstance(parsed, list):
        reviewed_candidates = parsed
        model_removed = []
    else:
        reviewed_candidates = []
        model_removed = []

    normalized = []
    for cand in reviewed_candidates:
        if not isinstance(cand, dict):
            continue
        norm = _normalize_final_candidate(cand, task_id, schema, valid_chunk_ids, valid_urls, internal_skill_ids)
        if norm:
            normalized.append(norm)

    _backfill_urls(normalized, evidence_map)
    normalized = _dedupe_final_candidates(normalized)[:keep_max]

    if len(normalized) < keep_min:
        for cand in pre_kept:
            norm = _normalize_final_candidate(
                {
                    "skill_id": cand.get("skill_id"),
                    "display_name": cand.get("display_name"),
                    "family": (cand.get("family") or [schema.get("family") or "general_problem_solving"])[0],
                    "artifacts": cand.get("artifacts"),
                    "tools": cand.get("tools"),
                    "operations": cand.get("operations"),
                    "granularity": cand.get("granularity"),
                    "summary": cand.get("summary"),
                    "why_kept": "Recovered from prefilter because final reviewer kept too few candidates.",
                    "source_chunk_ids": (cand.get("metadata") or {}).get("source_chunk_ids"),
                    "source_urls": (cand.get("metadata") or {}).get("source_urls"),
                    "confidence": (cand.get("metadata") or {}).get("confidence", 0.5),
                },
                task_id, schema, valid_chunk_ids, valid_urls, internal_skill_ids
            )
            if norm:
                normalized.append(norm)
        _backfill_urls(normalized, evidence_map)
        normalized = _dedupe_final_candidates(normalized)[:keep_max]

    final_payload = {
        "task_id": task_id,
        "generated_at": _now_iso(),
        "schema": schema,
        "summary": {
            "n_input_candidates": len(raw_candidates),
            "n_prefilter_kept": len(pre_kept),
            "n_final_candidates": len(normalized),
            "model": model,
        },
        "final_skill_candidates": normalized,
    }
    _write_json(final_json_dir / f"{task_id}.json", final_payload)

    audit_payload = {
        "task_id": task_id,
        "generated_at": _now_iso(),
        "summary": {
            "n_input_candidates": len(raw_candidates),
            "n_prefilter_removed": len(pre_removed),
            "n_model_removed": len(model_removed) if isinstance(model_removed, list) else 0,
            "n_final_candidates": len(normalized),
        },
        "prefilter_removed": pre_removed,
        "model_removed": model_removed if isinstance(model_removed, list) else [],
    }
    _write_json(audit_dir / f"{task_id}.json", audit_payload)

    task_skill_root = skill_dir / task_id
    for skill in normalized:
        skill_root = task_skill_root / skill["skill_id"]
        _write_text(skill_root / "SKILL.md", _render_skill_md(task_id, skill, evidence_map))
        _write_json(skill_root / "skill.json", skill)

    return final_payload

def main() -> None:
    parser = argparse.ArgumentParser(description="Finalize grounded skill candidates into final JSON + SKILL.md.")
    parser.add_argument("--generated-dir", type=Path, default=DEFAULT_GENERATED_DIR)
    parser.add_argument("--ranked-dir", type=Path, default=DEFAULT_RANKED_DIR)
    parser.add_argument("--final-json-dir", type=Path, default=DEFAULT_FINAL_JSON_DIR)
    parser.add_argument("--audit-dir", type=Path, default=DEFAULT_AUDIT_DIR)
    parser.add_argument("--skill-dir", type=Path, default=DEFAULT_SKILL_DIR)
    parser.add_argument("--manifest-path", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--internal-registry", type=Path, default=DEFAULT_INTERNAL_REGISTRY)
    parser.add_argument("--task-ids", type=str, default=None)

    parser.add_argument("--api-base", type=str, default=DEFAULT_API_BASE)
    parser.add_argument("--api-key", type=str, default=os.getenv("OPENAI_API_KEY"))
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-tokens", type=int, default=2200)
    parser.add_argument("--reasoning-effort", type=str, default=None)
    parser.add_argument("--timeout-sec", type=float, default=120.0)
    parser.add_argument("--connect-timeout-sec", type=float, default=20.0)

    parser.add_argument("--keep-min", type=int, default=3)
    parser.add_argument("--keep-max", type=int, default=5)
    parser.add_argument("--retries", type=int, default=1)
    parser.add_argument("--retry-sleep-sec", type=float, default=2.0)
    args = parser.parse_args()

    if not args.api_key:
        raise SystemExit("Missing API key. Set OPENAI_API_KEY or pass --api-key.")

    timeout = httpx.Timeout(
        timeout=max(1.0, float(args.timeout_sec)),
        connect=max(1.0, float(args.connect_timeout_sec)),
    )
    client = openai.OpenAI(api_key=args.api_key, base_url=args.api_base, timeout=timeout)
    internal_skill_ids = _load_internal_skill_ids(args.internal_registry)

    selected_task_ids = [x.strip() for x in args.task_ids.split(",") if x.strip()] if args.task_ids else None
    gen_files = sorted(args.generated_dir.glob("*.json"))
    if selected_task_ids:
        gen_files = [p for p in gen_files if p.stem in set(selected_task_ids)]
    if not gen_files:
        raise SystemExit(f"No generated candidate files found in {args.generated_dir}")

    manifest = {
        "generated_at": _now_iso(),
        "generated_dir": str(args.generated_dir),
        "ranked_dir": str(args.ranked_dir),
        "final_json_dir": str(args.final_json_dir),
        "skill_dir": str(args.skill_dir),
        "model": args.model,
        "api_base": args.api_base,
        "timeout_sec": max(1.0, float(args.timeout_sec)),
        "connect_timeout_sec": max(1.0, float(args.connect_timeout_sec)),
        "summary": {"n_tasks": 0, "n_total_final_candidates": 0},
        "tasks": [],
    }

    total = 0
    for gen_path in gen_files:
        task_id = gen_path.stem
        ranked_path = args.ranked_dir / f"{task_id}.json"
        if not ranked_path.exists():
            print(f"[WARN] missing ranked payload for task={task_id}, skip")
            continue

        generated_payload = _read_json(gen_path)
        ranked_payload = _read_json(ranked_path)
        result = finalize_task(
            client=client, task_id=task_id, generated_payload=generated_payload, ranked_payload=ranked_payload,
            final_json_dir=args.final_json_dir, audit_dir=args.audit_dir, skill_dir=args.skill_dir,
            internal_skill_ids=internal_skill_ids, model=args.model, temperature=args.temperature,
            max_tokens=max(512, args.max_tokens), reasoning_effort=args.reasoning_effort,
            keep_min=max(1, args.keep_min), keep_max=max(1, args.keep_max),
            retries=max(0, args.retries), retry_sleep_sec=max(0.0, args.retry_sleep_sec),
        )

        n = len(result.get("final_skill_candidates", []))
        total += n
        manifest["tasks"].append({
            "task_id": task_id,
            "final_json_file": str(args.final_json_dir / f"{task_id}.json"),
            "audit_file": str(args.audit_dir / f"{task_id}.json"),
            "skill_dir": str(args.skill_dir / task_id),
            "n_final_candidates": n,
        })
        print(f"[OK] {task_id}: final_candidates={n}")

    manifest["summary"]["n_tasks"] = len(manifest["tasks"])
    manifest["summary"]["n_total_final_candidates"] = total
    _write_json(args.manifest_path, manifest)
    print(json.dumps(manifest["summary"], indent=2, ensure_ascii=False))
    print(f"Manifest: {args.manifest_path}")
    print(f"Final JSON dir: {args.final_json_dir}")
    print(f"Final skill dir: {args.skill_dir}")

if __name__ == "__main__":
    main()
