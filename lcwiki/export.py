"""Export functions for LLM Wiki.

Wraps graphify.export with a file_type mapping layer: lcwiki uses
`document` / `concept` for business semantics, but graphify's to_html
renderer only styles `code / document / image / paper / rationale`.
Without mapping, concept nodes fall back to unstyled defaults and can
disappear from filtered views. We map `concept → rationale` at the
render boundary so the visualisation looks right without polluting the
business layer.
"""

from lcwiki._vendored_graphify.export import (
    to_html as _graphify_to_html,
    to_json as _graphify_to_json,
    attach_hyperedges,
    prune_dangling_edges,
    to_obsidian,   # 一节点一 .md，支持 [[wikilinks]]，可直接在 Obsidian 打开
    to_canvas,     # 生成 .canvas 文件，Obsidian Canvas 格式按社区分组布局
)


__all__ = [
    "to_html", "to_json", "attach_hyperedges", "prune_dangling_edges",
    "to_obsidian", "to_canvas",
]


# Map lcwiki file_type → graphify-recognised file_type (for rendering only)
_RENDER_TYPE_MAP = {
    "concept": "rationale",    # concept 是"理念/观点"，graphify 的 rationale 最贴合
    "document": "document",    # 保持
    # future types can be added here without touching business layer
}


def _remap_for_graphify(G):
    """Return a shallow copy of G where node.file_type is mapped to a
    graphify-recognised value. Original graph is untouched.
    """
    G2 = G.copy()
    for nid, data in G2.nodes(data=True):
        ft = data.get("file_type", "")
        mapped = _RENDER_TYPE_MAP.get(ft)
        if mapped:
            data["file_type"] = mapped
        # Also stash original for tooltip inspection
        if ft and "file_type_lcwiki" not in data:
            data["file_type_lcwiki"] = ft
    return G2


def to_html(G, communities: dict, output_path: str, community_labels: dict | None = None) -> None:
    """Generate interactive HTML visualization (vis.js) via graphify.

    Applies file_type remap so concept nodes get proper styling.
    """
    G_rendered = _remap_for_graphify(G)
    _graphify_to_html(G_rendered, communities, output_path, community_labels=community_labels)


def to_json(G, communities: dict, output_path: str) -> None:
    """Export graph as node-link JSON via graphify.

    Keeps original lcwiki file_types (no remap — JSON consumers expect
    the business-layer values).
    """
    _graphify_to_json(G, communities, output_path)
