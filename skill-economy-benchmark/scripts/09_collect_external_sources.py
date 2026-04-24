
#!/usr/bin/env python3
"""Query-driven external source collection for skill expansion."""

from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_QUERY_MANIFEST = PROJECT_ROOT / "data" / "external_queries.json"
DEFAULT_QUERY_DIR = PROJECT_ROOT / "data" / "external_queries"
DEFAULT_SOURCE_POLICY = PROJECT_ROOT / "data" / "source_policy.json"

DEFAULT_OUTPUT_HITS = PROJECT_ROOT / "data" / "external_source_hits.json"
DEFAULT_OUTPUT_DOCS = PROJECT_ROOT / "data" / "external_source_docs.json"
DEFAULT_OUTPUT_CHUNKS = PROJECT_ROOT / "data" / "external_corpus_chunks.jsonl"
DEFAULT_CACHE_DIR = PROJECT_ROOT / "external_cache"

TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_\-/.+]*")
MD_HEADING_RE = re.compile(r"^#{1,6}\s+(.+)$", re.MULTILINE)
HTML_H_RE = re.compile(r"<h[1-6][^>]*>(.*?)</h[1-6]>", re.IGNORECASE | re.DOTALL)
HTML_TAG_RE = re.compile(r"<[^>]+>")
SCRIPT_STYLE_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
CODE_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
WS_RE = re.compile(r"\s+")

SUPPORTED_DOC_EXTS = {".md", ".rst", ".txt", ".html", ".htm"}
FAVORED_PATH_HINTS = ("readme", "docs/", "examples/", "example/", "guide", "tutorial", "howto", "how-to", "cookbook")
TRUSTED_DOC_PATH_HINTS = ("docs/", "examples/", "example/", "guides/", "tutorials/", "cookbook/")
MAX_HTML_CHARS = 300_000

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

@dataclass
class SearchHit:
    task_id: str
    query_id: str
    query_text: str
    provider: str
    source_type: str
    title: str
    url: str
    domain: str
    score_hint: float
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass
class SourceDoc:
    doc_id: str
    source_type: str
    task_ids: list[str]
    query_ids: list[str]
    title: str
    section_title: str
    source_url: str
    domain: str
    repo: str
    path: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass
class CorpusChunk:
    chunk_id: str
    doc_id: str
    task_ids: list[str]
    query_ids: list[str]
    title: str
    section_title: str
    source_url: str
    domain: str
    repo: str
    path: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)

def _read_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

def _now_iso() -> str:
    return datetime.now().isoformat()

def _normalize_token(token: str) -> str:
    token = token.lower().strip().replace("/", "_")
    if token.endswith("s") and len(token) > 4:
        token = token[:-1]
    return token

def _tokenize(text: str) -> set[str]:
    return {_normalize_token(t) for t in TOKEN_RE.findall(text or "") if len(t) >= 2}

def _sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()

def _domain_of_url(url: str) -> str:
    try:
        return urllib.parse.urlparse(url).netloc.lower()
    except Exception:
        return ""

def _allowed_domains_for_task(task_plan: dict[str, Any], source_policy: dict[str, Any]) -> list[str]:
    allowed = set()
    schema = task_plan.get("schema", {}) or {}
    family = str(schema.get("family") or "general_problem_solving")
    allowed |= set(source_policy.get("global_allowed_domains", []))
    allowed |= set((source_policy.get("domains_by_family", {}) or {}).get(family, []))
    allowed |= set(((task_plan.get("source_policy") or {}).get("allowed_domains") or []))
    return sorted(x for x in allowed if x)

def _url_allowed(url: str, allowed_domains: list[str]) -> bool:
    domain = _domain_of_url(url)
    if not domain:
        return False
    return any(domain == d or domain.endswith("." + d) or d in domain for d in allowed_domains)

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

def _load_source_policy(path: Path | None) -> dict[str, Any]:
    if path and path.exists():
        return _read_json(path)
    return DEFAULT_SOURCE_POLICY_DATA

def _http_get_json(url: str, headers: dict[str, str] | None = None, timeout: int = 30) -> Any:
    req = urllib.request.Request(url, method="GET")
    req.add_header("User-Agent", "skill-economy-benchmark/09_collect_external_sources")
    req.add_header("Accept", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))

