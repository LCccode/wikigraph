"""Query helpers for LLM Wiki.

Provides node matching, BFS/DFS graph traversal, and subgraph rendering.
The actual LLM answer synthesis is done by skill.md — this module
handles the graph navigation that precedes it.
"""

import json
import unicodedata
from pathlib import Path

import networkx as nx


def _strip_diacritics(text: str) -> str:
    """Normalize text for accent-insensitive matching."""
    return "".join(
        c for c in unicodedata.normalize("NFKD", text)
        if unicodedata.category(c) != "Mn"
    )


def parse_filters(raw_args: list[str]) -> dict:
    """Parse `--filter k=v` style arguments into a dict.

    Accepts multiple `--filter` occurrences. Values may be comma-separated
    for OR match, e.g. `--filter region=陕西,新疆` → matches either. Keys
    correspond to node attributes populated from article frontmatter
    (region / customer / customer_type / domain / topic / doc_type).

    Example:
        parse_filters(["--filter", "region=新疆", "--filter", "customer_type=民办"])
        → {"region": ["新疆"], "customer_type": ["民办"]}

    Returns {} if no filter args found.
    """
    filters: dict[str, list[str]] = {}
    i = 0
    while i < len(raw_args):
        tok = raw_args[i]
        if tok == "--filter" and i + 1 < len(raw_args):
            kv = raw_args[i + 1]
            if "=" in kv:
                k, v = kv.split("=", 1)
                filters.setdefault(k.strip(), []).extend(
                    [s.strip() for s in v.split(",") if s.strip()]
                )
            i += 2
        elif tok.startswith("--filter=") and len(tok) > 9:
            kv = tok[9:]
            if "=" in kv:
                k, v = kv.split("=", 1)
                filters.setdefault(k.strip(), []).extend(
                    [s.strip() for s in v.split(",") if s.strip()]
                )
            i += 1
        else:
            i += 1
    return filters


def _node_matches_filters(node_data: dict, filters: dict) -> bool:
    """Check if a node's frontmatter attributes satisfy the filter dict.

    A node matches iff for every filter key, the node's attribute value
    contains (as substring) one of the accepted values — case-insensitive.
    Missing attributes don't match (the node is excluded).
    """
    for k, accepted in filters.items():
        v = str(node_data.get(k, "")).lower()
        if not v:
            return False
        if not any(a.lower() in v for a in accepted):
            return False
    return True


def score_nodes(
    G: nx.Graph,
    terms: list[str],
    label_weight: float = 1.0,
    source_weight: float = 0.5,
    filters: dict | None = None,
) -> list[tuple[float, str]]:
    """Score graph nodes by relevance to query terms.

    Returns list of (score, node_id), sorted descending.
    Matching is case-insensitive and diacritics-insensitive.

    If `filters` is given (dict of node-attribute → list of accepted values),
    nodes not matching the filter are excluded. The filter keys correspond
    to frontmatter fields copied onto nodes during graph extraction (e.g.
    region / customer / customer_type / domain / topic / doc_type).
    """
    results = []
    terms_lower = [_strip_diacritics(t.lower()) for t in terms if len(t) > 1]
    if not terms_lower:
        return []

    for nid, data in G.nodes(data=True):
        if filters and not _node_matches_filters(data, filters):
            continue

        score = 0.0
        label = _strip_diacritics(data.get("label", "").lower())
        source = _strip_diacritics(data.get("source_file", "").lower())

        for term in terms_lower:
            if term in label:
                score += label_weight
            elif term in source:
                score += source_weight

        if score > 0:
            results.append((score, nid))

    results.sort(key=lambda x: x[0], reverse=True)
    return results


def filter_visited_by_frontmatter(
    G: nx.Graph,
    visited: set[str],
    filters: dict,
) -> set[str]:
    """Post-BFS filter: keep only nodes whose frontmatter matches.

    Use case: BFS from filtered start_nodes may expand into unfiltered
    neighbours (e.g. a concept 'smart classroom' touched via edge). If the
    caller wants strict attribute-bound retrieval, pipe visited through
    this to drop the unrelated expansion. Usually prefer NOT calling this —
    concepts bridging different regions are often useful in answers.
    """
    return {n for n in visited if _node_matches_filters(G.nodes[n], filters)}


