"""Post-`graph-run` output verifier.

Checks that `/lcwiki graph` produced every required artifact. Purpose: detect
when the upstream agent hand-crafted files instead of calling `lcwiki
graph-run` (e.g. writing a forged `index.html` or `.xxx_llm_<ts>.ext`
shadow file), and refuse to proceed when the graph is incomplete.

Invariants verified:
- required files exist and are non-empty
- graph.json has the networkx node_link_data shape (nodes with file_type,
  edges with relation in the allowed set)
- nav/index.md + at least one community-*.md exist
- no files outside the whitelist live directly under vault/graph/ (catches
  the "forged index.html" pattern)

Exits non-zero + prints a structured FAILED: report on any violation.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ALLOWED_GRAPH_FILES = {
    "graph.json",
    "graph.html",
    "graph_index.json",
    "GRAPH_REPORT_SUMMARY.md",
    "GRAPH_REPORT_FULL.md",
}

ALLOWED_GRAPH_DIRS = {"cache", "obsidian"}

ALLOWED_RELATIONS = {
    "applied_to",
    "references",
    "includes_module",
    "semantically_similar_to",
    "triggered_by",
    "provides",
    "uses",
    "depends_on",
    "part_of",
    "example_of",
}

MIN_NAV_COMMUNITY_PAGES = 1


def _fail(msg: str) -> None:
    print(f"FAILED: {msg}", file=sys.stderr)


def verify(kb: Path) -> list[str]:
    errors: list[str] = []
    graph_dir = kb / "vault" / "graph"
    nav_dir = kb / "vault" / "wiki" / "nav"

    if not graph_dir.exists():
        errors.append(f"graph dir missing: {graph_dir}")
        return errors

    for fname in ("graph.json", "graph.html", "GRAPH_REPORT_SUMMARY.md", "GRAPH_REPORT_FULL.md"):
        p = graph_dir / fname
        if not p.exists():
            errors.append(f"required file missing: vault/graph/{fname}")
        elif p.stat().st_size == 0:
            errors.append(f"required file empty: vault/graph/{fname}")

    extras = []
    for entry in graph_dir.iterdir():
        if entry.name.startswith("."):
            continue
        if entry.is_dir():
            if entry.name not in ALLOWED_GRAPH_DIRS:
                extras.append(entry.name + "/")
            continue
        if entry.name not in ALLOWED_GRAPH_FILES:
            extras.append(entry.name)
    if extras:
        errors.append(
            "forbidden extra files in vault/graph/ "
            f"(whitelist: {sorted(ALLOWED_GRAPH_FILES)}; extras: {extras}). "
            "If these were hand-crafted by an LLM, delete them and rerun `lcwiki graph-run`."
        )

    gj = graph_dir / "graph.json"
    if gj.exists() and gj.stat().st_size > 0:
        try:
            data = json.loads(gj.read_text(encoding="utf-8"))
        except Exception as e:
            errors.append(f"graph.json is not valid JSON: {e}")
        else:
            nodes = data.get("nodes", [])
            links = data.get("links", data.get("edges", []))
            if not isinstance(nodes, list) or not nodes:
                errors.append("graph.json has no nodes")
            if not isinstance(links, list):
                errors.append("graph.json links/edges is not a list")
            if nodes:
                sample = nodes[0]
                missing_keys = [k for k in ("id", "label", "file_type") if k not in sample]
                if missing_keys:
                    errors.append(
                        f"graph.json node missing keys {missing_keys} (hand-crafted schema?); "
                        f"sample: {json.dumps(sample, ensure_ascii=False)[:200]}"
                    )
            bad_rels = set()
            for e in (links or []):
                rel = e.get("relation") or e.get("label")
                if rel and rel not in ALLOWED_RELATIONS:
                    bad_rels.add(rel)
            if bad_rels:
                errors.append(
                    f"graph.json contains forbidden relations {sorted(bad_rels)}; "
                    f"allowed: {sorted(ALLOWED_RELATIONS)}"
                )

    if not nav_dir.exists():
        errors.append(f"nav dir missing: {nav_dir}")
    else:
        if not (nav_dir / "index.md").exists():
            errors.append("nav/index.md missing")
        # to_wiki() names files '<label>.md' using _safe_filename (which only
        # swaps '/', ' ', ':'). Page count should be >= 1 (at least one
        # community or god-node article).
        page_count = sum(1 for p in nav_dir.glob("*.md") if p.name != "index.md")
        if page_count < MIN_NAV_COMMUNITY_PAGES:
            errors.append(
                f"nav/ has {page_count} article pages (expected >= {MIN_NAV_COMMUNITY_PAGES}); "
                "was to_wiki() actually run?"
            )
        # Forgery signal: filenames containing markdown syntax chars mean the
        # Step-2 extraction produced a garbage 'label' (e.g. an image tag
        # '![img-003](assets/images/img-003.png)' was captured as a node label,
        # and to_wiki faithfully turned it into a filename).
        bad_chars = set("![]()<>`")
        for entry in nav_dir.iterdir():
            if not entry.is_file():
                continue
            stem = entry.stem
            if any(c in stem for c in bad_chars):
                errors.append(
                    f"nav/ has malformed filename '{entry.name}' (contains markdown/html syntax); "
                    "Step-2 extraction produced a garbage label — fix extraction then rerun `lcwiki graph-run`"
                )
            elif len(stem) > 120:
                errors.append(
                    f"nav/ has abnormally long filename '{entry.name[:60]}...' "
                    "(>120 chars, likely captured a whole sentence as a label)"
                )

    return errors


def main(argv: list[str]) -> int:
    kb: Path | None = None
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--kb":
            kb = Path(argv[i + 1])
            i += 2
        else:
            print(f"error: unknown flag '{a}'", file=sys.stderr)
            return 2

    if kb is None:
        print("usage: lcwiki graph-verify --kb KB_PATH", file=sys.stderr)
        return 2
    if not kb.exists():
        print(f"error: kb path does not exist: {kb}", file=sys.stderr)
        return 1

    errors = verify(kb)
    if errors:
        print(f"❌ graph verification FAILED — {len(errors)} problem(s):")
        for e in errors:
            _fail(e)
        print("\n⚠️ Do NOT hand-craft missing files. Rerun `lcwiki graph-run` after fixing Step 2.")
        return 1

    print("✅ graph verification passed — all required artifacts present and well-formed.")
    return 0