def _http_get_text(url: str, headers: dict[str, str] | None = None, timeout: int = 30) -> str:
    req = urllib.request.Request(url, method="GET")
    req.add_header("User-Agent", "skill-economy-benchmark/09_collect_external_sources")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw.decode("latin-1", errors="replace")

def _github_headers(token: str | None) -> dict[str, str]:
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers

def _github_search_repositories(query: str, token: str | None, per_page: int = 5) -> list[dict[str, Any]]:
    q = urllib.parse.quote(query)
    url = f"https://api.github.com/search/repositories?q={q}&sort=stars&order=desc&per_page={per_page}"
    data = _http_get_json(url, headers=_github_headers(token))
    return [x for x in data.get("items", []) if isinstance(x, dict)]

def _github_repo_info(owner: str, repo: str, token: str | None) -> dict[str, Any]:
    return _http_get_json(f"https://api.github.com/repos/{owner}/{repo}", headers=_github_headers(token))

def _github_recursive_tree(owner: str, repo: str, ref: str, token: str | None) -> list[dict[str, Any]]:
    ref_q = urllib.parse.quote(ref)
    data = _http_get_json(f"https://api.github.com/repos/{owner}/{repo}/git/trees/{ref_q}?recursive=1", headers=_github_headers(token))
    return [x for x in data.get("tree", []) if isinstance(x, dict)]

def _github_contents_file(owner: str, repo: str, path: str, ref: str, token: str | None) -> str:
    path_q = urllib.parse.quote(path.strip("/"))
    ref_q = urllib.parse.quote(ref)
    data = _http_get_json(f"https://api.github.com/repos/{owner}/{repo}/contents/{path_q}?ref={ref_q}", headers=_github_headers(token))
    content_b64 = str(data.get("content", "")).strip().replace("\n", "")
    return base64.b64decode(content_b64).decode("utf-8", errors="replace") if content_b64 else ""

def _score_repo_path(path: str) -> tuple[int, int]:
    low = path.lower()
    favored = sum(1 for hint in FAVORED_PATH_HINTS if hint in low)
    trusted = sum(1 for hint in TRUSTED_DOC_PATH_HINTS if hint in low)
    return (trusted, favored)

def _select_repo_doc_paths(tree: list[dict[str, Any]], max_docs_per_repo: int) -> list[str]:
    candidates = []
    for node in tree:
        if node.get("type") != "blob":
            continue
        path = str(node.get("path", "")).strip()
        if not path:
            continue
        suffix = Path(path).suffix.lower()
        if suffix not in SUPPORTED_DOC_EXTS:
            continue
        low = path.lower()
        if any(x in low for x in ("node_modules/", "/dist/", "/build/", "/vendor/")):
            continue
        if low.endswith("license") or low.endswith("license.md"):
            continue
        candidates.append(path)
    ranked = sorted(candidates, key=lambda p: (-_score_repo_path(p)[0], -_score_repo_path(p)[1], 0 if "readme" in p.lower() else 1, len(p), p))
    return ranked[:max_docs_per_repo]

def _brave_headers(api_key: str) -> dict[str, str]:
    return {"Accept": "application/json", "X-Subscription-Token": api_key}

def _brave_web_search(query: str, api_key: str, count: int = 5) -> list[dict[str, Any]]:
    q = urllib.parse.quote(query)
    data = _http_get_json(f"https://api.search.brave.com/res/v1/web/search?q={q}&count={count}", headers=_brave_headers(api_key))
    return [x for x in ((data.get("web") or {}).get("results") or []) if isinstance(x, dict)]

def _clean_markdown_text(text: str) -> str:
    text = FRONTMATTER_RE.sub("", text or "")
    text = CODE_FENCE_RE.sub(" ", text)
    return text.replace("\r\n", "\n")

def _clean_html_text(text: str) -> str:
    text = text[:MAX_HTML_CHARS]
    text = SCRIPT_STYLE_RE.sub(" ", text)
    text = html.unescape(text)
    text = HTML_TAG_RE.sub(" ", text)
    return text.replace("\r\n", "\n")

