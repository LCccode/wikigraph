"""Alias-driven node merging for lcwiki graph construction.

Merges nodes whose labels (or aliases parsed from concepts_index summary)
point to the same canonical concept. Also fixes a compile-time bug: aliases
that live only in summary text like "(别名: X, Y)" instead of the aliases array.

Why: without this merge, the LLM can emit `concept_ai_jiaoshi_zhushou`,
`concept_xinghuo_jiaoshi_zhushou`, and `concept_beishouke_jiaoshi_zhushou`
as separate nodes even though they are aliases of the same concept
"备授课教师助手". That fragments communities and hides real relationships.

How to apply: call in /lcwiki graph pipeline after LLM extraction and
before build_graph(). Reads vault/meta/concepts_index.json and rewrites
the extraction dict in place.
"""

import re
from pathlib import Path


_ALIAS_PATTERN = re.compile(
    r"[（(]\s*(?:别名|aka|also\s+known\s+as|a\.k\.a\.?)\s*[:：]\s*([^)）]+)[)）]",
    re.IGNORECASE,
)
_NON_WORD = re.compile(r"[^\w\u4e00-\u9fff]+")


def find_orphan_concepts(
    extraction: dict,
    concepts_dir: Path,
) -> list[dict]:
    """Find suspicious nodes: no backing .md file AND degree 0 AND no hyperedge.

    Returns a list of candidate dicts (NOT modifying extraction). Each entry:
        {"id": str, "label": str, "file_type": str, "reason": str}

    This is the "nothing-connects-to-it and nothing-backs-it" heuristic. It
    does NOT delete anything — the /lcwiki audit command feeds these candidates
    to an LLM for semantic judgment (is it a real orphan to remove, or a
    legitimate standalone that should stay?).

    Safe to call on any file_type, any domain, any kb layout. Nodes with a
    backing file, or with any edge, or in a hyperedge are never flagged —
    they always have information value.
    """
    if not concepts_dir.exists():
        return []

    existing_labels: set[str] = {p.stem for p in concepts_dir.glob("*.md")}

    degree: dict[str, int] = {}
    for edge in extraction.get("edges", []):
        s = edge.get("source") or edge.get("from") or ""
        t = edge.get("target") or edge.get("to") or ""
        if s:
            degree[s] = degree.get(s, 0) + 1
        if t:
            degree[t] = degree.get(t, 0) + 1
    for he in extraction.get("hyperedges", []):
        for m in he.get("members", []):
            degree[m] = degree.get(m, 0) + 1

    candidates: list[dict] = []
    for node in extraction.get("nodes", []):
        ftype = node.get("file_type", "")
        label = (node.get("label") or "").strip()
        src = node.get("source_file") or ""
        nid = node.get("id", "")

        has_file = bool(src) or (label in existing_labels)
        is_isolated = degree.get(nid, 0) == 0

        if not has_file and is_isolated:
            candidates.append({
                "id": nid,
                "label": label,
                "file_type": ftype,
                "reason": "no backing file AND degree 0 AND not in any hyperedge",
            })

    return candidates


