"""Performance benchmarks for lcwiki FIX-A through FIX-E.

Each bench_fix_* function is self-contained:
  - sets up data from a pre-generated synthetic KB
  - measures wall-clock time
  - returns a result dict with keys: name, elapsed, threshold, passed, notes

No LLM APIs are called. All I/O is local.
"""

from __future__ import annotations

import sys
import time
import json
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch

# Ensure lcwiki is importable when running from repo root
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


# ---------------------------------------------------------------------------
# FIX-A: filename_index O(1) lookup
# ---------------------------------------------------------------------------

def bench_fix_a_filename_index(kb_root: Path) -> dict:
    """Simulate conflict detection for 100 new files against a 2000-entry source_map.

    Steps:
      1. Load source_map + build filename_index (both already generated)
      2. Construct 100 candidate stems (30 with conflicts, 70 novel)
      3. Measure total time for 100 filename_index_lookup calls

    Threshold: < 0.1s
    """
    from lcwiki.index import (
        load_source_map,
        load_filename_index,
        rebuild_filename_index,
        filename_index_lookup,
    )

    meta_dir = kb_root / "vault" / "meta"
    source_map = load_source_map(meta_dir)
    n_docs = len(source_map)

    # Build or load filename_index
    filename_index = load_filename_index(meta_dir)
    if not filename_index and source_map:
        filename_index = rebuild_filename_index(source_map)

    # Candidate stems: pick 30 existing stems (conflict) + 70 novel stems
    existing_stems = list(filename_index.keys())
    conflict_stems = existing_stems[:30] if len(existing_stems) >= 30 else existing_stems
    novel_stems = [f"new_doc_{i:04d}" for i in range(70)]
    candidate_stems = conflict_stems + novel_stems  # total 100

    # Measure 100 lookups
    t0 = time.perf_counter()
    for stem in candidate_stems:
        _ = filename_index_lookup(stem, filename_index)
    elapsed = time.perf_counter() - t0

    threshold = 0.1
    conflicts_found = sum(
        1 for s in conflict_stems if filename_index_lookup(s, filename_index)
    )

    return {
        "name": "FIX-A filename_index lookup (100 files)",
        "elapsed": elapsed,
        "threshold": threshold,
        "passed": elapsed < threshold,
        "notes": (
            f"n_docs={n_docs}, index_size={len(filename_index)}, "
            f"conflicts_detected={conflicts_found}/30"
        ),
    }


# ---------------------------------------------------------------------------
# FIX-B: ConceptsIndexWriter reduce (2000 partials)
# ---------------------------------------------------------------------------

def bench_fix_b_concepts_writer(kb_root: Path) -> dict:
    """Simulate reduce of 2000 partial concept index files.

    Steps:
      1. Create a temp meta dir with 2000 .partial.json files
         (each with avg_concepts_per_doc=8 concepts)
      2. Call ConceptsIndexWriter.reduce(meta_dir)
      3. Measure reduce elapsed time

    Threshold: < 5s
    """
    from lcwiki.index import ConceptsIndexWriter

    # Use a temp dir so we don't pollute the synthetic KB
    tmp_dir = Path(tempfile.mkdtemp(prefix="bench_fix_b_"))
    try:
        meta_dir = tmp_dir / "meta"
        meta_dir.mkdir()

        n_partials = 2000
        avg_concepts = 8

        # Write 2000 partial files
        for task_idx in range(n_partials):
            writer = ConceptsIndexWriter(meta_dir, f"task_{task_idx:04d}")
            for c_idx in range(avg_concepts):
                # ~10% concept reuse across tasks
                if c_idx < 1:
                    # Always reuse concept_0 to simulate merging
                    cname = "concept_shared_0"
                else:
                    cname = f"concept_{task_idx}_{c_idx}"
                writer.update(
                    cname,
                    f"concepts/{cname}.md",
                    summary=f"Summary for {cname}",
                    aliases=[f"{cname}_alias"],
                )
            writer.flush()

        # Count partial files written
        partial_dir = meta_dir / ConceptsIndexWriter.PARTIAL_DIR
        partial_count = len(list(partial_dir.glob("*.partial.json")))

        # Measure reduce time
        t0 = time.perf_counter()
        result = ConceptsIndexWriter.reduce(meta_dir)
        elapsed = time.perf_counter() - t0

        threshold = 5.0
        return {
            "name": "FIX-B concepts reduce (2000 partials x 8 concepts)",
            "elapsed": elapsed,
            "threshold": threshold,
            "passed": elapsed < threshold,
            "notes": (
                f"partial_files={partial_count}, "
                f"merged_concepts={len(result)}"
            ),
        }
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# FIX-D: Leiden timeout + Louvain fallback
# ---------------------------------------------------------------------------