def bfs(G: nx.Graph, start_nodes: list[str], depth: int = 3) -> tuple[set[str], list[tuple]]:
    """Breadth-first traversal from start nodes, treating the graph as undirected
    (walks both successors and predecessors for DiGraphs).

    Why undirected: lcwiki queries often want "what references X?" which means
    walking in-edges, and "what does X contain?" which means out-edges. A
    concept like "大数据精准教学" has many solutions as predecessors via
    includes_module — an out-only walk misses them all.

    Returns (visited_nodes, edges_traversed).
    """
    visited: set[str] = set(start_nodes)
    frontier = set(start_nodes)
    edges_seen: list[tuple] = []

    is_directed = G.is_directed() if hasattr(G, "is_directed") else False

    for _ in range(depth):
        next_frontier: set[str] = set()
        for n in frontier:
            if is_directed:
                neighbors = set(G.successors(n)) | set(G.predecessors(n))
            else:
                neighbors = set(G.neighbors(n))
            for neighbor in neighbors:
                if neighbor not in visited:
                    next_frontier.add(neighbor)
                    edges_seen.append((n, neighbor))
        visited.update(next_frontier)
        frontier = next_frontier

    return visited, edges_seen


def dfs(G: nx.Graph, start_nodes: list[str], depth: int = 6) -> tuple[set[str], list[tuple]]:
    """Depth-first traversal from start nodes.

    Returns (visited_nodes, edges_traversed).
    Best for: "How does X reach Y?" — trace a specific chain.
    """
    visited: set[str] = set()
    edges_seen: list[tuple] = []
    stack = [(n, 0) for n in reversed(start_nodes)]

    while stack:
        node, d = stack.pop()
        if node in visited or d > depth:
            continue
        visited.add(node)
        for neighbor in G.neighbors(node):
            if neighbor not in visited:
                stack.append((neighbor, d + 1))
                edges_seen.append((node, neighbor))

    return visited, edges_seen


def subgraph_to_text(
    G: nx.Graph,
    nodes: set[str],
    edges: list[tuple],
    token_budget: int = 2000,
) -> str:
    """Render a subgraph as text, respecting token budget.

    Nodes are sorted by degree (most connected first).
    Truncates at ~token_budget tokens (approx 3 chars/token for Chinese).
    """
    char_budget = token_budget * 2  # Chinese chars ≈ 2 chars/token

    lines = ["## 子图节点\n"]
    sorted_nodes = sorted(nodes, key=lambda n: G.degree(n), reverse=True)
    for nid in sorted_nodes:
        data = G.nodes.get(nid, {})
        label = data.get("label", nid)
        ftype = data.get("file_type", "")
        comm = data.get("community", "")
        lines.append(f"- `{label}` [{ftype}] 社区:{comm} 度数:{G.degree(nid)}")

    lines.append("\n## 子图关系\n")
    for u, v in edges:
        edata = G.edges.get((u, v), {})
        if not edata and G.is_directed():
            edata = G.edges.get((v, u), {})
        ul = G.nodes[u].get("label", u) if u in G.nodes else u
        vl = G.nodes[v].get("label", v) if v in G.nodes else v
        rel = edata.get("relation", "")
        conf = edata.get("confidence", "")
        lines.append(f"  {ul} --{rel}--> {vl} [{conf}]")

    output = "\n".join(lines)
    if len(output) > char_budget:
        output = output[:char_budget] + f"\n... (截断至 ~{token_budget} token 预算)"
    return output


def read_article_tldrs(
    G: nx.Graph,
    visited_nodes: set[str],
    wiki_dir: Path,
    max_tldrs: int = 10,
) -> list[dict]:
    """Token-saving helper: read only the `tldr` field from article frontmatter
    for each visited article node. Use this BEFORE reading full article content.

    Returns [{"label": ..., "path": ..., "tldr": ...}], ranked by node degree.

    Rationale: reading 10 TL;DRs (~100 字 each ≈ 1K tokens) is much cheaper
    than reading 10 articles (~12K chars each ≈ 40K tokens). The LLM can then
    decide which 2-3 full articles are actually needed for the answer.
    """
    import re
    candidates = []
    for nid in visited_nodes:
        src = G.nodes.get(nid, {}).get("source_file", "")
        if not src or not src.startswith("articles/"):
            continue
        p = wiki_dir / src
        if not p.exists():
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        m = re.search(r'^tldr:\s*"?(.+?)"?\s*$', text, flags=re.MULTILINE)
        tldr = m.group(1).strip() if m else "(无 tldr 字段)"
        label = G.nodes[nid].get("label", p.stem)
        candidates.append({
            "label": label,
            "path": str(p),
            "tldr": tldr,
            "degree_in_visited": sum(
                1 for nbr in G.neighbors(nid) if nbr in visited_nodes
            ),
        })
    candidates.sort(key=lambda c: -c["degree_in_visited"])
    return candidates[:max_tldrs]


