"""SHA256 incremental cache for LLM Wiki.

Caches extraction and compilation results per file to avoid redundant LLM calls.
Uses frontmatter-only hashing for markdown: metadata changes don't invalidate cache.
"""

import hashlib
import json
from pathlib import Path


def _body_content(raw: bytes) -> bytes:
    """Strip YAML frontmatter from markdown, return only body for hashing.

    If the file starts with '---', skip everything until the closing '---'.
    This ensures that changing frontmatter tags (region, topic, etc.)
    does NOT invalidate the cache — only body content changes do.
    """
    text = raw.decode("utf-8", errors="replace")
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            return text[end + 4:].encode("utf-8")
    return raw


def file_hash(path: Path, root: Path | None = None) -> str:
    """Compute cache key: SHA256 of (body content + relative path).

    For .md files, only the body (below frontmatter) is hashed.
    The relative path is included so the same content in different
    locations produces different hashes.
    """
    raw = path.read_bytes()

    if path.suffix.lower() in (".md", ".markdown", ".txt", ".rst"):
        content = _body_content(raw)
    else:
        content = raw

    rel = str(path.relative_to(root)) if root else str(path)
    h = hashlib.sha256()
    h.update(content)
    h.update(rel.encode("utf-8"))
    return h.hexdigest()


def load_cached(path: Path, cache_dir: Path) -> dict | None:
    """Load cached result for a file, or return None if not cached."""
    if not cache_dir.exists():
        return None
    # Use file_hash as cache key — but we need the hash to look up
    # So cache files are named by their content hash
    # This is called by the orchestrator who already computed the hash
    return None  # Caller should use load_by_hash


def load_by_hash(content_hash: str, cache_dir: Path) -> dict | None:
    """Load cached extraction result by content hash."""
    cache_file = cache_dir / f"{content_hash}.json"
    if not cache_file.exists():
        return None
    try:
        return json.loads(cache_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def save_cache(content_hash: str, result: dict, cache_dir: Path) -> None:
    """Save extraction result to cache."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / f"{content_hash}.json"
    cache_file.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def check_cache(files: list[Path], cache_dir: Path, root: Path | None = None) -> tuple[list[dict], list[Path]]:
    """Check which files have cached results.

    Returns:
        (cached_results, uncached_files)
    """
    cached = []
    uncached = []
    for f in files:
        h = file_hash(f, root)
        result = load_by_hash(h, cache_dir)
        if result is not None:
            cached.append(result)
        else:
            uncached.append(f)
    return cached, uncached