def bench_fix_d_leiden_timeout() -> dict:
    """Verify Leiden timeout triggers Louvain fallback.

    Strategy:
      - graspologic may or may not be installed.
      - If graspologic IS available: mock _run_leiden_in_process to sleep 90s,
        set timeout=5s, verify fallback triggers and result is valid.
      - If graspologic is NOT available (ImportError path): directly verify
        that cluster() falls through to Louvain and returns a valid result.
        This tests the ImportError branch of the fallback chain.

    In both cases we verify:
      - Return value is dict[int, list[str]]
      - All nodes present in at least one community
      - Total elapsed < 65s (or < 5s for the no-graspologic path)

    Uses a real NetworkX graph to prove pickle compatibility.
    """
    import networkx as nx
    from lcwiki.cluster import cluster

    # Build a real picklable NetworkX graph (50 nodes, 100 edges)
    G = nx.barabasi_albert_graph(50, 2, seed=42)
    # Relabel nodes to strings (as lcwiki uses string node IDs)
    G = nx.relabel_nodes(G, {n: f"node_{n}" for n in G.nodes()})

    # Check if graspologic is actually importable
    graspologic_available = False
    try:
        import graspologic.partition  # noqa: F401
        graspologic_available = True
    except (ImportError, Exception):
        graspologic_available = False

    if graspologic_available:
        # Mock leiden to sleep longer than timeout, forcing the TimeoutError branch
        import concurrent.futures as _cf

        def _slow_leiden(g):
            import time
            time.sleep(90)
            return {}

        t0 = time.perf_counter()
        with patch("lcwiki.cluster._run_leiden_in_process", side_effect=_slow_leiden):
            result = cluster(G, timeout=5)
        elapsed = time.perf_counter() - t0

        threshold_lo = 4.0   # must have waited at least ~timeout
        threshold_hi = 15.0  # should not take more than timeout + Louvain overhead
        passed = threshold_lo <= elapsed <= threshold_hi
        mode = "graspologic+mock_timeout"
    else:
        # graspologic unavailable: test the ImportError fallback path (instant)
        t0 = time.perf_counter()
        result = cluster(G, timeout=5)
        elapsed = time.perf_counter() - t0

        # Should complete very quickly via Louvain
        threshold_hi = 10.0
        passed = elapsed < threshold_hi
        mode = "no_graspologic_louvain_direct"

    # Validate result structure: dict[int, list[str]]
    structure_ok = (
        isinstance(result, dict)
        and all(isinstance(k, int) for k in result.keys())
        and all(isinstance(v, list) for v in result.values())
    )
    all_nodes_covered = set(G.nodes()) <= {n for nodes in result.values() for n in nodes}

    if not structure_ok:
        passed = False
    if not all_nodes_covered:
        passed = False

    return {
        "name": "FIX-D Leiden timeout fallback",
        "elapsed": elapsed,
        "threshold": threshold_hi,
        "passed": passed,
        "notes": (
            f"mode={mode}, communities={len(result)}, "
            f"nodes_covered={all_nodes_covered}, "
            f"structure_ok={structure_ok}"
        ),
    }


# ---------------------------------------------------------------------------
# FIX-E: TldrCache cold vs warm
# ---------------------------------------------------------------------------