def _split_markdown_sections(text: str, fallback_title: str) -> list[tuple[str, str]]:
    cleaned = _clean_markdown_text(text)
    headings = list(MD_HEADING_RE.finditer(cleaned))
    if not headings:
        body = WS_RE.sub(" ", cleaned).strip()
        return [(fallback_title, body)] if body else []
    sections = []
    for i, m in enumerate(headings):
        title = m.group(1).strip()
        start = m.end()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(cleaned)
        body = WS_RE.sub(" ", cleaned[start:end]).strip()
        if len(body) >= 120:
            sections.append((title, body))
    return sections or ([(fallback_title, WS_RE.sub(" ", cleaned).strip())] if cleaned.strip() else [])

def _split_html_sections(text: str, fallback_title: str) -> list[tuple[str, str]]:
    cleaned = _clean_html_text(text)
    headings = list(HTML_H_RE.finditer(text[:MAX_HTML_CHARS]))
    if not headings:
        paras = [WS_RE.sub(" ", p).strip() for p in cleaned.split("\n\n")]
        paras = [p for p in paras if len(p) >= 120]
        return [(fallback_title, p) for p in paras[:12]] or ([(fallback_title, cleaned[:2000])] if cleaned.strip() else [])
    sections = []
    raw = text[:MAX_HTML_CHARS]
    for i, m in enumerate(headings):
        title = WS_RE.sub(" ", html.unescape(HTML_TAG_RE.sub(" ", m.group(1)))).strip() or fallback_title
        start = m.end()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(raw)
        body = WS_RE.sub(" ", _clean_html_text(raw[start:end])).strip()
        if len(body) >= 120:
            sections.append((title, body))
    return sections or ([(fallback_title, WS_RE.sub(" ", cleaned).strip()[:2000])] if cleaned.strip() else [])

def _chunk_text(section_text: str, target_chars: int = 1200, overlap_chars: int = 150) -> list[str]:
    text = WS_RE.sub(" ", section_text).strip()
    if len(text) <= target_chars:
        return [text] if text else []
    chunks = []
    start = 0
    while start < len(text):
        end = min(len(text), start + target_chars)
        if end < len(text):
            cut = text.rfind(". ", start, end)
            if cut != -1 and cut - start > 400:
                end = cut + 1
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(end - overlap_chars, start + 1)
    return chunks

def _repo_hit_to_search_hit(task_id: str, query_id: str, query_text: str, repo_item: dict[str, Any]) -> SearchHit:
    full_name = str(repo_item.get("full_name", "")).strip()
    url = str(repo_item.get("html_url", "")).strip()
    stars = float(repo_item.get("stargazers_count") or 0)
    score_hint = min(5.0, 1.0 + stars / 5000.0)
    return SearchHit(
        task_id=task_id, query_id=query_id, query_text=query_text, provider="github_repo_search",
        source_type="github_repo", title=full_name or str(repo_item.get("name", "")).strip(),
        url=url, domain=_domain_of_url(url), score_hint=round(score_hint, 3),
        metadata={"repo_full_name": full_name, "description": repo_item.get("description"), "stars": repo_item.get("stargazers_count"), "default_branch": repo_item.get("default_branch")},
    )

def _brave_hit_to_search_hit(task_id: str, query_id: str, query_text: str, item: dict[str, Any]) -> SearchHit:
    url = str(item.get("url", "")).strip()
    return SearchHit(
        task_id=task_id, query_id=query_id, query_text=query_text, provider="brave_search",
        source_type="web_page", title=str(item.get("title", "")).strip() or url, url=url,
        domain=_domain_of_url(url), score_hint=1.0, metadata={"description": item.get("description")},
    )

