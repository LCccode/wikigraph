"""Atomic implementation of `/lcwiki graph` Step 3.

Replaces the 150-line python heredoc that used to live in skill.md/skill-claw.md.
The heredoc design let LLMs "understand and rewrite" the step — they'd skip the
real build_graph/cluster/to_html/to_wiki chain and hand-craft a simplified
graph.json + index.html instead. This module makes Step 3 a single atomic CLI
call; LLMs invoke `lcwiki graph-run --kb KB --extraction FILE.json` and have
no wiggle room to forge outputs.

Inputs:
    kb         : path to the KB root
    extraction : path to the Step 2 extraction JSON file

Outputs (all under <kb>/vault/graph/ and <kb>/vault/wiki/nav/):
    graph.json
    graph.html
    GRAPH_REPORT_SUMMARY.md
    GRAPH_REPORT_FULL.md
    graph_index.json
    nav/index.md + community-/god- pages

Exits non-zero on any failure. Callers MUST check the exit code and MUST NOT
fall back to hand-crafted alternatives.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path


def run_graph(
    kb: Path,
    extraction_path: Path,
    obsidian: bool = False,
    obsidian_dir: Path | None = None,
) -> dict:
    """Execute Step 3 end-to-end. Returns a stats dict.

    Raises on fatal errors so the caller's exit(1) path is clean.
    """
    from lcwiki.build import build_graph
    from lcwiki.cluster import cluster, score_all
    from lcwiki.analyze import (
        god_nodes,
        surprising_connections,
        knowledge_gaps,
        bridge_nodes,
        prune_dangling_edges,
    )
    from lcwiki.export import to_html, to_json, attach_hyperedges
    from lcwiki.report import generate_summary, generate_full
    from lcwiki.wiki import to_wiki
    from lcwiki.index import (
        save_graph_index,
        load_concepts_index,
        save_concepts_index,
    )
    from lcwiki.merge import (
        merge_extraction_by_aliases,
        backfill_aliases_from_summary,
        consolidate_by_source_file,
    )
    from lcwiki.validate import validate_extraction_schema, summarize_issues
    from lcwiki.runlog import record_run

    run_started = time.time()
    warnings: list = []

    extraction = json.loads(extraction_path.read_text(encoding="utf-8"))

    raw_issues = validate_extraction_schema(
        extraction, allowed_file_types={"document", "concept"}
    )
    if raw_issues:
        print(f"⚠️ 抽取原始数据 {len(raw_issues)} 个 schema 问题:")
        print(f"   分类: {summarize_issues(raw_issues)}")
        warnings.extend(raw_issues[:50])

    extraction, src_redirect = consolidate_by_source_file(extraction, kb_root=kb)
    print(f"✅ 按 source_file 合并/纠正 {len(src_redirect)} 个节点（前缀 + file_type 自动修复）")

    post_issues = validate_extraction_schema(
        extraction, allowed_file_types={"document", "concept"}
    )
    if post_issues:
        print(f"⚠️ consolidate 后仍有 {len(post_issues)} 个问题（留给 /lcwiki audit）:")
        print(f"   分类: {summarize_issues(post_issues)}")
        warnings.extend(post_issues[:30])

    concepts_idx = load_concepts_index(kb / "vault" / "meta")
    fixed = backfill_aliases_from_summary(concepts_idx)
    if fixed:
        save_concepts_index(concepts_idx, kb / "vault" / "meta")
        print(f"✅ 回填 {fixed} 个 concept 的 aliases（修 compile bug）")

    extraction, alias_redirect = merge_extraction_by_aliases(extraction, concepts_idx)
    print(f"✅ 别名合并 {len(alias_redirect)} 个同义节点")

    G = build_graph(extraction)
    attach_hyperedges(G, extraction.get("hyperedges", []))
    pruned = prune_dangling_edges(G)

    communities = cluster(G)
    cohesion = score_all(G, communities)
    gods = god_nodes(G)
    surprises = surprising_connections(G, communities)
    gaps = knowledge_gaps(G, communities)
    bridges = bridge_nodes(G, communities)

    labels: dict = {}
    used_labels: set[str] = set()
    for cid, members in communities.items():
        concepts = [n for n in members if G.nodes[n].get("file_type") == "concept"]
        candidates = concepts if concepts else list(members)
        top = sorted(candidates, key=lambda n: G.degree(n), reverse=True)[:4]

        chosen = f"社区{cid}"
        for k in range(1, len(top) + 1):
            lbl = " / ".join(G.nodes[n].get("label", n) for n in top[:k])
            if lbl and lbl not in used_labels:
                chosen = lbl
                break
        if chosen in used_labels:
            chosen = f"{chosen} (#{cid})"
        labels[cid] = chosen
        used_labels.add(chosen)

    summary = generate_summary(G, communities, labels, gods, cohesion, surprises=surprises)
    full = generate_full(G, communities, labels, cohesion, gods, surprises, gaps, bridges=bridges)

    graph_dir = kb / "vault" / "graph"
    graph_dir.mkdir(parents=True, exist_ok=True)
    (graph_dir / "GRAPH_REPORT_SUMMARY.md").write_text(summary, encoding="utf-8")
    (graph_dir / "GRAPH_REPORT_FULL.md").write_text(full, encoding="utf-8")
    to_json(G, communities, str(graph_dir / "graph.json"))
    to_html(G, communities, str(graph_dir / "graph.html"), community_labels=labels)

    nav_dir = kb / "vault" / "wiki" / "nav"
    nav_count = to_wiki(
        G,
        communities,
        nav_dir,
        community_labels=labels,
        cohesion=cohesion,
        god_nodes_data=gods,
    )
    print(f"✅ navigation wiki: {nav_count} 篇（{nav_dir}/index.md）")

    if obsidian:
        from lcwiki.export import to_obsidian, to_canvas

        ob_dir = Path(obsidian_dir) if obsidian_dir else (graph_dir / "obsidian")
        n = to_obsidian(G, communities, str(ob_dir), community_labels=labels, cohesion=cohesion)
        to_canvas(G, communities, str(ob_dir / "graph.canvas"), community_labels=labels)
        print(f"✅ Obsidian vault: {n} notes + graph.canvas → {ob_dir}/")

    n2c = {}
    for cid, nodes in communities.items():
        for n in nodes:
            n2c[n] = cid
    n2s = {n: G.nodes[n].get("source_file", "") for n in G.nodes()}
    save_graph_index(n2c, dict(communities), n2s, 0, graph_dir)

    isolated = [n for n in G.nodes() if G.degree(n) == 0]
    sem_edges = sum(
        1 for _, _, d in G.edges(data=True) if d.get("relation") == "semantically_similar_to"
    )

    stats = {
        "nodes": G.number_of_nodes(),
        "edges": G.number_of_edges(),
        "communities": len(communities),
        "hyperedges": len(extraction.get("hyperedges", [])),
        "isolated_nodes": len(isolated),
        "semantic_edges": sem_edges,
        "edges_pruned": pruned,
        "source_file_redirects": len(src_redirect),
        "alias_redirects": len(alias_redirect),
        "schema_issues_raw": len(raw_issues),
        "schema_issues_post": len(post_issues),
        "god_nodes_top5": [g["label"] for g in gods[:5]],
        "nav_count": nav_count,
    }

    print(f"✅ 图谱：{stats['nodes']} 节点 / {stats['edges']} 边 / {stats['communities']} 社区")
    print(f"   God Nodes: {', '.join(stats['god_nodes_top5'])}")
    print(f"   孤边清理: {pruned} 条")

    report_path = record_run(
        kb,
        "graph",
        started_at=run_started,
        params={"kb_path": str(kb), "extraction": str(extraction_path)},
        stats=stats,
        tokens={},
        warnings=warnings,
        status="success" if len(post_issues) == 0 else "partial",
    )
    if report_path:
        print(f"📄 运行报告：{report_path}")

    return stats


def main(argv: list[str]) -> int:
    """Entry point wired into `lcwiki graph-run` via __main__.py."""
    kb: Path | None = None
    extraction: Path | None = None
    obsidian = False
    obsidian_dir: Path | None = None

    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--kb":
            kb = Path(argv[i + 1])
            i += 2
        elif a == "--extraction":
            extraction = Path(argv[i + 1])
            i += 2
        elif a == "--obsidian":
            obsidian = True
            i += 1
        elif a == "--obsidian-dir":
            obsidian_dir = Path(argv[i + 1])
            i += 2
        else:
            print(f"error: unknown flag '{a}'", file=sys.stderr)
            return 2

    if kb is None or extraction is None:
        print(
            "usage: lcwiki graph-run --kb KB_PATH --extraction EXTRACTION.json "
            "[--obsidian] [--obsidian-dir DIR]",
            file=sys.stderr,
        )
        return 2
    if not kb.exists():
        print(f"error: kb path does not exist: {kb}", file=sys.stderr)
        return 1
    if not extraction.exists():
        print(f"error: extraction file does not exist: {extraction}", file=sys.stderr)
        return 1

    run_graph(kb, extraction, obsidian=obsidian, obsidian_dir=obsidian_dir)
    return 0
