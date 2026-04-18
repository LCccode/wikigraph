"""Backfill frontmatter for existing wiki files missing it.

Two-tier schema:
  Universal required (always written)
    - title: from first "# " heading
    - doc_type: inferred, fallback "document"
    - source_sha256: reverse-looked-up from source_map.json (articles only)
    - concepts: from graph.json covers_concept/includes_module edges (articles only)
    - created_at: file mtime (best available)
    - compiled_by: "script-backfill-v1"
    - confidence: 0.7 (lower than LLM-written, reflects reverse inference)

  Domain optional (written only when detectable)
    - region / customer / customer_type: from graph.json node attributes
    - domain / topic: from graph.json node attributes or frontmatter guesses

Concept files get a concept-specific schema:
    - name: from "# " heading
    - aliases: parsed from summary "(别名: …)" pattern
    - summary: first non-empty paragraph after heading
    - doc_type: "concept"
    - article_count: count of "- [[…]]" lines under "## 相关文章"
    - created_at / updated_at: file mtime

The backfill is non-destructive: a .bak file is written next to every file
we touch, so you can diff before committing.
"""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from lcwiki.merge import parse_aliases_from_summary


_HEADING = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)


def _has_frontmatter(text: str) -> bool:
    return text.startswith("---\n") or text.startswith("---\r\n")


def _extract_title(text: str) -> str:
    m = _HEADING.search(text)
    return m.group(1).strip() if m else ""


def _file_created_at(p: Path) -> str:
    try:
        mt = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
        return mt.date().isoformat()
    except OSError:
        return datetime.now(timezone.utc).date().isoformat()


def _yaml_scalar(v) -> str:
    if v is None:
        return '""'
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, list):
        return "[" + ", ".join(_yaml_scalar(x) for x in v) + "]"
    s = str(v).replace('"', '\\"')
    return f'"{s}"'


def _render_frontmatter(fields: dict) -> str:
    lines = ["---"]
    for k, v in fields.items():
        lines.append(f"{k}: {_yaml_scalar(v)}")
    lines.append("---")
    return "\n".join(lines) + "\n"


# ---------- article backfill ----------

def _load_sha_lookup(source_map: dict) -> dict[str, str]:
    """Build article_stem → sha256 (full) lookup from source_map.

    Prefers source_map[sha].generated_pages (which should contain the exact
    vault/wiki/articles/*.md paths after the compile or /lcwiki audit fills
    them in). Falls back to original_filename stem if generated_pages is
    empty — this mostly helps legacy KBs that ran old compiles.
    """
    table: dict[str, str] = {}
    for sha, info in source_map.items():
        for p in info.get("generated_pages", []) or []:
            stem = Path(p).stem
            if stem:
                table[stem] = sha
        if not info.get("generated_pages"):
            orig = info.get("original_filename", "") or ""
            if orig:
                stem = Path(orig).stem
                table.setdefault(stem, sha)
    return table


def _node_attrs_from_graph(graph_data: dict, source_file: str) -> dict:
    """Find the node whose source_file matches and return its attributes."""
    for n in graph_data.get("nodes", []):
        if n.get("source_file") == source_file:
            return n
    return {}


def _concepts_for_article(graph_data: dict, source_file: str) -> list[str]:
    """From graph: find edges where article is source and target is a concept.
    Returns concept labels (deduped, order preserved)."""
    article_id = None
    for n in graph_data.get("nodes", []):
        if n.get("source_file") == source_file:
            article_id = n.get("id")
            break
    if not article_id:
        return []
    nodes_by_id = {n["id"]: n for n in graph_data.get("nodes", [])}
    concepts: list[str] = []
    seen: set[str] = set()
    for e in graph_data.get("links", []):
        if e.get("source") != article_id:
            continue
        rel = e.get("relation", "")
        if rel not in {"includes_module", "covers_concept", "references", "related_to"}:
            continue
        tgt = nodes_by_id.get(e.get("target"), {})
        if tgt.get("file_type") != "concept":
            continue
        lbl = tgt.get("label", "")
        if lbl and lbl not in seen:
            concepts.append(lbl)
            seen.add(lbl)
    return concepts


_OPTIONAL_ARTICLE_ATTRS = ("region", "customer", "customer_type", "domain", "topic")