def _gather_search_hits(query_plans: dict[str, dict[str, Any]], source_policy: dict[str, Any], github_token: str | None, brave_api_key: str | None, max_results_per_query: int, max_queries_per_task: int, sleep_sec: float) -> list[SearchHit]:
    all_hits = []
    for task_id, plan in query_plans.items():
        allowed = _allowed_domains_for_task(plan, source_policy)
        queries = [q for q in (plan.get("queries") or []) if isinstance(q, dict)][:max_queries_per_task]
        print(f"[INFO] task={task_id} queries={len(queries)} allowed_domains={len(allowed)}")
        for q in queries:
            query_id = str(q.get("query_id", ""))
            query_text = str(q.get("text", "")).strip()
            if not query_text:
                continue
            print(f"[INFO]   search query: {query_id} | {query_text}")
            try:
                gh_items = _github_search_repositories(query_text, github_token, per_page=max_results_per_query)
            except Exception as e:
                print(f"[WARN] GitHub repo search failed for {query_id}: {e}")
                gh_items = []
            kept_gh = 0
            for item in gh_items:
                url = str(item.get("html_url", "")).strip()
                if url and _url_allowed(url, allowed):
                    all_hits.append(_repo_hit_to_search_hit(task_id, query_id, query_text, item))
                    kept_gh += 1
            print(f"[INFO]     github_repo_hits={kept_gh}")
            if brave_api_key:
                try:
                    web_items = _brave_web_search(query_text, brave_api_key, count=max_results_per_query)
                except Exception as e:
                    print(f"[WARN] Brave search failed for {query_id}: {e}")
                    web_items = []
                kept_web = 0
                for item in web_items:
                    url = str(item.get("url", "")).strip()
                    if url and _url_allowed(url, allowed):
                        all_hits.append(_brave_hit_to_search_hit(task_id, query_id, query_text, item))
                        kept_web += 1
                print(f"[INFO]     brave_web_hits={kept_web}")
            if sleep_sec > 0:
                time.sleep(sleep_sec)
    deduped = {}
    for hit in all_hits:
        key = (hit.task_id, hit.query_id, hit.provider, hit.url)
        if key not in deduped:
            deduped[key] = hit
    hits = list(deduped.values())
    hits.sort(key=lambda x: (x.task_id, x.query_id, -x.score_hint, x.url))
    return hits

def _group_hits_by_source(hits: list[SearchHit]) -> dict[str, list[SearchHit]]:
    grouped = {}
    for hit in hits:
        grouped.setdefault(hit.url, []).append(hit)
    return grouped

def _fetch_github_repo_docs(repo_full_name: str, task_refs: list[dict[str, str]], github_token: str | None, max_docs_per_repo: int, cache_dir: Path) -> list[SourceDoc]:
    owner, repo = repo_full_name.split("/", 1)
    info = _github_repo_info(owner, repo, github_token)
    default_branch = str(info.get("default_branch") or "main")
    tree = _github_recursive_tree(owner, repo, default_branch, github_token)
    paths = _select_repo_doc_paths(tree, max_docs_per_repo=max_docs_per_repo)
    docs = []
    print(f"[INFO]   fetch repo docs: {repo_full_name} paths={len(paths)} branch={default_branch}")
    for path in paths:
        try:
            content = _github_contents_file(owner, repo, path, default_branch, github_token)
        except Exception as e:
            print(f"[WARN]     failed file {repo_full_name}:{path} -> {e}")
            continue
        if not content.strip():
            continue
        doc_id = _sha1(f"github_repo::{repo_full_name}::{path}")
        _write_json(cache_dir / "docs" / f"{doc_id}.json", {
            "doc_id": doc_id, "fetched_at": _now_iso(), "source_type": "github_repo_doc",
            "repo": repo_full_name, "path": path, "default_branch": default_branch,
            "source_url": f"https://github.com/{repo_full_name}/blob/{default_branch}/{path}",
            "text": content, "task_refs": task_refs,
        })
        docs.append(SourceDoc(
            doc_id=doc_id, source_type="github_repo_doc", task_ids=sorted({x["task_id"] for x in task_refs}),
            query_ids=sorted({x["query_id"] for x in task_refs}), title=f"{repo_full_name}:{path}",
            section_title=Path(path).stem, source_url=f"https://github.com/{repo_full_name}/blob/{default_branch}/{path}",
            domain="github.com", repo=repo_full_name, path=path, text=content,
            metadata={"default_branch": default_branch, "task_refs": task_refs},
        ))
    return docs

def _fetch_web_doc(url: str, task_refs: list[dict[str, str]], cache_dir: Path) -> SourceDoc | None:
    try:
        text = _http_get_text(url, timeout=25)
    except Exception as e:
        print(f"[WARN]   failed web doc {url} -> {e}")
        return None
    if not text.strip():
        return None
    doc_id = _sha1(f"web::{url}")
    _write_json(cache_dir / "docs" / f"{doc_id}.json", {
        "doc_id": doc_id, "fetched_at": _now_iso(), "source_type": "web_page",
        "source_url": url, "text": text, "task_refs": task_refs,
    })
    return SourceDoc(
        doc_id=doc_id, source_type="web_page", task_ids=sorted({x["task_id"] for x in task_refs}),
        query_ids=sorted({x["query_id"] for x in task_refs}), title=url,
        section_title=Path(urllib.parse.urlparse(url).path).name or "page",
        source_url=url, domain=_domain_of_url(url), repo="", path=urllib.parse.urlparse(url).path,
        text=text, metadata={"task_refs": task_refs},
    )

