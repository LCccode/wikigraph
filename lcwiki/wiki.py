"""Navigation wiki generation — Wikipedia-style articles from the graph.

Wraps the vendored graphify wiki.py. Generates:
- `<kb>/vault/wiki/nav/index.md` — catalog of all generated articles
- `<kb>/vault/wiki/nav/<Community>.md` — one article per community
- `<kb>/vault/wiki/nav/<GodNode>.md` — one article per god node

Why this layer: lcwiki's concept/*.md pages are thin词条 (summary + aliases +
relations). The community / god-node articles here are the longer-form,
navigation-friendly documents that describe clusters of related nodes and
their cross-community links. Think "Wikipedia article" vs "dictionary entry".

Agents/humans read index.md to discover the graph, then follow links into
the cluster articles. This was a valuable feature in graphify (Karpathy's
/raw workflow) — we reuse it here.
"""

from pathlib import Path

from lcwiki._vendored_graphify.wiki import to_wiki as _graphify_to_wiki


__all__ = ["to_wiki"]


def to_wiki(
    G,
    communities: dict,
    output_dir: str | Path,
    community_labels: dict | None = None,
    cohesion: dict | None = None,
    god_nodes_data: list | None = None,
) -> int:
    """Generate navigation wiki. Returns the number of articles written (excluding index).

    Recommended output_dir: `<kb>/vault/wiki/nav/` — keeps it separate from
    the concept/*.md and articles/*.md that compile produces.
    """
    return _graphify_to_wiki(
        G,
        communities,
        output_dir,
        community_labels=community_labels,
        cohesion=cohesion,
        god_nodes_data=god_nodes_data,
    )