def _auto_heal_source_file(node: dict, kb_root=None) -> dict:
    """Fix common subagent bugs in source_file + file_type consistency.

    Observed failure modes (from real OpenClaw subagent output):
    - source_file = "XXX.md" without the "concepts/" or "articles/" prefix
    - file_type="document" but source_file points at concepts/XXX.md (or vice
      versa) — LLM inferred from the label meaning, ignoring the directory

    Healing strategy (domain-agnostic, safe under all kb_path layouts):
    1. If source_file has a directory prefix (concepts/ or articles/), trust
       the directory over file_type — set file_type to match the directory.
    2. If source_file has NO prefix, use file_type to decide which to add:
         file_type="concept"  → prepend "concepts/"
         file_type="document" → prepend "articles/"
         file_type missing    → try both: prefer the one that exists on disk
           (if kb_root given); otherwise leave alone.
    3. If kb_root is provided, verify the resulting source_file exists on disk;
       if not, try the opposite directory as a fallback, then accept what we
       have even if missing (let validate_extraction_schema flag it).

    Returns a new node dict (does not mutate input). If no change needed, the
    returned dict equals input.
    """
    from pathlib import Path as _P

    node = dict(node)
    src = node.get("source_file") or ""
    ftype = node.get("file_type") or ""

    if not src:
        return node

    normalized = src.replace("\\", "/")

    # Case 1: already has a valid directory prefix — trust the directory
    if normalized.startswith("concepts/") or normalized.startswith("articles/"):
        # Fix file_type if it contradicts the directory
        want = "concept" if normalized.startswith("concepts/") else "document"
        if ftype and ftype != want:
            node["file_type"] = want
        elif not ftype:
            node["file_type"] = want
        node["source_file"] = normalized
        return node

    # Case 2: no directory prefix — need to decide where it goes
    candidate_concept = f"concepts/{normalized}"
    candidate_article = f"articles/{normalized}"

    if ftype == "concept":
        node["source_file"] = candidate_concept
    elif ftype == "document":
        node["source_file"] = candidate_article
    elif kb_root:
        # No file_type hint — probe disk
        concepts_path = _P(kb_root) / "vault" / "wiki" / candidate_concept
        articles_path = _P(kb_root) / "vault" / "wiki" / candidate_article
        if concepts_path.exists():
            node["source_file"] = candidate_concept
            node["file_type"] = "concept"
        elif articles_path.exists():
            node["source_file"] = candidate_article
            node["file_type"] = "document"
    # else: leave source_file as-is; schema validator will complain

    # Case 3: if kb_root given and we picked a path, verify it exists; try the
    # other directory if not (common when LLM gets file_type wrong).
    if kb_root:
        chosen = node.get("source_file", "")
        if chosen:
            chosen_path = _P(kb_root) / "vault" / "wiki" / chosen
            if not chosen_path.exists():
                # Try the other directory
                if chosen.startswith("concepts/"):
                    alt = "articles/" + chosen[len("concepts/"):]
                    alt_path = _P(kb_root) / "vault" / "wiki" / alt
                    if alt_path.exists():
                        node["source_file"] = alt
                        node["file_type"] = "document"
                elif chosen.startswith("articles/"):
                    alt = "concepts/" + chosen[len("articles/"):]
                    alt_path = _P(kb_root) / "vault" / "wiki" / alt
                    if alt_path.exists():
                        node["source_file"] = alt
                        node["file_type"] = "concept"

    return node