def _fetch_documents_from_hits(hits: list[SearchHit], github_token: str | None, cache_dir: Path, max_docs_per_repo: int, max_docs_per_task: int) -> list[SourceDoc]:
    grouped = _group_hits_by_source(hits)
    docs = []
    task_doc_counts: dict[str, int] = {}
    for url, url_hits in grouped.items():
        task_refs = [{"task_id": h.task_id, "query_id": h.query_id} for h in url_hits]
        touched_tasks = sorted({h.task_id for h in url_hits})
        if all(task_doc_counts.get(t, 0) >= max_docs_per_task for t in touched_tasks):
            continue
        provider = url_hits[0].provider
        if provider == "github_repo_search":
            repo_full_name = str(url_hits[0].metadata.get("repo_full_name", "")).strip()
            if not repo_full_name or "/" not in repo_full_name:
                continue
            repo_docs = _fetch_github_repo_docs(repo_full_name, task_refs, github_token, max_docs_per_repo, cache_dir)
            for doc in repo_docs:
                if any(task_doc_counts.get(t, 0) < max_docs_per_task for t in doc.task_ids):
                    docs.append(doc)
                    for t in doc.task_ids:
                        task_doc_counts[t] = task_doc_counts.get(t, 0) + 1
        elif provider == "brave_search":
            doc = _fetch_web_doc(url, task_refs, cache_dir)
            if doc and any(task_doc_counts.get(t, 0) < max_docs_per_task for t in doc.task_ids):
                docs.append(doc)
                for t in doc.task_ids:
                    task_doc_counts[t] = task_doc_counts.get(t, 0) + 1
    return docs

def _doc_to_chunks(doc: SourceDoc) -> list[CorpusChunk]:
    suffix = Path(doc.path).suffix.lower()
    sections = _split_html_sections(doc.text, doc.section_title or doc.title) if suffix in {".html", ".htm"} else _split_markdown_sections(doc.text, doc.section_title or doc.title)
    chunks = []
    for sec_idx, (sec_title, sec_body) in enumerate(sections):
        for chunk_idx, chunk_text in enumerate(_chunk_text(sec_body)):
            if len(chunk_text) < 120:
                continue
            chunk_id = _sha1(f"{doc.doc_id}::{sec_idx}::{chunk_idx}")
            chunks.append(CorpusChunk(
                chunk_id=chunk_id, doc_id=doc.doc_id, task_ids=doc.task_ids, query_ids=doc.query_ids,
                title=doc.title, section_title=sec_title, source_url=doc.source_url, domain=doc.domain,
                repo=doc.repo, path=doc.path, text=chunk_text,
                metadata={"source_type": doc.source_type, "sec_idx": sec_idx, "chunk_idx": chunk_idx},
            ))
    return chunks

