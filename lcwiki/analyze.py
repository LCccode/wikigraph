"""Graph analysis for LLM Wiki.

Adapted from lcwiki._vendored_graphify.analyze with LLM Wiki-specific changes:
- No AST/code file logic (LLM Wiki only has business documents)
- _is_file_node simplified: no .py/.ts method stub detection
- _is_concept_node adapted: LLM Wiki concepts have real source_file paths
- bridge_nodes: new function for per-community bridge detection
- prune_dangling_edges: clean up orphan edges after incremental update
"""

import networkx as nx

# graph_diff / suggest_questions reuse the vendored graphify implementation
# (copied into lcwiki/_vendored_graphify/, no external graphify dependency)
from lcwiki._vendored_graphify.analyze import graph_diff, suggest_questions


def _is_file_node(G: nx.Graph, node_id: str) -> bool:
    """In lcwiki, no node is a pure structural container.

    Unlike graphify (which analyses code where a "file node" is just a
    container for classes/functions), lcwiki nodes are semantic:
    - document nodes = a whole article/solution (meaningful entity)
    - concept nodes = a knowledge concept (meaningful entity)

    Both have `label == Path(source_file).stem` by design — that's the
    correct name, not a signal that the node is structural. So we always
    return False, i.e. no node is filtered out of god_nodes / knowledge_gaps.
    """
    return False


def _is_concept_node(G: nx.Graph, node_id: str) -> bool:
    """Check if node is an abstract concept (vs a concrete business entity).

    LLM Wiki adaptation: concepts have source_file like 'concepts/xxx.md',
    so we check for the 'concepts/' prefix instead of empty source_file.
    We do NOT exclude concept nodes from god_nodes — in LLM Wiki,
    concepts ARE the core abstractions (unlike graphify where they're injected).
    """
    # In LLM Wiki, all nodes are meaningful — don't exclude any
    return False


def god_nodes(
    G: nx.Graph,
    top_n: int = 10,
    exclude_kinds: set[str] | None = None,
) -> list[dict]:
    """Return the top_n most-connected nodes (core abstractions).

    Args:
        exclude_kinds: set of `concept_kind` values to exclude. Useful for
            filtering out policy references (e.g. "教育强国建设规划纲要") when
            the caller wants "core capabilities/products" only. Common:
            {"policy", "metric"}. None → no filter (default).
    """
    exclude_kinds = exclude_kinds or set()
    degree = dict(G.degree())
    sorted_nodes = sorted(degree.items(), key=lambda x: x[1], reverse=True)
    result = []
    for node_id, deg in sorted_nodes:
        if _is_file_node(G, node_id):
            continue
        data = G.nodes[node_id]
        if exclude_kinds and data.get("concept_kind") in exclude_kinds:
            continue
        result.append({
            "id": node_id,
            "label": data.get("label", node_id),
            "degree": deg,
            "concept_kind": data.get("concept_kind", ""),
        })
        if len(result) >= top_n:
            break
    return result


