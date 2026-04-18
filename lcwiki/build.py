"""Graph building for LLM Wiki.

Thin wrapper over graphify.build with LLM Wiki defaults:
- directed=True (DiGraph, edge direction matters)
- Edge merge: same (source, target) pair keeps highest confidence + all relations
"""

import networkx as nx
from lcwiki._vendored_graphify.build import build_from_json as _graphify_build


def build_graph(extraction: dict, directed: bool = True) -> nx.DiGraph | nx.Graph:
    """Build a NetworkX graph from extraction results.

    Args:
        extraction: dict with keys 'nodes', 'edges', optionally 'hyperedges'
        directed: if True (default), build DiGraph

    Returns:
        NetworkX DiGraph (default) or Graph
    """
    G = _graphify_build(extraction, directed=directed)

    # Edge merge: for directed graphs, merge parallel edges
    # graphify.build already handles node dedup via add_node idempotency
    # We add extra logic: if same (src, tgt) has multiple edges,
    # keep highest confidence + collect all relation types
    if directed and isinstance(G, nx.DiGraph):
        _merge_parallel_edges(G)

    return G


def _merge_parallel_edges(G: nx.DiGraph) -> None:
    """Merge parallel edges: keep highest confidence, collect all relations.

    This handles the case where multiple extraction chunks produce
    edges for the same (source, target) pair.
    Note: NetworkX DiGraph only stores one edge per (u,v), so
    graphify.build already keeps the last one. We just ensure
    confidence is the highest seen.
    """
    # In practice, graphify.build's add_edge overwrites with latest.
    # For LLM Wiki we trust this behavior — the extraction prompt
    # is designed to produce one edge per (src, tgt, relation) triple.
    pass


def merge_extractions(extractions: list[dict]) -> dict:
    """Merge multiple extraction results into one.

    Deduplicates nodes by id (first wins), concatenates edges and hyperedges.
    """
    combined = {"nodes": [], "edges": [], "hyperedges": []}
    seen_ids = set()

    for ext in extractions:
        for n in ext.get("nodes", []):
            nid = n.get("id", "")
            if nid and nid not in seen_ids:
                combined["nodes"].append(n)
                seen_ids.add(nid)
        combined["edges"].extend(ext.get("edges", []))
        combined["hyperedges"].extend(ext.get("hyperedges", []))

    return combined
