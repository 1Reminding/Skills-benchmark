
#!/usr/bin/env python3
"""Generate grounded external skill candidates from ranked chunks.

Pipeline position
-----------------
08 external query generation
09 external source collection
10 external chunk rerank
11 grounded skill generation   <-- this script

What this script does
---------------------
For each task:
1. Read top reranked evidence chunks from data/external_ranked_chunks/<task>.json
2. Build a grounded evidence pack
3. Call a chat model (OpenAI-compatible API) to synthesize a small set of
   explicit skill candidates
4. Validate / normalize the output against the task schema
5. Write:
   - data/generated_external_skills/<task>.json
   - data/generated_external_skills_manifest.json

Design principles
-----------------
- Do NOT invent skills from scratch
- Every skill must cite evidence chunks
- Keep a small, diverse, analysis-friendly skill pool
- Prefer benchmark-compatible, reusable skill units
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import openai

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_RANKED_DIR = PROJECT_ROOT / "data" / "external_ranked_chunks"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "generated_external_skills"
DEFAULT_MANIFEST = PROJECT_ROOT / "data" / "generated_external_skills_manifest.json"
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

def _read_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

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

def _compact(text: str) -> str:
    return WS_RE.sub(" ", (text or "")).strip()

def _extract_json(text: str) -> Any:
    text = text.strip()
    m = JSON_BLOCK_RE.search(text)
    if m:
        candidate = m.group(1).strip()
        try:
            return json.loads(candidate)
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
            frag = text[start:end+1]
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

def _build_evidence_pack(task_payload: dict[str, Any], max_chunks: int, max_chars_per_chunk: int) -> list[dict[str, Any]]:
    chunks = task_payload.get("ranked_chunks") or []
    evidence = []
    for ch in chunks[:max_chunks]:
        evidence.append({
            "chunk_id": ch.get("chunk_id"),
            "doc_id": ch.get("doc_id"),
            "title": ch.get("title"),
            "section_title": ch.get("section_title"),
            "repo": ch.get("repo"),
            "path": ch.get("path"),
            "source_url": ch.get("source_url"),
            "retrieval_score": ch.get("retrieval_score"),
            "retrieval_path": ch.get("retrieval_path"),
            "text": _compact(str(ch.get("text", "")))[:max_chars_per_chunk],
        })
    return evidence

def _system_prompt() -> str:
    return """You are constructing benchmark-compatible skill candidates from retrieved evidence.

Rules:
1. Do NOT invent skills from scratch.
2. Every skill candidate must be grounded in the provided evidence chunks.
3. Prefer reusable procedural skill units, not task answers.
4. Prefer skills that are method-like:
   - workflow
   - validation
   - extraction
   - transformation
   - aggregation
   - calculation