def bench_fix_e_tldr_cache(kb_root: Path) -> dict:
    """Benchmark TldrCache for 100-node visited set.

    Steps:
      1. Reset singleton to ensure cold start
      2. Build synthetic NetworkX graph with 100 article nodes
      3. First call to read_article_tldrs (cold — reads 100 files from disk)
      4. Second call to read_article_tldrs (warm — all in cache)
      5. Report cold and warm elapsed times

    Thresholds:
      cold: < 2.0s
      warm: < 0.1s
    """
    import networkx as nx
    from lcwiki.query import TldrCache, read_article_tldrs

    articles_dir = kb_root / "vault" / "wiki" / "articles"
    wiki_dir = kb_root / "vault" / "wiki"

    # Gather up to 100 article files that actually exist
    all_articles = sorted(articles_dir.glob("*.md"))
    sample_articles = all_articles[:100]
    n_sample = len(sample_articles)

    if n_sample == 0:
        return {
            "name": "FIX-E tldr cache (cold)",
            "elapsed": 0.0,
            "threshold": 2.0,
            "passed": False,
            "notes": "No article files found in KB",
        }

    # Build a synthetic NetworkX graph with nodes pointing to these articles
    G = nx.DiGraph()
    visited_nodes: set[str] = set()
    for art_path in sample_articles:
        rel = f"articles/{art_path.name}"
        nid = art_path.stem
        G.add_node(nid, label=art_path.stem, source_file=rel)
        visited_nodes.add(nid)

    # Reset cache to ensure cold start
    TldrCache.reset()

    # Cold run
    t0 = time.perf_counter()
    cold_result = read_article_tldrs(G, visited_nodes, wiki_dir, max_tldrs=n_sample)
    cold_elapsed = time.perf_counter() - t0

    # Warm run (same nodes, cache should be populated)
    t1 = time.perf_counter()
    warm_result = read_article_tldrs(G, visited_nodes, wiki_dir, max_tldrs=n_sample)
    warm_elapsed = time.perf_counter() - t1

    cold_threshold = 2.0
    warm_threshold = 0.1

    return {
        "name": "FIX-E tldr cache",
        "elapsed": cold_elapsed,           # primary metric = cold
        "threshold": cold_threshold,
        "passed": cold_elapsed < cold_threshold and warm_elapsed < warm_threshold,
        "notes": (
            f"n_articles={n_sample}, "
            f"cold={cold_elapsed:.4f}s (< {cold_threshold}s), "
            f"warm={warm_elapsed:.4f}s (< {warm_threshold}s), "
            f"cold_pass={cold_elapsed < cold_threshold}, "
            f"warm_pass={warm_elapsed < warm_threshold}"
        ),
        # Extra fields for detailed reporting
        "_cold_elapsed": cold_elapsed,
        "_warm_elapsed": warm_elapsed,
        "_cold_threshold": cold_threshold,
        "_warm_threshold": warm_threshold,
        "_cold_passed": cold_elapsed < cold_threshold,
        "_warm_passed": warm_elapsed < warm_threshold,
    }


# ---------------------------------------------------------------------------
# FIX-C: aliases field written correctly (accuracy, not timing)
# ---------------------------------------------------------------------------

def bench_fix_c_aliases_accuracy(kb_root: Path) -> dict:
    """Verify that generated articles contain a valid 'aliases' frontmatter field.

    Checks a random sample of 100 articles from the synthetic KB.
    This is an accuracy verification, not a timing benchmark.
    """
    import re

    articles_dir = kb_root / "vault" / "wiki" / "articles"
    all_articles = sorted(articles_dir.glob("*.md"))
    # Sample up to 100
    rng = __import__("random").Random(42)
    sample = rng.sample(all_articles, min(100, len(all_articles)))

    _ALIASES_RE = re.compile(r"^aliases:\s*(\[.*?\])\s*$", re.MULTILINE)

    ok = 0
    fail = 0
    fail_details: list[str] = []

    for path in sample:
        text = path.read_text(encoding="utf-8")
        m = _ALIASES_RE.search(text)
        if m:
            try:
                val = json.loads(m.group(1))
                if isinstance(val, list):
                    ok += 1
                else:
                    fail += 1
                    fail_details.append(f"{path.name}: aliases not a list")
            except json.JSONDecodeError:
                fail += 1
                fail_details.append(f"{path.name}: aliases JSON invalid")
        else:
            fail += 1
            fail_details.append(f"{path.name}: aliases field missing")

    passed = fail == 0
    return {
        "name": "FIX-C aliases field accuracy (100 articles sampled)",
        "elapsed": 0.0,   # not a timing test
        "threshold": 0.0,
        "passed": passed,
        "notes": (
            f"ok={ok}/{len(sample)}, fail={fail}, "
            + (f"first_fail={fail_details[0]}" if fail_details else "all_ok")
        ),
    }
