"""Schema validation for lcwiki extractions.

This is stricter than graphify's generic schema validator. Enforces the
label/file_type/source_file rules that lcwiki's downstream graph quality
depends on.

Two modes:
  strict=True  -> raise ValueError on any issue (use in CI or new pipelines)
  strict=False -> return issue list, let caller decide (default in /lcwiki graph)

The caller typically prints issues as warnings, runs consolidate_by_source_file
to fix id/label problems where possible, then proceeds. Remaining issues
are carried into the run report so the user can see the data quality trend.
"""

from __future__ import annotations

import re


_ID_LIKE = re.compile(
    r"^(concept|solution|document|article|region|customer)[_:].+",
    re.IGNORECASE,
)


def _looks_like_id(label: str, node_id: str) -> bool:
    if not label:
        return False
    if label == node_id:
        return True
    if _ID_LIKE.match(label):
        return True
    return False


def validate_extraction_schema(
    extraction: dict,
    *,
    strict: bool = False,
    allowed_file_types: set[str] | None = None,
) -> list[str]:
    """Validate lcwiki-specific schema. Returns issue strings.

    Rules enforced on nodes:
      - non-empty id
      - id unique within the extraction
      - non-empty label
      - label is NOT in id-form (e.g. "concept_xxx" or "solution:abc")
      - non-empty file_type
      - file_type in allowed_file_types (if provided)

    Rules enforced on edges:
      - source + target present and referenceable in nodes
      - no self-loops (source == target)
      - confidence_score present and in [0, 1]

    Rules enforced on hyperedges:
      - member_count >= 2
      - all members exist in nodes

    If strict=True and issues are non-empty, raises ValueError.
    Otherwise returns the list for the caller to print/log/store.
    """
    issues: list[str] = []
    nodes = extraction.get("nodes", [])
    edges = extraction.get("edges", [])
    hyperedges = extraction.get("hyperedges", [])

    seen_ids: set[str] = set()
    for i, node in enumerate(nodes):
        nid = node.get("id", "")
        label = node.get("label", "")
        ftype = node.get("file_type", "")

        if not nid:
            issues.append(f"node#{i}: missing 'id'")
            continue
        if nid in seen_ids:
            issues.append(f"node id={nid!r}: duplicate id")
        seen_ids.add(nid)

        if not label:
            issues.append(f"node id={nid!r}: missing/empty 'label'")
        elif _looks_like_id(label, nid):
            issues.append(
                f"node id={nid!r}: label {label!r} looks like an id — "
                "expected human-readable name from source file"
            )

        if not ftype:
            issues.append(f"node id={nid!r}: missing 'file_type'")
        elif allowed_file_types and ftype not in allowed_file_types:
            issues.append(
                f"node id={nid!r}: file_type {ftype!r} not in allowed "
                f"{sorted(allowed_file_types)}"
            )

    for i, edge in enumerate(edges):
        s = edge.get("source") or edge.get("from")
        t = edge.get("target") or edge.get("to")
        if not s or not t:
            issues.append(f"edge#{i}: missing source or target")
            continue
        if s == t:
            issues.append(f"edge#{i} {s!r}->{t!r}: self-loop")
            continue
        if s not in seen_ids:
            issues.append(f"edge#{i} {s!r}->{t!r}: source not in node set")
        if t not in seen_ids:
            issues.append(f"edge#{i} {s!r}->{t!r}: target not in node set")

        score = edge.get("confidence_score")
        if score is None:
            issues.append(
                f"edge#{i} {s!r}->{t!r}: missing 'confidence_score'"
            )
        else:
            try:
                f = float(score)
                if not (0.0 <= f <= 1.0):
                    issues.append(
                        f"edge#{i} {s!r}->{t!r}: confidence_score {f} "
                        "out of [0,1]"
                    )
            except (TypeError, ValueError):
                issues.append(
                    f"edge#{i} {s!r}->{t!r}: confidence_score {score!r} "
                    "not a number"
                )

    for i, he in enumerate(hyperedges):
        members = he.get("members") or []
        if len(members) < 2:
            issues.append(
                f"hyperedge#{i} {he.get('label', he.get('id', ''))}: "
                f"fewer than 2 members"
            )
        for m in members:
            if m not in seen_ids:
                issues.append(
                    f"hyperedge#{i}: member {m!r} not in node set"
                )

    if strict and issues:
        head = "; ".join(issues[:3])
        raise ValueError(
            f"schema validation failed ({len(issues)} issues). First: {head}"
        )
    return issues


def summarize_issues(issues: list[str]) -> dict:
    """Bucket issues by category for reporting."""
    buckets: dict[str, int] = {
        "missing_label": 0,
        "label_is_id_form": 0,
        "missing_file_type": 0,
        "duplicate_id": 0,
        "missing_confidence": 0,
        "bad_confidence_range": 0,
        "dangling_edge": 0,
        "self_loop": 0,
        "bad_hyperedge": 0,
        "other": 0,
    }
    for issue in issues:
        if "missing/empty 'label'" in issue:
            buckets["missing_label"] += 1
        elif "looks like an id" in issue:
            buckets["label_is_id_form"] += 1
        elif "missing 'file_type'" in issue or "file_type" in issue and "not in allowed" in issue:
            buckets["missing_file_type"] += 1
        elif "duplicate id" in issue:
            buckets["duplicate_id"] += 1
        elif "missing 'confidence_score'" in issue:
            buckets["missing_confidence"] += 1
        elif "confidence_score" in issue and "out of [0,1]" in issue:
            buckets["bad_confidence_range"] += 1
        elif "not in node set" in issue:
            buckets["dangling_edge"] += 1
        elif "self-loop" in issue:
            buckets["self_loop"] += 1
        elif "hyperedge" in issue:
            buckets["bad_hyperedge"] += 1
        else:
            buckets["other"] += 1
    return {k: v for k, v in buckets.items() if v > 0}