5. Keep candidates distinct from one another.
6. Avoid generic product/platform names unless they correspond to a real reusable method.
7. Output strict JSON only.
"""

def _user_prompt(task_id: str, schema: dict[str, Any], evidence: list[dict[str, Any]], n_candidates: int) -> str:
    prompt = {
        "task_id": task_id,
        "task_schema": schema,
        "goal": (
            "Synthesize a small set of grounded external skill candidates for this task. "
            "Candidates should be benchmark-compatible skill units, not final task solutions."
        ),
        "required_output_schema": {
            "task_id": task_id,
            "skill_candidates": [
                {
                    "skill_id": "string, lowercase kebab-case, concise and method-oriented",
                    "display_name": "string",
                    "family": "one controlled family label",
                    "artifacts": ["list of controlled artifact labels"],
                    "tools": ["list of controlled tool labels"],
                    "operations": ["list of controlled operation labels"],
                    "granularity": "atomic|compositional|generic",
                    "summary": "1-3 sentence grounded summary",
                    "why_distinct": "why this differs from the other candidates",
                    "source_chunk_ids": ["list of evidence chunk ids used"],
                    "source_urls": ["list of source urls used"],
                    "confidence": "0-1 float"
                }
            ]
        },
        "constraints": [
            f"Generate at most {n_candidates} candidates.",
            "Generate at least 3 candidates if the evidence supports it.",
            "family/tools/artifacts/operations must stay within the task schema neighborhood.",
            "If evidence is weak, generate fewer candidates rather than hallucinating.",
            "Prefer candidates that are distinct in strategy or emphasis.",
            "Do not output any text outside JSON."
        ],
        "evidence_chunks": evidence,
    }
    return json.dumps(prompt, ensure_ascii=False, indent=2)

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

    # 先尝试 json_object
    try:
        resp = client.chat.completions.create(
            **kwargs,
            response_format={"type": "json_object"},
        )
        return resp.choices[0].message.content
    except Exception:
        pass

    # 再尝试去掉 response_format
    try:
        resp = client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content
    except Exception:
        # 最后去掉 reasoning_effort 再试一次
        kwargs.pop("reasoning_effort", None)
        resp = client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content

def _repair_json_with_model(
    client: openai.OpenAI,
    model: str,
    bad_text: str,
    max_tokens: int = 2200,
) -> str:
    repair_prompt = (
        "请把下面这段模型输出修复成严格合法的 JSON。"
        "不要添加解释，不要使用 markdown 代码块，不要省略字段。"
        "只输出修复后的 JSON。\n\n"
        "原始内容如下：\n"
        f"{bad_text}"
    )

    # 先尝试 json_object
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
        pass

    # 再退化
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
    
def _normalize_candidate(
    candidate: dict[str, Any],
    task_id: str,
    schema: dict[str, Any],
    valid_chunk_ids: set[str],
    valid_urls: set[str],
    internal_skill_ids: set[str],
) -> dict[str, Any] | None:
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

    why_distinct = _compact(str(candidate.get("why_distinct") or ""))
    source_chunk_ids = [x for x in _safe_list_str(candidate.get("source_chunk_ids")) if x in valid_chunk_ids]
    source_urls = [x for x in _safe_list_str(candidate.get("source_urls")) if x in valid_urls]

    if not source_chunk_ids:
        return None

    try:
        confidence = float(candidate.get("confidence", 0.5))
    except Exception:
        confidence = 0.5
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
        "why_distinct": why_distinct,
        "metadata": {
            "task_id": task_id,
            "source_chunk_ids": source_chunk_ids,
            "source_urls": source_urls,
            "confidence": round(confidence, 3),
            "generated_at": _now_iso(),
            "generator": "11_generate_skill_candidates.vendor_compatible.py",
        },
    }

def _dedupe_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
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

def _backfill_urls(candidates: list[dict[str, Any]], evidence: list[dict[str, Any]]) -> None:
    chunk_to_url = {str(x["chunk_id"]): str(x.get("source_url", "")) for x in evidence}
    for cand in candidates:
        urls = set(cand["metadata"].get("source_urls", []))
        for cid in cand["metadata"].get("source_chunk_ids", []):
            url = chunk_to_url.get(cid)
            if url:
                urls.add(url)
        cand["metadata"]["source_urls"] = sorted(urls)

def generate_for_task(
    client: openai.OpenAI,
    task_payload: dict[str, Any],
    task_id: str,
    output_dir: Path,
    model: str,
    internal_skill_ids: set[str],
    max_input_chunks: int,
    max_chars_per_chunk: int,
    n_candidates: int,
    temperature: float,
    max_tokens: int,
    reasoning_effort: str | None,
    retries: int,
    retry_sleep_sec: float,
) -> dict[str, Any]:
    schema = task_payload.get("schema", {}) or {}
    evidence = _build_evidence_pack(task_payload, max_chunks=max_input_chunks, max_chars_per_chunk=max_chars_per_chunk)
    if not evidence:
        payload = {
            "task_id": task_id,
            "generated_at": _now_iso(),
            "schema": schema,
            "summary": {"n_evidence_chunks": 0, "n_generated_candidates": 0},
            "skill_candidates": [],
        }
        _write_json(output_dir / f"{task_id}.json", payload)
        return payload

    valid_chunk_ids = {str(x["chunk_id"]) for x in evidence}
    valid_urls = {str(x["source_url"]) for x in evidence if str(x.get("source_url", "")).strip()}

    system_prompt = _system_prompt()
    user_prompt = _user_prompt(task_id=task_id, schema=schema, evidence=evidence, n_candidates=n_candidates)

    parsed = None
    raw_content = None

    for attempt in range(retries + 1):
        try:
            raw_content = _chat_completion(
                client=client,
                model=model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                reasoning_effort=reasoning_effort,
            )
            try:
                parsed = _extract_json(raw_content)
            except Exception:
                repaired = _repair_json_with_model(
                    client=client,
                    model=model,
                    bad_text=raw_content,
                    max_tokens=max_tokens,
                )
                parsed = _extract_json(repaired)
            break
        except Exception:
            if attempt < retries:
                time.sleep(retry_sleep_sec)
            else:
                # 保存原始输出，方便排查
                if raw_content:
                    raw_dir = output_dir / "_raw_failed_outputs"
                    raw_dir.mkdir(parents=True, exist_ok=True)
                    (raw_dir / f"{task_id}.txt").write_text(raw_content, encoding="utf-8")
                raise

    raw_candidates = []
    if isinstance(parsed, dict):
        raw_candidates = parsed.get("skill_candidates") or []
    elif isinstance(parsed, list):
        raw_candidates = parsed

    normalized = []
    for cand in raw_candidates:
        if not isinstance(cand, dict):
            continue
        norm = _normalize_candidate(
            candidate=cand,
            task_id=task_id,
            schema=schema,
            valid_chunk_ids=valid_chunk_ids,
            valid_urls=valid_urls,
            internal_skill_ids=internal_skill_ids,
        )
        if norm:
            normalized.append(norm)

    _backfill_urls(normalized, evidence)
    normalized = _dedupe_candidates(normalized)[:n_candidates]

    payload = {
        "task_id": task_id,
        "generated_at": _now_iso(),
        "schema": schema,
        "summary": {
            "n_evidence_chunks": len(evidence),
            "n_generated_candidates": len(normalized),
            "model": model,
        },
        "evidence_preview": evidence[: min(8, len(evidence))],
        "skill_candidates": normalized,
    }
    _write_json(output_dir / f"{task_id}.json", payload)
    return payload

def main() -> None:
    parser = argparse.ArgumentParser(description="Generate grounded skill candidates from reranked chunks.")
    parser.add_argument("--ranked-dir", type=Path, default=DEFAULT_RANKED_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--manifest-path", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--task-ids", type=str, default=None)
    parser.add_argument("--internal-registry", type=Path, default=DEFAULT_INTERNAL_REGISTRY)

    parser.add_argument("--api-base", type=str, default=DEFAULT_API_BASE)
    parser.add_argument("--api-key", type=str, default=os.getenv("OPENAI_API_KEY"))
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL)
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--max-tokens", type=int, default=2200)
    parser.add_argument("--reasoning-effort", type=str, default=None)

    parser.add_argument("--max-input-chunks", type=int, default=10)
    parser.add_argument("--max-chars-per-chunk", type=int, default=1200)
    parser.add_argument("--n-candidates", type=int, default=5)
    parser.add_argument("--retries", type=int, default=1)
    parser.add_argument("--retry-sleep-sec", type=float, default=2.0)
    args = parser.parse_args()

    if not args.api_key:
        raise SystemExit("Missing API key. Set OPENAI_API_KEY or pass --api-key.")

    client = openai.OpenAI(
        api_key=args.api_key,
        base_url=args.api_base,
    )

    selected_task_ids = [x.strip() for x in args.task_ids.split(",") if x.strip()] if args.task_ids else None
    internal_skill_ids = _load_internal_skill_ids(args.internal_registry)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    task_files = sorted(args.ranked_dir.glob("*.json"))
    if selected_task_ids:
        task_files = [p for p in task_files if p.stem in set(selected_task_ids)]
    if not task_files:
        raise SystemExit(f"No ranked chunk files found in {args.ranked_dir}")

    manifest = {
        "generated_at": _now_iso(),
        "ranked_dir": str(args.ranked_dir),
        "output_dir": str(args.output_dir),
        "model": args.model,
        "api_base": args.api_base,
        "summary": {
            "n_tasks": 0,
            "n_total_candidates": 0,
        },
        "tasks": [],
    }

    total_candidates = 0
    for path in task_files:
        task_id = path.stem
        task_payload = _read_json(path)
        result = generate_for_task(
            client=client,
            task_payload=task_payload,
            task_id=task_id,
            output_dir=args.output_dir,
            model=args.model,
            internal_skill_ids=internal_skill_ids,
            max_input_chunks=max(1, args.max_input_chunks),
            max_chars_per_chunk=max(200, args.max_chars_per_chunk),
            n_candidates=max(1, args.n_candidates),
            temperature=args.temperature,
            max_tokens=max(512, args.max_tokens),
            reasoning_effort=args.reasoning_effort,
            retries=max(0, args.retries),
            retry_sleep_sec=max(0.0, args.retry_sleep_sec),
        )
        n = len(result.get("skill_candidates", []))
        total_candidates += n
        manifest["tasks"].append({
            "task_id": task_id,
            "output_file": str(args.output_dir / f"{task_id}.json"),
            "n_generated_candidates": n,
        })
        print(f"[OK] {task_id}: generated_candidates={n}")

    manifest["summary"]["n_tasks"] = len(manifest["tasks"])
    manifest["summary"]["n_total_candidates"] = total_candidates
    _write_json(args.manifest_path, manifest)
    print(json.dumps(manifest["summary"], indent=2, ensure_ascii=False))
    print(f"Manifest: {args.manifest_path}")
    print(f"Generated skills dir: {args.output_dir}")

if __name__ == "__main__":
    main()