def find_relevant_wiki_pages(
    G: nx.Graph,
    visited_nodes: set[str],
    wiki_dir: Path,
    max_pages: int = 6,
    start_nodes: list[str] | None = None,
) -> list[Path]:
    """Find wiki pages relevant to the visited subgraph.

    Ranking signals (higher = more relevant):
    1. Bonus if the node is one of the BFS start_nodes (top-scored by
       score_nodes) — these match the query keywords directly and should
       almost always appear in results, even if their subgraph_degree is
       modest.
    2. Subgraph degree — how many visited nodes this node connects to.
       High-degree nodes sit at the centre of the retrieved subgraph.

    Budget split: half concepts, half articles. Leftover quota flows to the
    other side so max_pages is always fully used when candidates exist.
    """
    starts = set(start_nodes or [])
    START_BONUS = 10_000  # ensures start_nodes rank above any subgraph_degree

    concept_candidates: list[tuple[int, Path]] = []
    article_candidates: list[tuple[int, Path]] = []
    visited_set = set(visited_nodes)

    for nid in visited_nodes:
        source = G.nodes.get(nid, {}).get("source_file", "")
        if not source:
            continue
        p = wiki_dir / source
        if not p.exists():
            continue
        subgraph_degree = sum(
            1 for nbr in G.neighbors(nid) if nbr in visited_set
        )
        score = subgraph_degree + (START_BONUS if nid in starts else 0)
        if source.startswith("concepts/"):
            concept_candidates.append((score, p))
        elif source.startswith("articles/"):
            article_candidates.append((score, p))

    concept_candidates.sort(key=lambda x: (-x[0], str(x[1])))
    article_candidates.sort(key=lambda x: (-x[0], str(x[1])))

    concept_quota = max_pages // 2
    article_quota = max_pages - concept_quota

    concept_take = min(concept_quota, len(concept_candidates))
    article_take = min(article_quota, len(article_candidates))
    leftover = (concept_quota - concept_take) + (article_quota - article_take)
    if leftover > 0:
        if concept_take < len(concept_candidates):
            concept_take = min(len(concept_candidates), concept_take + leftover)
        elif article_take < len(article_candidates):
            article_take = min(len(article_candidates), article_take + leftover)

    pages: list[Path] = []
    pages.extend(p for _, p in article_candidates[:article_take])
    pages.extend(p for _, p in concept_candidates[:concept_take])
    return pages[:max_pages]


def trace_to_source(article_path: Path, kb_root: Path) -> Path | None:
    """Trace an article back to its original content.md via source_sha256.

    Three-layer query chain:
    1. Article (structured summary) → fast navigation
    2. content.md (full text) → detailed information
    3. original file + assets/ → images, charts

    Returns path to content.md, or None if not found.
    """
    if not article_path.exists():
        return None

    # Parse source_sha256 from article frontmatter
    text = article_path.read_text(encoding="utf-8", errors="replace")
    sha = ""
    if text.startswith("---"):
        try:
            fm_end = text.index("---", 3)
            fm_block = text[3:fm_end]
            for line in fm_block.split("\n"):
                if line.strip().startswith("source_sha256:"):
                    sha = line.split(":", 1)[1].strip().strip('"').strip("'")
                    break
        except ValueError:
            pass

    if not sha:
        return None

    # Search archive for matching content.md
    archive_dir = kb_root / "raw" / "archive"
    if not archive_dir.exists():
        return None

    # Search source_map.json first (fast lookup)
    source_map_path = kb_root / "vault" / "meta" / "source_map.json"
    if source_map_path.exists():
        try:
            smap = json.loads(source_map_path.read_text(encoding="utf-8"))
            if sha in smap:
                raw_path = smap[sha].get("raw_path", "")
                candidate = kb_root / raw_path
                if candidate.is_dir():
                    content_md = candidate / "content.md"
                    if content_md.exists():
                        return content_md
        except Exception:
            pass

    # Fallback: scan archive directories
    for content_md in archive_dir.rglob("content.md"):
        return content_md

    return None


def save_query_result(
    question: str,
    answer: str,
    mode: str,
    answer_nodes: list[str],
    satisfied: bool,
    took_ms: int,
    memory_dir: Path,
) -> Path:
    """Save Q&A result to memory/ for feedback loop.

    The graph skill will consume these files on next update,
    extracting co_queried relationships.
    """
    from datetime import datetime, timezone
    import hashlib

    now = datetime.now(timezone.utc)
    query_hash = hashlib.sha256(question.encode()).hexdigest()[:8]
    filename = f"query_{now.strftime('%Y%m%d_%H%M%S')}.md"

    content = f"""---
type: query_answer
question: "{question}"
mode: {mode}
answer_nodes: {json.dumps(answer_nodes, ensure_ascii=False)}
satisfied: {str(satisfied).lower()}
date: {now.isoformat()}
query_hash: "{query_hash}"
took_ms: {took_ms}
---

{answer}
"""
    memory_dir.mkdir(parents=True, exist_ok=True)
    out_path = memory_dir / filename
    out_path.write_text(content, encoding="utf-8")
    return out_path