def backfill_article(
    article_path: Path,
    kb_root: Path,
    graph_data: dict,
    source_map: dict,
    sha_lookup: dict[str, str],
    write: bool = True,
) -> dict:
    """Add frontmatter to a single article file if missing. Returns the fields
    written (or would-be written if write=False)."""
    text = article_path.read_text(encoding="utf-8")
    if _has_frontmatter(text):
        return {"skipped": "already has frontmatter"}

    title = _extract_title(text) or article_path.stem
    rel = article_path.relative_to(kb_root / "vault" / "wiki").as_posix()  # e.g. "articles/XX.md"
    node_attrs = _node_attrs_from_graph(graph_data, rel)

    sha = sha_lookup.get(article_path.stem, "")
    concepts = _concepts_for_article(graph_data, rel)

    fields: dict = {
        "title": title,
        "doc_type": node_attrs.get("doc_type") or "document",
        "source_sha256": sha[:16] if sha else "",
        "concepts": concepts,
        "created_at": _file_created_at(article_path),
        "compiled_by": "script-backfill-v1",
        "confidence": 0.7,
    }
    for attr in _OPTIONAL_ARTICLE_ATTRS:
        v = node_attrs.get(attr)
        if v:
            fields[attr] = v

    new_text = _render_frontmatter(fields) + "\n" + text

    if write:
        shutil.copy(article_path, article_path.with_suffix(article_path.suffix + ".bak"))
        article_path.write_text(new_text, encoding="utf-8")

    return fields


# ---------- concept backfill ----------

def _count_related_articles(text: str) -> int:
    m = re.search(r"##\s+相关文章\s*\n", text)
    if not m:
        return 0
    block = text[m.end():]
    # Stop at next heading
    end = re.search(r"\n#+\s", block)
    if end:
        block = block[: end.start()]
    return len(re.findall(r"^\s*-\s*\[\[", block, flags=re.MULTILINE))


def _summary_paragraph(text_after_heading: str) -> str:
    for chunk in re.split(r"\n\s*\n", text_after_heading.strip()):
        chunk = chunk.strip()
        if not chunk:
            continue
        if chunk.startswith("#"):
            continue
        return chunk
    return ""


def backfill_concept(
    concept_path: Path,
    write: bool = True,
) -> dict:
    """Add frontmatter to a concept file. Parses aliases from summary text."""
    text = concept_path.read_text(encoding="utf-8")
    if _has_frontmatter(text):
        return {"skipped": "already has frontmatter"}

    name = _extract_title(text) or concept_path.stem
    # Body after first heading line
    m = _HEADING.search(text)
    body_after = text[m.end():] if m else text
    summary = _summary_paragraph(body_after)
    aliases = parse_aliases_from_summary(summary)
    article_count = _count_related_articles(text)
    mt = _file_created_at(concept_path)

    fields = {
        "name": name,
        "aliases": aliases,
        "summary": summary[:300],
        "doc_type": "concept",
        "article_count": article_count,
        "created_at": mt,
        "updated_at": mt,
    }

    new_text = _render_frontmatter(fields) + "\n" + text

    if write:
        shutil.copy(concept_path, concept_path.with_suffix(concept_path.suffix + ".bak"))
        concept_path.write_text(new_text, encoding="utf-8")

    return fields


# ---------- batch runner ----------

def backfill_kb(kb_root: Path, write: bool = True) -> dict:
    """Backfill all article and concept files in a kb. Returns a summary dict."""
    wiki = kb_root / "vault" / "wiki"
    meta = kb_root / "vault" / "meta"
    graph_path = kb_root / "vault" / "graph" / "graph.json"

    graph_data = json.loads(graph_path.read_text(encoding="utf-8")) if graph_path.exists() else {"nodes": [], "links": []}
    source_map = json.loads((meta / "source_map.json").read_text(encoding="utf-8")) if (meta / "source_map.json").exists() else {}
    sha_lookup = _load_sha_lookup(source_map)

    art_results: list[tuple[str, dict]] = []
    for p in sorted((wiki / "articles").glob("*.md")):
        r = backfill_article(p, kb_root, graph_data, source_map, sha_lookup, write=write)
        art_results.append((p.name, r))

    con_results: list[tuple[str, dict]] = []
    for p in sorted((wiki / "concepts").glob("*.md")):
        r = backfill_concept(p, write=write)
        con_results.append((p.name, r))

    return {
        "articles": {"total": len(art_results), "done": sum(1 for _, r in art_results if "skipped" not in r), "skipped": sum(1 for _, r in art_results if "skipped" in r)},
        "concepts": {"total": len(con_results), "done": sum(1 for _, r in con_results if "skipped" not in r), "skipped": sum(1 for _, r in con_results if "skipped" in r)},
        "article_details": art_results,
        "concept_details": con_results,
    }
