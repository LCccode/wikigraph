"""Metadata index management for LLM Wiki.

Maintains:
- concepts_index.json: concept name → path + aliases + summary
- source_map.json: SHA256 → original file + generated products
- graph_index.json: lightweight node→community/source mapping
"""

import json
from datetime import datetime, timezone
from pathlib import Path


def _read_json(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _write_json(data: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# --- concepts_index.json ---

def load_concepts_index(meta_dir: Path) -> dict:
    """Load concepts_index.json: {concept_name: {path, aliases, summary, article_count}}."""
    return _read_json(meta_dir / "concepts_index.json")


def update_concepts_index(
    concept_name: str,
    concept_path: str,
    summary: str = "",
    aliases: list[str] | None = None,
    meta_dir: Path | None = None,
    index: dict | None = None,
) -> dict:
    """Add or update a concept in the index."""
    if index is None:
        index = load_concepts_index(meta_dir) if meta_dir else {}

    existing = index.get(concept_name, {})
    existing_aliases = existing.get("aliases", [])
    new_aliases = list(set(existing_aliases + (aliases or [])))

    index[concept_name] = {
        "path": concept_path,
        "aliases": new_aliases,
        "summary": summary or existing.get("summary", ""),
        "article_count": existing.get("article_count", 0) + 1,
    }
    return index


def save_concepts_index(index: dict, meta_dir: Path) -> None:
    _write_json(index, meta_dir / "concepts_index.json")


def match_related_concepts(
    key_terms: list[str],
    concepts_index: dict,
    top_n: int = 5,
    key_terms_llm: list[str] | None = None,
) -> list[str]:
    """Find concepts related to given key terms, matching name + aliases.

    Uses LLM-quality key_terms (key_terms_llm) if available, otherwise
    falls back to regex-extracted key_terms.

    Returns list of concept names (up to top_n).
    """
    # Prefer LLM-quality terms if available
    effective_terms = key_terms_llm if key_terms_llm else key_terms
    scores: dict[str, int] = {}
    terms_lower = [t.lower() for t in effective_terms]

    for concept_name, info in concepts_index.items():
        score = 0
        name_lower = concept_name.lower()
        all_names = [name_lower] + [a.lower() for a in info.get("aliases", [])]

        for term in terms_lower:
            for name in all_names:
                if term in name or name in term:
                    score += 1
                    break

        if score > 0:
            scores[concept_name] = score

    ranked = sorted(scores, key=lambda k: scores[k], reverse=True)
    return ranked[:top_n]


# --- source_map.json ---

def load_source_map(meta_dir: Path) -> dict:
    """Load source_map.json: {sha256: {original_filename, raw_path, generated_pages, ...}}."""
    return _read_json(meta_dir / "source_map.json")


def update_source_map(
    sha256: str,
    original_filename: str,
    raw_path: str,
    generated_pages: list[str],
    uploader: str = "manual",
    meta_dir: Path | None = None,
    source_map: dict | None = None,
) -> dict:
    if source_map is None:
        source_map = load_source_map(meta_dir) if meta_dir else {}

    source_map[sha256] = {
        "original_filename": original_filename,
        "raw_path": raw_path,
        "generated_pages": generated_pages,
        "uploader": uploader,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
    }
    return source_map


def save_source_map(source_map: dict, meta_dir: Path) -> None:
    _write_json(source_map, meta_dir / "source_map.json")


# --- graph_index.json ---

def load_graph_index(graph_dir: Path) -> dict:
    """Load graph_index.json: lightweight node→community/source mapping."""
    return _read_json(graph_dir / "graph_index.json")


def save_graph_index(
    node_to_community: dict[str, int],
    community_to_nodes: dict[int, list[str]],
    node_to_source: dict[str, str],
    articles_since_last_cluster: int,
    graph_dir: Path,
) -> None:
    data = {
        "node_count": len(node_to_community),
        "node_to_community": node_to_community,
        "community_to_nodes": {str(k): v for k, v in community_to_nodes.items()},
        "node_to_source": node_to_source,
        "articles_since_last_cluster": articles_since_last_cluster,
    }
    _write_json(data, graph_dir / "graph_index.json")


# --- index.jsonl (event log) ---

def append_event(index_path: Path, event: dict) -> None:
    """Append an event to raw/index.jsonl."""
    index_path.parent.mkdir(parents=True, exist_ok=True)
    event["at"] = datetime.now(timezone.utc).isoformat()
    with open(index_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


# --- filename_index.json (FIX-A: source_map 反向索引) ---

def load_filename_index(meta_dir: Path) -> dict[str, list[str]]:
    """加载 filename_index.json。文件不存在返回空 dict（冷启动场景）。"""
    return _read_json(meta_dir / "filename_index.json")


def save_filename_index(index: dict[str, list[str]], meta_dir: Path) -> None:
    """原子写入 filename_index.json。"""
    _write_json(index, meta_dir / "filename_index.json")


def rebuild_filename_index(source_map: dict) -> dict[str, list[str]]:
    """冷启动重建：一次性扫 source_map 生成反向索引。

    旧 KB 首次使用时调用一次，此后增量维护。
    复杂度 O(N)。
    """
    index: dict[str, list[str]] = {}
    for sha256, info in source_map.items():
        stem = Path(info.get("original_filename", "") or "").stem
        if stem:
            index.setdefault(stem, []).append(sha256)
    return index


def filename_index_lookup(
    stem: str,
    index: dict[str, list[str]],
    exclude_sha: str | None = None,
) -> list[str]:
    """查询 stem 对应的 sha256 列表，排除 exclude_sha（当前文件自身）。"""
    candidates = index.get(stem, [])
    if exclude_sha:
        candidates = [s for s in candidates if s != exclude_sha]
    return candidates


def filename_index_add(
    stem: str,
    sha256: str,
    index: dict[str, list[str]],
) -> dict[str, list[str]]:
    """向反向索引添加一条记录（ingest 新文件时调用）。幂等。"""
    existing = index.setdefault(stem, [])
    if sha256 not in existing:
        existing.append(sha256)
    return index


def filename_index_remove(
    sha256: str,
    index: dict[str, list[str]],
) -> dict[str, list[str]]:
    """从反向索引中删除一个 sha256（update/trash 旧版本时调用）。

    清空后的 stem key 保留空列表（不删 key，避免并发写问题）。
    """
    for stem_list in index.values():
        if sha256 in stem_list:
            stem_list.remove(sha256)
    return index


# --- ConceptsIndexWriter (FIX-B: per-task 增量写) ---


# --- cost.jsonl ---

def append_cost(logs_dir: Path, op: str, model: str, input_tokens: int, output_tokens: int, took_ms: int = 0) -> None:
    """Append a cost record to logs/cost.jsonl."""
    logs_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "op": op,
        "at": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "took_ms": took_ms,
    }
    with open(logs_dir / "cost.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