def consolidate_by_source_file(extraction: dict, kb_root=None) -> tuple[dict, dict[str, str]]:
    """Merge nodes that share the same source_file, and backfill missing labels.

    Why: different subagents often assign different id conventions for the
    same source file (e.g. `concept_xxx_pinyin` from one chunk,
    `concept:中文名` from another). After id-level dedup these still remain
    as two separate nodes pointing to one file — which is wrong. This
    collapses them into one canonical node per source_file.

    Also backfills `label` from source_file stem when missing. This is
    domain-agnostic: it works for any kb_path, any file naming, any LLM
    subagent output style.

    If `kb_root` is given, ALSO auto-heal source_file prefix and file_type
    consistency before grouping — catching the common subagent bug where
    source_file lacks a "concepts/" or "articles/" prefix, or file_type
    contradicts the directory. See `_auto_heal_source_file` for rules.

    Returns (consolidated_extraction, id_redirect) where id_redirect is
    {old_id: canonical_id} for any redirected node.
    """
    from pathlib import Path as _P

    # Auto-heal each node's source_file + file_type before grouping
    raw_nodes = extraction.get("nodes", [])
    healed_nodes = [_auto_heal_source_file(n, kb_root=kb_root) for n in raw_nodes]

    # Group nodes by source_file (only nodes that HAVE a source_file)
    by_source: dict[str, list[dict]] = {}
    no_source: list[dict] = []
    for node in healed_nodes:
        src = node.get("source_file") or ""
        if src:
            by_source.setdefault(src, []).append(node)
        else:
            no_source.append(node)

    id_redirect: dict[str, str] = {}
    kept_nodes: list[dict] = []

    for src, nodes in by_source.items():
        # Pick canonical id: prefer one that already has a non-empty label
        canonical = None
        for n in nodes:
            if n.get("label"):
                canonical = n
                break
        if canonical is None:
            canonical = nodes[0]

        canonical_id = canonical.get("id", "")

        canonical = dict(canonical)

        # Ensure label — derive from file stem if still missing
        if not canonical.get("label"):
            canonical["label"] = _P(src).stem

        # Ensure file_type — infer from source_file path if missing
        if not canonical.get("file_type"):
            src_lower = src.replace("\\", "/").lower()
            if "concepts/" in src_lower:
                canonical["file_type"] = "concept"
            elif "articles/" in src_lower:
                canonical["file_type"] = "document"

        # Record redirects for the other nodes
        for n in nodes:
            if n is canonical:
                continue
            nid = n.get("id", "")
            if nid and nid != canonical_id:
                id_redirect[nid] = canonical_id

        kept_nodes.append(canonical)

    # Nodes without source_file: keep as-is but ensure label (fall back to id)
    for node in no_source:
        if not node.get("label"):
            node = dict(node)
            node["label"] = node.get("id", "")
        kept_nodes.append(node)

    # Rewrite edges
    new_edges = []
    seen_keys: set[tuple[str, str, str]] = set()
    for edge in extraction.get("edges", []):
        s = edge.get("source") or edge.get("from") or ""
        t = edge.get("target") or edge.get("to") or ""
        s2 = id_redirect.get(s, s)
        t2 = id_redirect.get(t, t)
        if not s2 or not t2 or s2 == t2:
            continue
        key = (s2, t2, edge.get("relation", ""))
        if key in seen_keys:
            continue
        seen_keys.add(key)
        new_edge = dict(edge)
        new_edge["source"] = s2
        new_edge["target"] = t2
        new_edges.append(new_edge)

    new_hyper = []
    for he in extraction.get("hyperedges", []):
        members = [id_redirect.get(m, m) for m in he.get("members", [])]
        # de-dup members preserving order
        seen = set()
        deduped = []
        for m in members:
            if m not in seen:
                seen.add(m)
                deduped.append(m)
        if len(deduped) < 2:
            continue
        new_he = dict(he)
        new_he["members"] = deduped
        new_he["member_count"] = len(deduped)
        new_hyper.append(new_he)

    return {"nodes": kept_nodes, "edges": new_edges, "hyperedges": new_hyper}, id_redirect


def find_duplicate_concept_files(
    concepts_dir: Path,
    concepts_index: dict,
    graph_path: Path | None = None,
    semantic_threshold: float = 0.85,
) -> list[dict]:
    """Find concept .md files that may be duplicates/synonyms of each other.

    Two detection channels, both returned together:

    1. **Alias channel** (high precision): stem matches an alias of a
       different canonical concept in concepts_index.
    2. **Graph-similarity channel** (optional, high recall): if graph_path
       is given, also flag pairs connected by a `semantically_similar_to`
       edge with confidence_score >= semantic_threshold. LLM/user must
       review — not every high-similarity pair is a true merge candidate.

    Returns list of:
        {"canonical_name": str,
         "canonical_file": str,
         "duplicate_files": [filename, ...],
         "reason": str,
         "source": "aliases" | "graph_semantic" }

    Grouped so the user can confirm or reject each cluster at once.
    """
    if not concepts_dir.exists():
        return []

    canonical_map = build_canonical_map(concepts_index)
    existing_stems: set[str] = {p.stem for p in concepts_dir.glob("*.md")}

    # Channel 1: aliases
    alias_groups: dict[str, set[str]] = {}
    for stem in existing_stems:
        canonical = canonical_map.get(stem.lower())
        if canonical and canonical != stem:
            alias_groups.setdefault(canonical, set()).add(stem)

    # Channel 2: graph semantic edges (optional)
    graph_groups: dict[str, set[str]] = {}
    if graph_path and graph_path.exists():
        try:
            import json as _json
            gdata = _json.loads(graph_path.read_text(encoding="utf-8"))
            nodes_by_id = {n.get("id"): n for n in gdata.get("nodes", [])}
            for edge in gdata.get("links", []):
                if edge.get("relation") != "semantically_similar_to":
                    continue
                score = edge.get("confidence_score", 0.0)
                try:
                    score = float(score)
                except (TypeError, ValueError):
                    continue
                if score < semantic_threshold:
                    continue
                src_lbl = nodes_by_id.get(edge.get("source"), {}).get("label", "")
                tgt_lbl = nodes_by_id.get(edge.get("target"), {}).get("label", "")
                if not src_lbl or not tgt_lbl:
                    continue
                if src_lbl not in existing_stems or tgt_lbl not in existing_stems:
                    continue
                # Pick the shorter label as canonical (often closer to root name)
                canonical, dup = sorted([src_lbl, tgt_lbl], key=len)
                if canonical == dup:
                    continue
                # Avoid duplicates already surfaced via aliases
                if dup in alias_groups.get(canonical, set()):
                    continue
                graph_groups.setdefault(canonical, set()).add(dup)
        except Exception:
            pass

    result: list[dict] = []
    for canonical, duplicates in alias_groups.items():
        canonical_file = f"{canonical}.md" if canonical in existing_stems else "(missing)"
        result.append({
            "canonical_name": canonical,
            "canonical_file": canonical_file,
            "duplicate_files": sorted(f"{d}.md" for d in duplicates),
            "reason": f"stems match aliases of '{canonical}'",
            "source": "aliases",
        })
    for canonical, duplicates in graph_groups.items():
        canonical_file = f"{canonical}.md" if canonical in existing_stems else "(missing)"
        result.append({
            "canonical_name": canonical,
            "canonical_file": canonical_file,
            "duplicate_files": sorted(f"{d}.md" for d in duplicates),
            "reason": f"graph semantically_similar_to edge ≥ {semantic_threshold}",
            "source": "graph_semantic",
        })
    return sorted(result, key=lambda g: -len(g["duplicate_files"]))


