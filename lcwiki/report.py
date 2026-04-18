"""GRAPH_REPORT generation for LLM Wiki.

Produces two files per design:
- GRAPH_REPORT_SUMMARY.md (~3K tokens, query always reads)
- GRAPH_REPORT_FULL.md (complete, on-demand)
"""

from datetime import date


def generate_summary(
    G,
    communities: dict,
    community_labels: dict,
    gods: list[dict],
    cohesion: dict | None = None,
    surprises: list[dict] | None = None,
) -> str:
    """Generate GRAPH_REPORT_SUMMARY.md (~3K tokens).

    Contains: stats + God Nodes TOP 10 + community navigation table
    + Surprising Connections (top 5 cross-community/cross-type).
    This is what query reads on every call.
    """
    node_count = G.number_of_nodes()
    edge_count = G.number_of_edges()
    comm_count = len(communities)
    hyperedge_count = len(G.graph.get("hyperedges", []))

    # Confidence distribution
    confidences = [d.get("confidence", "EXTRACTED") for _, _, d in G.edges(data=True)]
    total = len(confidences) or 1
    ext_pct = round(confidences.count("EXTRACTED") / total * 100)
    inf_pct = round(confidences.count("INFERRED") / total * 100)
    amb_pct = round(confidences.count("AMBIGUOUS") / total * 100)

    lines = [
        f"# LLM Wiki 图谱摘要 ({date.today()})",
        "",
        f"- {node_count} 节点 · {edge_count} 边 · {hyperedge_count} 超边 · {comm_count} 社区",
        f"- 置信度：EXTRACTED {ext_pct}% · INFERRED {inf_pct}% · AMBIGUOUS {amb_pct}%",
        "",
        "## 核心节点 (God Nodes)",
    ]
    for i, g in enumerate(gods[:10], 1):
        lines.append(f"{i}. `{g['label']}` — {g['degree']} 条边")

    lines.extend(["", "## 社区导航"])
    lines.append("| 社区 | 成员数 | 内聚度 |")
    lines.append("|------|--------|--------|")
    for cid in sorted(communities.keys()):
        label = community_labels.get(cid, f"社区 {cid}")
        members = len(communities[cid])
        coh = cohesion.get(cid, 0) if cohesion else 0
        lines.append(f"| {label} | {members} | {coh:.2f} |")

    # Surprising Connections — promoted from FULL so query-time LLM sees it
    if surprises:
        lines.extend(["", "## 意外关联 (Surprising Connections)", ""])
        lines.append("跨社区 / 跨类型的高价值关联（按 surprise 分数排序）:")
        lines.append("")
        for s in surprises[:5]:
            src = s.get("source_label", s.get("source", ""))
            tgt = s.get("target_label", s.get("target", ""))
            rel = s.get("relation", "related")
            conf = s.get("confidence", "")
            score = s.get("score", "")
            reasons = s.get("reasons") or []
            reasons_str = f" · {', '.join(reasons[:3])}" if reasons else ""
            lines.append(f"- `{src}` --{rel}--> `{tgt}` [{conf}, score={score}]{reasons_str}")

    return "\n".join(lines) + "\n"


def generate_full(
    G,
    communities: dict,
    community_labels: dict,
    cohesion: dict,
    gods: list[dict],
    surprises: list[dict],
    gaps: dict,
    questions: list[dict] | None = None,
    bridges: dict | None = None,
) -> str:
    """Generate GRAPH_REPORT_FULL.md (complete report).

    Contains everything from SUMMARY plus:
    - Community details (members, cohesion)
    - Surprising Connections (with reasons)
    - Hyperedges
    - Knowledge Gaps
    - Suggested Questions
    - Bridge Nodes
    """
    lines = [generate_summary(G, communities, community_labels, gods, cohesion)]

    # Surprising Connections
    lines.append("\n## 意外关联 (Surprising Connections)\n")
    if surprises:
        for s in surprises:
            reasons_str = ", ".join(s.get("reasons", []))
            lines.append(
                f"- `{s['source_label']}` --{s['relation']}--> `{s['target_label']}` "
                f"[{s['confidence']}] (分数: {s['score']}, 原因: {reasons_str})"
            )
    else:
        lines.append("无意外关联。")

    # Hyperedges
    hyperedges = G.graph.get("hyperedges", [])
    if hyperedges:
        lines.append("\n## 超边 (Hyperedges)\n")
        for h in hyperedges:
            nodes_str = ", ".join(h.get("nodes", []))
            conf = h.get("confidence", "INFERRED")
            score = h.get("confidence_score", 0)
            lines.append(f"- **{h.get('label', h.get('id', ''))}** — {nodes_str} [{conf} {score:.2f}]")

    # Communities detail
    lines.append("\n## 社区详情\n")
    for cid in sorted(communities.keys()):
        label = community_labels.get(cid, f"社区 {cid}")
        coh = cohesion.get(cid, 0)
        members = communities[cid]
        member_labels = [G.nodes[n].get("label", n) for n in members[:8]]
        more = f" (+{len(members)-8} more)" if len(members) > 8 else ""
        lines.append(f"### {label}")
        lines.append(f"内聚度: {coh:.2f} · 成员: {len(members)}")
        lines.append(f"节点: {', '.join(member_labels)}{more}")

        # Bridge nodes for this community
        if bridges and cid in bridges:
            for b in bridges[cid]:
                lines.append(f"  桥接: `{b['label']}` (跨 {b['connected_communities']} 个社区)")
        lines.append("")

    # Knowledge Gaps
    lines.append("\n## 知识缺口 (Knowledge Gaps)\n")
    isolated = gaps.get("isolated_nodes", [])
    thin = gaps.get("thin_communities", [])
    amb_pct = gaps.get("ambiguous_pct", 0)

    if isolated:
        labels = [n["label"] for n in isolated[:5]]
        more = f" (+{len(isolated)-5} more)" if len(isolated) > 5 else ""
        lines.append(f"- **{len(isolated)} 个孤立节点**: {', '.join(labels)}{more}")
        lines.append("  （degree ≤ 1，可能缺少边或未文档化）")
    if thin:
        for t in thin:
            lines.append(f"- **薄弱社区**（{t['members']} 个节点）: {', '.join(t['nodes'])}")
    if amb_pct > 20:
        lines.append(f"- **高歧义**: {amb_pct}% 的边标记为 AMBIGUOUS")
    if not isolated and not thin and amb_pct <= 20:
        lines.append("无明显知识缺口。")

    # Suggested Questions
    if questions:
        lines.append("\n## 建议探索问题\n")
        for q in questions:
            if q.get("question"):
                lines.append(f"- **{q['question']}**")
                lines.append(f"  _{q.get('why', '')}_")

    return "\n".join(lines) + "\n"