def build_external_source_collection(query_manifest: Path, query_dir: Path, source_policy_path: Path | None, output_hits: Path, output_docs: Path, output_chunks: Path, cache_dir: Path, task_ids: list[str] | None, github_token: str | None, brave_api_key: str | None, max_results_per_query: int, max_queries_per_task: int, max_docs_per_repo: int, max_docs_per_task: int, sleep_sec: float) -> dict[str, Any]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "docs").mkdir(parents=True, exist_ok=True)
    source_policy = _load_source_policy(source_policy_path)
    query_plans = _load_query_plans(query_manifest, query_dir, task_ids)
    if not query_plans:
        raise SystemExit("No query plans found. Run 08_generate_external_queries.py first.")
    hits = _gather_search_hits(query_plans, source_policy, github_token, brave_api_key, max_results_per_query, max_queries_per_task, sleep_sec)
    print(f"[INFO] total_search_hits={len(hits)}")
    docs = _fetch_documents_from_hits(hits, github_token, cache_dir, max_docs_per_repo, max_docs_per_task)
    print(f"[INFO] fetched_docs={len(docs)}")
    doc_by_url = {}
    for doc in docs:
        if doc.source_url not in doc_by_url:
            doc_by_url[doc.source_url] = doc
        else:
            prev = doc_by_url[doc.source_url]
            prev.task_ids = sorted(set(prev.task_ids) | set(doc.task_ids))
            prev.query_ids = sorted(set(prev.query_ids) | set(doc.query_ids))
    dedup_docs = list(doc_by_url.values())
    chunks = []
    for doc in dedup_docs:
        chunks.extend(_doc_to_chunks(doc))
    print(f"[INFO] built_chunks={len(chunks)}")
    _write_json(output_hits, {"generated_at": _now_iso(), "summary": {"n_hits": len(hits), "n_tasks": len(query_plans)}, "hits": [asdict(h) for h in hits]})
    _write_json(output_docs, {"generated_at": _now_iso(), "summary": {"n_docs": len(dedup_docs)}, "docs": [asdict(d) for d in dedup_docs]})
    _write_jsonl(output_chunks, [asdict(c) for c in chunks])
    cache_manifest = {
        "generated_at": _now_iso(),
        "query_manifest": str(query_manifest),
        "query_dir": str(query_dir),
        "source_policy_path": str(source_policy_path) if source_policy_path and source_policy_path.exists() else None,
        "task_ids": sorted(query_plans.keys()),
        "summary": {"n_hits": len(hits), "n_docs": len(dedup_docs), "n_chunks": len(chunks)},
        "outputs": {"hits": str(output_hits), "docs": str(output_docs), "chunks": str(output_chunks)},
    }
    _write_json(cache_dir / "manifest.json", cache_manifest)
    return cache_manifest

def main() -> None:
    parser = argparse.ArgumentParser(description="Collect external docs from task-aware queries.")
    parser.add_argument("--query-manifest", type=Path, default=DEFAULT_QUERY_MANIFEST)
    parser.add_argument("--query-dir", type=Path, default=DEFAULT_QUERY_DIR)
    parser.add_argument("--source-policy", type=Path, default=DEFAULT_SOURCE_POLICY)
    parser.add_argument("--output-hits", type=Path, default=DEFAULT_OUTPUT_HITS)
    parser.add_argument("--output-docs", type=Path, default=DEFAULT_OUTPUT_DOCS)
    parser.add_argument("--output-chunks", type=Path, default=DEFAULT_OUTPUT_CHUNKS)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--task-ids", type=str, default=None)
    parser.add_argument("--max-results-per-query", type=int, default=5)
    parser.add_argument("--max-queries-per-task", type=int, default=8)
    parser.add_argument("--max-docs-per-repo", type=int, default=6)
    parser.add_argument("--max-docs-per-task", type=int, default=40)
    parser.add_argument("--sleep-sec", type=float, default=0.2)
    parser.add_argument("--github-token", type=str, default=None)
    parser.add_argument("--brave-api-key", type=str, default=None)
    args = parser.parse_args()
    selected_task_ids = [x.strip() for x in args.task_ids.split(",") if x.strip()] if args.task_ids else None
    github_token = args.github_token or os.getenv("GITHUB_TOKEN")
    brave_api_key = args.brave_api_key or os.getenv("BRAVE_API_KEY")
    result = build_external_source_collection(
        query_manifest=args.query_manifest, query_dir=args.query_dir, source_policy_path=args.source_policy,
        output_hits=args.output_hits, output_docs=args.output_docs, output_chunks=args.output_chunks,
        cache_dir=args.cache_dir, task_ids=selected_task_ids, github_token=github_token,
        brave_api_key=brave_api_key, max_results_per_query=max(1, args.max_results_per_query),
        max_queries_per_task=max(1, args.max_queries_per_task), max_docs_per_repo=max(1, args.max_docs_per_repo),
        max_docs_per_task=max(1, args.max_docs_per_task), sleep_sec=max(0.0, args.sleep_sec),
    )
    print(json.dumps(result["summary"], indent=2, ensure_ascii=False))
    print(f"Written hits: {args.output_hits}")
    print(f"Written docs: {args.output_docs}")
    print(f"Written chunks: {args.output_chunks}")
    print(f"Cache manifest: {args.cache_dir / 'manifest.json'}")

if __name__ == "__main__":
    main()