def surprising_connections(G: nx.Graph, communities: dict | None = None, top_n: int = 5) -> list[dict]:
    """Find the most surprising cross-community connections.

    Uses a multi-factor surprise score:
    - Confidence bonus: AMBIGUOUS +3, INFERRED +2, EXTRACTED +1
    - Cross doc_type: +2 (solution↔sop, faq↔manual)
    - Cross community: +1
    - Semantic similarity: ×1.5
    - Peripheral→hub: +1 (degree≤2 connects to degree≥5)
    """
    if G.number_of_edges() == 0:
        return []

    node_community = {}
    if communities:
        for cid, nodes in communities.items():
            for n in nodes:
                node_community[n] = cid

    scored = []
    for u, v, data in G.edges(data=True):
        score = 0
        reasons = []

        # Confidence bonus
        conf = data.get("confidence", "EXTRACTED")
        if conf == "AMBIGUOUS":
            score += 3
            reasons.append("AMBIGUOUS edge")
        elif conf == "INFERRED":
            score += 2
            reasons.append("INFERRED edge")
        else:
            score += 1

        # Cross doc_type
        u_type = G.nodes[u].get("file_type", "")
        v_type = G.nodes[v].get("file_type", "")
        if u_type and v_type and u_type != v_type:
            score += 2
            reasons.append(f"cross-type: {u_type}↔{v_type}")

        # Cross community
        u_comm = node_community.get(u)
        v_comm = node_community.get(v)
        if u_comm is not None and v_comm is not None and u_comm != v_comm:
            score += 1
            reasons.append("cross-community")

        # Semantic similarity
        if data.get("relation") == "semantically_similar_to":
            score = int(score * 1.5)
            reasons.append("semantically similar")

        # Peripheral → hub
        u_deg = G.degree(u)
        v_deg = G.degree(v)
        if (u_deg <= 2 and v_deg >= 5) or (v_deg <= 2 and u_deg >= 5):
            score += 1
            reasons.append("peripheral→hub")

        if score > 1:  # Only include non-trivial surprises
            scored.append({
                "source": u,
                "target": v,
                "source_label": G.nodes[u].get("label", u),
                "target_label": G.nodes[v].get("label", v),
                "relation": data.get("relation", ""),
                "confidence": conf,
                "confidence_score": data.get("confidence_score", 1.0),
                "score": score,
                "reasons": reasons,
            })

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_n]


def knowledge_gaps(G: nx.Graph, communities: dict | None = None) -> dict:
    """Identify knowledge gaps in the graph.

    Returns:
        {
          "isolated_nodes": [...],  # degree ≤ 1, excluding hub nodes
          "thin_communities": [...],  # < 3 members
          "ambiguous_pct": float,  # % of AMBIGUOUS edges
        }
    """
    # Isolated nodes
    isolated = []
    for n in G.nodes():
        if G.degree(n) <= 1 and not _is_file_node(G, n):
            isolated.append({
                "id": n,
                "label": G.nodes[n].get("label", n),
                "degree": G.degree(n),
            })

    # Thin communities
    thin = []
    if communities:
        for cid, nodes in communities.items():
            if len(nodes) < 3:
                thin.append({
                    "community_id": cid,
                    "members": len(nodes),
                    "nodes": [G.nodes[n].get("label", n) for n in nodes],
                })

    # Ambiguous percentage
    total = G.number_of_edges() or 1
    ambiguous = sum(1 for _, _, d in G.edges(data=True) if d.get("confidence") == "AMBIGUOUS")
    amb_pct = round(ambiguous / total * 100, 1)

    return {
        "isolated_nodes": isolated,
        "thin_communities": thin,
        "ambiguous_pct": amb_pct,
    }


def bridge_nodes(G: nx.Graph, communities: dict, top_per_community: int = 3) -> dict[int, list[dict]]:
    """Find bridge nodes for each community (nodes connecting to other communities).

    Returns: {community_id: [{id, label, degree, connected_communities: int}, ...]}
    """
    node_community = {}
    for cid, nodes in communities.items():
        for n in nodes:
            node_community[n] = cid

    result = {}
    for cid, nodes in communities.items():
        bridges = []
        for n in nodes:
            connected_comms = set()
            for neighbor in G.neighbors(n):
                nc = node_community.get(neighbor)
                if nc is not None and nc != cid:
                    connected_comms.add(nc)
            if connected_comms:
                bridges.append({
                    "id": n,
                    "label": G.nodes[n].get("label", n),
                    "degree": G.degree(n),
                    "connected_communities": len(connected_comms),
                })
        bridges.sort(key=lambda x: x["connected_communities"], reverse=True)
        result[cid] = bridges[:top_per_community]

    return result


def prune_dangling_edges(G: nx.Graph) -> int:
    """Remove edges whose source or target no longer exists.

    Returns number of pruned edges.
    """
    to_remove = []
    for u, v in G.edges():
        if u not in G.nodes or v not in G.nodes:
            to_remove.append((u, v))
    G.remove_edges_from(to_remove)
    return len(to_remove)
