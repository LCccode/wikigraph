"""Synthetic KB generator for lcwiki performance benchmarks.

Generates a realistic KB structure with N documents, articles, and inbox files
without calling any LLM APIs. All data is deterministic (seed=42).

Usage:
    from tests.bench.gen_synthetic_kb import generate_synthetic_kb
    kb_root = generate_synthetic_kb(Path("/tmp/bench_kb"), n_docs=500)
"""

from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path


def generate_synthetic_kb(
    kb_root: Path,
    n_docs: int = 2000,
    avg_concepts_per_doc: int = 8,
    avg_aliases_per_concept: int = 2,
) -> Path:
    """Generate N synthetic documents for performance benchmarking.

    Directory layout produced:
        kb_root/
            vault/meta/source_map.json          (n_docs entries)
            vault/meta/concepts_index.json       (n_docs * avg_concepts_per_doc entries)
            vault/wiki/articles/<title>.md       (n_docs .md files with frontmatter + tldr)
            raw/inbox/doc_XXXX.txt               (n_docs .txt inbox files)

    Args:
        kb_root: Root directory to create the KB in. Created if absent.
        n_docs: Number of synthetic documents.
        avg_concepts_per_doc: Average concepts referenced per document.
        avg_aliases_per_concept: Average aliases per concept entry.

    Returns:
        kb_root (the same Path passed in).
    """
    rng = random.Random(42)

    # Build directory structure
    meta_dir = kb_root / "vault" / "meta"
    articles_dir = kb_root / "vault" / "wiki" / "articles"
    inbox_dir = kb_root / "raw" / "inbox"
    for d in (meta_dir, articles_dir, inbox_dir):
        d.mkdir(parents=True, exist_ok=True)

    # -----------------------------------------------------------------------
    # 1. Concept pool: total unique concepts is smaller than total references
    #    to ensure cross-doc overlap (~10% reuse across docs).
    # -----------------------------------------------------------------------
    total_concept_slots = n_docs * avg_concepts_per_doc
    # ~10% reuse: pool size = 90% of slots
    pool_size = max(1, int(total_concept_slots * 0.90))
    concept_pool: list[str] = [f"concept_{i}" for i in range(pool_size)]

    # Pre-generate aliases for each pool concept
    concept_aliases: dict[str, list[str]] = {}
    for cname in concept_pool:
        n_aliases = rng.randint(0, avg_aliases_per_concept * 2)
        aliases = [f"{cname}_alias_{j}" for j in range(n_aliases)]
        concept_aliases[cname] = aliases

    # -----------------------------------------------------------------------
    # 2. source_map.json and inbox .txt files
    # -----------------------------------------------------------------------
    source_map: dict = {}

    for i in range(1, n_docs + 1):
        stem = f"doc_{i:04d}"
        raw_content = (
            f"This is synthetic document {i}. "
            f"It covers topic {stem} for benchmark purposes. "
            f"{'Lorem ipsum ' * 5}"
        )
        # Inbox file
        txt_path = inbox_dir / f"{stem}.txt"
        txt_path.write_text(raw_content, encoding="utf-8")

        # SHA256 from content (deterministic)
        sha256 = hashlib.sha256(raw_content.encode()).hexdigest()

        source_map[sha256] = {
            "original_filename": f"{stem}.txt",
            "raw_path": f"raw/inbox/{stem}.txt",
            "generated_pages": [f"articles/{stem}.md"],
            "uploader": "bench",
            "uploaded_at": "2026-01-01T00:00:00+00:00",
        }

    (meta_dir / "source_map.json").write_text(
        json.dumps(source_map, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # -----------------------------------------------------------------------
    # 3. articles/*.md — with frontmatter including tldr and aliases fields
    # -----------------------------------------------------------------------
    sha_list = list(source_map.keys())

    for idx, (sha256, info) in enumerate(source_map.items()):
        stem = Path(info["original_filename"]).stem
        title = stem.replace("_", " ").title()

        # Pick random concepts for this doc
        n_concepts = max(1, rng.randint(
            avg_concepts_per_doc - 2, avg_concepts_per_doc + 2
        ))
        doc_concepts = rng.sample(concept_pool, min(n_concepts, len(concept_pool)))

        # Aliases on the article itself (FIX-C format)
        article_aliases = [f"{stem}_en", f"{stem}_zh"] if rng.random() > 0.5 else []
        aliases_yaml = json.dumps(article_aliases, ensure_ascii=False)

        tldr_text = f"Synthetic document covering {title}. Generated for perf bench."
        # Truncate to <=100 chars per spec
        tldr_text = tldr_text[:100]

        concepts_yaml = json.dumps(doc_concepts, ensure_ascii=False)

        frontmatter = (
            f"---\n"
            f'title: "{title}"\n'
            f"doc_type: benchmark\n"
            f"source_sha256: {sha256}\n"
            f"concepts: {concepts_yaml}\n"
            f"compiled_by: bench\n"
            f"confidence: 0.9\n"
            f'tldr: "{tldr_text}"\n'
            f"aliases: {aliases_yaml}\n"
            f"---\n\n"
            f"# {title}\n\n"
            f"Synthetic article body for document {stem}.\n"
        )

        article_path = articles_dir / f"{stem}.md"
        article_path.write_text(frontmatter, encoding="utf-8")

    # -----------------------------------------------------------------------
    # 4. concepts_index.json — built from all doc-concept references
    # -----------------------------------------------------------------------
    concepts_index: dict = {}
    for idx, (sha256, info) in enumerate(source_map.items()):
        stem = Path(info["original_filename"]).stem
        # Re-derive concepts deterministically (same rng seed approach: re-read from article)
        article_path = articles_dir / f"{stem}.md"
        text = article_path.read_text(encoding="utf-8")

        # Parse concepts from frontmatter
        import re
        m = re.search(r"^concepts:\s*(\[.*?\])", text, re.MULTILINE)
        doc_concepts: list[str] = json.loads(m.group(1)) if m else []

        for cname in doc_concepts:
            entry = concepts_index.get(cname, {})
            aliases = concept_aliases.get(cname, [])
            merged_aliases = list(set(entry.get("aliases", []) + aliases))
            concepts_index[cname] = {
                "path": f"concepts/{cname}.md",
                "aliases": merged_aliases,
                "summary": f"Concept {cname} used across multiple documents.",
                "article_count": entry.get("article_count", 0) + 1,
            }

    (meta_dir / "concepts_index.json").write_text(
        json.dumps(concepts_index, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return kb_root
