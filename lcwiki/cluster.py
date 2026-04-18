"""Community detection for LLM Wiki.

Direct re-export of graphify.cluster — no modification needed.
Leiden (graspologic) preferred, Louvain (networkx) fallback.
"""

from lcwiki._vendored_graphify.cluster import cluster, score_all, cohesion_score

__all__ = ["cluster", "score_all", "cohesion_score"]