def apply_orphan_removal(extraction: dict, removal_ids: list[str]) -> dict:
    """Execute removal decisions from an audit review. Input a list of node
    ids (typically an LLM-reviewed subset of find_orphan_concepts candidates).

    Returns a new extraction with those nodes and any edges touching them
    removed. Hyperedges that drop below 2 members are also pruned.
    """
    rs = set(removal_ids)
    kept_nodes = [n for n in extraction.get("nodes", []) if n.get("id") not in rs]
    kept_edges = []
    for edge in extraction.get("edges", []):
        s = edge.get("source") or edge.get("from") or ""
        t = edge.get("target") or edge.get("to") or ""
        if s in rs or t in rs:
            continue
        kept_edges.append(edge)
    kept_hyper = []
    for he in extraction.get("hyperedges", []):
        members = [m for m in he.get("members", []) if m not in rs]
        if len(members) < 2:
            continue
        new_he = dict(he)
        new_he["members"] = members
        new_he["member_count"] = len(members)
        kept_hyper.append(new_he)
    return {"nodes": kept_nodes, "edges": kept_edges, "hyperedges": kept_hyper}


def parse_aliases_from_summary(summary: str) -> list[str]:
    """Extract aliases from summary ending with '(别名: A, B)' or '（别名：A、B）'."""
    if not summary:
        return []
    m = _ALIAS_PATTERN.search(summary)
    if not m:
        return []
    raw = m.group(1)
    parts = re.split(r"[,，、;；]", raw)
    return [p.strip() for p in parts if p.strip()]


def backfill_aliases_from_summary(concepts_index: dict) -> int:
    """Populate empty aliases[] from summary '(别名: …)'. Returns count fixed."""
    fixed = 0
    for info in concepts_index.values():
        if info.get("aliases"):
            continue
        parsed = parse_aliases_from_summary(info.get("summary", ""))
        if parsed:
            info["aliases"] = parsed
            fixed += 1
    return fixed


def build_canonical_map(concepts_index: dict) -> dict[str, str]:
    """Build {label_or_alias (lowercase) → canonical_concept_name}."""
    mapping: dict[str, str] = {}
    for concept_name, info in concepts_index.items():
        mapping[concept_name.lower()] = concept_name
        for a in info.get("aliases", []) or []:
            if a:
                mapping[a.lower()] = concept_name
        for a in parse_aliases_from_summary(info.get("summary", "")):
            if a:
                mapping.setdefault(a.lower(), concept_name)
    return mapping


def _pick_canonical_id(
    extraction: dict,
    canonical_map: dict[str, str],
) -> dict[str, str]:
    """First pass: decide canonical node id for each canonical concept name.

    Rule: if any node's label exactly equals the canonical name, use that
    node's id. Otherwise, use the first-seen node's id whose label maps to
    this canonical name.
    """
    first_seen: dict[str, str] = {}
    exact_match: dict[str, str] = {}
    for node in extraction.get("nodes", []):
        nid = node.get("id", "")
        label = (node.get("label") or "").strip()
        ftype = node.get("file_type", "")
        if ftype != "concept" or not label or not nid:
            continue
        cname = canonical_map.get(label.lower())
        if not cname:
            continue
        first_seen.setdefault(cname, nid)
        if label == cname:
            exact_match.setdefault(cname, nid)
    return {cname: exact_match.get(cname, nid) for cname, nid in first_seen.items()}


def merge_extraction_by_aliases(
    extraction: dict,
    concepts_index: dict,
) -> tuple[dict, dict[str, str]]:
    """Merge concept nodes that are aliases of the same canonical concept.

    Returns (merged_extraction, id_redirect) where id_redirect is
    {old_id: canonical_id} for every node that got redirected.

    Only concept nodes (file_type=="concept") participate in merging.
    Document/solution nodes keep their original ids. The canonical id is
    picked from existing node ids (preferring the node whose label equals
    the canonical name), so we don't need to agree with the LLM's id
    naming convention.
    """
    canonical_map = build_canonical_map(concepts_index)
    canonical_to_id = _pick_canonical_id(extraction, canonical_map)

    id_redirect: dict[str, str] = {}
    kept_nodes: dict[str, dict] = {}

    for node in extraction.get("nodes", []):
        nid = node.get("id", "")
        label = (node.get("label") or "").strip()
        ftype = node.get("file_type", "")

        if ftype == "concept" and label:
            cname = canonical_map.get(label.lower())
            if cname and cname in canonical_to_id:
                cid = canonical_to_id[cname]
                if nid != cid:
                    id_redirect[nid] = cid
                if cid not in kept_nodes:
                    new_node = dict(node)
                    new_node["id"] = cid
                    new_node["label"] = cname
                    new_node.setdefault("aliases_ids", [])
                    if nid and nid != cid and nid not in new_node["aliases_ids"]:
                        new_node["aliases_ids"].append(nid)
                    kept_nodes[cid] = new_node
                else:
                    existing = kept_nodes[cid]
                    existing.setdefault("aliases_ids", [])
                    if nid and nid != cid and nid not in existing["aliases_ids"]:
                        existing["aliases_ids"].append(nid)
                continue

        if nid and nid not in kept_nodes:
            kept_nodes[nid] = node

    new_edges = []
    seen_edges: set[tuple[str, str, str]] = set()
    for edge in extraction.get("edges", []):
        src = edge.get("source") or edge.get("from")
        tgt = edge.get("target") or edge.get("to")
        if not src or not tgt:
            continue
        src2 = id_redirect.get(src, src)
        tgt2 = id_redirect.get(tgt, tgt)
        if src2 == tgt2:
            continue
        rel = edge.get("relation", "")
        key = (src2, tgt2, rel)
        if key in seen_edges:
            continue
        seen_edges.add(key)
        new_edge = dict(edge)
        new_edge["source"] = src2
        new_edge["target"] = tgt2
        new_edges.append(new_edge)

    new_hyperedges = []
    for he in extraction.get("hyperedges", []):
        members = [id_redirect.get(m, m) for m in he.get("members", [])]
        seen: set[str] = set()
        deduped = []
        for m in members:
            if m not in seen:
                deduped.append(m)
                seen.add(m)
        new_he = dict(he)
        new_he["members"] = deduped
        new_he["member_count"] = len(deduped)
        new_hyperedges.append(new_he)

    merged = {
        "nodes": list(kept_nodes.values()),
        "edges": new_edges,
        "hyperedges": new_hyperedges,
    }
    return merged, id_redirect
